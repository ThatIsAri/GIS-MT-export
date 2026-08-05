from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify, request, send_file
from mysql.connector import MySQLConnection


document_catalog_bp = Blueprint(
    "document_catalog",
    __name__,
)

ROOT_CACHE_TTL_SECONDS = 300.0
DIRECTORY_CACHE_TTL_SECONDS = 30.0

_root_cache_lock = threading.Lock()
_root_cache: dict[str, Any] = {
    "expires_at": 0.0,
    "payload": None,
}

_directory_cache_lock = threading.Lock()
_directory_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Environment variable {name} is required."
        )

    return value


def database_settings() -> dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "mysql"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "database": os.getenv("DB_NAME", "gis_mt"),
        "user": required_env("DB_USER"),
        "password": required_env("DB_PASSWORD"),
        "charset": "utf8mb4",
        "collation": "utf8mb4_0900_ai_ci",
        "use_unicode": True,
        "connection_timeout": 10,
        "autocommit": True,
    }


@contextmanager
def database_read() -> Iterator[MySQLConnection]:
    connection = mysql.connector.connect(
        **database_settings()
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
            "DOCUMENT_ROOT не должен быть пустым."
        )

    return Path(configured).resolve()


def bounded_env_integer(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = os.getenv(name, str(default)).strip()

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} должен быть числом."
        ) from exc

    return max(minimum, min(value, maximum))


def max_catalog_entries() -> int:
    return bounded_env_integer(
        "DOCUMENT_CATALOG_MAX_ENTRIES",
        5000,
        minimum=100,
        maximum=50000,
    )


def max_directory_entries() -> int:
    return bounded_env_integer(
        "DOCUMENT_CATALOG_DIRECTORY_MAX_ENTRIES",
        250,
        minimum=50,
        maximum=2000,
    )


def load_organizations() -> list[dict[str, Any]]:
    with database_read() as connection:
        cursor = connection.cursor(dictionary=True)

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
                WHERE storage_slug IS NOT NULL
                  AND storage_slug <> ''
                ORDER BY
                    COALESCE(
                        NULLIF(gis_mt_name, ''),
                        short_name
                    ),
                    id
                """
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()


def normalize_query(value: str | None) -> str | None:
    prepared = " ".join(str(value or "").split())

    if not prepared:
        return None

    if len(prepared) < 3:
        raise ValueError(
            "Для поиска введите не менее трёх символов."
        )

    if len(prepared) > 200:
        raise ValueError(
            "Поисковая строка не должна превышать "
            "200 символов."
        )

    return prepared.casefold()


def normalize_catalog_path(value: str | None) -> str | None:
    prepared = str(value or "").strip().replace("\\", "/")

    if not prepared:
        return None

    if len(prepared) > 4096:
        raise ValueError(
            "Путь каталога слишком длинный."
        )

    candidate = Path(prepared)

    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(
            "Некорректный путь каталога."
        )

    return candidate.as_posix().strip("/")


def matches_query(
    query: str,
    *values: Any,
) -> bool:
    return any(
        query in str(value or "").casefold()
        for value in values
    )


def organization_payload(
    organization: dict[str, Any],
    *,
    children: list[dict[str, Any]] | None = None,
    lazy: bool = True,
) -> dict[str, Any]:
    storage_slug = str(
        organization.get("storage_slug") or ""
    ).strip().lower()
    display_name = str(
        organization.get("gis_mt_name")
        or organization.get("short_name")
        or storage_slug
    ).strip()
    short_name = str(
        organization.get("short_name")
        or display_name
    ).strip()
    prepared_children = children or []

    return {
        "type": "organization",
        "id": int(organization["id"]),
        "name": display_name,
        "short_name": short_name,
        "inn": str(organization.get("inn") or "").strip(),
        "status": str(organization.get("status") or ""),
        "storage_slug": storage_slug,
        "path": storage_slug,
        "children": prepared_children,
        "lazy": lazy,
        "loaded": not lazy,
        "has_children": None if lazy else bool(prepared_children),
    }


def build_catalog_root() -> dict[str, Any]:
    now = time.monotonic()

    with _root_cache_lock:
        cached_payload = _root_cache.get("payload")

        if (
            cached_payload is not None
            and now < float(_root_cache["expires_at"])
        ):
            return dict(cached_payload)

        organizations = [
            organization_payload(organization)
            for organization in load_organizations()
        ]
        payload = {
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "root_name": "Каталог документов",
            "query": None,
            "organizations": organizations,
            "summary": {
                "organization_count": len(organizations),
                "directory_count": 0,
                "file_count": 0,
                "scanned_entry_count": 0,
                "truncated": False,
                "lazy": True,
            },
        }

        _root_cache["expires_at"] = (
            now + ROOT_CACHE_TTL_SECONDS
        )
        _root_cache["payload"] = payload
        return dict(payload)


def resolve_directory_path(
    relative_path: str,
) -> tuple[Path, Path]:
    root = document_root()
    candidate = (root / relative_path).resolve()

    if not candidate.is_relative_to(root):
        raise ValueError(
            "Некорректный путь каталога."
        )

    if not candidate.is_dir():
        raise FileNotFoundError(
            "Папка не найдена."
        )

    return root, candidate


def lightweight_directory_items(
    *,
    root: Path,
    directory: Path,
    maximum: int,
) -> tuple[list[dict[str, Any]], bool]:
    prepared_entries: list[tuple[bool, str, str]] = []

    try:
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if (
                    entry.name.startswith(".")
                    or entry.name.endswith(".tmp")
                    or entry.is_symlink()
                ):
                    continue

                try:
                    is_directory = entry.is_dir(
                        follow_symlinks=False
                    )
                    is_file = (
                        not is_directory
                        and entry.is_file(
                            follow_symlinks=False
                        )
                    )
                except OSError:
                    continue

                if not is_directory and not is_file:
                    continue

                relative_path = Path(entry.path).relative_to(
                    root
                ).as_posix()
                prepared_entries.append(
                    (
                        is_directory,
                        entry.name,
                        relative_path,
                    )
                )

                if len(prepared_entries) >= maximum + 1:
                    break
    except OSError:
        return [], False

    truncated = len(prepared_entries) > maximum
    prepared_entries = prepared_entries[:maximum]
    prepared_entries.sort(
        key=lambda item: (
            0 if item[0] else 1,
            item[1].casefold(),
        )
    )

    items: list[dict[str, Any]] = []

    for is_directory, name, relative_path in prepared_entries:
        if is_directory:
            items.append(
                {
                    "type": "directory",
                    "name": name,
                    "path": relative_path,
                    "modified_at": None,
                    "children": [],
                    "lazy": True,
                    "loaded": False,
                    "has_children": None,
                }
            )
        else:
            items.append(
                {
                    "type": "file",
                    "name": name,
                    "path": relative_path,
                    "extension": Path(name).suffix.lower(),
                    "size": None,
                    "modified_at": None,
                }
            )

    return items, truncated


def build_directory_listing(
    relative_path: str,
) -> dict[str, Any]:
    now = time.monotonic()

    with _directory_cache_lock:
        cached = _directory_cache.get(relative_path)

        if cached is not None and now < cached[0]:
            return dict(cached[1])

    root, directory = resolve_directory_path(relative_path)
    maximum = max_directory_entries()
    items, truncated = lightweight_directory_items(
        root=root,
        directory=directory,
        maximum=maximum,
    )
    payload = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "path": relative_path,
        "items": items,
        "summary": {
            "entry_count": len(items),
            "truncated": truncated,
            "max_entries": maximum,
            "metadata_deferred": True,
        },
    }

    with _directory_cache_lock:
        if len(_directory_cache) > 500:
            expired = [
                key
                for key, value in _directory_cache.items()
                if now >= value[0]
            ]

            for key in expired:
                _directory_cache.pop(key, None)

            if len(_directory_cache) > 500:
                _directory_cache.clear()

        _directory_cache[relative_path] = (
            now + DIRECTORY_CACHE_TTL_SECONDS,
            payload,
        )

    return dict(payload)


def recursive_search(
    *,
    root: Path,
    directory: Path,
    query: str,
    limit: int,
    counters: dict[str, Any],
) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []

    try:
        iterator = os.scandir(directory)
    except OSError:
        return children

    with iterator:
        for entry in iterator:
            if counters["scanned"] >= limit:
                counters["truncated"] = True
                break

            if (
                entry.name.startswith(".")
                or entry.name.endswith(".tmp")
                or entry.is_symlink()
            ):
                continue

            counters["scanned"] += 1

            try:
                is_directory = entry.is_dir(
                    follow_symlinks=False
                )
                is_file = (
                    not is_directory
                    and entry.is_file(
                        follow_symlinks=False
                    )
                )
            except OSError:
                continue

            relative_path = Path(entry.path).relative_to(
                root
            ).as_posix()
            matched = matches_query(
                query,
                entry.name,
                relative_path,
            )

            if is_directory:
                nested = recursive_search(
                    root=root,
                    directory=Path(entry.path),
                    query=query,
                    limit=limit,
                    counters=counters,
                )

                if matched or nested:
                    counters["directories"] += 1
                    children.append(
                        {
                            "type": "directory",
                            "name": entry.name,
                            "path": relative_path,
                            "modified_at": None,
                            "children": nested,
                            "lazy": False,
                            "loaded": True,
                            "has_children": bool(nested),
                        }
                    )

                if counters["truncated"]:
                    break
                continue

            if is_file and matched:
                counters["files"] += 1
                children.append(
                    {
                        "type": "file",
                        "name": entry.name,
                        "path": relative_path,
                        "extension": Path(entry.name).suffix.lower(),
                        "size": None,
                        "modified_at": None,
                    }
                )

    children.sort(
        key=lambda item: (
            0 if item["type"] == "directory" else 1,
            str(item["name"]).casefold(),
        )
    )
    return children


def build_search_catalog(query: str) -> dict[str, Any]:
    root = document_root()
    maximum = max_catalog_entries()
    counters: dict[str, Any] = {
        "directories": 0,
        "files": 0,
        "scanned": 0,
        "truncated": False,
    }
    organizations: list[dict[str, Any]] = []

    for organization in load_organizations():
        storage_slug = str(
            organization.get("storage_slug") or ""
        ).strip().lower()
        organization_matched = matches_query(
            query,
            organization.get("short_name"),
            organization.get("gis_mt_name"),
            organization.get("inn"),
            storage_slug,
        )
        directory = (root / storage_slug).resolve()
        children: list[dict[str, Any]] = []

        if (
            directory.is_relative_to(root)
            and directory.is_dir()
        ):
            children = recursive_search(
                root=root,
                directory=directory,
                query=query,
                limit=maximum,
                counters=counters,
            )

        if organization_matched or children:
            organizations.append(
                organization_payload(
                    organization,
                    children=children,
                    lazy=False,
                )
            )

        if counters["truncated"]:
            break

    return {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "root_name": "Каталог документов",
        "query": query,
        "organizations": organizations,
        "summary": {
            "organization_count": len(organizations),
            "directory_count": counters["directories"],
            "file_count": counters["files"],
            "scanned_entry_count": counters["scanned"],
            "truncated": counters["truncated"],
            "max_entries": maximum,
            "lazy": False,
            "metadata_deferred": True,
        },
    }


def resolve_download_path(
    raw_path: str,
) -> Path:
    prepared = normalize_catalog_path(raw_path)

    if not prepared:
        raise ValueError(
            "Не указан путь к файлу."
        )

    root = document_root()
    candidate = (root / prepared).resolve()

    if not candidate.is_relative_to(root):
        raise ValueError(
            "Некорректный путь к файлу."
        )

    if not candidate.is_file():
        raise FileNotFoundError(
            "Файл не найден."
        )

    return candidate


@document_catalog_bp.get("/api/document-catalog")
def document_catalog():
    started_at = time.perf_counter()

    try:
        query = normalize_query(
            request.args.get("q")
        )
        relative_path = normalize_catalog_path(
            request.args.get("path")
        )

        if query is not None and relative_path is not None:
            raise ValueError(
                "Поиск и открытие папки нельзя "
                "выполнять одним запросом."
            )

        if query is not None:
            payload = build_search_catalog(query)
            operation = "search"
        elif relative_path is not None:
            payload = build_directory_listing(
                relative_path
            )
            operation = "directory"
        else:
            payload = build_catalog_root()
            operation = "root"

        elapsed_ms = round(
            (time.perf_counter() - started_at) * 1000,
            1,
        )
        payload["performance"] = {
            "elapsed_ms": elapsed_ms,
            "operation": operation,
        }
        response = jsonify(payload)
        response.headers["Server-Timing"] = (
            f"catalog;dur={elapsed_ms}"
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    except ValueError as exc:
        return jsonify(
            {
                "status": "ERROR",
                "error": str(exc),
            }
        ), 400
    except FileNotFoundError as exc:
        return jsonify(
            {
                "status": "ERROR",
                "error": str(exc),
            }
        ), 404
    except mysql.connector.Error:
        return jsonify(
            {
                "status": "ERROR",
                "error": (
                    "Не удалось получить список "
                    "организаций."
                ),
            }
        ), 500


@document_catalog_bp.get(
    "/api/document-catalog/download"
)
def download_document():
    try:
        path = resolve_download_path(
            request.args.get("path", "")
        )
    except ValueError as exc:
        return jsonify(
            {
                "status": "ERROR",
                "error": str(exc),
            }
        ), 400
    except FileNotFoundError as exc:
        return jsonify(
            {
                "status": "ERROR",
                "error": str(exc),
            }
        ), 404

    return send_file(
        path,
        as_attachment=True,
        download_name=path.name,
        conditional=True,
    )
