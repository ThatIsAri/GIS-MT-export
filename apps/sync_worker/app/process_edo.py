from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from app.cli import read_token_from_stdin
from app.config import get_settings
from app.datamatrix_storage import (
    DatamatrixSyncSummary,
    sync_datamatrix_units,
)
from app.db import Database
from app.edo_document_type import (
    DOCUMENT_KIND_UKD,
    document_kind_from_xml,
)
from app.import_edo_xml import (
    FileImportResult,
    find_xml_files,
    import_xml_file,
)
from app.match_edo_document import (
    MatchDecision,
    mark_match_error,
    match_one,
)
from app.parse_edo_document import (
    load_raw_document,
    mark_parse_error,
    parse_xml,
    persist_document,
)
from app.parse_ukd_document import parse_ukd_xml
from app.reconcile_ukd_datamatrix import (
    UkdDatamatrixReconcileSummary,
    reconcile_ukd_datamatrix_units,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ProcessingResult:
    file_path: Path
    raw_document_id: int
    created: bool

    parse_status: str
    match_status: str

    core_document_id: int | None

    line_count: int
    code_count: int

    document_kind: str = "UNKNOWN"
    product_group: str | None = None

    datamatrix_source_count: int = 0
    datamatrix_aggregate_count: int = 0
    datamatrix_terminal_count: int = 0

    datamatrix_inserted_count: int = 0
    datamatrix_updated_count: int = 0
    datamatrix_unchanged_count: int = 0
    datamatrix_removed_count: int = 0

    datamatrix_mismatch_count: int = 0
    datamatrix_product_count: int = 0

    aggregate_request_count: int = 0
    product_request_count: int = 0

    product_lookup_error: str | None = None

    ukd_removed_source_count: int = 0
    ukd_removed_unit_count: int = 0
    ukd_skipped_newer_count: int = 0


def _empty_datamatrix_summary(
    *,
    raw_document_id: int,
    core_document_id: int,
    product_group: str,
) -> DatamatrixSyncSummary:
    return DatamatrixSyncSummary(
        raw_document_id=raw_document_id,
        core_document_id=core_document_id,
        legal_entity_id=None,
        product_group=product_group,
        source_count=0,
        aggregate_count=0,
        terminal_count=0,
        inserted_count=0,
        updated_count=0,
        unchanged_count=0,
        removed_count=0,
        source_inserted_count=0,
        source_updated_count=0,
        source_unchanged_count=0,
        mismatch_count=0,
        product_count=0,
        aggregate_request_count=0,
        product_request_count=0,
        product_lookup_error=None,
        receiver_warehouse_address=None,
    )


def _empty_ukd_reconcile_summary(
) -> UkdDatamatrixReconcileSummary:
    return UkdDatamatrixReconcileSummary(
        before_count=0,
        after_count=0,
        removed_count=0,
        removed_unit_count=0,
        skipped_newer_count=0,
    )


def process_imported_document(
    *,
    database: Database,
    file_path: Path,
    import_result: FileImportResult,
    token: str,
    product_group: str,
) -> ProcessingResult:
    """
    Выполняет полный цикл для одного XML ЭДО:

    1. читает неизменяемое содержимое из RAW;
    2. определяет вид документа УПД/УКД;
    3. разбирает товарные строки и корневые КИ;
    4. сопоставляет XML с CORE;
    5. раскрывает каждый корневой КИ через True API;
    6. сохраняет только конечные КИ единиц товара;
    7. для УКД удаляет корни состояния «до»,
       которых нет в состоянии «после».
    """

    raw_document_id = (
        import_result.raw_document_id
    )

    prepared_token = token.strip()

    prepared_product_group = (
        product_group
        .strip()
        .lower()
    )

    if not import_result.well_formed:
        return ProcessingResult(
            file_path=file_path,
            raw_document_id=(
                raw_document_id
            ),
            created=(
                import_result.created
            ),
            parse_status="INVALID_XML",
            match_status="NOT_PROCESSED",
            core_document_id=None,
            line_count=0,
            code_count=0,
            document_kind="UNKNOWN",
            product_group=(
                prepared_product_group
                or None
            ),
        )

    try:
        (
            xml_content,
            well_formed,
        ) = load_raw_document(
            database=database,
            raw_document_id=(
                raw_document_id
            ),
        )

        if not well_formed:
            raise ValueError(
                "RAW-документ не отмечен "
                "как корректный XML."
            )

        document_kind = (
            document_kind_from_xml(
                xml_content
            )
        )

        if (
            document_kind
            == DOCUMENT_KIND_UKD
        ):
            (
                external_document_id,
                lines,
            ) = parse_ukd_xml(
                xml_content
            )

        else:
            (
                external_document_id,
                lines,
            ) = parse_xml(
                xml_content
            )

        (
            parsed_core_document_id,
            parse_status,
            code_counts,
        ) = persist_document(
            database=database,
            raw_document_id=(
                raw_document_id
            ),
            external_document_id=(
                external_document_id
            ),
            lines=lines,
        )

    except Exception as exc:
        try:
            mark_parse_error(
                database=database,
                raw_document_id=(
                    raw_document_id
                ),
                error=exc,
            )

        except Exception:
            pass

        raise RuntimeError(
            "Ошибка разбора XML: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    try:
        decision: MatchDecision = (
            match_one(
                database=database,
                raw_document_id=(
                    raw_document_id
                ),
            )
        )

    except Exception as exc:
        try:
            mark_match_error(
                database=database,
                raw_document_id=(
                    raw_document_id
                ),
                error=exc,
            )

        except Exception:
            pass

        raise RuntimeError(
            "Ошибка сопоставления XML "
            "с CORE: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc

    total_code_count = sum(
        code_counts.values()
    )

    final_parse_status = (
        "PARSED"
        if decision.status
        == "MATCHED"
        else parse_status
    )

    final_core_document_id = (
        decision.core_document_id
        or parsed_core_document_id
    )

    datamatrix_summary: (
        DatamatrixSyncSummary
        | None
    ) = None

    ukd_summary = (
        _empty_ukd_reconcile_summary()
    )

    if (
        decision.status
        == "MATCHED"
        and final_core_document_id
        is not None
    ):
        if not prepared_token:
            raise RuntimeError(
                "Документ сопоставлен с CORE, "
                "но токен True API для "
                "раскрытия КИ не передан."
            )

        if not prepared_product_group:
            raise RuntimeError(
                "Документ сопоставлен с CORE, "
                "но товарная группа для "
                "раскрытия КИ не указана."
            )

        try:
            datamatrix_summary = (
                sync_datamatrix_units(
                    database=database,
                    raw_document_id=(
                        raw_document_id
                    ),
                    core_document_id=(
                        final_core_document_id
                    ),
                    xml_content=(
                        xml_content
                    ),
                    token=(
                        prepared_token
                    ),
                    product_group=(
                        prepared_product_group
                    ),
                )
            )

            if (
                document_kind
                == DOCUMENT_KIND_UKD
            ):
                ukd_summary = (
                    reconcile_ukd_datamatrix_units(
                        database=database,
                        raw_document_id=(
                            raw_document_id
                        ),
                        core_document_id=(
                            final_core_document_id
                        ),
                    )
                )

        except Exception as exc:
            raise RuntimeError(
                "Ошибка раскрытия и "
                "сохранения КИ единиц товара: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ) from exc

    if datamatrix_summary is None:
        datamatrix_summary = (
            _empty_datamatrix_summary(
                raw_document_id=(
                    raw_document_id
                ),
                core_document_id=(
                    final_core_document_id
                    or 0
                ),
                product_group=(
                    prepared_product_group
                ),
            )
        )

    return ProcessingResult(
        file_path=file_path,
        raw_document_id=(
            raw_document_id
        ),
        created=(
            import_result.created
        ),
        parse_status=(
            final_parse_status
        ),
        match_status=(
            decision.status
        ),
        core_document_id=(
            final_core_document_id
        ),
        line_count=len(
            lines
        ),
        code_count=(
            total_code_count
        ),
        document_kind=(
            document_kind
        ),
        product_group=(
            prepared_product_group
            or None
        ),
        datamatrix_source_count=(
            datamatrix_summary
            .source_count
        ),
        datamatrix_aggregate_count=(
            datamatrix_summary
            .aggregate_count
        ),
        datamatrix_terminal_count=(
            datamatrix_summary
            .terminal_count
        ),
        datamatrix_inserted_count=(
            datamatrix_summary
            .inserted_count
        ),
        datamatrix_updated_count=(
            datamatrix_summary
            .updated_count
        ),
        datamatrix_unchanged_count=(
            datamatrix_summary
            .unchanged_count
        ),
        datamatrix_removed_count=(
            datamatrix_summary
            .removed_count
        ),
        datamatrix_mismatch_count=(
            datamatrix_summary
            .mismatch_count
        ),
        datamatrix_product_count=(
            datamatrix_summary
            .product_count
        ),
        aggregate_request_count=(
            datamatrix_summary
            .aggregate_request_count
        ),
        product_request_count=(
            datamatrix_summary
            .product_request_count
        ),
        product_lookup_error=(
            datamatrix_summary
            .product_lookup_error
        ),
        ukd_removed_source_count=(
            ukd_summary
            .removed_count
        ),
        ukd_removed_unit_count=(
            ukd_summary
            .removed_unit_count
        ),
        ukd_skipped_newer_count=(
            ukd_summary
            .skipped_newer_count
        ),
    )


def print_result(
    *,
    index: int,
    total: int,
    result: ProcessingResult,
) -> None:
    """
    Выводит итог обработки
    одного XML.
    """

    import_status = (
        "NEW"
        if result.created
        else "DUPLICATE"
    )

    core_value = (
        str(
            result.core_document_id
        )
        if result.core_document_id
        is not None
        else "-"
    )

    typer.echo(
        f"{index}/{total} "
        f"{result.file_path.name}: "
        f"RAW id="
        f"{result.raw_document_id}; "
        f"import="
        f"{import_status}; "
        f"kind="
        f"{result.document_kind}; "
        f"pg="
        f"{result.product_group or '-'}; "
        f"parse="
        f"{result.parse_status}; "
        f"match="
        f"{result.match_status}; "
        f"core_document_id="
        f"{core_value}; "
        f"lines="
        f"{result.line_count}; "
        f"source_codes="
        f"{result.code_count}; "
        f"roots="
        f"{result.datamatrix_source_count}; "
        f"aggregates="
        f"{result.datamatrix_aggregate_count}; "
        f"units="
        f"{result.datamatrix_terminal_count}; "
        f"unit_inserted="
        f"{result.datamatrix_inserted_count}; "
        f"unit_updated="
        f"{result.datamatrix_updated_count}; "
        f"unit_unchanged="
        f"{result.datamatrix_unchanged_count}; "
        f"unit_removed="
        f"{result.datamatrix_removed_count}; "
        f"quantity_mismatches="
        f"{result.datamatrix_mismatch_count}; "
        f"ukd_removed_roots="
        f"{result.ukd_removed_source_count}; "
        f"ukd_removed_units="
        f"{result.ukd_removed_unit_count}"
    )

    if result.product_lookup_error:
        typer.echo(
            "    Предупреждение "
            "product/info: "
            f"{result.product_lookup_error}",
            err=True,
        )


def main(
    path: Path = typer.Option(
        Path(
            "/data/edo_inbox"
        ),
        "--path",
        file_okay=True,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help=(
            "XML-файл или каталог "
            "с XML ЭДО."
        ),
    ),

    product_group: str = typer.Option(
        ...,
        "--pg",
        help=(
            "Код товарной группы "
            "True API, например "
            "softdrinks."
        ),
    ),

    source_system: str = typer.Option(
        "EDO_MANUAL",
        "--source-system",
        help=(
            "Код источника XML."
        ),
    ),

    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help=(
            "Искать XML во вложенных "
            "каталогах."
        ),
    ),

    max_file_size_mb: int = typer.Option(
        50,
        "--max-file-size-mb",
        min=1,
        max=500,
        help=(
            "Максимальный размер "
            "одного XML."
        ),
    ),
) -> None:
    """
    Импортирует, разбирает,
    сопоставляет XML ЭДО
    и раскрывает корневые КИ
    до конечных КИ единиц товара.

    Токен True API передаётся
    только через stdin.
    """

    prepared_source_system = (
        source_system.strip()
    )

    prepared_product_group = (
        product_group
        .strip()
        .lower()
    )

    if not prepared_source_system:
        raise typer.BadParameter(
            "Значение source-system "
            "не может быть пустым."
        )

    if len(
        prepared_source_system
    ) > 64:
        raise typer.BadParameter(
            "Значение source-system "
            "превышает 64 символа."
        )

    if not prepared_product_group:
        raise typer.BadParameter(
            "Значение --pg "
            "не может быть пустым."
        )

    if len(
        prepared_product_group
    ) > 64:
        raise typer.BadParameter(
            "Значение --pg "
            "превышает 64 символа."
        )

    resolved_path = path.resolve()

    if not resolved_path.exists():
        raise typer.BadParameter(
            f"Путь не найден: "
            f"{resolved_path}"
        )

    if resolved_path.is_file():
        if (
            resolved_path
            .suffix
            .lower()
            != ".xml"
        ):
            raise typer.BadParameter(
                "Указанный файл не имеет "
                "расширение .xml."
            )

        import_root = (
            resolved_path.parent
        )

        files = [
            resolved_path
        ]

    elif resolved_path.is_dir():
        import_root = (
            resolved_path
        )

        files = find_xml_files(
            root=resolved_path,
            recursive=recursive,
        )

    else:
        raise typer.BadParameter(
            "Путь не является файлом "
            "или каталогом: "
            f"{resolved_path}"
        )

    typer.echo(
        f"Путь обработки: "
        f"{resolved_path}"
    )

    typer.echo(
        f"Товарная группа: "
        f"{prepared_product_group}"
    )

    typer.echo(
        f"Найдено XML-файлов: "
        f"{len(files)}"
    )

    if not files:
        typer.echo(
            "Обработка не требуется: "
            "XML-файлы не найдены."
        )

        return

    token = read_token_from_stdin()

    database = Database(
        get_settings()
    )

    max_file_size_bytes = (
        max_file_size_mb
        * 1024
        * 1024
    )

    counters = {
        "NEW": 0,
        "DUPLICATE": 0,
        "INVALID_XML": 0,
        "MATCHED": 0,
        "UNMATCHED": 0,
        "AMBIGUOUS": 0,
        "ERROR": 0,
        "ROOTS": 0,
        "AGGREGATES": 0,
        "UNITS": 0,
        "UNIT_INSERTED": 0,
        "UNIT_UPDATED": 0,
        "UNIT_UNCHANGED": 0,
        "UNIT_REMOVED": 0,
        "MISMATCH": 0,
        "UKD_REMOVED_ROOTS": 0,
        "UKD_REMOVED_UNITS": 0,
    }

    processed_raw_ids: set[
        int
    ] = set()

    for index, file_path in (
        enumerate(
            files,
            start=1,
        )
    ):
        try:
            import_result = (
                import_xml_file(
                    database=database,
                    root=import_root,
                    file_path=file_path,
                    source_system=(
                        prepared_source_system
                    ),
                    max_file_size_bytes=(
                        max_file_size_bytes
                    ),
                )
            )

            import_counter = (
                "NEW"
                if import_result.created
                else "DUPLICATE"
            )

            counters[
                import_counter
            ] += 1

            raw_document_id = (
                import_result
                .raw_document_id
            )

            if (
                raw_document_id
                in processed_raw_ids
            ):
                typer.echo(
                    f"{index}/"
                    f"{len(files)} "
                    f"{file_path.name}: "
                    "содержимое уже "
                    "обработано в текущем "
                    "запуске; "
                    f"RAW id="
                    f"{raw_document_id}"
                )

                continue

            processed_raw_ids.add(
                raw_document_id
            )

            result = (
                process_imported_document(
                    database=database,
                    file_path=file_path,
                    import_result=(
                        import_result
                    ),
                    token=token,
                    product_group=(
                        prepared_product_group
                    ),
                )
            )

            if (
                result.parse_status
                == "INVALID_XML"
            ):
                counters[
                    "INVALID_XML"
                ] += 1

            else:
                counters[
                    result.match_status
                ] += 1

            counters[
                "ROOTS"
            ] += (
                result
                .datamatrix_source_count
            )

            counters[
                "AGGREGATES"
            ] += (
                result
                .datamatrix_aggregate_count
            )

            counters[
                "UNITS"
            ] += (
                result
                .datamatrix_terminal_count
            )

            counters[
                "UNIT_INSERTED"
            ] += (
                result
                .datamatrix_inserted_count
            )

            counters[
                "UNIT_UPDATED"
            ] += (
                result
                .datamatrix_updated_count
            )

            counters[
                "UNIT_UNCHANGED"
            ] += (
                result
                .datamatrix_unchanged_count
            )

            counters[
                "UNIT_REMOVED"
            ] += (
                result
                .datamatrix_removed_count
            )

            counters[
                "MISMATCH"
            ] += (
                result
                .datamatrix_mismatch_count
            )

            counters[
                "UKD_REMOVED_ROOTS"
            ] += (
                result
                .ukd_removed_source_count
            )

            counters[
                "UKD_REMOVED_UNITS"
            ] += (
                result
                .ukd_removed_unit_count
            )

            print_result(
                index=index,
                total=len(
                    files
                ),
                result=result,
            )

        except Exception as exc:
            counters[
                "ERROR"
            ] += 1

            typer.echo(
                f"{index}/"
                f"{len(files)} "
                f"{file_path.name}: "
                "ERROR; "
                f"{type(exc).__name__}: "
                f"{exc}",
                err=True,
            )

    token = ""

    typer.echo("")

    typer.echo(
        "Обработка XML ЭДО "
        "завершена."
    )

    typer.echo(
        "Новых RAW-документов: "
        f"{counters['NEW']}"
    )

    typer.echo(
        "Повторных файлов: "
        f"{counters['DUPLICATE']}"
    )

    typer.echo(
        "Некорректных XML: "
        f"{counters['INVALID_XML']}"
    )

    typer.echo(
        "MATCHED: "
        f"{counters['MATCHED']}"
    )

    typer.echo(
        "UNMATCHED: "
        f"{counters['UNMATCHED']}"
    )

    typer.echo(
        "AMBIGUOUS: "
        f"{counters['AMBIGUOUS']}"
    )

    typer.echo(
        "Корневых КИ: "
        f"{counters['ROOTS']}"
    )

    typer.echo(
        "Агрегатов: "
        f"{counters['AGGREGATES']}"
    )

    typer.echo(
        "Конечных КИ единиц: "
        f"{counters['UNITS']}"
    )

    typer.echo(
        "КИ единиц: "
        f"добавлено="
        f"{counters['UNIT_INSERTED']}; "
        f"обновлено="
        f"{counters['UNIT_UPDATED']}; "
        f"без изменений="
        f"{counters['UNIT_UNCHANGED']}; "
        f"удалено="
        f"{counters['UNIT_REMOVED']}."
    )

    typer.echo(
        "Несовпадений количества: "
        f"{counters['MISMATCH']}"
    )

    typer.echo(
        "УКД удалено: "
        f"корней="
        f"{counters['UKD_REMOVED_ROOTS']}; "
        f"единиц="
        f"{counters['UKD_REMOVED_UNITS']}."
    )

    typer.echo(
        "ERROR: "
        f"{counters['ERROR']}"
    )

    if counters["ERROR"] > 0:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(
        main
    )