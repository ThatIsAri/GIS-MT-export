from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import typer
from mysql.connector import MySQLConnection

from app.config import get_settings
from app.db import Database
from app.normalizers import (
    DocumentNormalizationError,
    normalize_document_info,
)


app = typer.Typer(
    add_completion=False,
    help=(
        "Нормализация подробных ответов документов "
        "из RAW-слоя в таблицу core_document."
    ),
)


@dataclass(
    frozen=True,
    slots=True,
)
class CoreLoadSummary:
    """
    Итог переноса подробных RAW-ответов в CORE.
    """

    run_id: int
    selected_count: int
    processed_count: int
    conflict_count: int
    failed_count: int


def decode_payload(
    value: Any,
) -> Any:
    """
    Преобразует payload_json из MySQL
    в Python-объект.
    """

    if isinstance(
        value,
        (
            dict,
            list,
        ),
    ):
        return value

    if isinstance(
        value,
        bytes,
    ):
        value = value.decode(
            "utf-8"
        )

    if isinstance(
        value,
        str,
    ):
        return json.loads(
            value
        )

    raise ValueError(
        "RAW payload имеет неподдерживаемый тип: "
        f"{type(value).__name__}."
    )


def parse_iso_datetime(
    value: Any,
) -> datetime | None:
    """
    Преобразует ISO 8601 в UTC datetime
    без timezone для сохранения в MySQL.

    Пример:
        2026-06-03T08:43:22.928Z
    """

    if not isinstance(
        value,
        str,
    ):
        return None

    prepared_value = value.strip()

    if not prepared_value:
        return None

    try:
        parsed = datetime.fromisoformat(
            prepared_value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:
        return None

    if parsed.tzinfo is not None:
        parsed = (
            parsed
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

    return parsed


def json_for_mysql(
    value: Any,
) -> str | None:
    """
    Преобразует Python-объект в компактный
    JSON для MySQL.
    """

    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )


def find_latest_details_run(
    connection: MySQLConnection,
) -> dict[str, Any]:
    """
    Находит последний успешный или частично
    успешный запуск SYNC_DOCUMENT_DETAILS.
    """

    sql = """
        SELECT
            id,
            run_uuid,
            status,
            records_received,
            started_at,
            finished_at
        FROM sys_sync_run
        WHERE job_type = 'SYNC_DOCUMENT_DETAILS'
          AND status IN ('SUCCESS', 'PARTIAL')
        ORDER BY id DESC
        LIMIT 1
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            sql
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if row is None:
        raise RuntimeError(
            "Не найден успешный запуск "
            "SYNC_DOCUMENT_DETAILS."
        )

    return row


def find_details_run(
    connection: MySQLConnection,
    run_id: int,
) -> dict[str, Any]:
    """
    Находит конкретный запуск
    SYNC_DOCUMENT_DETAILS.
    """

    sql = """
        SELECT
            id,
            run_uuid,
            status,
            records_received,
            started_at,
            finished_at
        FROM sys_sync_run
        WHERE id = %s
          AND job_type = 'SYNC_DOCUMENT_DETAILS'
        LIMIT 1
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            sql,
            (
                run_id,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if row is None:
        raise RuntimeError(
            "Запуск SYNC_DOCUMENT_DETAILS "
            f"с id={run_id} не найден."
        )

    return row


def read_detail_responses(
    connection: MySQLConnection,
    run_id: int,
) -> list[dict[str, Any]]:
    """
    Читает только подробные ответы метода:

        /doc/{document_number}/info

    Ответы метода /doc/list не попадают
    в нормализацию независимо от имени
    external_entity_id.
    """

    sql = """
        SELECT
            id,
            external_entity_id,
            payload_json,
            processing_status,
            processing_error
        FROM raw_api_response
        WHERE sync_run_id = %s
          AND external_entity_id IS NOT NULL
          AND endpoint LIKE %s
        ORDER BY id
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            sql,
            (
                run_id,
                "%/doc/%/info",
            ),
        )

        return list(
            cursor.fetchall()
        )

    finally:
        cursor.close()


UPSERT_DOCUMENT_SQL = """
    INSERT INTO core_document (
        external_document_id,
        doc_date,
        received_at,
        document_type,
        document_status,
        sender_inn,
        sender_name,
        receiver_inn,
        receiver_name,
        invoice_number,
        invoice_date,
        related_document_id,
        turnover_type,
        product_groups,
        product_group_ids,
        errors_json,
        source_item_count,
        normalization_status,
        normalization_conflicts,
        source_sync_run_id,
        source_raw_response_id,
        first_seen_at,
        last_seen_at
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
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        UTC_TIMESTAMP(3),
        UTC_TIMESTAMP(3)
    )
    ON DUPLICATE KEY UPDATE
        doc_date = VALUES(
            doc_date
        ),

        received_at = VALUES(
            received_at
        ),

        document_type = VALUES(
            document_type
        ),

        document_status = VALUES(
            document_status
        ),

        sender_inn = VALUES(
            sender_inn
        ),

        sender_name = VALUES(
            sender_name
        ),

        receiver_inn = VALUES(
            receiver_inn
        ),

        receiver_name = VALUES(
            receiver_name
        ),

        invoice_number = VALUES(
            invoice_number
        ),

        invoice_date = VALUES(
            invoice_date
        ),

        related_document_id = VALUES(
            related_document_id
        ),

        turnover_type = VALUES(
            turnover_type
        ),

        product_groups = VALUES(
            product_groups
        ),

        product_group_ids = VALUES(
            product_group_ids
        ),

        errors_json = VALUES(
            errors_json
        ),

        source_item_count = VALUES(
            source_item_count
        ),

        normalization_status = VALUES(
            normalization_status
        ),

        normalization_conflicts = VALUES(
            normalization_conflicts
        ),

        source_sync_run_id = VALUES(
            source_sync_run_id
        ),

        source_raw_response_id = VALUES(
            source_raw_response_id
        ),

        last_seen_at = UTC_TIMESTAMP(3),

        updated_at = UTC_TIMESTAMP(3)
"""


def upsert_document(
    connection: MySQLConnection,
    *,
    run_id: int,
    raw_response_id: int,
    normalized: dict[str, Any],
) -> None:
    """
    Создаёт или обновляет документ
    в таблице core_document.
    """

    conflicts = normalized.get(
        "_conflicts"
    )

    normalization_status = (
        "CONFLICT"
        if conflicts
        else "OK"
    )

    parameters = (
        normalized.get(
            "number"
        ),

        parse_iso_datetime(
            normalized.get(
                "docDate"
            )
        ),

        parse_iso_datetime(
            normalized.get(
                "receivedAt"
            )
        ),

        normalized.get(
            "type"
        ),

        normalized.get(
            "status"
        ),

        normalized.get(
            "senderInn"
        ),

        normalized.get(
            "senderName"
        ),

        normalized.get(
            "receiverInn"
        ),

        normalized.get(
            "receiverName"
        ),

        normalized.get(
            "invoiceNumber"
        ),

        parse_iso_datetime(
            normalized.get(
                "invoiceDate"
            )
        ),

        normalized.get(
            "relatedDocId"
        ),

        normalized.get(
            "turnoverType"
        ),

        json_for_mysql(
            normalized.get(
                "productGroup"
            )
        ),

        json_for_mysql(
            normalized.get(
                "productGroupId"
            )
        ),

        json_for_mysql(
            normalized.get(
                "errors"
            )
        ),

        int(
            normalized.get(
                "_source_item_count",
                1,
            )
        ),

        normalization_status,

        json_for_mysql(
            conflicts
        ),

        run_id,

        raw_response_id,
    )

    cursor = connection.cursor()

    try:
        cursor.execute(
            UPSERT_DOCUMENT_SQL,
            parameters,
        )

    finally:
        cursor.close()


def update_raw_processing_status(
    connection: MySQLConnection,
    *,
    raw_response_id: int,
    status: str,
    error: str | None = None,
) -> None:
    """
    Обновляет результат обработки
    исходного RAW-ответа.
    """

    safe_error = (
        error[:2000]
        if error
        else None
    )

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE raw_api_response
               SET processing_status = %s,
                   processing_error = %s
             WHERE id = %s
            """,
            (
                status,
                safe_error,
                raw_response_id,
            ),
        )

    finally:
        cursor.close()


def load_core_documents(
    *,
    database: Database,
    run_id: int | None,
    batch_size: int = 50,
    echo_progress: bool = True,
) -> CoreLoadSummary:
    """
    Нормализует подробные RAW-ответы
    выбранного запуска в CORE.

    Функция может вызываться напрямую
    из pipeline либо через CLI.
    """

    if batch_size < 1:
        raise ValueError(
            "batch_size должен быть "
            "не меньше 1."
        )

    connection = database.connect()

    processed = 0
    conflict_count = 0
    failed = 0

    try:
        if run_id is None:
            run = find_latest_details_run(
                connection
            )

        else:
            run = find_details_run(
                connection,
                run_id,
            )

        selected_run_id = int(
            run["id"]
        )

        rows = read_detail_responses(
            connection,
            selected_run_id,
        )

        if echo_progress:
            typer.echo(
                "Источник: "
                "SYNC_DOCUMENT_DETAILS "
                f"id={selected_run_id}"
            )

            typer.echo(
                "Статус исходного запуска: "
                f"{run['status']}"
            )

            typer.echo(
                "Найдено RAW-ответов документов: "
                f"{len(rows)}"
            )

        if not rows:
            raise RuntimeError(
                "В выбранном запуске отсутствуют "
                "подробные RAW-ответы документов."
            )

        for row_number, row in enumerate(
            rows,
            start=1,
        ):
            raw_response_id = int(
                row["id"]
            )

            document_id = str(
                row["external_entity_id"]
            ).strip()

            try:
                payload = decode_payload(
                    row["payload_json"]
                )

                normalized = normalize_document_info(
                    payload,
                    document_id,
                )

                upsert_document(
                    connection,
                    run_id=selected_run_id,
                    raw_response_id=raw_response_id,
                    normalized=normalized,
                )

                update_raw_processing_status(
                    connection,
                    raw_response_id=raw_response_id,
                    status="PROCESSED",
                )

                processed += 1

                if normalized.get(
                    "_conflicts"
                ):
                    conflict_count += 1

            except (
                DocumentNormalizationError,
                json.JSONDecodeError,
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
                failed += 1

                error_message = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                update_raw_processing_status(
                    connection,
                    raw_response_id=raw_response_id,
                    status="ERROR",
                    error=error_message,
                )

                if echo_progress:
                    typer.echo(
                        f"RAW id={raw_response_id}: "
                        f"{error_message}",
                        err=True,
                    )

            if (
                row_number
                % batch_size
                == 0
            ):
                connection.commit()

                if echo_progress:
                    typer.echo(
                        "Обработано: "
                        f"{row_number}/{len(rows)}"
                    )

        connection.commit()

        if (
            echo_progress
            and len(rows)
            % batch_size
            != 0
        ):
            typer.echo(
                "Обработано: "
                f"{len(rows)}/{len(rows)}"
            )

        summary = CoreLoadSummary(
            run_id=selected_run_id,
            selected_count=len(rows),
            processed_count=processed,
            conflict_count=conflict_count,
            failed_count=failed,
        )

        if echo_progress:
            typer.echo(
                ""
            )

            typer.echo(
                "Нормализация завершена."
            )

            typer.echo(
                "Успешно загружено в CORE: "
                f"{processed}"
            )

            typer.echo(
                "Документов с расхождениями: "
                f"{conflict_count}"
            )

            typer.echo(
                "Ошибок нормализации: "
                f"{failed}"
            )

        return summary

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


@app.command()
def main(
    batch_size: int = typer.Option(
        50,
        "--batch-size",
        min=1,
        max=1000,
        help=(
            "Количество документов между "
            "транзакциями COMMIT."
        ),
    ),

    run_id: int | None = typer.Option(
        None,
        "--run-id",
        min=1,
        help=(
            "ID конкретного запуска "
            "SYNC_DOCUMENT_DETAILS. "
            "Без параметра используется последний "
            "успешный запуск."
        ),
    ),
) -> None:
    """
    Переносит подробные RAW-ответы документов
    в нормализованную таблицу core_document.
    """

    try:
        summary = load_core_documents(
            database=Database(
                get_settings()
            ),
            run_id=run_id,
            batch_size=batch_size,
        )

    except Exception as exc:
        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc

    if summary.failed_count > 0:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    app()