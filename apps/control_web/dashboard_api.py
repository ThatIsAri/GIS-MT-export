from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify
from mysql.connector import MySQLConnection


analytics_dashboard_bp = Blueprint(
    "analytics_dashboard",
    __name__,
)

PERIOD_FROM = datetime(
    2026,
    7,
    1,
    0,
    0,
    0,
)

PERIOD_TO_EXCLUSIVE = datetime(
    2026,
    8,
    5,
    0,
    0,
    0,
)

TREND_FROM = datetime(
    2026,
    6,
    1,
    0,
    0,
    0,
)

PERIOD_LABEL = (
    "01.07.2026 — 04.08.2026"
)

PENALTY_TEST_EXACT = 185_000
PENALTY_TEST_POSSIBLE = 420_000

SIGNED_DOCUMENT_PATTERN = (
    "SIGNED|"
    "ACCEPTED|"
    "COMPLETED|"
    "PROCESSED|"
    "SUCCESS"
)

DOCUMENT_ERROR_SQL = """
(
    UPPER(
        COALESCE(
            normalization_status,
            ''
        )
    ) IN (
        'ERROR',
        'FAILED',
        'CONFLICT'
    )

    OR COALESCE(
        JSON_LENGTH(
            errors_json
        ),
        0
    ) > 0
)
"""


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
            collation=(
                "utf8mb4_0900_ai_ci"
            ),
        )

        yield connection

    finally:
        connection.close()


def compact_segments(
    rows: list[
        dict[
            str,
            Any,
        ]
    ],
    *,
    maximum: int = 7,
) -> list[
    dict[
        str,
        Any,
    ]
]:
    segments = [
        {
            "label": str(
                row.get(
                    "segment_name"
                )
                or "Не определено"
            ),
            "value": int(
                row.get(
                    "segment_count"
                )
                or 0
            ),
        }
        for row in rows
    ]

    if len(segments) <= maximum:
        return segments

    visible = segments[
        :maximum
    ]

    other_count = sum(
        item["value"]
        for item
        in segments[maximum:]
    )

    if other_count:
        visible.append(
            {
                "label": "Прочие",
                "value": (
                    other_count
                ),
            }
        )

    return visible


def load_violation_summary(
    connection: MySQLConnection,
) -> dict[
    str,
    Any,
]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                COALESCE(
                    NULLIF(
                        TRIM(
                            violation_kind
                        ),
                        ''
                    ),
                    'Не определено'
                ) AS segment_name,

                COUNT(*) AS segment_count

            FROM gis_mt_violation

            WHERE event_at >= %s
              AND event_at < %s

            GROUP BY
                segment_name

            ORDER BY
                segment_count DESC,
                segment_name
            """,
            (
                PERIOD_FROM,
                PERIOD_TO_EXCLUSIVE,
            ),
        )

        rows = [
            dict(row)
            for row
            in cursor.fetchall()
        ]

    finally:
        cursor.close()

    segments = compact_segments(
        rows
    )

    total = sum(
        item["value"]
        for item in segments
    )

    return {
        "title": "Отклонения",
        "total": total,
        "segments": segments,
        "source": (
            "gis_mt_violation"
        ),
    }


def load_document_summary(
    connection: MySQLConnection,
) -> dict[
    str,
    Any,
]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total_count,

                SUM(
                    CASE
                        WHEN
                            {DOCUMENT_ERROR_SQL}
                        THEN 1
                        ELSE 0
                    END
                ) AS error_count,

                SUM(
                    CASE
                        WHEN NOT
                            {DOCUMENT_ERROR_SQL}

                         AND UPPER(
                            COALESCE(
                                document_status,
                                ''
                            )
                         ) REGEXP %s

                        THEN 1
                        ELSE 0
                    END
                ) AS signed_count

            FROM core_document

            WHERE COALESCE(
                doc_date,
                invoice_date,
                received_at,
                first_seen_at
            ) >= %s

              AND COALESCE(
                doc_date,
                invoice_date,
                received_at,
                first_seen_at
            ) < %s
            """,
            (
                SIGNED_DOCUMENT_PATTERN,
                PERIOD_FROM,
                PERIOD_TO_EXCLUSIVE,
            ),
        )

        row = dict(
            cursor.fetchone()
            or {}
        )

    finally:
        cursor.close()

    total = int(
        row.get(
            "total_count"
        )
        or 0
    )

    signed = int(
        row.get(
            "signed_count"
        )
        or 0
    )

    error = int(
        row.get(
            "error_count"
        )
        or 0
    )

    waiting = max(
        0,
        total
        - signed
        - error,
    )

    return {
        "title": "Документы",
        "total": total,
        "segments": [
            {
                "label": (
                    "Подписаны"
                ),
                "value": signed,
            },
            {
                "label": (
                    "Ожидают "
                    "подписания"
                ),
                "value": waiting,
            },
            {
                "label": (
                    "Ошибка обработки "
                    "ГИС МТ"
                ),
                "value": error,
            },
        ],
        "source": (
            "core_document"
        ),
    }


def load_monthly_violations(
    connection: MySQLConnection,
) -> dict[
    str,
    int,
]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                DATE_FORMAT(
                    event_at,
                    '%Y-%m'
                ) AS month_key,

                COUNT(*) AS item_count

            FROM gis_mt_violation

            WHERE event_at >= %s
              AND event_at < %s

            GROUP BY
                month_key

            ORDER BY
                month_key
            """,
            (
                TREND_FROM,
                PERIOD_TO_EXCLUSIVE,
            ),
        )

        return {
            str(
                row[
                    "month_key"
                ]
            ): int(
                row.get(
                    "item_count"
                )
                or 0
            )
            for row
            in cursor.fetchall()
        }

    finally:
        cursor.close()


def conservative_forecast(
    actual_values: list[int],
    *,
    current_days_elapsed: int,
    current_month_days: int,
) -> tuple[
    int,
    int,
]:
    if not actual_values:
        return 0, 0

    complete_values = (
        actual_values[:-1]
    )

    current_value = max(
        0,
        actual_values[-1],
    )

    projected_current = (
        current_value
        * current_month_days
        / max(
            1,
            current_days_elapsed,
        )
    )

    positive_complete = [
        value
        for value
        in complete_values
        if value > 0
    ]

    baseline = float(
        median(
            positive_complete
        )
        if positive_complete
        else projected_current
    )

    if baseline > 0:
        projected_current = min(
            max(
                projected_current,
                baseline * 0.65,
            ),
            baseline * 1.55,
        )

    last_complete = float(
        complete_values[-1]
        if complete_values
        else projected_current
    )

    raw_trend = 0.0

    if len(
        complete_values
    ) >= 2:
        raw_trend = float(
            complete_values[-1]
            - complete_values[-2]
        )

    stabilized_trend = (
        raw_trend
        * 0.25
    )

    first = round(
        max(
            0.0,

            baseline * 0.50

            + projected_current
            * 0.30

            + max(
                0.0,
                (
                    last_complete
                    + stabilized_trend
                ),
            ) * 0.20,
        )
    )

    second = round(
        max(
            0.0,

            baseline * 0.55

            + first * 0.30

            + max(
                0.0,
                (
                    first
                    + stabilized_trend
                    * 0.5
                ),
            ) * 0.15,
        )
    )

    return (
        int(first),
        int(second),
    )


def build_trend(
    monthly_violations: dict[
        str,
        int,
    ],
) -> dict[
    str,
    Any,
]:
    month_keys = [
        "2026-06",
        "2026-07",
        "2026-08",
    ]

    actual_violations = [
        int(
            monthly_violations.get(
                key,
                0,
            )
        )
        for key
        in month_keys
    ]

    violation_forecast = (
        conservative_forecast(
            actual_violations,
            current_days_elapsed=4,
            current_month_days=31,
        )
    )

    actual_penalties: list[
        int
    ] = []

    for index, value in enumerate(
        actual_violations
    ):
        previous_value = (
            actual_violations[
                index - 1
            ]
            if index > 0
            else 0
        )

        base_rate = [
            1_900,
            2_250,
            2_100,
        ][index]

        actual_penalties.append(
            int(
                value
                * base_rate

                + previous_value
                * 420
            )
        )

    penalty_forecast = (
        conservative_forecast(
            actual_penalties,
            current_days_elapsed=4,
            current_month_days=31,
        )
    )

    months = [
        {
            "key": "2026-06",
            "label": "Июнь",
            "forecast": False,
        },
        {
            "key": "2026-07",
            "label": "Июль",
            "forecast": False,
        },
        {
            "key": "2026-08",
            "label": "Август",
            "forecast": False,
        },
        {
            "key": "2026-09",
            "label": "Сентябрь",
            "forecast": True,
        },
        {
            "key": "2026-10",
            "label": "Октябрь",
            "forecast": True,
        },
    ]

    return {
        "months": months,

        "forecast_start_index": 3,

        "violations": [
            *actual_violations,
            *violation_forecast,
        ],

        "penalties": [
            *actual_penalties,
            *penalty_forecast,
        ],

        "model": {
            "name": (
                "Консервативный "
                "стабилизированный "
                "прогноз"
            ),

            "description": (
                "Текущий неполный месяц "
                "приводится к месячному "
                "темпу, но ограничивается "
                "историческим диапазоном. "
                "Кратковременное резкое "
                "снижение не переносится "
                "на следующий месяц "
                "без сглаживания."
            ),

            "penalties_are_test": (
                True
            ),
        },
    }


def build_sales_summary(
    violation_total: int,
) -> dict[
    str,
    Any,
]:
    return {
        "title": "Продажи",

        "available": False,

        "total": None,

        "segments": [
            {
                "label": (
                    "Продажи "
                    "без ошибок"
                ),
                "value": None,
            },
            {
                "label": (
                    "Продажи "
                    "с ошибками"
                ),
                "value": (
                    violation_total
                ),
            },
        ],

        "note": (
            "В текущей схеме БД "
            "отсутствует реестр всех "
            "продаж. Поэтому "
            "безошибочные продажи пока "
            "не вычисляются, а второе "
            "значение основано на "
            "количестве записей об "
            "отклонениях ГИС МТ."
        ),
    }


def build_penalty_summary() -> dict[
    str,
    Any,
]:
    return {
        "title": "Штрафы",

        "total": (
            PENALTY_TEST_EXACT
            + PENALTY_TEST_POSSIBLE
        ),

        "segments": [
            {
                "label": (
                    "Точно будут "
                    "начислены"
                ),
                "value": (
                    PENALTY_TEST_EXACT
                ),
            },
            {
                "label": (
                    "Возможные"
                ),
                "value": (
                    PENALTY_TEST_POSSIBLE
                ),
            },
        ],

        "is_test": True,

        "note": (
            "Тестовые значения "
            "без источника начислений."
        ),
    }


@analytics_dashboard_bp.errorhandler(
    mysql.connector.Error
)
def handle_database_error(
    _exc: mysql.connector.Error,
):
    return (
        jsonify(
            {
                "status": "ERROR",

                "error": (
                    "Не удалось получить "
                    "данные аналитического "
                    "дашборда."
                ),
            }
        ),
        500,
    )


@analytics_dashboard_bp.get(
    "/api/analytics-dashboard"
)
def get_analytics_dashboard():
    with database_read() as connection:
        violations = (
            load_violation_summary(
                connection
            )
        )

        documents = (
            load_document_summary(
                connection
            )
        )

        monthly_violations = (
            load_monthly_violations(
                connection
            )
        )

    payload = {
        "status": "OK",

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),

        "period": {
            "date_from": (
                "2026-07-01"
            ),
            "date_to": (
                "2026-08-04"
            ),
            "label": PERIOD_LABEL,
            "locked": True,
        },

        "filters": {
            "trade_point": (
                "Все ТТ"
            ),
            "organization": (
                "Все организации"
            ),
        },

        "cards": {
            "sales": (
                build_sales_summary(
                    int(
                        violations[
                            "total"
                        ]
                    )
                )
            ),

            "violations": (
                violations
            ),

            "documents": (
                documents
            ),

            "penalties": (
                build_penalty_summary()
            ),
        },

        "trend": build_trend(
            monthly_violations
        ),

        "table": {
            "title": (
                "Программируемая "
                "таблица"
            ),

            "columns": [
                "Показатель",
                "Значение",
                "Статус",
                "Комментарий",
            ],
        },
    }

    response = jsonify(
        payload
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response