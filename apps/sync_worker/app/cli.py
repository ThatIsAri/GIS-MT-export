from __future__ import annotations

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
from app.repository import Repository


app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Диагностический CLI-контейнер "
        "для работы с True API ГИС МТ."
    ),
)


def read_token_from_stdin() -> str:
    """
    Получает токен ГИС МТ через stdin.

    Поддерживаемые форматы:

    - чистое значение токена;
    - Bearer <token>;
    - JSON-объект с полем token;
    - токен как JSON-строка в кавычках.

    Токен не принимается через аргументы командной
    строки, чтобы не попадать в историю PowerShell
    и список процессов.
    """

    if sys.stdin.isatty():
        raise typer.BadParameter(
            "Токен должен поступить через stdin. "
            "Не передавайте токен аргументом "
            "командной строки."
        )

    raw_value = sys.stdin.read().strip()

    if not raw_value:
        raise typer.BadParameter(
            "stdin пуст: токен ГИС МТ не получен."
        )

    token = raw_value

    if raw_value.startswith("{"):
        try:
            auth_payload = json.loads(
                raw_value
            )

        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                "Через stdin получен некорректный "
                "JSON ответа авторизации."
            ) from exc

        if not isinstance(
            auth_payload,
            dict,
        ):
            raise typer.BadParameter(
                "Ответ авторизации должен быть "
                "JSON-объектом."
            )

        raw_token = auth_payload.get(
            "token"
        )

        if not isinstance(
            raw_token,
            str,
        ):
            raise typer.BadParameter(
                "В JSON-ответе отсутствует "
                "строковое поле token."
            )

        token = raw_token.strip()

    elif (
        len(raw_value) >= 2
        and raw_value.startswith('"')
        and raw_value.endswith('"')
    ):
        try:
            decoded_value = json.loads(
                raw_value
            )

        except json.JSONDecodeError:
            decoded_value = None

        if isinstance(
            decoded_value,
            str,
        ):
            token = decoded_value.strip()

    if token.lower().startswith(
        "bearer "
    ):
        token = token[7:].strip()

    if not token:
        raise typer.BadParameter(
            "Получено пустое значение токена."
        )

    if (
        "\r" in token
        or "\n" in token
    ):
        raise typer.BadParameter(
            "Токен содержит переносы строк. "
            "Скопируйте только значение токена."
        )

    if any(
        character.isspace()
        for character in token
    ):
        raise typer.BadParameter(
            "Токен содержит пробелы "
            "или другие разделители."
        )

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
                f"Параметр {value!r} должен иметь "
                "формат key=value."
            )

        key, item = value.split(
            "=",
            1,
        )

        key = key.strip()
        item = item.strip()

        if not key:
            raise typer.BadParameter(
                "Имя дополнительного "
                "параметра пусто."
            )

        if key in result:
            raise typer.BadParameter(
                "Дополнительный параметр "
                f"{key!r} указан повторно."
            )

        result[key] = item

    return result


def finish_failed_run(
    *,
    repository: Repository,
    run_id: int,
    exc: Exception,
) -> None:
    """
    Фиксирует ошибку диагностического запуска.
    """

    if isinstance(
        exc,
        GisMtAuthError,
    ):
        error_code = "AUTH_REJECTED"

    else:
        error_code = type(exc).__name__

    repository.finish_run(
        run_id=run_id,
        status="FAILED",
        error_code=error_code,
        error_message=str(exc),
    )


@app.command("health")
def health() -> None:
    """
    Проверяет конфигурацию и подключение к MySQL.
    """

    settings = get_settings()
    database = Database(
        settings
    )

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
            help=(
                "Начало периода "
                "в ISO 8601."
            ),
        ),
    ] = None,

    date_to: Annotated[
        str | None,
        typer.Option(
            "--date-to",
            help=(
                "Окончание периода "
                "в ISO 8601."
            ),
        ),
    ] = None,

    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            min=1,
            help=(
                "Количество документов "
                "в одном диагностическом запросе."
            ),
        ),
    ] = None,

    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param",
            help=(
                "Дополнительный query-параметр "
                "в формате key=value."
            ),
        ),
    ] = None,

    print_json: Annotated[
        bool,
        typer.Option(
            "--print-json",
            help=(
                "Вывести JSON-ответ "
                "в консоль."
            ),
        ),
    ] = False,
) -> None:
    """
    Получает только один диагностический ответ
    списка документов.

    Команда не предназначена для полной
    синхронизации периода.
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
        Database(
            settings
        )
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
            source_system=(
                "GIS_MT_TRUE_API"
            ),
            external_entity_id=(
                "document-list-diagnostic"
            ),
        )

        page = parse_document_page(
            result.payload
        )

        repository.finish_run(
            run_id=run_id,
            status="SUCCESS",
            records_received=len(
                page.document_ids
            ),
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
            "Получено документов "
            "в диагностическом ответе: "
            f"{len(page.document_ids)}"
        )

        typer.echo(
            f"nextPage={page.next_page}"
        )

        if page.next_page:
            typer.echo(
                ""
            )

            typer.echo(
                "ВНИМАНИЕ: API сообщает "
                "о наличии продолжения.",
                err=True,
            )

            typer.echo(
                "Эта команда получает только "
                "один ответ и не должна "
                "использоваться для полной "
                "синхронизации периода.",
                err=True,
            )

            typer.echo(
                "Для полной загрузки используйте "
                "app.sync_document_details "
                "или app.sync_pipeline.",
                err=True,
            )

        for document_id in (
            page.document_ids[:20]
        ):
            typer.echo(
                f"  {document_id}"
            )

        if len(
            page.document_ids
        ) > 20:
            typer.echo(
                "  ... и ещё "
                f"{len(page.document_ids) - 20}"
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
        finish_failed_run(
            repository=repository,
            run_id=run_id,
            exc=exc,
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(
            code=20
        ) from exc

    except Exception as exc:
        finish_failed_run(
            repository=repository,
            run_id=run_id,
            exc=exc,
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


@app.command("get-document")
def get_document(
    doc_id: Annotated[
        str,
        typer.Option(
            "--doc-id",
            help=(
                "Значение поля number "
                "документа ГИС МТ."
            ),
        ),
    ],

    print_json: Annotated[
        bool,
        typer.Option(
            "--print-json",
            help=(
                "Вывести JSON-ответ "
                "в консоль."
            ),
        ),
    ] = False,
) -> None:
    """
    Получает сведения по одному документу.
    """

    prepared_document_id = (
        doc_id.strip()
    )

    if not prepared_document_id:
        raise typer.BadParameter(
            "Идентификатор документа "
            "не может быть пустым."
        )

    token = read_token_from_stdin()

    asyncio.run(
        _get_document(
            token=token,
            doc_id=prepared_document_id,
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
        Database(
            settings
        )
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
            source_system=(
                "GIS_MT_TRUE_API"
            ),
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
        finish_failed_run(
            repository=repository,
            run_id=run_id,
            exc=exc,
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(
            code=20
        ) from exc

    except Exception as exc:
        finish_failed_run(
            repository=repository,
            run_id=run_id,
            exc=exc,
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


@app.command("get-aggregate")
def get_aggregate(
    code: Annotated[
        list[str],
        typer.Option(
            "--code",
            help=(
                "Код агрегации. "
                "Параметр можно указывать "
                "несколько раз."
            ),
        ),
    ],

    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help=(
                "Товарная группа ГИС МТ."
            ),
        ),
    ] = "water",

    print_json: Annotated[
        bool,
        typer.Option(
            "--print-json",
            help=(
                "Вывести JSON-ответ "
                "в консоль."
            ),
        ),
    ] = False,
) -> None:
    """
    Получает состав одного или нескольких
    кодов агрегации.
    """

    prepared_codes = list(
        dict.fromkeys(
            item.strip()
            for item in code
            if item.strip()
        )
    )

    if not prepared_codes:
        raise typer.BadParameter(
            "Не указан ни один "
            "непустой код агрегации."
        )

    prepared_product_group = (
        product_group.strip().lower()
    )

    if not prepared_product_group:
        raise typer.BadParameter(
            "Товарная группа "
            "не может быть пустой."
        )

    token = read_token_from_stdin()

    asyncio.run(
        _get_aggregate(
            token=token,
            product_group=(
                prepared_product_group
            ),
            codes=prepared_codes,
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
        Database(
            settings
        )
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
            source_system=(
                "GIS_MT_TRUE_API"
            ),
        )

        repository.finish_run(
            run_id=run_id,
            status="SUCCESS",
            records_received=len(
                codes
            ),
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
            "Запрошено кодов агрегации: "
            f"{len(codes)}"
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
        finish_failed_run(
            repository=repository,
            run_id=run_id,
            exc=exc,
        )

        typer.echo(
            f"AUTH ERROR: {exc}",
            err=True,
        )

        raise typer.Exit(
            code=20
        ) from exc

    except Exception as exc:
        finish_failed_run(
            repository=repository,
            run_id=run_id,
            exc=exc,
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


@app.command("sync-document-list")
def sync_document_list(
    product_group: Annotated[
        str,
        typer.Option(
            "--pg",
            help=(
                "Устаревший параметр. "
                "Команда отключена."
            ),
        ),
    ] = "water",

    date_from: Annotated[
        str,
        typer.Option(
            "--date-from",
            help=(
                "Устаревший параметр. "
                "Команда отключена."
            ),
        ),
    ] = ...,

    date_to: Annotated[
        str,
        typer.Option(
            "--date-to",
            help=(
                "Устаревший параметр. "
                "Команда отключена."
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
                "Устаревший параметр. "
                "Команда отключена."
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
                "Устаревший параметр. "
                "Команда отключена."
            ),
        ),
    ] = 1000,
) -> None:
    """
    Отключённая устаревшая команда.

    Ранее использовала серверную курсорную
    пагинацию, которая показала неполные
    результаты и повторяющиеся страницы.
    """

    _ = (
        product_group,
        date_from,
        date_to,
        limit,
        max_pages,
    )

    typer.echo(
        "ERROR: команда sync-document-list "
        "отключена.",
        err=True,
    )

    typer.echo(
        "Серверная курсорная пагинация "
        "True API показала неполные результаты "
        "и повторяющиеся страницы.",
        err=True,
    )

    typer.echo(
        "Используйте app.sync_document_details "
        "или app.sync_pipeline, которые применяют "
        "адаптивное деление периода.",
        err=True,
    )

    raise typer.Exit(
        code=2
    )


if __name__ == "__main__":
    app()