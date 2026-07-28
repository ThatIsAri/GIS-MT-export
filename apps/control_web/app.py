from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

import mysql.connector
from flask import Flask, jsonify, render_template
from mysql.connector import MySQLConnection


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


def required_env(
    name: str,
) -> str:
    value = os.getenv(
        name,
        "",
    ).strip()

    if not value:
        raise RuntimeError(
            f"Environment variable {name} is required."
        )

    return value


def db_settings() -> dict[str, Any]:
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
def db_read() -> Iterator[
    MySQLConnection
]:
    connection = mysql.connector.connect(
        **db_settings()
    )

    try:
        yield connection

    finally:
        connection.close()


def looks_like_utf8_mojibake(
    value: str,
) -> bool:
    if not value:
        return False

    markers = (
        "Ð",
        "Ñ",
        "Ã",
        "Â",
        "ð",
        "ñ",
    )

    count = sum(
        value.count(marker)
        for marker in markers
    )

    return count >= 2


def try_repair_mojibake(
    value: str,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        return value

    if not looks_like_utf8_mojibake(
        value
    ):
        return value

    for source_encoding in (
        "latin1",
        "cp1252",
    ):
        try:
            repaired = (
                value
                .encode(source_encoding)
                .decode("utf-8")
            )

            if repaired and not looks_like_utf8_mojibake(
                repaired
            ):
                return repaired

        except (
            UnicodeEncodeError,
            UnicodeDecodeError,
        ):
            continue

    return value


def json_value(
    value: Any,
) -> Any:
    if isinstance(
        value,
        datetime,
    ):
        return value.replace(
            tzinfo=timezone.utc
        ).isoformat()

    if isinstance(
        value,
        date,
    ):
        return value.isoformat()

    if isinstance(
        value,
        str,
    ):
        return try_repair_mojibake(
            value
        )

    return value


def rows_to_json(
    rows: list[
        dict[str, Any]
    ],
) -> list[
    dict[str, Any]
]:
    return [
        {
            key: json_value(
                value
            )
            for key, value
            in row.items()
        }
        for row in rows
    ]


def dashboard_data() -> dict[str, Any]:
    with db_read() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    e.id,
                    e.inn,
                    e.short_name,
                    e.gis_mt_name,
                    e.status,
                    e.storage_slug,
                    e.gis_mt_last_sync_status,
                    e.gis_mt_last_sync_at,
                    config.true_api_enabled,

                    COUNT(
                        DISTINCT certificate.id
                    ) AS certificate_count,

                    MAX(
                        certificate.valid_to
                    ) AS certificate_valid_to,


                    MAX(
                        auth_job.status
                    ) AS active_auth_status,

                    MAX(
                        sync_job.status
                    ) AS active_sync_status

                FROM legal_entity e

                JOIN legal_entity_integration_config config
                  ON config.legal_entity_id = e.id

                LEFT JOIN legal_entity_certificate certificate
                  ON certificate.legal_entity_id = e.id
                 AND certificate.is_active = 1


                LEFT JOIN sys_auth_job auth_job
                  ON auth_job.legal_entity_id = e.id
                 AND auth_job.status IN (
                    'PENDING',
                    'WAITING_CERTIFICATE',
                    'PROCESSING'
                 )

                LEFT JOIN sys_sync_job sync_job
                  ON sync_job.legal_entity_id = e.id
                 AND sync_job.status IN (
                    'CREATED',
                    'PUBLISHED',
                    'PROCESSING',
                    'RETRY_WAIT'
                 )

                GROUP BY
                    e.id,
                    e.inn,
                    e.short_name,
                    e.gis_mt_name,
                    e.status,
                    e.storage_slug,
                    e.gis_mt_last_sync_status,
                    e.gis_mt_last_sync_at,
                    config.true_api_enabled

                ORDER BY e.id
                """
            )

            entities = rows_to_json(
                list(
                    cursor.fetchall()
                )
            )

            cursor.execute(
                """
                SELECT
                    job_uuid,
                    legal_entity_id,
                    status,
                    requested_by,
                    requested_at,
                    finished_at,
                    certificate_thumbprint,
                    sync_job_uuid,
                    last_error_type,
                    last_error_message
                FROM sys_auth_job
                ORDER BY requested_at DESC
                LIMIT 50
                """
            )

            auth_jobs = rows_to_json(
                list(
                    cursor.fetchall()
                )
            )

            cursor.execute(
                """
                SELECT
                    job_uuid,
                    legal_entity_id,
                    job_type,
                    status,
                    requested_by,
                    requested_at,
                    retry_count,
                    attempt_count,
                    published_at,
                    finished_at,
                    last_error_type,
                    last_error_message
                FROM sys_sync_job
                ORDER BY requested_at DESC
                LIMIT 50
                """
            )

            sync_jobs = rows_to_json(
                list(
                    cursor.fetchall()
                )
            )


        finally:
            cursor.close()

    return {
        "generated_at": (
            datetime
            .now(
                timezone.utc
            )
            .isoformat()
        ),
        "entities": entities,
        "auth_jobs": auth_jobs,
        "sync_jobs": sync_jobs,
    }


@app.errorhandler(
    Exception
)
def unexpected_error(
    exc: Exception,
):
    app.logger.exception(
        "Unhandled control-web error"
    )

    return (
        jsonify(
            {
                "status": "ERROR",
                "error_type": (
                    type(
                        exc
                    ).__name__
                ),
                "error": str(
                    exc
                ),
            }
        ),
        500,
    )


@app.get(
    "/"
)
def index():
    return render_template(
        "index.html"
    )


@app.get(
    "/api/health"
)
def health():
    with db_read() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "SELECT 1"
            )
            cursor.fetchone()

        finally:
            cursor.close()

    return jsonify(
        {
            "status": "OK"
        }
    )


@app.get(
    "/api/dashboard"
)
def dashboard():
    return jsonify(
        dashboard_data()
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
    )