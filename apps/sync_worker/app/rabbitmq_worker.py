from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aio_pika
import typer
from aio_pika import (
    DeliveryMode,
    IncomingMessage,
    Message,
)
from pydantic import BaseModel, ValidationError

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.process_downloaded_upd import (
    process_downloaded_upd,
)
from app.rabbitmq_jobs import (
    JOB_TYPE_EXPORT_UPD,
    JOB_TYPE_LEGACY,
    JOB_TYPE_PROCESS_UPD,
    JOB_TYPE_TRACK_VIOLATIONS,
    PipelineTaskJob,
    SUPPORTED_JOB_TYPES,
    declare_job_topology,
    job_topology,
)
from app.sync_job_repository import (
    SyncJobClaim,
    SyncJobNotFoundError,
    SyncJobRepository,
    SyncJobRetryLimitError,
    SyncJobStateError,
)
from app.sync_legal_entity import (
    PipelineExecutionMode,
    sync_legal_entity,
)


SUCCESS_EXIT_CODE = 0
AUTH_RETRY_EXIT_CODE = 20
AUTH_DEAD_EXIT_CODE = 21
GENERAL_RETRY_EXIT_CODE = 30
GENERAL_DEAD_EXIT_CODE = 31
WORKER_ERROR_EXIT_CODE = 40

DEFAULT_JOB_LEASE_SECONDS = 900
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60
DEFAULT_PARENT_WAIT_SECONDS = 21600


class WorkerResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ALREADY_SUCCESS = "ALREADY_SUCCESS"
    AUTH_RETRY = "AUTH_RETRY"
    AUTH_DEAD = "AUTH_DEAD"
    RETRY = "RETRY"
    DEAD = "DEAD"
    LEASE_RETRY = "LEASE_RETRY"
    CANCELLED = "CANCELLED"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    WORKER_ERROR = "WORKER_ERROR"


class NonRetryableJobError(RuntimeError):
    pass


class ParentJobFailedError(NonRetryableJobError):
    pass


def _secret_value(value: Any) -> str:
    getter = getattr(
        value,
        "get_secret_value",
        None,
    )

    if callable(getter):
        return str(getter())

    return str(value)


def _worker_id(
    legal_entity_id: int,
    job_type: str,
) -> str:
    hostname = (
        socket.gethostname()
        .strip()
        .replace(" ", "-")
    )

    suffix = uuid4().hex[:12]

    return (
        f"{hostname}:{os.getpid()}:"
        f"{legal_entity_id}:{job_type}:"
        f"{suffix}"
    )[:128]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value):
        return asdict(value)

    model_dump = getattr(
        value,
        "model_dump",
        None,
    )

    if callable(model_dump):
        return model_dump(mode="json")

    if isinstance(value, set):
        return sorted(value)

    return str(value)


def _json_safe_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, BaseModel):
        prepared = value.model_dump(mode="json")

    elif is_dataclass(value):
        prepared = asdict(value)

    elif isinstance(value, dict):
        prepared = value

    else:
        prepared = {"value": value}

    encoded = json.dumps(
        prepared,
        ensure_ascii=False,
        default=_json_default,
        separators=(",", ":"),
    )

    decoded = json.loads(encoded)

    if not isinstance(decoded, dict):
        return {"value": decoded}

    return decoded


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        default=_json_default,
        separators=(",", ":"),
    )


def _error_message(exc: BaseException) -> str:
    prepared = str(exc).strip()

    if not prepared:
        prepared = type(exc).__name__

    return prepared[:2000]


def _result_payload(
    *,
    status: WorkerResultStatus,
    legal_entity_id: int,
    job_type: str,
    job_id: str | None,
    queue_name: str,
    retry_count: int | None = None,
    attempt_count: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status.value,
        "job_type": job_type,
        "legal_entity_id": legal_entity_id,
        "processed_count": 1,
        "job_id": job_id,
        "queue": queue_name,
    }

    if retry_count is not None:
        payload["retry_count"] = retry_count

    if attempt_count is not None:
        payload["attempt_count"] = attempt_count

    if error_type is not None:
        payload["error_type"] = error_type

    if error_message is not None:
        payload["error"] = error_message

    if result is not None:
        payload["result"] = result

    return payload


async def _publish_job(
    *,
    exchange: aio_pika.abc.AbstractExchange,
    routing_key: str,
    job: PipelineTaskJob,
    message_id: str,
    headers: dict[str, Any] | None = None,
) -> None:
    prepared_headers = {
        "schema_version": job.schema_version,
        "job_type": job.job_type,
        "legal_entity_id": job.legal_entity_id,
        "retry_count": job.retry_count,
    }

    if headers:
        prepared_headers.update(headers)

    body = json.dumps(
        job.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    confirmation = await exchange.publish(
        Message(
            body=body,
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id,
            correlation_id=str(job.job_id),
            timestamp=_utc_now(),
            type=job.job_type,
            app_id="gis-mt-rabbitmq-worker",
            headers=prepared_headers,
        ),
        routing_key=routing_key,
        mandatory=True,
    )

    if confirmation is False:
        raise RuntimeError(
            "RabbitMQ не подтвердил публикацию сообщения."
        )


async def _publish_dead_message(
    *,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    job_type: str,
    legal_entity_id: int,
    job_id: str | None,
    body: bytes,
    error_type: str,
    error_message: str,
) -> None:
    topology = job_topology(
        settings,
        job_type,
        legal_entity_id,
    )

    message_id = (
        f"{job_id or uuid4()}-dead-"
        f"{uuid4().hex[:12]}"
    )[:255]

    confirmation = await exchange.publish(
        Message(
            body=body,
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id,
            correlation_id=job_id,
            timestamp=_utc_now(),
            type=f"{job_type}.DEAD",
            app_id="gis-mt-rabbitmq-worker",
            headers={
                "job_type": job_type,
                "legal_entity_id": legal_entity_id,
                "error_type": error_type[:128],
                "error_message": error_message[:2000],
            },
        ),
        routing_key=topology.dead_routing_key,
        mandatory=True,
    )

    if confirmation is False:
        raise RuntimeError(
            "RabbitMQ не подтвердил публикацию "
            "в dead queue."
        )


def _extract_details_run_ids(
    parent_result: dict[str, Any] | None,
) -> tuple[int, ...]:
    if not parent_result:
        return ()

    groups = parent_result.get(
        "successful_groups"
    )

    if not isinstance(groups, list):
        return ()

    result: set[int] = set()

    for group in groups:
        if not isinstance(group, dict):
            continue

        value = group.get("details_run_id")

        try:
            run_id = int(value)
        except (TypeError, ValueError):
            continue

        if run_id > 0:
            result.add(run_id)

    return tuple(sorted(result))


def _wait_for_parent_export(
    *,
    repository: SyncJobRepository,
    parent_job_id: UUID,
    legal_entity_id: int,
    timeout_seconds: int,
) -> tuple[int, ...]:
    deadline = time.monotonic() + timeout_seconds
    parent_uuid = str(parent_job_id)

    while True:
        parent = repository.require_job(
            parent_uuid
        )

        if parent.legal_entity_id != legal_entity_id:
            raise ParentJobFailedError(
                "Родительское задание относится "
                "к другой организации."
            )

        if parent.job_type not in {
            JOB_TYPE_LEGACY,
            JOB_TYPE_EXPORT_UPD,
        }:
            raise ParentJobFailedError(
                "Родительское задание не является "
                "экспортом УПД."
            )

        if parent.status == "SUCCESS":
            return _extract_details_run_ids(
                parent.result
            )

        if parent.status in {
            "DEAD",
            "CANCELLED",
        }:
            raise ParentJobFailedError(
                "Экспорт УПД завершён безуспешно: "
                f"status={parent.status}; "
                "error="
                f"{parent.last_error_message or '-'}."
            )

        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Истёк таймаут ожидания "
                "родительского задания экспорта УПД."
            )

        time.sleep(3)


def _execute_job(
    *,
    token: str,
    job: PipelineTaskJob,
    repository: SyncJobRepository,
    parent_wait_seconds: int,
) -> Any:
    if job.job_type in {
        JOB_TYPE_LEGACY,
        JOB_TYPE_EXPORT_UPD,
    }:
        summary = sync_legal_entity(
            token=token,
            legal_entity_id=job.legal_entity_id,
            date_from=job.date_from,
            date_to=job.date_to,
            skip_edo=job.skip_edo,
            force_edo=job.force_edo,
            edo_fail_fast=job.edo_fail_fast,
            continue_on_error=(
                job.continue_on_error
            ),
            execution_mode=PipelineExecutionMode(
                pipeline_run_active=True,
                sync_documents=True,
                process_upd=False,
                sync_violations=False,
            ),
        )

        if summary.failed_group_count > 0:
            raise RuntimeError(
                "Экспорт УПД завершился с ошибками "
                "товарных групп: "
                f"{summary.failed_group_count}."
            )

        return summary

    if job.job_type == JOB_TYPE_TRACK_VIOLATIONS:
        summary = sync_legal_entity(
            token=token,
            legal_entity_id=job.legal_entity_id,
            date_from=job.date_from,
            date_to=job.date_to,
            skip_edo=True,
            force_edo=False,
            edo_fail_fast=False,
            continue_on_error=(
                job.continue_on_error
            ),
            execution_mode=PipelineExecutionMode(
                pipeline_run_active=True,
                sync_documents=False,
                process_upd=False,
                sync_violations=True,
            ),
        )

        if summary.failed_group_count > 0:
            raise RuntimeError(
                "Скачивание отклонений завершилось "
                "с ошибками товарных групп: "
                f"{summary.failed_group_count}."
            )

        return summary

    if job.job_type == JOB_TYPE_PROCESS_UPD:
        if job.parent_job_id is None:
            raise NonRetryableJobError(
                "PROCESS_UPD не содержит parent_job_id."
            )

        details_run_ids = _wait_for_parent_export(
            repository=repository,
            parent_job_id=job.parent_job_id,
            legal_entity_id=job.legal_entity_id,
            timeout_seconds=parent_wait_seconds,
        )

        if not details_run_ids:
            return {
                "legal_entity_id": (
                    job.legal_entity_id
                ),
                "processing_job_uuid": str(
                    job.job_id
                ),
                "details_run_ids": [],
                "selected_count": 0,
                "already_processed_count": 0,
                "processed_count": 0,
                "matched_count": 0,
                "error_count": 0,
                "message": (
                    "В родительском экспорте нет "
                    "документов для обработки."
                ),
            }

        return process_downloaded_upd(
            legal_entity_id=job.legal_entity_id,
            details_run_ids=details_run_ids,
            processing_job_uuid=str(job.job_id),
            output_root=Path("/data/official"),
        )

    raise NonRetryableJobError(
        "Неподдерживаемый job_type: "
        f"{job.job_type}."
    )


async def _heartbeat_loop(
    *,
    repository: SyncJobRepository,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    while True:
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval_seconds,
            )
            return

        except asyncio.TimeoutError:
            pass

        try:
            await asyncio.to_thread(
                repository.heartbeat,
                job_uuid=job_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )

        except Exception as exc:
            typer.echo(
                "Ошибка heartbeat задания: "
                f"job_id={job_id}; "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )


async def _execute_with_heartbeat(
    *,
    repository: SyncJobRepository,
    token: str,
    job: PipelineTaskJob,
    worker_id: str,
    lease_seconds: int,
    heartbeat_interval_seconds: int,
    parent_wait_seconds: int,
) -> Any:
    stop_event = asyncio.Event()

    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            repository=repository,
            job_id=str(job.job_id),
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            interval_seconds=(
                heartbeat_interval_seconds
            ),
            stop_event=stop_event,
        )
    )

    try:
        return await asyncio.to_thread(
            _execute_job,
            token=token,
            job=job,
            repository=repository,
            parent_wait_seconds=(
                parent_wait_seconds
            ),
        )

    finally:
        stop_event.set()

        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


async def _move_to_dead(
    *,
    message: IncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    repository: SyncJobRepository,
    worker_id: str | None,
    job: PipelineTaskJob,
    queue_name: str,
    exc: BaseException,
    is_auth_error: bool,
) -> tuple[bool, int]:
    job_id = str(job.job_id)
    error_type = type(exc).__name__
    error_message = _error_message(exc)

    try:
        record = await asyncio.to_thread(
            repository.mark_dead,
            job_uuid=job_id,
            worker_id=worker_id,
            error_type=error_type,
            error_message=error_message,
            result={
                "job_type": job.job_type,
                "dead_at": _utc_now().isoformat(),
            },
        )

    except SyncJobStateError:
        record = repository.require_job(job_id)

    await _publish_dead_message(
        exchange=exchange,
        settings=settings,
        job_type=job.job_type,
        legal_entity_id=job.legal_entity_id,
        job_id=job_id,
        body=message.body,
        error_type=error_type,
        error_message=error_message,
    )

    await message.ack()

    status = (
        WorkerResultStatus.AUTH_DEAD
        if is_auth_error
        else WorkerResultStatus.DEAD
    )

    payload = _result_payload(
        status=status,
        legal_entity_id=job.legal_entity_id,
        job_type=job.job_type,
        job_id=job_id,
        queue_name=queue_name,
        retry_count=record.retry_count,
        attempt_count=record.attempt_count,
        error_type=error_type,
        error_message=error_message,
    )

    typer.echo(_compact_json(payload))

    return (
        True,
        AUTH_DEAD_EXIT_CODE
        if is_auth_error
        else GENERAL_DEAD_EXIT_CODE,
    )


async def _schedule_retry(
    *,
    message: IncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    repository: SyncJobRepository,
    worker_id: str,
    job: PipelineTaskJob,
    queue_name: str,
    exc: BaseException,
    is_auth_error: bool,
) -> tuple[bool, int]:
    job_id = str(job.job_id)
    error_type = type(exc).__name__
    error_message = _error_message(exc)

    try:
        retry_record = await asyncio.to_thread(
            repository.schedule_retry,
            job_uuid=job_id,
            worker_id=worker_id,
            delay_seconds=(
                settings.rabbitmq_retry_delay_seconds
            ),
            error_type=error_type,
            error_message=error_message,
        )

    except SyncJobRetryLimitError:
        return await _move_to_dead(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=worker_id,
            job=job,
            queue_name=queue_name,
            exc=exc,
            is_auth_error=is_auth_error,
        )

    retry_job = job.model_copy(
        update={
            "retry_count": retry_record.retry_count,
        }
    )

    topology = job_topology(
        settings,
        job.job_type,
        job.legal_entity_id,
    )

    retry_message_id = (
        f"{job_id}-retry-"
        f"{retry_record.retry_count}"
    )[:255]

    await _publish_job(
        exchange=exchange,
        routing_key=topology.retry_routing_key,
        job=retry_job,
        message_id=retry_message_id,
        headers={
            "retry_reason": (
                "AUTH_ERROR"
                if is_auth_error
                else "PROCESSING_ERROR"
            ),
            "worker_retry": True,
            "error_type": error_type[:128],
        },
    )

    await asyncio.to_thread(
        repository.mark_published,
        job_uuid=job_id,
        queue_name=topology.retry_queue_name,
        routing_key=topology.retry_routing_key,
        message_id=retry_message_id,
        correlation_id=job_id,
    )

    await message.ack()

    status = (
        WorkerResultStatus.AUTH_RETRY
        if is_auth_error
        else WorkerResultStatus.RETRY
    )

    payload = _result_payload(
        status=status,
        legal_entity_id=job.legal_entity_id,
        job_type=job.job_type,
        job_id=job_id,
        queue_name=queue_name,
        retry_count=retry_record.retry_count,
        attempt_count=retry_record.attempt_count,
        error_type=error_type,
        error_message=error_message,
    )

    typer.echo(_compact_json(payload))

    return (
        True,
        AUTH_RETRY_EXIT_CODE
        if is_auth_error
        else GENERAL_RETRY_EXIT_CODE,
    )


async def _process_message(
    *,
    message: IncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    repository: SyncJobRepository,
    token: str,
    worker_id: str,
    legal_entity_id: int,
    expected_job_type: str,
    queue_name: str,
    lease_seconds: int,
    heartbeat_interval_seconds: int,
    parent_wait_seconds: int,
) -> tuple[bool, int]:
    try:
        payload = json.loads(
            message.body.decode("utf-8")
        )
        job = PipelineTaskJob.model_validate(
            payload
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        await _publish_dead_message(
            exchange=exchange,
            settings=settings,
            job_type=expected_job_type,
            legal_entity_id=legal_entity_id,
            job_id=None,
            body=message.body,
            error_type=type(exc).__name__,
            error_message=_error_message(exc),
        )
        await message.ack()

        typer.echo(
            _compact_json(
                _result_payload(
                    status=(
                        WorkerResultStatus.INVALID_MESSAGE
                    ),
                    legal_entity_id=legal_entity_id,
                    job_type=expected_job_type,
                    job_id=None,
                    queue_name=queue_name,
                    error_type=type(exc).__name__,
                    error_message=_error_message(exc),
                )
            )
        )

        return True, GENERAL_DEAD_EXIT_CODE

    job_id = str(job.job_id)

    if (
        job.legal_entity_id != legal_entity_id
        or job.job_type != expected_job_type
    ):
        exc = NonRetryableJobError(
            "Сообщение попало не в свою очередь: "
            f"message_entity={job.legal_entity_id}; "
            f"worker_entity={legal_entity_id}; "
            f"message_type={job.job_type}; "
            f"worker_type={expected_job_type}."
        )

        return await _move_to_dead(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=None,
            job=job,
            queue_name=queue_name,
            exc=exc,
            is_auth_error=False,
        )

    typer.echo(
        "Получено задание: "
        f"job_id={job_id}; "
        f"job_type={job.job_type}; "
        f"entity_id={job.legal_entity_id}; "
        f"retry_count={job.retry_count}."
    )

    try:
        claim = await asyncio.to_thread(
            repository.claim_job,
            job_uuid=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            message_id=(
                str(message.message_id)
                if message.message_id is not None
                else None
            ),
            correlation_id=(
                str(message.correlation_id)
                if message.correlation_id is not None
                else None
            ),
            expected_retry_count=job.retry_count,
        )

    except (
        SyncJobNotFoundError,
        SyncJobStateError,
    ) as exc:
        return await _move_to_dead(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=None,
            job=job,
            queue_name=queue_name,
            exc=exc,
            is_auth_error=False,
        )

    if claim.outcome == "STALE":
        await message.ack()
        return False, SUCCESS_EXIT_CODE

    if claim.outcome == "BUSY":
        topology = job_topology(
            settings,
            job.job_type,
            job.legal_entity_id,
        )
        message_id = (
            f"{job_id}-lease-{uuid4().hex[:12]}"
        )[:255]

        await _publish_job(
            exchange=exchange,
            routing_key=topology.retry_routing_key,
            job=job,
            message_id=message_id,
            headers={
                "retry_reason": "ACTIVE_LEASE",
                "worker_retry": False,
            },
        )
        await asyncio.to_thread(
            repository.mark_published,
            job_uuid=job_id,
            queue_name=topology.retry_queue_name,
            routing_key=topology.retry_routing_key,
            message_id=message_id,
            correlation_id=job_id,
        )
        await message.ack()
        return True, GENERAL_RETRY_EXIT_CODE

    if claim.outcome == "TERMINAL":
        await message.ack()

        if claim.job.status == "SUCCESS":
            status = WorkerResultStatus.ALREADY_SUCCESS
            exit_code = SUCCESS_EXIT_CODE
        elif claim.job.status == "CANCELLED":
            status = WorkerResultStatus.CANCELLED
            exit_code = GENERAL_DEAD_EXIT_CODE
        else:
            status = WorkerResultStatus.DEAD
            exit_code = GENERAL_DEAD_EXIT_CODE

        typer.echo(
            _compact_json(
                _result_payload(
                    status=status,
                    legal_entity_id=legal_entity_id,
                    job_type=job.job_type,
                    job_id=job_id,
                    queue_name=queue_name,
                    retry_count=claim.job.retry_count,
                    attempt_count=claim.job.attempt_count,
                    error_type=(
                        claim.job.last_error_type
                    ),
                    error_message=(
                        claim.job.last_error_message
                    ),
                    result=claim.job.result,
                )
            )
        )

        return True, exit_code

    if claim.outcome != "CLAIMED":
        return await _move_to_dead(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=worker_id,
            job=job,
            queue_name=queue_name,
            exc=RuntimeError(
                "Неизвестный результат захвата: "
                f"{claim.outcome}."
            ),
            is_auth_error=False,
        )

    try:
        execution_result = await _execute_with_heartbeat(
            repository=repository,
            token=token,
            job=job,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            heartbeat_interval_seconds=(
                heartbeat_interval_seconds
            ),
            parent_wait_seconds=parent_wait_seconds,
        )

        result_object = _json_safe_object(
            execution_result
        )
        result_object["completed_at"] = (
            _utc_now().isoformat()
        )

        success_record = await asyncio.to_thread(
            repository.mark_success,
            job_uuid=job_id,
            worker_id=worker_id,
            result=result_object,
        )

        await message.ack()

        typer.echo(
            _compact_json(
                _result_payload(
                    status=WorkerResultStatus.SUCCESS,
                    legal_entity_id=legal_entity_id,
                    job_type=job.job_type,
                    job_id=job_id,
                    queue_name=queue_name,
                    retry_count=(
                        success_record.retry_count
                    ),
                    attempt_count=(
                        success_record.attempt_count
                    ),
                    result=result_object,
                )
            )
        )

        return True, SUCCESS_EXIT_CODE

    except NonRetryableJobError as exc:
        return await _move_to_dead(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=worker_id,
            job=job,
            queue_name=queue_name,
            exc=exc,
            is_auth_error=False,
        )

    except GisMtAuthError as exc:
        current = await asyncio.to_thread(
            repository.require_job,
            job_id,
        )

        if current.retry_count >= current.max_retries:
            return await _move_to_dead(
                message=message,
                exchange=exchange,
                settings=settings,
                repository=repository,
                worker_id=worker_id,
                job=job,
                queue_name=queue_name,
                exc=exc,
                is_auth_error=True,
            )

        return await _schedule_retry(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=worker_id,
            job=job,
            queue_name=queue_name,
            exc=exc,
            is_auth_error=True,
        )

    except Exception as exc:
        current = await asyncio.to_thread(
            repository.require_job,
            job_id,
        )

        if current.retry_count >= current.max_retries:
            return await _move_to_dead(
                message=message,
                exchange=exchange,
                settings=settings,
                repository=repository,
                worker_id=worker_id,
                job=job,
                queue_name=queue_name,
                exc=exc,
                is_auth_error=False,
            )

        return await _schedule_retry(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            worker_id=worker_id,
            job=job,
            queue_name=queue_name,
            exc=exc,
            is_auth_error=False,
        )


async def run_worker(
    *,
    token: str,
    legal_entity_id: int,
    job_type: str,
    once: bool,
    lease_seconds: int,
    heartbeat_interval_seconds: int,
    parent_wait_seconds: int,
) -> int:
    settings = get_settings()
    prepared_job_type = job_type.strip().upper()

    if prepared_job_type not in SUPPORTED_JOB_TYPES:
        raise ValueError(
            "Неподдерживаемый job_type: "
            f"{prepared_job_type}."
        )

    repository = SyncJobRepository(
        Database(settings)
    )

    worker_id = _worker_id(
        legal_entity_id,
        prepared_job_type,
    )

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
                f"{settings.rabbitmq_connection_name}:"
                f"worker:{prepared_job_type}:"
                f"{legal_entity_id}"
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
        await channel.set_qos(prefetch_count=1)

        exchange, queue, topology = (
            await declare_job_topology(
                channel=channel,
                settings=settings,
                job_type=prepared_job_type,
                legal_entity_id=legal_entity_id,
            )
        )

        typer.echo("RabbitMQ worker запущен.")
        typer.echo(
            f"Организация: {legal_entity_id}"
        )
        typer.echo(
            f"Тип задания: {prepared_job_type}"
        )
        typer.echo(
            f"Очередь: {topology.queue_name}"
        )
        typer.echo(f"Worker ID: {worker_id}")
        typer.echo(
            "Режим: "
            + (
                "одно итоговое задание"
                if once
                else "постоянный consumer"
            )
        )
        typer.echo("")

        async with queue.iterator() as iterator:
            async for message in iterator:
                should_stop, exit_code = (
                    await _process_message(
                        message=message,
                        exchange=exchange,
                        settings=settings,
                        repository=repository,
                        token=token,
                        worker_id=worker_id,
                        legal_entity_id=(
                            legal_entity_id
                        ),
                        expected_job_type=(
                            prepared_job_type
                        ),
                        queue_name=(
                            topology.queue_name
                        ),
                        lease_seconds=lease_seconds,
                        heartbeat_interval_seconds=(
                            heartbeat_interval_seconds
                        ),
                        parent_wait_seconds=(
                            parent_wait_seconds
                        ),
                    )
                )

                if once and should_stop:
                    return exit_code

        return SUCCESS_EXIT_CODE

    finally:
        await connection.close()


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
    once: bool = typer.Option(
        False,
        "--once",
    ),
    lease_seconds: int = typer.Option(
        DEFAULT_JOB_LEASE_SECONDS,
        "--lease-seconds",
        min=60,
    ),
    heartbeat_interval_seconds: int = typer.Option(
        DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        "--heartbeat-interval-seconds",
        min=5,
    ),
    parent_wait_seconds: int = typer.Option(
        DEFAULT_PARENT_WAIT_SECONDS,
        "--parent-wait-seconds",
        min=60,
    ),
) -> None:
    token = read_token_from_stdin()

    try:
        exit_code = asyncio.run(
            run_worker(
                token=token,
                legal_entity_id=entity_id,
                job_type=job_type,
                once=once,
                lease_seconds=lease_seconds,
                heartbeat_interval_seconds=(
                    heartbeat_interval_seconds
                ),
                parent_wait_seconds=(
                    parent_wait_seconds
                ),
            )
        )

    except Exception as exc:
        typer.echo(
            _compact_json(
                _result_payload(
                    status=(
                        WorkerResultStatus.WORKER_ERROR
                    ),
                    legal_entity_id=entity_id,
                    job_type=job_type,
                    job_id=None,
                    queue_name="",
                    error_type=type(exc).__name__,
                    error_message=_error_message(exc),
                )
            ),
            err=True,
        )
        raise typer.Exit(
            code=WORKER_ERROR_EXIT_CODE
        ) from exc

    if exit_code != SUCCESS_EXIT_CODE:
        raise typer.Exit(code=exit_code)


if __name__ == "__main__":
    typer.run(main)
