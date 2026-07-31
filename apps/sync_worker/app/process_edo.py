from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from app.config import get_settings
from app.datamatrix_storage import (
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
from app.parse_ukd_document import (
    parse_ukd_xml,
)
from app.reconcile_ukd_datamatrix import (
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


def process_imported_document(
    *,
    database: Database,
    file_path: Path,
    import_result: FileImportResult,
) -> ProcessingResult:
    """
    Выполняет полный цикл
    для одного XML:

    1. читает неизменяемое
       содержимое из RAW;

    2. определяет тип документа;

    3. разбирает товарные строки
       и коды;

    4. сопоставляет документ
       с CORE;

    5. обновляет текущее
       хранилище DataMatrix.
    """

    raw_document_id = (
        import_result.raw_document_id
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
            parse_status=(
                "INVALID_XML"
            ),
            match_status=(
                "NOT_PROCESSED"
            ),
            core_document_id=None,
            line_count=0,
            code_count=0,
            document_kind=(
                "UNKNOWN"
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

    if (
        decision.status == "MATCHED"
        and final_core_document_id
        is not None
    ):
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
        )

        if (
            document_kind
            == DOCUMENT_KIND_UKD
        ):
            reconcile_ukd_datamatrix_units(
                database=database,
                raw_document_id=(
                    raw_document_id
                ),
                core_document_id=(
                    final_core_document_id
                ),
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
        f"import={import_status}; "
        f"kind="
        f"{result.document_kind}; "
        f"parse="
        f"{result.parse_status}; "
        f"match="
        f"{result.match_status}; "
        f"core_document_id="
        f"{core_value}; "
        f"lines="
        f"{result.line_count}; "
        f"codes="
        f"{result.code_count}"
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
    Импортирует, разбирает
    и сопоставляет XML ЭДО
    одной командой.
    """

    prepared_source_system = (
        source_system.strip()
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
        f"Найдено XML-файлов: "
        f"{len(files)}"
    )

    if not files:
        typer.echo(
            "Обработка не требуется: "
            "XML-файлы не найдены."
        )

        return

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