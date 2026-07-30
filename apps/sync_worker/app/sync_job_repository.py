from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from mysql.connector import IntegrityError
from mysql.connector.connection import MySQLConnection

from app.db import Database


TERMINAL_STATUSES = frozenset(
    {
        "SUCCESS",
        "DEAD",
        "CANCELLED",
    }
)

ACTIVE_STATUSES = frozenset(
    {
        "CREATED",
        "PUBLISHED",
        "PROCESSING",
        "RETRY_WAIT",
    }
)


class SyncJobRepositoryError(RuntimeError):
    """
    Базовая ошибка реестра заданий.
    """


class SyncJobNotFoundError(SyncJobRepositoryError):
    """
    Задание с указанным UUID не найдено.
    """


class ActiveSyncJobExistsError(SyncJobRepositoryError):
    """
    Для организации уже существует
    активное задание.
    """

    def __init__(
        self,
        *,
        legal_entity_id: int,
        job_type: str,
        active_job_uuid: str,
        active_status: str,
    ) -> None:
        self.legal_entity_id = legal_entity_id
        self.job_type = job_type
        self.active_job_uuid = active_job_uuid
        self.active_status = active_status

        super().__init__(
            "Для организации уже существует "
            "активное задание этого типа: "
            f"legal_entity_id={legal_entity_id}; "
            f"job_type={job_type}; "
            f"job_id={active_job_uuid}; "
            f"status={active_status}."
        )


class SyncJobPayloadConflictError(
    SyncJobRepositoryError
):
    """
    Один job_uuid был использован
    с различающимися данными.
    """


class SyncJobStateError(SyncJobRepositoryError):
    """
    Операция недопустима для текущего
    состояния задания.
    """


class SyncJobWorkerConflictError(
    SyncJobRepositoryError
):
    """
    Задание принадлежит другому worker.
    """


class SyncJobRetryLimitError(
    SyncJobRepositoryError
):
    """
    Лимит повторных попыток исчерпан.
    """


ClaimOutcome = Literal[
    "CLAIMED",
    "TERMINAL",
    "BUSY",
    "STALE",
]


@dataclass(
    frozen=True,
    slots=True,
)
class SyncJobRecord:
    id: int
    job_uuid: str
    schema_version: int
    job_type: str
    parent_job_uuid: str | None
    legal_entity_id: int

    requested_by: str
    requested_at: datetime

    date_from: datetime | None
    date_to: datetime | None

    skip_edo: bool
    force_edo: bool
    edo_fail_fast: bool
    continue_on_error: bool

    payload: dict[str, Any]

    status: str
    retry_count: int
    max_retries: int
    attempt_count: int

    queue_name: str | None
    routing_key: str | None
    last_message_id: str | None
    correlation_id: str | None
    worker_id: str | None

    first_started_at: datetime | None
    last_started_at: datetime | None
    last_heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    retry_available_at: datetime | None
    published_at: datetime | None
    finished_at: datetime | None

    last_error_type: str | None
    last_error_message: str | None
    result: dict[str, Any] | None

    lock_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class SyncJobClaim:
    outcome: ClaimOutcome
    job: SyncJobRecord
    reason: str | None = None


def _canonical_json(
    value: Any,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_json_object(
    value: Any,
) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if isinstance(value, bytes):
        value = value.decode("utf-8")

    if isinstance(value, str):
        decoded = json.loads(value)

        if not isinstance(decoded, dict):
            raise SyncJobRepositoryError(
                "JSON задания должен содержать объект."
            )

        return decoded

    raise SyncJobRepositoryError(
        "Неподдерживаемый тип JSON-поля: "
        f"{type(value).__name__}."
    )


def _decode_optional_json_object(
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None

    return _decode_json_object(value)


def _safe_error_text(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    prepared = value.strip()

    if not prepared:
        return None

    return prepared[:2000]


def _safe_error_type(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    prepared = value.strip()

    if not prepared:
        return None

    return prepared[:128]


def _row_to_record(
    row: dict[str, Any],
) -> SyncJobRecord:
    return SyncJobRecord(
        id=int(row["id"]),
        job_uuid=str(row["job_uuid"]),
        schema_version=int(row["schema_version"]),
        job_type=str(row["job_type"]),
        parent_job_uuid=(
            str(row["parent_job_uuid"])
            if row.get("parent_job_uuid") is not None
            else None
        ),
        legal_entity_id=int(
            row["legal_entity_id"]
        ),
        requested_by=str(row["requested_by"]),
        requested_at=row["requested_at"],
        date_from=row["date_from"],
        date_to=row["date_to"],
        skip_edo=bool(row["skip_edo"]),
        force_edo=bool(row["force_edo"]),
        edo_fail_fast=bool(
            row["edo_fail_fast"]
        ),
        continue_on_error=bool(
            row["continue_on_error"]
        ),
        payload=_decode_json_object(
            row["payload_json"]
        ),
        status=str(row["status"]),
        retry_count=int(row["retry_count"]),
        max_retries=int(row["max_retries"]),
        attempt_count=int(row["attempt_count"]),
        queue_name=(
            str(row["queue_name"])
            if row["queue_name"] is not None
            else None
        ),
        routing_key=(
            str(row["routing_key"])
            if row["routing_key"] is not None
            else None
        ),
        last_message_id=(
            str(row["last_message_id"])
            if row["last_message_id"] is not None
            else None
        ),
        correlation_id=(
            str(row["correlation_id"])
            if row["correlation_id"] is not None
            else None
        ),
        worker_id=(
            str(row["worker_id"])
            if row["worker_id"] is not None
            else None
        ),
        first_started_at=row[
            "first_started_at"
        ],
        last_started_at=row[
            "last_started_at"
        ],
        last_heartbeat_at=row[
            "last_heartbeat_at"
        ],
        lease_expires_at=row[
            "lease_expires_at"
        ],
        retry_available_at=row[
            "retry_available_at"
        ],
        published_at=row["published_at"],
        finished_at=row["finished_at"],
        last_error_type=(
            str(row["last_error_type"])
            if row["last_error_type"] is not None
            else None
        ),
        last_error_message=(
            str(row["last_error_message"])
            if row["last_error_message"]
            is not None
            else None
        ),
        result=_decode_optional_json_object(
            row["result_json"]
        ),
        lock_version=int(row["lock_version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SyncJobRepository:
    """
    Постоянный реестр RabbitMQ-заданий.

    Реестр обеспечивает:

    - идемпотентную регистрацию job_uuid;
    - одно активное задание на организацию;
    - атомарный захват задания worker-ом;
    - защиту от повторной доставки;
    - фиксацию retry, success и dead;
    - хранение результата и ошибок.
    """

    def __init__(
        self,
        database: Database,
    ) -> None:
        self._database = database

    @staticmethod
    def _select_job_for_update(
        connection: MySQLConnection,
        job_uuid: str,
    ) -> dict[str, Any] | None:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    *
                FROM sys_sync_job
                WHERE job_uuid = %s
                LIMIT 1
                FOR UPDATE
                """,
                (job_uuid,),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

        if row is None:
            return None

        return dict(row)

    @staticmethod
    def _select_job(
        connection: MySQLConnection,
        job_uuid: str,
    ) -> dict[str, Any] | None:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    *
                FROM sys_sync_job
                WHERE job_uuid = %s
                LIMIT 1
                """,
                (job_uuid,),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

        if row is None:
            return None

        return dict(row)

    @staticmethod
    def _select_active_job_for_entity(
        connection: MySQLConnection,
        legal_entity_id: int,
        job_type: str,
    ) -> dict[str, Any] | None:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    *
                FROM sys_sync_job
                WHERE active_job_key = CONCAT(%s, ':', %s)
                LIMIT 1
                """,
                (
                    job_type,
                    legal_entity_id,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

        if row is None:
            return None

        return dict(row)

    def get_job(
        self,
        job_uuid: str,
    ) -> SyncJobRecord | None:
        with self._database.transaction() as connection:
            row = self._select_job(
                connection,
                job_uuid,
            )

        if row is None:
            return None

        return _row_to_record(row)

    def require_job(
        self,
        job_uuid: str,
    ) -> SyncJobRecord:
        job = self.get_job(job_uuid)

        if job is None:
            raise SyncJobNotFoundError(
                f"Задание job_id={job_uuid} "
                "не найдено."
            )

        return job

    def get_active_job_for_entity(
        self,
        legal_entity_id: int,
        job_type: str,
    ) -> SyncJobRecord | None:
        if legal_entity_id < 1:
            raise ValueError(
                "legal_entity_id должен быть "
                "больше 0."
            )

        prepared_job_type = job_type.strip().upper()

        if not prepared_job_type:
            raise ValueError(
                "job_type не может быть пустым."
            )

        with self._database.transaction() as connection:
            row = (
                self._select_active_job_for_entity(
                    connection,
                    legal_entity_id,
                    prepared_job_type,
                )
            )

        if row is None:
            return None

        return _row_to_record(row)

    def register_job(
        self,
        *,
        job_uuid: str,
        schema_version: int,
        job_type: str,
        parent_job_uuid: str | None,
        legal_entity_id: int,
        requested_by: str,
        requested_at: datetime,
        date_from: datetime | None,
        date_to: datetime | None,
        skip_edo: bool,
        force_edo: bool,
        edo_fail_fast: bool,
        continue_on_error: bool,
        payload: dict[str, Any],
        max_retries: int,
    ) -> SyncJobRecord:
        """
        Регистрирует задание до публикации.

        Повторный вызов с тем же job_uuid
        и тем же payload является идемпотентным.
        """

        prepared_job_uuid = job_uuid.strip()
        prepared_job_type = (
            job_type.strip().upper()
        )
        prepared_requested_by = (
            requested_by.strip()
        )

        if not prepared_job_uuid:
            raise ValueError(
                "job_uuid не может быть пустым."
            )

        if schema_version < 1:
            raise ValueError(
                "schema_version должен быть "
                "больше 0."
            )

        supported_job_types = {
            "SYNC_LEGAL_ENTITY",
            "EXPORT_UPD",
            "PROCESS_UPD",
            "TRACK_VIOLATIONS",
        }

        if prepared_job_type not in supported_job_types:
            raise ValueError(
                "Неподдерживаемый job_type: "
                f"{prepared_job_type}."
            )

        prepared_parent_job_uuid = (
            parent_job_uuid.strip()
            if parent_job_uuid is not None
            else None
        )

        if prepared_parent_job_uuid == "":
            prepared_parent_job_uuid = None

        if legal_entity_id < 1:
            raise ValueError(
                "legal_entity_id должен быть "
                "больше 0."
            )

        if not prepared_requested_by:
            raise ValueError(
                "requested_by не может быть пустым."
            )

        if max_retries < 0:
            raise ValueError(
                "max_retries не может быть "
                "отрицательным."
            )

        payload_json = _canonical_json(payload)

        try:
            with self._database.transaction() as connection:
                cursor = connection.cursor()

                try:
                    cursor.execute(
                        """
                        INSERT INTO sys_sync_job (
                            job_uuid,
                            schema_version,
                            job_type,
                            parent_job_uuid,
                            legal_entity_id,
                            requested_by,
                            requested_at,
                            date_from,
                            date_to,
                            skip_edo,
                            force_edo,
                            edo_fail_fast,
                            continue_on_error,
                            payload_json,
                            status,
                            retry_count,
                            max_retries,
                            attempt_count,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            CAST(%s AS JSON),
                            'CREATED',
                            0,
                            %s,
                            0,
                            UTC_TIMESTAMP(6),
                            UTC_TIMESTAMP(6)
                        )
                        """,
                        (
                            prepared_job_uuid,
                            schema_version,
                            prepared_job_type,
                            prepared_parent_job_uuid,
                            legal_entity_id,
                            prepared_requested_by,
                            requested_at,
                            date_from,
                            date_to,
                            int(skip_edo),
                            int(force_edo),
                            int(edo_fail_fast),
                            int(
                                continue_on_error
                            ),
                            payload_json,
                            max_retries,
                        ),
                    )

                finally:
                    cursor.close()

        except IntegrityError as exc:
            if exc.errno != 1062:
                raise

            existing = self.get_job(
                prepared_job_uuid
            )

            if existing is not None:
                if (
                    _canonical_json(
                        existing.payload
                    )
                    != payload_json
                ):
                    raise (
                        SyncJobPayloadConflictError(
                            "Задание с job_id="
                            f"{prepared_job_uuid} "
                            "уже существует с другим "
                            "payload."
                        )
                    ) from exc

                return existing

            active_job = (
                self.get_active_job_for_entity(
                    legal_entity_id,
                    prepared_job_type,
                )
            )

            if active_job is not None:
                raise ActiveSyncJobExistsError(
                    legal_entity_id=(
                        legal_entity_id
                    ),
                    job_type=prepared_job_type,
                    active_job_uuid=(
                        active_job.job_uuid
                    ),
                    active_status=(
                        active_job.status
                    ),
                ) from exc

            raise

        return self.require_job(
            prepared_job_uuid
        )

    def mark_published(
        self,
        *,
        job_uuid: str,
        queue_name: str,
        routing_key: str,
        message_id: str,
        correlation_id: str,
    ) -> SyncJobRecord:
        """
        Фиксирует успешную публикацию сообщения.

        Статус не откатывается назад, если worker
        уже успел захватить сообщение.
        """

        with self._database.transaction() as connection:
            row = self._select_job_for_update(
                connection,
                job_uuid,
            )

            if row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "не найдено."
                )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_job
                       SET status =
                           CASE
                               WHEN status = 'CREATED'
                                   THEN 'PUBLISHED'
                               ELSE status
                           END,

                           queue_name = %s,
                           routing_key = %s,
                           last_message_id = %s,
                           correlation_id = %s,

                           published_at =
                               COALESCE(
                                   published_at,
                                   UTC_TIMESTAMP(6)
                               ),

                           lock_version =
                               lock_version + 1,

                           updated_at =
                               UTC_TIMESTAMP(6)

                     WHERE job_uuid = %s
                    """,
                    (
                        queue_name,
                        routing_key,
                        message_id,
                        correlation_id,
                        job_uuid,
                    ),
                )

            finally:
                cursor.close()

        return self.require_job(job_uuid)

    def claim_job(
        self,
        *,
        job_uuid: str,
        worker_id: str,
        lease_seconds: int,
        message_id: str | None,
        correlation_id: str | None,
        expected_retry_count: int | None = None,
    ) -> SyncJobClaim:
        """
        Атомарно захватывает задание worker-ом.

        Повторная доставка завершённого задания
        возвращает TERMINAL и не запускает
        синхронизацию повторно.
        """

        prepared_worker_id = worker_id.strip()

        if not prepared_worker_id:
            raise ValueError(
                "worker_id не может быть пустым."
            )

        if lease_seconds < 1:
            raise ValueError(
                "lease_seconds должен быть "
                "больше 0."
            )

        with self._database.transaction() as connection:
            row = self._select_job_for_update(
                connection,
                job_uuid,
            )

            if row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "не найдено."
                )

            job = _row_to_record(row)

            if (
                expected_retry_count is not None
                and expected_retry_count
                < job.retry_count
            ):
                return SyncJobClaim(
                    outcome="STALE",
                    job=job,
                    reason=(
                        "Получена устаревшая доставка: "
                        "retry_count сообщения="
                        f"{expected_retry_count}; "
                        "retry_count реестра="
                        f"{job.retry_count}."
                    ),
                )

            if (
                expected_retry_count is not None
                and expected_retry_count
                > job.retry_count
            ):
                raise SyncJobStateError(
                    "retry_count сообщения больше "
                    "значения в реестре: "
                    f"message={expected_retry_count}; "
                    f"ledger={job.retry_count}."
                )

            if job.status in TERMINAL_STATUSES:
                return SyncJobClaim(
                    outcome="TERMINAL",
                    job=job,
                    reason=(
                        "Задание уже находится "
                        "в конечном состоянии."
                    ),
                )

            cursor = connection.cursor(
                dictionary=True
            )

            try:
                cursor.execute(
                    """
                    SELECT
                        lease_expires_at
                            IS NOT NULL
                        AND lease_expires_at
                            > UTC_TIMESTAMP(6)
                            AS lease_is_active
                    FROM sys_sync_job
                    WHERE job_uuid = %s
                    LIMIT 1
                    """,
                    (job_uuid,),
                )

                lease_row = cursor.fetchone()

            finally:
                cursor.close()

            lease_is_active = bool(
                lease_row
                and lease_row[
                    "lease_is_active"
                ]
            )

            if (
                job.status == "PROCESSING"
                and lease_is_active
                and job.worker_id
                != prepared_worker_id
            ):
                return SyncJobClaim(
                    outcome="BUSY",
                    job=job,
                    reason=(
                        "Задание уже выполняется "
                        "другим worker."
                    ),
                )

            if job.status not in ACTIVE_STATUSES:
                raise SyncJobStateError(
                    "Невозможно захватить задание "
                    f"в состоянии {job.status}."
                )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_job
                       SET status = 'PROCESSING',

                           worker_id = %s,

                           attempt_count =
                               attempt_count + 1,

                           first_started_at =
                               COALESCE(
                                   first_started_at,
                                   UTC_TIMESTAMP(6)
                               ),

                           last_started_at =
                               UTC_TIMESTAMP(6),

                           last_heartbeat_at =
                               UTC_TIMESTAMP(6),

                           lease_expires_at =
                               TIMESTAMPADD(
                                   SECOND,
                                   %s,
                                   UTC_TIMESTAMP(6)
                               ),

                           retry_available_at = NULL,

                           last_message_id =
                               COALESCE(
                                   %s,
                                   last_message_id
                               ),

                           correlation_id =
                               COALESCE(
                                   %s,
                                   correlation_id
                               ),

                           last_error_type = NULL,
                           last_error_message = NULL,

                           lock_version =
                               lock_version + 1,

                           updated_at =
                               UTC_TIMESTAMP(6)

                     WHERE job_uuid = %s
                    """,
                    (
                        prepared_worker_id,
                        lease_seconds,
                        message_id,
                        correlation_id,
                        job_uuid,
                    ),
                )

            finally:
                cursor.close()

            updated_row = (
                self._select_job_for_update(
                    connection,
                    job_uuid,
                )
            )

            if updated_row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "исчезло после захвата."
                )

            claimed_job = _row_to_record(
                updated_row
            )

        return SyncJobClaim(
            outcome="CLAIMED",
            job=claimed_job,
        )

    def heartbeat(
        self,
        *,
        job_uuid: str,
        worker_id: str,
        lease_seconds: int,
    ) -> SyncJobRecord:
        """
        Продлевает аренду выполняемого задания.
        """

        if lease_seconds < 1:
            raise ValueError(
                "lease_seconds должен быть "
                "больше 0."
            )

        with self._database.transaction() as connection:
            row = self._select_job_for_update(
                connection,
                job_uuid,
            )

            if row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "не найдено."
                )

            job = _row_to_record(row)

            if job.status != "PROCESSING":
                raise SyncJobStateError(
                    "Heartbeat допустим только "
                    "для PROCESSING. "
                    f"Текущий статус: {job.status}."
                )

            if job.worker_id != worker_id:
                raise SyncJobWorkerConflictError(
                    "Heartbeat отклонён: задание "
                    "принадлежит другому worker."
                )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_job
                       SET last_heartbeat_at =
                               UTC_TIMESTAMP(6),

                           lease_expires_at =
                               TIMESTAMPADD(
                                   SECOND,
                                   %s,
                                   UTC_TIMESTAMP(6)
                               ),

                           lock_version =
                               lock_version + 1,

                           updated_at =
                               UTC_TIMESTAMP(6)

                     WHERE job_uuid = %s
                    """,
                    (
                        lease_seconds,
                        job_uuid,
                    ),
                )

            finally:
                cursor.close()

        return self.require_job(job_uuid)

    def mark_success(
        self,
        *,
        job_uuid: str,
        worker_id: str,
        result: dict[str, Any],
    ) -> SyncJobRecord:
        """
        Завершает задание успешно.
        """

        result_json = _canonical_json(result)

        with self._database.transaction() as connection:
            row = self._select_job_for_update(
                connection,
                job_uuid,
            )

            if row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "не найдено."
                )

            job = _row_to_record(row)

            if job.status == "SUCCESS":
                return job

            if job.status in {
                "DEAD",
                "CANCELLED",
            }:
                raise SyncJobStateError(
                    "Нельзя перевести задание "
                    f"из {job.status} в SUCCESS."
                )

            if (
                job.status == "PROCESSING"
                and job.worker_id != worker_id
            ):
                raise SyncJobWorkerConflictError(
                    "Завершение отклонено: задание "
                    "принадлежит другому worker."
                )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_job
                       SET status = 'SUCCESS',
                           result_json =
                               CAST(%s AS JSON),
                           finished_at =
                               UTC_TIMESTAMP(6),
                           last_heartbeat_at =
                               UTC_TIMESTAMP(6),
                           lease_expires_at = NULL,
                           retry_available_at = NULL,
                           last_error_type = NULL,
                           last_error_message = NULL,
                           lock_version =
                               lock_version + 1,
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE job_uuid = %s
                    """,
                    (
                        result_json,
                        job_uuid,
                    ),
                )

            finally:
                cursor.close()

        return self.require_job(job_uuid)

    def schedule_retry(
        self,
        *,
        job_uuid: str,
        worker_id: str,
        delay_seconds: int,
        error_type: str,
        error_message: str,
    ) -> SyncJobRecord:
        """
        Переводит задание в RETRY_WAIT
        и увеличивает retry_count.
        """

        if delay_seconds < 1:
            raise ValueError(
                "delay_seconds должен быть "
                "больше 0."
            )

        with self._database.transaction() as connection:
            row = self._select_job_for_update(
                connection,
                job_uuid,
            )

            if row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "не найдено."
                )

            job = _row_to_record(row)

            if job.status in TERMINAL_STATUSES:
                return job

            if (
                job.status == "PROCESSING"
                and job.worker_id != worker_id
            ):
                raise SyncJobWorkerConflictError(
                    "Retry отклонён: задание "
                    "принадлежит другому worker."
                )

            next_retry_count = (
                job.retry_count + 1
            )

            if (
                next_retry_count
                > job.max_retries
            ):
                raise SyncJobRetryLimitError(
                    "Лимит повторных попыток "
                    "исчерпан: "
                    f"retry_count={job.retry_count}; "
                    f"max_retries={job.max_retries}."
                )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_job
                       SET status = 'RETRY_WAIT',
                           retry_count = %s,

                           retry_available_at =
                               TIMESTAMPADD(
                                   SECOND,
                                   %s,
                                   UTC_TIMESTAMP(6)
                               ),

                           lease_expires_at = NULL,
                           worker_id = NULL,

                           last_error_type = %s,
                           last_error_message = %s,

                           lock_version =
                               lock_version + 1,

                           updated_at =
                               UTC_TIMESTAMP(6)

                     WHERE job_uuid = %s
                    """,
                    (
                        next_retry_count,
                        delay_seconds,
                        _safe_error_type(
                            error_type
                        ),
                        _safe_error_text(
                            error_message
                        ),
                        job_uuid,
                    ),
                )

            finally:
                cursor.close()

        return self.require_job(job_uuid)

    def mark_dead(
        self,
        *,
        job_uuid: str,
        worker_id: str | None,
        error_type: str,
        error_message: str,
        result: dict[str, Any] | None = None,
    ) -> SyncJobRecord:
        """
        Переводит задание в DEAD.
        """

        result_json = (
            _canonical_json(result)
            if result is not None
            else None
        )

        with self._database.transaction() as connection:
            row = self._select_job_for_update(
                connection,
                job_uuid,
            )

            if row is None:
                raise SyncJobNotFoundError(
                    f"Задание job_id={job_uuid} "
                    "не найдено."
                )

            job = _row_to_record(row)

            if job.status == "DEAD":
                return job

            if job.status in {
                "SUCCESS",
                "CANCELLED",
            }:
                raise SyncJobStateError(
                    "Нельзя перевести задание "
                    f"из {job.status} в DEAD."
                )

            if (
                job.status == "PROCESSING"
                and worker_id is not None
                and job.worker_id != worker_id
            ):
                raise SyncJobWorkerConflictError(
                    "Завершение DEAD отклонено: "
                    "задание принадлежит другому "
                    "worker."
                )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_job
                       SET status = 'DEAD',

                           result_json =
                               CASE
                                   WHEN %s IS NULL
                                       THEN result_json
                                   ELSE CAST(%s AS JSON)
                               END,

                           finished_at =
                               UTC_TIMESTAMP(6),

                           lease_expires_at = NULL,
                           retry_available_at = NULL,

                           last_error_type = %s,
                           last_error_message = %s,

                           lock_version =
                               lock_version + 1,

                           updated_at =
                               UTC_TIMESTAMP(6)

                     WHERE job_uuid = %s
                    """,
                    (
                        result_json,
                        result_json,
                        _safe_error_type(
                            error_type
                        ),
                        _safe_error_text(
                            error_message
                        ),
                        job_uuid,
                    ),
                )

            finally:
                cursor.close()

        return self.require_job(job_uuid)