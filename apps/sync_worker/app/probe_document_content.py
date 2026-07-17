import asyncio
import hashlib
import json
import os
from typing import Annotated, Any
from urllib.parse import quote

import httpx
import typer

from app.cli import read_token_from_stdin


app = typer.Typer(
    add_completion=False,
    help=(
        "Диагностика метода получения содержимого "
        "документа True API ГИС МТ."
    ),
)


def required_env(name: str) -> str:
    """
    Возвращает обязательную переменную окружения.
    """

    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(
            f"Не задана обязательная переменная окружения {name}."
        )

    return value.strip().rstrip("/")


def describe_value(
    container: Any,
    field_name: str,
) -> str:
    """
    Описывает тип и размер поля, не выводя его содержимое.
    """

    if not isinstance(container, dict):
        return "отсутствует"

    if field_name not in container:
        return "отсутствует"

    value = container[field_name]

    if value is None:
        return "NULL"

    if isinstance(value, bool):
        return f"BOOLEAN, значение={value}"

    if isinstance(value, str):
        return f"STRING, длина={len(value)}"

    if isinstance(value, list):
        return f"ARRAY, элементов={len(value)}"

    if isinstance(value, dict):
        keys = ", ".join(
            sorted(str(key) for key in value.keys())
        )

        return f"OBJECT, ключи={keys}"

    if isinstance(value, int):
        return f"INTEGER, значение={value}"

    if isinstance(value, float):
        return f"NUMBER, значение={value}"

    return type(value).__name__.upper()


def summarize_json(
    payload: Any,
) -> None:
    """
    Выводит структуру JSON без значений коммерческих
    и персональных данных.
    """

    probe_container: dict[str, Any] | None = None

    if isinstance(payload, dict):
        typer.echo("JSON type: OBJECT")

        typer.echo(
            "Ключи: "
            + ", ".join(
                sorted(
                    str(key)
                    for key in payload.keys()
                )
            )
        )

        probe_container = payload

    elif isinstance(payload, list):
        typer.echo("JSON type: ARRAY")
        typer.echo(
            f"Количество элементов: {len(payload)}"
        )

        if payload and isinstance(payload[0], dict):
            probe_container = payload[0]

            typer.echo(
                "Ключи первого элемента: "
                + ", ".join(
                    sorted(
                        str(key)
                        for key in probe_container.keys()
                    )
                )
            )

        elif payload:
            typer.echo(
                "Тип первого элемента: "
                f"{type(payload[0]).__name__.upper()}"
            )

    else:
        typer.echo(
            "JSON type: "
            f"{type(payload).__name__.upper()}"
        )

    for field_name in (
        "products",
        "product",
        "codes",
        "cis",
        "cises",
        "nextPage",
        "content",
        "body",
        "document",
        "file",
        "fileName",
        "pdfFile",
        "downloadDesc",
        "input",
    ):
        typer.echo(
            f"Поле {field_name}: "
            f"{describe_value(probe_container, field_name)}"
        )


def classify_non_json_content(
    content: bytes,
) -> str:
    """
    Определяет предположительный формат не-JSON ответа.
    """

    stripped = content.lstrip()

    if stripped.startswith(b"<?xml"):
        return "XML"

    if stripped.startswith(b"<"):
        return "XML или HTML"

    if content.startswith(b"PK"):
        return "ZIP"

    if content.startswith(b"%PDF"):
        return "PDF"

    if content.startswith(b"\x1f\x8b"):
        return "GZIP"

    return "двоичные или текстовые данные"


def summarize_response(
    name: str,
    response: httpx.Response,
) -> None:
    """
    Показывает технические характеристики ответа,
    не раскрывая тело документа.
    """

    content_type = response.headers.get(
        "content-type",
        "",
    )

    content_disposition = response.headers.get(
        "content-disposition",
        "",
    )

    response_hash = hashlib.sha256(
        response.content
    ).hexdigest()

    typer.echo("")
    typer.echo("=" * 72)
    typer.echo(name)

    typer.echo(
        f"URL path: {response.request.url.path}"
    )

    typer.echo(
        f"Query: {response.request.url.query.decode('utf-8')}"
        if isinstance(response.request.url.query, bytes)
        else f"Query: {response.request.url.query}"
    )

    typer.echo(
        f"HTTP status: {response.status_code}"
    )

    typer.echo(
        "Content-Type: "
        f"{content_type or 'не указан'}"
    )

    typer.echo(
        "Content-Disposition: "
        f"{content_disposition or 'не указан'}"
    )

    typer.echo(
        f"Размер ответа: {len(response.content)} байт"
    )

    typer.echo(
        f"SHA-256 ответа: {response_hash}"
    )

    if not response.content:
        typer.echo("Ответ пуст.")
        return

    try:
        payload = response.json()

    except ValueError:
        typer.echo("Ответ не является JSON.")

        typer.echo(
            "Класс содержимого: "
            f"{classify_non_json_content(response.content)}"
        )

        return

    summarize_json(payload)


async def execute_probe(
    *,
    token: str,
    document_id: str,
) -> None:
    """
    Выполняет диагностические запросы к одному документу.
    """

    base_v4 = required_env(
        "GIS_MT_TRUE_API_V4_URL"
    )

    encoded_document_id = quote(
        document_id,
        safe="",
    )

    document_url = (
        f"{base_v4}/doc/"
        f"{encoded_document_id}/info"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": (
            "CZ-Async-Document-Content-Probe/0.2"
        ),
    }

    requests: list[
        tuple[
            str,
            dict[str, str] | None,
        ]
    ] = [
        (
            "V4: без товарной группы",
            None,
        ),
        (
            "V4: упакованная вода, pg=13",
            {
                "pg": "13",
                "limit": "15",
            },
        ),
        (
            "V4: безалкогольные напитки, pg=23",
            {
                "pg": "23",
                "limit": "15",
            },
        ),
    ]

    timeout = httpx.Timeout(
        connect=20.0,
        read=120.0,
        write=30.0,
        pool=20.0,
    )

    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        for request_name, params in requests:
            try:
                response = await client.get(
                    document_url,
                    params=params,
                )

                summarize_response(
                    request_name,
                    response,
                )

            except httpx.HTTPError as exc:
                typer.echo("")
                typer.echo("=" * 72)
                typer.echo(request_name)

                typer.echo(
                    "HTTP ERROR: "
                    f"{type(exc).__name__}: {exc}"
                )


@app.command()
def main(
    document_id: Annotated[
        str,
        typer.Option(
            "--doc-id",
            help="Значение поля number документа ГИС МТ.",
        ),
    ],
) -> None:
    """
    Проверяет получение документа:

    - без товарной группы;
    - с pg=13 для упакованной воды;
    - с pg=23 для безалкогольных напитков.

    Содержимое документа в консоль не выводится.
    """

    prepared_document_id = document_id.strip()

    if not prepared_document_id:
        raise typer.BadParameter(
            "Идентификатор документа не может быть пустым."
        )

    token = read_token_from_stdin()

    asyncio.run(
        execute_probe(
            token=token,
            document_id=prepared_document_id,
        )
    )


if __name__ == "__main__":
    app()