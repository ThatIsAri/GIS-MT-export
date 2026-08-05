from __future__ import annotations

import math
import os
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify, request
from mysql.connector import MySQLConnection


violations_bp = Blueprint(
    "violations",
    __name__,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_QUERY_LENGTH = 200
REFERENCE_CACHE_TTL_SECONDS = 600.0


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


def normalize_exact_filter(
    value: str | None,
    *,
    field_name: str,
    maximum: int = 1000,
) -> str | None:
    prepared = " ".join(
        str(value or "").split()
    )

    if not prepared:
        return None

    if len(prepared) > maximum:
        raise ViolationsApiError(
            f"Параметр {field_name} не должен превышать "
            f"{maximum} символов."
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


def optional_text(value: Any) -> str:
    return str(value or "").strip()


def organization_name(row: dict[str, Any]) -> str:
    return str(
        row.get("gis_mt_name")
        or row.get("short_name")
        or "Организация"
    )


def first_non_empty(*values: Any) -> str:
    for value in values:
        prepared = optional_text(value)

        if prepared:
            return prepared

    return ""


def extract_gtin(
    gtin: Any,
    code_text: Any,
) -> str:
    prepared_gtin = optional_text(gtin)

    if len(prepared_gtin) == 14 and prepared_gtin.isdigit():
        return prepared_gtin

    code = optional_text(code_text)

    candidates: list[str] = []

    if code[:3].lower() == "]d2" and code[3:5] == "01":
        candidates.append(code[5:19])

    if code.startswith("(01)"):
        candidates.append(code[4:18])

    if code.startswith("01"):
        candidates.append(code[2:16])

    candidates.append(code[:14])

    for candidate in candidates:
        if len(candidate) == 14 and candidate.isdigit():
            return candidate

    return ""


def direct_product_match(
    row: dict[str, Any],
) -> tuple[str, str, str]:
    linked_name = optional_text(
        row.get("linked_product_name")
    )
    linked_code = optional_text(
        row.get("linked_product_code")
    )

    if linked_name or linked_code:
        return (
            linked_name,
            linked_code,
            "DATAMATRIX_LINK",
        )

    code_name = optional_text(
        row.get("code_product_name")
    )
    code_product_code = optional_text(
        row.get("code_product_code")
    )

    if code_name or code_product_code:
        return (
            code_name,
            code_product_code,
            "CODE_HASH",
        )

    return "", "", "NOT_FOUND"


BASE_SEARCH_CONDITION_SQL = """
(
    violation.code_text LIKE %s
    OR violation.gtin LIKE %s
    OR violation.violation_kind LIKE %s
    OR violation.violation_result LIKE %s
    OR violation.product_group_name LIKE %s
    OR violation.location_address LIKE %s
    OR violation.document_number LIKE %s
    OR violation.kkt_registration_number LIKE %s
    OR violation.violation_number LIKE %s
    OR entity.inn LIKE %s
    OR entity.short_name LIKE %s
    OR entity.gis_mt_name LIKE %s
    OR linked_unit.product_name LIKE %s
    OR linked_unit.product_code LIKE %s
    OR code_unit.product_name LIKE %s
    OR code_unit.product_code LIKE %s
)
"""


_reference_cache_lock = threading.Lock()

_reference_cache: dict[str, Any] = {
    "expires_at": 0.0,
    "organizations": [],
    "violation_kinds": [],
}


def build_filters() -> tuple[
    str,
    list[Any],
    str | None,
    dict[str, Any],
]:
    query = normalize_query(
        request.args.get("q")
    )
    entity_id = parse_optional_integer(
        request.args.get("entity_id"),
        field_name="entity_id",
    )
    violation_kind = normalize_exact_filter(
        request.args.get("violation_kind"),
        field_name="violation_kind",
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

    if violation_kind is not None:
        conditions.append(
            "violation.violation_kind = %s"
        )
        params.append(violation_kind)

    if period_from is not None:
        conditions.append(
            "violation.event_at >= %s"
        )
        params.append(period_from)

    if period_to is not None:
        conditions.append(
            "violation.event_at < %s"
        )
        params.append(
            period_to + timedelta(days=1)
        )

    if nivellated is not None:
        conditions.append(
            "violation.is_nivellated = %s"
        )
        params.append(int(nivellated))

    return (
        " AND ".join(conditions),
        params,
        query,
        {
            "q": query,
            "entity_id": entity_id,
            "violation_kind": violation_kind,
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


def load_reference_data(
    connection: MySQLConnection,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    now = time.monotonic()

    with _reference_cache_lock:
        if now < float(
            _reference_cache["expires_at"]
        ):
            return (
                list(
                    _reference_cache["organizations"]
                ),
                list(
                    _reference_cache["violation_kinds"]
                ),
            )

        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    entity.id,
                    entity.inn,
                    entity.short_name,
                    entity.gis_mt_name
                FROM legal_entity AS entity
                WHERE entity.status <> 'DELETED'
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

            organization_rows = list(
                cursor.fetchall()
            )

            cursor.execute(
                """
                SELECT DISTINCT violation_kind
                FROM gis_mt_violation
                WHERE violation_kind IS NOT NULL
                  AND violation_kind <> ''
                ORDER BY violation_kind
                """
            )

            violation_kind_rows = list(
                cursor.fetchall()
            )
        finally:
            cursor.close()

        organizations = [
            {
                "id": int(row["id"]),
                "name": organization_name(row),
                "inn": optional_text(
                    row.get("inn")
                ),
            }
            for row in organization_rows
        ]

        violation_kinds = [
            {
                "name": optional_text(
                    row.get("violation_kind")
                ),
            }
            for row in violation_kind_rows
        ]

        _reference_cache.update(
            {
                "expires_at": (
                    now
                    + REFERENCE_CACHE_TTL_SECONDS
                ),
                "organizations": organizations,
                "violation_kinds": violation_kinds,
            }
        )

        return (
            list(organizations),
            list(violation_kinds),
        )


def fetch_page_rows(
    connection: MySQLConnection,
    *,
    where_sql: str,
    params: list[Any],
    query: str | None,
    page_size: int,
    offset: int,
) -> list[dict[str, Any]]:
    cursor = connection.cursor(
        dictionary=True
    )

    select_sql = """
        SELECT
            violation.id,
            violation.legal_entity_id,
            violation.product_group,
            violation.product_group_name,
            violation.operation_at,
            violation.registered_at,
            violation.code_text,
            violation.code_sha256,
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

            entity.inn,
            entity.short_name,
            entity.gis_mt_name,

            linked_unit.product_name
                AS linked_product_name,
            linked_unit.product_code
                AS linked_product_code,

            code_unit.product_name
                AS code_product_name,
            code_unit.product_code
                AS code_product_code

        FROM gis_mt_violation AS violation

        JOIN legal_entity AS entity
          ON entity.id =
             violation.legal_entity_id

        LEFT JOIN datamatrix_unit
            AS linked_unit
          ON linked_unit.id =
             violation.datamatrix_unit_id

        LEFT JOIN datamatrix_unit
            AS code_unit
          ON code_unit.code_sha256 =
             violation.code_sha256
    """

    query_params = list(params)
    query_condition = ""

    if query is not None:
        query_condition = (
            f" AND {BASE_SEARCH_CONDITION_SQL}"
        )
        query_params.extend(
            [f"%{query}%"] * 16
        )

    try:
        cursor.execute(
            f"""
            {select_sql}

            WHERE {where_sql}
            {query_condition}

            ORDER BY
                violation.event_at DESC,
                violation.id DESC

            LIMIT %s OFFSET %s
            """,
            tuple(
                [
                    *query_params,
                    page_size + 1,
                    offset,
                ]
            ),
        )

        return [
            dict(row)
            for row in cursor.fetchall()
        ]
    finally:
        cursor.close()


def load_entity_gtin_matches(
    connection: MySQLConnection,
    pairs: set[tuple[int, str]],
) -> dict[
    tuple[int, str],
    tuple[str, str],
]:
    if not pairs:
        return {}

    ordered_pairs = sorted(pairs)

    placeholders = ", ".join(
        ["(%s, %s)"] * len(ordered_pairs)
    )

    params: list[Any] = []

    for entity_id, gtin in ordered_pairs:
        params.extend(
            [
                entity_id,
                gtin,
            ]
        )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            f"""
            SELECT
                ranked.legal_entity_id,
                ranked.gtin,
                ranked.product_name,
                ranked.product_code
            FROM (
                SELECT
                    unit.legal_entity_id,
                    unit.gtin,
                    unit.product_name,
                    unit.product_code,

                    ROW_NUMBER() OVER (
                        PARTITION BY
                            unit.legal_entity_id,
                            unit.gtin
                        ORDER BY
                            unit.source_document_date DESC,
                            unit.id DESC
                    ) AS rn

                FROM datamatrix_unit AS unit

                WHERE (
                    unit.legal_entity_id,
                    unit.gtin
                ) IN ({placeholders})

                  AND (
                      unit.product_name IS NOT NULL
                      OR unit.product_code IS NOT NULL
                  )
            ) AS ranked

            WHERE ranked.rn = 1
            """,
            tuple(params),
        )

        return {
            (
                int(row["legal_entity_id"]),
                optional_text(
                    row.get("gtin")
                ),
            ): (
                optional_text(
                    row.get("product_name")
                ),
                optional_text(
                    row.get("product_code")
                ),
            )
            for row in cursor.fetchall()
        }
    finally:
        cursor.close()


def load_global_gtin_matches(
    connection: MySQLConnection,
    gtins: set[str],
) -> dict[
    str,
    tuple[str, str],
]:
    if not gtins:
        return {}

    ordered_gtins = sorted(gtins)

    placeholders = ", ".join(
        ["%s"] * len(ordered_gtins)
    )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            f"""
            SELECT
                ranked.gtin,
                ranked.product_name,
                ranked.product_code
            FROM (
                SELECT
                    unit.gtin,
                    unit.product_name,
                    unit.product_code,

                    ROW_NUMBER() OVER (
                        PARTITION BY unit.gtin
                        ORDER BY
                            unit.source_document_date DESC,
                            unit.id DESC
                    ) AS rn

                FROM datamatrix_unit AS unit

                WHERE unit.gtin
                      IN ({placeholders})

                  AND (
                      unit.product_name IS NOT NULL
                      OR unit.product_code IS NOT NULL
                  )
            ) AS ranked

            WHERE ranked.rn = 1
            """,
            tuple(ordered_gtins),
        )

        return {
            optional_text(
                row.get("gtin")
            ): (
                optional_text(
                    row.get("product_name")
                ),
                optional_text(
                    row.get("product_code")
                ),
            )
            for row in cursor.fetchall()
        }
    finally:
        cursor.close()


def resolve_page_products(
    connection: MySQLConnection,
    rows: list[dict[str, Any]],
) -> dict[
    int,
    tuple[str, str, str, str],
]:
    resolved: dict[
        int,
        tuple[str, str, str, str],
    ] = {}

    entity_pairs: set[
        tuple[int, str]
    ] = set()

    gtins: set[str] = set()

    for row in rows:
        row_id = int(row["id"])

        gtin = extract_gtin(
            row.get("gtin"),
            row.get("code_text"),
        )

        (
            name,
            product_code,
            source,
        ) = direct_product_match(row)

        if source != "NOT_FOUND":
            resolved[row_id] = (
                name,
                product_code,
                source,
                gtin,
            )
            continue

        if gtin:
            entity_pairs.add(
                (
                    int(
                        row["legal_entity_id"]
                    ),
                    gtin,
                )
            )

            gtins.add(gtin)

        resolved[row_id] = (
            "",
            "",
            "NOT_FOUND",
            gtin,
        )

    entity_matches = (
        load_entity_gtin_matches(
            connection,
            entity_pairs,
        )
    )

    unresolved_gtins: set[str] = set()

    for row in rows:
        row_id = int(row["id"])

        (
            name,
            product_code,
            source,
            gtin,
        ) = resolved[row_id]

        if (
            source != "NOT_FOUND"
            or not gtin
        ):
            continue

        entity_key = (
            int(row["legal_entity_id"]),
            gtin,
        )

        entity_match = (
            entity_matches.get(
                entity_key
            )
        )

        if entity_match is not None:
            resolved[row_id] = (
                entity_match[0],
                entity_match[1],
                "GTIN_ENTITY",
                gtin,
            )
        else:
            unresolved_gtins.add(gtin)

    global_matches = (
        load_global_gtin_matches(
            connection,
            unresolved_gtins,
        )
    )

    for row in rows:
        row_id = int(row["id"])

        (
            name,
            product_code,
            source,
            gtin,
        ) = resolved[row_id]

        if (
            source != "NOT_FOUND"
            or not gtin
        ):
            continue

        global_match = (
            global_matches.get(gtin)
        )

        if global_match is not None:
            resolved[row_id] = (
                global_match[0],
                global_match[1],
                "GTIN_GLOBAL",
                gtin,
            )

    return resolved


def serialize_violation(
    row: dict[str, Any],
    product: tuple[
        str,
        str,
        str,
        str,
    ],
) -> dict[str, Any]:
    (
        product_name,
        product_code,
        match_source,
        effective_gtin,
    ) = product

    return {
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
            "inn": optional_text(
                row.get("inn")
            ),
        },

        "product_group": optional_text(
            row.get("product_group")
        ),

        "product_group_name": optional_text(
            row.get("product_group_name")
        ),

        "product": {
            "name": product_name,
            "code": product_code,
            "match_source": match_source,
        },

        "product_name": product_name,
        "product_code": product_code,
        "product_match_source": match_source,

        "code": optional_text(
            row.get("code_text")
        ),

        "gtin": effective_gtin,

        "violation_kind": optional_text(
            row.get("violation_kind")
        ),

        "violation_result": optional_text(
            row.get("violation_result")
        ),

        "location_address": optional_text(
            row.get("location_address")
        ),

        "fias_id": optional_text(
            row.get("fias_id")
        ),

        "municipal_district": optional_text(
            row.get("municipal_district")
        ),

        "document_number": optional_text(
            row.get("document_number")
        ),

        "kkt_registration_number": optional_text(
            row.get(
                "kkt_registration_number"
            )
        ),

        "fiscal_drive_number": optional_text(
            row.get("fiscal_drive_number")
        ),

        "violation_number": optional_text(
            row.get("violation_number")
        ),

        "is_nivellated": (
            bool(row["is_nivellated"])
            if row.get("is_nivellated")
            is not None
            else None
        ),

        "permission_mode_result": optional_text(
            row.get(
                "permission_mode_result"
            )
        ),

        "withdrawal_volume": decimal_text(
            row.get("withdrawal_volume")
        ),

        "expansion_stage": optional_text(
            row.get("expansion_stage")
        ),
    }


@violations_bp.errorhandler(
    ViolationsApiError
)
def handle_api_error(
    exc: ViolationsApiError,
):
    return jsonify(
        {
            "status": "ERROR",
            "error": str(exc),
        }
    ), exc.status_code


@violations_bp.errorhandler(
    mysql.connector.Error
)
def handle_database_error(
    _exc: mysql.connector.Error,
):
    return jsonify(
        {
            "status": "ERROR",
            "error": (
                "Не удалось получить "
                "реестр отклонений."
            ),
        }
    ), 500


@violations_bp.get(
    "/api/violations"
)
def get_violations():
    started_at = time.perf_counter()

    requested_page = (
        parse_positive_integer(
            request.args.get("page"),
            field_name="page",
            default=1,
        )
    )

    page_size = parse_positive_integer(
        request.args.get("page_size"),
        field_name="page_size",
        default=DEFAULT_PAGE_SIZE,
        maximum=MAX_PAGE_SIZE,
    )

    (
        where_sql,
        params,
        query,
        filters,
    ) = build_filters()

    offset = (
        (requested_page - 1)
        * page_size
    )

    stage_started_at = (
        time.perf_counter()
    )

    with database_read() as connection:
        rows_with_sentinel = (
            fetch_page_rows(
                connection,
                where_sql=where_sql,
                params=params,
                query=query,
                page_size=page_size,
                offset=offset,
            )
        )

        page_query_ms = round(
            (
                time.perf_counter()
                - stage_started_at
            )
            * 1000,
            1,
        )

        has_next = (
            len(rows_with_sentinel)
            > page_size
        )

        rows = rows_with_sentinel[
            :page_size
        ]

        stage_started_at = (
            time.perf_counter()
        )

        product_map = (
            resolve_page_products(
                connection,
                rows,
            )
        )

        product_lookup_ms = round(
            (
                time.perf_counter()
                - stage_started_at
            )
            * 1000,
            1,
        )

        stage_started_at = (
            time.perf_counter()
        )

        (
            organizations,
            violation_kinds,
        ) = load_reference_data(
            connection
        )

        reference_ms = round(
            (
                time.perf_counter()
                - stage_started_at
            )
            * 1000,
            1,
        )

    items = [
        serialize_violation(
            row,
            product_map[
                int(row["id"])
            ],
        )
        for row in rows
    ]

    first_item = (
        offset + 1
        if items
        else 0
    )

    last_item = (
        offset + len(items)
    )

    elapsed_ms = round(
        (
            time.perf_counter()
            - started_at
        )
        * 1000,
        1,
    )

    payload = {
        "status": "OK",
        "items": items,
        "organizations": organizations,
        "violation_kinds": violation_kinds,
        "filters": filters,

        "pagination": {
            "page": requested_page,
            "page_size": page_size,
            "total_count": None,
            "total_pages": None,
            "first_item": first_item,
            "last_item": last_item,
            "has_previous": (
                requested_page > 1
            ),
            "has_next": has_next,
        },

        "performance": {
            "elapsed_ms": elapsed_ms,
            "page_query_ms": page_query_ms,
            "product_lookup_ms": (
                product_lookup_ms
            ),
            "reference_ms": reference_ms,
            "exact_count_skipped": True,
        },
    }

    response = jsonify(payload)

    response.headers["Server-Timing"] = (
        f"page;dur={page_query_ms}, "
        f"product;dur={product_lookup_ms}, "
        f"reference;dur={reference_ms}, "
        f"total;dur={elapsed_ms}"
    )

    response.headers["Cache-Control"] = (
        "no-store"
    )

    return response