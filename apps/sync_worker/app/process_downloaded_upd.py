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
from app.process_edo import (
    process_imported_document,
)


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

    datamatrix_source_count: int
    datamatrix_aggregate_count: int
    datamatrix_terminal_count: int

    datamatrix_inserted_count: int
    datamatrix_updated_count: int
    datamatrix_unchanged_count: int
    datamatrix_removed_count: int

    datamatrix_mismatch_count: int
    datamatrix_product_count: int

    aggregate_request_count: int
    product_request_count: int
    product_lookup_warning_count: int

    ukd_removed_source_count: int
    ukd_removed_unit_count: int
    ukd_skipped_newer_count: int


class DownloadedUpdProcessingError(
    RuntimeError
):
    pass


def normalize_run_ids(
    values: Iterable[int],
) -> tuple[int, ...]:
    result = sorted(
        {
            int(
                value
            )

            for value in values

            if int(
                value
            ) > 0
        }
    )

    if not result:
        raise ValueError(
            "Не переданы запуски "
            "выгрузки УПД/УКД "
            "для обработки."
        )

    return tuple(
        result
    )


def load_downloaded_files(
    *,
    database: Database,
    legal_entity_id: int,
    details_run_ids: tuple[int, ...],
) -> tuple[
    list[
        dict[
            str,
            Any,
        ]
    ],
    int,
]:
    placeholders = ",".join(
        [
            "%s"
        ]
        * len(
            details_run_ids
        )
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

                  AND details_run_id
                      IN ({placeholders})

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
                dict(
                    row
                )
                for row
                in cursor.fetchall()
            ]

        finally:
            cursor.close()

    already_processed = sum(
        1

        for row in rows

        if (
            str(
                row[
                    "status"
                ]
            ).upper()
            == "PROCESSED"
        )
    )

    pending = [
        row

        for row in rows

        if (
            str(
                row[
                    "status"
                ]
            ).upper()
            != "PROCESSED"
        )
    ]

    return (
        pending,
        already_processed,
    )


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

                   SET status =
                           'PROCESSING',

                       processing_job_uuid = %s,

                       last_error_type = NULL,
                       last_error_message = NULL,

                       updated_at =
                           UTC_TIMESTAMP(6)

                 WHERE id = %s

                   AND status
                       <> 'PROCESSED'
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

                   SET status =
                           'PROCESSED',

                       raw_document_id = %s,

                       processing_job_uuid = %s,

                       processed_at =
                           UTC_TIMESTAMP(6),

                       last_error_type = NULL,
                       last_error_message = NULL,

                       updated_at =
                           UTC_TIMESTAMP(6)

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

                   SET status =
                           'ERROR',

                       processing_job_uuid = %s,

                       last_error_type = %s,
                       last_error_message = %s,

                       updated_at =
                           UTC_TIMESTAMP(6)

                 WHERE id = %s
                """,
                (
                    processing_job_uuid,
                    type(
                        exc
                    ).__name__[
                        :128
                    ],
                    str(
                        exc
                    )[
                        :2000
                    ],
                    download_file_id,
                ),
            )

        finally:
            cursor.close()


def _prepared_product_group(
    row: dict[
        str,
        Any,
    ],
) -> str:
    product_group = (
        str(
            row.get(
                "product_group"
            )
            or ""
        )
        .strip()
        .lower()
    )

    if not product_group:
        raise ValueError(
            "Для скачанного XML "
            "не указана товарная группа "
            "True API."
        )

    if len(
        product_group
    ) > 64:
        raise ValueError(
            "Код товарной группы "
            "True API превышает "
            "64 символа."
        )

    return product_group


def process_downloaded_upd(
    *,
    token: str,
    legal_entity_id: int,
    details_run_ids: Iterable[int],
    processing_job_uuid: str,
    output_root: Path = Path(
        "/data/official"
    ),
    database: Database | None = None,
) -> DownloadedUpdProcessingSummary:
    """
    Обрабатывает XML, скачанные
    родительским заданием EXPORT_UPD.

    Для каждого документа выполняются:

    - импорт RAW;
    - разбор УПД/УКД;
    - сопоставление с ожидаемым CORE;
    - раскрытие корневых КИ;
    - получение названий по GTIN;
    - сохранение конечных КИ единиц;
    - применение состояния «после»
      для УКД.
    """

    prepared_token = (
        token.strip()
    )

    if not prepared_token:
        raise ValueError(
            "Для задания обработки "
            "УПД/УКД не передан "
            "токен True API."
        )

    if legal_entity_id < 1:
        raise ValueError(
            "legal_entity_id должен "
            "быть больше 0."
        )

    prepared_job_uuid = (
        processing_job_uuid.strip()
    )

    if not prepared_job_uuid:
        raise ValueError(
            "processing_job_uuid "
            "не может быть пустым."
        )

    prepared_run_ids = (
        normalize_run_ids(
            details_run_ids
        )
    )

    active_database = (
        database
        or Database(
            get_settings()
        )
    )

    prepared_root = (
        output_root.resolve()
    )

    (
        rows,
        already_processed_count,
    ) = load_downloaded_files(
        database=(
            active_database
        ),
        legal_entity_id=(
            legal_entity_id
        ),
        details_run_ids=(
            prepared_run_ids
        ),
    )

    typer.echo(
        "Обработка скачанных "
        "УПД/УКД с раскрытием "
        "до КИ единицы."
    )

    typer.echo(
        f"Организация: "
        f"{legal_entity_id}."
    )

    typer.echo(
        "Запуски выгрузки: "
        + ", ".join(
            str(
                value
            )
            for value
            in prepared_run_ids
        )
        + "."
    )

    typer.echo(
        f"Файлов к обработке: "
        f"{len(rows)}; "
        f"уже обработано: "
        f"{already_processed_count}."
    )

    processed_count = 0
    matched_count = 0
    error_count = 0

    datamatrix_source_count = 0
    datamatrix_aggregate_count = 0
    datamatrix_terminal_count = 0

    datamatrix_inserted_count = 0
    datamatrix_updated_count = 0
    datamatrix_unchanged_count = 0
    datamatrix_removed_count = 0

    datamatrix_mismatch_count = 0
    datamatrix_product_count = 0

    aggregate_request_count = 0
    product_request_count = 0
    product_lookup_warning_count = 0

    ukd_removed_source_count = 0
    ukd_removed_unit_count = 0
    ukd_skipped_newer_count = 0

    for index, row in enumerate(
        rows,
        start=1,
    ):
        download_file_id = int(
            row[
                "id"
            ]
        )

        file_path = (
            prepared_root
            / str(
                row[
                    "relative_path"
                ]
            )
        ).resolve()

        try:
            row_entity_id = int(
                row[
                    "legal_entity_id"
                ]
            )

            if (
                row_entity_id
                != legal_entity_id
            ):
                raise RuntimeError(
                    "Скачанный XML относится "
                    "к другой организации: "
                    f"expected="
                    f"{legal_entity_id}; "
                    f"actual="
                    f"{row_entity_id}."
                )

            product_group = (
                _prepared_product_group(
                    row
                )
            )

            file_path.relative_to(
                prepared_root
            )

            if not file_path.is_file():
                raise FileNotFoundError(
                    "Скачанный XML "
                    "не найден: "
                    f"{file_path}."
                )

            mark_processing(
                database=(
                    active_database
                ),
                download_file_id=(
                    download_file_id
                ),
                processing_job_uuid=(
                    prepared_job_uuid
                ),
            )

            import_result = (
                import_xml_file(
                    database=(
                        active_database
                    ),
                    root=(
                        prepared_root
                    ),
                    file_path=(
                        file_path
                    ),
                    source_system=(
                        SOURCE_SYSTEM
                    ),
                    max_file_size_bytes=(
                        MAX_ENTRY_BYTES
                    ),
                )
            )

            update_raw_source_message_id(
                active_database,
                raw_document_id=(
                    import_result
                    .raw_document_id
                ),
                document_id=str(
                    row[
                        "document_uuid"
                    ]
                ),
            )

            processing_result = (
                process_imported_document(
                    database=(
                        active_database
                    ),
                    file_path=(
                        file_path
                    ),
                    import_result=(
                        import_result
                    ),
                    token=(
                        prepared_token
                    ),
                    product_group=(
                        product_group
                    ),
                )
            )

            if (
                processing_result
                .match_status
                != "MATCHED"

                or processing_result
                .core_document_id
                != int(
                    row[
                        "core_document_id"
                    ]
                )
            ):
                raise RuntimeError(
                    "XML обработан, но "
                    "не связан с ожидаемым "
                    "CORE-документом: "
                    f"expected="
                    f"{row['core_document_id']}; "
                    f"actual="
                    f"{processing_result.core_document_id}; "
                    f"match_status="
                    f"{processing_result.match_status}."
                )

            mark_processed(
                database=(
                    active_database
                ),
                download_file_id=(
                    download_file_id
                ),
                processing_job_uuid=(
                    prepared_job_uuid
                ),
                raw_document_id=(
                    processing_result
                    .raw_document_id
                ),
            )

            processed_count += 1
            matched_count += 1

            datamatrix_source_count += (
                processing_result
                .datamatrix_source_count
            )

            datamatrix_aggregate_count += (
                processing_result
                .datamatrix_aggregate_count
            )

            datamatrix_terminal_count += (
                processing_result
                .datamatrix_terminal_count
            )

            datamatrix_inserted_count += (
                processing_result
                .datamatrix_inserted_count
            )

            datamatrix_updated_count += (
                processing_result
                .datamatrix_updated_count
            )

            datamatrix_unchanged_count += (
                processing_result
                .datamatrix_unchanged_count
            )

            datamatrix_removed_count += (
                processing_result
                .datamatrix_removed_count
            )

            datamatrix_mismatch_count += (
                processing_result
                .datamatrix_mismatch_count
            )

            datamatrix_product_count += (
                processing_result
                .datamatrix_product_count
            )

            aggregate_request_count += (
                processing_result
                .aggregate_request_count
            )

            product_request_count += (
                processing_result
                .product_request_count
            )

            if (
                processing_result
                .product_lookup_error
            ):
                product_lookup_warning_count += 1

            ukd_removed_source_count += (
                processing_result
                .ukd_removed_source_count
            )

            ukd_removed_unit_count += (
                processing_result
                .ukd_removed_unit_count
            )

            ukd_skipped_newer_count += (
                processing_result
                .ukd_skipped_newer_count
            )

            typer.echo(
                f"{index}/"
                f"{len(rows)}: "
                "SUCCESS; "
                f"file="
                f"{file_path.name}; "
                f"kind="
                f"{processing_result.document_kind}; "
                f"pg="
                f"{product_group}; "
                f"core_document_id="
                f"{processing_result.core_document_id}; "
                f"lines="
                f"{processing_result.line_count}; "
                f"source_codes="
                f"{processing_result.code_count}; "
                f"roots="
                f"{processing_result.datamatrix_source_count}; "
                f"aggregates="
                f"{processing_result.datamatrix_aggregate_count}; "
                f"units="
                f"{processing_result.datamatrix_terminal_count}; "
                f"quantity_mismatches="
                f"{processing_result.datamatrix_mismatch_count}."
            )

            if (
                processing_result
                .product_lookup_error
            ):
                typer.echo(
                    "    WARNING "
                    "product/info: "
                    f"{processing_result.product_lookup_error}",
                    err=True,
                )

        except Exception as exc:
            error_count += 1

            mark_error(
                database=(
                    active_database
                ),
                download_file_id=(
                    download_file_id
                ),
                processing_job_uuid=(
                    prepared_job_uuid
                ),
                exc=exc,
            )

            typer.echo(
                f"{index}/"
                f"{len(rows)}: "
                "ERROR; "
                f"{type(exc).__name__}: "
                f"{exc}",
                err=True,
            )

    prepared_token = ""

    summary = (
        DownloadedUpdProcessingSummary(
            legal_entity_id=(
                legal_entity_id
            ),
            processing_job_uuid=(
                prepared_job_uuid
            ),
            details_run_ids=(
                prepared_run_ids
            ),
            selected_count=len(
                rows
            ),
            already_processed_count=(
                already_processed_count
            ),
            processed_count=(
                processed_count
            ),
            matched_count=(
                matched_count
            ),
            error_count=(
                error_count
            ),
            datamatrix_source_count=(
                datamatrix_source_count
            ),
            datamatrix_aggregate_count=(
                datamatrix_aggregate_count
            ),
            datamatrix_terminal_count=(
                datamatrix_terminal_count
            ),
            datamatrix_inserted_count=(
                datamatrix_inserted_count
            ),
            datamatrix_updated_count=(
                datamatrix_updated_count
            ),
            datamatrix_unchanged_count=(
                datamatrix_unchanged_count
            ),
            datamatrix_removed_count=(
                datamatrix_removed_count
            ),
            datamatrix_mismatch_count=(
                datamatrix_mismatch_count
            ),
            datamatrix_product_count=(
                datamatrix_product_count
            ),
            aggregate_request_count=(
                aggregate_request_count
            ),
            product_request_count=(
                product_request_count
            ),
            product_lookup_warning_count=(
                product_lookup_warning_count
            ),
            ukd_removed_source_count=(
                ukd_removed_source_count
            ),
            ukd_removed_unit_count=(
                ukd_removed_unit_count
            ),
            ukd_skipped_newer_count=(
                ukd_skipped_newer_count
            ),
        )
    )

    typer.echo(
        "Итог обработки УПД/УКД: "
        f"успешно="
        f"{processed_count}; "
        f"ошибок="
        f"{error_count}; "
        f"корневых КИ="
        f"{datamatrix_source_count}; "
        f"агрегатов="
        f"{datamatrix_aggregate_count}; "
        f"КИ единиц="
        f"{datamatrix_terminal_count}; "
        f"несовпадений количества="
        f"{datamatrix_mismatch_count}."
    )

    if error_count > 0:
        raise DownloadedUpdProcessingError(
            "Обработка УПД/УКД "
            "завершилась с ошибками: "
            f"{error_count} "
            f"из {len(rows)}."
        )

    return summary