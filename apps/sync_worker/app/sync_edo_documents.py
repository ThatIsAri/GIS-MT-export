from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.download_edo_archive import (
    MAX_ENTRY_BYTES,
    extract_document_uuid,
    extract_upd_xml,
    update_raw_source_message_id,
)
from app.edo_archive_client import EdoArchiveClient
from app.import_edo_xml import import_xml_file
from app.process_edo import process_imported_document


SUPPORTED_DOCUMENT_TYPE = (
    "UNIVERSAL_TRANSFER_DOCUMENT"
)

SOURCE_SYSTEM = "TRUE_API_EDO"

COMPLETED_DOCUMENT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class CoreDocumentTarget:
    core_document_id: int
    external_document_id: str
    document_type: str | None
    document_uuid: str


@dataclass(frozen=True, slots=True)
class EdoSyncSummary:
    run_id: int

    selected_count: int
    unsupported_type_count: int
    missing_uuid_count: int

    already_processed_count: int
    downloaded_count: int
    matched_count: int
    error_count: int


def resolve_details_run_id(
    database: Database,
    run_id: int | None,
) -> int:
    """
    Проверяет переданный запуск либо возвращает
    последний завершённый SYNC_DOCUMENT_DETAILS.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            if run_id is None:
                cursor.execute(
                    """
                    SELECT id
                    FROM sys_sync_run
                    WHERE job_type = 'SYNC_DOCUMENT_DETAILS'
                      AND status IN (
                          'SUCCESS',
                          'PARTIAL'
                      )
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )

            else:
                cursor.execute(
                    """
                    SELECT id
                    FROM sys_sync_run
                    WHERE id = %s
                      AND job_type = 'SYNC_DOCUMENT_DETAILS'
                      AND status IN (
                          'SUCCESS',
                          'PARTIAL'
                      )
                    LIMIT 1
                    """,
                    (
                        run_id,
                    ),
                )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        if run_id is None:
            raise ValueError(
                "Не найден завершённый запуск "
                "SYNC_DOCUMENT_DETAILS."
            )

        raise ValueError(
            "Не найден завершённый запуск "
            f"SYNC_DOCUMENT_DETAILS id={run_id}."
        )

    return int(
        row[0]
    )


def load_targets(
    database: Database,
    run_id: int,
) -> tuple[
    list[CoreDocumentTarget],
    int,
    int,
]:
    """
    Выбирает из CORE документы последнего запуска,
    поддерживаемые текущим XML-парсером.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    id,
                    external_document_id,
                    document_type
                FROM core_document
                WHERE source_sync_run_id = %s
                ORDER BY id
                """,
                (
                    run_id,
                ),
            )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    targets: list[
        CoreDocumentTarget
    ] = []

    unsupported_type_count = 0
    missing_uuid_count = 0

    for row in rows:
        core_document_id = int(
            row[0]
        )

        external_document_id = str(
            row[1]
        ).strip()

        document_type = (
            str(
                row[2]
            ).strip()
            if row[2] is not None
            else None
        )

        if (
            document_type
            != SUPPORTED_DOCUMENT_TYPE
        ):
            unsupported_type_count += 1

            typer.echo(
                f"CORE id={core_document_id}: "
                "SKIP_UNSUPPORTED_TYPE; "
                f"type={document_type or '-'}"
            )

            continue

        document_uuid = (
            extract_document_uuid(
                external_document_id
            )
        )

        if document_uuid is None:
            missing_uuid_count += 1

            typer.echo(
                f"CORE id={core_document_id}: "
                "SKIP_UUID_NOT_FOUND"
            )

            continue

        targets.append(
            CoreDocumentTarget(
                core_document_id=(
                    core_document_id
                ),
                external_document_id=(
                    external_document_id
                ),
                document_type=document_type,
                document_uuid=document_uuid,
            )
        )

    return (
        targets,
        unsupported_type_count,
        missing_uuid_count,
    )


def load_completed_documents(
    database: Database,
    targets: list[
        CoreDocumentTarget
    ],
) -> dict[
    str,
    int,
]:
    """
    Возвращает уже полностью обработанные UUID:

    UUID → core_document_id.
    """

    document_uuids = sorted(
        {
            target.document_uuid
            for target in targets
        }
    )

    if not document_uuids:
        return {}

    result: dict[
        str,
        int,
    ] = {}

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            for offset in range(
                0,
                len(
                    document_uuids
                ),
                COMPLETED_DOCUMENT_BATCH_SIZE,
            ):
                chunk = document_uuids[
                    offset:
                    (
                        offset
                        + COMPLETED_DOCUMENT_BATCH_SIZE
                    )
                ]

                placeholders = ", ".join(
                    ["%s"] * len(
                        chunk
                    )
                )

                cursor.execute(
                    f"""
                    SELECT
                        source_message_id,
                        core_document_id
                    FROM raw_edo_document
                    WHERE source_message_id
                              IN ({placeholders})
                      AND parse_status = 'PARSED'
                      AND match_status = 'MATCHED'
                      AND core_document_id IS NOT NULL
                    """,
                    tuple(
                        chunk
                    ),
                )

                for row in cursor.fetchall():
                    source_message_id = str(
                        row[0]
                    ).strip().lower()

                    result[
                        source_message_id
                    ] = int(
                        row[1]
                    )

        finally:
            cursor.close()

    return result


async def sync_edo_documents(
    *,
    token: str,
    run_id: int | None,
    output_root: Path,
    delay_ms: int,
    force: bool,
    fail_fast: bool,
) -> EdoSyncSummary:
    """
    Скачивает официальные XML ЭДО
    для документов указанного CORE-запуска.
    """

    settings = get_settings()

    database = Database(
        settings
    )

    selected_run_id = (
        resolve_details_run_id(
            database,
            run_id,
        )
    )

    (
        targets,
        unsupported_type_count,
        missing_uuid_count,
    ) = load_targets(
        database,
        selected_run_id,
    )

    typer.echo(
        "Пакетная загрузка XML ЭДО."
    )

    typer.echo(
        "Источник CORE: "
        "SYNC_DOCUMENT_DETAILS "
        f"id={selected_run_id}"
    )

    typer.echo(
        "Поддерживаемых документов: "
        f"{len(targets)}"
    )

    typer.echo(
        "Пропущено по типу: "
        f"{unsupported_type_count}"
    )

    typer.echo(
        "Без UUID: "
        f"{missing_uuid_count}"
    )

    if not targets:
        return EdoSyncSummary(
            run_id=selected_run_id,
            selected_count=0,
            unsupported_type_count=(
                unsupported_type_count
            ),
            missing_uuid_count=(
                missing_uuid_count
            ),
            already_processed_count=0,
            downloaded_count=0,
            matched_count=0,
            error_count=0,
        )

    completed_documents = (
        {}
        if force
        else load_completed_documents(
            database,
            targets,
        )
    )

    already_processed_count = 0
    downloaded_count = 0
    matched_count = 0
    error_count = 0

    prepared_output_root = (
        output_root.resolve()
    )

    async with EdoArchiveClient(
        settings=settings,
        token=token,
    ) as client:
        for index, target in enumerate(
            targets,
            start=1,
        ):
            completed_core_document_id = (
                completed_documents.get(
                    target.document_uuid
                )
            )

            if (
                not force
                and completed_core_document_id
                == target.core_document_id
            ):
                already_processed_count += 1

                typer.echo(
                    f"{index}/{len(targets)} "
                    f"CORE id="
                    f"{target.core_document_id}: "
                    "SKIP_ALREADY_PROCESSED; "
                    f"document_id="
                    f"{target.document_uuid}"
                )

                continue

            try:
                response = (
                    await client
                    .download_incoming_document(
                        document_id=(
                            target.document_uuid
                        )
                    )
                )

                downloaded_count += 1

                typer.echo(
                    f"{index}/{len(targets)} "
                    f"CORE id="
                    f"{target.core_document_id}: "
                    f"HTTP {response.status_code}; "
                    f"Content-Type="
                    f"{response.content_type or '-'}; "
                    f"bytes="
                    f"{len(response.content)}; "
                    f"elapsed_ms="
                    f"{response.elapsed_ms}"
                )

                document_directory = (
                    prepared_output_root
                    / target.document_uuid
                )

                (
                    response_format,
                    xml_paths,
                ) = extract_upd_xml(
                    content=response.content,
                    output_directory=(
                        document_directory
                    ),
                    document_id=(
                        target.document_uuid
                    ),
                )

                if not xml_paths:
                    raise RuntimeError(
                        "В ответе не найден "
                        "товарный XML титула "
                        "продавца УПД."
                    )

                target_matched = False

                for xml_path in xml_paths:
                    import_result = (
                        import_xml_file(
                            database=database,
                            root=(
                                document_directory
                            ),
                            file_path=xml_path,
                            source_system=(
                                SOURCE_SYSTEM
                            ),
                            max_file_size_bytes=(
                                MAX_ENTRY_BYTES
                            ),
                        )
                    )

                    update_raw_source_message_id(
                        database,
                        raw_document_id=(
                            import_result
                            .raw_document_id
                        ),
                        document_id=(
                            target.document_uuid
                        ),
                    )

                    processing_result = (
                        process_imported_document(
                            database=database,
                            file_path=xml_path,
                            import_result=(
                                import_result
                            ),
                        )
                    )

                    typer.echo(
                        "    "
                        f"format={response_format}; "
                        f"file={xml_path.name}; "
                        "RAW id="
                        f"{processing_result.raw_document_id}; "
                        "import="
                        f"{'NEW' if processing_result.created else 'DUPLICATE'}; "
                        "parse="
                        f"{processing_result.parse_status}; "
                        "match="
                        f"{processing_result.match_status}; "
                        "core_document_id="
                        f"{processing_result.core_document_id or '-'}; "
                        "lines="
                        f"{processing_result.line_count}; "
                        "codes="
                        f"{processing_result.code_count}"
                    )

                    if (
                        processing_result.match_status
                        == "MATCHED"
                        and processing_result
                        .core_document_id
                        == target.core_document_id
                    ):
                        target_matched = True

                if not target_matched:
                    raise RuntimeError(
                        "XML обработан, но не связан "
                        "с ожидаемым "
                        f"core_document.id="
                        f"{target.core_document_id}."
                    )

                matched_count += 1

            except GisMtAuthError:
                raise

            except Exception as exc:
                error_count += 1

                typer.echo(
                    f"{index}/{len(targets)} "
                    f"CORE id="
                    f"{target.core_document_id}: "
                    f"ERROR "
                    f"{type(exc).__name__}: "
                    f"{exc}",
                    err=True,
                )

                if fail_fast:
                    raise

            if delay_ms > 0:
                await asyncio.sleep(
                    delay_ms / 1000
                )

    return EdoSyncSummary(
        run_id=selected_run_id,
        selected_count=len(
            targets
        ),
        unsupported_type_count=(
            unsupported_type_count
        ),
        missing_uuid_count=(
            missing_uuid_count
        ),
        already_processed_count=(
            already_processed_count
        ),
        downloaded_count=(
            downloaded_count
        ),
        matched_count=(
            matched_count
        ),
        error_count=error_count,
    )


def main(
    run_id: int | None = typer.Option(
        None,
        "--run-id",
        min=1,
        help=(
            "ID запуска "
            "SYNC_DOCUMENT_DETAILS. "
            "По умолчанию используется "
            "последний завершённый запуск."
        ),
    ),

    output_root: Path = typer.Option(
        Path(
            "/data/edo_inbox/official"
        ),
        "--output-root",
        file_okay=False,
        dir_okay=True,
        help=(
            "Каталог официально "
            "загруженных XML ЭДО."
        ),
    ),

    delay_ms: int = typer.Option(
        150,
        "--delay-ms",
        min=0,
        max=10000,
        help=(
            "Пауза между запросами "
            "документов."
        ),
    ),

    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Повторно скачать уже "
            "успешно обработанные документы."
        ),
    ),

    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help=(
            "Остановить пакет после "
            "первой ошибки документа."
        ),
    ),
) -> None:
    """
    Пакетно скачивает и обрабатывает
    официальные XML ЭДО.
    """

    token = read_token_from_stdin()

    try:
        summary = asyncio.run(
            sync_edo_documents(
                token=token,
                run_id=run_id,
                output_root=output_root,
                delay_ms=delay_ms,
                force=force,
                fail_fast=fail_fast,
            )
        )

    except GisMtAuthError as exc:
        typer.echo(
            "AUTH ERROR: токен True API "
            "отклонён или истёк.",
            err=True,
        )

        typer.echo(
            str(
                exc
            ),
            err=True,
        )

        raise typer.Exit(
            code=20
        ) from exc

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

    typer.echo("")
    typer.echo(
        "Пакетная загрузка XML ЭДО завершена."
    )

    typer.echo(
        f"Запуск CORE: "
        f"{summary.run_id}"
    )

    typer.echo(
        "Выбрано документов: "
        f"{summary.selected_count}"
    )

    typer.echo(
        "Уже обработано: "
        f"{summary.already_processed_count}"
    )

    typer.echo(
        "Скачано: "
        f"{summary.downloaded_count}"
    )

    typer.echo(
        "Успешно связано: "
        f"{summary.matched_count}"
    )

    typer.echo(
        "Пропущено по типу: "
        f"{summary.unsupported_type_count}"
    )

    typer.echo(
        "Без UUID: "
        f"{summary.missing_uuid_count}"
    )

    typer.echo(
        "Ошибок: "
        f"{summary.error_count}"
    )

    if summary.error_count > 0:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(
        main
    )