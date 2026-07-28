from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import typer

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.entity_document_links import (
    EntityDocumentLinkSummary,
    link_core_documents_for_run,
)
from app.load_core_documents import (
    CoreLoadSummary,
    load_core_documents,
)
from app.sync_document_details import (
    DocumentDetailsSyncSummary,
    sync_document_details,
)
from app.sync_edo_documents import (
    EdoSyncSummary,
    sync_edo_documents,
)


@dataclass(
    frozen=True,
    slots=True,
)
class PipelineSummary:
    """
    Итог полного последовательного конвейера
    одной организации и товарной группы.
    """

    legal_entity_id: int
    product_group: str
    details_run_id: int

    unique_document_count: int
    successful_document_count: int
    failed_document_count: int

    core_selected_count: int
    core_processed_count: int
    core_conflict_count: int
    core_failed_count: int

    linked_source_document_count: int
    linked_document_count: int

    edo_selected_count: int
    edo_already_processed_count: int
    edo_downloaded_count: int
    edo_matched_count: int
    edo_error_count: int

    edo_skipped: bool


def prepare_product_group(
    value: str,
) -> str:
    """
    Нормализует наименование товарной группы.
    """

    prepared = value.strip().lower()

    if not prepared:
        raise ValueError(
            "Товарная группа не может быть пустой."
        )

    return prepared


def validate_legal_entity_id(
    value: int,
) -> int:
    """
    Проверяет ID карточки организации.
    """

    if value < 1:
        raise ValueError(
            "legal_entity_id должен быть больше 0."
        )

    return value


def print_edo_summary(
    summary: EdoSyncSummary,
) -> None:
    """
    Выводит итог официальной загрузки XML ЭДО.
    """

    typer.echo("")
    typer.echo(
        "Итог официальной загрузки XML ЭДО."
    )
    typer.echo(
        f"Запуск CORE: {summary.run_id}"
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
        f"Скачано: {summary.downloaded_count}"
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
        f"Без UUID: {summary.missing_uuid_count}"
    )
    typer.echo(
        f"Ошибок: {summary.error_count}"
    )


def print_link_summary(
    summary: EntityDocumentLinkSummary,
) -> None:
    """
    Выводит итог привязки документов CORE
    к организации и товарной группе.
    """

    typer.echo("")
    typer.echo(
        "Итог привязки документов к организации."
    )
    typer.echo(
        "Организация: "
        f"{summary.legal_entity_id}"
    )
    typer.echo(
        "Товарная группа: "
        f"{summary.product_group}"
    )
    typer.echo(
        "Документов CORE: "
        f"{summary.source_document_count}"
    )
    typer.echo(
        "Связей сохранено: "
        f"{summary.linked_document_count}"
    )


def validate_core_summary(
    *,
    details_summary: DocumentDetailsSyncSummary,
    core_summary: CoreLoadSummary,
) -> None:
    """
    Проверяет согласованность этапов RAW и CORE.

    Число подробных ответов, успешно сохранённых
    на первом этапе, должно совпадать с числом
    RAW-ответов, выбранных загрузчиком CORE.
    """

    if (
        core_summary.run_id
        != details_summary.run_id
    ):
        raise RuntimeError(
            "CORE_RUN_MISMATCH: "
            "загрузчик CORE обработал другой запуск. "
            f"Ожидался id={details_summary.run_id}, "
            f"получен id={core_summary.run_id}."
        )

    if (
        core_summary.selected_count
        != details_summary.successful_document_count
    ):
        raise RuntimeError(
            "CORE_SOURCE_COUNT_MISMATCH: "
            "количество подробных RAW-ответов "
            "не совпало с количеством ответов, "
            "переданных в CORE. "
            "Сохранено на этапе True API: "
            f"{details_summary.successful_document_count}; "
            "выбрано загрузчиком CORE: "
            f"{core_summary.selected_count}."
        )

    if core_summary.failed_count > 0:
        raise RuntimeError(
            "Нормализация CORE завершилась "
            "с ошибками: "
            f"{core_summary.failed_count}."
        )

    if (
        core_summary.processed_count
        != core_summary.selected_count
    ):
        raise RuntimeError(
            "CORE_PROCESSING_COUNT_MISMATCH: "
            "не все выбранные RAW-ответы "
            "были загружены в CORE. "
            f"Выбрано: {core_summary.selected_count}; "
            f"обработано: {core_summary.processed_count}."
        )


def execute_pipeline(
    *,
    token: str,
    legal_entity_id: int,
    product_group: str,
    date_from: str,
    date_to: str,
    limit: int,
    max_pages: int,
    details_delay_ms: int,
    batch_size: int,
    edo_delay_ms: int,
    edo_output_root: Path,
    skip_edo: bool,
    force_edo: bool,
    edo_fail_fast: bool,
    database: Database | None = None,
) -> PipelineSummary:
    """
    Выполняет полный последовательный конвейер:

    True API
    -> RAW
    -> CORE
    -> legal_entity_document
    -> XML ЭДО.

    Функция отделена от CLI, поэтому позднее
    сможет вызываться worker-ом RabbitMQ
    без запуска дочернего процесса.
    """

    prepared_entity_id = (
        validate_legal_entity_id(
            legal_entity_id
        )
    )

    prepared_product_group = (
        prepare_product_group(
            product_group
        )
    )

    active_database = (
        database
        if database is not None
        else Database(
            get_settings()
        )
    )

    typer.echo(
        "Область конвейера: "
        f"entity_id={prepared_entity_id}; "
        f"product_group={prepared_product_group}."
    )

    typer.echo("")
    typer.echo(
        "Этап 1/4: получение списка "
        "и подробностей документов True API."
    )

    details_summary = asyncio.run(
        sync_document_details(
            token=token,
            legal_entity_id=(
                prepared_entity_id
            ),
            product_group=(
                prepared_product_group
            ),
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            max_pages=max_pages,
            delay_ms=details_delay_ms,
        )
    )

    details_run_id = (
        details_summary.run_id
    )

    typer.echo("")
    typer.echo(
        "Получен запуск "
        "SYNC_DOCUMENT_DETAILS "
        f"id={details_run_id}."
    )

    if (
        details_summary.unique_document_count
        == 0
    ):
        typer.echo("")
        typer.echo(
            "Документы за выбранный период отсутствуют."
        )
        typer.echo(
            "Этап 2/4 пропущен: "
            "нормализовать нечего."
        )
        typer.echo(
            "Этап 3/4 пропущен: "
            "документы CORE отсутствуют."
        )
        typer.echo(
            "Этап 4/4 пропущен: "
            "XML ЭДО отсутствуют."
        )

        return PipelineSummary(
            legal_entity_id=(
                prepared_entity_id
            ),
            product_group=(
                prepared_product_group
            ),
            details_run_id=(
                details_run_id
            ),
            unique_document_count=0,
            successful_document_count=0,
            failed_document_count=(
                details_summary
                .failed_document_count
            ),
            core_selected_count=0,
            core_processed_count=0,
            core_conflict_count=0,
            core_failed_count=0,
            linked_source_document_count=0,
            linked_document_count=0,
            edo_selected_count=0,
            edo_already_processed_count=0,
            edo_downloaded_count=0,
            edo_matched_count=0,
            edo_error_count=0,
            edo_skipped=True,
        )

    if (
        details_summary
        .successful_document_count
        == 0
    ):
        raise RuntimeError(
            "Список документов получен, "
            "но ни один подробный ответ "
            "не был сохранён."
        )

    typer.echo("")
    typer.echo(
        "Этап 2/4: перенос подробных "
        "ответов в core_document."
    )

    core_summary = load_core_documents(
        database=active_database,
        run_id=details_run_id,
        batch_size=batch_size,
        echo_progress=True,
    )

    validate_core_summary(
        details_summary=details_summary,
        core_summary=core_summary,
    )

    typer.echo("")
    typer.echo(
        "Этап 3/4: привязка документов CORE "
        "к организации и товарной группе."
    )

    link_summary = (
        link_core_documents_for_run(
            database=active_database,
            run_id=details_run_id,
        )
    )

    print_link_summary(
        link_summary
    )

    edo_summary: EdoSyncSummary | None = None

    if skip_edo:
        typer.echo("")
        typer.echo(
            "Этап 4/4 пропущен "
            "по параметру --skip-edo."
        )

    else:
        typer.echo("")
        typer.echo(
            "Этап 4/4: официальная загрузка "
            "и обработка XML ЭДО."
        )

        edo_summary = asyncio.run(
            sync_edo_documents(
                token=token,
                run_id=details_run_id,
                output_root=(
                    edo_output_root
                ),
                delay_ms=edo_delay_ms,
                force=force_edo,
                fail_fast=edo_fail_fast,
            )
        )

        print_edo_summary(
            edo_summary
        )

        if (
            edo_summary.error_count
            > 0
        ):
            raise RuntimeError(
                "Пакетная загрузка XML ЭДО "
                "завершилась с ошибками: "
                f"{edo_summary.error_count}."
            )

    if (
        details_summary
        .failed_document_count
        > 0
    ):
        raise RuntimeError(
            "Подробные сведения получены "
            "не полностью. "
            "Ошибок документов: "
            f"{details_summary.failed_document_count}."
        )

    return PipelineSummary(
        legal_entity_id=(
            prepared_entity_id
        ),
        product_group=(
            prepared_product_group
        ),
        details_run_id=details_run_id,
        unique_document_count=(
            details_summary
            .unique_document_count
        ),
        successful_document_count=(
            details_summary
            .successful_document_count
        ),
        failed_document_count=(
            details_summary
            .failed_document_count
        ),
        core_selected_count=(
            core_summary.selected_count
        ),
        core_processed_count=(
            core_summary.processed_count
        ),
        core_conflict_count=(
            core_summary.conflict_count
        ),
        core_failed_count=(
            core_summary.failed_count
        ),
        linked_source_document_count=(
            link_summary
            .source_document_count
        ),
        linked_document_count=(
            link_summary
            .linked_document_count
        ),
        edo_selected_count=(
            edo_summary.selected_count
            if edo_summary is not None
            else 0
        ),
        edo_already_processed_count=(
            edo_summary
            .already_processed_count
            if edo_summary is not None
            else 0
        ),
        edo_downloaded_count=(
            edo_summary.downloaded_count
            if edo_summary is not None
            else 0
        ),
        edo_matched_count=(
            edo_summary.matched_count
            if edo_summary is not None
            else 0
        ),
        edo_error_count=(
            edo_summary.error_count
            if edo_summary is not None
            else 0
        ),
        edo_skipped=skip_edo,
    )


def main(
    legal_entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help=(
            "ID существующей карточки "
            "организации."
        ),
    ),
    product_group: str = typer.Option(
        "water",
        "--pg",
        help=(
            "Товарная группа ГИС МТ, "
            "например water или beer."
        ),
    ),
    date_from: str = typer.Option(
        ...,
        "--date-from",
        help=(
            "Начало периода "
            "в формате ISO 8601."
        ),
    ),
    date_to: str = typer.Option(
        ...,
        "--date-to",
        help=(
            "Окончание периода "
            "в формате ISO 8601."
        ),
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        min=1,
        max=1000,
        help=(
            "Максимальное количество документов "
            "в одном запросе списка True API."
        ),
    ),
    max_pages: int = typer.Option(
        1000,
        "--max-pages",
        min=1,
        max=10000,
        help=(
            "Максимальное количество запросов "
            "временных окон списка документов."
        ),
    ),
    details_delay_ms: int = typer.Option(
        100,
        "--details-delay-ms",
        min=0,
        max=10000,
        help=(
            "Пауза между запросами "
            "подробностей документов."
        ),
    ),
    batch_size: int = typer.Option(
        50,
        "--batch-size",
        min=1,
        max=1000,
        help=(
            "Размер транзакционного пакета "
            "при переносе RAW в CORE."
        ),
    ),
    edo_delay_ms: int = typer.Option(
        150,
        "--edo-delay-ms",
        min=0,
        max=10000,
        help=(
            "Пауза между запросами XML ЭДО."
        ),
    ),
    edo_output_root: Path = typer.Option(
        Path(
            "/data/official"
        ),
        "--edo-output-root",
        file_okay=False,
        dir_okay=True,
        help=(
            "Каталог официально "
            "полученных XML ЭДО."
        ),
    ),
    skip_edo: bool = typer.Option(
        False,
        "--skip-edo",
        help=(
            "Не скачивать XML ЭДО."
        ),
    ),
    force_edo: bool = typer.Option(
        False,
        "--force-edo",
        help=(
            "Повторно скачивать "
            "уже обработанные XML."
        ),
    ),
    edo_fail_fast: bool = typer.Option(
        False,
        "--edo-fail-fast",
        help=(
            "Остановить загрузку XML "
            "после первой ошибки."
        ),
    ),
) -> None:
    token = read_token_from_stdin()

    try:
        summary = execute_pipeline(
            token=token,
            legal_entity_id=(
                legal_entity_id
            ),
            product_group=(
                product_group
            ),
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            max_pages=max_pages,
            details_delay_ms=(
                details_delay_ms
            ),
            batch_size=batch_size,
            edo_delay_ms=(
                edo_delay_ms
            ),
            edo_output_root=(
                edo_output_root
            ),
            skip_edo=skip_edo,
            force_edo=force_edo,
            edo_fail_fast=(
                edo_fail_fast
            ),
        )

    except GisMtAuthError as exc:
        typer.echo("")
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
        typer.echo("")
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
        "Полный конвейер завершён успешно."
    )
    typer.echo(
        "Организация: "
        f"{summary.legal_entity_id}"
    )
    typer.echo(
        "Товарная группа: "
        f"{summary.product_group}"
    )
    typer.echo(
        "Запуск SYNC_DOCUMENT_DETAILS: "
        f"{summary.details_run_id}"
    )
    typer.echo(
        "Документов связано с организацией: "
        f"{summary.linked_document_count}"
    )


if __name__ == "__main__":
    typer.run(
        main
    )