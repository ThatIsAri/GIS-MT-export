from __future__ import annotations

import asyncio
import json
import os
import socket
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

import aio_pika
import typer
from aio_pika import (
    DeliveryMode,
    ExchangeType,
    IncomingMessage,
    Message,
)
from pydantic import BaseModel, ValidationError

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.rabbitmq_jobs import (
    JOB_TYPE,
    SyncLegalEntityJob,
)
from app.sync_job_repository import (
    SyncJobClaim,
    SyncJobNotFoundError,
    SyncJobRepository,
    SyncJobRetryLimitError,
    SyncJobStateError,
)
from app.sync_legal_entity import (
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


class WorkerResultStatus(str, Enum):
    SUCCESS = "SUCCESS"

    ALREADY_SUCCESS = (
        "ALREADY_SUCCESS"
    )

    AUTH_RETRY = "AUTH_RETRY"
    AUTH_DEAD = "AUTH_DEAD"

    RETRY = "RETRY"
    DEAD = "DEAD"

    LEASE_RETRY = "LEASE_RETRY"

    CANCELLED = "CANCELLED"

    INVALID_MESSAGE = (
        "INVALID_MESSAGE"
    )

    WORKER_ERROR = "WORKER_ERROR"


def _secret_value(
    value: Any,
) -> str:
    getter = getattr(
        value,
        "get_secret_value",
        None,
    )

    if callable(getter):
        return str(
            getter()
        )

    return str(value)


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


def _worker_id(
    legal_entity_id: int,
) -> str:
    hostname = (
        socket.gethostname()
        .strip()
        .replace(
            " ",
            "-",
        )
    )

    suffix = uuid4().hex[:12]

    return (
        f"{hostname}:"
        f"{os.getpid()}:"
        f"{legal_entity_id}:"
        f"{suffix}"
    )[:128]


def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _json_default(
    value: Any,
) -> Any:
    if isinstance(
        value,
        (
            datetime,
            date,
        ),
    ):
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
        return model_dump(
            mode="json"
        )

    if isinstance(value, set):
        return sorted(value)

    return str(value)


def _json_safe_object(
    value: Any,
) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, BaseModel):
        prepared = value.model_dump(
            mode="json"
        )

    elif is_dataclass(value):
        prepared = asdict(value)

    elif isinstance(value, dict):
        prepared = value

    else:
        prepared = {
            "value": value,
        }

    encoded = json.dumps(
        prepared,
        ensure_ascii=False,
        default=_json_default,
        separators=(
            ",",
            ":",
        ),
    )

    decoded = json.loads(encoded)

    if not isinstance(decoded, dict):
        return {
            "value": decoded,
        }

    return decoded


def _compact_json(
    value: dict[str, Any],
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        default=_json_default,
        separators=(
            ",",
            ":",
        ),
    )


def _error_message(
    exc: BaseException,
) -> str:
    prepared = str(exc).strip()

    if not prepared:
        prepared = type(
            exc
        ).__name__

    return prepared[:2000]


def _message_id(
    message: IncomingMessage,
) -> str | None:
    if message.message_id is None:
        return None

    prepared = str(
        message.message_id
    ).strip()

    return prepared or None


def _correlation_id(
    message: IncomingMessage,
) -> str | None:
    if message.correlation_id is None:
        return None

    prepared = str(
        message.correlation_id
    ).strip()

    return prepared or None


def _result_payload(
    *,
    status: WorkerResultStatus,
    legal_entity_id: int,
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
        "legal_entity_id": (
            legal_entity_id
        ),
        "processed_count": 1,
        "job_id": job_id,
        "queue": queue_name,
    }

    if retry_count is not None:
        payload[
            "retry_count"
        ] = retry_count

    if attempt_count is not None:
        payload[
            "attempt_count"
        ] = attempt_count

    if error_type is not None:
        payload[
            "error_type"
        ] = error_type

    if error_message is not None:
        payload[
            "error"
        ] = error_message

    if result is not None:
        payload[
            "result"
        ] = result

    return payload


async def _declare_topology(
    *,
    channel: aio_pika.abc.AbstractChannel,
    settings: Any,
    legal_entity_id: int,
) -> tuple[
    aio_pika.abc.AbstractExchange,
    aio_pika.abc.AbstractQueue,
]:
    exchange = (
        await channel.declare_exchange(
            settings.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
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
                    settings.rabbitmq_exchange
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

    return (
        exchange,
        sync_queue,
    )


def _retry_message_id(
    job: SyncLegalEntityJob,
) -> str:
    return (
        f"{job.job_id}:"
        f"retry:{job.retry_count}"
    )


def _lease_retry_message_id(
    job: SyncLegalEntityJob,
) -> str:
    return (
        f"{job.job_id}:"
        "lease:"
        f"{uuid4().hex[:12]}"
    )


def _dead_message_id(
    job_id: str | None,
) -> str:
    prepared_job_id = (
        job_id
        if job_id
        else "unknown"
    )

    return (
        f"{prepared_job_id}:"
        "dead:"
        f"{uuid4().hex[:12]}"
    )


async def _publish_job(
    *,
    exchange: aio_pika.abc.AbstractExchange,
    routing_key: str,
    job: SyncLegalEntityJob,
    message_id: str,
    headers: dict[str, Any] | None = None,
) -> None:
    prepared_headers: dict[
        str,
        Any,
    ] = {
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
    }

    if headers:
        prepared_headers.update(
            headers
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

    confirmation = (
        await exchange.publish(
            Message(
                body=body,
                content_type=(
                    "application/json"
                ),
                content_encoding="utf-8",
                delivery_mode=(
                    DeliveryMode.PERSISTENT
                ),
                message_id=message_id,
                correlation_id=str(
                    job.job_id
                ),
                timestamp=_utc_now(),
                type=job.job_type,
                app_id=(
                    "gis-mt-sync-worker"
                ),
                headers=(
                    prepared_headers
                ),
            ),
            routing_key=routing_key,
            mandatory=True,
        )
    )

    if confirmation is False:
        raise RuntimeError(
            "RabbitMQ не подтвердил "
            "публикацию сообщения."
        )


async def _publish_dead_message(
    *,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    legal_entity_id: int,
    job_id: str | None,
    body: bytes,
    original_message_id: str | None,
    original_correlation_id: str | None,
    error_type: str,
    error_message: str,
) -> None:
    prepared_message_id = (
        _dead_message_id(
            job_id
        )
    )

    confirmation = (
        await exchange.publish(
            Message(
                body=body,
                content_type=(
                    "application/json"
                ),
                content_encoding="utf-8",
                delivery_mode=(
                    DeliveryMode.PERSISTENT
                ),
                message_id=(
                    prepared_message_id
                ),
                correlation_id=(
                    job_id
                    or original_correlation_id
                    or prepared_message_id
                ),
                timestamp=_utc_now(),
                type=JOB_TYPE,
                app_id=(
                    "gis-mt-sync-worker"
                ),
                headers={
                    "legal_entity_id": (
                        legal_entity_id
                    ),
                    "dead": True,
                    "error_type": (
                        error_type[:128]
                    ),
                    "error_message": (
                        error_message[:2000]
                    ),
                    "original_message_id": (
                        original_message_id
                    ),
                    "original_correlation_id": (
                        original_correlation_id
                    ),
                },
            ),
            routing_key=(
                settings
                .rabbitmq_dead_routing_key
            ),
            mandatory=True,
        )
    )

    if confirmation is False:
        raise RuntimeError(
            "RabbitMQ не подтвердил "
            "публикацию в dead queue."
        )


def _execute_job(
    *,
    token: str,
    job: SyncLegalEntityJob,
) -> Any:
    """
    Выполняется в отдельном потоке.

    Внутренний конвейер использует asyncio.run,
    поэтому его нельзя вызывать непосредственно
    из event loop RabbitMQ worker.
    """

    return sync_legal_entity(
        token=token,
        legal_entity_id=(
            job.legal_entity_id
        ),
        date_from=job.date_from,
        date_to=job.date_to,
        skip_edo=job.skip_edo,
        force_edo=job.force_edo,
        edo_fail_fast=(
            job.edo_fail_fast
        ),
        continue_on_error=(
            job.continue_on_error
        ),
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
                timeout=(
                    interval_seconds
                ),
            )

            return

        except asyncio.TimeoutError:
            pass

        try:
            await asyncio.to_thread(
                repository.heartbeat,
                job_uuid=job_id,
                worker_id=worker_id,
                lease_seconds=(
                    lease_seconds
                ),
            )

        except Exception as exc:
            typer.echo(
                "Ошибка heartbeat задания: "
                f"job_id={job_id}; "
                f"{type(exc).__name__}: "
                f"{exc}",
                err=True,
            )


async def _execute_with_heartbeat(
    *,
    repository: SyncJobRepository,
    token: str,
    job: SyncLegalEntityJob,
    worker_id: str,
    lease_seconds: int,
    heartbeat_interval_seconds: int,
) -> Any:
    stop_event = asyncio.Event()

    heartbeat_task = (
        asyncio.create_task(
            _heartbeat_loop(
                repository=repository,
                job_id=str(
                    job.job_id
                ),
                worker_id=worker_id,
                lease_seconds=(
                    lease_seconds
                ),
                interval_seconds=(
                    heartbeat_interval_seconds
                ),
                stop_event=stop_event,
            )
        )
    )

    try:
        return await asyncio.to_thread(
            _execute_job,
            token=token,
            job=job,
        )

    finally:
        stop_event.set()

        try:
            await heartbeat_task

        except asyncio.CancelledError:
            pass


async def _handle_busy_claim(
    *,
    message: IncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    repository: SyncJobRepository,
    job: SyncLegalEntityJob,
    claim: SyncJobClaim,
    queue_name: str,
) -> tuple[
    bool,
    int,
]:
    """
    Активная аренда принадлежит другому worker.

    Сообщение переносится в retry queue без
    увеличения retry_count. После TTL аренда
    уже должна истечь либо быть продлена
    действующим worker.
    """

    retry_routing_key = (
        _retry_routing_key(
            settings,
            job.legal_entity_id,
        )
    )

    retry_message_id = (
        _lease_retry_message_id(
            job
        )
    )

    await _publish_job(
        exchange=exchange,
        routing_key=(
            retry_routing_key
        ),
        job=job,
        message_id=(
            retry_message_id
        ),
        headers={
            "retry_reason": (
                "ACTIVE_LEASE"
            ),
            "worker_retry": False,
        },
    )

    await asyncio.to_thread(
        repository.mark_published,
        job_uuid=str(
            job.job_id
        ),
        queue_name=(
            _retry_queue_name(
                settings,
                job.legal_entity_id,
            )
        ),
        routing_key=(
            retry_routing_key
        ),
        message_id=(
            retry_message_id
        ),
        correlation_id=str(
            job.job_id
        ),
    )

    await message.ack()

    payload = _result_payload(
        status=(
            WorkerResultStatus
            .LEASE_RETRY
        ),
        legal_entity_id=(
            job.legal_entity_id
        ),
        job_id=str(
            job.job_id
        ),
        queue_name=queue_name,
        retry_count=(
            claim.job.retry_count
        ),
        attempt_count=(
            claim.job.attempt_count
        ),
        error_type=(
            "ACTIVE_JOB_LEASE"
        ),
        error_message=(
            claim.reason
            or (
                "Задание выполняется "
                "другим worker."
            )
        ),
    )

    typer.echo(
        _compact_json(
            payload
        )
    )

    return (
        True,
        GENERAL_RETRY_EXIT_CODE,
    )


async def _schedule_retry(
    *,
    message: IncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    repository: SyncJobRepository,
    worker_id: str,
    job: SyncLegalEntityJob,
    queue_name: str,
    exc: BaseException,
    is_auth_error: bool,
) -> tuple[
    bool,
    int,
]:
    job_id = str(
        job.job_id
    )

    error_type = type(
        exc
    ).__name__

    error_message = (
        _error_message(
            exc
        )
    )

    try:
        retry_record = (
            await asyncio.to_thread(
                repository.schedule_retry,
                job_uuid=job_id,
                worker_id=worker_id,
                delay_seconds=(
                    settings
                    .rabbitmq_retry_delay_seconds
                ),
                error_type=error_type,
                error_message=(
                    error_message
                ),
            )
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
            is_auth_error=(
                is_auth_error
            ),
        )

    retry_job = job.model_copy(
        update={
            "retry_count": (
                retry_record.retry_count
            ),
        }
    )

    retry_routing_key = (
        _retry_routing_key(
            settings,
            job.legal_entity_id,
        )
    )

    retry_queue_name = (
        _retry_queue_name(
            settings,
            job.legal_entity_id,
        )
    )

    retry_message_id = (
        _retry_message_id(
            retry_job
        )
    )

    try:
        await _publish_job(
            exchange=exchange,
            routing_key=(
                retry_routing_key
            ),
            job=retry_job,
            message_id=(
                retry_message_id
            ),
            headers={
                "retry_reason": (
                    "AUTH_ERROR"
                    if is_auth_error
                    else "PROCESSING_ERROR"
                ),
                "worker_retry": True,
                "error_type": (
                    error_type[:128]
                ),
            },
        )

        await asyncio.to_thread(
            repository.mark_published,
            job_uuid=job_id,
            queue_name=(
                retry_queue_name
            ),
            routing_key=(
                retry_routing_key
            ),
            message_id=(
                retry_message_id
            ),
            correlation_id=job_id,
        )

    except Exception as publish_exc:
        combined_error = (
            "Не удалось опубликовать "
            "повторную попытку. "
            f"Исходная ошибка: "
            f"{error_type}: "
            f"{error_message}. "
            "Ошибка публикации: "
            f"{type(publish_exc).__name__}: "
            f"{publish_exc}"
        )

        await asyncio.to_thread(
            repository.mark_dead,
            job_uuid=job_id,
            worker_id=None,
            error_type=(
                type(
                    publish_exc
                ).__name__
            ),
            error_message=(
                combined_error
            ),
            result={
                "retry_publish_failed": (
                    True
                ),
                "original_error_type": (
                    error_type
                ),
                "original_error": (
                    error_message
                ),
            },
        )

        try:
            await _publish_dead_message(
                exchange=exchange,
                settings=settings,
                legal_entity_id=(
                    job.legal_entity_id
                ),
                job_id=job_id,
                body=message.body,
                original_message_id=(
                    _message_id(
                        message
                    )
                ),
                original_correlation_id=(
                    _correlation_id(
                        message
                    )
                ),
                error_type=(
                    type(
                        publish_exc
                    ).__name__
                ),
                error_message=(
                    combined_error
                ),
            )

        except Exception as dead_publish_exc:
            typer.echo(
                "Не удалось опубликовать "
                "dead-сообщение: "
                f"{type(dead_publish_exc).__name__}: "
                f"{dead_publish_exc}",
                err=True,
            )

        await message.ack()

        payload = _result_payload(
            status=(
                WorkerResultStatus
                .AUTH_DEAD
                if is_auth_error
                else WorkerResultStatus.DEAD
            ),
            legal_entity_id=(
                job.legal_entity_id
            ),
            job_id=job_id,
            queue_name=queue_name,
            retry_count=(
                retry_record.retry_count
            ),
            attempt_count=(
                retry_record.attempt_count
            ),
            error_type=(
                type(
                    publish_exc
                ).__name__
            ),
            error_message=(
                combined_error
            ),
        )

        typer.echo(
            _compact_json(
                payload
            )
        )

        return (
            True,
            (
                AUTH_DEAD_EXIT_CODE
                if is_auth_error
                else GENERAL_DEAD_EXIT_CODE
            ),
        )

    await message.ack()

    payload = _result_payload(
        status=(
            WorkerResultStatus
            .AUTH_RETRY
            if is_auth_error
            else WorkerResultStatus.RETRY
        ),
        legal_entity_id=(
            job.legal_entity_id
        ),
        job_id=job_id,
        queue_name=queue_name,
        retry_count=(
            retry_record.retry_count
        ),
        attempt_count=(
            retry_record.attempt_count
        ),
        error_type=error_type,
        error_message=error_message,
    )

    typer.echo(
        _compact_json(
            payload
        )
    )

    return (
        True,
        (
            AUTH_RETRY_EXIT_CODE
            if is_auth_error
            else GENERAL_RETRY_EXIT_CODE
        ),
    )


async def _move_to_dead(
    *,
    message: IncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    settings: Any,
    repository: SyncJobRepository,
    worker_id: str | None,
    job: SyncLegalEntityJob,
    queue_name: str,
    exc: BaseException,
    is_auth_error: bool,
) -> tuple[
    bool,
    int,
]:
    job_id = str(
        job.job_id
    )

    error_type = type(
        exc
    ).__name__

    error_message = (
        _error_message(
            exc
        )
    )

    dead_record = (
        await asyncio.to_thread(
            repository.mark_dead,
            job_uuid=job_id,
            worker_id=worker_id,
            error_type=error_type,
            error_message=(
                error_message
            ),
            result={
                "error_type": (
                    error_type
                ),
                "error": (
                    error_message
                ),
                "retry_count": (
                    job.retry_count
                ),
            },
        )
    )

    try:
        await _publish_dead_message(
            exchange=exchange,
            settings=settings,
            legal_entity_id=(
                job.legal_entity_id
            ),
            job_id=job_id,
            body=message.body,
            original_message_id=(
                _message_id(
                    message
                )
            ),
            original_correlation_id=(
                _correlation_id(
                    message
                )
            ),
            error_type=error_type,
            error_message=(
                error_message
            ),
        )

    except Exception as publish_exc:
        typer.echo(
            "Реестр задания переведён "
            "в DEAD, но публикация "
            "в dead queue не выполнена: "
            f"{type(publish_exc).__name__}: "
            f"{publish_exc}",
            err=True,
        )

    await message.ack()

    payload = _result_payload(
        status=(
            WorkerResultStatus
            .AUTH_DEAD
            if is_auth_error
            else WorkerResultStatus.DEAD
        ),
        legal_entity_id=(
            job.legal_entity_id
        ),
        job_id=job_id,
        queue_name=queue_name,
        retry_count=(
            dead_record.retry_count
        ),
        attempt_count=(
            dead_record.attempt_count
        ),
        error_type=error_type,
        error_message=error_message,
    )

    typer.echo(
        _compact_json(
            payload
        )
    )

    return (
        True,
        (
            AUTH_DEAD_EXIT_CODE
            if is_auth_error
            else GENERAL_DEAD_EXIT_CODE
        ),
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
    queue_name: str,
    lease_seconds: int,
    heartbeat_interval_seconds: int,
) -> tuple[
    bool,
    int,
]:
    """
    Возвращает:

        should_stop
        exit_code

    Для устаревшей доставки should_stop=False:
    worker продолжает ожидать актуальное сообщение.
    """

    original_message_id = (
        _message_id(
            message
        )
    )

    original_correlation_id = (
        _correlation_id(
            message
        )
    )

    try:
        job = (
            SyncLegalEntityJob
            .model_validate_json(
                message.body
            )
        )

    except ValidationError as exc:
        error_message = (
            _error_message(
                exc
            )
        )

        try:
            await _publish_dead_message(
                exchange=exchange,
                settings=settings,
                legal_entity_id=(
                    legal_entity_id
                ),
                job_id=(
                    original_correlation_id
                ),
                body=message.body,
                original_message_id=(
                    original_message_id
                ),
                original_correlation_id=(
                    original_correlation_id
                ),
                error_type=(
                    type(exc).__name__
                ),
                error_message=(
                    error_message
                ),
            )

        finally:
            await message.ack()

        payload = _result_payload(
            status=(
                WorkerResultStatus
                .INVALID_MESSAGE
            ),
            legal_entity_id=(
                legal_entity_id
            ),
            job_id=(
                original_correlation_id
            ),
            queue_name=queue_name,
            error_type=(
                type(exc).__name__
            ),
            error_message=(
                error_message
            ),
        )

        typer.echo(
            _compact_json(
                payload
            )
        )

        return (
            True,
            GENERAL_DEAD_EXIT_CODE,
        )

    job_id = str(
        job.job_id
    )

    if (
        job.legal_entity_id
        != legal_entity_id
    ):
        exc = ValueError(
            "LEGAL_ENTITY_MISMATCH: "
            "сообщение предназначено "
            "для другой организации. "
            "Очередь организации="
            f"{legal_entity_id}; "
            "задание организации="
            f"{job.legal_entity_id}."
        )

        try:
            try:
                await asyncio.to_thread(
                    repository.mark_dead,
                    job_uuid=job_id,
                    worker_id=None,
                    error_type=(
                        type(exc).__name__
                    ),
                    error_message=(
                        str(exc)
                    ),
                    result={
                        "queue_entity_id": (
                            legal_entity_id
                        ),
                        "job_entity_id": (
                            job
                            .legal_entity_id
                        ),
                    },
                )

            except SyncJobNotFoundError:
                pass

            await _publish_dead_message(
                exchange=exchange,
                settings=settings,
                legal_entity_id=(
                    legal_entity_id
                ),
                job_id=job_id,
                body=message.body,
                original_message_id=(
                    original_message_id
                ),
                original_correlation_id=(
                    original_correlation_id
                ),
                error_type=(
                    type(exc).__name__
                ),
                error_message=str(
                    exc
                ),
            )

        finally:
            await message.ack()

        payload = _result_payload(
            status=(
                WorkerResultStatus.DEAD
            ),
            legal_entity_id=(
                legal_entity_id
            ),
            job_id=job_id,
            queue_name=queue_name,
            error_type=(
                type(exc).__name__
            ),
            error_message=str(
                exc
            ),
        )

        typer.echo(
            _compact_json(
                payload
            )
        )

        return (
            True,
            GENERAL_DEAD_EXIT_CODE,
        )

    typer.echo(
        "Получено задание: "
        f"job_id={job_id}; "
        "entity_id="
        f"{job.legal_entity_id}; "
        "retry_count="
        f"{job.retry_count}."
    )

    try:
        claim = await asyncio.to_thread(
            repository.claim_job,
            job_uuid=job_id,
            worker_id=worker_id,
            lease_seconds=(
                lease_seconds
            ),
            message_id=(
                original_message_id
            ),
            correlation_id=(
                original_correlation_id
            ),
            expected_retry_count=(
                job.retry_count
            ),
        )

    except SyncJobNotFoundError as exc:
        try:
            await _publish_dead_message(
                exchange=exchange,
                settings=settings,
                legal_entity_id=(
                    legal_entity_id
                ),
                job_id=job_id,
                body=message.body,
                original_message_id=(
                    original_message_id
                ),
                original_correlation_id=(
                    original_correlation_id
                ),
                error_type=(
                    type(exc).__name__
                ),
                error_message=(
                    _error_message(
                        exc
                    )
                ),
            )

        finally:
            await message.ack()

        payload = _result_payload(
            status=(
                WorkerResultStatus.DEAD
            ),
            legal_entity_id=(
                legal_entity_id
            ),
            job_id=job_id,
            queue_name=queue_name,
            error_type=(
                type(exc).__name__
            ),
            error_message=(
                _error_message(
                    exc
                )
            ),
        )

        typer.echo(
            _compact_json(
                payload
            )
        )

        return (
            True,
            GENERAL_DEAD_EXIT_CODE,
        )

    except SyncJobStateError as exc:
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
        typer.echo(
            "Устаревшая доставка "
            "подтверждена без выполнения: "
            f"job_id={job_id}; "
            f"{claim.reason or '-'}"
        )

        await message.ack()

        return (
            False,
            SUCCESS_EXIT_CODE,
        )

    if claim.outcome == "BUSY":
        return await _handle_busy_claim(
            message=message,
            exchange=exchange,
            settings=settings,
            repository=repository,
            job=job,
            claim=claim,
            queue_name=queue_name,
        )

    if claim.outcome == "TERMINAL":
        await message.ack()

        if claim.job.status == "SUCCESS":
            payload = _result_payload(
                status=(
                    WorkerResultStatus
                    .ALREADY_SUCCESS
                ),
                legal_entity_id=(
                    legal_entity_id
                ),
                job_id=job_id,
                queue_name=queue_name,
                retry_count=(
                    claim.job.retry_count
                ),
                attempt_count=(
                    claim.job.attempt_count
                ),
                result=(
                    claim.job.result
                ),
            )

            typer.echo(
                _compact_json(
                    payload
                )
            )

            return (
                True,
                SUCCESS_EXIT_CODE,
            )

        status = (
            WorkerResultStatus
            .CANCELLED
            if (
                claim.job.status
                == "CANCELLED"
            )
            else WorkerResultStatus.DEAD
        )

        payload = _result_payload(
            status=status,
            legal_entity_id=(
                legal_entity_id
            ),
            job_id=job_id,
            queue_name=queue_name,
            retry_count=(
                claim.job.retry_count
            ),
            attempt_count=(
                claim.job.attempt_count
            ),
            error_type=(
                claim.job
                .last_error_type
            ),
            error_message=(
                claim.job
                .last_error_message
            ),
            result=(
                claim.job.result
            ),
        )

        typer.echo(
            _compact_json(
                payload
            )
        )

        return (
            True,
            GENERAL_DEAD_EXIT_CODE,
        )

    if claim.outcome != "CLAIMED":
        exc = RuntimeError(
            "Неизвестный результат "
            "захвата задания: "
            f"{claim.outcome}."
        )

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

    typer.echo(
        "Задание захвачено: "
        f"job_id={job_id}; "
        f"worker_id={worker_id}; "
        "attempt_count="
        f"{claim.job.attempt_count}; "
        "retry_count="
        f"{claim.job.retry_count}."
    )

    try:
        execution_result = (
            await _execute_with_heartbeat(
                repository=repository,
                token=token,
                job=job,
                worker_id=worker_id,
                lease_seconds=(
                    lease_seconds
                ),
                heartbeat_interval_seconds=(
                    heartbeat_interval_seconds
                ),
            )
        )

        result_object = (
            _json_safe_object(
                execution_result
            )
        )

        result_object[
            "completed_at"
        ] = (
            _utc_now()
            .isoformat()
        )

        success_record = (
            await asyncio.to_thread(
                repository.mark_success,
                job_uuid=job_id,
                worker_id=worker_id,
                result=result_object,
            )
        )

        await message.ack()

        typer.echo(
            "Задание выполнено успешно: "
            f"job_id={job_id}."
        )

        payload = _result_payload(
            status=(
                WorkerResultStatus.SUCCESS
            ),
            legal_entity_id=(
                legal_entity_id
            ),
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

        typer.echo(
            _compact_json(
                payload
            )
        )

        return (
            True,
            SUCCESS_EXIT_CODE,
        )

    except GisMtAuthError as exc:
        current_record = (
            await asyncio.to_thread(
                repository.require_job,
                job_id,
            )
        )

        if (
            current_record.retry_count
            >= current_record.max_retries
        ):
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
        current_record = (
            await asyncio.to_thread(
                repository.require_job,
                job_id,
            )
        )

        if (
            current_record.retry_count
            >= current_record.max_retries
        ):
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
    once: bool,
    lease_seconds: int,
    heartbeat_interval_seconds: int,
) -> int:
    settings = get_settings()

    queue_name = _sync_queue_name(
        settings,
        legal_entity_id,
    )

    repository = SyncJobRepository(
        Database(
            settings
        )
    )

    worker_id = _worker_id(
        legal_entity_id
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
                    f"{settings.rabbitmq_connection_name}"
                    f":worker:{legal_entity_id}"
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

        await channel.set_qos(
            prefetch_count=1
        )

        (
            exchange,
            sync_queue,
        ) = await _declare_topology(
            channel=channel,
            settings=settings,
            legal_entity_id=(
                legal_entity_id
            ),
        )

        typer.echo(
            "RabbitMQ worker запущен."
        )

        typer.echo(
            "Организация: "
            f"{legal_entity_id}"
        )

        typer.echo(
            "Очередь: "
            f"{queue_name}"
        )

        typer.echo(
            "Worker ID: "
            f"{worker_id}"
        )

        typer.echo(
            "Режим: "
            + (
                "одно итоговое задание"
                if once
                else "постоянный consumer"
            )
        )

        typer.echo("")

        async with (
            sync_queue.iterator()
            as queue_iterator
        ):
            async for message in (
                queue_iterator
            ):
                (
                    should_stop,
                    exit_code,
                ) = await _process_message(
                    message=message,
                    exchange=exchange,
                    settings=settings,
                    repository=repository,
                    token=token,
                    worker_id=worker_id,
                    legal_entity_id=(
                        legal_entity_id
                    ),
                    queue_name=queue_name,
                    lease_seconds=(
                        lease_seconds
                    ),
                    heartbeat_interval_seconds=(
                        heartbeat_interval_seconds
                    ),
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
        help=(
            "ID организации, очередь которой "
            "должен обслуживать worker."
        ),
    ),

    once: bool = typer.Option(
        False,
        "--once",
        help=(
            "Завершить worker после одного "
            "итогового задания. Устаревшие "
            "доставки не считаются итоговыми."
        ),
    ),

    lease_seconds: int = typer.Option(
        DEFAULT_JOB_LEASE_SECONDS,
        "--lease-seconds",
        min=60,
        max=86400,
        help=(
            "Продолжительность аренды задания "
            "worker-ом в секундах."
        ),
    ),

    heartbeat_interval_seconds: int = (
        typer.Option(
            DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
            "--heartbeat-interval-seconds",
            min=10,
            max=3600,
            help=(
                "Интервал продления аренды "
                "задания в секундах."
            ),
        )
    ),
) -> None:
    if (
        heartbeat_interval_seconds
        >= lease_seconds
    ):
        typer.echo(
            "ERROR: heartbeat interval должен "
            "быть меньше lease_seconds.",
            err=True,
        )

        raise typer.Exit(
            code=WORKER_ERROR_EXIT_CODE
        )

    token = read_token_from_stdin()

    try:
        exit_code = asyncio.run(
            run_worker(
                token=token,
                legal_entity_id=(
                    entity_id
                ),
                once=once,
                lease_seconds=(
                    lease_seconds
                ),
                heartbeat_interval_seconds=(
                    heartbeat_interval_seconds
                ),
            )
        )

    except KeyboardInterrupt:
        typer.echo(
            "RabbitMQ worker остановлен."
        )

        raise typer.Exit(
            code=130
        )

    except Exception as exc:
        payload = _result_payload(
            status=(
                WorkerResultStatus
                .WORKER_ERROR
            ),
            legal_entity_id=(
                entity_id
            ),
            job_id=None,
            queue_name="",
            error_type=(
                type(exc).__name__
            ),
            error_message=(
                _error_message(
                    exc
                )
            ),
        )

        typer.echo(
            _compact_json(
                payload
            ),
            err=True,
        )

        raise typer.Exit(
            code=WORKER_ERROR_EXIT_CODE
        ) from exc

    if exit_code != SUCCESS_EXIT_CODE:
        raise typer.Exit(
            code=exit_code
        )


if __name__ == "__main__":
    typer.run(main)