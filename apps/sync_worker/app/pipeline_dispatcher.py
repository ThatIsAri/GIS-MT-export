from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
)
from contextlib import contextmanager
from datetime import (
    date,
    datetime,
    time as day_time,
    timedelta,
    timezone,
)
from typing import Any, Iterator
from uuid import uuid4
from zoneinfo import (
    ZoneInfo,
    ZoneInfoNotFoundError,
)

import mysql.connector
from mysql.connector import (
    Error as MySqlError,
    MySQLConnection,
)
from mysql.connector.errors import (
    IntegrityError,
)

from app.rabbitmq_jobs import (
    publish_sync_legal_entity_job,
)
from app.sync_job_repository import (
    ActiveSyncJobExistsError,
)


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

WORKER_TERMINAL_EXIT_CODES = {
    0,
    21,
    31,
    40,
}

_STOP_EVENT = threading.Event()


class DispatcherError(
    RuntimeError
):
    pass


class DispatcherStopped(
    DispatcherError
):
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


def compact_json(
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


def required_env(
    name: str,
) -> str:
    value = os.getenv(
        name,
        "",
    ).strip()

    if not value:
        raise DispatcherError(
            (
                "Не задана переменная "
                f"окружения {name}."
            )
        )

    return value


def integer_env(
    name: str,
    default: int,
) -> int:
    raw_value = os.getenv(
        name,
        str(
            default
        ),
    ).strip()

    try:
        value = int(
            raw_value
        )

    except ValueError as exc:
        raise DispatcherError(
            f"{name} должен быть целым числом."
        ) from exc

    if value <= 0:
        raise DispatcherError(
            f"{name} должен быть больше нуля."
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
        "database": required_env(
            "DB_NAME"
        ),
        "user": required_env(
            "DB_USER"
        ),
        "password": required_env(
            "DB_PASSWORD"
        ),
        "charset": "utf8mb4",
        "collation":
            "utf8mb4_0900_ai_ci",
        "use_unicode": True,
        "connection_timeout": 10,
        "autocommit": False,
    }


def open_mysql_connection(
    settings: dict[
        str,
        Any,
    ],
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
                    **settings
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
                or attempt >= attempts
            ):
                raise

            delay_seconds = (
                initial_delay_seconds
                * attempt
            )

            log(
                "MySQL connection attempt "
                f"{attempt}/{attempts} "
                "failed: "
                f"{error_code}: {exc}. "
                "Retry in "
                f"{delay_seconds:.1f} seconds."
            )

            if _STOP_EVENT.wait(
                delay_seconds
            ):
                raise DispatcherStopped(
                    "Диспетчер остановлен."
                )

    if last_error is not None:
        raise last_error

    raise DispatcherError(
        "Не удалось подключиться к MySQL."
    )


@contextmanager
def db_read(
    settings: dict[
        str,
        Any,
    ],
) -> Iterator[
    MySQLConnection
]:
    connection = open_mysql_connection(
        settings
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
    settings: dict[
        str,
        Any,
    ],
) -> Iterator[
    MySQLConnection
]:
    connection = open_mysql_connection(
        settings
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


def last_json_object(
    output: str,
    operation_name: str,
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
        (
            f"{operation_name} "
            "не вернула итоговый JSON."
        )
    )


def run_python_module(
    module: str,
    arguments: list[str],
    *,
    operation_name: str,
    stdin: str | None = None,
    allowed_exit_codes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            module,
            *arguments,
        ],
        input=stdin,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )

    output = completed.stdout or ""

    for line in output.splitlines():
        log(
            f"[{operation_name}] {line}"
        )

    accepted = (
        allowed_exit_codes
        if allowed_exit_codes is not None
        else {
            0,
        }
    )

    if completed.returncode not in accepted:
        diagnostic = (
            output.strip()
            or "нет диагностического вывода"
        )

        raise DispatcherError(
            f"{operation_name} завершилась "
            f"с кодом {completed.returncode}: "
            f"{diagnostic[-4000:]}"
        )

    return completed


def certificate_agent_url() -> str:
    return required_env(
        "CERTIFICATE_AGENT_URL"
    ).rstrip(
        "/"
    )


def certificate_agent_key() -> str:
    return required_env(
        "CERTIFICATE_AGENT_API_KEY"
    )


def read_json_response(
    response: Any,
) -> dict[str, Any]:
    raw_body = response.read()

    try:
        value = json.loads(
            raw_body.decode(
                "utf-8"
            )
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise DispatcherError(
            (
                "Certificate-agent вернул "
                "некорректный JSON."
            )
        ) from exc

    if not isinstance(
        value,
        dict,
    ):
        raise DispatcherError(
            (
                "Certificate-agent вернул "
                "не JSON-объект."
            )
        )

    return value


def check_certificate_agent(
    timeout_seconds: int = 5,
) -> dict[str, Any]:
    request = urllib.request.Request(
        certificate_agent_url()
        + "/health",
        method="GET",
        headers={
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout_seconds,
    ) as response:
        return read_json_response(
            response
        )


def wait_for_certificate_agent(
    poll_seconds: int,
) -> None:
    while not _STOP_EVENT.is_set():
        try:
            result = check_certificate_agent()

            if (
                str(
                    result.get(
                        "status"
                    )
                    or ""
                ).upper()
                == "OK"
            ):
                log(
                    (
                        "Certificate-agent доступен: "
                        "service="
                        f"{result.get('service')}; "
                        "version="
                        f"{result.get('version')}."
                    )
                )

                return

            log(
                (
                    "Certificate-agent вернул: "
                    f"{compact_json(result)}"
                )
            )

        except Exception as exc:
            log(
                (
                    "Certificate-agent пока "
                    "недоступен: "
                    f"{type(exc).__name__}: "
                    f"{exc}."
                )
            )

        _STOP_EVENT.wait(
            poll_seconds
        )

    raise DispatcherStopped(
        "Диспетчер остановлен."
    )


def authorize_via_agent(
    entity: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    body = compact_json(
        {
            "legal_entity_id": (
                entity[
                    "id"
                ]
            ),
            "device_name": (
                entity[
                    "diskontrol_profile"
                ]
            ),
            "inn": entity[
                "inn"
            ],
            "thumbprint": (
                entity[
                    "thumbprint"
                ]
            ),
            "store_location": (
                entity[
                    "store_location"
                ]
            ),
            "store_name": (
                entity[
                    "store_name"
                ]
            ),
        }
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        certificate_agent_url()
        + "/authorize",
        data=body,
        method="POST",
        headers={
            "Accept":
                "application/json",

            "Content-Type":
                (
                    "application/json; "
                    "charset=utf-8"
                ),

            "Authorization":
                (
                    "Bearer "
                    + certificate_agent_key()
                ),
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            return read_json_response(
                response
            )

    except urllib.error.HTTPError as exc:
        try:
            error_body = read_json_response(
                exc
            )

            message = str(
                error_body.get(
                    "message"
                )
                or error_body
            )

        except Exception:
            message = str(
                exc
            )

        raise DispatcherError(
            (
                "Certificate-agent вернул "
                f"HTTP {exc.code}: {message}"
            )
        ) from exc

    except urllib.error.URLError as exc:
        raise DispatcherError(
            (
                "Certificate-agent "
                f"недоступен: {exc}"
            )
        ) from exc


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
                    "Предыдущий запуск "
                    "Docker-диспетчера "
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
        (
            "Сброшен зависший запуск "
            f"{run_uuid}; "
            f"режим={mode or 'UNKNOWN'}."
        )
    )

    return True


def claim_run(
    settings: dict[str, Any],
    stale_seconds: int,
) -> dict[str, Any] | None:
    with db_write(
        settings
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
                    export_upd_enabled,
                    export_period_from,
                    export_period_to,
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
                               'Docker-диспетчер начал тестовый запуск.',

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

                           last_autorun_slot_utc =
                               %s,

                           last_autorun_status =
                               'RUNNING',

                           last_autorun_started_at =
                               UTC_TIMESTAMP(6),

                           last_autorun_finished_at =
                               NULL,

                           last_autorun_message =
                               'Docker-диспетчер начал автоматический запуск.',

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

                "export_enabled": bool(
                    prepared[
                        "export_upd_enabled"
                    ]
                ),

                "export_period_from": (
                    prepared[
                        "export_period_from"
                    ]
                ),

                "export_period_to": (
                    prepared[
                        "export_period_to"
                    ]
                ),
            }

        finally:
            cursor.close()


def heartbeat(
    settings: dict[str, Any],
    run_uuid: str,
) -> None:
    with db_write(
        settings
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
    settings: dict[str, Any],
) -> bool:
    with db_read(
        settings
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
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
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
        settings
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
    settings: dict[str, Any],
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

    with db_write(
        settings
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
                           'Stale authorization job was reset.',

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

    return job_uuid


def finish_auth(
    settings: dict[str, Any],
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
        settings
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
                        compact_json(
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


def metadata_sync(
    entity_id: int,
    token: str,
    certificate: dict[str, Any],
) -> dict[str, Any]:
    source = compact_json(
        {
            "token": token,
            "certificate": certificate,
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

    completed = run_python_module(
        "app.legal_entity_metadata",
        [
            "sync",
            "--entity-id",
            str(
                entity_id
            ),
        ],
        operation_name=(
            f"metadata entity={entity_id}"
        ),
        stdin=payload,
    )

    return last_json_object(
        completed.stdout
        or "",
        (
            "app.legal_entity_metadata "
            "sync"
        ),
    )


def activate_entity(
    entity_id: int,
) -> None:
    run_python_module(
        "app.legal_entities",
        [
            "activate",
            "--entity-id",
            str(
                entity_id
            ),
        ],
        operation_name=(
            f"activate entity={entity_id}"
        ),
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

            "RUSSIAN STANDARD TIME": (
                timezone(
                    timedelta(
                        hours=3
                    ),
                    name="MSK",
                )
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
                    "Системная база часовых "
                    "поясов не содержит "
                    f"{prepared}; используется "
                    "встроенный fallback."
                )
            )

            return fallback

        raise DispatcherError(
            f"Не найден часовой пояс {prepared}."
        ) from exc


def configured_period(
    run_info: dict[str, Any],
    timezone_name: str,
) -> tuple[
    datetime,
    datetime,
]:
    start_date = run_info.get(
        "export_period_from"
    )

    end_date = run_info.get(
        "export_period_to"
    )

    if (
        not isinstance(
            start_date,
            date,
        )
        or not isinstance(
            end_date,
            date,
        )
    ):
        raise DispatcherError(
            (
                "Для экспорта УПД "
                "не заполнен период."
            )
        )

    if start_date > end_date:
        raise DispatcherError(
            (
                "Дата начала экспорта "
                "позже даты окончания."
            )
        )

    zone = resolve_timezone(
        timezone_name
    )

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


def worker_process_once(
    entity_id: int,
    token: str,
) -> int:
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "app.rabbitmq_worker",
            "--entity-id",
            str(
                entity_id
            ),
            "--once",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )

    try:
        if (
            process.stdin is None
            or process.stdout is None
        ):
            raise DispatcherError(
                (
                    "Не удалось открыть каналы "
                    "RabbitMQ worker."
                )
            )

        process.stdin.write(
            token
            + "\n"
        )

        process.stdin.flush()
        process.stdin.close()

        for raw_line in process.stdout:
            line = raw_line.rstrip(
                "\r\n"
            )

            if line:
                log(
                    (
                        "[worker "
                        f"entity={entity_id}] "
                        f"{line}"
                    )
                )

        return int(
            process.wait()
        )

    finally:
        token = ""


def worker_supervisor(
    entity_id: int,
    token: str,
    retry_delay_seconds: int,
) -> int:
    cycle = 0

    while not _STOP_EVENT.is_set():
        cycle += 1

        log(
            (
                "Worker supervisor: "
                f"entity={entity_id}; "
                f"cycle={cycle}."
            )
        )

        exit_code = worker_process_once(
            entity_id,
            token,
        )

        log(
            (
                "Worker supervisor: "
                f"entity={entity_id}; "
                f"exit_code={exit_code}."
            )
        )

        if (
            exit_code
            in WORKER_TERMINAL_EXIT_CODES
        ):
            return exit_code

        if (
            exit_code
            in WORKER_RETRY_EXIT_CODES
        ):
            delay_seconds = (
                retry_delay_seconds
                + 5
            )

            log(
                (
                    "Worker supervisor: "
                    f"entity={entity_id}; "
                    "повтор через "
                    f"{delay_seconds} секунд."
                )
            )

            if _STOP_EVENT.wait(
                delay_seconds
            ):
                return 130

            continue

        return exit_code

    return 130


def active_sync_job(
    settings: dict[str, Any],
    entity_id: int,
) -> dict[str, Any] | None:
    with db_read(
        settings
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


def process_entity(
    settings: dict[str, Any],
    run_info: dict[str, Any],
    entity: dict[str, Any],
    args: argparse.Namespace,
    executor: ThreadPoolExecutor,
    worker_futures: list[
        Future[int]
    ],
) -> dict[str, Any]:
    auth_uuid = create_auth_job(
        settings,
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
        auth_result = authorize_via_agent(
            entity,
            timeout_seconds=(
                args.agent_timeout_seconds
            ),
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
                settings,
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
        }

        if entity[
            "export_enabled"
        ]:
            metadata = metadata_sync(
                entity[
                    "id"
                ],
                token,
                certificate,
            )

            activate_entity(
                entity[
                    "id"
                ]
            )

            (
                date_from,
                date_to,
            ) = configured_period(
                run_info,
                entity[
                    "timezone_name"
                ],
            )

            try:
                published = (
                    publish_sync_legal_entity_job(
                        entity_id=(
                            entity[
                                "id"
                            ]
                        ),
                        date_from=date_from,
                        date_to=date_to,
                        skip_edo=False,
                        force_edo=False,
                        edo_fail_fast=False,
                        continue_on_error=True,
                        requested_by=(
                            "pipeline:"
                            + run_info[
                                "uuid"
                            ]
                        ),
                    )
                )

                publish_status = str(
                    published.status
                ).upper()

                sync_uuid = str(
                    published.job_id
                )

            except ActiveSyncJobExistsError as exc:
                publish_status = str(
                    exc.active_status
                ).upper()

                sync_uuid = str(
                    exc.active_job_uuid
                )

            worker_required = (
                publish_status
                in {
                    "PUBLISHED",
                    "RETRY_WAIT",
                }
            )

            if publish_status == "CREATED":
                raise DispatcherError(
                    (
                        "Sync-задание осталось "
                        "в статусе CREATED "
                        "и не опубликовано."
                    )
                )

            if not sync_uuid:
                active = active_sync_job(
                    settings,
                    entity[
                        "id"
                    ],
                )

                if active is None:
                    raise DispatcherError(
                        (
                            "Не удалось определить "
                            "UUID sync-задания."
                        )
                    )

                sync_uuid = str(
                    active[
                        "job_uuid"
                    ]
                )

                publish_status = str(
                    active[
                        "status"
                    ]
                ).upper()

                worker_required = (
                    publish_status
                    in {
                        "PUBLISHED",
                        "RETRY_WAIT",
                    }
                )

            if worker_required:
                worker_futures.append(
                    executor.submit(
                        worker_supervisor,
                        entity[
                            "id"
                        ],
                        token,
                        (
                            args
                            .rabbitmq_retry_delay_seconds
                        ),
                    )
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

                    "date_from": iso_utc(
                        date_from
                    ),

                    "date_to": iso_utc(
                        date_to
                    ),
                }
            )

        finish_auth(
            settings,
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
            settings,
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
    settings: dict[str, Any],
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
        if _STOP_EVENT.is_set():
            raise DispatcherStopped(
                (
                    "Диспетчер остановлен "
                    "во время ожидания sync job."
                )
            )

        heartbeat(
            settings,
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
            settings
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
                    "превысило "
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

        _STOP_EVENT.wait(
            poll_seconds
        )


def finish_run(
    settings: dict[str, Any],
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
        settings
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
    settings: dict[str, Any],
    run_info: dict[str, Any],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    entities = load_entities(
        settings
    )

    results: list[
        dict[str, Any]
    ] = []

    worker_futures: list[
        Future[int]
    ] = []

    log(
        (
            f"Запуск {run_info['uuid']}; "
            f"режим={run_info['mode']}; "
            f"организаций={len(entities)}."
        )
    )

    if not entities:
        return results

    with ThreadPoolExecutor(
        max_workers=max(
            1,
            len(
                entities
            ),
        ),
        thread_name_prefix=
            "sync-worker",
    ) as executor:
        for entity in entities:
            if _STOP_EVENT.is_set():
                raise DispatcherStopped(
                    "Диспетчер остановлен."
                )

            heartbeat(
                settings,
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
                    settings
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
                settings,
                run_info,
                entity,
                args,
                executor,
                worker_futures,
            )

            results.append(
                result
            )

            log(
                compact_json(
                    result
                )
            )

        wait_for_sync_jobs(
            settings,
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

        for future in worker_futures:
            try:
                future.result(
                    timeout=30
                )

            except Exception as exc:
                log(
                    (
                        "Worker supervisor "
                        "завершился с ошибкой: "
                        f"{type(exc).__name__}: "
                        f"{exc}."
                    )
                )

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Docker-диспетчер авторизации "
            "и RabbitMQ-заданий ГИС МТ."
        )
    )

    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=integer_env(
            "PIPELINE_POLL_SECONDS",
            1,
        ),
    )

    parser.add_argument(
        "--sync-poll-seconds",
        type=int,
        default=integer_env(
            "PIPELINE_SYNC_POLL_SECONDS",
            3,
        ),
    )

    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=integer_env(
            "PIPELINE_STALE_AFTER_SECONDS",
            180,
        ),
    )

    parser.add_argument(
        "--auth-job-stale-minutes",
        type=int,
        default=integer_env(
            "PIPELINE_AUTH_JOB_STALE_MINUTES",
            5,
        ),
    )

    parser.add_argument(
        "--run-timeout-seconds",
        type=int,
        default=integer_env(
            "PIPELINE_RUN_TIMEOUT_SECONDS",
            21600,
        ),
    )

    parser.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=integer_env(
            "CERTIFICATE_AGENT_TIMEOUT_SECONDS",
            240,
        ),
    )

    parser.add_argument(
        "--rabbitmq-retry-delay-seconds",
        type=int,
        default=integer_env(
            "RABBITMQ_RETRY_DELAY_SECONDS",
            300,
        ),
    )

    return parser.parse_args()


def install_signal_handlers() -> None:
    def handle_signal(
        signum: int,
        frame: Any,
    ) -> None:
        del frame

        log(
            (
                "Получен сигнал "
                f"остановки {signum}."
            )
        )

        _STOP_EVENT.set()

    signal.signal(
        signal.SIGTERM,
        handle_signal,
    )

    signal.signal(
        signal.SIGINT,
        handle_signal,
    )


def main() -> int:
    args = parse_args()

    install_signal_handlers()

    settings = database_settings()

    log(
        (
            "Docker-диспетчер запущен. "
            f"Host={socket.gethostname()}; "
            f"PID={os.getpid()}."
        )
    )

    wait_for_certificate_agent(
        args.poll_seconds
    )

    while not _STOP_EVENT.is_set():
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
                settings,
                args.stale_after_seconds,
            )

            if run_info is None:
                _STOP_EVENT.wait(
                    args.poll_seconds
                )

                continue

            results = execute_run(
                settings,
                run_info,
                args,
            )

        except DispatcherStopped as exc:
            fatal_error = exc

            log(
                str(
                    exc
                )
            )

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
                        settings,
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

        if (
            fatal_error is not None
            and not isinstance(
                fatal_error,
                DispatcherStopped,
            )
        ):
            _STOP_EVENT.wait(
                args.poll_seconds
            )

    log(
        "Docker-диспетчер остановлен."
    )

    return 0


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