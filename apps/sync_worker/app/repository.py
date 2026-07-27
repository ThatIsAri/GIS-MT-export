from __future__ import annotations

import hashlib
import json
import uuid

from app.db import Database
from app.models import ApiResult


class Repository:
    """
    Репозиторий служебных запусков,
    HTTP-запросов и RAW-ответов True API.
    """

    def __init__(
        self,
        database: Database,
    ) -> None:
        self._database = database

    @staticmethod
    def _prepare_job_type(
        value: str,
    ) -> str:
        prepared = value.strip().upper()

        if not prepared:
            raise ValueError(
                "Тип задания не может быть пустым."
            )

        if len(prepared) > 64:
            raise ValueError(
                "Тип задания не может быть длиннее "
                "64 символов."
            )

        return prepared

    @staticmethod
    def _prepare_product_group(
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        prepared = value.strip().lower()

        if not prepared:
            return None

        if len(prepared) > 64:
            raise ValueError(
                "Товарная группа не может быть длиннее "
                "64 символов."
            )

        return prepared

    def start_run(
        self,
        *,
        job_type: str,
        date_from: str | None = None,
        date_to: str | None = None,
        legal_entity_id: int | None = None,
        product_group: str | None = None,
    ) -> tuple[int, str]:
        """
        Создаёт служебный запуск.

        Для запуска, относящегося к товарной группе,
        обязательно передаётся legal_entity_id.

        Старые и общесистемные задания могут
        запускаться без области организации.
        """

        prepared_job_type = self._prepare_job_type(
            job_type
        )

        prepared_product_group = (
            self._prepare_product_group(
                product_group
            )
        )

        if (
            legal_entity_id is not None
            and legal_entity_id < 1
        ):
            raise ValueError(
                "legal_entity_id должен быть больше 0."
            )

        if (
            prepared_product_group is not None
            and legal_entity_id is None
        ):
            raise ValueError(
                "Для запуска товарной группы необходимо "
                "указать legal_entity_id."
            )

        run_uuid = str(
            uuid.uuid4()
        )

        with self._database.transaction() as connection:
            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO sys_sync_run (
                        legal_entity_id,
                        run_uuid,
                        job_type,
                        product_group,
                        status,
                        date_from,
                        date_to,
                        started_at,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        'STARTED',
                        %s,
                        %s,
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        legal_entity_id,
                        run_uuid,
                        prepared_job_type,
                        prepared_product_group,
                        date_from,
                        date_to,
                    ),
                )

                run_id = int(
                    cursor.lastrowid
                )

            finally:
                cursor.close()

        return (
            run_id,
            run_uuid,
        )

    def get_run_scope(
        self,
        *,
        run_id: int,
    ) -> dict[str, object]:
        """
        Возвращает область существующего запуска.

        Метод используется этапами CORE и ЭДО,
        чтобы работать в области той же организации
        и товарной группы, что и RAW-загрузка.
        """

        if run_id < 1:
            raise ValueError(
                "run_id должен быть больше 0."
            )

        connection = self._database.connect()

        try:
            cursor = connection.cursor(
                dictionary=True
            )

            try:
                cursor.execute(
                    """
                    SELECT
                        id,
                        run_uuid,
                        legal_entity_id,
                        job_type,
                        product_group,
                        status,
                        date_from,
                        date_to,
                        records_received,
                        error_code,
                        error_message,
                        started_at,
                        finished_at,
                        created_at
                    FROM sys_sync_run
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (
                        run_id,
                    ),
                )

                row = cursor.fetchone()

            finally:
                cursor.close()

        finally:
            connection.close()

        if row is None:
            raise ValueError(
                "Служебный запуск "
                f"id={run_id} не найден."
            )

        return dict(
            row
        )

    def finish_run(
        self,
        *,
        run_id: int,
        status: str,
        records_received: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Завершает служебный запуск.
        """

        if run_id < 1:
            raise ValueError(
                "run_id должен быть больше 0."
            )

        if records_received < 0:
            raise ValueError(
                "records_received не может быть "
                "отрицательным."
            )

        prepared_status = status.strip().upper()

        if not prepared_status:
            raise ValueError(
                "Статус запуска не может быть пустым."
            )

        if len(prepared_status) > 32:
            raise ValueError(
                "Статус запуска не может быть длиннее "
                "32 символов."
            )

        safe_error_code = (
            error_code[:128]
            if error_code
            else None
        )

        safe_error_message = (
            error_message[:2000]
            if error_message
            else None
        )

        with self._database.transaction() as connection:
            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE sys_sync_run
                       SET status = %s,
                           records_received = %s,
                           error_code = %s,
                           error_message = %s,
                           finished_at = UTC_TIMESTAMP(6)
                     WHERE id = %s
                    """,
                    (
                        prepared_status,
                        records_received,
                        safe_error_code,
                        safe_error_message,
                        run_id,
                    ),
                )

                if cursor.rowcount != 1:
                    raise ValueError(
                        "Служебный запуск "
                        f"id={run_id} не найден."
                    )

            finally:
                cursor.close()

    def save_api_result(
        self,
        *,
        run_id: int,
        result: ApiResult,
        source_system: str,
        external_entity_id: str | None = None,
    ) -> int:
        """
        Сохраняет метаданные HTTP-запроса
        и неизменённый JSON-ответ в RAW-слой.

        Область организации и товарной группы
        наследуется через sync_run_id.
        """

        if run_id < 1:
            raise ValueError(
                "run_id должен быть больше 0."
            )

        prepared_source_system = (
            source_system.strip().upper()
        )

        if not prepared_source_system:
            raise ValueError(
                "source_system не может быть пустым."
            )

        if len(prepared_source_system) > 64:
            raise ValueError(
                "source_system не может быть длиннее "
                "64 символов."
            )

        prepared_external_entity_id = (
            external_entity_id.strip() or None
            if external_entity_id
            else None
        )

        if (
            prepared_external_entity_id is not None
            and len(prepared_external_entity_id) > 255
        ):
            raise ValueError(
                "external_entity_id не может быть "
                "длиннее 255 символов."
            )

        canonical_json = json.dumps(
            result.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

        payload_hash = hashlib.sha256(
            canonical_json.encode(
                "utf-8"
            )
        ).hexdigest()

        request_params_json = json.dumps(
            result.params,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

        with self._database.transaction() as connection:
            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    INSERT INTO sys_api_request (
                        sync_run_id,
                        http_method,
                        endpoint,
                        request_params,
                        requested_at,
                        response_received_at,
                        http_status,
                        response_time_ms,
                        attempt_number,
                        status,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        CAST(%s AS JSON),
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6),
                        %s,
                        %s,
                        1,
                        'SUCCESS',
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        run_id,
                        result.method,
                        result.endpoint,
                        request_params_json,
                        result.status_code,
                        result.elapsed_ms,
                    ),
                )

                api_request_id = int(
                    cursor.lastrowid
                )

                cursor.execute(
                    """
                    INSERT INTO raw_api_response (
                        sync_run_id,
                        api_request_id,
                        source_system,
                        endpoint,
                        external_entity_id,
                        payload_json,
                        payload_hash,
                        received_at,
                        processing_status,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        CAST(%s AS JSON),
                        %s,
                        UTC_TIMESTAMP(6),
                        'NEW',
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        run_id,
                        api_request_id,
                        prepared_source_system,
                        result.endpoint,
                        prepared_external_entity_id,
                        canonical_json,
                        payload_hash,
                    ),
                )

                raw_response_id = int(
                    cursor.lastrowid
                )

            finally:
                cursor.close()

        return raw_response_id