from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

import typer

from app.client import (
    GisMtAuthError,
    GisMtClient,
)
from app.cli import read_token_from_stdin
from app.config import get_settings
from app.db import Database
from app.normalizers import normalize_document_info
from app.pagination import parse_document_page
from app.repository import Repository
from app.windowing import (
    DateWindow,
    format_request_params,
    format_utc_datetime,
    parse_utc_datetime,
    split_window,
    validate_window_coverage,
)


app = typer.Typer(
    add_completion=False,
    help=(
        "Загрузка подробных сведений по документам "
        "True API ГИС МТ."
    ),
)


@dataclass(frozen=True, slots=True)
class DocumentDetailsSyncSummary:
    """
    Итог получения списка и подробных
    сведений документов True API.
    """

    run_id: int
    run_uuid: str

    list_request_count: int
    leaf_window_count: int
    split_count: int

    unique_document_count: int
    successful_document_count: int
    failed_document_count: int
    duplicate_document_count: int


@app.command()
def main(
    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help="Товарная группа ГИС МТ.",
        ),
    ] = "water",

    date_from: Annotated[
        str,
        typer.Option(
            "--date-from",
            help=(
                "Начало периода "
                "в ISO 8601."
            ),
        ),
    ] = ...,

    date_to: Annotated[
        str,
        typer.Option(
            "--date-to",
            help=(
                "Окончание периода "
                "в ISO 8601."
            ),
        ),
    ] = ...,

    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=1000,
            help=(
                "Максимум документов "
                "в одном запросе списка."
            ),
        ),
    ] = 100,

    max_pages: Annotated[
        int,
        typer.Option(
            "--max-pages",
            min=1,
            max=10000,
            help=(
                "Максимальное количество "
                "запросов временных окон."
            ),
        ),
    ] = 1000,

    delay_ms: Annotated[
        int,
        typer.Option(
            "--delay-ms",
            min=0,
            max=10000,
            help=(
                "Пауза между запросами "
                "подробностей документов "
                "в миллисекундах."
            ),
        ),
    ] = 100,
) -> None:
    token = read_token_from_stdin()

    try:
        asyncio.run(
            sync_document_details(
                token=token,
                product_group=product_group,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                max_pages=max_pages,
                delay_ms=delay_ms,
            )
        )

    except GisMtAuthError as exc:
        typer.echo("")
        typer.echo(
            "AUTH ERROR: токен отклонён "
            "или истёк.",
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


async def sync_document_details(
    *,
    token: str,
    product_group: str,
    date_from: str,
    date_to: str,
    limit: int,
    max_pages: int,
    delay_ms: int,
) -> DocumentDetailsSyncSummary:
    """
    Получает документы True API через
    адаптивное деление периода.

    Переполненные окна не обрабатываются
    непосредственно. Они делятся на две части,
    после чего документы собираются только
    из конечных временных окон.

    После обхода проверяется, что все документы,
    замеченные в переполненных родительских
    окнах, присутствуют хотя бы в одном
    конечном окне.
    """

    settings = get_settings()

    repository = Repository(
        Database(
            settings
        )
    )

    prepared_product_group = (
        product_group
        .strip()
        .lower()
    )

    if not prepared_product_group:
        raise ValueError(
            "Товарная группа "
            "не может быть пустой."
        )

    if limit < 1:
        raise ValueError(
            "limit должен быть "
            "не меньше 1."
        )

    if max_pages < 1:
        raise ValueError(
            "max_pages должен быть "
            "не меньше 1."
        )

    if delay_ms < 0:
        raise ValueError(
            "delay_ms не может "
            "быть отрицательным."
        )

    resolved_date_from = parse_utc_datetime(
        date_from,
        "date_from",
    )

    resolved_date_to = parse_utc_datetime(
        date_to,
        "date_to",
    )

    if resolved_date_from >= resolved_date_to:
        raise ValueError(
            "date_from должен быть "
            "раньше date_to."
        )

    run_id, run_uuid = repository.start_run(
        job_type="SYNC_DOCUMENT_DETAILS",
        date_from=format_utc_datetime(
            resolved_date_from
        ),
        date_to=format_utc_datetime(
            resolved_date_to
        ),
    )

    processed_document_ids: set[str] = set()

    # Документы, обнаруженные в переполненных
    # родительских окнах. После завершения
    # обхода они должны встретиться в листьях.
    split_parent_document_ids: set[str] = set()

    successful_documents = 0
    failed_documents = 0
    duplicate_documents = 0

    list_request_count = 0
    leaf_window_count = 0
    split_count = 0

    minimum_window = timedelta(
        milliseconds=1
    )

    pending_windows: list[DateWindow] = [
        DateWindow(
            date_from=resolved_date_from,
            date_to=resolved_date_to,
            depth=0,
        )
    ]

    try:
        async with GisMtClient(
            settings,
            token,
        ) as client:
            while pending_windows:
                window = pending_windows.pop()

                list_request_count += 1

                if list_request_count > max_pages:
                    raise RuntimeError(
                        "WINDOW_MAX_REQUESTS_EXCEEDED: "
                        "достигнут предел "
                        f"{max_pages} запросов списка."
                    )

                window_date_from = (
                    format_utc_datetime(
                        window.date_from
                    )
                )

                window_date_to = (
                    format_utc_datetime(
                        window.date_to
                    )
                )

                list_result = await client.list_documents(
                    product_group=(
                        prepared_product_group
                    ),
                    date_from=window_date_from,
                    date_to=window_date_to,
                    limit=limit,
                    extra_params={
                        "order": "ASC",
                        "orderColumn": "receivedAt",
                    },
                )

                list_raw_id = (
                    repository.save_api_result(
                        run_id=run_id,
                        result=list_result,
                        source_system=(
                            "GIS_MT_TRUE_API"
                        ),
                        external_entity_id=(
                            "document-list-window-"
                            f"{list_request_count}"
                        ),
                    )
                )

                page = parse_document_page(
                    list_result.payload
                )

                typer.echo("")
                typer.echo(
                    "Запрос списка "
                    f"{list_request_count}: "
                    "окно "
                    f"{window_date_from} - "
                    f"{window_date_to}; "
                    f"глубина={window.depth}; "
                    f"RAW id={list_raw_id}"
                )

                typer.echo(
                    "Параметры: "
                    f"{format_request_params(list_result.params)}"
                )

                typer.echo(
                    "Получено документов: "
                    f"{len(page.document_ids)}; "
                    f"nextPage={page.next_page}"
                )

                window_is_full = (
                    page.next_page
                    or len(page.document_ids) >= limit
                )

                if window_is_full:
                    split_parent_document_ids.update(
                        page.document_ids
                    )

                    duration = (
                        window.date_to
                        - window.date_from
                    )

                    if duration <= minimum_window:
                        raise RuntimeError(
                            "WINDOW_TOO_DENSE: "
                            "даже минимальное "
                            "временное окно содержит "
                            "больше документов, чем "
                            "допускает один ответ API."
                        )

                    left_window, right_window = (
                        split_window(
                            window
                        )
                    )

                    split_count += 1

                    if page.next_page:
                        split_reason = (
                            "nextPage=true"
                        )
                    else:
                        split_reason = (
                            "получен лимит "
                            f"{limit}"
                        )

                    typer.echo(
                        "Окно требует разделения: "
                        f"{split_reason}. "
                        "Разделение на два "
                        "временных окна."
                    )

                    # Стек LIFO. Правую половину
                    # добавляем первой, чтобы левая
                    # обработалась раньше.
                    pending_windows.append(
                        right_window
                    )

                    pending_windows.append(
                        left_window
                    )

                    continue

                leaf_window_count += 1

                new_document_ids: list[str] = []

                for document_id in page.document_ids:
                    if (
                        document_id
                        in processed_document_ids
                    ):
                        duplicate_documents += 1
                        continue

                    processed_document_ids.add(
                        document_id
                    )

                    new_document_ids.append(
                        document_id
                    )

                typer.echo(
                    "Новых уникальных "
                    "документов в окне: "
                    f"{len(new_document_ids)}; "
                    "повторов всего="
                    f"{duplicate_documents}"
                )

                for document_id in new_document_ids:
                    global_index = (
                        successful_documents
                        + failed_documents
                        + 1
                    )

                    try:
                        document_result = (
                            await client.get_document(
                                doc_id=document_id
                            )
                        )

                        raw_id = (
                            repository.save_api_result(
                                run_id=run_id,
                                result=document_result,
                                source_system=(
                                    "GIS_MT_TRUE_API"
                                ),
                                external_entity_id=(
                                    document_id
                                ),
                            )
                        )

                        normalized = (
                            normalize_document_info(
                                document_result.payload,
                                document_id,
                            )
                        )

                        successful_documents += 1

                        source_item_count = int(
                            normalized.get(
                                "_source_item_count",
                                1,
                            )
                        )

                        conflicts = normalized.get(
                            "_conflicts"
                        )

                        status_suffix = ""

                        if source_item_count > 1:
                            status_suffix += (
                                ", элементов ответа="
                                f"{source_item_count}"
                            )

                        if conflicts:
                            status_suffix += (
                                ", есть расхождения"
                            )

                        typer.echo(
                            "  Документ "
                            f"{global_index}: "
                            "OK, RAW id="
                            f"{raw_id}"
                            f"{status_suffix}"
                        )

                    except GisMtAuthError:
                        raise

                    except Exception as exc:
                        failed_documents += 1

                        typer.echo(
                            "  Документ "
                            f"{global_index}: "
                            "ERROR "
                            f"{type(exc).__name__}: "
                            f"{exc}",
                            err=True,
                        )

                    if delay_ms > 0:
                        await asyncio.sleep(
                            delay_ms / 1000
                        )

        # Проверяется только то покрытие, которое
        # можно доказать по фактическим ответам API:
        # каждый номер из переполненного окна
        # должен быть найден в конечных окнах.
        validate_window_coverage(
            parent_document_ids=(
                split_parent_document_ids
            ),
            leaf_document_ids=(
                processed_document_ids
            ),
        )

        if split_parent_document_ids:
            typer.echo("")
            typer.echo(
                "Контроль покрытия временных окон: "
                "успешно."
            )
            typer.echo(
                "Документов, замеченных "
                "в родительских окнах: "
                f"{len(split_parent_document_ids)}"
            )

        final_status = (
            "SUCCESS"
            if failed_documents == 0
            else "PARTIAL"
        )

        error_code: str | None = None
        error_message: str | None = None

        if failed_documents > 0:
            error_code = (
                "DOCUMENT_DETAIL_ERRORS"
            )

            error_message = (
                "Не удалось получить "
                "или нормализовать "
                f"{failed_documents} документов."
            )

        repository.finish_run(
            run_id=run_id,
            status=final_status,
            records_received=(
                successful_documents
            ),
            error_code=error_code,
            error_message=error_message,
        )

        summary = DocumentDetailsSyncSummary(
            run_id=run_id,
            run_uuid=str(run_uuid),
            list_request_count=(
                list_request_count
            ),
            leaf_window_count=(
                leaf_window_count
            ),
            split_count=split_count,
            unique_document_count=len(
                processed_document_ids
            ),
            successful_document_count=(
                successful_documents
            ),
            failed_document_count=(
                failed_documents
            ),
            duplicate_document_count=(
                duplicate_documents
            ),
        )

        typer.echo("")
        typer.echo(
            f"{final_status} "
            f"run_uuid={run_uuid}"
        )

        typer.echo(
            "Запросов списка выполнено: "
            f"{list_request_count}"
        )

        typer.echo(
            "Конечных временных окон: "
            f"{leaf_window_count}"
        )

        typer.echo(
            "Разделений временных окон: "
            f"{split_count}"
        )

        typer.echo(
            "Уникальных документов "
            "в списке: "
            f"{len(processed_document_ids)}"
        )

        typer.echo(
            "Подробных ответов сохранено: "
            f"{successful_documents}"
        )

        typer.echo(
            "Ошибок документов: "
            f"{failed_documents}"
        )

        typer.echo(
            "Повторов между окнами: "
            f"{duplicate_documents}"
        )

        return summary

    except GisMtAuthError as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            records_received=(
                successful_documents
            ),
            error_code="AUTH_REJECTED",
            error_message=str(exc),
        )

        raise

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            records_received=(
                successful_documents
            ),
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

        typer.echo(
            "До остановки сохранено "
            "подробных ответов: "
            f"{successful_documents}",
            err=True,
        )

        raise


if __name__ == "__main__":
    app()