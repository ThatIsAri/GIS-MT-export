from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import mysql.connector
from flask import (
    Blueprint,
    jsonify,
    request,
    send_file,
)
from mysql.connector import MySQLConnection


document_catalog_bp = Blueprint(
    "document_catalog",
    __name__,
)


@dataclass(
    slots=True,
)
class CatalogCounters:
    directory_count: int = 0
    file_count: int = 0
    scanned_entry_count: int = 0
    truncated: bool = False


def required_env(
    name: str,
) -> str:
    value = os.getenv(
        name,
        "",
    ).strip()

    if not value:
        raise RuntimeError(
            f"Environment variable "
            f"{name} is required."
        )

    return value


def database_settings() -> dict[
    str,
    Any,
]:
    return {
        "host": os.getenv(
            "DB_HOST",
            "mysql",
        ),
        "port": int(
            os.getenv(
                "DB_PORT",
                "3306",
            )
        ),
        "database": os.getenv(
            "DB_NAME",
            "gis_mt",
        ),
        "user": required_env(
            "DB_USER"
        ),
        "password": required_env(
            "DB_PASSWORD"
        ),
        "charset": "utf8mb4",
        "collation": (
            "utf8mb4_0900_ai_ci"
        ),
        "use_unicode": True,
        "connection_timeout": 10,
        "autocommit": True,
    }


@contextmanager
def database_read() -> Iterator[
    MySQLConnection
]:
    connection = (
        mysql.connector.connect(
            **database_settings()
        )
    )

    try:
        yield connection

    finally:
        connection.close()


def document_root() -> Path:
    configured = os.getenv(
        "DOCUMENT_ROOT",
        "/data/official",
    ).strip()

    if not configured:
        raise RuntimeError(
            "DOCUMENT_ROOT не должен "
            "быть пустым."
        )

    root = Path(
        configured
    ).resolve()

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    return root


def max_catalog_entries() -> int:
    raw_value = os.getenv(
        "DOCUMENT_CATALOG_MAX_ENTRIES",
        "20000",
    ).strip()

    try:
        value = int(
            raw_value
        )

    except ValueError as exc:
        raise RuntimeError(
            "DOCUMENT_CATALOG_MAX_ENTRIES "
            "должен быть числом."
        ) from exc

    return max(
        100,
        min(
            value,
            200000,
        ),
    )


def load_organizations() -> list[
    dict[str, Any]
]:
    with database_read() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    id,
                    short_name,
                    gis_mt_name,
                    inn,
                    storage_slug,
                    status
                FROM legal_entity
                ORDER BY
                    short_name,
                    id
                """
            )

            return [
                dict(
                    row
                )
                for row
                in cursor.fetchall()
            ]

        finally:
            cursor.close()


def normalize_query(
    value: str | None,
) -> str | None:
    prepared = " ".join(
        str(
            value or ""
        ).split()
    )

    if not prepared:
        return None

    if len(
        prepared
    ) < 3:
        raise ValueError(
            "Для поиска введите "
            "не менее трёх символов."
        )

    if len(
        prepared
    ) > 200:
        raise ValueError(
            "Поисковая строка не должна "
            "превышать 200 символов."
        )

    return prepared.casefold()


def relative_catalog_path(
    path: Path,
    root: Path,
) -> str:
    return (
        path
        .relative_to(
            root
        )
        .as_posix()
    )


def matches_query(
    query: str | None,
    *values: Any,
) -> bool:
    if query is None:
        return True

    return any(
        query
        in str(
            value or ""
        ).casefold()
        for value
        in values
    )


def modified_at_iso(
    path: Path,
) -> str | None:
    try:
        timestamp = (
            path.stat().st_mtime
        )

    except OSError:
        return None

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    ).isoformat()


def safe_directory_entries(
    path: Path,
) -> list[Path]:
    try:
        entries = list(
            path.iterdir()
        )

    except OSError:
        return []

    return sorted(
        (
            entry
            for entry
            in entries
            if not entry.is_symlink()
            and not entry.name.startswith(
                "."
            )
            and not entry.name.endswith(
                ".tmp"
            )
        ),
        key=lambda entry: (
            0
            if entry.is_dir()
            else 1,
            entry.name.casefold(),
        ),
    )


def scan_directory(
    *,
    directory: Path,
    root: Path,
    query: str | None,
    include_all: bool,
    counters: CatalogCounters,
    max_entries: int,
) -> list[
    dict[str, Any]
]:
    result: list[
        dict[str, Any]
    ] = []

    for entry in safe_directory_entries(
        directory
    ):
        if (
            counters.scanned_entry_count
            >= max_entries
        ):
            counters.truncated = True
            break

        counters.scanned_entry_count += 1

        relative_path = (
            relative_catalog_path(
                entry,
                root,
            )
        )

        entry_matches = matches_query(
            query,
            entry.name,
            relative_path,
        )

        if entry.is_dir():
            children = scan_directory(
                directory=entry,
                root=root,
                query=query,
                include_all=(
                    include_all
                    or entry_matches
                ),
                counters=counters,
                max_entries=max_entries,
            )

            if (
                query is not None
                and not include_all
                and not entry_matches
                and not children
            ):
                continue

            counters.directory_count += 1

            result.append(
                {
                    "type": "directory",
                    "name": entry.name,
                    "path": relative_path,
                    "modified_at": (
                        modified_at_iso(
                            entry
                        )
                    ),
                    "children": children,
                }
            )

            continue

        if not entry.is_file():
            continue

        if (
            query is not None
            and not include_all
            and not entry_matches
        ):
            continue

        counters.file_count += 1

        try:
            size = (
                entry.stat().st_size
            )

        except OSError:
            size = None

        result.append(
            {
                "type": "file",
                "name": entry.name,
                "path": relative_path,
                "extension": (
                    entry.suffix.lower()
                ),
                "size": size,
                "modified_at": (
                    modified_at_iso(
                        entry
                    )
                ),
            }
        )

    return result


def ensure_organization_directory(
    *,
    root: Path,
    storage_slug: str,
) -> Path | None:
    if not storage_slug:
        return None

    candidate = (
        root
        / storage_slug
    ).resolve()

    if not candidate.is_relative_to(
        root
    ):
        return None

    candidate.mkdir(
        parents=True,
        exist_ok=True,
    )

    return candidate


def build_catalog(
    query: str | None,
) -> dict[
    str,
    Any,
]:
    root = document_root()

    counters = CatalogCounters()

    max_entries = (
        max_catalog_entries()
    )

    organizations: list[
        dict[str, Any]
    ] = []

    for organization in load_organizations():
        storage_slug = str(
            organization.get(
                "storage_slug"
            )
            or ""
        ).strip().lower()

        organization_directory = (
            ensure_organization_directory(
                root=root,
                storage_slug=storage_slug,
            )
        )

        if organization_directory is None:
            continue

        display_name = str(
            organization.get(
                "gis_mt_name"
            )
            or organization.get(
                "short_name"
            )
            or storage_slug
        ).strip()

        short_name = str(
            organization.get(
                "short_name"
            )
            or display_name
        ).strip()

        inn = str(
            organization.get(
                "inn"
            )
            or ""
        ).strip()

        organization_matches = (
            matches_query(
                query,
                display_name,
                short_name,
                storage_slug,
                inn,
            )
        )

        children = scan_directory(
            directory=(
                organization_directory
            ),
            root=root,
            query=query,
            include_all=(
                organization_matches
            ),
            counters=counters,
            max_entries=max_entries,
        )

        if (
            query is not None
            and not organization_matches
            and not children
        ):
            continue

        organizations.append(
            {
                "type": "organization",
                "id": int(
                    organization["id"]
                ),
                "name": display_name,
                "short_name": short_name,
                "inn": inn,
                "status": str(
                    organization.get(
                        "status"
                    )
                    or ""
                ),
                "storage_slug": (
                    storage_slug
                ),
                "path": storage_slug,
                "children": children,
            }
        )

    return {
        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "root_name": (
            "Каталог документов"
        ),
        "query": query,
        "organizations": organizations,
        "summary": {
            "organization_count": len(
                organizations
            ),
            "directory_count": (
                counters.directory_count
            ),
            "file_count": (
                counters.file_count
            ),
            "scanned_entry_count": (
                counters
                .scanned_entry_count
            ),
            "truncated": (
                counters.truncated
            ),
            "max_entries": max_entries,
        },
    }


def resolve_download_path(
    relative_path: str,
) -> Path:
    prepared = str(
        relative_path or ""
    ).strip()

    if not prepared:
        raise ValueError(
            "Не указан путь к файлу."
        )

    root = document_root()

    candidate = (
        root
        / prepared
    ).resolve()

    if not candidate.is_relative_to(
        root
    ):
        raise ValueError(
            "Некорректный путь "
            "к файлу."
        )

    if not candidate.is_file():
        raise FileNotFoundError(
            "Файл не найден."
        )

    return candidate


@document_catalog_bp.get(
    "/api/document-catalog"
)
def document_catalog():
    try:
        query = normalize_query(
            request.args.get(
                "q"
            )
        )

        return jsonify(
            build_catalog(
                query
            )
        )

    except ValueError as exc:
        return (
            jsonify(
                {
                    "status": "ERROR",
                    "error": str(
                        exc
                    ),
                }
            ),
            400,
        )


@document_catalog_bp.get(
    "/api/document-catalog/download"
)
def download_document():
    try:
        path = resolve_download_path(
            request.args.get(
                "path",
                "",
            )
        )

    except ValueError as exc:
        return (
            jsonify(
                {
                    "status": "ERROR",
                    "error": str(
                        exc
                    ),
                }
            ),
            400,
        )

    except FileNotFoundError as exc:
        return (
            jsonify(
                {
                    "status": "ERROR",
                    "error": str(
                        exc
                    ),
                }
            ),
            404,
        )

    response = send_file(
        path,
        as_attachment=True,
        download_name=path.name,
        conditional=True,
    )

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    return response