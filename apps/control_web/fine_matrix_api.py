from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify, request
from mysql.connector import MySQLConnection


fine_matrix_bp = Blueprint(
    "fine_matrix",
    __name__,
)


MAX_AMOUNT = Decimal(
    "9999999999999.99"
)


class FineMatrixApiError(
    RuntimeError
):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        field: str | None = None,
    ) -> None:
        super().__init__(
            message
        )

        self.status_code = (
            status_code
        )

        self.field = field


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
        "collation": "utf8mb4_0900_ai_ci",
        "use_unicode": True,
        "connection_timeout": 10,
        "autocommit": False,
    }


@contextmanager
def database_read() -> Iterator[
    MySQLConnection
]:
    connection = mysql.connector.connect(
        **database_settings()
    )

    try:
        yield connection

    finally:
        connection.close()


@contextmanager
def database_transaction() -> Iterator[
    MySQLConnection
]:
    connection = mysql.connector.connect(
        **database_settings()
    )

    try:
        connection.start_transaction()

        yield connection

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def request_payload() -> dict[
    str,
    Any,
]:
    value = request.get_json(
        silent=True
    )

    if not isinstance(
        value,
        dict,
    ):
        raise FineMatrixApiError(
            "Тело запроса должно быть "
            "JSON-объектом."
        )

    return value


def parse_positive_id(
    value: Any,
    field: str,
) -> int:
    try:
        prepared = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise FineMatrixApiError(
            "Некорректный идентификатор "
            "строки матрицы.",
            field=field,
        ) from exc

    if prepared < 1:
        raise FineMatrixApiError(
            "Идентификатор строки должен "
            "быть больше нуля.",
            field=field,
        )

    return prepared


def parse_amount(
    value: Any,
    field: str,
) -> Decimal:
    if isinstance(
        value,
        bool,
    ):
        raise FineMatrixApiError(
            "Сумма штрафа должна быть числом.",
            field=field,
        )

    prepared_text = (
        str(
            value
            if value is not None
            else ""
        )
        .strip()
        .replace(
            " ",
            "",
        )
        .replace(
            "\u00a0",
            "",
        )
        .replace(
            ",",
            ".",
        )
    )

    if not prepared_text:
        raise FineMatrixApiError(
            "Сумма штрафа не заполнена.",
            field=field,
        )

    try:
        prepared = Decimal(
            prepared_text
        ).quantize(
            Decimal(
                "0.01"
            )
        )

    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise FineMatrixApiError(
            "Сумма штрафа должна быть "
            "корректным числом.",
            field=field,
        ) from exc

    if prepared < 0:
        raise FineMatrixApiError(
            "Сумма штрафа не может "
            "быть отрицательной.",
            field=field,
        )

    if prepared > MAX_AMOUNT:
        raise FineMatrixApiError(
            "Сумма штрафа превышает "
            "допустимое значение.",
            field=field,
        )

    return prepared


def decimal_text(
    value: Any,
) -> str:
    if value is None:
        return "0"

    prepared = Decimal(
        str(
            value
        )
    )

    return format(
        prepared,
        ".2f",
    )


def iso_value(
    value: Any,
) -> str | None:
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        prepared = value

        if prepared.tzinfo is None:
            prepared = prepared.replace(
                tzinfo=timezone.utc
            )

        return prepared.isoformat()

    if isinstance(
        value,
        date,
    ):
        return value.isoformat()

    return str(
        value
    )


def serialize_rule(
    row: dict[
        str,
        Any,
    ],
) -> dict[
    str,
    Any,
]:
    return {
        "id": int(
            row[
                "id"
            ]
        ),

        "rule_code": str(
            row[
                "rule_code"
            ]
        ),

        "violation_name": str(
            row[
                "violation_name"
            ]
        ),

        "product_scope": str(
            row.get(
                "product_scope"
            )
            or ""
        ),

        "calculation_mode": str(
            row[
                "calculation_mode"
            ]
        ),

        "aggregation_scope": str(
            row[
                "aggregation_scope"
            ]
        ),

        "quantity_from": (
            int(
                row[
                    "quantity_from"
                ]
            )
            if row.get(
                "quantity_from"
            )
            is not None
            else None
        ),

        "quantity_to": (
            int(
                row[
                    "quantity_to"
                ]
            )
            if row.get(
                "quantity_to"
            )
            is not None
            else None
        ),

        "individual_entrepreneur_amount": (
            decimal_text(
                row[
                    "individual_entrepreneur_amount"
                ]
            )
        ),

        "legal_entity_amount": (
            decimal_text(
                row[
                    "legal_entity_amount"
                ]
            )
        ),

        "statutory_default_individual_amount": (
            decimal_text(
                row[
                    "statutory_default_individual_amount"
                ]
            )
        ),

        "statutory_default_legal_amount": (
            decimal_text(
                row[
                    "statutory_default_legal_amount"
                ]
            )
        ),

        "effective_from": iso_value(
            row[
                "effective_from"
            ]
        ),

        "legal_basis": str(
            row[
                "legal_basis"
            ]
        ),

        "calculation_note": str(
            row.get(
                "calculation_note"
            )
            or ""
        ),

        "sort_order": int(
            row[
                "sort_order"
            ]
        ),

        "is_active": bool(
            row[
                "is_active"
            ]
        ),

        "updated_at": iso_value(
            row[
                "updated_at"
            ]
        ),
    }


def load_rules(
    connection: MySQLConnection,
) -> list[
    dict[
        str,
        Any,
    ]
]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                id,
                rule_code,
                violation_name,
                product_scope,
                calculation_mode,
                aggregation_scope,
                quantity_from,
                quantity_to,
                individual_entrepreneur_amount,
                legal_entity_amount,
                statutory_default_individual_amount,
                statutory_default_legal_amount,
                effective_from,
                legal_basis,
                calculation_note,
                sort_order,
                is_active,
                updated_at

            FROM fine_matrix_rule

            WHERE is_active = 1

            ORDER BY
                sort_order,
                id
            """
        )

        return [
            serialize_rule(
                dict(
                    row
                )
            )
            for row
            in cursor.fetchall()
        ]

    finally:
        cursor.close()


def matrix_response(
    connection: MySQLConnection,
):
    items = load_rules(
        connection
    )

    return jsonify(
        {
            "items": items,

            "columns": [
                {
                    "code": (
                        "INDIVIDUAL_ENTREPRENEUR"
                    ),

                    "title": "ИП",
                },
                {
                    "code": (
                        "LEGAL_ENTITY"
                    ),

                    "title": "Юрлицо",
                },
            ],

            "effective_from": (
                min(
                    (
                        item[
                            "effective_from"
                        ]
                        for item
                        in items
                        if item[
                            "effective_from"
                        ]
                    ),
                    default=None,
                )
            ),

            "legal_document": (
                "Федеральный закон "
                "от 02.05.2026 № 120-ФЗ"
            ),
        }
    )


@fine_matrix_bp.errorhandler(
    FineMatrixApiError
)
def handle_api_error(
    exc: FineMatrixApiError,
):
    payload: dict[
        str,
        Any,
    ] = {
        "error": str(
            exc
        ),
    }

    if exc.field:
        payload[
            "field"
        ] = exc.field

    return (
        jsonify(
            payload
        ),
        exc.status_code,
    )


@fine_matrix_bp.get(
    "/api/fine-matrix"
)
def get_fine_matrix():
    with database_read() as connection:
        return matrix_response(
            connection
        )


@fine_matrix_bp.put(
    "/api/fine-matrix"
)
def update_fine_matrix():
    payload = request_payload()

    raw_items = payload.get(
        "items"
    )

    if not isinstance(
        raw_items,
        list,
    ):
        raise FineMatrixApiError(
            "Поле items должно быть массивом.",
            field="items",
        )

    if not raw_items:
        raise FineMatrixApiError(
            "Не переданы строки матрицы.",
            field="items",
        )

    if len(
        raw_items
    ) > 100:
        raise FineMatrixApiError(
            "Передано слишком много "
            "строк матрицы.",
            field="items",
        )

    prepared_items: list[
        tuple[
            int,
            Decimal,
            Decimal,
        ]
    ] = []

    used_ids: set[
        int
    ] = set()

    for index, raw_item in enumerate(
        raw_items
    ):
        if not isinstance(
            raw_item,
            dict,
        ):
            raise FineMatrixApiError(
                "Каждая строка матрицы "
                "должна быть объектом.",
                field=(
                    f"items.{index}"
                ),
            )

        rule_id = parse_positive_id(
            raw_item.get(
                "id"
            ),
            field=(
                f"items.{index}.id"
            ),
        )

        if rule_id in used_ids:
            raise FineMatrixApiError(
                "Одна строка матрицы "
                "передана несколько раз.",
                field=(
                    f"items.{index}.id"
                ),
            )

        used_ids.add(
            rule_id
        )

        individual_amount = parse_amount(
            raw_item.get(
                "individual_entrepreneur_amount"
            ),
            field=(
                f"items.{index}."
                "individual_entrepreneur_amount"
            ),
        )

        legal_amount = parse_amount(
            raw_item.get(
                "legal_entity_amount"
            ),
            field=(
                f"items.{index}."
                "legal_entity_amount"
            ),
        )

        prepared_items.append(
            (
                rule_id,
                individual_amount,
                legal_amount,
            )
        )

    with database_transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            placeholders = ",".join(
                [
                    "%s"
                ]
                * len(
                    prepared_items
                )
            )

            cursor.execute(
                f"""
                SELECT
                    id

                FROM fine_matrix_rule

                WHERE id IN (
                    {placeholders}
                )

                  AND is_active = 1

                FOR UPDATE
                """,
                tuple(
                    item[0]
                    for item
                    in prepared_items
                ),
            )

            existing_ids = {
                int(
                    row[
                        "id"
                    ]
                )
                for row
                in cursor.fetchall()
            }

            missing_ids = (
                used_ids
                - existing_ids
            )

            if missing_ids:
                raise FineMatrixApiError(
                    "Не найдены строки матрицы: "
                    + ", ".join(
                        str(
                            value
                        )
                        for value
                        in sorted(
                            missing_ids
                        )
                    ),
                    status_code=404,
                )

            for (
                rule_id,
                individual_amount,
                legal_amount,
            ) in prepared_items:
                cursor.execute(
                    """
                    UPDATE fine_matrix_rule

                       SET individual_entrepreneur_amount = %s,
                           legal_entity_amount = %s,
                           updated_at =
                               UTC_TIMESTAMP(6)

                     WHERE id = %s
                       AND is_active = 1
                    """,
                    (
                        individual_amount,
                        legal_amount,
                        rule_id,
                    ),
                )

        finally:
            cursor.close()

    with database_read() as connection:
        return matrix_response(
            connection
        )


@fine_matrix_bp.post(
    "/api/fine-matrix/reset"
)
def reset_fine_matrix():
    with database_transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE fine_matrix_rule

                   SET individual_entrepreneur_amount =
                           statutory_default_individual_amount,

                       legal_entity_amount =
                           statutory_default_legal_amount,

                       updated_at =
                           UTC_TIMESTAMP(6)

                 WHERE is_active = 1
                """
            )

        finally:
            cursor.close()

    with database_read() as connection:
        return matrix_response(
            connection
        )