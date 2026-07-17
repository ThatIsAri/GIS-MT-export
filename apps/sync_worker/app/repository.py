import hashlib
import json
import uuid
from typing import Any

from app.db import Database
from app.models import ApiResult


class Repository:
    def __init__(
        self,
        database: Database,
    ) -> None:
        self._database = database

    def start_run(
        self,
        *,
        job_type: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[int, str]:
        run_uuid = str(uuid.uuid4())

        with self._database.transaction() as connection:
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO sys_sync_run (
                    run_uuid,
                    job_type,
                    status,
                    date_from,
                    date_to,
                    started_at,
                    created_at
                )
                VALUES (
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
                    run_uuid,
                    job_type,
                    date_from,
                    date_to,
                ),
            )

            run_id = int(cursor.lastrowid)
            cursor.close()

        return run_id, run_uuid

    def finish_run(
        self,
        *,
        run_id: int,
        status: str,
        records_received: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        safe_error_message = None

        if error_message:
            safe_error_message = error_message[:2000]

        with self._database.transaction() as connection:
            cursor = connection.cursor()

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
                    status,
                    records_received,
                    error_code,
                    safe_error_message,
                    run_id,
                ),
            )

            cursor.close()

    def save_api_result(
        self,
        *,
        run_id: int,
        result: ApiResult,
        source_system: str,
        external_entity_id: str | None = None,
    ) -> int:
        canonical_json = json.dumps(
            result.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        payload_hash = hashlib.sha256(
            canonical_json.encode("utf-8")
        ).hexdigest()

        request_params_json = json.dumps(
            result.params,
            ensure_ascii=False,
        )

        with self._database.transaction() as connection:
            cursor = connection.cursor()

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
                    source_system,
                    result.endpoint,
                    external_entity_id,
                    canonical_json,
                    payload_hash,
                ),
            )

            raw_response_id = int(
                cursor.lastrowid
            )

            cursor.close()

        return raw_response_id


def extract_document_ids(
    payload: Any,
) -> list[str]:
    """
    Извлекает идентификаторы документов из ответа
    GET /api/v4/true-api/doc/list.

    В фактическом ответе идентификатор документа
    находится в поле results[].number.
    """

    if not isinstance(payload, dict):
        return []

    results = payload.get("results")

    if not isinstance(results, list):
        return []

    document_ids: list[str] = []

    for item in results:
        if not isinstance(item, dict):
            continue

        document_number = item.get("number")

        if not isinstance(document_number, str):
            continue

        document_number = document_number.strip()

        if document_number:
            document_ids.append(document_number)

    # Удаляем дубли, сохраняя исходный порядок.
    return list(dict.fromkeys(document_ids))