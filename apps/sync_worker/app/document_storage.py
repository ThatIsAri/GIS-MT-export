from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


DOCUMENT_TYPE_DIRECTORY_NAMES = {
    "UNIVERSAL_TRANSFER_DOCUMENT": "УПД",
    "UPD": "УПД",
    "ON_NSCHFDOPPR": "УПД",
}

MISSING_DOCUMENT_DATE_DIRECTORY = "Без даты"

_STORAGE_SLUG_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,159}$"
)

_INVALID_DIRECTORY_CHARACTERS = re.compile(
    r'[<>:"/\\|?*\x00-\x1f]'
)


def parse_document_date(
    value: Any,
) -> date | None:
    if isinstance(
        value,
        datetime,
    ):
        return value.date()

    if isinstance(
        value,
        date,
    ):
        return value

    if value is None:
        return None

    prepared = str(
        value
    ).strip()

    if not prepared:
        return None

    try:
        return datetime.fromisoformat(
            prepared.replace(
                "Z",
                "+00:00",
            )
        ).date()

    except ValueError:
        pass

    try:
        return date.fromisoformat(
            prepared[:10]
        )

    except ValueError:
        return None


def resolve_document_date(
    *values: Any,
) -> date | None:
    """
    Возвращает первую доступную дату.

    Приоритет определяется порядком
    переданных аргументов.
    """

    for value in values:
        resolved = parse_document_date(
            value
        )

        if resolved is not None:
            return resolved

    return None


def safe_directory_name(
    value: str,
    *,
    fallback: str,
) -> str:
    prepared = " ".join(
        str(value).split()
    )

    prepared = (
        _INVALID_DIRECTORY_CHARACTERS
        .sub(
            "_",
            prepared,
        )
        .strip(" .")
    )

    prepared = re.sub(
        r"_+",
        "_",
        prepared,
    )

    if not prepared:
        return fallback

    return prepared[:120]


def document_type_directory_name(
    document_type: str | None,
) -> str:
    prepared = str(
        document_type or ""
    ).strip().upper()

    if not prepared:
        return "Прочие документы"

    configured = (
        DOCUMENT_TYPE_DIRECTORY_NAMES
        .get(
            prepared
        )
    )

    if configured:
        return configured

    return safe_directory_name(
        prepared,
        fallback="Прочие документы",
    )


def document_date_directory_name(
    document_date: date | None,
) -> str:
    if document_date is None:
        return (
            MISSING_DOCUMENT_DATE_DIRECTORY
        )

    return document_date.isoformat()


def build_document_directory(
    *,
    root: Path,
    storage_slug: str,
    document_type: str | None,
    document_date: date | None,
) -> Path:
    """
    Формирует структуру:

        <root>
        └── <организация>
            └── <тип документа>
                └── <дата документа>
    """

    prepared_slug = str(
        storage_slug
    ).strip().lower()

    if not _STORAGE_SLUG_PATTERN.fullmatch(
        prepared_slug
    ):
        raise ValueError(
            "Некорректный storage_slug "
            "организации."
        )

    prepared_root = root.resolve()

    prepared_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    target = (
        prepared_root
        / prepared_slug
        / document_type_directory_name(
            document_type
        )
        / document_date_directory_name(
            document_date
        )
    ).resolve()

    if not target.is_relative_to(
        prepared_root
    ):
        raise ValueError(
            "Каталог документа выходит "
            "за пределы корневой папки."
        )

    target.mkdir(
        parents=True,
        exist_ok=True,
    )

    return target