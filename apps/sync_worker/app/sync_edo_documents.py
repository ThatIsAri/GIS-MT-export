from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import typer

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.document_storage import (
    build_document_directory,
    resolve_document_date,
)
from app.download_edo_archive import (
    MAX_ENTRY_BYTES,
    extract_document_uuid,
    extract_edo_xml,
    update_raw_source_message_id,
)
from app.edo_archive_client import EdoArchiveClient
from app.edo_document_type import SUPPORTED_EDO_DOCUMENT_TYPES
from app.import_edo_xml import import_xml_file
from app.process_edo import process_imported_document


SUPPORTED_DOCUMENT_TYPES = SUPPORTED_EDO_DOCUMENT_TYPES
SOURCE_SYSTEM = "TRUE_API_EDO"
COMPLETED_DOCUMENT_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class DetailsRunScope:
    run_id: int
    legal_entity_id: int
    product_group: str
    status: str
    records_received: int
    storage_slug: str = "organization"
    organization_name: str = "Организация"


@dataclass(frozen=True, slots=True)
class CoreDocumentTarget:
    core_document_id: int
    external_document_id: str
    document_type: str | None
    document_uuid: str
    document_date: date | None = None


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


def resolve_details_run(
    database: Database,
    run_id: int | None,
) -> DetailsRunScope:
    with database.transaction() as connection:
        cursor = connection.cursor(dictionary=True)

        try:
            if run_id is None:
                cursor.execute(
                    """
                    SELECT
                        sync_run.id,
                        sync_run.legal_entity_id,
                        sync_run.product_group,
                        sync_run.status,
                        sync_run.records_received,
                        entity.storage_slug,
                        entity.short_name
                    FROM sys_sync_run AS sync_run
                    JOIN legal_entity AS entity
                      ON entity.id = sync_run.legal_entity_id
                    WHERE sync_run.job_type = 'SYNC_DOCUMENT_DETAILS'
                      AND sync_run.status IN ('SUCCESS', 'PARTIAL')
                      AND sync_run.legal_entity_id IS NOT NULL
                      AND sync_run.product_group IS NOT NULL
                    ORDER BY sync_run.id DESC
                    LIMIT 1
                    """
                )
            else:
                if run_id < 1:
                    raise ValueError("run_id должен быть больше 0.")

                cursor.execute(
                    """
                    SELECT
                        sync_run.id,
                        sync_run.legal_entity_id,
                        sync_run.product_group,
                        sync_run.status,
                        sync_run.records_received,
                        entity.storage_slug,
                        entity.short_name
                    FROM sys_sync_run AS sync_run
                    JOIN legal_entity AS entity
                      ON entity.id = sync_run.legal_entity_id
                    WHERE sync_run.id = %s
                      AND sync_run.job_type = 'SYNC_DOCUMENT_DETAILS'
                      AND sync_run.status IN ('SUCCESS', 'PARTIAL')
                    LIMIT 1
                    """,
                    (run_id,),
                )

            row = cursor.fetchone()
        finally:
            cursor.close()

    if row is None:
        if run_id is None:
            raise ValueError(
                "Не найден завершённый scoped-запуск "
                "SYNC_DOCUMENT_DETAILS."
            )

        raise ValueError(
            "Не найден завершённый запуск "
            f"SYNC_DOCUMENT_DETAILS id={run_id}."
        )

    legal_entity_value = row["legal_entity_id"]
    product_group_value = row["product_group"]

    if legal_entity_value is None:
        raise ValueError("У запуска отсутствует legal_entity_id.")

    if product_group_value is None:
        raise ValueError("У запуска отсутствует product_group.")

    legal_entity_id = int(legal_entity_value)
    product_group = str(product_group_value).strip().lower()

    if legal_entity_id < 1:
        raise ValueError("У запуска указан некорректный legal_entity_id.")

    if not product_group:
        raise ValueError("Товарная группа запуска пуста.")

    return DetailsRunScope(
        run_id=int(row["id"]),
        legal_entity_id=legal_entity_id,
        product_group=product_group,
        status=str(row["status"]).strip().upper(),
        records_received=int(row["records_received"] or 0),
        storage_slug=str(row["storage_slug"]).strip().lower(),
        organization_name=str(row["short_name"]).strip(),
    )


def load_targets(
    database: Database,
    run_scope: DetailsRunScope,
) -> tuple[list[CoreDocumentTarget], int, int]:
    with database.transaction() as connection:
        cursor = connection.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT
                    observation.id AS observation_id,
                    observation.core_document_id,
                    observation.legal_entity_id,
                    observation.product_group,
                    observation.sync_run_id,
                    observation.observed_at,
                    document.external_document_id,
                    document.document_type,
                    document.doc_date,
                    document.invoice_date,
                    document.received_at
                FROM core_document_observation AS observation
                JOIN core_document AS document
                  ON document.id = observation.core_document_id
                WHERE observation.sync_run_id = %s
                ORDER BY
                    observation.core_document_id,
                    observation.observed_at,
                    observation.id
                """,
                (run_scope.run_id,),
            )

            observations = [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    if run_scope.records_received > 0 and not observations:
        raise RuntimeError(
            "DOCUMENT_OBSERVATIONS_NOT_FOUND: запуск содержит "
            "полученные документы, но записи "
            "core_document_observation отсутствуют."
        )

    targets: list[CoreDocumentTarget] = []
    processed_ids: set[int] = set()
    unsupported_type_count = 0
    missing_uuid_count = 0

    for observation in observations:
        observation_run_id = int(observation["sync_run_id"])
        observation_entity_id = int(observation["legal_entity_id"])
        observation_group = str(
            observation["product_group"]
        ).strip().lower()

        if observation_run_id != run_scope.run_id:
            raise RuntimeError("DOCUMENT_OBSERVATION_RUN_MISMATCH")

        if observation_entity_id != run_scope.legal_entity_id:
            raise RuntimeError("DOCUMENT_OBSERVATION_ENTITY_MISMATCH")

        if observation_group != run_scope.product_group:
            raise RuntimeError("DOCUMENT_OBSERVATION_GROUP_MISMATCH")

        core_document_id = int(observation["core_document_id"])

        if core_document_id in processed_ids:
            continue

        processed_ids.add(core_document_id)

        external_document_id = str(
            observation["external_document_id"] or ""
        ).strip()

        if not external_document_id:
            raise RuntimeError(
                f"Канонический документ id={core_document_id} "
                "не содержит external_document_id."
            )

        document_type_value = observation["document_type"]

        document_type = (
            str(document_type_value).strip().upper()
            if document_type_value is not None
            else None
        )

        if document_type not in SUPPORTED_DOCUMENT_TYPES:
            unsupported_type_count += 1

            typer.echo(
                f"CORE id={core_document_id}: "
                "SKIP_UNSUPPORTED_TYPE; "
                f"type={document_type or '-'}"
            )

            continue

        document_uuid = extract_document_uuid(external_document_id)

        if document_uuid is None or not document_uuid.strip():
            missing_uuid_count += 1

            typer.echo(
                f"CORE id={core_document_id}: SKIP_UUID_NOT_FOUND"
            )

            continue

        targets.append(
            CoreDocumentTarget(
                core_document_id=core_document_id,
                external_document_id=external_document_id,
                document_type=document_type,
                document_uuid=document_uuid.strip().lower(),
                document_date=resolve_document_date(
                    observation.get("doc_date"),
                    observation.get("invoice_date"),
                    observation.get("received_at"),
                ),
            )
        )

    return targets, unsupported_type_count, missing_uuid_count

def load_completed_documents(
    database: Database,
    targets: list[CoreDocumentTarget],
) -> dict[str, int]:
    document_uuids = sorted(
        {
            target.document_uuid
            for target in targets
        }
    )

    if not document_uuids:
        return {}

    result: dict[str, int] = {}

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            for offset in range(
                0,
                len(document_uuids),
                COMPLETED_DOCUMENT_BATCH_SIZE,
            ):
                chunk = document_uuids[
                    offset:
                    offset + COMPLETED_DOCUMENT_BATCH_SIZE
                ]

                placeholders = ", ".join(
                    ["%s"] * len(chunk)
                )

                cursor.execute(
                    f"""
                    SELECT
                        source_message_id,
                        core_document_id
                    FROM raw_edo_document
                    WHERE source_message_id IN ({placeholders})
                      AND parse_status = 'PARSED'
                      AND match_status = 'MATCHED'
                      AND core_document_id IS NOT NULL
                    """,
                    tuple(chunk),
                )

                for row in cursor.fetchall():
                    source_message_id = str(
                        row[0]
                    ).strip().lower()

                    core_document_id = int(
                        row[1]
                    )

                    existing = result.get(
                        source_message_id
                    )

                    if (
                        existing is not None
                        and existing != core_document_id
                    ):
                        raise RuntimeError(
                            "EDO_DOCUMENT_MATCH_CONFLICT: "
                            "один UUID XML ЭДО связан "
                            "с несколькими CORE-документами. "
                            f"UUID={source_message_id}; "
                            f"первый CORE id={existing}; "
                            f"второй CORE id={core_document_id}."
                        )

                    result[
                        source_message_id
                    ] = core_document_id
        finally:
            cursor.close()

    return result


def resolve_pipeline_processing_mode(
    database: Database,
    legal_entity_id: int,
) -> bool:
    with database.transaction() as connection:
        cursor = connection.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT
                    config.current_run_uuid,
                    config.process_upd_enabled,

                    EXISTS (
                        SELECT 1
                        FROM sys_pipeline_task_entity AS selection
                        WHERE selection.task_code = 'PROCESS_UPD'
                          AND selection.legal_entity_id = %s
                    ) AS entity_selected

                FROM sys_pipeline_config AS config

                WHERE config.id = 1
                LIMIT 1
                """,
                (legal_entity_id,),
            )

            row = cursor.fetchone()
        finally:
            cursor.close()

    if row is None or not row["current_run_uuid"]:
        return True

    return bool(
        row["process_upd_enabled"]
        and row["entity_selected"]
    )


def register_downloaded_file(
    *,
    database: Database,
    run_scope: DetailsRunScope,
    target: CoreDocumentTarget,
    output_root: Path,
    xml_path: Path,
) -> int:
    resolved_root = output_root.resolve()
    resolved_path = xml_path.resolve()

    try:
        relative_path = resolved_path.relative_to(
            resolved_root
        ).as_posix()
    except ValueError as exc:
        raise ValueError(
            "Скачанный XML находится за пределами "
            "каталога официальных документов."
        ) from exc

    content = resolved_path.read_bytes()

    content_sha256 = hashlib.sha256(
        content
    ).hexdigest()

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO upd_download_file (
                    legal_entity_id,
                    product_group,
                    details_run_id,
                    core_document_id,
                    document_uuid,
                    relative_path,
                    content_sha256,
                    file_size_bytes,
                    status,
                    downloaded_at,
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
                    'DOWNLOADED',
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                ON DUPLICATE KEY UPDATE
                    id = LAST_INSERT_ID(id),

                    relative_path =
                        VALUES(relative_path),

                    file_size_bytes =
                        VALUES(file_size_bytes),

                    status = CASE
                        WHEN status = 'PROCESSED'
                            THEN 'PROCESSED'
                        ELSE 'DOWNLOADED'
                    END,

                    last_error_type = NULL,
                    last_error_message = NULL,

                    downloaded_at =
                        UTC_TIMESTAMP(6),

                    updated_at =
                        UTC_TIMESTAMP(6)
                """,
                (
                    run_scope.legal_entity_id,
                    run_scope.product_group,
                    run_scope.run_id,
                    target.core_document_id,
                    target.document_uuid,
                    relative_path,
                    content_sha256,
                    len(content),
                ),
            )

            return int(
                cursor.lastrowid
            )
        finally:
            cursor.close()


def mark_download_file_processed(
    *,
    database: Database,
    download_file_id: int,
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
                    download_file_id,
                ),
            )
        finally:
            cursor.close()


async def sync_edo_documents(
    *,
    token: str,
    run_id: int | None,
    output_root: Path,
    delay_ms: int,
    force: bool,
    fail_fast: bool,
    process_documents: bool | None = None,
) -> EdoSyncSummary:
    if delay_ms < 0:
        raise ValueError(
            "delay_ms не может быть отрицательным."
        )

    prepared_token = token.strip()

    if not prepared_token:
        raise ValueError(
            "Токен True API не передан."
        )

    settings = get_settings()
    database = Database(settings)

    run_scope = resolve_details_run(
        database,
        run_id,
    )

    if process_documents is None:
        process_documents = resolve_pipeline_processing_mode(
            database,
            run_scope.legal_entity_id,
        )

    (
        targets,
        unsupported_type_count,
        missing_uuid_count,
    ) = load_targets(
        database,
        run_scope,
    )

    typer.echo(
        "Пакетная загрузка XML ЭДО."
    )

    typer.echo(
        "Источник наблюдений: "
        "SYNC_DOCUMENT_DETAILS "
        f"id={run_scope.run_id}"
    )

    typer.echo(
        f"Организация: "
        f"{run_scope.legal_entity_id}"
    )

    typer.echo(
        f"Товарная группа: "
        f"{run_scope.product_group}"
    )

    typer.echo(
        f"Поддерживаемых документов: "
        f"{len(targets)}"
    )

    typer.echo(
        "Режим XML УПД/УКД: "
        + (
            "скачивание, обработка "
            "и раскрытие КИ"
            if process_documents
            else "только скачивание"
        )
    )

    typer.echo(
        f"Пропущено по типу: "
        f"{unsupported_type_count}"
    )

    typer.echo(
        f"Без UUID: "
        f"{missing_uuid_count}"
    )

    if not targets:
        return EdoSyncSummary(
            run_id=run_scope.run_id,
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
        token=prepared_token,
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
                    "CORE id="
                    f"{target.core_document_id}: "
                    "SKIP_ALREADY_PROCESSED; "
                    "document_id="
                    f"{target.document_uuid}"
                )

                continue

            if (
                not force
                and completed_core_document_id
                is not None
                and completed_core_document_id
                != target.core_document_id
            ):
                raise RuntimeError(
                    "EDO_TARGET_CORE_CONFLICT: "
                    "UUID уже обработан, "
                    "но связан с другим "
                    "CORE-документом. "
                    f"UUID={target.document_uuid}; "
                    "ожидаемый CORE id="
                    f"{target.core_document_id}; "
                    "существующий CORE id="
                    f"{completed_core_document_id}."
                )

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
                    "CORE id="
                    f"{target.core_document_id}: "
                    f"HTTP {response.status_code}; "
                    "Content-Type="
                    f"{response.content_type or '-'}; "
                    "bytes="
                    f"{len(response.content)}; "
                    "elapsed_ms="
                    f"{response.elapsed_ms}"
                )

                document_directory = (
                    build_document_directory(
                        root=prepared_output_root,
                        storage_slug=(
                            run_scope.storage_slug
                        ),
                        document_type=(
                            target.document_type
                        ),
                        document_date=(
                            target.document_date
                        ),
                    )
                )

                (
                    response_format,
                    xml_paths,
                ) = extract_edo_xml(
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
                        "поддерживаемый товарный "
                        "XML титула продавца "
                        "УПД/УПД(и) или "
                        "УКД/УКД(и)."
                    )

                downloaded_files = [
                    (
                        xml_path,

                        register_downloaded_file(
                            database=database,
                            run_scope=run_scope,
                            target=target,
                            output_root=(
                                prepared_output_root
                            ),
                            xml_path=xml_path,
                        ),
                    )

                    for xml_path in xml_paths
                ]

                if not process_documents:
                    for (
                        xml_path,
                        _,
                    ) in downloaded_files:
                        typer.echo(
                            "    "
                            f"format="
                            f"{response_format}; "
                            f"file="
                            f"{xml_path.name}; "
                            "mode=DOWNLOAD_ONLY"
                        )

                    if delay_ms > 0:
                        await asyncio.sleep(
                            delay_ms / 1000
                        )

                    continue

                target_matched = False

                for (
                    xml_path,
                    download_file_id,
                ) in downloaded_files:
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
                            token=(
                                prepared_token
                            ),
                            product_group=(
                                run_scope.product_group
                            ),
                        )
                    )

                    typer.echo(
                        "    "
                        f"format="
                        f"{response_format}; "
                        f"file="
                        f"{xml_path.name}; "
                        "RAW id="
                        f"{processing_result.raw_document_id}; "
                        "import="
                        f"{'NEW' if processing_result.created else 'DUPLICATE'}; "
                        "kind="
                        f"{processing_result.document_kind}; "
                        "pg="
                        f"{processing_result.product_group or '-'}; "
                        "parse="
                        f"{processing_result.parse_status}; "
                        "match="
                        f"{processing_result.match_status}; "
                        "core_document_id="
                        f"{processing_result.core_document_id or '-'}; "
                        "lines="
                        f"{processing_result.line_count}; "
                        "source_codes="
                        f"{processing_result.code_count}; "
                        "roots="
                        f"{processing_result.datamatrix_source_count}; "
                        "aggregates="
                        f"{processing_result.datamatrix_aggregate_count}; "
                        "units="
                        f"{processing_result.datamatrix_terminal_count}; "
                        "quantity_mismatches="
                        f"{processing_result.datamatrix_mismatch_count}"
                    )

                    if (
                        processing_result
                        .product_lookup_error
                    ):
                        typer.echo(
                            "        WARNING "
                            "product/info: "
                            f"{processing_result.product_lookup_error}",
                            err=True,
                        )

                    if (
                        processing_result.match_status
                        == "MATCHED"

                        and processing_result
                        .core_document_id
                        == target.core_document_id
                    ):
                        target_matched = True

                        mark_download_file_processed(
                            database=database,
                            download_file_id=(
                                download_file_id
                            ),
                            raw_document_id=(
                                processing_result
                                .raw_document_id
                            ),
                        )

                if not target_matched:
                    raise RuntimeError(
                        "XML обработан, но не связан "
                        "с ожидаемым "
                        "core_document.id="
                        f"{target.core_document_id}."
                    )

                matched_count += 1

            except GisMtAuthError:
                raise

            except Exception as exc:
                error_count += 1

                typer.echo(
                    f"{index}/{len(targets)} "
                    "CORE id="
                    f"{target.core_document_id}: "
                    "ERROR "
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
        run_id=run_scope.run_id,

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

        error_count=(
            error_count
        ),
    )

def main(
    run_id: int | None = typer.Option(
        None,
        "--run-id",
        min=1,
        help=(
            "ID scoped-запуска "
            "SYNC_DOCUMENT_DETAILS. "
            "По умолчанию используется "
            "последний завершённый запуск."
        ),
    ),

    output_root: Path = typer.Option(
        Path(
            "/data/official"
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
            "обработанные документы."
        ),
    ),

    download_only: bool = typer.Option(
        False,
        "--download-only",
        help=(
            "Только скачать XML "
            "для последующей обработки."
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
    Пакетно скачивает официальные XML ЭДО
    и при необходимости раскрывает
    содержащиеся в них агрегаты
    до КИ единиц товара.
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
                process_documents=(
                    not download_only
                ),
            )
        )

    except GisMtAuthError as exc:
        typer.echo(
            "AUTH ERROR: токен True API "
            "отклонён или истёк.",
            err=True,
        )

        typer.echo(
            str(exc),
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

    token = ""

    typer.echo("")

    typer.echo(
        "Пакетная загрузка XML ЭДО "
        "завершена."
    )

    typer.echo(
        f"Запуск наблюдений: "
        f"{summary.run_id}"
    )

    typer.echo(
        f"Выбрано документов: "
        f"{summary.selected_count}"
    )

    typer.echo(
        f"Уже обработано: "
        f"{summary.already_processed_count}"
    )

    typer.echo(
        f"Скачано: "
        f"{summary.downloaded_count}"
    )

    typer.echo(
        f"Успешно связано: "
        f"{summary.matched_count}"
    )

    typer.echo(
        f"Пропущено по типу: "
        f"{summary.unsupported_type_count}"
    )

    typer.echo(
        f"Без UUID: "
        f"{summary.missing_uuid_count}"
    )

    typer.echo(
        f"Ошибок: "
        f"{summary.error_count}"
    )

    if summary.error_count > 0:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(main)
