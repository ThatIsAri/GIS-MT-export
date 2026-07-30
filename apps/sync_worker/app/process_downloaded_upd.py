from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import typer

from app.config import get_settings
from app.db import Database
from app.download_edo_archive import (
    MAX_ENTRY_BYTES,
    update_raw_source_message_id,
)
from app.import_edo_xml import import_xml_file
from app.process_edo import process_imported_document


SOURCE_SYSTEM = "TRUE_API_EDO"


@dataclass(
    frozen=True,
    slots=True,
)
class DownloadedUpdProcessingSummary:
    legal_entity_id: int
    processing_job_uuid: str
    details_run_ids: tuple[int, ...]
    selected_count: int
    already_processed_count: int
    processed_count: int
    matched_count: int
    error_count: int


class DownloadedUpdProcessingError(RuntimeError):
    pass


def normalize_run_ids(
    values: Iterable[int],
) -> tuple[int, ...]:
    result = sorted(
        {
            int(value)
            for value in values
            if int(value) > 0
        }
    )

    if not result:
        raise ValueError(
            "Не переданы запуски выгрузки УПД "
            "для обработки."
        )

    return tuple(result)


def load_downloaded_files(
    *,
    database: Database,
    legal_entity_id: int,
    details_run_ids: tuple[int, ...],
) -> tuple[
    list[dict[str, Any]],
    int,
]:
    placeholders = ",".join(
        ["%s"] * len(details_run_ids)
    )

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                f"""
                SELECT
                    id,
                    legal_entity_id,
                    product_group,
                    details_run_id,
                    core_document_id,
                    document_uuid,
                    relative_path,
                    content_sha256,
                    file_size_bytes,
                    status,
                    raw_document_id
                FROM upd_download_file
                WHERE legal_entity_id = %s
                  AND details_run_id IN ({placeholders})
                ORDER BY
                    details_run_id,
                    core_document_id,
                    id
                """,
                (
                    legal_entity_id,
                    *details_run_ids,
                ),
            )

            rows = [
                dict(row)
                for row in cursor.fetchall()
            ]

        finally:
            cursor.close()

    already_processed = sum(
        1
        for row in rows
        if str(row["status"]).upper()
        == "PROCESSED"
    )

    pending = [
        row
        for row in rows
        if str(row["status"]).upper()
        != "PROCESSED"
    ]

    return pending, already_processed


def mark_processing(
    *,
    database: Database,
    download_file_id: int,
    processing_job_uuid: str,
) -> None:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE upd_download_file
                   SET status = 'PROCESSING',
                       processing_job_uuid = %s,
                       last_error_type = NULL,
                       last_error_message = NULL,
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = %s
                   AND status <> 'PROCESSED'
                """,
                (
                    processing_job_uuid,
                    download_file_id,
                ),
            )

        finally:
            cursor.close()


def mark_processed(
    *,
    database: Database,
    download_file_id: int,
    processing_job_uuid: str,
    raw_document_id: int,
) -> None:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE upd_download_file
                   SET status = 'PROCESSED',
                       raw_document_id = %s,
                       processing_job_uuid = %s,
                       processed_at = UTC_TIMESTAMP(6),
                       last_error_type = NULL,
                       last_error_message = NULL,
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    raw_document_id,
                    processing_job_uuid,
                    download_file_id,
                ),
            )

        finally:
            cursor.close()


def mark_error(
    *,
    database: Database,
    download_file_id: int,
    processing_job_uuid: str,
    exc: BaseException,
) -> None:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE upd_download_file
                   SET status = 'ERROR',
                       processing_job_uuid = %s,
                       last_error_type = %s,
                       last_error_message = %s,
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    processing_job_uuid,
                    type(exc).__name__[:128],
                    str(exc)[:2000],
                    download_file_id,
                ),
            )

        finally:
            cursor.close()


def process_downloaded_upd(
    *,
    legal_entity_id: int,
    details_run_ids: Iterable[int],
    processing_job_uuid: str,
    output_root: Path = Path("/data/official"),
    database: Database | None = None,
) -> DownloadedUpdProcessingSummary:
    if legal_entity_id < 1:
        raise ValueError(
            "legal_entity_id должен быть больше 0."
        )

    prepared_job_uuid = processing_job_uuid.strip()

    if not prepared_job_uuid:
        raise ValueError(
            "processing_job_uuid не может быть пустым."
        )

    prepared_run_ids = normalize_run_ids(
        details_run_ids
    )

    active_database = (
        database
        or Database(get_settings())
    )

    prepared_root = output_root.resolve()

    rows, already_processed_count = (
        load_downloaded_files(
            database=active_database,
            legal_entity_id=legal_entity_id,
            details_run_ids=prepared_run_ids,
        )
    )

    typer.echo(
        "Обработка скачанных УПД."
    )
    typer.echo(
        f"Организация: {legal_entity_id}."
    )
    typer.echo(
        "Запуски выгрузки: "
        + ", ".join(
            str(value)
            for value in prepared_run_ids
        )
        + "."
    )
    typer.echo(
        f"Файлов к обработке: {len(rows)}; "
        f"уже обработано: {already_processed_count}."
    )

    processed_count = 0
    matched_count = 0
    error_count = 0

    for index, row in enumerate(
        rows,
        start=1,
    ):
        download_file_id = int(row["id"])
        file_path = (
            prepared_root
            / str(row["relative_path"])
        ).resolve()

        try:
            file_path.relative_to(
                prepared_root
            )

            if not file_path.is_file():
                raise FileNotFoundError(
                    "Скачанный XML не найден: "
                    f"{file_path}."
                )

            mark_processing(
                database=active_database,
                download_file_id=(
                    download_file_id
                ),
                processing_job_uuid=(
                    prepared_job_uuid
                ),
            )

            import_result = import_xml_file(
                database=active_database,
                root=prepared_root,
                file_path=file_path,
                source_system=SOURCE_SYSTEM,
                max_file_size_bytes=(
                    MAX_ENTRY_BYTES
                ),
            )

            update_raw_source_message_id(
                active_database,
                raw_document_id=(
                    import_result.raw_document_id
                ),
                document_id=str(
                    row["document_uuid"]
                ),
            )

            processing_result = (
                process_imported_document(
                    database=active_database,
                    file_path=file_path,
                    import_result=import_result,
                )
            )

            processed_count += 1

            if (
                processing_result.match_status
                != "MATCHED"
                or processing_result.core_document_id
                != int(row["core_document_id"])
            ):
                raise RuntimeError(
                    "XML обработан, но не связан "
                    "с ожидаемым CORE-документом: "
                    f"expected={row['core_document_id']}; "
                    "actual="
                    f"{processing_result.core_document_id}; "
                    "match_status="
                    f"{processing_result.match_status}."
                )

            matched_count += 1

            mark_processed(
                database=active_database,
                download_file_id=(
                    download_file_id
                ),
                processing_job_uuid=(
                    prepared_job_uuid
                ),
                raw_document_id=(
                    processing_result.raw_document_id
                ),
            )

            typer.echo(
                f"{index}/{len(rows)}: SUCCESS; "
                f"file={file_path.name}; "
                "core_document_id="
                f"{processing_result.core_document_id}; "
                f"lines={processing_result.line_count}; "
                f"codes={processing_result.code_count}."
            )

        except Exception as exc:
            error_count += 1

            mark_error(
                database=active_database,
                download_file_id=(
                    download_file_id
                ),
                processing_job_uuid=(
                    prepared_job_uuid
                ),
                exc=exc,
            )

            typer.echo(
                f"{index}/{len(rows)}: ERROR; "
                f"{type(exc).__name__}: {exc}",
                err=True,
            )

    summary = DownloadedUpdProcessingSummary(
        legal_entity_id=legal_entity_id,
        processing_job_uuid=prepared_job_uuid,
        details_run_ids=prepared_run_ids,
        selected_count=len(rows),
        already_processed_count=(
            already_processed_count
        ),
        processed_count=processed_count,
        matched_count=matched_count,
        error_count=error_count,
    )

    if error_count > 0:
        raise DownloadedUpdProcessingError(
            "Обработка УПД завершилась с ошибками: "
            f"{error_count} из {len(rows)}."
        )

    return summary
