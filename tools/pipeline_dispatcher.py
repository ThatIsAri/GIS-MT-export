from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import (
    date,
    datetime,
    time as day_time,
    timedelta,
    timezone,
)
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import mysql.connector
from mysql.connector import Error as MySqlError
from mysql.connector import MySQLConnection
from mysql.connector.errors import IntegrityError


SCHEDULE_INTERVALS = {
    "HOURLY": timedelta(
        hours=1
    ),
    "DAILY": timedelta(
        days=1
    ),
    "WEEKLY": timedelta(
        days=7
    ),
}

MYSQL_TRANSIENT_ERROR_CODES = {
    2002,
    2003,
    2006,
    2013,
    2055,
}

AUTH_TERMINAL_STATUSES = {
    "SUCCESS",
    "ERROR",
    "CANCELLED",
}

SYNC_TERMINAL_STATUSES = {
    "SUCCESS",
    "DEAD",
    "CANCELLED",
}

WORKER_RETRY_EXIT_CODES = {
    20,
    30,
}


class DispatcherError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def mysql_datetime(
    value: datetime | None,
) -> datetime | None:
    prepared = as_utc(
        value
    )

    if prepared is None:
        return None

    return prepared.replace(
        tzinfo=None
    )


def iso_utc(
    value: datetime,
) -> str:
    return (
        value
        .astimezone(
            timezone.utc
        )
        .replace(
            microsecond=0
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def json_text(
    value: Any,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
        default=str,
    )


def log(
    message: str,
) -> None:
    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print(
        f"[{timestamp}] {message}",
        flush=True,
    )


def read_env(
    path: Path,
) -> dict[str, str]:
    if not path.is_file():
        raise DispatcherError(
            f"Файл окружения не найден: {path}"
        )

    result: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        name, value = line.split(
            "=",
            1,
        )

        name = name.strip()
        value = value.strip()

        if (
            len(
                value
            )
            >= 2
            and value[0]
            == value[-1]
            and value[0]
            in {
                "'",
                '"',
            }
        ):
            value = value[
                1:-1
            ]

        if name:
            result[
                name
            ] = value

    return result


def required(
    values: dict[str, str],
    name: str,
) -> str:
    value = os.getenv(
        name,
        values.get(
            name,
            "",
        ),
    ).strip()

    if not value:
        raise DispatcherError(
            f"Не задан параметр {name}."
        )

    return value


def db_options(
    values: dict[str, str],
) -> dict[str, Any]:
    return {
        "host": os.getenv(
            "MYSQL_HOST",
            "127.0.0.1",
        ),
        "port": int(
            os.getenv(
                "MYSQL_PORT",
                values.get(
                    "MYSQL_PORT",
                    "3306",
                ),
            )
        ),
        "database": required(
            values,
            "MYSQL_DATABASE",
        ),
        "user": required(
            values,
            "MYSQL_USER",
        ),
        "password": required(
            values,
            "MYSQL_PASSWORD",
        ),
        "charset": "utf8mb4",
        "collation":
            "utf8mb4_0900_ai_ci",
        "use_unicode": True,
        "connection_timeout": 10,
        "autocommit": False,
    }


def open_mysql_connection(
    options: dict[str, Any],
    *,
    attempts: int = 6,
    initial_delay_seconds: float = 1.0,
) -> MySQLConnection:
    last_error: MySqlError | None = None

    for attempt in range(
        1,
        attempts + 1,
    ):
        try:
            connection = (
                mysql.connector.connect(
                    **options
                )
            )

            connection.ping(
                reconnect=False,
                attempts=1,
                delay=0,
            )

            return connection

        except MySqlError as exc:
            last_error = exc
            error_code = int(
                exc.errno
                or 0
            )

            if (
                error_code
                not in
                MYSQL_TRANSIENT_ERROR_CODES
                or attempt
                >= attempts
            ):
                raise

            delay_seconds = (
                initial_delay_seconds
                * attempt
            )

            log(
                "MySQL connection attempt "
                f"{attempt}/{attempts} failed: "
                f"{error_code}: {exc}. "
                "Retry in "
                f"{delay_seconds:.1f} seconds."
            )

            time.sleep(
                delay_seconds
            )

    if last_error is not None:
        raise last_error

    raise DispatcherError(
        "Не удалось установить соединение с MySQL."
    )


@contextmanager
def db_read(
    options: dict[str, Any],
) -> Iterator[
    MySQLConnection
]:
    connection = open_mysql_connection(
        options
    )

    try:
        yield connection

    finally:
        try:
            if connection.is_connected():
                connection.close()

        except MySqlError:
            pass


@contextmanager
def db_write(
    options: dict[str, Any],
) -> Iterator[
    MySQLConnection
]:
    connection = open_mysql_connection(
        options
    )

    try:
        connection.start_transaction()

        yield connection

        connection.commit()

    except Exception:
        try:
            if connection.is_connected():
                connection.rollback()

        except MySqlError:
            pass

        raise

    finally:
        try:
            if connection.is_connected():
                connection.close()

        except MySqlError:
            pass


def compose(
    env_file: Path,
) -> list[str]:
    return [
        "docker",
        "compose",
        "--ansi",
        "never",
        "--env-file",
        str(
            env_file
        ),
    ]


def run_command(
    arguments: list[str],
    *,
    root: Path,
    name: str,
    stdin: str | None = None,
    allowed: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        cwd=str(
            root
        ),
        input=stdin,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env={
            **os.environ,
            "PYTHONIOENCODING":
                "utf-8",
            "PYTHONUTF8": "1",
        },
    )

    accepted = (
        allowed
        if allowed is not None
        else {
            0,
        }
    )

    if (
        completed.returncode
        not in accepted
    ):
        output = (
            completed.stdout.strip()
            or "нет диагностического вывода"
        )

        raise DispatcherError(
            f"{name} завершилась с кодом "
            f"{completed.returncode}: "
            f"{output[-4000:]}"
        )

    return completed


def last_json(
    output: str,
    name: str,
) -> dict[str, Any]:
    for raw_line in reversed(
        output.splitlines()
    ):
        line = raw_line.strip()

        if not (
            line.startswith(
                "{"
            )
            and line.endswith(
                "}"
            )
        ):
            continue

        try:
            value = json.loads(
                line
            )

        except json.JSONDecodeError:
            continue

        if isinstance(
            value,
            dict,
        ):
            return value

    raise DispatcherError(
        f"{name} не вернула итоговый JSON."
    )


def due_slot(
    starts_at: datetime | None,
    schedule: str,
    current: datetime,
) -> datetime | None:
    start = as_utc(
        starts_at
    )

    interval = SCHEDULE_INTERVALS.get(
        schedule.upper()
    )

    if (
        start is None
        or interval is None
        or current < start
    ):
        return None

    slot_number = int(
        (
            current
            - start
        ).total_seconds()
        // interval.total_seconds()
    )

    return (
        start
        + interval * slot_number
    )


def recover_stale_run(
    connection: MySQLConnection,
    row: dict[str, Any],
    stale_seconds: int,
) -> bool:
    run_uuid = str(
        row.get(
            "current_run_uuid"
        )
        or ""
    ).strip()

    if not run_uuid:
        return False

    heartbeat_at = as_utc(
        row.get(
            "current_run_heartbeat_at"
        )
    )

    if heartbeat_at is not None:
        age_seconds = (
            utc_now()
            - heartbeat_at
        ).total_seconds()

        if age_seconds <= stale_seconds:
            return False

    mode = str(
        row.get(
            "current_run_mode"
        )
        or ""
    ).upper()

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE sys_auth_job
               SET status = 'CANCELLED',
                   last_error_type =
                       'STALE_DISPATCHER_RUN',
                   last_error_message = %s,
                   finished_at =
                       UTC_TIMESTAMP(6),
                   updated_at =
                       UTC_TIMESTAMP(6)
             WHERE requested_by = %s
               AND status IN (
                   'PENDING',
                   'WAITING_CERTIFICATE',
                   'PROCESSING'
               )
            """,
            (
                (
                    "Предыдущий запуск диспетчера "
                    "признан зависшим."
                ),
                f"pipeline:{run_uuid}",
            ),
        )

        cursor.execute(
            """
            UPDATE sys_pipeline_config
               SET test_running = 0,
                   autorun_running = 0,

                   last_test_status =
                       IF(
                           %s = 'TEST',
                           'ERROR',
                           last_test_status
                       ),

                   last_test_message =
                       IF(
                           %s = 'TEST',
                           'Предыдущий тестовый запуск признан зависшим.',
                           last_test_message
                       ),

                   last_autorun_status =
                       IF(
                           %s = 'AUTORUN',
                           'ERROR',
                           last_autorun_status
                       ),

                   last_autorun_finished_at =
                       IF(
                           %s = 'AUTORUN',
                           UTC_TIMESTAMP(6),
                           last_autorun_finished_at
                       ),

                   last_autorun_message =
                       IF(
                           %s = 'AUTORUN',
                           'Предыдущий автоматический запуск признан зависшим.',
                           last_autorun_message
                       ),

                   current_run_uuid = NULL,
                   current_run_mode = NULL,
                   current_run_started_at = NULL,
                   current_run_heartbeat_at = NULL,
                   updated_by =
                       'pipeline-dispatcher',
                   updated_at =
                       UTC_TIMESTAMP(6)

             WHERE id = 1
            """,
            (
                mode,
                mode,
                mode,
                mode,
                mode,
            ),
        )

    finally:
        cursor.close()

    log(
        f"Сброшен зависший запуск "
        f"{run_uuid}; "
        f"режим={mode or 'UNKNOWN'}."
    )

    return True


def claim_run(
    options: dict[str, Any],
    stale_seconds: int,
) -> dict[str, Any] | None:
    with db_write(
        options
    ) as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    pipeline_enabled,
                    autorun_enabled,
                    autorun_running,
                    authorization_enabled,
                    schedule_code,
                    starts_at_utc,
                    last_autorun_slot_utc,
                    test_running,
                    last_test_status,
                    current_run_uuid,
                    current_run_mode,
                    current_run_heartbeat_at
                FROM sys_pipeline_config
                WHERE id = 1
                FOR UPDATE
                """
            )

            row = cursor.fetchone()

            if row is None:
                raise DispatcherError(
                    (
                        "Строка "
                        "sys_pipeline_config "
                        "id=1 не найдена."
                    )
                )

            prepared = dict(
                row
            )

            if recover_stale_run(
                connection,
                prepared,
                stale_seconds,
            ):
                return None

            if prepared.get(
                "current_run_uuid"
            ):
                return None

            mode: str | None = None
            slot: datetime | None = None

            if (
                bool(
                    prepared[
                        "test_running"
                    ]
                )
                and str(
                    prepared[
                        "last_test_status"
                    ]
                ).upper()
                == "REQUESTED"
            ):
                mode = "TEST"

            elif (
                bool(
                    prepared[
                        "pipeline_enabled"
                    ]
                )
                and bool(
                    prepared[
                        "autorun_enabled"
                    ]
                )
                and bool(
                    prepared[
                        "authorization_enabled"
                    ]
                )
                and not bool(
                    prepared[
                        "autorun_running"
                    ]
                )
            ):
                slot = due_slot(
                    prepared[
                        "starts_at_utc"
                    ],
                    str(
                        prepared[
                            "schedule_code"
                        ]
                    ),
                    utc_now(),
                )

                previous_slot = as_utc(
                    prepared[
                        "last_autorun_slot_utc"
                    ]
                )

                if (
                    slot is not None
                    and (
                        previous_slot is None
                        or slot > previous_slot
                    )
                ):
                    mode = "AUTORUN"

            if mode is None:
                return None

            run_uuid = str(
                uuid4()
            )

            if mode == "TEST":
                cursor.execute(
                    """
                    UPDATE sys_pipeline_config
                       SET test_running = 1,
                           last_test_status =
                               'RUNNING',
                           last_test_message =
                               'Windows-диспетчер начал тестовый запуск.',
                           current_run_uuid = %s,
                           current_run_mode =
                               'TEST',
                           current_run_started_at =
                               UTC_TIMESTAMP(6),
                           current_run_heartbeat_at =
                               UTC_TIMESTAMP(6),
                           updated_by =
                               'pipeline-dispatcher',
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = 1
                    """,
                    (
                        run_uuid,
                    ),
                )

            else:
                cursor.execute(
                    """
                    UPDATE sys_pipeline_config
                       SET autorun_running = 1,
                           last_autorun_slot_utc = %s,
                           last_autorun_status =
                               'RUNNING',
                           last_autorun_started_at =
                               UTC_TIMESTAMP(6),
                           last_autorun_finished_at =
                               NULL,
                           last_autorun_message =
                               'Windows-диспетчер начал автоматический запуск.',
                           current_run_uuid = %s,
                           current_run_mode =
                               'AUTORUN',
                           current_run_started_at =
                               UTC_TIMESTAMP(6),
                           current_run_heartbeat_at =
                               UTC_TIMESTAMP(6),
                           updated_by =
                               'pipeline-dispatcher',
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = 1
                    """,
                    (
                        mysql_datetime(
                            slot
                        ),
                        run_uuid,
                    ),
                )

            return {
                "uuid": run_uuid,
                "mode": mode,
                "slot": slot,
            }

        finally:
            cursor.close()


def heartbeat(
    options: dict[str, Any],
    run_uuid: str,
) -> None:
    with db_write(
        options
    ) as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_pipeline_config
                   SET current_run_heartbeat_at =
                           UTC_TIMESTAMP(6),
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE id = 1
                   AND current_run_uuid = %s
                """,
                (
                    run_uuid,
                ),
            )

            if cursor.rowcount != 1:
                raise DispatcherError(
                    (
                        "Диспетчер потерял "
                        "блокировку запуска."
                    )
                )

        finally:
            cursor.close()


def pipeline_enabled(
    options: dict[str, Any],
) -> bool:
    with db_read(
        options
    ) as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT pipeline_enabled
                FROM sys_pipeline_config
                WHERE id = 1
                """
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    return bool(
        row
        and row[0]
    )


def load_entities(
    options: dict[str, Any],
    mode: str,
) -> list[dict[str, Any]]:
    del mode

    query = """
        SELECT
            entity.id,
            entity.inn,
            entity.short_name,
            entity.status,
            entity.timezone_name,

            UPPER(
                REPLACE(
                    certificate.thumbprint,
                    ' ',
                    ''
                )
            ) AS thumbprint,

            certificate.store_location,
            certificate.store_name,
            certificate.diskontrol_profile,

            CASE
                WHEN pipeline.export_upd_enabled = 1
                 AND EXISTS (
                    SELECT 1
                    FROM sys_pipeline_task_entity
                         export_selection
                    WHERE export_selection.task_code =
                          'EXPORT_UPD'
                      AND export_selection.legal_entity_id =
                          entity.id
                 )
                THEN 1
                ELSE 0
            END AS export_enabled

        FROM legal_entity entity

        JOIN legal_entity_integration_config
             integration
          ON integration.legal_entity_id =
             entity.id

        JOIN legal_entity_certificate
             certificate
          ON certificate.id = (
              SELECT latest_certificate.id
              FROM legal_entity_certificate
                   latest_certificate
              WHERE latest_certificate.legal_entity_id =
                    entity.id
                AND latest_certificate.is_active = 1
              ORDER BY latest_certificate.id DESC
              LIMIT 1
          )

        JOIN sys_pipeline_config pipeline
          ON pipeline.id = 1

        JOIN sys_pipeline_task_entity
             auth_selection
          ON auth_selection.legal_entity_id =
             entity.id
         AND auth_selection.task_code =
             'AUTHORIZATION'

        WHERE entity.status IN (
            'SETUP',
            'ACTIVE'
        )
          AND pipeline.authorization_enabled = 1
          AND integration.true_api_enabled = 1
          AND certificate.diskontrol_profile
              IS NOT NULL
          AND TRIM(
              certificate.diskontrol_profile
          ) <> ''

        ORDER BY entity.id
    """

    with db_read(
        options
    ) as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                query
            )

            rows = [
                dict(
                    row
                )
                for row
                in cursor.fetchall()
            ]

        finally:
            cursor.close()

    result: list[
        dict[str, Any]
    ] = []

    for row in rows:
        entity = {
            "id": int(
                row[
                    "id"
                ]
            ),
            "inn": str(
                row[
                    "inn"
                ]
            ).strip(),
            "short_name": str(
                row[
                    "short_name"
                ]
                or ""
            ).strip(),
            "status": str(
                row[
                    "status"
                ]
            ),
            "timezone_name": str(
                row[
                    "timezone_name"
                ]
                or "Europe/Moscow"
            ).strip(),
            "thumbprint": str(
                row[
                    "thumbprint"
                ]
            ).strip().upper(),
            "store_location": str(
                row[
                    "store_location"
                ]
                or "CurrentUser"
            ).strip(),
            "store_name": str(
                row[
                    "store_name"
                ]
                or "My"
            ).strip(),
            "diskontrol_profile": str(
                row[
                    "diskontrol_profile"
                ]
            ).strip(),
            "export_enabled": bool(
                row[
                    "export_enabled"
                ]
            ),
        }

        if (
            not entity[
                "inn"
            ].isdigit()
            or len(
                entity[
                    "inn"
                ]
            )
            not in {
                10,
                12,
            }
        ):
            raise DispatcherError(
                (
                    "Некорректный ИНН "
                    "у организации id="
                    f"{entity['id']}."
                )
            )

        if len(
            entity[
                "thumbprint"
            ]
        ) != 40:
            raise DispatcherError(
                (
                    "Некорректный Thumbprint "
                    "у организации id="
                    f"{entity['id']}."
                )
            )

        if entity[
            "store_location"
        ] not in {
            "CurrentUser",
            "LocalMachine",
        }:
            raise DispatcherError(
                (
                    "Некорректное хранилище "
                    "сертификата у организации "
                    f"id={entity['id']}: "
                    f"{entity['store_location']}."
                )
            )

        result.append(
            entity
        )

    return result


def create_auth_job(
    options: dict[str, Any],
    run_uuid: str,
    entity: dict[str, Any],
    stale_minutes: int,
) -> str | None:
    job_uuid = str(
        uuid4()
    )

    requested_by = (
        f"pipeline:{run_uuid}"
    )

    cancelled_count = 0

    with db_write(
        options
    ) as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_auth_job auth_job

                LEFT JOIN sys_pipeline_config
                          pipeline
                  ON pipeline.id = 1
                 AND auth_job.requested_by =
                     CONCAT(
                         'pipeline:',
                         pipeline.current_run_uuid
                     )

                   SET auth_job.status =
                           'CANCELLED',
                       auth_job.last_error_type =
                           'STALE_AUTH_JOB',
                       auth_job.last_error_message =
                           'Stale unclaimed authorization job was reset.',
                       auth_job.finished_at =
                           UTC_TIMESTAMP(6),
                       auth_job.updated_at =
                           UTC_TIMESTAMP(6)

                 WHERE auth_job.legal_entity_id = %s
                   AND auth_job.status IN (
                       'PENDING',
                       'WAITING_CERTIFICATE',
                       'PROCESSING'
                   )
                   AND auth_job.claimed_by_agent_id
                       IS NULL
                   AND (
                       (
                           auth_job.requested_by
                               LIKE 'pipeline:%%'
                           AND pipeline.id IS NULL
                       )
                       OR auth_job.updated_at <
                          TIMESTAMPADD(
                              MINUTE,
                              -%s,
                              UTC_TIMESTAMP(6)
                          )
                   )
                """,
                (
                    entity[
                        "id"
                    ],
                    stale_minutes,
                ),
            )

            cancelled_count = (
                cursor.rowcount
            )

            cursor.execute(
                """
                INSERT INTO sys_auth_job (
                    job_uuid,
                    legal_entity_id,
                    requested_by,
                    requested_at,
                    status,
                    certificate_thumbprint,
                    started_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    UTC_TIMESTAMP(6),
                    'PROCESSING',
                    %s,
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    job_uuid,
                    entity[
                        "id"
                    ],
                    requested_by,
                    entity[
                        "thumbprint"
                    ],
                ),
            )

        except IntegrityError as exc:
            if exc.errno == 1062:
                return None

            raise

        finally:
            cursor.close()

    if cancelled_count > 0:
        log(
            (
                "Организация "
                f"id={entity['id']}: "
                "закрыто устаревших заданий "
                "авторизации: "
                f"{cancelled_count}."
            )
        )

    return job_uuid


def finish_auth(
    options: dict[str, Any],
    job_uuid: str,
    status: str,
    *,
    sync_uuid: str | None = None,
    error_type: str | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    if status not in AUTH_TERMINAL_STATUSES:
        raise ValueError(
            (
                "Недопустимый статус "
                f"auth job: {status}"
            )
        )

    with db_write(
        options
    ) as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_auth_job
                   SET status = %s,
                       sync_job_uuid = %s,
                       last_error_type = %s,
                       last_error_message = %s,
                       result_json = %s,
                       finished_at =
                           UTC_TIMESTAMP(6),
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE job_uuid = %s
                   AND status IN (
                       'PENDING',
                       'WAITING_CERTIFICATE',
                       'PROCESSING'
                   )
                """,
                (
                    status,
                    sync_uuid,
                    (
                        error_type[
                            :128
                        ]
                        if error_type
                        else None
                    ),
                    (
                        message[
                            :2000
                        ]
                        if message
                        else None
                    ),
                    (
                        json_text(
                            result
                        )
                        if result is not None
                        else None
                    ),
                    job_uuid,
                ),
            )

        finally:
            cursor.close()


def authorize(
    root: Path,
    env_file: Path,
    dkcl_path: Path,
    entity: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    command = [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(
            root
            / "tools"
            / "authorize_pipeline_entity.ps1"
        ),
        "-DeviceName",
        entity[
            "diskontrol_profile"
        ],
        "-Inn",
        entity[
            "inn"
        ],
        "-CertificateThumbprint",
        entity[
            "thumbprint"
        ],
        "-StoreLocation",
        entity[
            "store_location"
        ],
        "-StoreName",
        entity[
            "store_name"
        ],
        "-EnvFile",
        str(
            env_file
        ),
        "-DkclPath",
        str(
            dkcl_path
        ),
        "-CertificateWaitSeconds",
        str(
            args.certificate_wait_seconds
        ),
        "-AuthTimeoutSeconds",
        str(
            args.auth_timeout_seconds
        ),
    ]

    if args.allow_pin_prompt:
        command.append(
            "-AllowPinPrompt"
        )

    completed = run_command(
        command,
        root=root,
        name=(
            "Авторизация id="
            f"{entity['id']}"
        ),
        allowed={
            0,
            2,
            3,
            4,
            10,
        },
    )

    return last_json(
        completed.stdout,
        "authorize_pipeline_entity.ps1",
    )


def resolve_timezone(
    timezone_name: str,
):
    prepared = (
        timezone_name.strip()
        or "Europe/Moscow"
    )

    try:
        return ZoneInfo(
            prepared
        )

    except ZoneInfoNotFoundError as exc:
        aliases = {
            "EUROPE/MOSCOW": timezone(
                timedelta(
                    hours=3
                ),
                name="MSK",
            ),
            "RUSSIAN STANDARD TIME": timezone(
                timedelta(
                    hours=3
                ),
                name="MSK",
            ),
            "MSK": timezone(
                timedelta(
                    hours=3
                ),
                name="MSK",
            ),
            "UTC": timezone.utc,
            "ETC/UTC": timezone.utc,
        }

        fallback = aliases.get(
            prepared.upper()
        )

        if fallback is not None:
            log(
                (
                    "Системная база часовых поясов "
                    "не содержит "
                    f"{prepared}; используется "
                    "встроенный fallback."
                )
            )

            return fallback

        raise DispatcherError(
            (
                "Не найден часовой пояс "
                f"{prepared}. Установите пакет "
                "tzdata в Windows-окружение Python."
            )
        ) from exc


def metadata_sync(
    root: Path,
    env_file: Path,
    entity_id: int,
    token: str,
    certificate: dict[str, Any],
) -> dict[str, Any]:
    source = json_text(
        {
            "token": token,
            "certificate":
                certificate,
        }
    ).encode(
        "utf-8"
    )

    payload = (
        base64.b64encode(
            source
        ).decode(
            "ascii"
        )
        + "\n"
    )

    completed = run_command(
        compose(
            env_file
        )
        + [
            "--profile",
            "tools",
            "run",
            "--rm",
            "-T",
            "--entrypoint",
            "python",
            "sync-worker",
            "-m",
            "app.legal_entity_metadata",
            "sync",
            "--entity-id",
            str(
                entity_id
            ),
        ],
        root=root,
        name=(
            "Метаданные id="
            f"{entity_id}"
        ),
        stdin=payload,
    )

    return last_json(
        completed.stdout,
        (
            "app.legal_entity_metadata "
            "sync"
        ),
    )


def activate(
    root: Path,
    env_file: Path,
    entity_id: int,
) -> None:
    run_command(
        compose(
            env_file
        )
        + [
            "--profile",
            "tools",
            "run",
            "--rm",
            "-T",
            "--entrypoint",
            "python",
            "sync-worker",
            "-m",
            "app.legal_entities",
            "activate",
            "--entity-id",
            str(
                entity_id
            ),
        ],
        root=root,
        name=(
            "Активация id="
            f"{entity_id}"
        ),
    )


def export_period(
    options: dict[str, Any],
    mode: str,
    timezone_name: str,
) -> tuple[
    datetime,
    datetime,
]:
    del mode

    zone = resolve_timezone(
        timezone_name
    )

    with db_read(
        options
    ) as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    export_period_from,
                    export_period_to
                FROM sys_pipeline_config
                WHERE id = 1
                """
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if (
        row is None
        or row[0] is None
        or row[1] is None
    ):
        raise DispatcherError(
            (
                "Для экспорта УПД "
                "не заполнен период."
            )
        )

    start_date: date = row[0]
    end_date: date = row[1]

    date_from = datetime.combine(
        start_date,
        day_time.min,
        tzinfo=zone,
    )

    date_to = datetime.combine(
        end_date
        + timedelta(
            days=1
        ),
        day_time.min,
        tzinfo=zone,
    )

    return (
        date_from.astimezone(
            timezone.utc
        ),
        date_to.astimezone(
            timezone.utc
        ),
    )


def publish(
    root: Path,
    env_file: Path,
    entity_id: int,
    date_from: datetime,
    date_to: datetime,
    requested_by: str,
) -> dict[str, Any]:
    completed = run_command(
        compose(
            env_file
        )
        + [
            "--profile",
            "tools",
            "run",
            "--rm",
            "-T",
            "--entrypoint",
            "python",
            "sync-worker",
            "-m",
            "app.rabbitmq_jobs",
            "--entity-id",
            str(
                entity_id
            ),
            "--date-from",
            iso_utc(
                date_from
            ),
            "--date-to",
            iso_utc(
                date_to
            ),
            "--continue-on-error",
            "--requested-by",
            requested_by,
        ],
        root=root,
        name=(
            "Публикация id="
            f"{entity_id}"
        ),
        allowed={
            0,
            3,
        },
    )

    return last_json(
        completed.stdout,
        "app.rabbitmq_jobs",
    )


def active_sync_job(
    options: dict[str, Any],
    entity_id: int,
) -> dict[str, Any] | None:
    with db_read(
        options
    ) as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    job_uuid,
                    status,
                    last_error_type,
                    last_error_message
                FROM sys_sync_job
                WHERE legal_entity_id = %s
                  AND status IN (
                      'CREATED',
                      'PUBLISHED',
                      'PROCESSING',
                      'RETRY_WAIT'
                  )
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    entity_id,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        return None

    return dict(
        row
    )


def worker_supervisor(
    root: Path,
    env_file: Path,
    entity_id: int,
) -> int:
    token = sys.stdin.readline().strip()

    if not token:
        raise DispatcherError(
            (
                "Worker supervisor "
                "не получил токен через stdin."
            )
        )

    values = read_env(
        env_file
    )

    retry_delay_seconds = int(
        os.getenv(
            "RABBITMQ_RETRY_DELAY_SECONDS",
            values.get(
                "RABBITMQ_RETRY_DELAY_SECONDS",
                "300",
            ),
        )
    )

    command = (
        compose(
            env_file
        )
        + [
            "--profile",
            "tools",
            "run",
            "--rm",
            "-T",
            "--entrypoint",
            "python",
            "sync-worker",
            "-u",
            "-m",
            "app.rabbitmq_worker",
            "--entity-id",
            str(
                entity_id
            ),
            "--once",
        ]
    )

    try:
        cycle = 0

        while True:
            cycle += 1

            log(
                (
                    "Worker supervisor: "
                    f"entity={entity_id}; "
                    f"cycle={cycle}."
                )
            )

            completed = subprocess.run(
                command,
                cwd=str(
                    root
                ),
                input=(
                    token
                    + "\n"
                ),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=sys.stdout,
                stderr=subprocess.STDOUT,
                check=False,
                env={
                    **os.environ,
                    "PYTHONIOENCODING":
                        "utf-8",
                    "PYTHONUTF8": "1",
                },
            )

            exit_code = int(
                completed.returncode
            )

            log(
                (
                    "Worker supervisor: "
                    f"entity={entity_id}; "
                    f"exit_code={exit_code}."
                )
            )

            if exit_code == 0:
                return 0

            if (
                exit_code
                in WORKER_RETRY_EXIT_CODES
            ):
                delay = (
                    retry_delay_seconds
                    + 5
                )

                log(
                    (
                        "Worker supervisor: "
                        f"entity={entity_id}; "
                        f"повтор через {delay} секунд."
                    )
                )

                time.sleep(
                    delay
                )

                continue

            return exit_code

    finally:
        token = ""


def start_worker(
    root: Path,
    env_file: Path,
    entity_id: int,
    token: str,
    run_uuid: str,
) -> tuple[
    int,
    str,
]:
    directory = (
        root
        / "logs"
        / "pipeline_dispatcher"
        / "workers"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    log_path = directory / (
        f"entity_{entity_id}_"
        f"{timestamp}_"
        f"{run_uuid[:8]}.log"
    )

    handle = log_path.open(
        "w",
        encoding="utf-8",
        buffering=1,
    )

    creation_flags = 0

    if (
        os.name == "nt"
        and hasattr(
            subprocess,
            "CREATE_NO_WINDOW",
        )
    ):
        creation_flags = (
            subprocess
            .CREATE_NO_WINDOW
        )

    process = subprocess.Popen(
        [
            sys.executable,
            str(
                Path(
                    __file__
                ).resolve()
            ),
            "--worker-entity-id",
            str(
                entity_id
            ),
            "--env-file",
            str(
                env_file
            ),
        ],
        cwd=str(
            root
        ),
        stdin=subprocess.PIPE,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PYTHONIOENCODING":
                "utf-8",
            "PYTHONUTF8": "1",
        },
        creationflags=(
            creation_flags
        ),
    )

    try:
        if process.stdin is None:
            raise DispatcherError(
                (
                    "Не открыт stdin "
                    "worker supervisor."
                )
            )

        process.stdin.write(
            token
            + "\n"
        )

        process.stdin.flush()
        process.stdin.close()

    except Exception:
        process.terminate()
        handle.close()
        raise

    handle.close()

    return (
        process.pid,
        str(
            log_path
        ),
    )


def process_entity(
    options: dict[str, Any],
    root: Path,
    env_file: Path,
    dkcl_path: Path,
    run_info: dict[str, Any],
    entity: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    auth_uuid = create_auth_job(
        options,
        run_info[
            "uuid"
        ],
        entity,
        args.auth_job_stale_minutes,
    )

    if auth_uuid is None:
        return {
            "entity_id": entity[
                "id"
            ],
            "inn": entity[
                "inn"
            ],
            "status":
                "SKIPPED_ACTIVE_AUTH_JOB",
            "message": (
                "У организации уже есть "
                "действующее задание авторизации."
            ),
        }

    token: str | None = None

    try:
        auth_result = authorize(
            root,
            env_file,
            dkcl_path,
            entity,
            args,
        )

        auth_status = str(
            auth_result.get(
                "status"
            )
            or "ERROR"
        ).upper()

        if auth_status.startswith(
            "SKIPPED_"
        ):
            safe_result = {
                key: value
                for key, value
                in auth_result.items()
                if key != "token"
            }

            finish_auth(
                options,
                auth_uuid,
                "CANCELLED",
                error_type=
                    auth_status,
                message=str(
                    auth_result.get(
                        "message"
                    )
                    or auth_status
                ),
                result=
                    safe_result,
            )

            return {
                "entity_id": entity[
                    "id"
                ],
                "inn": entity[
                    "inn"
                ],
                "status":
                    auth_status,
                "message": str(
                    auth_result.get(
                        "message"
                    )
                    or (
                        "Организация "
                        "пропущена."
                    )
                ),
            }

        if auth_status != "SUCCESS":
            raise DispatcherError(
                str(
                    auth_result.get(
                        "message"
                    )
                    or (
                        "Ошибка "
                        "авторизации."
                    )
                )
            )

        token = str(
            auth_result.get(
                "token"
            )
            or ""
        ).strip()

        certificate = auth_result.get(
            "certificate"
        )

        if (
            not token
            or not isinstance(
                certificate,
                dict,
            )
        ):
            raise DispatcherError(
                (
                    "Авторизация не вернула "
                    "токен или сертификат."
                )
            )

        result: dict[str, Any] = {
            "entity_id": entity[
                "id"
            ],
            "inn": entity[
                "inn"
            ],
            "short_name": entity[
                "short_name"
            ],
            "status": "SUCCESS",
            "export_requested": False,
            "sync_job_uuid": None,
            "worker_started": False,
            "worker_pid": None,
            "worker_log": None,
        }

        if entity[
            "export_enabled"
        ]:
            metadata = metadata_sync(
                root,
                env_file,
                entity[
                    "id"
                ],
                token,
                certificate,
            )

            activate(
                root,
                env_file,
                entity[
                    "id"
                ],
            )

            (
                date_from,
                date_to,
            ) = export_period(
                options,
                run_info[
                    "mode"
                ],
                entity[
                    "timezone_name"
                ],
            )

            published = publish(
                root,
                env_file,
                entity[
                    "id"
                ],
                date_from,
                date_to,
                (
                    "pipeline:"
                    + run_info[
                        "uuid"
                    ]
                ),
            )

            publish_status = str(
                published.get(
                    "status"
                )
                or ""
            ).upper()

            sync_uuid: str | None = None
            worker_required = False

            if publish_status == "PUBLISHED":
                sync_uuid = str(
                    published.get(
                        "job_id"
                    )
                    or ""
                ).strip()

                worker_required = True

            elif (
                publish_status
                == "ACTIVE_JOB_EXISTS"
            ):
                sync_uuid = str(
                    published.get(
                        "active_job_id"
                    )
                    or ""
                ).strip()

                active_status = str(
                    published.get(
                        "active_status"
                    )
                    or ""
                ).upper()

                if not sync_uuid:
                    active = active_sync_job(
                        options,
                        entity[
                            "id"
                        ],
                    )

                    if active is not None:
                        sync_uuid = str(
                            active[
                                "job_uuid"
                            ]
                        ).strip()

                        active_status = str(
                            active[
                                "status"
                            ]
                        ).upper()

                if active_status == "CREATED":
                    raise DispatcherError(
                        (
                            "Активное sync-задание "
                            "осталось в статусе CREATED "
                            "и не опубликовано."
                        )
                    )

                worker_required = (
                    active_status
                    in {
                        "PUBLISHED",
                        "RETRY_WAIT",
                    }
                )

                publish_status = (
                    "ACTIVE_"
                    + active_status
                )

            elif publish_status in {
                "PROCESSING",
                "RETRY_WAIT",
                "SUCCESS",
            }:
                sync_uuid = str(
                    published.get(
                        "job_id"
                    )
                    or ""
                ).strip()

                worker_required = (
                    publish_status
                    == "RETRY_WAIT"
                )

            else:
                raise DispatcherError(
                    (
                        "Неожиданный статус "
                        "publisher: "
                        f"{publish_status or 'EMPTY'}."
                    )
                )

            if not sync_uuid:
                raise DispatcherError(
                    (
                        "Publisher не вернул UUID "
                        "sync-задания."
                    )
                )

            worker_pid: int | None = None
            worker_log: str | None = None

            if worker_required:
                (
                    worker_pid,
                    worker_log,
                ) = start_worker(
                    root,
                    env_file,
                    entity[
                        "id"
                    ],
                    token,
                    run_info[
                        "uuid"
                    ],
                )

            result.update(
                {
                    "participant_status": (
                        metadata.get(
                            "participant_status"
                        )
                    ),
                    "product_group_count": (
                        metadata.get(
                            "product_group_count"
                        )
                    ),
                    "export_requested": True,
                    "publish_status":
                        publish_status,
                    "sync_job_uuid":
                        sync_uuid,
                    "worker_started":
                        worker_required,
                    "worker_pid":
                        worker_pid,
                    "worker_log":
                        worker_log,
                    "date_from": iso_utc(
                        date_from
                    ),
                    "date_to": iso_utc(
                        date_to
                    ),
                }
            )

        finish_auth(
            options,
            auth_uuid,
            "SUCCESS",
            sync_uuid=result.get(
                "sync_job_uuid"
            ),
            result=result,
        )

        return result

    except Exception as exc:
        finish_auth(
            options,
            auth_uuid,
            "ERROR",
            error_type=
                type(
                    exc
                ).__name__,
            message=str(
                exc
            ),
            result={
                "entity_id": entity[
                    "id"
                ],
                "inn": entity[
                    "inn"
                ],
                "device_name": entity[
                    "diskontrol_profile"
                ],
            },
        )

        return {
            "entity_id": entity[
                "id"
            ],
            "inn": entity[
                "inn"
            ],
            "status": "ERROR",
            "error_type":
                type(
                    exc
                ).__name__,
            "message": str(
                exc
            ),
        }

    finally:
        token = None


def wait_for_sync_jobs(
    options: dict[str, Any],
    run_uuid: str,
    results: list[dict[str, Any]],
    poll_seconds: int,
    timeout_seconds: int,
) -> None:
    tracked = {
        str(
            item[
                "sync_job_uuid"
            ]
        ): item
        for item in results
        if item.get(
            "sync_job_uuid"
        )
    }

    if not tracked:
        return

    deadline = (
        time.monotonic()
        + timeout_seconds
    )

    while True:
        heartbeat(
            options,
            run_uuid,
        )

        placeholders = ",".join(
            [
                "%s"
            ]
            * len(
                tracked
            )
        )

        with db_read(
            options
        ) as connection:
            cursor = connection.cursor(
                dictionary=True
            )

            try:
                cursor.execute(
                    (
                        "SELECT "
                        "job_uuid, "
                        "status, "
                        "last_error_type, "
                        "last_error_message "
                        "FROM sys_sync_job "
                        "WHERE job_uuid IN ("
                        + placeholders
                        + ")"
                    ),
                    tuple(
                        tracked.keys()
                    ),
                )

                rows = {
                    str(
                        row[
                            "job_uuid"
                        ]
                    ): dict(
                        row
                    )
                    for row
                    in cursor.fetchall()
                }

            finally:
                cursor.close()

        unfinished: list[str] = []

        for (
            job_uuid,
            item,
        ) in tracked.items():
            row = rows.get(
                job_uuid
            )

            if row is None:
                item[
                    "status"
                ] = "ERROR"

                item[
                    "error_type"
                ] = (
                    "SYNC_JOB_NOT_FOUND"
                )

                item[
                    "message"
                ] = (
                    "Связанное задание "
                    "sys_sync_job не найдено."
                )

                continue

            sync_status = str(
                row[
                    "status"
                ]
            ).upper()

            item[
                "sync_status"
            ] = sync_status

            if (
                sync_status
                not in
                SYNC_TERMINAL_STATUSES
            ):
                unfinished.append(
                    job_uuid
                )

                continue

            if sync_status != "SUCCESS":
                item[
                    "status"
                ] = "ERROR"

                item[
                    "error_type"
                ] = str(
                    row.get(
                        "last_error_type"
                    )
                    or sync_status
                )

                item[
                    "message"
                ] = str(
                    row.get(
                        "last_error_message"
                    )
                    or (
                        "Sync job завершён "
                        "со статусом "
                        f"{sync_status}."
                    )
                )

        if not unfinished:
            return

        if (
            time.monotonic()
            >= deadline
        ):
            for job_uuid in unfinished:
                tracked[
                    job_uuid
                ][
                    "status"
                ] = "ERROR"

                tracked[
                    job_uuid
                ][
                    "error_type"
                ] = "SYNC_TIMEOUT"

                tracked[
                    job_uuid
                ][
                    "message"
                ] = (
                    "Ожидание sync job "
                    f"превысило "
                    f"{timeout_seconds} секунд."
                )

            return

        log(
            (
                "Ожидаю завершение "
                "заданий скачивания: "
                f"{len(unfinished)}."
            )
        )

        time.sleep(
            poll_seconds
        )


def finish_run(
    options: dict[str, Any],
    run_info: dict[str, Any],
    results: list[dict[str, Any]],
    fatal_error: BaseException | None,
) -> None:
    success_count = sum(
        item.get(
            "status"
        )
        == "SUCCESS"
        for item in results
    )

    skipped_count = sum(
        str(
            item.get(
                "status"
            )
            or ""
        ).startswith(
            "SKIPPED_"
        )
        for item in results
    )

    error_count = sum(
        item.get(
            "status"
        )
        == "ERROR"
        for item in results
    )

    if fatal_error is not None:
        final_status = "ERROR"

        message = (
            "Аварийное завершение: "
            f"{type(fatal_error).__name__}: "
            f"{fatal_error}"
        )

    elif not results:
        final_status = "ERROR"

        message = (
            "Нет организаций, "
            "подходящих для запуска."
        )

    elif (
        error_count == 0
        and skipped_count == 0
        and success_count
        == len(
            results
        )
    ):
        final_status = "SUCCESS"

        message = (
            "Запуск завершён. "
            f"Организаций: {len(results)}; "
            f"успешно: {success_count}."
        )

    elif (
        success_count > 0
        or skipped_count > 0
    ):
        final_status = "PARTIAL"

        message = (
            f"Успешно: {success_count}; "
            f"пропущено: {skipped_count}; "
            f"ошибок: {error_count}."
        )

    else:
        final_status = "ERROR"

        message = (
            f"Успешно: {success_count}; "
            f"пропущено: {skipped_count}; "
            f"ошибок: {error_count}."
        )

    with db_write(
        options
    ) as connection:
        cursor = connection.cursor()

        try:
            if (
                run_info[
                    "mode"
                ]
                == "TEST"
            ):
                cursor.execute(
                    """
                    UPDATE sys_pipeline_config
                       SET test_running = 0,
                           last_test_status = %s,
                           last_test_message = %s,
                           current_run_uuid = NULL,
                           current_run_mode = NULL,
                           current_run_started_at = NULL,
                           current_run_heartbeat_at = NULL,
                           updated_by =
                               'pipeline-dispatcher',
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = 1
                       AND current_run_uuid = %s
                    """,
                    (
                        final_status,
                        message[
                            :1000
                        ],
                        run_info[
                            "uuid"
                        ],
                    ),
                )

            else:
                cursor.execute(
                    """
                    UPDATE sys_pipeline_config
                       SET autorun_running = 0,
                           last_autorun_status = %s,
                           last_autorun_finished_at =
                               UTC_TIMESTAMP(6),
                           last_autorun_message = %s,
                           current_run_uuid = NULL,
                           current_run_mode = NULL,
                           current_run_started_at = NULL,
                           current_run_heartbeat_at = NULL,
                           updated_by =
                               'pipeline-dispatcher',
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = 1
                       AND current_run_uuid = %s
                    """,
                    (
                        final_status,
                        message[
                            :1000
                        ],
                        run_info[
                            "uuid"
                        ],
                    ),
                )

        finally:
            cursor.close()

    log(
        message
    )


def execute_run(
    options: dict[str, Any],
    root: Path,
    env_file: Path,
    dkcl_path: Path,
    run_info: dict[str, Any],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    entities = load_entities(
        options,
        run_info[
            "mode"
        ],
    )

    results: list[
        dict[str, Any]
    ] = []

    log(
        (
            f"Запуск {run_info['uuid']}; "
            f"режим={run_info['mode']}; "
            f"организаций={len(entities)}."
        )
    )

    if not entities:
        log(
            (
                "Нет организаций, "
                "подходящих для запуска."
            )
        )

        return results

    for entity in entities:
        heartbeat(
            options,
            run_info[
                "uuid"
            ],
        )

        if (
            run_info[
                "mode"
            ]
            == "AUTORUN"
            and not pipeline_enabled(
                options
            )
        ):
            log(
                (
                    "Получен Стоп. "
                    "Новые авторизации "
                    "не запускаются."
                )
            )

            break

        log(
            (
                "Организация "
                f"id={entity['id']}; "
                f"ИНН={entity['inn']}; "
                "профиль="
                f"{entity['diskontrol_profile']}."
            )
        )

        result = process_entity(
            options,
            root,
            env_file,
            dkcl_path,
            run_info,
            entity,
            args,
        )

        results.append(
            result
        )

        log(
            json_text(
                result
            )
        )

    wait_for_sync_jobs(
        options,
        run_info[
            "uuid"
        ],
        results,
        poll_seconds=(
            args.sync_poll_seconds
        ),
        timeout_seconds=(
            args.run_timeout_seconds
        ),
    )

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Windows-диспетчер авторизации "
            "и RabbitMQ-заданий ГИС МТ."
        )
    )

    parser.add_argument(
        "--env-file"
    )

    parser.add_argument(
        "--dkcl-path",
        default=(
            r"C:\Users\kudryavcev"
            r"\Desktop\dkcl64.exe"
        ),
    )

    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=1,
    )

    parser.add_argument(
        "--sync-poll-seconds",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=1800,
    )

    parser.add_argument(
        "--auth-job-stale-minutes",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--run-timeout-seconds",
        type=int,
        default=21600,
    )

    parser.add_argument(
        "--certificate-wait-seconds",
        type=int,
        default=60,
    )

    parser.add_argument(
        "--auth-timeout-seconds",
        type=int,
        default=60,
    )

    parser.add_argument(
        "--allow-pin-prompt",
        action="store_true",
    )

    parser.add_argument(
        "--once",
        action="store_true",
    )

    parser.add_argument(
        "--worker-entity-id",
        type=int,
        default=0,
        help=argparse.SUPPRESS,
    )

    return parser.parse_args()


def validate_args(
    args: argparse.Namespace,
) -> None:
    values = {
        "poll_seconds":
            args.poll_seconds,
        "sync_poll_seconds":
            args.sync_poll_seconds,
        "stale_after_seconds":
            args.stale_after_seconds,
        "auth_job_stale_minutes":
            args.auth_job_stale_minutes,
        "run_timeout_seconds":
            args.run_timeout_seconds,
        "certificate_wait_seconds":
            args.certificate_wait_seconds,
        "auth_timeout_seconds":
            args.auth_timeout_seconds,
    }

    for (
        name,
        value,
    ) in values.items():
        if value <= 0:
            raise DispatcherError(
                (
                    f"Параметр {name} "
                    "должен быть больше 0."
                )
            )


def main() -> int:
    args = parse_args()

    validate_args(
        args
    )

    root = (
        Path(
            __file__
        )
        .resolve()
        .parent
        .parent
    )

    env_file = (
        Path(
            args.env_file
        ).resolve()
        if args.env_file
        else root / ".env"
    )

    if args.worker_entity_id:
        return worker_supervisor(
            root,
            env_file,
            args.worker_entity_id,
        )

    dkcl_path = Path(
        args.dkcl_path
    ).resolve()

    if not dkcl_path.is_file():
        raise DispatcherError(
            (
                "dkcl64.exe не найден: "
                f"{dkcl_path}"
            )
        )

    authorization_script = (
        root
        / "tools"
        / "authorize_pipeline_entity.ps1"
    )

    if not authorization_script.is_file():
        raise DispatcherError(
            (
                "Не найден tools/"
                "authorize_pipeline_entity.ps1."
            )
        )

    options = db_options(
        read_env(
            env_file
        )
    )

    run_command(
        compose(
            env_file
        )
        + [
            "up",
            "-d",
            "--wait",
            "mysql",
            "rabbitmq",
        ],
        root=root,
        name=(
            "Запуск MySQL "
            "и RabbitMQ"
        ),
    )

    log(
        (
            "Диспетчер запущен. "
            f"Host={socket.gethostname()}; "
            f"PID={os.getpid()}."
        )
    )

    while True:
        run_info: dict[
            str,
            Any,
        ] | None = None

        results: list[
            dict[str, Any]
        ] = []

        fatal_error: BaseException | None = None

        try:
            run_info = claim_run(
                options,
                args.stale_after_seconds,
            )

            if run_info is None:
                if args.once:
                    log(
                        (
                            "Нет ожидающего запуска. "
                            "Для теста требуется "
                            "test_running=1 и "
                            "last_test_status=REQUESTED."
                        )
                    )

                    return 2

                time.sleep(
                    args.poll_seconds
                )

                continue

            results = execute_run(
                options,
                root,
                env_file,
                dkcl_path,
                run_info,
                args,
            )

        except KeyboardInterrupt:
            log(
                (
                    "Диспетчер остановлен "
                    "пользователем."
                )
            )

            return 130

        except Exception as exc:
            fatal_error = exc

            log(
                (
                    "Ошибка: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )
            )

        finally:
            if run_info is not None:
                try:
                    finish_run(
                        options,
                        run_info,
                        results,
                        fatal_error,
                    )

                except Exception as exc:
                    log(
                        (
                            "Не удалось закрыть запуск: "
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )
                    )

        if args.once:
            return (
                1
                if fatal_error
                else 0
            )

        time.sleep(
            args.poll_seconds
        )


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except Exception as exc:
        print(
            (
                "ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            file=sys.stderr,
            flush=True,
        )

        raise SystemExit(
            1
        ) from exc