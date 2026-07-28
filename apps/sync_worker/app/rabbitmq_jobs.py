from __future__ import annotations

import asyncio
import json
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
    model_validator,
)

from app.config import get_settings
from app.db import Database
from app.sync_job_repository import (
    ActiveSyncJobExistsError,
    SyncJobPayloadConflictError,
    SyncJobRepository,
)


JOB_SCHEMA_VERSION = 1
JOB_TYPE = "SYNC_LEGAL_ENTITY"


class SyncLegalEntityJob(BaseModel):
    """
    Контракт задания синхронизации одной организации.

    Токен True API, сертификат, PIN и иные секреты
    в сообщение не включаются.
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
    job_type: str = JOB_TYPE
    legal_entity_id: int = Field(
        ge=1
    )

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

    @model_validator(
        mode="after"
    )
    def validate_contract(
        self,
    ) -> SyncLegalEntityJob:
        if self.job_type != JOB_TYPE:
            raise ValueError(
                "Поддерживается только "
                f"job_type={JOB_TYPE}."
            )

        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from >= self.date_to
        ):
            raise ValueError(
                "date_from должен быть "
                "меньше date_to."
            )

        if (
            self.skip_edo
            and self.force_edo
        ):
            raise ValueError(
                "Параметры skip_edo и force_edo "
                "не могут быть включены "
                "одновременно."
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


def _secret_value(
    value: Any,
) -> str:
    getter = getattr(
        value,
        "get_secret_value",
        None,
    )

    if callable(
        getter
    ):
        return str(
            getter()
        )

    return str(
        value
    )


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
            prepared.replace(
                "Z",
                "+00:00",
            )
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

    return parsed.astimezone(
        timezone.utc
    )


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
        .astimezone(
            timezone.utc
        )
        .replace(
            tzinfo=None
        )
    )


def _sync_queue_name(
    settings: Any,
    legal_entity_id: int,
) -> str:
    return (
        f"{settings.rabbitmq_sync_queue}."
        f"{legal_entity_id}"
    )


def _sync_routing_key(
    settings: Any,
    legal_entity_id: int,
) -> str:
    return (
        f"{settings.rabbitmq_sync_routing_key}."
        f"{legal_entity_id}"
    )


def _retry_queue_name(
    settings: Any,
    legal_entity_id: int,
) -> str:
    return (
        f"{settings.rabbitmq_retry_queue}."
        f"{legal_entity_id}"
    )


def _retry_routing_key(
    settings: Any,
    legal_entity_id: int,
) -> str:
    return (
        f"{settings.rabbitmq_retry_routing_key}."
        f"{legal_entity_id}"
    )


async def _publish_job_message(
    *,
    settings: Any,
    job: SyncLegalEntityJob,
) -> RabbitMqPublishResult:
    legal_entity_id = (
        job.legal_entity_id
    )

    sync_queue_name = (
        _sync_queue_name(
            settings,
            legal_entity_id,
        )
    )

    sync_routing_key = (
        _sync_routing_key(
            settings,
            legal_entity_id,
        )
    )

    retry_queue_name = (
        _retry_queue_name(
            settings,
            legal_entity_id,
        )
    )

    retry_routing_key = (
        _retry_routing_key(
            settings,
            legal_entity_id,
        )
    )

    connection = (
        await aio_pika.connect_robust(
            host=(
                settings.rabbitmq_host
            ),
            port=(
                settings.rabbitmq_port
            ),
            login=(
                settings.rabbitmq_user
            ),
            password=_secret_value(
                settings.rabbitmq_password
            ),
            virtualhost=(
                settings.rabbitmq_vhost
            ),
            client_properties={
                "connection_name": (
                    settings
                    .rabbitmq_connection_name
                ),
            },
            heartbeat=(
                settings.rabbitmq_heartbeat
            ),
            timeout=(
                settings.rabbitmq_timeout
            ),
            fail_fast="1",
        )
    )

    try:
        channel = (
            await connection.channel(
                publisher_confirms=True
            )
        )

        exchange = (
            await channel
            .declare_exchange(
                settings.rabbitmq_exchange,
                ExchangeType.DIRECT,
                durable=True,
            )
        )

        sync_queue = (
            await channel.declare_queue(
                sync_queue_name,
                durable=True,
            )
        )

        await sync_queue.bind(
            exchange,
            routing_key=(
                sync_routing_key
            ),
        )

        retry_queue = (
            await channel.declare_queue(
                retry_queue_name,
                durable=True,
                arguments={
                    "x-message-ttl": (
                        settings
                        .rabbitmq_retry_delay_seconds
                        * 1000
                    ),
                    "x-dead-letter-exchange": (
                        settings
                        .rabbitmq_exchange
                    ),
                    "x-dead-letter-routing-key": (
                        sync_routing_key
                    ),
                },
            )
        )

        await retry_queue.bind(
            exchange,
            routing_key=(
                retry_routing_key
            ),
        )

        dead_queue = (
            await channel.declare_queue(
                settings.rabbitmq_dead_queue,
                durable=True,
            )
        )

        await dead_queue.bind(
            exchange,
            routing_key=(
                settings
                .rabbitmq_dead_routing_key
            ),
        )

        body = json.dumps(
            job.model_dump(
                mode="json"
            ),
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        ).encode(
            "utf-8"
        )

        message_id = str(
            job.job_id
        )

        message = Message(
            body=body,
            content_type=(
                "application/json"
            ),
            content_encoding="utf-8",
            delivery_mode=(
                DeliveryMode.PERSISTENT
            ),
            message_id=message_id,
            correlation_id=message_id,
            timestamp=datetime.now(
                timezone.utc
            ),
            type=job.job_type,
            app_id=(
                "gis-mt-sync-worker"
            ),
            headers={
                "schema_version": (
                    job.schema_version
                ),
                "job_type": (
                    job.job_type
                ),
                "legal_entity_id": (
                    job.legal_entity_id
                ),
                "retry_count": (
                    job.retry_count
                ),
            },
        )

        confirmation = (
            await exchange.publish(
                message,
                routing_key=(
                    sync_routing_key
                ),
                mandatory=True,
            )
        )

        if confirmation is False:
            raise RuntimeError(
                "RabbitMQ не подтвердил "
                "публикацию задания."
            )

        return RabbitMqPublishResult(
            status="PUBLISHED",
            job_id=message_id,
            message_id=message_id,
            job_type=job.job_type,
            legal_entity_id=(
                job.legal_entity_id
            ),
            queue=sync_queue_name,
            routing_key=(
                sync_routing_key
            ),
        )

    finally:
        await connection.close()


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
    settings = get_settings()

    prepared_requested_by = (
        requested_by.strip()
    )

    if not prepared_requested_by:
        raise ValueError(
            "requested_by не может быть пустым."
        )

    requested_at = datetime.now(
        timezone.utc
    )

    job = SyncLegalEntityJob(
        job_id=(
            job_id
            if job_id is not None
            else uuid4()
        ),
        legal_entity_id=(
            entity_id
        ),
        date_from=date_from,
        date_to=date_to,
        skip_edo=skip_edo,
        force_edo=force_edo,
        edo_fail_fast=(
            edo_fail_fast
        ),
        continue_on_error=(
            continue_on_error
        ),
        retry_count=0,
        requested_by=(
            prepared_requested_by
        ),
        requested_at=(
            requested_at
        ),
    )

    payload = job.model_dump(
        mode="json"
    )

    repository = SyncJobRepository(
        Database(
            settings
        )
    )

    registered = (
        repository.register_job(
            job_uuid=str(
                job.job_id
            ),
            schema_version=(
                job.schema_version
            ),
            job_type=(
                job.job_type
            ),
            legal_entity_id=(
                job.legal_entity_id
            ),
            requested_by=(
                job.requested_by
            ),
            requested_at=(
                _to_mysql_datetime(
                    job.requested_at
                )
            ),
            date_from=(
                _to_mysql_datetime(
                    job.date_from
                )
            ),
            date_to=(
                _to_mysql_datetime(
                    job.date_to
                )
            ),
            skip_edo=(
                job.skip_edo
            ),
            force_edo=(
                job.force_edo
            ),
            edo_fail_fast=(
                job.edo_fail_fast
            ),
            continue_on_error=(
                job.continue_on_error
            ),
            payload=payload,
            max_retries=(
                settings
                .rabbitmq_max_retries
            ),
        )
    )

    if registered.status != "CREATED":
        if registered.status in {
            "PUBLISHED",
            "PROCESSING",
            "RETRY_WAIT",
            "SUCCESS",
        }:
            return RabbitMqPublishResult(
                status=(
                    registered.status
                ),
                job_id=(
                    registered.job_uuid
                ),
                message_id=(
                    registered
                    .last_message_id
                    or registered.job_uuid
                ),
                job_type=(
                    registered.job_type
                ),
                legal_entity_id=(
                    registered
                    .legal_entity_id
                ),
                queue=(
                    registered.queue_name
                    or _sync_queue_name(
                        settings,
                        registered
                        .legal_entity_id,
                    )
                ),
                routing_key=(
                    registered.routing_key
                    or _sync_routing_key(
                        settings,
                        registered
                        .legal_entity_id,
                    )
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
        job_uuid=(
            publish_result.job_id
        ),
        queue_name=(
            publish_result.queue
        ),
        routing_key=(
            publish_result.routing_key
        ),
        message_id=(
            publish_result.message_id
        ),
        correlation_id=(
            publish_result.message_id
        ),
    )

    return publish_result


def main(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help=(
            "ID организации "
            "в legal_entity."
        ),
    ),

    date_from: str | None = typer.Option(
        None,
        "--date-from",
        "--from",
        help=(
            "Начало периода ISO 8601. "
            "При отсутствии период определяет "
            "рабочий конвейер."
        ),
    ),

    date_to: str | None = typer.Option(
        None,
        "--date-to",
        "--to",
        help=(
            "Конец периода ISO 8601. "
            "При отсутствии период определяет "
            "рабочий конвейер."
        ),
    ),

    skip_edo: bool = typer.Option(
        False,
        "--skip-edo",
        help=(
            "Не загружать XML ЭДО."
        ),
    ),

    force_edo: bool = typer.Option(
        False,
        "--force-edo",
        help=(
            "Повторно загружать ранее "
            "обработанные XML ЭДО."
        ),
    ),

    edo_fail_fast: bool = typer.Option(
        False,
        "--edo-fail-fast",
        help=(
            "Остановить обработку ЭДО "
            "после первой ошибки документа."
        ),
    ),

    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help=(
            "Продолжать обработку следующих "
            "товарных групп после ошибки."
        ),
    ),

    requested_by: str = typer.Option(
        "manual-cli",
        "--requested-by",
        help=(
            "Источник постановки задания."
        ),
    ),

    job_id: str | None = typer.Option(
        None,
        "--job-id",
        help=(
            "Заранее заданный UUID задания. "
            "Обычно генерируется автоматически."
        ),
    ),
) -> None:
    try:
        prepared_job_id = (
            UUID(
                job_id.strip()
            )
            if (
                job_id is not None
                and job_id.strip()
            )
            else None
        )

        result = (
            publish_sync_legal_entity_job(
                entity_id=entity_id,
                date_from=(
                    _parse_optional_datetime(
                        date_from,
                        option_name=(
                            "date_from"
                        ),
                    )
                ),
                date_to=(
                    _parse_optional_datetime(
                        date_to,
                        option_name=(
                            "date_to"
                        ),
                    )
                ),
                skip_edo=skip_edo,
                force_edo=force_edo,
                edo_fail_fast=(
                    edo_fail_fast
                ),
                continue_on_error=(
                    continue_on_error
                ),
                requested_by=(
                    requested_by
                ),
                job_id=(
                    prepared_job_id
                ),
            )
        )

    except ActiveSyncJobExistsError as exc:
        typer.echo(
            json.dumps(
                {
                    "status": (
                        "ACTIVE_JOB_EXISTS"
                    ),
                    "legal_entity_id": (
                        exc.legal_entity_id
                    ),
                    "active_job_id": (
                        exc.active_job_uuid
                    ),
                    "active_status": (
                        exc.active_status
                    ),
                    "error": str(
                        exc
                    ),
                },
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            ),
            err=True,
        )

        raise typer.Exit(
            code=3
        ) from exc

    except SyncJobPayloadConflictError as exc:
        typer.echo(
            json.dumps(
                {
                    "status": (
                        "JOB_PAYLOAD_CONFLICT"
                    ),
                    "error": str(
                        exc
                    ),
                },
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            ),
            err=True,
        )

        raise typer.Exit(
            code=4
        ) from exc

    except Exception as exc:
        typer.echo(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": (
                        type(exc).__name__
                    ),
                    "error": str(
                        exc
                    ),
                },
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            ),
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc

    typer.echo(
        result.model_dump_json()
    )


if __name__ == "__main__":
    typer.run(
        main
    )