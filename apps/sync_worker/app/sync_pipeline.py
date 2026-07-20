from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Annotated

import typer

from app.cli import read_token_from_stdin
from app.sync_document_details import (
    sync_document_details,
)


app = typer.Typer(
    add_completion=False,
    help=(
        "Полный цикл обновления документов "
        "True API, загрузки CORE и "
        "повторного сопоставления XML ЭДО."
    ),
)


def run_module(
    module: str,
    arguments: list[str],
) -> None:
    """
    Запускает внутренний модуль проекта
    в текущем Python-контейнере.
    """

    command = [
        sys.executable,
        "-m",
        module,
        *arguments,
    ]

    completed = subprocess.run(
        command,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Модуль {module} "
            "завершился с кодом "
            f"{completed.returncode}."
        )


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
            help="Начало периода в ISO 8601.",
        ),
    ] = ...,

    date_to: Annotated[
        str,
        typer.Option(
            "--date-to",
            help="Окончание периода в ISO 8601.",
        ),
    ] = ...,

    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            min=1,
            max=1000,
            help=(
                "Количество документов "
                "на странице."
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
                "Максимальное количество страниц."
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
                "документов в миллисекундах."
            ),
        ),
    ] = 100,

    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            min=1,
            max=1000,
            help=(
                "Размер транзакции при загрузке "
                "в core_document."
            ),
        ),
    ] = 50,

    skip_matching: Annotated[
        bool,
        typer.Option(
            "--skip-matching",
            help=(
                "Не выполнять повторное "
                "сопоставление XML ЭДО."
            ),
        ),
    ] = False,
) -> None:
    """
    Выполняет три этапа:

    1. Загружает подробности документов True API.
    2. Переносит их в core_document.
    3. Повторно сопоставляет XML ЭДО.
    """

    token = read_token_from_stdin()

    typer.echo(
        "Этап 1/3: получение подробностей "
        "документов True API."
    )

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

    typer.echo("")
    typer.echo(
        "Этап 2/3: перенос последнего запуска "
        "в core_document."
    )

    try:
        run_module(
            "app.load_core_documents",
            [
                "--batch-size",
                str(
                    batch_size
                ),
            ],
        )

        if not skip_matching:
            typer.echo("")
            typer.echo(
                "Этап 3/3: повторное "
                "сопоставление XML ЭДО."
            )

            run_module(
                "app.match_edo_document",
                [
                    "--all-unmatched",
                ],
            )

        else:
            typer.echo("")
            typer.echo(
                "Этап 3/3 пропущен "
                "по параметру --skip-matching."
            )

    except RuntimeError as exc:
        typer.echo(
            f"ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc

    typer.echo("")
    typer.echo(
        "Полный цикл синхронизации завершён."
    )


if __name__ == "__main__":
    app()