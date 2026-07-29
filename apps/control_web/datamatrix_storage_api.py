from __future__ import annotations

import math
import os
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


class DatamatrixStorageApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(
            message
        )

        self.status_code = status_code


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
    prepared = str(
        value or ""
    ).strip()

    if not prepared:
        return default

    try:
        result = int(
            prepared
        )

    except ValueError as exc:
        raise DatamatrixStorageApiError(
            f"Параметр {field_name} "
            "должен быть числом."
        ) from exc

    if result < 1:
        raise DatamatrixStorageApiError(
            f"Параметр {field_name} "
            "должен быть больше 0."
        )

    if (
        maximum is not None
        and result > maximum
    ):
        return maximum

    return result


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
        raise DatamatrixStorageApiError(
            "Для поиска введите "
            "не менее трёх символов."
        )

    if len(
        prepared
    ) > MAX_QUERY_LENGTH:
        raise DatamatrixStorageApiError(
            "Поисковая строка не должна "
            f"превышать {MAX_QUERY_LENGTH} "
            "символов."
        )

    return prepared


def parse_entity_id(
    value: str | None,
) -> int | None:
    prepared = str(
        value or ""
    ).strip()

    if not prepared:
        return None

    try:
        entity_id = int(
            prepared
        )

    except ValueError as exc:
        raise DatamatrixStorageApiError(
            "Некорректный идентификатор "
            "организации."
        ) from exc

    if entity_id < 1:
        raise DatamatrixStorageApiError(
            "Некорректный идентификатор "
            "организации."
        )

    return entity_id


def decimal_text(
    value: (
        Decimal
        | int
        | float
        | str
        | None
    ),
) -> str | None:
    if value is None:
        return None

    prepared = format(
        Decimal(
            str(
                value
            )
        ),
        "f",
    )

    if "." in prepared:
        prepared = prepared.rstrip(
            "0"
        ).rstrip(
            "."
        )

    return prepared or "0"


def datetime_iso(
    value: datetime | date | None,
) -> str | None:
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        if value.tzinfo is None:
            value = value.replace(
                tzinfo=timezone.utc
            )

        return value.isoformat()

    return value.isoformat()


def organization_name(
    row: dict[str, Any],
) -> str:
    return str(
        row.get(
            "gis_mt_name"
        )
        or row.get(
            "short_name"
        )
        or "Организация"
    )


def serialize_organization(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": int(
            row["id"]
        ),

        "name": organization_name(
            row
        ),

        "short_name": str(
            row.get(
                "short_name"
            )
            or ""
        ),

        "gis_mt_name": str(
            row.get(
                "gis_mt_name"
            )
            or ""
        ),

        "inn": str(
            row.get(
                "inn"
            )
            or ""
        ),

        "unit_count": int(
            row.get(
                "unit_count"
            )
            or 0
        ),
    }


def serialize_unit(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": int(
            row["id"]
        ),

        "code": str(
            row.get(
                "code_text"
            )
            or ""
        ),

        "product_name": str(
            row.get(
                "product_name"
            )
            or ""
        ),

        "product_code": str(
            row.get(
                "product_code"
            )
            or ""
        ),

        "quantity": decimal_text(
            row.get(
                "quantity"
            )
        ),

        "source_line_quantity": (
            decimal_text(
                row.get(
                    "source_line_quantity"
                )
            )
        ),

        "receiver_warehouse_address": str(
            row.get(
                "receiver_warehouse_address"
            )
            or ""
        ),

        "source_document_date": datetime_iso(
            row.get(
                "source_document_date"
            )
        ),

        "external_document_id": str(
            row.get(
                "external_document_id"
            )
            or ""
        ),

        "core_document_id": int(
            row[
                "core_document_id"
            ]
        ),

        "raw_edo_document_id": int(
            row[
                "raw_edo_document_id"
            ]
        ),

        "updated_at": datetime_iso(
            row.get(
                "updated_at"
            )
        ),

        "organization": {
            "id": int(
                row[
                    "legal_entity_id"
                ]
            ),

            "name": organization_name(
                row
            ),

            "short_name": str(
                row.get(
                    "short_name"
                )
                or ""
            ),

            "gis_mt_name": str(
                row.get(
                    "gis_mt_name"
                )
                or ""
            ),

            "inn": str(
                row.get(
                    "inn"
                )
                or ""
            ),
        },
    }


def load_organizations(
    connection: MySQLConnection,
) -> list[
    dict[str, Any]
]:
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

                COUNT(
                    unit.id
                ) AS unit_count

            FROM legal_entity AS entity

            JOIN datamatrix_unit AS unit
              ON unit.legal_entity_id =
                 entity.id

            GROUP BY
                entity.id,
                entity.short_name,
                entity.gis_mt_name,
                entity.inn

            ORDER BY
                COALESCE(
                    NULLIF(
                        entity.gis_mt_name,
                        ''
                    ),
                    entity.short_name
                ),
                entity.id
            """
        )

        return [
            serialize_organization(
                dict(
                    row
                )
            )
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()


def build_filters(
    *,
    query: str | None,
    entity_id: int | None,
) -> tuple[
    str,
    list[Any],
]:
    conditions = [
        "1 = 1",
    ]

    parameters: list[Any] = []

    if entity_id is not None:
        conditions.append(
            "unit.legal_entity_id = %s"
        )

        parameters.append(
            entity_id
        )

    if query is not None:
        pattern = (
            "%"
            + query
            + "%"
        )

        conditions.append(
            """
            (
                unit.code_text LIKE %s

                OR unit.product_name
                    LIKE %s

                OR unit.product_code
                    LIKE %s

                OR unit.receiver_warehouse_address
                    LIKE %s

                OR entity.short_name
                    LIKE %s

                OR entity.gis_mt_name
                    LIKE %s

                OR entity.inn
                    LIKE %s
            )
            """
        )

        parameters.extend(
            [
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
            ]
        )

    return (
        " AND ".join(
            conditions
        ),
        parameters,
    )


def count_units(
    connection: MySQLConnection,
    *,
    where_sql: str,
    parameters: list[Any],
) -> int:
    cursor = connection.cursor()

    try:
        cursor.execute(
            f"""
            SELECT
                COUNT(*)

            FROM datamatrix_unit AS unit

            JOIN legal_entity AS entity
              ON entity.id =
                 unit.legal_entity_id

            WHERE {where_sql}
            """,
            tuple(
                parameters
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    return int(
        row[0]
        if row is not None
        else 0
    )


def load_units(
    connection: MySQLConnection,
    *,
    where_sql: str,
    parameters: list[Any],
    page_size: int,
    offset: int,
) -> list[
    dict[str, Any]
]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            f"""
            SELECT
                unit.id,
                unit.code_text,
                unit.product_name,
                unit.product_code,
                unit.quantity,
                unit.source_line_quantity,

                unit.receiver_warehouse_address,
                unit.source_document_date,

                unit.external_document_id,
                unit.core_document_id,
                unit.raw_edo_document_id,
                unit.updated_at,

                entity.id
                    AS legal_entity_id,

                entity.short_name,
                entity.gis_mt_name,
                entity.inn

            FROM datamatrix_unit AS unit

            JOIN legal_entity AS entity
              ON entity.id =
                 unit.legal_entity_id

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
            serialize_unit(
                dict(
                    row
                )
            )
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()


@datamatrix_storage_bp.get(
    "/api/datamatrix-storage"
)
def get_datamatrix_storage():
    try:
        query = normalize_query(
            request.args.get(
                "q"
            )
        )

        entity_id = parse_entity_id(
            request.args.get(
                "entity_id"
            )
        )

        requested_page = (
            parse_positive_integer(
                request.args.get(
                    "page"
                ),
                field_name="page",
                default=1,
            )
        )

        page_size = (
            parse_positive_integer(
                request.args.get(
                    "page_size"
                ),
                field_name="page_size",
                default=DEFAULT_PAGE_SIZE,
                maximum=MAX_PAGE_SIZE,
            )
        )

        (
            where_sql,
            parameters,
        ) = build_filters(
            query=query,
            entity_id=entity_id,
        )

        with database_read() as connection:
            organizations = (
                load_organizations(
                    connection
                )
            )

            total_count = count_units(
                connection,
                where_sql=where_sql,
                parameters=parameters,
            )

            total_pages = max(
                1,
                math.ceil(
                    total_count
                    / page_size
                ),
            )

            page = min(
                requested_page,
                total_pages,
            )

            offset = (
                page - 1
            ) * page_size

            items = load_units(
                connection,
                where_sql=where_sql,
                parameters=parameters,
                page_size=page_size,
                offset=offset,
            )

        first_item = (
            offset + 1
            if total_count > 0
            else 0
        )

        last_item = min(
            offset
            + len(
                items
            ),
            total_count,
        )

        return jsonify(
            {
                "items": items,

                "organizations": (
                    organizations
                ),

                "query": query or "",

                "entity_id": (
                    entity_id
                ),

                "pagination": {
                    "page": page,

                    "page_size": (
                        page_size
                    ),

                    "total_count": (
                        total_count
                    ),

                    "total_pages": (
                        total_pages
                    ),

                    "first_item": (
                        first_item
                    ),

                    "last_item": (
                        last_item
                    ),

                    "has_previous": (
                        page > 1
                    ),

                    "has_next": (
                        page
                        < total_pages
                    ),
                },
            }
        )

    except DatamatrixStorageApiError as exc:
        return (
            jsonify(
                {
                    "error": str(
                        exc
                    )
                }
            ),
            exc.status_code,
        )

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