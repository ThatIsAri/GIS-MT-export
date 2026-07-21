from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlencode

import typer

from app.cli import read_token_from_stdin
from app.client import (
    GisMtAuthError,
    GisMtClient,
)
from app.config import get_settings


app = typer.Typer(
    add_completion=False,
    help=(
        "Диагностика курсорной пагинации "
        "списка документов True API."
    ),
)


@dataclass(frozen=True, slots=True)
class PaginationSummary:
    page_count: int
    unique_document_count: int
    duplicate_document_count: int
    completed: bool
    stop_reason: str


def format_params(
    params: dict[str, Any],
) -> str:
    items: list[tuple[str, str]] = []

    for key in sorted(params):
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


def read_page(
    payload: Any,
) -> tuple[
    list[dict[str, Any]],
    bool,
]:
    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            "Ответ списка не является "
            "JSON-объектом."
        )

    raw_results = payload.get(
        "results"
    )

    if not isinstance(
        raw_results,
        list,
    ):
        raise RuntimeError(
            "В ответе отсутствует "
            "массив results."
        )

    next_page = payload.get(
        "nextPage"
    )

    if not isinstance(
        next_page,
        bool,
    ):
        raise RuntimeError(
            "Поле nextPage отсутствует "
            "или не является boolean."
        )

    documents = [
        item
        for item in raw_results
        if isinstance(
            item,
            dict,
        )
    ]

    return (
        documents,
        next_page,
    )


def read_document_number(
    document: dict[str, Any],
) -> str:
    value = document.get(
        "number"
    )

    if not isinstance(
        value,
        str,
    ):
        raise RuntimeError(
            "У документа отсутствует "
            "строковое поле number."
        )

    prepared = value.strip()

    if not prepared:
        raise RuntimeError(
            "Поле number документа пусто."
        )

    return prepared


def read_received_at(
    document: dict[str, Any],
) -> str:
    value = document.get(
        "receivedAt"
    )

    if not isinstance(
        value,
        str,
    ):
        raise RuntimeError(
            "У документа отсутствует "
            "строковое поле receivedAt."
        )

    prepared = value.strip()

    if not prepared:
        raise RuntimeError(
            "Поле receivedAt документа пусто."
        )

    return prepared


async def diagnose_pagination(
    *,
    token: str,
    product_group: str,
    date_from: str,
    date_to: str,
    limit: int,
    max_pages: int,
    order: str,
) -> PaginationSummary:
    settings = get_settings()

    seen_document_numbers: set[str] = set()

    seen_cursors: set[
        tuple[
            str,
            str,
        ]
    ] = set()

    cursor_number: str | None = None
    cursor_received_at: str | None = None

    duplicate_count = 0
    page_number = 1

    async with GisMtClient(
        settings,
        token,
    ) as client:
        while True:
            if page_number > max_pages:
                return PaginationSummary(
                    page_count=(
                        page_number - 1
                    ),
                    unique_document_count=len(
                        seen_document_numbers
                    ),
                    duplicate_document_count=(
                        duplicate_count
                    ),
                    completed=False,
                    stop_reason=(
                        "MAX_PAGES_EXCEEDED"
                    ),
                )

            extra_params: dict[str, str] = {
                "order": order,
                "orderColumn": "receivedAt",
            }

            if (
                cursor_number is not None
                and cursor_received_at is not None
            ):
                extra_params.update(
                    {
                        "did": cursor_number,
                        "orderedColumnValue": (
                            cursor_received_at
                        ),
                        "pageDir": "NEXT",
                    }
                )

            result = await client.list_documents(
                product_group=(
                    product_group
                ),
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                extra_params=extra_params,
            )

            typer.echo("")
            typer.echo(
                f"Запрос страницы "
                f"{page_number}:"
            )
            typer.echo(
                format_params(
                    result.params
                )
            )

            (
                documents,
                next_page,
            ) = read_page(
                result.payload
            )

            if (
                page_number > 1
                and not documents
            ):
                typer.echo(
                    "EMPTY_PAGE_AFTER_NEXT",
                    err=True,
                )

                return PaginationSummary(
                    page_count=page_number,
                    unique_document_count=len(
                        seen_document_numbers
                    ),
                    duplicate_document_count=(
                        duplicate_count
                    ),
                    completed=False,
                    stop_reason=(
                        "EMPTY_PAGE_AFTER_NEXT"
                    ),
                )

            new_count = 0

            for document in documents:
                document_number = (
                    read_document_number(
                        document
                    )
                )

                if (
                    document_number
                    in seen_document_numbers
                ):
                    duplicate_count += 1
                else:
                    seen_document_numbers.add(
                        document_number
                    )
                    new_count += 1

            typer.echo(
                f"Страница "
                f"{page_number}: "
                f"документов="
                f"{len(documents)}; "
                f"новых={new_count}; "
                f"nextPage={next_page}"
            )

            if documents:
                first_document = documents[0]
                last_document = documents[-1]

                first_number = (
                    read_document_number(
                        first_document
                    )
                )
                first_received_at = (
                    read_received_at(
                        first_document
                    )
                )

                last_number = (
                    read_document_number(
                        last_document
                    )
                )
                last_received_at = (
                    read_received_at(
                        last_document
                    )
                )

                typer.echo(
                    "Первая запись: "
                    f"receivedAt="
                    f"{first_received_at}; "
                    f"number={first_number}"
                )

                typer.echo(
                    "Последняя запись: "
                    f"receivedAt="
                    f"{last_received_at}; "
                    f"number={last_number}"
                )

            typer.echo(
                "Уникальных документов "
                "накоплено: "
                f"{len(seen_document_numbers)}"
            )

            if not next_page:
                return PaginationSummary(
                    page_count=page_number,
                    unique_document_count=len(
                        seen_document_numbers
                    ),
                    duplicate_document_count=(
                        duplicate_count
                    ),
                    completed=True,
                    stop_reason=(
                        "NEXT_PAGE_FALSE"
                    ),
                )

            if not documents:
                return PaginationSummary(
                    page_count=page_number,
                    unique_document_count=len(
                        seen_document_numbers
                    ),
                    duplicate_document_count=(
                        duplicate_count
                    ),
                    completed=False,
                    stop_reason=(
                        "NEXT_PAGE_WITHOUT_RESULTS"
                    ),
                )

            last_document = documents[-1]

            next_cursor = (
                read_document_number(
                    last_document
                ),
                read_received_at(
                    last_document
                ),
            )

            if next_cursor in seen_cursors:
                return PaginationSummary(
                    page_count=page_number,
                    unique_document_count=len(
                        seen_document_numbers
                    ),
                    duplicate_document_count=(
                        duplicate_count
                    ),
                    completed=False,
                    stop_reason=(
                        "CURSOR_STALLED"
                    ),
                )

            seen_cursors.add(
                next_cursor
            )

            (
                cursor_number,
                cursor_received_at,
            ) = next_cursor

            page_number += 1


@app.command()
def main(
    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help="Товарная группа.",
        ),
    ],

    date_from: Annotated[
        str,
        typer.Option(
            "--date-from",
            help="Начало периода.",
        ),
    ],

    date_to: Annotated[
        str,
        typer.Option(
            "--date-to",
            help="Окончание периода.",
        ),
    ],

    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=1000,
        ),
    ] = 20,

    max_pages: Annotated[
        int,
        typer.Option(
            "--max-pages",
            min=1,
            max=10000,
        ),
    ] = 1000,

    order: Annotated[
        str,
        typer.Option(
            "--order",
            help=(
                "Направление сортировки: "
                "ASC или DESC."
            ),
        ),
    ] = "DESC",
) -> None:
    prepared_order = (
        order.strip().upper()
    )

    if prepared_order not in {
        "ASC",
        "DESC",
    }:
        raise typer.BadParameter(
            "--order должен быть "
            "ASC или DESC."
        )

    token = read_token_from_stdin()

    try:
        summary = asyncio.run(
            diagnose_pagination(
                token=token,
                product_group=(
                    product_group
                ),
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                max_pages=max_pages,
                order=prepared_order,
            )
        )

    except GisMtAuthError as exc:
        typer.echo(
            "AUTH ERROR: "
            f"{exc}",
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
        "Итог диагностики."
    )
    typer.echo(
        f"Порядок: "
        f"{prepared_order}"
    )
    typer.echo(
        f"Страниц: "
        f"{summary.page_count}"
    )
    typer.echo(
        "Уникальных документов: "
        f"{summary.unique_document_count}"
    )
    typer.echo(
        "Повторов: "
        f"{summary.duplicate_document_count}"
    )
    typer.echo(
        "Завершено полностью: "
        f"{summary.completed}"
    )
    typer.echo(
        "Причина остановки: "
        f"{summary.stop_reason}"
    )

    if not summary.completed:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    app()