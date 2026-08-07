from __future__ import annotations

import calendar
import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify, request
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


MONTH_NAMES_RU = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]


def parse_dashboard_date(
    raw_value: str | None,
    fallback: date,
) -> date:
    value = (raw_value or "").strip()

    if not value:
        return fallback

    for date_format in (
        "%d.%m.%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(
                value,
                date_format,
            ).date()
        except ValueError:
            continue

    raise ValueError(
        "Дата должна быть в формате "
        "ДД.ММ.ГГГГ или ГГГГ-ММ-ДД."
    )


def resolve_dashboard_period() -> tuple[
    datetime,
    datetime,
    date,
    date,
]:
    fallback_from = PERIOD_FROM.date()
    fallback_to = (
        PERIOD_TO_EXCLUSIVE.date()
        - timedelta(days=1)
    )

    date_from = parse_dashboard_date(
        request.args.get("date_from"),
        fallback_from,
    )
    date_to = parse_dashboard_date(
        request.args.get("date_to"),
        fallback_to,
    )

    if date_to < date_from:
        raise ValueError(
            "Конец периода не может быть "
            "раньше начала периода."
        )

    if (date_to - date_from).days > 730:
        raise ValueError(
            "Период дашборда не должен "
            "превышать 731 день."
        )

    period_from = datetime.combine(
        date_from,
        time.min,
    )
    period_to_exclusive = datetime.combine(
        date_to + timedelta(days=1),
        time.min,
    )

    return (
        period_from,
        period_to_exclusive,
        date_from,
        date_to,
    )


def format_period_label(
    date_from: date,
    date_to: date,
) -> str:
    return (
        date_from.strftime("%d.%m.%Y")
        + " — "
        + date_to.strftime("%d.%m.%Y")
    )


def first_day_of_month(value: date) -> date:
    return value.replace(day=1)


def shift_month(
    value: date,
    amount: int,
) -> date:
    absolute_month = (
        value.year * 12
        + value.month
        - 1
        + amount
    )
    year, month_index = divmod(
        absolute_month,
        12,
    )
    return date(
        year,
        month_index + 1,
        1,
    )


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def month_payload(
    value: date,
    *,
    forecast: bool,
) -> dict[str, Any]:
    return {
        "key": month_key(value),
        "label": MONTH_NAMES_RU[value.month - 1],
        "forecast": forecast,
    }


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



def json_number(
    value: Any,
) -> int | float:
    if value is None:
        return 0

    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)

    prepared = float(value)

    if prepared.is_integer():
        return int(prepared)

    return prepared


def load_sales_summary(
    connection: MySQLConnection,
    period_from: datetime,
    period_to_exclusive: datetime,
) -> dict[str, Any]:
    period_from = period_from.date()
    period_to_exclusive = period_to_exclusive.date()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                COALESCE(
                    SUM(sold_quantity),
                    0
                ) AS correct_sales,
                COALESCE(
                    SUM(sold_amount),
                    0
                ) AS sales_amount,
                COUNT(*) AS detail_row_count

            FROM gis_mt_retail_sale_daily AS sale

            JOIN sales_export_run AS export_run
              ON export_run.id = sale.source_run_id
             AND export_run.status = 'COMPLETED'

            WHERE sale.sale_date >= %s
              AND sale.sale_date < %s
            """,
            (
                period_from,
                period_to_exclusive,
            ),
        )
        total_row = dict(cursor.fetchone() or {})

        cursor.execute(
            """
            SELECT
                COUNT(DISTINCT period_from)
                    AS loaded_day_count,
                MIN(period_from) AS first_loaded_date,
                MAX(period_from) AS last_loaded_date

            FROM sales_export_run

            WHERE period_from = period_to
              AND period_from >= %s
              AND period_from < %s
              AND status IN (
                  'COMPLETED',
                  'EMPTY'
              )
            """,
            (
                period_from,
                period_to_exclusive,
            ),
        )
        coverage_row = dict(cursor.fetchone() or {})

    finally:
        cursor.close()

    loaded_day_count = int(
        coverage_row.get("loaded_day_count") or 0
    )
    requested_day_count = (
        period_to_exclusive - period_from
    ).days
    correct_sales = json_number(
        total_row.get("correct_sales")
    )
    available = loaded_day_count > 0

    first_loaded = coverage_row.get(
        "first_loaded_date"
    )
    last_loaded = coverage_row.get(
        "last_loaded_date"
    )

    return {
        "title": "Продажи",
        "available": available,
        "total": correct_sales if available else None,
        "segments": [
            {
                "label": "Продажи без ошибок",
                "value": (
                    correct_sales
                    if available
                    else None
                ),
            }
        ],
        "source": "gis_mt_retail_sale_daily",
        "sales_amount": json_number(
            total_row.get("sales_amount")
        ),
        "detail_row_count": int(
            total_row.get("detail_row_count") or 0
        ),
        "coverage": {
            "requested_day_count": requested_day_count,
            "loaded_day_count": loaded_day_count,
            "complete": (
                loaded_day_count >= requested_day_count
            ),
            "first_loaded_date": (
                first_loaded.isoformat()
                if first_loaded is not None
                else None
            ),
            "last_loaded_date": (
                last_loaded.isoformat()
                if last_loaded is not None
                else None
            ),
        },
        "note": (
            None
            if available
            else (
                "За выбранный период ещё нет "
                "завершённых выгрузок корректных продаж."
            )
        ),
    }

def load_violation_summary(
    connection: MySQLConnection,
    period_from: datetime,
    period_to_exclusive: datetime,
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
                period_from,
                period_to_exclusive,
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
    period_from: datetime,
    period_to_exclusive: datetime,
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
                period_from,
                period_to_exclusive,
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
    trend_from: datetime,
    period_to_exclusive: datetime,
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
                trend_from,
                period_to_exclusive,
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
    *,
    selected_date_to: date,
) -> dict[
    str,
    Any,
]:
    selected_month = first_day_of_month(
        selected_date_to
    )

    actual_months = [
        shift_month(selected_month, -2),
        shift_month(selected_month, -1),
        selected_month,
    ]

    actual_violations = [
        int(
            monthly_violations.get(
                month_key(value),
                0,
            )
        )
        for value in actual_months
    ]

    current_days_elapsed = max(
        1,
        selected_date_to.day,
    )
    current_month_days = calendar.monthrange(
        selected_date_to.year,
        selected_date_to.month,
    )[1]

    violation_forecast = conservative_forecast(
        actual_violations,
        current_days_elapsed=current_days_elapsed,
        current_month_days=current_month_days,
    )

    actual_penalties: list[int] = []
    base_rates = [
        1_900,
        2_250,
        2_100,
    ]

    for index, value in enumerate(
        actual_violations
    ):
        previous_value = (
            actual_violations[index - 1]
            if index > 0
            else 0
        )

        actual_penalties.append(
            int(
                value * base_rates[index]
                + previous_value * 420
            )
        )

    penalty_forecast = conservative_forecast(
        actual_penalties,
        current_days_elapsed=current_days_elapsed,
        current_month_days=current_month_days,
    )

    forecast_months = [
        shift_month(selected_month, 1),
        shift_month(selected_month, 2),
    ]

    months = [
        *[
            month_payload(
                value,
                forecast=False,
            )
            for value in actual_months
        ],
        *[
            month_payload(
                value,
                forecast=True,
            )
            for value in forecast_months
        ],
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
                "Последний отображаемый "
                "месяц рассчитывается по "
                "данным до конца выбранного "
                "периода. Следующие два "
                "месяца являются прогнозом."
            ),
            "penalties_are_test": True,
        },
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
    try:
        (
            period_from,
            period_to_exclusive,
            date_from,
            date_to,
        ) = resolve_dashboard_period()
    except ValueError as exc:
        return (
            jsonify(
                {
                    "status": "ERROR",
                    "error": str(exc),
                }
            ),
            400,
        )

    selected_month = first_day_of_month(
        date_to
    )
    trend_from_date = shift_month(
        selected_month,
        -2,
    )
    trend_from = datetime.combine(
        trend_from_date,
        time.min,
    )

    with database_read() as connection:
        sales = load_sales_summary(
            connection,
            period_from,
            period_to_exclusive,
        )

        violations = load_violation_summary(
            connection,
            period_from,
            period_to_exclusive,
        )

        documents = load_document_summary(
            connection,
            period_from,
            period_to_exclusive,
        )

        monthly_violations = load_monthly_violations(
            connection,
            trend_from,
            period_to_exclusive,
        )

    payload = {
        "status": "OK",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "period": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "label": format_period_label(
                date_from,
                date_to,
            ),
            "locked": False,
        },
        "filters": {
            "trade_point": "Все ТТ",
            "organization": "Все организации",
        },
        "cards": {
            "sales": sales,
            "violations": violations,
            "documents": documents,
            "penalties": build_penalty_summary(),
        },
        "trend": build_trend(
            monthly_violations,
            selected_date_to=date_to,
        ),
        "table": {
            "title": "Программируемая таблица",
            "columns": [
                "Показатель",
                "Значение",
                "Статус",
                "Комментарий",
            ],
        },
    }

    return jsonify(payload)

