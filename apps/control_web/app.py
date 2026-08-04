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

AUTH_ACTIVE_STATUSES = {
    "PENDING",
    "WAITING_CERTIFICATE",
    "PROCESSING",
}

SYNC_ACTIVE_STATUSES = {
    "CREATED",
    "PUBLISHED",
    "PROCESSING",
}

SUCCESS_STATUSES = {
    "SUCCESS",
}

RETRY_STATUSES = {
    "RETRY_WAIT",
}

DEAD_STATUSES = {
    "DEAD",
    "ERROR",
    "CANCELLED",
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


def row_to_json(
    row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        key: json_value(value)
        for key, value in row.items()
    }


def load_rows(
    cursor,
    query: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    cursor.execute(
        query,
        params,
    )

    return rows_to_json(
        list(cursor.fetchall())
    )


def load_status_counts(
    cursor,
    *,
    table_name: str,
    where_sql: str,
    params: tuple[Any, ...] = (),
) -> dict[str, int]:
    cursor.execute(
        f"""
        SELECT
            status,
            COUNT(*) AS item_count
        FROM {table_name}
        WHERE {where_sql}
        GROUP BY status
        """,
        params,
    )

    return {
        str(row["status"] or ""): int(
            row["item_count"] or 0
        )
        for row in cursor.fetchall()
    }


def load_last_job_meta(
    cursor,
    *,
    table_name: str,
    where_sql: str,
    params: tuple[Any, ...] = (),
) -> dict[str, Any] | None:
    cursor.execute(
        f"""
        SELECT
            status,
            requested_at
        FROM {table_name}
        WHERE {where_sql}
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        params,
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row_to_json(
        dict(row)
    )


def count_by_statuses(
    counts: dict[str, int],
    statuses: set[str],
) -> int:
    return sum(
        count
        for status, count in counts.items()
        if status in statuses
    )


def build_job_group(
    *,
    code: str,
    title: str,
    subtitle: str,
    jobs: list[dict[str, Any]],
    status_counts: dict[str, int],
    last_job_meta: dict[str, Any] | None,
    active_statuses: set[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "subtitle": subtitle,
        "jobs": jobs,
        "last_status": (
            last_job_meta.get("status")
            if last_job_meta
            else None
        ),
        "last_requested_at": (
            last_job_meta.get("requested_at")
            if last_job_meta
            else None
        ),
        "total_count": sum(
            status_counts.values()
        ),
        "dead_count": count_by_statuses(
            status_counts,
            DEAD_STATUSES,
        ),
        "retry_count": count_by_statuses(
            status_counts,
            RETRY_STATUSES,
        ),
        "success_count": count_by_statuses(
            status_counts,
            SUCCESS_STATUSES,
        ),
        "running_count": count_by_statuses(
            status_counts,
            active_statuses,
        ),
        "status_counts": status_counts,
    }


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

            auth_jobs = load_rows(
                cursor,
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
                """,
            )

            sync_jobs = load_rows(
                cursor,
                """
                SELECT
                    job_uuid,
                    parent_job_uuid,
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
                WHERE job_type IN (
                    'SYNC_LEGAL_ENTITY',
                    'EXPORT_UPD'
                )
                ORDER BY requested_at DESC
                LIMIT 50
                """,
            )

            process_upd_jobs = load_rows(
                cursor,
                """
                SELECT
                    job_uuid,
                    parent_job_uuid,
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
                WHERE job_type = 'PROCESS_UPD'
                ORDER BY requested_at DESC
                LIMIT 50
                """,
            )

            violation_jobs = load_rows(
                cursor,
                """
                SELECT
                    job_uuid,
                    parent_job_uuid,
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
                WHERE job_type = 'TRACK_VIOLATIONS'
                ORDER BY requested_at DESC
                LIMIT 50
                """,
            )

            auth_status_counts = load_status_counts(
                cursor,
                table_name="sys_auth_job",
                where_sql="1 = 1",
            )

            auth_last_job_meta = load_last_job_meta(
                cursor,
                table_name="sys_auth_job",
                where_sql="1 = 1",
            )

            sync_status_counts = load_status_counts(
                cursor,
                table_name="sys_sync_job",
                where_sql=(
                    "job_type IN ("
                    "'SYNC_LEGAL_ENTITY', "
                    "'EXPORT_UPD'"
                    ")"
                ),
            )

            sync_last_job_meta = load_last_job_meta(
                cursor,
                table_name="sys_sync_job",
                where_sql=(
                    "job_type IN ("
                    "'SYNC_LEGAL_ENTITY', "
                    "'EXPORT_UPD'"
                    ")"
                ),
            )

            process_status_counts = load_status_counts(
                cursor,
                table_name="sys_sync_job",
                where_sql="job_type = 'PROCESS_UPD'",
            )

            process_last_job_meta = load_last_job_meta(
                cursor,
                table_name="sys_sync_job",
                where_sql="job_type = 'PROCESS_UPD'",
            )

            violation_status_counts = load_status_counts(
                cursor,
                table_name="sys_sync_job",
                where_sql="job_type = 'TRACK_VIOLATIONS'",
            )

            violation_last_job_meta = load_last_job_meta(
                cursor,
                table_name="sys_sync_job",
                where_sql="job_type = 'TRACK_VIOLATIONS'",
            )

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total_count
                FROM datamatrix_unit
                """
            )

            datamatrix_count_row = (
                cursor.fetchone()
                or {"total_count": 0}
            )

            cursor.execute(
                """
                SELECT
                    autorun_running,
                    last_autorun_status,
                    last_autorun_started_at,
                    last_autorun_finished_at,
                    last_autorun_message
                FROM sys_pipeline_config
                ORDER BY id DESC
                LIMIT 1
                """
            )

            pipeline_row_raw = cursor.fetchone()

            pipeline_state = (
                rows_to_json(
                    [pipeline_row_raw]
                )[0]
                if pipeline_row_raw
                else {}
            )

        finally:
            cursor.close()

    job_groups = {
        "AUTHORIZATION": build_job_group(
            code="AUTHORIZATION",
            title="Задания авторизаций",
            subtitle=(
                "Токены в базе не сохраняются."
            ),
            jobs=auth_jobs,
            status_counts=auth_status_counts,
            last_job_meta=auth_last_job_meta,
            active_statuses=AUTH_ACTIVE_STATUSES,
        ),
        "EXPORT_UPD": build_job_group(
            code="EXPORT_UPD",
            title="Задания скачиваний",
            subtitle=(
                "Скачивание XML и связанных "
                "данных документов."
            ),
            jobs=sync_jobs,
            status_counts=sync_status_counts,
            last_job_meta=sync_last_job_meta,
            active_statuses=SYNC_ACTIVE_STATUSES,
        ),
        "PROCESS_UPD": build_job_group(
            code="PROCESS_UPD",
            title="Задания обработки УПД/УКД",
            subtitle=(
                "Разбор документов, КИ и "
                "раскрытие упаковок до КИ единицы."
            ),
            jobs=process_upd_jobs,
            status_counts=process_status_counts,
            last_job_meta=process_last_job_meta,
            active_statuses=SYNC_ACTIVE_STATUSES,
        ),
        "TRACK_VIOLATIONS": build_job_group(
            code="TRACK_VIOLATIONS",
            title="Задания скачивания отклонений",
            subtitle=(
                "Получение отклонений оборота "
                "подконтрольной продукции."
            ),
            jobs=violation_jobs,
            status_counts=violation_status_counts,
            last_job_meta=violation_last_job_meta,
            active_statuses=SYNC_ACTIVE_STATUSES,
        ),
    }

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
        "process_upd_jobs": process_upd_jobs,
        "violation_jobs": violation_jobs,
        "job_groups": job_groups,
        "metrics": {
            "datamatrix_count": int(
                datamatrix_count_row.get(
                    "total_count",
                    0
                )
                or 0
            ),
        },
        "pipeline": pipeline_state,
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