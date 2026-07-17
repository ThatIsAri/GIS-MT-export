import json
import os
from datetime import datetime, timezone
from typing import Any

import pymysql
import typer
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

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


def required_env(name: str) -> str:
    """
    Возвращает обязательную переменную окружения.
    """

    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(
            f"Не задана обязательная переменная окружения {name}."
        )

    return value.strip()


def create_connection() -> Connection:
    """
    Создаёт подключение к MySQL.
    """

    return pymysql.connect(
        host=required_env("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=required_env("DB_USER"),
        password=required_env("DB_PASSWORD"),
        database=required_env("DB_NAME"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=15,
        read_timeout=60,
        write_timeout=60,
    )


def decode_payload(value: Any) -> Any:
    """
    Преобразует значение payload_json из MySQL
    в Python-объект.
    """

    if isinstance(value, (dict, list)):
        return value

    if isinstance(value, bytes):
        value = value.decode("utf-8")

    if isinstance(value, str):
        return json.loads(value)

    raise ValueError(
        "RAW payload имеет неподдерживаемый тип: "
        f"{type(value).__name__}."
    )


def parse_iso_datetime(
    value: Any,
) -> datetime | None:
    """
    Преобразует ISO 8601 в datetime UTC без timezone.

    Пример:
        2026-06-03T08:43:22.928Z
    """

    if value is None:
        return None

    if not isinstance(value, str):
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
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    return parsed


def json_for_mysql(
    value: Any,
) -> str | None:
    """
    Преобразует Python-объект в JSON для MySQL.
    """

    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def find_latest_details_run(
    connection: Connection,
) -> dict[str, Any]:
    """
    Находит последний успешный или частично успешный
    запуск SYNC_DOCUMENT_DETAILS.
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

    with connection.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Не найден успешный запуск "
            "SYNC_DOCUMENT_DETAILS."
        )

    return row


def find_details_run(
    connection: Connection,
    run_id: int,
) -> dict[str, Any]:
    """
    Проверяет указанный запуск SYNC_DOCUMENT_DETAILS.
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

    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            (run_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Запуск SYNC_DOCUMENT_DETAILS "
            f"с id={run_id} не найден."
        )

    return row


def read_detail_responses(
    connection: Connection,
    run_id: int,
) -> list[dict[str, Any]]:
    """
    Читает только подробные ответы документов.

    RAW-ответы списка вида document-list-page-N
    в нормализацию не включаются.
    """

    sql = """
        SELECT
            id,
            external_entity_id,
            payload_json
        FROM raw_api_response
        WHERE sync_run_id = %s
          AND external_entity_id IS NOT NULL
          AND external_entity_id NOT LIKE 'document-list-page-%%'
        ORDER BY id
    """

    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            (run_id,),
        )

        return list(
            cursor.fetchall()
        )


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
        doc_date = VALUES(doc_date),
        received_at = VALUES(received_at),

        document_type = VALUES(document_type),
        document_status = VALUES(document_status),

        sender_inn = VALUES(sender_inn),
        sender_name = VALUES(sender_name),

        receiver_inn = VALUES(receiver_inn),
        receiver_name = VALUES(receiver_name),

        invoice_number = VALUES(invoice_number),
        invoice_date = VALUES(invoice_date),

        related_document_id = VALUES(
            related_document_id
        ),

        turnover_type = VALUES(turnover_type),

        product_groups = VALUES(product_groups),
        product_group_ids = VALUES(product_group_ids),
        errors_json = VALUES(errors_json),

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
    connection: Connection,
    *,
    run_id: int,
    raw_response_id: int,
    normalized: dict[str, Any],
) -> None:
    """
    Создаёт или обновляет документ в core_document.
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
        normalized.get("number"),
        parse_iso_datetime(
            normalized.get("docDate")
        ),
        parse_iso_datetime(
            normalized.get("receivedAt")
        ),
        normalized.get("type"),
        normalized.get("status"),
        normalized.get("senderInn"),
        normalized.get("senderName"),
        normalized.get("receiverInn"),
        normalized.get("receiverName"),
        normalized.get("invoiceNumber"),
        parse_iso_datetime(
            normalized.get("invoiceDate")
        ),
        normalized.get("relatedDocId"),
        normalized.get("turnoverType"),
        json_for_mysql(
            normalized.get("productGroup")
        ),
        json_for_mysql(
            normalized.get("productGroupId")
        ),
        json_for_mysql(
            normalized.get("errors")
        ),
        int(
            normalized.get(
                "_source_item_count",
                1,
            )
        ),
        normalization_status,
        json_for_mysql(conflicts),
        run_id,
        raw_response_id,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            UPSERT_DOCUMENT_SQL,
            parameters,
        )


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

    connection = create_connection()

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

                normalized = (
                    normalize_document_info(
                        payload,
                        document_id,
                    )
                )

                upsert_document(
                    connection,
                    run_id=selected_run_id,
                    raw_response_id=raw_response_id,
                    normalized=normalized,
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

                typer.echo(
                    f"RAW id={raw_response_id}: "
                    f"{type(exc).__name__}: {exc}",
                    err=True,
                )

            if row_number % batch_size == 0:
                connection.commit()

                typer.echo(
                    f"Обработано: "
                    f"{row_number}/{len(rows)}"
                )

        connection.commit()

        if len(rows) % batch_size != 0:
            typer.echo(
                f"Обработано: "
                f"{len(rows)}/{len(rows)}"
            )

        typer.echo("")
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

        if failed > 0:
            raise typer.Exit(code=2)

    except typer.Exit:
        raise

    except Exception as exc:
        connection.rollback()

        typer.echo(
            f"ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(code=1)

    finally:
        connection.close()


if __name__ == "__main__":
    app()