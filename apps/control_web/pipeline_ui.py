from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

import mysql.connector
from flask import Blueprint, jsonify, request
from mysql.connector import MySQLConnection


pipeline_ui_bp = Blueprint(
    "pipeline_ui",
    __name__,
    url_prefix="/api/pipeline",
)

SCHEDULE_CODES = {
    "HOURLY",
    "DAILY",
    "WEEKLY",
}

TASK_AUTHORIZATION = "AUTHORIZATION"
TASK_EXPORT_UPD = "EXPORT_UPD"
TASK_PROCESS_UPD = "PROCESS_UPD"
TASK_TRACK_VIOLATIONS = "TRACK_VIOLATIONS"

TASK_CODES = {
    TASK_AUTHORIZATION,
    TASK_EXPORT_UPD,
    TASK_PROCESS_UPD,
    TASK_TRACK_VIOLATIONS,
}


class PipelineApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.field = field


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
        "autocommit": False,
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


@contextmanager
def database_transaction() -> Iterator[MySQLConnection]:
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


def request_payload() -> dict[str, Any]:
    value = request.get_json(silent=True)

    if not isinstance(value, dict):
        raise PipelineApiError(
            "Тело запроса должно быть JSON-объектом."
        )

    return value


def require_object(
    value: Any,
    message: str,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PipelineApiError(
            message,
            field=field,
        )

    return value


def require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise PipelineApiError(
            "Значение должно быть логическим.",
            field=field,
        )

    return value


def parse_iso_datetime(
    value: Any,
    field: str,
) -> datetime | None:
    if value in (None, ""):
        return None

    prepared = str(value).strip()

    if prepared.endswith("Z"):
        prepared = prepared[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(prepared)
    except ValueError as exc:
        raise PipelineApiError(
            "Некорректные дата и время.",
            field=field,
        ) from exc

    if parsed.tzinfo is None:
        raise PipelineApiError(
            "Дата и время должны содержать часовой пояс.",
            field=field,
        )

    return parsed.astimezone(timezone.utc)


def parse_iso_date(
    value: Any,
    field: str,
) -> date | None:
    if value in (None, ""):
        return None

    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise PipelineApiError(
            "Некорректная дата.",
            field=field,
        ) from exc


def parse_entity_ids(
    value: Any,
    field: str,
) -> list[int]:
    if value is None:
        return []

    if not isinstance(value, list):
        raise PipelineApiError(
            "Список организаций должен быть массивом.",
            field=field,
        )

    result: list[int] = []
    seen: set[int] = set()

    for raw_value in value:
        try:
            entity_id = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise PipelineApiError(
                "Список организаций содержит некорректный ID.",
                field=field,
            ) from exc

        if entity_id <= 0:
            raise PipelineApiError(
                "ID организации должен быть положительным числом.",
                field=field,
            )

        if entity_id not in seen:
            seen.add(entity_id)
            result.append(entity_id)

    return result


def datetime_to_iso(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    prepared = value

    if prepared.tzinfo is None:
        prepared = prepared.replace(tzinfo=timezone.utc)
    else:
        prepared = prepared.astimezone(timezone.utc)

    return prepared.isoformat().replace(
        "+00:00",
        "Z",
    )


def date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def read_config_row(
    connection: MySQLConnection,
    for_update: bool = False,
) -> dict[str, Any]:
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT
                id,
                pipeline_enabled,
                autorun_enabled,
                autorun_running,
                schedule_code,
                starts_at_utc,
                authorization_enabled,
                export_upd_enabled,
                export_period_from,
                export_period_to,
                process_upd_enabled,
                track_violations_enabled,
                test_running,
                last_test_status,
                last_test_requested_at,
                last_test_message,
                current_run_uuid,
                current_run_mode,
                current_run_started_at,
                current_run_heartbeat_at,
                updated_at
            FROM sys_pipeline_config
            WHERE id = 1
        """

        if for_update:
            query += " FOR UPDATE"

        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            raise PipelineApiError(
                "Конфигурация конвейера не инициализирована.",
                500,
            )

        return dict(row)
    finally:
        cursor.close()


def read_task_entities(
    connection: MySQLConnection,
) -> dict[str, list[int]]:
    result = {
        code: []
        for code in TASK_CODES
    }

    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                task_code,
                legal_entity_id
            FROM sys_pipeline_task_entity
            ORDER BY
                task_code,
                legal_entity_id
            """
        )

        for row in cursor.fetchall():
            task_code = str(row["task_code"])

            if task_code in result:
                result[task_code].append(
                    int(row["legal_entity_id"])
                )
    finally:
        cursor.close()

    return result


def read_organizations(
    connection: MySQLConnection,
) -> list[dict[str, Any]]:
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT
                id,
                inn,
                short_name,
                gis_mt_name,
                status
            FROM legal_entity
            WHERE status IN (
                'SETUP',
                'ACTIVE'
            )
            ORDER BY
                COALESCE(
                    gis_mt_name,
                    short_name
                ),
                id
            """
        )

        return [
            {
                "id": int(row["id"]),
                "inn": str(row["inn"]),
                "short_name": str(
                    row["short_name"] or ""
                ),
                "gis_mt_name": (
                    str(row["gis_mt_name"])
                    if row["gis_mt_name"]
                    else None
                ),
                "status": str(row["status"]),
            }
            for row in cursor.fetchall()
        ]
    finally:
        cursor.close()


def serialize_config(
    row: dict[str, Any],
    task_entities: dict[str, list[int]],
) -> dict[str, Any]:
    return {
        "pipeline_enabled": bool(
            row["pipeline_enabled"]
        ),
        "autorun": {
            "enabled": bool(
                row["autorun_enabled"]
            ),
            "running": bool(
                row["autorun_running"]
            ),
            "schedule": str(
                row["schedule_code"]
            ),
            "starts_at": datetime_to_iso(
                row["starts_at_utc"]
            ),
        },
        "tasks": {
            "authorization": {
                "enabled": bool(
                    row["authorization_enabled"]
                ),
                "entity_ids": task_entities[
                    TASK_AUTHORIZATION
                ],
            },
            "export_upd": {
                "enabled": bool(
                    row["export_upd_enabled"]
                ),
                "period_from": date_to_iso(
                    row["export_period_from"]
                ),
                "period_to": date_to_iso(
                    row["export_period_to"]
                ),
                "entity_ids": task_entities[
                    TASK_EXPORT_UPD
                ],
            },
            "process_upd": {
                "enabled": bool(
                    row["process_upd_enabled"]
                ),
                "entity_ids": task_entities[
                    TASK_PROCESS_UPD
                ],
            },
            "track_violations": {
                "enabled": bool(
                    row["track_violations_enabled"]
                ),
                "entity_ids": task_entities[
                    TASK_TRACK_VIOLATIONS
                ],
            },
        },
        "test": {
            "running": bool(row["test_running"]),
            "last_status": str(
                row["last_test_status"]
            ),
            "last_requested_at": datetime_to_iso(
                row["last_test_requested_at"]
            ),
            "last_message": str(
                row["last_test_message"] or ""
            ),
        },
        "run": {
            "uuid": (
                str(row["current_run_uuid"])
                if row["current_run_uuid"]
                else None
            ),
            "mode": (
                str(row["current_run_mode"])
                if row["current_run_mode"]
                else None
            ),
            "started_at": datetime_to_iso(
                row["current_run_started_at"]
            ),
            "heartbeat_at": datetime_to_iso(
                row["current_run_heartbeat_at"]
            ),
        },
        "updated_at": datetime_to_iso(
            row["updated_at"]
        ),
    }


def assert_entities_exist(
    connection: MySQLConnection,
    entity_ids: set[int],
) -> None:
    if not entity_ids:
        return

    placeholders = ",".join(
        ["%s"] * len(entity_ids)
    )

    cursor = connection.cursor()

    try:
        cursor.execute(
            f"""
            SELECT id
            FROM legal_entity
            WHERE id IN ({placeholders})
              AND status IN (
                  'SETUP',
                  'ACTIVE'
              )
            """,
            tuple(sorted(entity_ids)),
        )

        found = {
            int(row[0])
            for row in cursor.fetchall()
        }
    finally:
        cursor.close()

    missing = sorted(entity_ids - found)

    if missing:
        raise PipelineApiError(
            "Не найдены доступные организации: "
            + ", ".join(str(value) for value in missing),
            field="organizations",
        )


def assert_no_active_run(
    current: dict[str, Any],
) -> None:
    if (
        bool(current["test_running"])
        or bool(current["autorun_running"])
        or bool(current["current_run_uuid"])
    ):
        raise PipelineApiError(
            "Нельзя изменять конфигурацию, "
            "пока запуск ожидает выполнения "
            "или выполняется.",
            409,
        )


def ensure_non_empty_selection(
    enabled: bool,
    entity_ids: list[int],
    message: str,
    field: str,
) -> None:
    if enabled and not entity_ids:
        raise PipelineApiError(
            message,
            field=field,
        )


def ensure_subset(
    child_ids: list[int],
    parent_ids: list[int],
    message: str,
    field: str,
) -> None:
    missing = sorted(
        set(child_ids) - set(parent_ids)
    )

    if missing:
        raise PipelineApiError(
            message,
            field=field,
        )


def validate_task_dependencies(
    *,
    authorization_enabled: bool,
    authorization_ids: list[int],
    export_enabled: bool,
    export_ids: list[int],
    process_enabled: bool,
    process_ids: list[int],
    violations_enabled: bool,
    violations_ids: list[int],
    export_period_from: date | None,
    export_period_to: date | None,
) -> None:
    ensure_non_empty_selection(
        authorization_enabled,
        authorization_ids,
        "Для авторизации выберите хотя бы одну организацию.",
        "tasks.authorization.entity_ids",
    )

    if export_enabled:
        if not authorization_enabled:
            raise PipelineApiError(
                "Экспорт УПД требует включённой авторизации.",
                field="tasks.export_upd.enabled",
            )

        ensure_non_empty_selection(
            True,
            export_ids,
            "Для экспорта УПД выберите хотя бы одну организацию.",
            "tasks.export_upd.entity_ids",
        )

        if (
            export_period_from is None
            or export_period_to is None
        ):
            raise PipelineApiError(
                "Укажите период экспорта УПД.",
                field="tasks.export_upd.period",
            )

        if export_period_from > export_period_to:
            raise PipelineApiError(
                "Дата «с» не может быть позже даты «по».",
                field="tasks.export_upd.period",
            )

        ensure_subset(
            export_ids,
            authorization_ids,
            "Экспорт УПД можно включить только "
            "для организаций, участвующих в авторизации.",
            "tasks.export_upd.entity_ids",
        )

    if process_enabled:
        if not export_enabled:
            raise PipelineApiError(
                "Обработка УПД требует включённого задания "
                "«Экспорт УПД».",
                field="tasks.process_upd.enabled",
            )

        ensure_non_empty_selection(
            True,
            process_ids,
            "Для обработки УПД выберите хотя бы одну организацию.",
            "tasks.process_upd.entity_ids",
        )

        ensure_subset(
            process_ids,
            export_ids,
            "Организацию можно добавить к заданию "
            "«Обработка УПД» только после добавления "
            "в задание «Экспорт УПД».",
            "tasks.process_upd.entity_ids",
        )

    if violations_enabled:
        if not authorization_enabled:
            raise PipelineApiError(
                "Отслеживание отклонений требует "
                "включённой авторизации.",
                field="tasks.track_violations.enabled",
            )

        ensure_non_empty_selection(
            True,
            violations_ids,
            "Для отслеживания отклонений выберите "
            "хотя бы одну организацию.",
            "tasks.track_violations.entity_ids",
        )

        ensure_subset(
            violations_ids,
            authorization_ids,
            "Организацию можно добавить к заданию "
            "«Отслеживание отклонений в продаже» "
            "только после добавления в задание «Авторизация».",
            "tasks.track_violations.entity_ids",
        )


@pipeline_ui_bp.errorhandler(PipelineApiError)
def handle_pipeline_api_error(exc: PipelineApiError):
    body: dict[str, Any] = {
        "status": "ERROR",
        "error": str(exc),
        "message": str(exc),
    }

    if exc.field:
        body["field"] = exc.field

    return jsonify(body), exc.status_code


@pipeline_ui_bp.get("/state")
def get_pipeline_state():
    with database_read() as connection:
        row = read_config_row(connection)
        task_entities = read_task_entities(connection)

    config = serialize_config(row, task_entities)

    return jsonify(
        {
            "status": "OK",
            "state": {
                "pipeline_enabled": config[
                    "pipeline_enabled"
                ],
                "test_running": config["test"][
                    "running"
                ],
                "last_test_status": config["test"][
                    "last_status"
                ],
                "last_test_requested_at": config[
                    "test"
                ]["last_requested_at"],
                "last_test_message": config["test"][
                    "last_message"
                ],
                "current_run_uuid": config["run"][
                    "uuid"
                ],
                "current_run_mode": config["run"][
                    "mode"
                ],
            },
        }
    )


@pipeline_ui_bp.get("/config")
def get_pipeline_config():
    with database_read() as connection:
        row = read_config_row(connection)
        task_entities = read_task_entities(connection)
        organizations = read_organizations(connection)

    return jsonify(
        {
            "status": "OK",
            "config": serialize_config(
                row,
                task_entities,
            ),
            "organizations": organizations,
        }
    )


@pipeline_ui_bp.put("/config")
def update_pipeline_config():
    data = request_payload()

    autorun = require_object(
        data.get("autorun"),
        "Раздел «Авто-запуск» заполнен некорректно.",
        "autorun",
    )

    tasks = require_object(
        data.get("tasks"),
        "Раздел «Задания» заполнен некорректно.",
        "tasks",
    )

    authorization = require_object(
        tasks.get("authorization"),
        "Настройка авторизации заполнена некорректно.",
        "authorization",
    )

    export_upd = require_object(
        tasks.get("export_upd"),
        "Настройка экспорта УПД заполнена некорректно.",
        "export_upd",
    )

    process_upd = require_object(
        tasks.get("process_upd"),
        "Настройка обработки УПД заполнена некорректно.",
        "process_upd",
    )

    track_violations = require_object(
        tasks.get("track_violations"),
        "Настройка отслеживания отклонений заполнена некорректно.",
        "track_violations",
    )

    autorun_enabled = require_bool(
        autorun.get("enabled"),
        "autorun.enabled",
    )

    schedule_code = str(
        autorun.get("schedule") or ""
    ).upper()

    if schedule_code not in SCHEDULE_CODES:
        raise PipelineApiError(
            "Выбран некорректный вариант расписания.",
            field="autorun.schedule",
        )

    starts_at_utc = parse_iso_datetime(
        autorun.get("starts_at"),
        "autorun.starts_at",
    )

    authorization_enabled = require_bool(
        authorization.get("enabled"),
        "tasks.authorization.enabled",
    )

    authorization_ids = parse_entity_ids(
        authorization.get("entity_ids"),
        "tasks.authorization.entity_ids",
    )

    export_enabled = require_bool(
        export_upd.get("enabled"),
        "tasks.export_upd.enabled",
    )

    export_period_from = parse_iso_date(
        export_upd.get("period_from"),
        "tasks.export_upd.period_from",
    )

    export_period_to = parse_iso_date(
        export_upd.get("period_to"),
        "tasks.export_upd.period_to",
    )

    export_ids = parse_entity_ids(
        export_upd.get("entity_ids"),
        "tasks.export_upd.entity_ids",
    )

    process_enabled = require_bool(
        process_upd.get("enabled"),
        "tasks.process_upd.enabled",
    )

    process_ids = parse_entity_ids(
        process_upd.get("entity_ids"),
        "tasks.process_upd.entity_ids",
    )

    violations_enabled = require_bool(
        track_violations.get("enabled"),
        "tasks.track_violations.enabled",
    )

    violations_ids = parse_entity_ids(
        track_violations.get("entity_ids"),
        "tasks.track_violations.entity_ids",
    )

    if autorun_enabled and starts_at_utc is None:
        raise PipelineApiError(
            "Укажите дату и время начала авто-запуска.",
            field="autorun.starts_at",
        )

    validate_task_dependencies(
        authorization_enabled=authorization_enabled,
        authorization_ids=authorization_ids,
        export_enabled=export_enabled,
        export_ids=export_ids,
        process_enabled=process_enabled,
        process_ids=process_ids,
        violations_enabled=violations_enabled,
        violations_ids=violations_ids,
        export_period_from=export_period_from,
        export_period_to=export_period_to,
    )

    all_ids = (
        set(authorization_ids)
        | set(export_ids)
        | set(process_ids)
        | set(violations_ids)
    )

    with database_transaction() as connection:
        current = read_config_row(
            connection,
            for_update=True,
        )

        assert_no_active_run(current)

        if autorun_enabled and starts_at_utc is not None:
            now_utc = datetime.now(timezone.utc)
            current_starts_at = current["starts_at_utc"]

            current_starts_at_utc = (
                current_starts_at.replace(
                    tzinfo=timezone.utc
                )
                if current_starts_at is not None
                else None
            )

            unchanged_past_value = (
                current_starts_at_utc is not None
                and abs(
                    (
                        starts_at_utc
                        - current_starts_at_utc
                    ).total_seconds()
                )
                < 1
            )

            if (
                starts_at_utc < now_utc
                and not unchanged_past_value
            ):
                raise PipelineApiError(
                    "Нельзя указать дату и время "
                    "раньше текущего момента.",
                    field="autorun.starts_at",
                )

        assert_entities_exist(connection, all_ids)

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_pipeline_config
                   SET autorun_enabled = %s,
                       schedule_code = %s,
                       starts_at_utc = %s,
                       authorization_enabled = %s,
                       export_upd_enabled = %s,
                       export_period_from = %s,
                       export_period_to = %s,
                       process_upd_enabled = %s,
                       track_violations_enabled = %s,
                       updated_by = 'control-web',
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = 1
                """,
                (
                    int(autorun_enabled),
                    schedule_code,
                    (
                        starts_at_utc.replace(tzinfo=None)
                        if starts_at_utc is not None
                        else None
                    ),
                    int(authorization_enabled),
                    int(export_enabled),
                    export_period_from,
                    export_period_to,
                    int(process_enabled),
                    int(violations_enabled),
                ),
            )

            cursor.execute(
                """
                DELETE FROM sys_pipeline_task_entity
                WHERE task_code IN (
                    'AUTHORIZATION',
                    'EXPORT_UPD',
                    'PROCESS_UPD',
                    'TRACK_VIOLATIONS'
                )
                """
            )

            rows: list[tuple[str, int]] = []

            rows.extend(
                (TASK_AUTHORIZATION, entity_id)
                for entity_id in authorization_ids
            )

            rows.extend(
                (TASK_EXPORT_UPD, entity_id)
                for entity_id in export_ids
            )

            rows.extend(
                (TASK_PROCESS_UPD, entity_id)
                for entity_id in process_ids
            )

            rows.extend(
                (TASK_TRACK_VIOLATIONS, entity_id)
                for entity_id in violations_ids
            )

            if rows:
                cursor.executemany(
                    """
                    INSERT INTO sys_pipeline_task_entity (
                        task_code,
                        legal_entity_id,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    rows,
                )

            cursor.execute(
                """
                UPDATE legal_entity_product_group
                   SET violations_enabled = 0,
                       updated_at = UTC_TIMESTAMP(6)
                """
            )

            if violations_enabled and violations_ids:
                placeholders = ",".join(
                    ["%s"] * len(violations_ids)
                )

                cursor.execute(
                    f"""
                    UPDATE legal_entity_product_group
                       SET violations_enabled = 1,
                           updated_at = UTC_TIMESTAMP(6)
                     WHERE legal_entity_id
                           IN ({placeholders})
                    """,
                    tuple(violations_ids),
                )
        finally:
            cursor.close()

        updated = read_config_row(connection)
        task_entities = read_task_entities(connection)

    return jsonify(
        {
            "status": "OK",
            "message": "Конфигурация конвейера сохранена.",
            "config": serialize_config(
                updated,
                task_entities,
            ),
        }
    )


@pipeline_ui_bp.post("/toggle")
def toggle_pipeline():
    data = request.get_json(silent=True) or {}
    desired_enabled = data.get("enabled")

    with database_transaction() as connection:
        current = read_config_row(
            connection,
            for_update=True,
        )

        if isinstance(desired_enabled, bool):
            enabled = desired_enabled
        else:
            enabled = not bool(
                current["pipeline_enabled"]
            )

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_pipeline_config
                   SET pipeline_enabled = %s,
                       updated_by = 'control-web',
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = 1
                """,
                (int(enabled),),
            )
        finally:
            cursor.close()

        updated = read_config_row(connection)
        task_entities = read_task_entities(connection)

    config = serialize_config(updated, task_entities)

    return jsonify(
        {
            "status": "OK",
            "message": (
                "Конвейер переведён в режим «Старт»."
                if enabled
                else "Конвейер переведён в режим «Стоп»."
            ),
            "state": {
                "pipeline_enabled": enabled,
                "test_running": config["test"][
                    "running"
                ],
                "last_test_status": config["test"][
                    "last_status"
                ],
                "last_test_requested_at": config[
                    "test"
                ]["last_requested_at"],
                "last_test_message": config["test"][
                    "last_message"
                ],
                "current_run_uuid": config["run"][
                    "uuid"
                ],
                "current_run_mode": config["run"][
                    "mode"
                ],
            },
        }
    )


@pipeline_ui_bp.post("/test")
def request_pipeline_test():
    with database_transaction() as connection:
        current = read_config_row(
            connection,
            for_update=True,
        )

        task_entities = read_task_entities(connection)

        if (
            bool(current["test_running"])
            or bool(current["autorun_running"])
            or bool(current["current_run_uuid"])
        ):
            raise PipelineApiError(
                "Другой запуск уже ожидает выполнения "
                "или выполняется.",
                409,
            )

        authorization_enabled = bool(
            current["authorization_enabled"]
        )
        export_enabled = bool(
            current["export_upd_enabled"]
        )
        process_enabled = bool(
            current["process_upd_enabled"]
        )
        violations_enabled = bool(
            current["track_violations_enabled"]
        )

        authorization_ids = task_entities[
            TASK_AUTHORIZATION
        ]
        export_ids = task_entities[TASK_EXPORT_UPD]
        process_ids = task_entities[TASK_PROCESS_UPD]
        violations_ids = task_entities[
            TASK_TRACK_VIOLATIONS
        ]

        if not authorization_enabled:
            raise PipelineApiError(
                "В конфигурации не включена авторизация. "
                "Тестовый запуск не содержит выполняемых функций.",
                400,
                field="tasks.authorization.enabled",
            )

        validate_task_dependencies(
            authorization_enabled=authorization_enabled,
            authorization_ids=authorization_ids,
            export_enabled=export_enabled,
            export_ids=export_ids,
            process_enabled=process_enabled,
            process_ids=process_ids,
            violations_enabled=violations_enabled,
            violations_ids=violations_ids,
            export_period_from=current[
                "export_period_from"
            ],
            export_period_to=current[
                "export_period_to"
            ],
        )

        description_parts = [
            f"Авторизация: {len(authorization_ids)}"
        ]

        if export_enabled:
            description_parts.append(
                f"экспорт УПД: {len(export_ids)}"
            )
            description_parts.append(
                "период: "
                f"{current['export_period_from']} — "
                f"{current['export_period_to']}"
            )
        else:
            description_parts.append(
                "экспорт УПД отключён"
            )

        description_parts.append(
            "обработка УПД: "
            + (
                str(len(process_ids))
                if process_enabled
                else "отключена"
            )
        )

        description_parts.append(
            "отклонения: "
            + (
                str(len(violations_ids))
                if violations_enabled
                else "отключены"
            )
        )

        test_description = "; ".join(
            description_parts
        ) + "."

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_pipeline_config
                   SET test_running = 1,
                       last_test_status = 'REQUESTED',
                       last_test_requested_at =
                           UTC_TIMESTAMP(6),
                       last_test_message = %s,
                       updated_by = 'control-web',
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = 1
                """,
                (
                    "Тестовый запуск поставлен в очередь. "
                    + test_description,
                ),
            )
        finally:
            cursor.close()

        updated = read_config_row(connection)
        updated_task_entities = read_task_entities(
            connection
        )

    config = serialize_config(
        updated,
        updated_task_entities,
    )

    return (
        jsonify(
            {
                "status": "ACCEPTED",
                "message": config["test"][
                    "last_message"
                ],
                "state": {
                    "pipeline_enabled": config[
                        "pipeline_enabled"
                    ],
                    "test_running": True,
                    "last_test_status": "REQUESTED",
                    "last_test_requested_at": config[
                        "test"
                    ]["last_requested_at"],
                    "last_test_message": config[
                        "test"
                    ]["last_message"],
                },
            }
        ),
        202,
    )
