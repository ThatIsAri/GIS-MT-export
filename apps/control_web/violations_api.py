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


violations_bp = Blueprint(
    "violations",
    __name__,
)

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 250
MAX_QUERY_LENGTH = 200


EFFECTIVE_GTIN_SQL = """
COALESCE(
    NULLIF(violation.gtin, ''),
    CASE
        WHEN LOWER(LEFT(violation.code_text, 3)) = ']d2'
         AND SUBSTRING(violation.code_text, 4, 2) = '01'
         AND SUBSTRING(violation.code_text, 6, 14)
             REGEXP '^[0-9]{14}$'
            THEN SUBSTRING(violation.code_text, 6, 14)

        WHEN LEFT(violation.code_text, 4) = '(01)'
         AND SUBSTRING(violation.code_text, 5, 14)
             REGEXP '^[0-9]{14}$'
            THEN SUBSTRING(violation.code_text, 5, 14)

        WHEN LEFT(violation.code_text, 2) = '01'
         AND SUBSTRING(violation.code_text, 3, 14)
             REGEXP '^[0-9]{14}$'
            THEN SUBSTRING(violation.code_text, 3, 14)

        WHEN LEFT(violation.code_text, 14)
             REGEXP '^[0-9]{14}$'
            THEN LEFT(violation.code_text, 14)

        ELSE NULL
    END
)
"""


class ViolationsApiError(RuntimeError):
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
        raise ViolationsApiError(
            f"Параметр {field_name} должен быть числом."
        ) from exc

    if result < 1:
        raise ViolationsApiError(
            f"Параметр {field_name} должен быть больше 0."
        )

    if maximum is not None:
        return min(result, maximum)

    return result


def parse_optional_integer(
    value: str | None,
    *,
    field_name: str,
) -> int | None:
    prepared = str(value or "").strip()

    if not prepared:
        return None

    return parse_positive_integer(
        prepared,
        field_name=field_name,
        default=1,
    )


def normalize_query(value: str | None) -> str | None:
    prepared = " ".join(
        str(value or "").split()
    )

    if not prepared:
        return None

    if len(prepared) < 3:
        raise ViolationsApiError(
            "Для поиска введите не менее трёх символов."
        )

    if len(prepared) > MAX_QUERY_LENGTH:
        raise ViolationsApiError(
            "Поисковая строка не должна превышать "
            f"{MAX_QUERY_LENGTH} символов."
        )

    return prepared


def parse_date(
    value: str | None,
    *,
    field_name: str,
) -> date | None:
    prepared = str(value or "").strip()

    if not prepared:
        return None

    try:
        return date.fromisoformat(prepared)
    except ValueError as exc:
        raise ViolationsApiError(
            f"Параметр {field_name} содержит "
            "некорректную дату."
        ) from exc


def parse_nivellated(value: str | None) -> bool | None:
    prepared = str(value or "").strip().lower()

    if prepared in {"", "all"}:
        return None
    if prepared in {"yes", "true", "1"}:
        return True
    if prepared in {"no", "false", "0"}:
        return False

    raise ViolationsApiError(
        "Некорректный фильтр нивелирования."
    )


def datetime_iso(
    value: datetime | date | None,
) -> str | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(
                tzinfo=timezone.utc
            )
        return value.isoformat()

    return value.isoformat()


def decimal_text(value: Any) -> str | None:
    if value is None:
        return None

    prepared = format(
        Decimal(str(value)),
        "f",
    )

    if "." in prepared:
        prepared = prepared.rstrip("0").rstrip(".")

    return prepared or "0"


def organization_name(row: dict[str, Any]) -> str:
    return str(
        row.get("gis_mt_name")
        or row.get("short_name")
        or "Организация"
    )


def first_non_empty(*values: Any) -> str:
    for value in values:
        prepared = str(value or "").strip()

        if prepared:
            return prepared

    return ""


def product_match_source(row: dict[str, Any]) -> str:
    if first_non_empty(
        row.get("linked_product_name"),
        row.get("linked_product_code"),
    ):
        return "DATAMATRIX_LINK"

    if first_non_empty(
        row.get("code_product_name"),
        row.get("code_product_code"),
    ):
        return "CODE_HASH"

    if first_non_empty(
        row.get("gtin_product_name"),
        row.get("gtin_product_code"),
    ):
        return "GTIN"

    if first_non_empty(
        row.get("line_product_name"),
        row.get("line_product_code"),
    ):
        return "UPD_LINE"

    return "NOT_FOUND"


def build_filters() -> tuple[
    str,
    list[Any],
    dict[str, Any],
]:
    query = normalize_query(
        request.args.get("q")
    )
    entity_id = parse_optional_integer(
        request.args.get("entity_id"),
        field_name="entity_id",
    )
    period_from = parse_date(
        request.args.get("date_from"),
        field_name="date_from",
    )
    period_to = parse_date(
        request.args.get("date_to"),
        field_name="date_to",
    )
    nivellated = parse_nivellated(
        request.args.get("nivellated")
    )

    if (
        period_from is not None
        and period_to is not None
        and period_from > period_to
    ):
        raise ViolationsApiError(
            "Дата начала периода не может быть "
            "позже даты окончания."
        )

    conditions = ["1 = 1"]
    params: list[Any] = []

    if entity_id is not None:
        conditions.append(
            "violation.legal_entity_id = %s"
        )
        params.append(entity_id)

    if period_from is not None:
        conditions.append(
            "DATE(COALESCE(violation.operation_at, "
            "violation.registered_at)) >= %s"
        )
        params.append(period_from)

    if period_to is not None:
        conditions.append(
            "DATE(COALESCE(violation.operation_at, "
            "violation.registered_at)) <= %s"
        )
        params.append(period_to)

    if nivellated is not None:
        conditions.append(
            "violation.is_nivellated = %s"
        )
        params.append(int(nivellated))

    if query is not None:
        pattern = f"%{query}%"
        conditions.append(
            "("
            "violation.code_text LIKE %s "
            "OR violation.gtin LIKE %s "
            "OR violation.violation_kind LIKE %s "
            "OR violation.violation_result LIKE %s "
            "OR violation.location_address LIKE %s "
            "OR violation.document_number LIKE %s "
            "OR violation.kkt_registration_number LIKE %s "
            "OR violation.violation_number LIKE %s "
            "OR entity.inn LIKE %s "
            "OR entity.short_name LIKE %s "
            "OR entity.gis_mt_name LIKE %s "
            "OR linked_unit.product_name LIKE %s "
            "OR code_unit.product_name LIKE %s "
            "OR gtin_unit.product_name LIKE %s "
            "OR EXISTS ("
            "    SELECT 1 "
            "    FROM core_document_line AS search_line "
            "    JOIN legal_entity_document AS search_link "
            "      ON search_link.core_document_id = "
            "         search_line.core_document_id "
            "    WHERE search_link.legal_entity_id = "
            "          violation.legal_entity_id "
            "      AND search_line.product_name LIKE %s "
            "      AND search_line.product_code = "
            f"          {EFFECTIVE_GTIN_SQL}"
            ")"
            ")"
        )
        params.extend([pattern] * 15)


    return (
        " AND ".join(conditions),
        params,
        {
            "q": query,
            "entity_id": entity_id,
            "date_from": (
                period_from.isoformat()
                if period_from
                else None
            ),
            "date_to": (
                period_to.isoformat()
                if period_to
                else None
            ),
            "nivellated": nivellated,
        },
    )


@violations_bp.errorhandler(ViolationsApiError)
def handle_api_error(exc: ViolationsApiError):
    return jsonify(
        {
            "status": "ERROR",
            "error": str(exc),
        }
    ), exc.status_code


@violations_bp.get("/api/violations")
def get_violations():
    page = parse_positive_integer(
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

    where_sql, params, filters = build_filters()
    offset = (page - 1) * page_size

    with database_read() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total_count
                FROM gis_mt_violation AS violation
                JOIN legal_entity AS entity
                  ON entity.id = violation.legal_entity_id
                LEFT JOIN datamatrix_unit AS linked_unit
                  ON linked_unit.id = violation.datamatrix_unit_id
                LEFT JOIN datamatrix_unit AS code_unit
                  ON code_unit.code_sha256 = violation.code_sha256
                LEFT JOIN datamatrix_unit AS gtin_unit
                  ON gtin_unit.id = (
                      SELECT candidate.id
                      FROM datamatrix_unit AS candidate
                      WHERE candidate.legal_entity_id =
                            violation.legal_entity_id
                        AND candidate.gtin =
                            {EFFECTIVE_GTIN_SQL}
                        AND candidate.product_name IS NOT NULL
                        AND TRIM(candidate.product_name) <> ''
                      ORDER BY
                          candidate.source_document_date DESC,
                          candidate.id DESC
                      LIMIT 1
                  )
                WHERE {where_sql}
                """,
                tuple(params),
            )
            count_row = cursor.fetchone() or {}
            total_count = int(
                count_row.get("total_count") or 0
            )

            cursor.execute(
                f"""
                SELECT
                    violation.id,
                    violation.legal_entity_id,
                    violation.product_group,
                    violation.product_group_name,
                    violation.operation_at,
                    violation.registered_at,
                    violation.code_text,
                    violation.gtin,
                    violation.violation_kind,
                    violation.violation_result,
                    violation.location_address,
                    violation.fias_id,
                    violation.municipal_district,
                    violation.document_number,
                    violation.kkt_registration_number,
                    violation.fiscal_drive_number,
                    violation.violation_number,
                    violation.is_nivellated,
                    violation.permission_mode_result,
                    violation.withdrawal_volume,
                    violation.expansion_stage,

                    linked_unit.product_name
                        AS linked_product_name,
                    linked_unit.product_code
                        AS linked_product_code,

                    code_unit.product_name
                        AS code_product_name,
                    code_unit.product_code
                        AS code_product_code,

                    gtin_unit.product_name
                        AS gtin_product_name,
                    gtin_unit.product_code
                        AS gtin_product_code,

                    (
                        SELECT fallback_line.product_name
                        FROM core_document_line AS fallback_line
                        JOIN legal_entity_document AS fallback_link
                          ON fallback_link.core_document_id =
                             fallback_line.core_document_id
                        WHERE fallback_link.legal_entity_id =
                              violation.legal_entity_id
                          AND fallback_line.product_code =
                              {EFFECTIVE_GTIN_SQL}
                          AND fallback_line.product_name IS NOT NULL
                          AND TRIM(fallback_line.product_name) <> ''
                        ORDER BY
                            fallback_link.last_seen_at DESC,
                            fallback_line.id DESC
                        LIMIT 1
                    ) AS line_product_name,

                    (
                        SELECT fallback_line.product_code
                        FROM core_document_line AS fallback_line
                        JOIN legal_entity_document AS fallback_link
                          ON fallback_link.core_document_id =
                             fallback_line.core_document_id
                        WHERE fallback_link.legal_entity_id =
                              violation.legal_entity_id
                          AND fallback_line.product_code =
                              {EFFECTIVE_GTIN_SQL}
                        ORDER BY
                            fallback_link.last_seen_at DESC,
                            fallback_line.id DESC
                        LIMIT 1
                    ) AS line_product_code,

                    entity.inn,
                    entity.short_name,
                    entity.gis_mt_name

                FROM gis_mt_violation AS violation

                JOIN legal_entity AS entity
                  ON entity.id = violation.legal_entity_id

                LEFT JOIN datamatrix_unit AS linked_unit
                  ON linked_unit.id = violation.datamatrix_unit_id

                LEFT JOIN datamatrix_unit AS code_unit
                  ON code_unit.code_sha256 = violation.code_sha256

                LEFT JOIN datamatrix_unit AS gtin_unit
                  ON gtin_unit.id = (
                      SELECT candidate.id
                      FROM datamatrix_unit AS candidate
                      WHERE candidate.legal_entity_id =
                            violation.legal_entity_id
                        AND candidate.gtin =
                            {EFFECTIVE_GTIN_SQL}
                        AND candidate.product_name IS NOT NULL
                        AND TRIM(candidate.product_name) <> ''
                      ORDER BY
                          candidate.source_document_date DESC,
                          candidate.id DESC
                      LIMIT 1
                  )

                WHERE {where_sql}

                ORDER BY
                    COALESCE(
                        violation.operation_at,
                        violation.registered_at
                    ) DESC,
                    violation.id DESC

                LIMIT %s OFFSET %s
                """,
                tuple([
                    *params,
                    page_size,
                    offset,
                ]),
            )

            rows = list(cursor.fetchall())

            cursor.execute(
                """
                SELECT
                    entity.id,
                    entity.inn,
                    entity.short_name,
                    entity.gis_mt_name,
                    COUNT(violation.id) AS violation_count
                FROM legal_entity AS entity
                JOIN gis_mt_violation AS violation
                  ON violation.legal_entity_id = entity.id
                GROUP BY
                    entity.id,
                    entity.inn,
                    entity.short_name,
                    entity.gis_mt_name
                ORDER BY
                    COALESCE(
                        entity.gis_mt_name,
                        entity.short_name
                    ),
                    entity.id
                """
            )
            organization_rows = list(
                cursor.fetchall()
            )

        finally:
            cursor.close()

    total_pages = max(
        1,
        math.ceil(total_count / page_size),
    )

    items = []

    for row in rows:
        product_name = first_non_empty(
            row.get("linked_product_name"),
            row.get("code_product_name"),
            row.get("gtin_product_name"),
            row.get("line_product_name"),
        )

        product_code = first_non_empty(
            row.get("linked_product_code"),
            row.get("code_product_code"),
            row.get("gtin_product_code"),
            row.get("line_product_code"),
        )

        match_source = product_match_source(row)

        items.append(
            {
                "id": int(row["id"]),
                "operation_at": datetime_iso(
                    row.get("operation_at")
                ),
                "registered_at": datetime_iso(
                    row.get("registered_at")
                ),
                "organization": {
                    "id": int(
                        row["legal_entity_id"]
                    ),
                    "name": organization_name(row),
                    "inn": str(row.get("inn") or ""),
                },
                "product_group": str(
                    row.get("product_group") or ""
                ),
                "product_group_name": str(
                    row.get("product_group_name") or ""
                ),
                "product": {
                    "name": product_name,
                    "code": product_code,
                    "match_source": match_source,
                },
                "product_name": product_name,
                "product_code": product_code,
                "product_match_source": match_source,
                "code": str(
                    row.get("code_text") or ""
                ),
                "gtin": str(row.get("gtin") or ""),
                "violation_kind": str(
                    row.get("violation_kind") or ""
                ),
                "violation_result": str(
                    row.get("violation_result") or ""
                ),
                "location_address": str(
                    row.get("location_address") or ""
                ),
                "fias_id": str(
                    row.get("fias_id") or ""
                ),
                "municipal_district": str(
                    row.get("municipal_district") or ""
                ),
                "document_number": str(
                    row.get("document_number") or ""
                ),
                "kkt_registration_number": str(
                    row.get("kkt_registration_number")
                    or ""
                ),
                "fiscal_drive_number": str(
                    row.get("fiscal_drive_number")
                    or ""
                ),
                "violation_number": str(
                    row.get("violation_number") or ""
                ),
                "is_nivellated": (
                    bool(row["is_nivellated"])
                    if row.get("is_nivellated")
                    is not None
                    else None
                ),
                "permission_mode_result": str(
                    row.get("permission_mode_result")
                    or ""
                ),
                "withdrawal_volume": decimal_text(
                    row.get("withdrawal_volume")
                ),
                "expansion_stage": str(
                    row.get("expansion_stage") or ""
                ),
            }
        )

    organizations = [
        {
            "id": int(row["id"]),
            "name": organization_name(row),
            "inn": str(row.get("inn") or ""),
            "violation_count": int(
                row.get("violation_count") or 0
            ),
        }
        for row in organization_rows
    ]

    first_item = (
        offset + 1
        if total_count > 0
        else 0
    )
    last_item = min(
        offset + len(items),
        total_count,
    )

    return jsonify(
        {
            "status": "OK",
            "items": items,
            "organizations": organizations,
            "filters": filters,
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
