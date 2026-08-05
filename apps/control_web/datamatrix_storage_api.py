from __future__ import annotations

import math
import os
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify, request
from mysql.connector import MySQLConnection


datamatrix_storage_bp = Blueprint(
    "datamatrix_storage",
    __name__,
)


DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 250
MAX_QUERY_LENGTH = 200
SUMMARY_CACHE_TTL_SECONDS = 30.0
ORGANIZATION_CACHE_TTL_SECONDS = 60.0

_summary_cache_lock = threading.Lock()
_summary_cache: dict[
    tuple[int | None, str | None],
    tuple[float, dict[str, int]],
] = {}

_organization_cache_lock = threading.Lock()
_organization_cache: dict[str, Any] = {
    "expires_at": 0.0,
    "items": [],
}

ALLOWED_QUANTITY_STATUSES = {
    "MATCHED",
    "MISMATCH",
    "NOT_CHECKED",
}


class DatamatrixStorageApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        connection.set_charset_collation(
            charset="utf8mb4",
            collation="utf8mb4_0900_ai_ci",
        )
        yield connection
    finally:
        connection.close()


def parse_positive_integer(
    value: str | None,
    *,
    field_name: str,
    default: int,
    maximum: int | None = None,
) -> int:
    prepared = str(value or "").strip()

    if not prepared:
        return default

    try:
        result = int(prepared)
    except ValueError as exc:
        raise DatamatrixStorageApiError(
            f"Параметр {field_name} должен быть числом."
        ) from exc

    if result < 1:
        raise DatamatrixStorageApiError(
            f"Параметр {field_name} должен быть больше 0."
        )

    if maximum is not None and result > maximum:
        return maximum

    return result


def normalize_query(value: str | None) -> str | None:
    prepared = " ".join(str(value or "").split())

    if not prepared:
        return None

    if len(prepared) < 3:
        raise DatamatrixStorageApiError(
            "Для поиска введите не менее трёх символов."
        )

    if len(prepared) > MAX_QUERY_LENGTH:
        raise DatamatrixStorageApiError(
            "Поисковая строка не должна превышать "
            f"{MAX_QUERY_LENGTH} символов."
        )

    return prepared


def parse_entity_id(value: str | None) -> int | None:
    prepared = str(value or "").strip()

    if not prepared:
        return None

    try:
        entity_id = int(prepared)
    except ValueError as exc:
        raise DatamatrixStorageApiError(
            "Некорректный идентификатор организации."
        ) from exc

    if entity_id < 1:
        raise DatamatrixStorageApiError(
            "Некорректный идентификатор организации."
        )

    return entity_id


def parse_quantity_status(value: str | None) -> str | None:
    prepared = str(value or "").strip().upper()

    if not prepared or prepared == "ALL":
        return None

    if prepared not in ALLOWED_QUANTITY_STATUSES:
        raise DatamatrixStorageApiError(
            "Некорректный статус проверки количества."
        )

    return prepared


def decimal_text(
    value: Decimal | int | float | str | None,
) -> str | None:
    if value is None:
        return None

    prepared = format(Decimal(str(value)), "f")

    if "." in prepared:
        prepared = prepared.rstrip("0").rstrip(".")

    return prepared or "0"


def datetime_iso(
    value: datetime | date | None,
) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.isoformat()

    return value.isoformat()


def optional_text(value: Any) -> str:
    return str(value or "")


def organization_name(row: dict[str, Any]) -> str:
    return str(
        row.get("gis_mt_name")
        or row.get("short_name")
        or "Организация"
    )


def serialize_organization(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": organization_name(row),
        "short_name": optional_text(row.get("short_name")),
        "gis_mt_name": optional_text(row.get("gis_mt_name")),
        "inn": optional_text(row.get("inn")),
        "unit_count": int(row.get("unit_count") or 0),
        "source_count": int(row.get("source_count") or 0),
        "mismatch_source_count": int(
            row.get("mismatch_source_count") or 0
        ),
    }


def serialize_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["source_code_id"]),
        "code": optional_text(row.get("source_code_text")),
        "gtin": optional_text(row.get("source_gtin")),
        "code_kind": optional_text(row.get("source_code_kind")),
        "expansion_status": optional_text(
            row.get("source_expansion_status")
        ),
        "quantity_match_status": optional_text(
            row.get("source_quantity_match_status")
        ),
        "expected_unit_count": decimal_text(
            row.get("source_expected_unit_count")
        ),
        "actual_unit_count": int(
            row.get("source_actual_unit_count") or 0
        ),
        "line_quantity": decimal_text(
            row.get("source_source_line_quantity")
        ),
        "line_code_count": int(
            row.get("source_line_code_count") or 0
        ),
        "document_product_name": optional_text(
            row.get("source_document_product_name")
        ),
        "product_code": optional_text(
            row.get("source_product_code")
        ),
        "error": optional_text(row.get("source_expansion_error")),
    }


def serialize_unit(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "code": optional_text(row.get("code_text")),
        "gtin": optional_text(row.get("gtin")),
        "product_name": optional_text(row.get("product_name")),
        "product_name_source": optional_text(
            row.get("product_name_source")
        ),
        "document_product_name": optional_text(
            row.get("document_product_name")
        ),
        "product_code": optional_text(row.get("product_code")),
        "quantity": decimal_text(row.get("quantity")),
        "source_line_quantity": decimal_text(
            row.get("unit_source_line_quantity")
        ),
        "receiver_warehouse_address": optional_text(
            row.get("receiver_warehouse_address")
        ),
        "source_document_date": datetime_iso(
            row.get("source_document_date")
        ),
        "external_document_id": optional_text(
            row.get("external_document_id")
        ),
        "core_document_id": int(row["core_document_id"]),
        "raw_edo_document_id": int(row["raw_edo_document_id"]),
        "updated_at": datetime_iso(row.get("updated_at")),
        "source": serialize_source(row),
        "organization": {
            "id": int(row["legal_entity_id"]),
            "name": organization_name(row),
            "short_name": optional_text(row.get("short_name")),
            "gis_mt_name": optional_text(row.get("gis_mt_name")),
            "inn": optional_text(row.get("inn")),
        },
    }


def load_organizations(
    connection: MySQLConnection,
) -> list[dict[str, Any]]:
    now = time.monotonic()

    with _organization_cache_lock:
        if now < float(
            _organization_cache["expires_at"]
        ):
            return list(
                _organization_cache["items"]
            )

        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    entity.id,
                    entity.short_name,
                    entity.gis_mt_name,
                    entity.inn,

                    COALESCE(
                        source_stats.unit_count,
                        0
                    ) AS unit_count,

                    COALESCE(
                        source_stats.source_count,
                        0
                    ) AS source_count,

                    COALESCE(
                        source_stats.mismatch_source_count,
                        0
                    ) AS mismatch_source_count

                FROM legal_entity AS entity

                JOIN (
                    SELECT
                        source.legal_entity_id,

                        COALESCE(
                            SUM(source.actual_unit_count),
                            0
                        ) AS unit_count,

                        COUNT(*) AS source_count,

                        COALESCE(
                            SUM(
                                source.quantity_match_status =
                                'MISMATCH'
                            ),
                            0
                        ) AS mismatch_source_count

                    FROM datamatrix_source_code AS source
                    GROUP BY source.legal_entity_id
                ) AS source_stats
                  ON source_stats.legal_entity_id = entity.id

                ORDER BY
                    COALESCE(
                        NULLIF(entity.gis_mt_name, ''),
                        entity.short_name
                    ),
                    entity.id
                """
            )

            organizations = [
                serialize_organization(dict(row))
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()

        _organization_cache["expires_at"] = (
            now + ORGANIZATION_CACHE_TTL_SECONDS
        )
        _organization_cache["items"] = organizations
        return list(organizations)


def build_filters(
    *,
    query: str | None,
    entity_id: int | None,
    quantity_status: str | None,
) -> tuple[str, list[Any]]:
    conditions = ["1 = 1"]
    parameters: list[Any] = []

    if entity_id is not None:
        conditions.append("unit.legal_entity_id = %s")
        parameters.append(entity_id)

    if quantity_status is not None:
        conditions.append("source.quantity_match_status = %s")
        parameters.append(quantity_status)

    if query is not None:
        pattern = f"%{query}%"

        conditions.append(
            """
            (
                unit.code_text LIKE %s
                OR unit.gtin LIKE %s
                OR unit.product_name LIKE %s
                OR unit.document_product_name LIKE %s
                OR unit.product_code LIKE %s
                OR unit.receiver_warehouse_address LIKE %s
                OR unit.external_document_id LIKE %s
                OR source.code_text LIKE %s
                OR source.source_gtin LIKE %s
                OR source.document_product_name LIKE %s
                OR source.product_code LIKE %s
                OR entity.short_name LIKE %s
                OR entity.gis_mt_name LIKE %s
                OR entity.inn LIKE %s
            )
            """
        )

        parameters.extend([pattern] * 14)

    return " AND ".join(conditions), parameters


def load_summary(
    connection: MySQLConnection,
    *,
    where_sql: str,
    parameters: list[Any],
    query: str | None,
    entity_id: int | None,
    quantity_status: str | None,
) -> dict[str, int]:
    cache_key = (
        entity_id,
        quantity_status,
    )
    now = time.monotonic()

    if query is None:
        with _summary_cache_lock:
            cached = _summary_cache.get(cache_key)

            if cached is not None and now < cached[0]:
                return dict(cached[1])

        conditions = ["1 = 1"]
        summary_parameters: list[Any] = []

        if entity_id is not None:
            conditions.append(
                "source.legal_entity_id = %s"
            )
            summary_parameters.append(entity_id)

        if quantity_status is not None:
            conditions.append(
                "source.quantity_match_status = %s"
            )
            summary_parameters.append(quantity_status)

        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                f"""
                SELECT
                    COALESCE(
                        SUM(source.actual_unit_count),
                        0
                    ) AS unit_count,

                    COUNT(*) AS source_count,

                    COALESCE(
                        SUM(
                            source.code_kind = 'AGGREGATE'
                        ),
                        0
                    ) AS aggregate_count,

                    COALESCE(
                        SUM(
                            source.quantity_match_status =
                            'MISMATCH'
                        ),
                        0
                    ) AS mismatch_source_count

                FROM datamatrix_source_code AS source

                WHERE {' AND '.join(conditions)}
                """,
                tuple(summary_parameters),
            )

            row = cursor.fetchone() or {}
        finally:
            cursor.close()

        summary = {
            "unit_count": int(
                row.get("unit_count") or 0
            ),
            "source_count": int(
                row.get("source_count") or 0
            ),
            "aggregate_count": int(
                row.get("aggregate_count") or 0
            ),
            "mismatch_source_count": int(
                row.get("mismatch_source_count") or 0
            ),
        }

        with _summary_cache_lock:
            if len(_summary_cache) > 100:
                expired_keys = [
                    key
                    for key, value in _summary_cache.items()
                    if now >= value[0]
                ]

                for key in expired_keys:
                    _summary_cache.pop(key, None)

                if len(_summary_cache) > 100:
                    _summary_cache.clear()

            _summary_cache[cache_key] = (
                now + SUMMARY_CACHE_TTL_SECONDS,
                summary,
            )

        return dict(summary)

    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            f"""
            SELECT
                COUNT(unit.id) AS unit_count,

                COUNT(
                    DISTINCT source.id
                ) AS source_count,

                COUNT(
                    DISTINCT CASE
                        WHEN source.code_kind = 'AGGREGATE'
                            THEN source.id
                        ELSE NULL
                    END
                ) AS aggregate_count,

                COUNT(
                    DISTINCT CASE
                        WHEN source.quantity_match_status = 'MISMATCH'
                            THEN source.id
                        ELSE NULL
                    END
                ) AS mismatch_source_count

            FROM datamatrix_unit AS unit

            JOIN datamatrix_source_code AS source
              ON source.id = unit.source_code_id

            JOIN legal_entity AS entity
              ON entity.id = unit.legal_entity_id

            WHERE {where_sql}
            """,
            tuple(parameters),
        )

        row = cursor.fetchone() or {}
    finally:
        cursor.close()

    return {
        "unit_count": int(row.get("unit_count") or 0),
        "source_count": int(row.get("source_count") or 0),
        "aggregate_count": int(row.get("aggregate_count") or 0),
        "mismatch_source_count": int(
            row.get("mismatch_source_count") or 0
        ),
    }


def load_units(
    connection: MySQLConnection,
    *,
    where_sql: str,
    parameters: list[Any],
    page_size: int,
    offset: int,
) -> list[dict[str, Any]]:
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            f"""
            SELECT
                unit.id,
                unit.code_text,
                unit.gtin,
                unit.product_name,
                unit.product_name_source,
                unit.document_product_name,
                unit.product_code,
                unit.quantity,
                unit.source_line_quantity
                    AS unit_source_line_quantity,
                unit.receiver_warehouse_address,
                unit.source_document_date,
                unit.external_document_id,
                unit.core_document_id,
                unit.raw_edo_document_id,
                unit.updated_at,

                source.id AS source_code_id,
                source.code_text AS source_code_text,
                source.source_gtin,
                source.code_kind AS source_code_kind,

                source.expansion_status
                    AS source_expansion_status,

                source.quantity_match_status
                    AS source_quantity_match_status,

                source.expected_unit_count
                    AS source_expected_unit_count,

                source.actual_unit_count
                    AS source_actual_unit_count,

                source.source_line_quantity
                    AS source_source_line_quantity,
                source.source_line_code_count,

                source.document_product_name
                    AS source_document_product_name,

                source.product_code
                    AS source_product_code,

                source.expansion_error
                    AS source_expansion_error,

                entity.id AS legal_entity_id,
                entity.short_name,
                entity.gis_mt_name,
                entity.inn

            FROM datamatrix_unit AS unit

            JOIN datamatrix_source_code AS source
              ON source.id = unit.source_code_id

            JOIN legal_entity AS entity
              ON entity.id = unit.legal_entity_id

            WHERE {where_sql}

            ORDER BY
                unit.source_document_date DESC,
                unit.id DESC

            LIMIT %s
            OFFSET %s
            """,
            tuple(
                parameters
                + [
                    page_size,
                    offset,
                ]
            ),
        )

        return [
            serialize_unit(dict(row))
            for row in cursor.fetchall()
        ]
    finally:
        cursor.close()


@datamatrix_storage_bp.get("/api/datamatrix-storage")
def get_datamatrix_storage():
    try:
        query = normalize_query(request.args.get("q"))
        entity_id = parse_entity_id(
            request.args.get("entity_id")
        )
        quantity_status = parse_quantity_status(
            request.args.get("quantity_status")
        )

        requested_page = parse_positive_integer(
            request.args.get("page"),
            field_name="page",
            default=1,
        )

        page_size = parse_positive_integer(
            request.args.get("page_size"),
            field_name="page_size",
            default=DEFAULT_PAGE_SIZE,
            maximum=MAX_PAGE_SIZE,
        )

        where_sql, parameters = build_filters(
            query=query,
            entity_id=entity_id,
            quantity_status=quantity_status,
        )

        with database_read() as connection:
            organizations = load_organizations(connection)
            summary = load_summary(
                connection,
                where_sql=where_sql,
                parameters=parameters,
                query=query,
                entity_id=entity_id,
                quantity_status=quantity_status,
            )

            total_count = summary["unit_count"]
            total_pages = max(
                1,
                math.ceil(total_count / page_size),
            )
            page = min(requested_page, total_pages)
            offset = (page - 1) * page_size

            items = load_units(
                connection,
                where_sql=where_sql,
                parameters=parameters,
                page_size=page_size,
                offset=offset,
            )

        first_item = offset + 1 if total_count > 0 else 0
        last_item = min(offset + len(items), total_count)

        return jsonify(
            {
                "items": items,
                "organizations": organizations,
                "summary": summary,
                "query": query or "",
                "entity_id": entity_id,
                "quantity_status": quantity_status or "ALL",
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": total_pages,
                    "first_item": first_item,
                    "last_item": last_item,
                    "has_previous": page > 1,
                    "has_next": page < total_pages,
                },
            }
        )

    except DatamatrixStorageApiError as exc:
        return jsonify({"error": str(exc)}), exc.status_code

    except mysql.connector.Error:
        return (
            jsonify(
                {
                    "error": (
                        "Не удалось получить данные "
                        "хранилища DataMatrix."
                    )
                }
            ),
            500,
        )