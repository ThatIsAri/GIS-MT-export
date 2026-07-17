import asyncio
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


app = typer.Typer(
    add_completion=False,
    help=(
        "Загрузка подробных сведений по документам "
        "True API ГИС МТ."
    ),
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
            help="Количество документов на странице.",
        ),
    ] = 100,

    max_pages: Annotated[
        int,
        typer.Option(
            "--max-pages",
            min=1,
            max=10000,
            help="Максимальное количество страниц.",
        ),
    ] = 1000,

    delay_ms: Annotated[
        int,
        typer.Option(
            "--delay-ms",
            min=0,
            max=10000,
            help=(
                "Пауза между запросами документов "
                "в миллисекундах."
            ),
        ),
    ] = 100,
) -> None:
    """
    Получает список документов и загружает сведения
    по каждому уникальному document number.

    Каждый ответ сохраняется в RAW-слое MySQL.
    """

    token = read_token_from_stdin()

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


async def sync_document_details(
    *,
    token: str,
    product_group: str,
    date_from: str,
    date_to: str,
    limit: int,
    max_pages: int,
    delay_ms: int,
) -> None:
    settings = get_settings()

    repository = Repository(
        Database(settings)
    )

    run_id, run_uuid = repository.start_run(
        job_type="SYNC_DOCUMENT_DETAILS",
        date_from=date_from,
        date_to=date_to,
    )

    processed_document_ids: set[str] = set()
    seen_cursors: set[tuple[str, str]] = set()

    cursor_document_id: str | None = None
    cursor_received_at: str | None = None

    page_number = 1
    successful_documents = 0
    failed_documents = 0
    duplicate_documents = 0

    try:
        async with GisMtClient(
            settings,
            token,
        ) as client:
            while True:
                if page_number > max_pages:
                    raise RuntimeError(
                        "PAGINATION_MAX_PAGES_EXCEEDED: "
                        f"достигнут предел {max_pages} страниц."
                    )

                extra_params: dict[str, str] = {
                    "order": "ASC",
                    "orderColumn": "receivedAt",
                }

                if (
                    cursor_document_id is not None
                    and cursor_received_at is not None
                ):
                    extra_params.update(
                        {
                            "did": cursor_document_id,
                            "orderedColumnValue": (
                                cursor_received_at
                            ),
                            "pageDir": "NEXT",
                        }
                    )

                list_result = await client.list_documents(
                    product_group=product_group,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                    extra_params=extra_params,
                )

                list_raw_id = repository.save_api_result(
                    run_id=run_id,
                    result=list_result,
                    source_system="GIS_MT_TRUE_API",
                    external_entity_id=(
                        f"document-list-page-{page_number}"
                    ),
                )

                page = parse_document_page(
                    list_result.payload
                )

                new_document_ids: list[str] = []

                for document_id in page.document_ids:
                    if document_id in processed_document_ids:
                        duplicate_documents += 1
                        continue

                    processed_document_ids.add(document_id)
                    new_document_ids.append(document_id)

                typer.echo("")
                typer.echo(
                    f"Страница {page_number}: "
                    f"{len(page.document_ids)} документов, "
                    f"новых {len(new_document_ids)}, "
                    f"RAW списка id={list_raw_id}, "
                    f"nextPage={page.next_page}"
                )

                for page_index, document_id in enumerate(
                    new_document_ids,
                    start=1,
                ):
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

                        # Проверяем, что ответ можно
                        # нормализовать. Исходный RAW к этому
                        # моменту уже сохранён без изменений.
                        normalized = (
                            normalize_document_info(
                                document_result.payload,
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

                        conflicts = normalized.get(
                            "_conflicts"
                        )

                        status_suffix = ""

                        if source_item_count > 1:
                            status_suffix += (
                                f", элементов ответа="
                                f"{source_item_count}"
                            )

                        if conflicts:
                            status_suffix += (
                                ", есть расхождения"
                            )

                        typer.echo(
                            f"  Документ {global_index}: "
                            f"OK, RAW id={raw_id}"
                            f"{status_suffix}"
                        )

                    except GisMtAuthError:
                        raise

                    except Exception as exc:
                        failed_documents += 1

                        typer.echo(
                            f"  Документ {global_index}: "
                            f"ERROR {type(exc).__name__}: "
                            f"{exc}",
                            err=True,
                        )

                    if delay_ms > 0:
                        await asyncio.sleep(
                            delay_ms / 1000
                        )

                typer.echo(
                    f"Итог страницы {page_number}: "
                    f"успешно всего "
                    f"{successful_documents}, "
                    f"ошибок всего "
                    f"{failed_documents}"
                )

                if not page.next_page:
                    break

                if page.cursor_document_id is None:
                    raise RuntimeError(
                        "PAGINATION_CURSOR_MISSING: "
                        "отсутствует number последнего "
                        "документа."
                    )

                if page.cursor_received_at is None:
                    raise RuntimeError(
                        "PAGINATION_CURSOR_MISSING: "
                        "отсутствует receivedAt последнего "
                        "документа."
                    )

                next_cursor = (
                    page.cursor_document_id,
                    page.cursor_received_at,
                )

                if next_cursor in seen_cursors:
                    raise RuntimeError(
                        "PAGINATION_CURSOR_STALLED: "
                        "сервер повторно вернул уже "
                        "использованный курсор."
                    )

                seen_cursors.add(next_cursor)

                cursor_document_id = (
                    page.cursor_document_id
                )

                cursor_received_at = (
                    page.cursor_received_at
                )

                page_number += 1

        final_status = (
            "SUCCESS"
            if failed_documents == 0
            else "PARTIAL"
        )

        error_code = None
        error_message = None

        if failed_documents > 0:
            error_code = "DOCUMENT_DETAIL_ERRORS"
            error_message = (
                "Не удалось получить или нормализовать "
                f"{failed_documents} документов."
            )

        repository.finish_run(
            run_id=run_id,
            status=final_status,
            records_received=successful_documents,
            error_code=error_code,
            error_message=error_message,
        )

        typer.echo("")
        typer.echo(
            f"{final_status} run_uuid={run_uuid}"
        )
        typer.echo(
            f"Загружено страниц: {page_number}"
        )
        typer.echo(
            "Уникальных документов в списке: "
            f"{len(processed_document_ids)}"
        )
        typer.echo(
            "Подробных ответов сохранено: "
            f"{successful_documents}"
        )
        typer.echo(
            f"Ошибок документов: {failed_documents}"
        )
        typer.echo(
            "Повторов между страницами: "
            f"{duplicate_documents}"
        )

    except GisMtAuthError as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            records_received=successful_documents,
            error_code="AUTH_REJECTED",
            error_message=str(exc),
        )

        typer.echo("")
        typer.echo(
            "AUTH ERROR: токен отклонён или истёк.",
            err=True,
        )
        typer.echo(
            "До остановки сохранено подробных "
            f"ответов: {successful_documents}",
            err=True,
        )

        raise typer.Exit(code=20)

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            records_received=successful_documents,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

        typer.echo("")
        typer.echo(
            f"ERROR: {type(exc).__name__}: {exc}",
            err=True,
        )
        typer.echo(
            "До остановки сохранено подробных "
            f"ответов: {successful_documents}",
            err=True,
        )

        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()