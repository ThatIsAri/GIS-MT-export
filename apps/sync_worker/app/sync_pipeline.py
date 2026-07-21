from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import typer

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.sync_document_details import (
    sync_document_details,
)
from app.sync_edo_documents import (
    sync_edo_documents,
)


def run_module(
    module: str,
    arguments: list[str],
) -> None:
    command = [
        sys.executable,
        "-u",
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


def print_edo_summary(
    summary: object,
) -> None:
    typer.echo(
        ""
    )

    typer.echo(
        "Итог официальной загрузки "
        "XML ЭДО."
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


def main(
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
            "Количество документов "
            "на странице True API."
        ),
    ),

    max_pages: int = typer.Option(
        1000,
        "--max-pages",
        min=1,
        max=10000,
        help=(
            "Максимальное количество "
            "страниц списка документов."
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
            "Размер пакета при переносе "
            "RAW в core_document."
        ),
    ),

    edo_delay_ms: int = typer.Option(
        150,
        "--edo-delay-ms",
        min=0,
        max=10000,
        help=(
            "Пауза между запросами "
            "XML ЭДО."
        ),
    ),

    edo_output_root: Path = typer.Option(
        Path(
            "/data/edo_inbox/official"
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
    prepared_product_group = (
        product_group.strip()
    )

    if not prepared_product_group:
        raise typer.BadParameter(
            "Товарная группа "
            "не может быть пустой."
        )

    token = read_token_from_stdin()

    details_run_id: (
        int | None
    ) = None

    try:
        typer.echo(
            "Этап 1/3: получение списка "
            "и подробностей документов "
            "True API."
        )

        details_summary = asyncio.run(
            sync_document_details(
                token=token,
                product_group=(
                    prepared_product_group
                ),
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                max_pages=max_pages,
                delay_ms=(
                    details_delay_ms
                ),
            )
        )

        details_run_id = (
            details_summary.run_id
        )

        typer.echo(
            ""
        )

        typer.echo(
            "Получен запуск "
            "SYNC_DOCUMENT_DETAILS "
            f"id={details_run_id}."
        )

        if (
            details_summary
            .unique_document_count
            == 0
        ):
            typer.echo(
                ""
            )

            typer.echo(
                "Документы за выбранный "
                "период отсутствуют."
            )

            typer.echo(
                "Этап 2/3 пропущен: "
                "нормализовать нечего."
            )

            typer.echo(
                "Этап 3/3 пропущен: "
                "XML ЭДО отсутствуют."
            )

        else:
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

            typer.echo(
                ""
            )

            typer.echo(
                "Этап 2/3: перенос "
                "подробных ответов "
                "в core_document."
            )

            run_module(
                "app.load_core_documents",
                [
                    "--run-id",
                    str(
                        details_run_id
                    ),
                    "--batch-size",
                    str(
                        batch_size
                    ),
                ],
            )

            if skip_edo:
                typer.echo(
                    ""
                )

                typer.echo(
                    "Этап 3/3 пропущен "
                    "по параметру --skip-edo."
                )

            else:
                typer.echo(
                    ""
                )

                typer.echo(
                    "Этап 3/3: официальная "
                    "загрузка и обработка "
                    "XML ЭДО."
                )

                edo_summary = asyncio.run(
                    sync_edo_documents(
                        token=token,
                        run_id=(
                            details_run_id
                        ),
                        output_root=(
                            edo_output_root
                        ),
                        delay_ms=(
                            edo_delay_ms
                        ),
                        force=(
                            force_edo
                        ),
                        fail_fast=(
                            edo_fail_fast
                        ),
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
                        "Пакетная загрузка "
                        "XML ЭДО завершилась "
                        "с ошибками: "
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

    except GisMtAuthError as exc:
        typer.echo(
            ""
        )

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
            ""
        )

        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc

    typer.echo(
        ""
    )

    typer.echo(
        "Полный конвейер "
        "завершён успешно."
    )

    typer.echo(
        "Товарная группа: "
        f"{prepared_product_group}"
    )

    typer.echo(
        "Запуск "
        "SYNC_DOCUMENT_DETAILS: "
        f"{details_run_id}"
    )


if __name__ == "__main__":
    typer.run(
        main
    )