import asyncio
import json
import sys
from typing import Annotated

import typer

from app.client import (
    GisMtAuthError,
    GisMtClient,
)
from app.config import get_settings
from app.db import Database
from app.pagination import parse_document_page
from app.repository import (
    Repository,
    extract_document_ids,
)


app = typer.Typer(
    no_args_is_help=True,
    help="CLI-контейнер получения данных из True API ГИС МТ.",
)


def read_token_from_stdin() -> str:
    """
    Получает токен ГИС МТ через stdin.

    Поддерживаемые форматы:
    - чистое значение токена;
    - Bearer <token>;
    - JSON-объект с полем token;
    - токен, скопированный как JSON-строка в кавычках.

    Токен не передаётся аргументом командной строки,
    чтобы он не попадал в историю PowerShell и список процессов.
    """

    if sys.stdin.isatty():
        raise typer.BadParameter(
            "Токен должен поступить через stdin. "
            "Не передавайте токен аргументом командной строки."
        )

    raw_value = sys.stdin.read().strip()

    if not raw_value:
        raise typer.BadParameter(
            "stdin пуст: токен ГИС МТ не получен."
        )

    token = raw_value

    # В буфер мог быть скопирован полный JSON-ответ авторизации.
    if raw_value.startswith("{"):
        try:
            auth_payload = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                "Через stdin получен некорректный JSON "
                "ответа авторизации."
            ) from exc

        if not isinstance(auth_payload, dict):
            raise typer.BadParameter(
                "Ответ авторизации должен быть JSON-объектом."
            )

        raw_token = auth_payload.get("token")

        if not isinstance(raw_token, str):
            raise typer.BadParameter(
                "В JSON-ответе отсутствует строковое поле token."
            )

        token = raw_token.strip()

    # В буфер могла быть скопирована JSON-строка:
    # "значение_токена"
    elif (
        len(raw_value) >= 2
        and raw_value.startswith('"')
        and raw_value.endswith('"')
    ):
        try:
            decoded_value = json.loads(raw_value)
        except json.JSONDecodeError:
            decoded_value = None

        if isinstance(decoded_value, str):
            token = decoded_value.strip()

    # Допускаем значение с префиксом Bearer.
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token:
        raise typer.BadParameter(
            "Получено пустое значение токена."
        )

    if "\r" in token or "\n" in token:
        raise typer.BadParameter(
            "Токен содержит переносы строк. "
            "Скопируйте только значение токена."
        )

    if any(character.isspace() for character in token):
        raise typer.BadParameter(
            "Токен содержит пробелы или другие разделители."
        )

    # Реальный токен ГИС МТ может быть длиннее 8192 символов.
    if len(token) > 65536:
        raise typer.BadParameter(
            "Полученное значение слишком длинное "
            "и не похоже на токен ГИС МТ."
        )

    return token


def parse_extra_params(
    values: list[str],
) -> dict[str, str]:
    """
    Преобразует параметры вида:

        --param key=value

    в словарь query-параметров.
    """

    result: dict[str, str] = {}

    for value in values:
        if "=" not in value:
            raise typer.BadParameter(
                f"Параметр {value!r} должен иметь формат key=value."
            )

        key, item = value.split("=", 1)

        key = key.strip()
        item = item.strip()

        if not key:
            raise typer.BadParameter(
                "Имя дополнительного параметра пусто."
            )

        result[key] = item

    return result


@app.command("health")
def health() -> None:
    """
    Проверяет конфигурацию и подключение к MySQL.
    """

    settings = get_settings()
    database = Database(settings)

    database.ping()

    typer.echo(
        "OK: MySQL доступен, "
        "конфигурация sync-worker загружена."
    )


@app.command("list-documents")
def list_documents(
    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help="Товарная группа ГИС МТ.",
        ),
    ] = "water",

    date_from: Annotated[
        str | None,
        typer.Option(
            "--date-from",
            help="Начало периода в ISO 8601.",
        ),
    ] = None,

    date_to: Annotated[
        str | None,
        typer.Option(
            "--date-to",
            help="Окончание периода в ISO 8601.",
        ),
    ] = None,

    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            min=1,
            help="Количество документов на странице.",
        ),
    ] = None,

    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param",
            help="Дополнительный query-параметр key=value.",
        ),
    ] = None,

    print_json: Annotated[
        bool,
        typer.Option(
            "--print-json",
            help="Вывести JSON-ответ в консоль.",
        ),
    ] = False,
) -> None:
    """
    Получает одну страницу списка документов.
    """

    token = read_token_from_stdin()

    asyncio.run(
        _list_documents(
            token=token,
            product_group=product_group,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            extra_params=parse_extra_params(
                param or []
            ),
            print_json=print_json,
        )
    )


async def _list_documents(
    *,
    token: str,
    product_group: str,
    date_from: str | None,
    date_to: str | None,
    limit: int | None,
    extra_params: dict[str, str],
    print_json: bool,
) -> None:
    settings = get_settings()

    repository = Repository(
        Database(settings)
    )

    run_id, run_uuid = repository.start_run(
        job_type="LIST_DOCUMENTS",
        date_from=date_from,
        date_to=date_to,
    )

    try:
        async with GisMtClient(
            settings,
            token,
        ) as client:
            result = await client.list_documents(
                product_group=product_group,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                extra_params=extra_params,
            )

        raw_id = repository.save_api_result(
            run_id=run_id,
            result=result,
            source_system="GIS_MT_TRUE_API",
        )

        document_ids = extract_document_ids(
            result.payload
        )

        repository.finish_run(
            run_id=run_id,
            status="SUCCESS",
            records_received=len(document_ids),
        )

        typer.echo(
            f"SUCCESS run_uuid={run_uuid}"
        )

        typer.echo(
            f"HTTP {result.status_code}, "
            f"{result.elapsed_ms} ms"
        )

        typer.echo(
            f"RAW response id={raw_id}"
        )

        typer.echo(
            "Найдено явных идентификаторов документов: "
            f"{len(document_ids)}"
        )

        for document_id in document_ids[:20]:
            typer.echo(
                f"  {document_id}"
            )

        if len(document_ids) > 20:
            typer.echo(
                "  ... и ещё "
                f"{len(document_ids) - 20}"
            )

        if print_json:
            typer.echo(
                json.dumps(
                    result.payload,
                    ensure_ascii=False,
                    indent=2,
                )
            )

    except GisMtAuthError as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code="AUTH_REJECTED",
            error_message=str(exc),
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=20)

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

        typer.echo(
            f"ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=1)


@app.command("get-document")
def get_document(
    doc_id: Annotated[
        str,
        typer.Option(
            "--doc-id",
            help="Значение поля number документа ГИС МТ.",
        ),
    ],

    print_json: Annotated[
        bool,
        typer.Option(
            "--print-json",
            help="Вывести JSON-ответ в консоль.",
        ),
    ] = False,
) -> None:
    """
    Получает сведения по одному документу.
    """

    token = read_token_from_stdin()

    asyncio.run(
        _get_document(
            token=token,
            doc_id=doc_id,
            print_json=print_json,
        )
    )


async def _get_document(
    *,
    token: str,
    doc_id: str,
    print_json: bool,
) -> None:
    settings = get_settings()

    repository = Repository(
        Database(settings)
    )

    run_id, run_uuid = repository.start_run(
        job_type="GET_DOCUMENT"
    )

    try:
        async with GisMtClient(
            settings,
            token,
        ) as client:
            result = await client.get_document(
                doc_id=doc_id
            )

        raw_id = repository.save_api_result(
            run_id=run_id,
            result=result,
            source_system="GIS_MT_TRUE_API",
            external_entity_id=doc_id,
        )

        repository.finish_run(
            run_id=run_id,
            status="SUCCESS",
            records_received=1,
        )

        typer.echo(
            f"SUCCESS run_uuid={run_uuid}"
        )

        typer.echo(
            f"HTTP {result.status_code}, "
            f"{result.elapsed_ms} ms"
        )

        typer.echo(
            f"RAW response id={raw_id}"
        )

        typer.echo(
            f"doc_id={doc_id}"
        )

        if print_json:
            typer.echo(
                json.dumps(
                    result.payload,
                    ensure_ascii=False,
                    indent=2,
                )
            )

    except GisMtAuthError as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code="AUTH_REJECTED",
            error_message=str(exc),
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=20)

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

        typer.echo(
            f"ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=1)


@app.command("get-aggregate")
def get_aggregate(
    code: Annotated[
        list[str],
        typer.Option(
            "--code",
            help=(
                "Код агрегации. Параметр можно "
                "указывать несколько раз."
            ),
        ),
    ],

    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help="Товарная группа ГИС МТ.",
        ),
    ] = "water",

    print_json: Annotated[
        bool,
        typer.Option(
            "--print-json",
            help="Вывести JSON-ответ в консоль.",
        ),
    ] = False,
) -> None:
    """
    Получает состав одного или нескольких кодов агрегации.
    """

    token = read_token_from_stdin()

    asyncio.run(
        _get_aggregate(
            token=token,
            product_group=product_group,
            codes=code,
            print_json=print_json,
        )
    )


async def _get_aggregate(
    *,
    token: str,
    product_group: str,
    codes: list[str],
    print_json: bool,
) -> None:
    settings = get_settings()

    repository = Repository(
        Database(settings)
    )

    run_id, run_uuid = repository.start_run(
        job_type="GET_AGGREGATE"
    )

    try:
        async with GisMtClient(
            settings,
            token,
        ) as client:
            result = await client.get_aggregate(
                product_group=product_group,
                codes=codes,
            )

        raw_id = repository.save_api_result(
            run_id=run_id,
            result=result,
            source_system="GIS_MT_TRUE_API",
        )

        repository.finish_run(
            run_id=run_id,
            status="SUCCESS",
            records_received=len(codes),
        )

        typer.echo(
            f"SUCCESS run_uuid={run_uuid}"
        )

        typer.echo(
            f"HTTP {result.status_code}, "
            f"{result.elapsed_ms} ms"
        )

        typer.echo(
            f"RAW response id={raw_id}"
        )

        if print_json:
            typer.echo(
                json.dumps(
                    result.payload,
                    ensure_ascii=False,
                    indent=2,
                )
            )

    except GisMtAuthError as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code="AUTH_REJECTED",
            error_message=str(exc),
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=20)

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

        typer.echo(
            f"ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=1)


@app.command("sync-document-list")
def sync_document_list(
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
            help="Предохранитель от бесконечной пагинации.",
        ),
    ] = 1000,
) -> None:
    """
    Последовательно загружает все страницы списка документов.
    """

    token = read_token_from_stdin()

    asyncio.run(
        _sync_document_list(
            token=token,
            product_group=product_group,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            max_pages=max_pages,
        )
    )


async def _sync_document_list(
    *,
    token: str,
    product_group: str,
    date_from: str,
    date_to: str,
    limit: int,
    max_pages: int,
) -> None:
    settings = get_settings()

    repository = Repository(
        Database(settings)
    )

    run_id, run_uuid = repository.start_run(
        job_type="SYNC_DOCUMENT_LIST",
        date_from=date_from,
        date_to=date_to,
    )

    unique_document_ids: set[str] = set()
    seen_cursors: set[tuple[str, str]] = set()

    cursor_document_id: str | None = None
    cursor_received_at: str | None = None

    page_number = 1

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
                            "orderedColumnValue": cursor_received_at,
                            "pageDir": "NEXT",
                        }
                    )

                result = await client.list_documents(
                    product_group=product_group,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                    extra_params=extra_params,
                )

                raw_response_id = repository.save_api_result(
                    run_id=run_id,
                    result=result,
                    source_system="GIS_MT_TRUE_API",
                    external_entity_id=(
                        f"document-list-page-{page_number}"
                    ),
                )

                page = parse_document_page(
                    result.payload
                )

                unique_document_ids.update(
                    page.document_ids
                )

                typer.echo(
                    f"Страница {page_number}: "
                    f"{len(page.document_ids)} документов, "
                    f"RAW id={raw_response_id}, "
                    f"nextPage={page.next_page}"
                )

                if not page.next_page:
                    break

                if page.cursor_document_id is None:
                    raise RuntimeError(
                        "PAGINATION_CURSOR_MISSING: "
                        "отсутствует number последнего документа."
                    )

                if page.cursor_received_at is None:
                    raise RuntimeError(
                        "PAGINATION_CURSOR_MISSING: "
                        "отсутствует receivedAt последнего документа."
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

        repository.finish_run(
            run_id=run_id,
            status="SUCCESS",
            records_received=len(
                unique_document_ids
            ),
        )

        typer.echo("")

        typer.echo(
            f"SUCCESS run_uuid={run_uuid}"
        )

        typer.echo(
            f"Загружено страниц: {page_number}"
        )

        typer.echo(
            "Уникальных документов: "
            f"{len(unique_document_ids)}"
        )

    except GisMtAuthError as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code="AUTH_REJECTED",
            error_message=str(exc),
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=20)

    except Exception as exc:
        repository.finish_run(
            run_id=run_id,
            status="FAILED",
            error_code=type(exc).__name__,
            error_message=str(exc),
        )

        typer.echo(
            f"ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()