from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlencode

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


app = typer.Typer(
    add_completion=False,
    help=(
        "Загрузка подробных сведений по документам "
        "True API ГИС МТ."
    ),
)


@dataclass(frozen=True, slots=True)
class DocumentDetailsSyncSummary:
    run_id: int
    run_uuid: str
    page_count: int
    unique_document_count: int
    successful_document_count: int
    failed_document_count: int
    duplicate_document_count: int
    reported_total: int | None


@dataclass(frozen=True, slots=True)
class DateWindow:
    date_from: datetime
    date_to: datetime
    depth: int


def parse_utc_datetime(
    value: str,
    parameter_name: str,
) -> datetime:
    prepared = value.strip()

    if not prepared:
        raise ValueError(
            f"{parameter_name} не может быть пустым."
        )

    if prepared.endswith("Z"):
        prepared = prepared[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(prepared)
    except ValueError as exc:
        raise ValueError(
            f"{parameter_name} должен быть в формате ISO 8601."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def format_utc_datetime(
    value: datetime,
) -> str:
    normalized = value.astimezone(
        timezone.utc
    )

    if normalized.microsecond:
        milliseconds = (
            normalized.microsecond // 1000
        )

        return (
            normalized.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            + f".{milliseconds:03d}Z"
        )

    return normalized.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def format_request_params(
    params: dict[str, Any],
) -> str:
    items: list[
        tuple[str, str]
    ] = []

    for key in sorted(
        params
    ):
        value = params[key]

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            for item in value:
                items.append(
                    (
                        str(key),
                        str(item),
                    )
                )
        else:
            items.append(
                (
                    str(key),
                    str(value),
                )
            )

    return urlencode(
        items,
        doseq=True,
    )


def split_window(
    window: DateWindow,
) -> tuple[
    DateWindow,
    DateWindow,
]:
    duration = (
        window.date_to
        - window.date_from
    )

    midpoint = (
        window.date_from
        + duration / 2
    )

    if (
        midpoint
        <= window.date_from
        or midpoint
        >= window.date_to
    ):
        raise RuntimeError(
            "WINDOW_SPLIT_FAILED: "
            "не удалось разделить "
            "временное окно."
        )

    return (
        DateWindow(
            date_from=(
                window.date_from
            ),
            date_to=midpoint,
            depth=(
                window.depth + 1
            ),
        ),
        DateWindow(
            date_from=midpoint,
            date_to=(
                window.date_to
            ),
            depth=(
                window.depth + 1
            ),
        ),
    )


@app.command()
def main(
    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help=(
                "Товарная группа ГИС МТ."
            ),
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
                "запросов списка. Параметр "
                "сохранён для совместимости."
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
                product_group=(
                    product_group
                ),
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                max_pages=max_pages,
                delay_ms=delay_ms,
            )
        )

    except GisMtAuthError as exc:
        typer.echo(
            ""
        )

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
        typer.echo(
            ""
        )

        typer.echo(
            f"ERROR: "
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

    resolved_date_from = (
        parse_utc_datetime(
            date_from,
            "date_from",
        )
    )

    resolved_date_to = (
        parse_utc_datetime(
            date_to,
            "date_to",
        )
    )

    if (
        resolved_date_from
        >= resolved_date_to
    ):
        raise ValueError(
            "date_from должен быть "
            "раньше date_to."
        )

    (
        run_id,
        run_uuid,
    ) = repository.start_run(
        job_type=(
            "SYNC_DOCUMENT_DETAILS"
        ),
        date_from=(
            format_utc_datetime(
                resolved_date_from
            )
        ),
        date_to=(
            format_utc_datetime(
                resolved_date_to
            )
        ),
    )

    processed_document_ids: set[
        str
    ] = set()

    successful_documents = 0
    failed_documents = 0
    duplicate_documents = 0

    list_request_count = 0
    leaf_window_count = 0
    split_count = 0

    minimum_window = timedelta(
        milliseconds=1
    )

    pending_windows: list[
        DateWindow
    ] = [
        DateWindow(
            date_from=(
                resolved_date_from
            ),
            date_to=(
                resolved_date_to
            ),
            depth=0,
        )
    ]

    try:
        async with GisMtClient(
            settings,
            token,
        ) as client:
            while pending_windows:
                window = (
                    pending_windows.pop()
                )

                list_request_count += 1

                if (
                    list_request_count
                    > max_pages
                ):
                    raise RuntimeError(
                        "WINDOW_MAX_REQUESTS_EXCEEDED: "
                        f"достигнут предел "
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

                list_result = (
                    await client
                    .list_documents(
                        product_group=(
                            prepared_product_group
                        ),
                        date_from=(
                            window_date_from
                        ),
                        date_to=(
                            window_date_to
                        ),
                        limit=limit,
                        extra_params={
                            "order": "ASC",
                            "orderColumn": (
                                "receivedAt"
                            ),
                        },
                    )
                )

                list_raw_id = (
                    repository
                    .save_api_result(
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

                page = (
                    parse_document_page(
                        list_result.payload
                    )
                )

                typer.echo(
                    ""
                )

                typer.echo(
                    f"Запрос списка "
                    f"{list_request_count}: "
                    f"окно "
                    f"{window_date_from} - "
                    f"{window_date_to}; "
                    f"глубина="
                    f"{window.depth}; "
                    f"RAW id="
                    f"{list_raw_id}"
                )

                typer.echo(
                    "Параметры: "
                    f"{format_request_params(list_result.params)}"
                )

                typer.echo(
                    "Получено документов: "
                    f"{len(page.document_ids)}; "
                    f"nextPage="
                    f"{page.next_page}"
                )

                window_is_full = (
                    page.next_page
                    or len(
                        page.document_ids
                    )
                    >= limit
                )

                if window_is_full:
                    duration = (
                        window.date_to
                        - window.date_from
                    )

                    if (
                        duration
                        <= minimum_window
                    ):
                        raise RuntimeError(
                            "WINDOW_TOO_DENSE: "
                            "даже минимальное "
                            "временное окно содержит "
                            "больше документов, чем "
                            "допускает один ответ API."
                        )

                    (
                        left_window,
                        right_window,
                    ) = split_window(
                        window
                    )

                    split_count += 1

                    reason = (
                        "nextPage=true"
                        if page.next_page
                        else (
                            f"получен лимит "
                            f"{limit}"
                        )
                    )

                    typer.echo(
                        "Окно требует разделения: "
                        f"{reason}. "
                        "Разделение на два "
                        "временных окна."
                    )

                    # Стек LIFO: правую половину
                    # добавляем первой, чтобы
                    # левой обработаться раньше.
                    pending_windows.append(
                        right_window
                    )

                    pending_windows.append(
                        left_window
                    )

                    continue

                leaf_window_count += 1

                new_document_ids: list[
                    str
                ] = []

                for document_id in (
                    page.document_ids
                ):
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

                for document_id in (
                    new_document_ids
                ):
                    global_index = (
                        successful_documents
                        + failed_documents
                        + 1
                    )

                    try:
                        document_result = (
                            await client
                            .get_document(
                                doc_id=(
                                    document_id
                                )
                            )
                        )

                        raw_id = (
                            repository
                            .save_api_result(
                                run_id=(
                                    run_id
                                ),
                                result=(
                                    document_result
                                ),
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
                                document_result
                                .payload,
                                document_id,
                            )
                        )

                        successful_documents += 1

                        source_item_count = (
                            normalized.get(
                                "_source_item_count",
                                1,
                            )
                        )

                        conflicts = (
                            normalized.get(
                                "_conflicts"
                            )
                        )

                        status_suffix = ""

                        if (
                            source_item_count
                            > 1
                        ):
                            status_suffix += (
                                ", элементов ответа="
                                f"{source_item_count}"
                            )

                        if conflicts:
                            status_suffix += (
                                ", есть расхождения"
                            )

                        typer.echo(
                            f"  Документ "
                            f"{global_index}: "
                            f"OK, RAW id="
                            f"{raw_id}"
                            f"{status_suffix}"
                        )

                    except GisMtAuthError:
                        raise

                    except Exception as exc:
                        failed_documents += 1

                        typer.echo(
                            f"  Документ "
                            f"{global_index}: "
                            f"ERROR "
                            f"{type(exc).__name__}: "
                            f"{exc}",
                            err=True,
                        )

                    if delay_ms > 0:
                        await asyncio.sleep(
                            delay_ms / 1000
                        )

        final_status = (
            "SUCCESS"
            if failed_documents == 0
            else "PARTIAL"
        )

        error_code = None
        error_message = None

        if failed_documents > 0:
            error_code = (
                "DOCUMENT_DETAIL_ERRORS"
            )

            error_message = (
                "Не удалось получить "
                "или нормализовать "
                f"{failed_documents} "
                "документов."
            )

        repository.finish_run(
            run_id=run_id,
            status=final_status,
            records_received=(
                successful_documents
            ),
            error_code=error_code,
            error_message=(
                error_message
            ),
        )

        summary = (
            DocumentDetailsSyncSummary(
                run_id=run_id,
                run_uuid=str(
                    run_uuid
                ),
                page_count=(
                    list_request_count
                ),
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
                reported_total=None,
            )
        )

        typer.echo(
            ""
        )

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
            error_code=(
                "AUTH_REJECTED"
            ),
            error_message=str(
                exc
            ),
        )

        raise

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            records_received=(
                successful_documents
            ),
            error_code=(
                type(exc).__name__
            ),
            error_message=str(
                exc
            ),
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