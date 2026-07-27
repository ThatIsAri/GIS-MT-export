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


@dataclass(
    frozen=True,
    slots=True,
)
class DetailsRunScope:
    """
    Организационная область запуска
    SYNC_DOCUMENT_DETAILS.
    """

    run_id: int
    legal_entity_id: int
    product_group: str
    status: str
    records_received: int


@dataclass(
    frozen=True,
    slots=True,
)
class CoreDocumentTarget:
    """
    Канонический документ, обнаруженный
    в выбранном scoped-запуске.
    """

    core_document_id: int
    external_document_id: str
    document_type: str | None
    document_uuid: str


@dataclass(
    frozen=True,
    slots=True,
)
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
    """
    Проверяет переданный scoped-запуск
    либо возвращает последний завершённый
    scoped-запуск SYNC_DOCUMENT_DETAILS.
    """

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            if run_id is None:
                cursor.execute(
                    """
                    SELECT
                        id,
                        legal_entity_id,
                        product_group,
                        status,
                        records_received
                    FROM sys_sync_run
                    WHERE job_type =
                          'SYNC_DOCUMENT_DETAILS'

                      AND status IN (
                          'SUCCESS',
                          'PARTIAL'
                      )

                      AND legal_entity_id
                          IS NOT NULL

                      AND product_group
                          IS NOT NULL

                    ORDER BY id DESC
                    LIMIT 1
                    """
                )

            else:
                if run_id < 1:
                    raise ValueError(
                        "run_id должен быть больше 0."
                    )

                cursor.execute(
                    """
                    SELECT
                        id,
                        legal_entity_id,
                        product_group,
                        status,
                        records_received
                    FROM sys_sync_run
                    WHERE id = %s

                      AND job_type =
                          'SYNC_DOCUMENT_DETAILS'

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
                "Не найден завершённый scoped-запуск "
                "SYNC_DOCUMENT_DETAILS."
            )

        raise ValueError(
            "Не найден завершённый запуск "
            f"SYNC_DOCUMENT_DETAILS id={run_id}."
        )

    legal_entity_value = row[
        "legal_entity_id"
    ]

    if legal_entity_value is None:
        raise ValueError(
            "У запуска отсутствует legal_entity_id. "
            "Наследуемые запуски без области "
            "организации не поддерживаются."
        )

    legal_entity_id = int(
        legal_entity_value
    )

    if legal_entity_id < 1:
        raise ValueError(
            "У запуска указан некорректный "
            "legal_entity_id."
        )

    product_group_value = row[
        "product_group"
    ]

    if product_group_value is None:
        raise ValueError(
            "У запуска отсутствует product_group."
        )

    product_group = str(
        product_group_value
    ).strip().lower()

    if not product_group:
        raise ValueError(
            "Товарная группа запуска пуста."
        )

    return DetailsRunScope(
        run_id=int(
            row["id"]
        ),
        legal_entity_id=legal_entity_id,
        product_group=product_group,
        status=str(
            row["status"]
        ).strip().upper(),
        records_received=int(
            row["records_received"] or 0
        ),
    )


def read_run_observations(
    database: Database,
    run_scope: DetailsRunScope,
) -> list[dict[str, Any]]:
    """
    Читает наблюдения канонических документов
    выбранного запуска.

    Таблица core_document используется только
    для получения канонических реквизитов.
    Область запуска определяется исключительно
    через core_document_observation.
    """

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    observation.id
                        AS observation_id,

                    observation.core_document_id,
                    observation.legal_entity_id,
                    observation.product_group,
                    observation.sync_run_id,
                    observation.raw_response_id,
                    observation.observed_at,

                    document.external_document_id,
                    document.document_type

                FROM core_document_observation
                    AS observation

                JOIN core_document
                    AS document
                  ON document.id =
                     observation.core_document_id

                WHERE observation.sync_run_id = %s

                ORDER BY
                    observation.core_document_id,
                    observation.observed_at,
                    observation.id
                """,
                (
                    run_scope.run_id,
                ),
            )

            return [
                dict(
                    row
                )
                for row in cursor.fetchall()
            ]

        finally:
            cursor.close()


def validate_observation_scope(
    *,
    observation: dict[str, Any],
    run_scope: DetailsRunScope,
) -> None:
    """
    Проверяет, что наблюдение относится
    к той же организации и товарной группе,
    что и служебный запуск.
    """

    observation_run_id = int(
        observation["sync_run_id"]
    )

    observation_entity_id = int(
        observation["legal_entity_id"]
    )

    observation_product_group = str(
        observation["product_group"]
    ).strip().lower()

    if (
        observation_run_id
        != run_scope.run_id
    ):
        raise RuntimeError(
            "DOCUMENT_OBSERVATION_RUN_MISMATCH: "
            "наблюдение относится к другому "
            "служебному запуску."
        )

    if (
        observation_entity_id
        != run_scope.legal_entity_id
    ):
        raise RuntimeError(
            "DOCUMENT_OBSERVATION_ENTITY_MISMATCH: "
            "наблюдение относится к другой "
            "организации."
        )

    if (
        observation_product_group
        != run_scope.product_group
    ):
        raise RuntimeError(
            "DOCUMENT_OBSERVATION_GROUP_MISMATCH: "
            "наблюдение относится к другой "
            "товарной группе."
        )


def load_targets(
    database: Database,
    run_scope: DetailsRunScope,
) -> tuple[
    list[CoreDocumentTarget],
    int,
    int,
]:
    """
    Выбирает уникальные канонические документы
    по наблюдениям выбранного запуска.

    Один core_document может иметь несколько
    наблюдений, поэтому итоговый список
    дедуплицируется по core_document_id.
    """

    observations = read_run_observations(
        database,
        run_scope,
    )

    if (
        run_scope.records_received > 0
        and not observations
    ):
        raise RuntimeError(
            "DOCUMENT_OBSERVATIONS_NOT_FOUND: "
            "запуск содержит полученные документы, "
            "но для него отсутствуют записи "
            "core_document_observation. "
            "Сначала необходимо выполнить "
            "перенос RAW в CORE."
        )

    targets: list[
        CoreDocumentTarget
    ] = []

    unsupported_type_count = 0
    missing_uuid_count = 0

    processed_core_document_ids: set[
        int
    ] = set()

    for observation in observations:
        validate_observation_scope(
            observation=observation,
            run_scope=run_scope,
        )

        core_document_id = int(
            observation[
                "core_document_id"
            ]
        )

        if (
            core_document_id
            in processed_core_document_ids
        ):
            continue

        processed_core_document_ids.add(
            core_document_id
        )

        external_document_id = str(
            observation[
                "external_document_id"
            ]
        ).strip()

        if not external_document_id:
            raise RuntimeError(
                "Канонический документ "
                f"id={core_document_id} "
                "не содержит external_document_id."
            )

        document_type_value = observation[
            "document_type"
        ]

        document_type = (
            str(
                document_type_value
            ).strip()
            if document_type_value is not None
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

        prepared_document_uuid = (
            document_uuid
            .strip()
            .lower()
        )

        if not prepared_document_uuid:
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
                document_type=(
                    document_type
                ),
                document_uuid=(
                    prepared_document_uuid
                ),
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

        UUID → core_document_id

    Обработанный XML является глобальным
    каноническим источником документа, поэтому
    повторная загрузка для другой организации
    или товарной группы не требуется.
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

                      AND core_document_id
                          IS NOT NULL
                    """,
                    tuple(
                        chunk
                    ),
                )

                for row in cursor.fetchall():
                    source_message_id = str(
                        row[0]
                    ).strip().lower()

                    core_document_id = int(
                        row[1]
                    )

                    existing_core_document_id = (
                        result.get(
                            source_message_id
                        )
                    )

                    if (
                        existing_core_document_id
                        is not None
                        and existing_core_document_id
                        != core_document_id
                    ):
                        raise RuntimeError(
                            "EDO_DOCUMENT_MATCH_CONFLICT: "
                            "один UUID XML ЭДО связан "
                            "с несколькими каноническими "
                            "документами. "
                            f"UUID={source_message_id}; "
                            "первый CORE id="
                            f"{existing_core_document_id}; "
                            "второй CORE id="
                            f"{core_document_id}."
                        )

                    result[
                        source_message_id
                    ] = core_document_id

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
    для документов выбранного scoped-запуска.

    Документы выбираются через
    core_document_observation.
    """

    if delay_ms < 0:
        raise ValueError(
            "delay_ms не может быть отрицательным."
        )

    settings = get_settings()

    database = Database(
        settings
    )

    run_scope = resolve_details_run(
        database,
        run_id,
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
        "Организация: "
        f"{run_scope.legal_entity_id}"
    )

    typer.echo(
        "Товарная группа: "
        f"{run_scope.product_group}"
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
                    "UUID уже обработан, но связан "
                    "с другим каноническим документом. "
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
                    import_result = import_xml_file(
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
        error_count=error_count,
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
            "последний завершённый "
            "scoped-запуск."
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
        "Запуск наблюдений: "
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