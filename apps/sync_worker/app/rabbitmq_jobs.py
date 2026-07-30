from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import aio_pika
import typer
from aio_pika import DeliveryMode, ExchangeType, Message
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.config import get_settings
from app.db import Database
from app.sync_job_repository import (
    ActiveSyncJobExistsError,
    SyncJobPayloadConflictError,
    SyncJobRepository,
)


JOB_SCHEMA_VERSION = 2

JOB_TYPE_LEGACY = "SYNC_LEGAL_ENTITY"
JOB_TYPE_EXPORT_UPD = "EXPORT_UPD"
JOB_TYPE_PROCESS_UPD = "PROCESS_UPD"
JOB_TYPE_TRACK_VIOLATIONS = "TRACK_VIOLATIONS"

SUPPORTED_JOB_TYPES = {
    JOB_TYPE_LEGACY,
    JOB_TYPE_EXPORT_UPD,
    JOB_TYPE_PROCESS_UPD,
    JOB_TYPE_TRACK_VIOLATIONS,
}

TOKEN_REQUIRED_JOB_TYPES = {
    JOB_TYPE_LEGACY,
    JOB_TYPE_EXPORT_UPD,
    JOB_TYPE_TRACK_VIOLATIONS,
}


@dataclass(
    frozen=True,
    slots=True,
)
class JobTopology:
    queue_name: str
    routing_key: str
    retry_queue_name: str
    retry_routing_key: str
    dead_queue_name: str
    dead_routing_key: str


class PipelineTaskJob(BaseModel):
    """
    Унифицированный контракт RabbitMQ-задания.

    В сообщении отсутствуют токен True API,
    сертификат, PIN и иные секреты.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    schema_version: int = Field(
        default=JOB_SCHEMA_VERSION,
        ge=1,
    )

    job_id: UUID
    job_type: str
    legal_entity_id: int = Field(ge=1)

    parent_job_id: UUID | None = None

    date_from: datetime | None = None
    date_to: datetime | None = None

    skip_edo: bool = False
    force_edo: bool = False
    edo_fail_fast: bool = False
    continue_on_error: bool = False

    retry_count: int = Field(
        default=0,
        ge=0,
    )

    requested_by: str = Field(
        min_length=1,
        max_length=128,
    )

    requested_at: datetime

    @field_validator("job_type", mode="before")
    @classmethod
    def normalize_job_type(cls, value: Any) -> str:
        return str(value or "").strip().upper()

    @model_validator(mode="after")
    def validate_contract(self) -> "PipelineTaskJob":
        prepared_job_type = self.job_type.strip().upper()

        if prepared_job_type not in SUPPORTED_JOB_TYPES:
            raise ValueError(
                "Неподдерживаемый тип задания: "
                f"{prepared_job_type}."
            )

        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from >= self.date_to
        ):
            raise ValueError(
                "date_from должен быть меньше date_to."
            )

        if self.skip_edo and self.force_edo:
            raise ValueError(
                "Параметры skip_edo и force_edo "
                "не могут быть включены одновременно."
            )

        if (
            prepared_job_type == JOB_TYPE_PROCESS_UPD
            and self.parent_job_id is None
        ):
            raise ValueError(
                "Задание PROCESS_UPD должно содержать "
                "parent_job_id задания EXPORT_UPD."
            )

        return self


class RabbitMqPublishResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    status: str
    job_id: str
    message_id: str
    job_type: str
    legal_entity_id: int
    queue: str
    routing_key: str


def _secret_value(value: Any) -> str:
    getter = getattr(
        value,
        "get_secret_value",
        None,
    )

    if callable(getter):
        return str(getter())

    return str(value)


def _parse_optional_datetime(
    value: str | None,
    *,
    option_name: str,
) -> datetime | None:
    if value is None:
        return None

    prepared = value.strip()

    if not prepared:
        return None

    try:
        parsed = datetime.fromisoformat(
            prepared.replace("Z", "+00:00")
        )

    except ValueError as exc:
        raise ValueError(
            f"{option_name} должен быть указан "
            "в формате ISO 8601."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)


def _to_mysql_datetime(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    prepared = value

    if prepared.tzinfo is None:
        prepared = prepared.replace(
            tzinfo=timezone.utc
        )

    return (
        prepared
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def canonical_job_type(job_type: str) -> str:
    prepared = job_type.strip().upper()

    if prepared == JOB_TYPE_LEGACY:
        return JOB_TYPE_EXPORT_UPD

    return prepared


def job_topology(
    settings: Any,
    job_type: str,
    legal_entity_id: int,
) -> JobTopology:
    prepared_type = canonical_job_type(job_type)

    if prepared_type == JOB_TYPE_EXPORT_UPD:
        queue_prefix = settings.rabbitmq_sync_queue
        routing_prefix = settings.rabbitmq_sync_routing_key
        retry_queue_prefix = settings.rabbitmq_retry_queue
        retry_routing_prefix = (
            settings.rabbitmq_retry_routing_key
        )
        dead_queue_prefix = settings.rabbitmq_dead_queue
        dead_routing_prefix = (
            settings.rabbitmq_dead_routing_key
        )

    elif prepared_type == JOB_TYPE_PROCESS_UPD:
        queue_prefix = "gis_mt.jobs.process_upd"
        routing_prefix = "jobs.process_upd"
        retry_queue_prefix = (
            "gis_mt.jobs.process_upd.retry"
        )
        retry_routing_prefix = (
            "jobs.process_upd.retry"
        )
        dead_queue_prefix = (
            "gis_mt.jobs.process_upd.dead"
        )
        dead_routing_prefix = (
            "jobs.process_upd.dead"
        )

    elif prepared_type == JOB_TYPE_TRACK_VIOLATIONS:
        queue_prefix = (
            "gis_mt.jobs.track_violations"
        )
        routing_prefix = (
            "jobs.track_violations"
        )
        retry_queue_prefix = (
            "gis_mt.jobs.track_violations.retry"
        )
        retry_routing_prefix = (
            "jobs.track_violations.retry"
        )
        dead_queue_prefix = (
            "gis_mt.jobs.track_violations.dead"
        )
        dead_routing_prefix = (
            "jobs.track_violations.dead"
        )

    else:
        raise ValueError(
            "Для job_type не определена топология: "
            f"{job_type}."
        )

    suffix = str(legal_entity_id)

    return JobTopology(
        queue_name=f"{queue_prefix}.{suffix}",
        routing_key=f"{routing_prefix}.{suffix}",
        retry_queue_name=(
            f"{retry_queue_prefix}.{suffix}"
        ),
        retry_routing_key=(
            f"{retry_routing_prefix}.{suffix}"
        ),
        dead_queue_name=(
            f"{dead_queue_prefix}.{suffix}"
        ),
        dead_routing_key=(
            f"{dead_routing_prefix}.{suffix}"
        ),
    )


async def declare_job_topology(
    *,
    channel: aio_pika.abc.AbstractChannel,
    settings: Any,
    job_type: str,
    legal_entity_id: int,
) -> tuple[
    aio_pika.abc.AbstractExchange,
    aio_pika.abc.AbstractQueue,
    JobTopology,
]:
    topology = job_topology(
        settings,
        job_type,
        legal_entity_id,
    )

    exchange = await channel.declare_exchange(
        settings.rabbitmq_exchange,
        ExchangeType.DIRECT,
        durable=True,
    )

    queue = await channel.declare_queue(
        topology.queue_name,
        durable=True,
    )

    await queue.bind(
        exchange,
        routing_key=topology.routing_key,
    )

    retry_queue = await channel.declare_queue(
        topology.retry_queue_name,
        durable=True,
        arguments={
            "x-message-ttl": (
                settings.rabbitmq_retry_delay_seconds
                * 1000
            ),
            "x-dead-letter-exchange": (
                settings.rabbitmq_exchange
            ),
            "x-dead-letter-routing-key": (
                topology.routing_key
            ),
        },
    )

    await retry_queue.bind(
        exchange,
        routing_key=topology.retry_routing_key,
    )

    dead_queue = await channel.declare_queue(
        topology.dead_queue_name,
        durable=True,
    )

    await dead_queue.bind(
        exchange,
        routing_key=topology.dead_routing_key,
    )

    return exchange, queue, topology


async def _publish_job_message(
    *,
    settings: Any,
    job: PipelineTaskJob,
) -> RabbitMqPublishResult:
    connection = await aio_pika.connect_robust(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_user,
        password=_secret_value(
            settings.rabbitmq_password
        ),
        virtualhost=settings.rabbitmq_vhost,
        client_properties={
            "connection_name": (
                settings.rabbitmq_connection_name
            ),
        },
        heartbeat=settings.rabbitmq_heartbeat,
        timeout=settings.rabbitmq_timeout,
        fail_fast="1",
    )

    try:
        channel = await connection.channel(
            publisher_confirms=True
        )

        exchange, _, topology = (
            await declare_job_topology(
                channel=channel,
                settings=settings,
                job_type=job.job_type,
                legal_entity_id=(
                    job.legal_entity_id
                ),
            )
        )

        body = json.dumps(
            job.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        message_id = str(job.job_id)

        message = Message(
            body=body,
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id,
            correlation_id=message_id,
            timestamp=datetime.now(timezone.utc),
            type=job.job_type,
            app_id="gis-mt-sync-worker",
            headers={
                "schema_version": job.schema_version,
                "job_type": job.job_type,
                "legal_entity_id": (
                    job.legal_entity_id
                ),
                "retry_count": job.retry_count,
            },
        )

        confirmation = await exchange.publish(
            message,
            routing_key=topology.routing_key,
            mandatory=True,
        )

        if confirmation is False:
            raise RuntimeError(
                "RabbitMQ не подтвердил публикацию задания."
            )

        return RabbitMqPublishResult(
            status="PUBLISHED",
            job_id=message_id,
            message_id=message_id,
            job_type=job.job_type,
            legal_entity_id=job.legal_entity_id,
            queue=topology.queue_name,
            routing_key=topology.routing_key,
        )

    finally:
        await connection.close()


def publish_pipeline_task_job(
    *,
    job_type: str,
    entity_id: int,
    requested_by: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    parent_job_id: UUID | None = None,
    skip_edo: bool = False,
    force_edo: bool = False,
    edo_fail_fast: bool = False,
    continue_on_error: bool = False,
    job_id: UUID | None = None,
) -> RabbitMqPublishResult:
    settings = get_settings()

    prepared_requested_by = requested_by.strip()

    if not prepared_requested_by:
        raise ValueError(
            "requested_by не может быть пустым."
        )

    job = PipelineTaskJob(
        job_id=(job_id or uuid4()),
        job_type=job_type,
        legal_entity_id=entity_id,
        parent_job_id=parent_job_id,
        date_from=date_from,
        date_to=date_to,
        skip_edo=skip_edo,
        force_edo=force_edo,
        edo_fail_fast=edo_fail_fast,
        continue_on_error=continue_on_error,
        retry_count=0,
        requested_by=prepared_requested_by,
        requested_at=datetime.now(timezone.utc),
    )

    payload = job.model_dump(mode="json")

    repository = SyncJobRepository(
        Database(settings)
    )

    registered = repository.register_job(
        job_uuid=str(job.job_id),
        schema_version=job.schema_version,
        job_type=job.job_type,
        parent_job_uuid=(
            str(job.parent_job_id)
            if job.parent_job_id is not None
            else None
        ),
        legal_entity_id=job.legal_entity_id,
        requested_by=job.requested_by,
        requested_at=_to_mysql_datetime(
            job.requested_at
        ),
        date_from=_to_mysql_datetime(job.date_from),
        date_to=_to_mysql_datetime(job.date_to),
        skip_edo=job.skip_edo,
        force_edo=job.force_edo,
        edo_fail_fast=job.edo_fail_fast,
        continue_on_error=job.continue_on_error,
        payload=payload,
        max_retries=settings.rabbitmq_max_retries,
    )

    topology = job_topology(
        settings,
        registered.job_type,
        registered.legal_entity_id,
    )

    if registered.status != "CREATED":
        if registered.status in {
            "PUBLISHED",
            "PROCESSING",
            "RETRY_WAIT",
            "SUCCESS",
        }:
            return RabbitMqPublishResult(
                status=registered.status,
                job_id=registered.job_uuid,
                message_id=(
                    registered.last_message_id
                    or registered.job_uuid
                ),
                job_type=registered.job_type,
                legal_entity_id=(
                    registered.legal_entity_id
                ),
                queue=(
                    registered.queue_name
                    or topology.queue_name
                ),
                routing_key=(
                    registered.routing_key
                    or topology.routing_key
                ),
            )

        raise RuntimeError(
            "Задание уже зарегистрировано "
            "в состоянии, которое не допускает "
            "публикацию: "
            f"status={registered.status}."
        )

    publish_result = asyncio.run(
        _publish_job_message(
            settings=settings,
            job=job,
        )
    )

    repository.mark_published(
        job_uuid=publish_result.job_id,
        queue_name=publish_result.queue,
        routing_key=publish_result.routing_key,
        message_id=publish_result.message_id,
        correlation_id=publish_result.message_id,
    )

    return publish_result


def publish_export_upd_job(
    *,
    entity_id: int,
    date_from: datetime | None,
    date_to: datetime | None,
    requested_by: str,
    continue_on_error: bool = True,
) -> RabbitMqPublishResult:
    return publish_pipeline_task_job(
        job_type=JOB_TYPE_EXPORT_UPD,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        requested_by=requested_by,
        continue_on_error=continue_on_error,
    )


def publish_process_upd_job(
    *,
    entity_id: int,
    parent_job_id: UUID,
    requested_by: str,
) -> RabbitMqPublishResult:
    return publish_pipeline_task_job(
        job_type=JOB_TYPE_PROCESS_UPD,
        entity_id=entity_id,
        parent_job_id=parent_job_id,
        requested_by=requested_by,
        continue_on_error=True,
    )


def publish_track_violations_job(
    *,
    entity_id: int,
    date_from: datetime | None,
    date_to: datetime | None,
    requested_by: str,
) -> RabbitMqPublishResult:
    return publish_pipeline_task_job(
        job_type=JOB_TYPE_TRACK_VIOLATIONS,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        requested_by=requested_by,
        continue_on_error=True,
    )


# Совместимость со старым импортом диспетчера.
def publish_sync_legal_entity_job(
    *,
    entity_id: int,
    date_from: datetime | None,
    date_to: datetime | None,
    skip_edo: bool,
    force_edo: bool,
    edo_fail_fast: bool,
    continue_on_error: bool,
    requested_by: str,
    job_id: UUID | None = None,
) -> RabbitMqPublishResult:
    return publish_pipeline_task_job(
        job_type=JOB_TYPE_EXPORT_UPD,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
        skip_edo=skip_edo,
        force_edo=force_edo,
        edo_fail_fast=edo_fail_fast,
        continue_on_error=continue_on_error,
        requested_by=requested_by,
        job_id=job_id,
    )


def main(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
    ),
    job_type: str = typer.Option(
        JOB_TYPE_EXPORT_UPD,
        "--job-type",
    ),
    date_from: str | None = typer.Option(
        None,
        "--date-from",
    ),
    date_to: str | None = typer.Option(
        None,
        "--date-to",
    ),
    parent_job_id: str | None = typer.Option(
        None,
        "--parent-job-id",
    ),
    requested_by: str = typer.Option(
        "manual-cli",
        "--requested-by",
    ),
) -> None:
    try:
        result = publish_pipeline_task_job(
            job_type=job_type,
            entity_id=entity_id,
            date_from=_parse_optional_datetime(
                date_from,
                option_name="date_from",
            ),
            date_to=_parse_optional_datetime(
                date_to,
                option_name="date_to",
            ),
            parent_job_id=(
                UUID(parent_job_id)
                if parent_job_id
                else None
            ),
            requested_by=requested_by,
        )

    except ActiveSyncJobExistsError as exc:
        typer.echo(
            json.dumps(
                {
                    "status": "ACTIVE_JOB_EXISTS",
                    "legal_entity_id": (
                        exc.legal_entity_id
                    ),
                    "job_type": exc.job_type,
                    "active_job_id": (
                        exc.active_job_uuid
                    ),
                    "active_status": (
                        exc.active_status
                    ),
                    "error": str(exc),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            err=True,
        )
        raise typer.Exit(code=3) from exc

    except SyncJobPayloadConflictError as exc:
        typer.echo(
            json.dumps(
                {
                    "status": "JOB_PAYLOAD_CONFLICT",
                    "error": str(exc),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            err=True,
        )
        raise typer.Exit(code=4) from exc

    except Exception as exc:
        typer.echo(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc

    typer.echo(result.model_dump_json())


if __name__ == "__main__":
    typer.run(main)
