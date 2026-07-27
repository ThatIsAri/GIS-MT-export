from __future__ import annotations

import hmac
import json
import os
import re
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import mysql.connector
from flask import Flask, jsonify, render_template, request
from mysql.connector import MySQLConnection
from mysql.connector.errors import IntegrityError


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


AUTH_ACTIVE = (
    "PENDING",
    "WAITING_CERTIFICATE",
    "PROCESSING",
)

AUTH_TERMINAL = (
    "SUCCESS",
    "ERROR",
    "CANCELLED",
)


RU_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


class ApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


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
def db_transaction() -> Iterator[
    MySQLConnection
]:
    connection = mysql.connector.connect(
        **db_settings()
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


def payload() -> dict[str, Any]:
    value = request.get_json(
        silent=True
    )

    if not isinstance(
        value,
        dict,
    ):
        raise ApiError(
            "Тело запроса должно быть JSON-объектом."
        )

    return value


def require_agent_key() -> None:
    actual = request.headers.get(
        "X-Agent-Key",
        "",
    )

    expected = required_env(
        "CONTROL_AGENT_API_KEY"
    )

    if not hmac.compare_digest(
        actual,
        expected,
    ):
        raise ApiError(
            "Недействительный ключ агента.",
            401,
        )


def normalize_uuid(
    value: Any,
    name: str,
) -> str:
    try:
        return str(
            UUID(
                str(
                    value or ""
                ).strip()
            )
        )

    except ValueError as exc:
        raise ApiError(
            f"Поле {name} должно содержать UUID."
        ) from exc


def normalize_inn(
    value: Any,
) -> str:
    inn = re.sub(
        r"\D",
        "",
        str(
            value or ""
        ),
    )

    if not re.fullmatch(
        r"\d{10}(?:\d{2})?",
        inn,
    ):
        raise ApiError(
            "ИНН должен содержать 10 или 12 цифр."
        )

    return inn


def normalize_thumbprint(
    value: Any,
) -> str:
    thumbprint = re.sub(
        r"[^0-9A-Fa-f]",
        "",
        str(
            value or ""
        ),
    ).upper()

    if not re.fullmatch(
        r"[0-9A-F]{40}",
        thumbprint,
    ):
        raise ApiError(
            "Некорректный отпечаток сертификата."
        )

    return thumbprint


def text(
    value: Any,
    max_length: int,
    required: bool = False,
) -> str | None:
    prepared = " ".join(
        str(
            value or ""
        ).split()
    )

    if not prepared:
        if required:
            raise ApiError(
                "Отсутствует обязательное текстовое поле."
            )

        return None

    if len(
        prepared
    ) > max_length:
        raise ApiError(
            f"Текст длиннее {max_length} символов."
        )

    return prepared


def parse_datetime(
    value: Any,
) -> datetime | None:
    if value in (
        None,
        "",
    ):
        return None

    prepared = str(
        value
    ).strip()

    if prepared.endswith(
        "Z"
    ):
        prepared = (
            prepared[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            prepared
        )

    except ValueError as exc:
        raise ApiError(
            "Некорректная дата сертификата."
        ) from exc

    if parsed.tzinfo is not None:
        parsed = (
            parsed
            .astimezone(
                timezone.utc
            )
            .replace(
                tzinfo=None
            )
        )

    return parsed


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


def make_storage_slug(
    short_name: str,
    inn: str,
    entity_id: int,
) -> str:
    value = (
        short_name
        .lower()
        .translate(
            RU_TRANSLIT
        )
    )

    value = (
        unicodedata
        .normalize(
            "NFKD",
            value,
        )
        .encode(
            "ascii",
            "ignore",
        )
        .decode()
    )

    value = re.sub(
        r"[^a-z0-9]+",
        "_",
        value,
    ).strip(
        "_"
    )

    if not value:
        value = "organization"

    if (
        len(
            inn
        ) == 12
        and not value.startswith(
            "ip_"
        )
    ):
        value = (
            "ip_"
            + value
        )

    return (
        f"{value[:110]}_"
        f"{entity_id}_"
        f"{inn}"
    )[:160]


def upsert_agent(
    connection: MySQLConnection,
    data: dict[str, Any],
) -> int:
    agent_uuid = normalize_uuid(
        data.get(
            "agent_uuid"
        ),
        "agent_uuid",
    )

    host_name = text(
        data.get(
            "host_name"
        ),
        255,
        True,
    )

    version = text(
        data.get(
            "agent_version"
        ),
        64,
        True,
    )

    current_thumbprint = None

    if data.get(
        "current_certificate_thumbprint"
    ):
        current_thumbprint = (
            normalize_thumbprint(
                data[
                    "current_certificate_thumbprint"
                ]
            )
        )

    current_inn = None

    if data.get(
        "current_certificate_inn"
    ):
        current_inn = normalize_inn(
            data[
                "current_certificate_inn"
            ]
        )

    capabilities = data.get(
        "capabilities"
    )

    capabilities_json = None

    if isinstance(
        capabilities,
        dict,
    ):
        capabilities_json = json.dumps(
            capabilities,
            ensure_ascii=False,
        )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT id
            FROM sys_control_agent
            WHERE agent_uuid = %s
            FOR UPDATE
            """,
            (
                agent_uuid,
            ),
        )

        existing = cursor.fetchone()

        if existing is None:
            cursor.execute(
                """
                INSERT INTO sys_control_agent (
                    agent_uuid,
                    host_name,
                    agent_version,
                    status,
                    current_certificate_thumbprint,
                    current_certificate_inn,
                    capabilities_json,
                    last_seen_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    'ONLINE',
                    %s,
                    %s,
                    %s,
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    agent_uuid,
                    host_name,
                    version,
                    current_thumbprint,
                    current_inn,
                    capabilities_json,
                ),
            )

            return int(
                cursor.lastrowid
            )

        agent_id = int(
            existing["id"]
        )

        cursor.execute(
            """
            UPDATE sys_control_agent
               SET host_name = %s,
                   agent_version = %s,
                   status = 'ONLINE',
                   current_certificate_thumbprint = %s,
                   current_certificate_inn = %s,
                   capabilities_json = %s,
                   last_seen_at = UTC_TIMESTAMP(6),
                   updated_at = UTC_TIMESTAMP(6)
             WHERE id = %s
            """,
            (
                host_name,
                version,
                current_thumbprint,
                current_inn,
                capabilities_json,
                agent_id,
            ),
        )

        return agent_id

    finally:
        cursor.close()


def get_or_create_entity(
    connection: MySQLConnection,
    certificate: dict[str, Any],
) -> int:
    inn = normalize_inn(
        certificate.get(
            "inn"
        )
    )

    short_name = text(
        (
            certificate.get(
                "short_name"
            )
            or certificate.get(
                "common_name"
            )
            or f"Организация {inn}"
        ),
        255,
        True,
    )

    full_name = text(
        certificate.get(
            "subject_name"
        ),
        1000,
    )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                id,
                storage_slug
            FROM legal_entity
            WHERE inn = %s
            FOR UPDATE
            """,
            (
                inn,
            ),
        )

        existing = cursor.fetchone()

        if existing is not None:
            entity_id = int(
                existing["id"]
            )

            current_slug = str(
                existing[
                    "storage_slug"
                ]
                or ""
            )

            if current_slug.startswith(
                "entity_"
            ):
                cursor.execute(
                    """
                    UPDATE legal_entity
                       SET short_name = %s,
                           full_name =
                               COALESCE(
                                   full_name,
                                   %s
                               ),
                           storage_slug = %s,
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = %s
                    """,
                    (
                        short_name,
                        full_name,
                        make_storage_slug(
                            short_name,
                            inn,
                            entity_id,
                        ),
                        entity_id,
                    ),
                )

            return entity_id

        entity_uuid = str(
            uuid4()
        )

        entity_type = (
            "INDIVIDUAL_ENTREPRENEUR"
            if len(
                inn
            ) == 12
            else "LEGAL_ENTITY"
        )

        temporary_slug = (
            "pending_"
            + entity_uuid.replace(
                "-",
                "",
            )
        )

        cursor.execute(
            """
            INSERT INTO legal_entity (
                entity_uuid,
                inn,
                kpp,
                short_name,
                full_name,
                entity_type,
                status,
                timezone_name,
                storage_slug,
                notes,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                NULL,
                %s,
                %s,
                %s,
                'SETUP',
                'Europe/Moscow',
                %s,
                'Создано автоматически Windows-агентом по сертификату.',
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6)
            )
            """,
            (
                entity_uuid,
                inn,
                short_name,
                full_name,
                entity_type,
                temporary_slug,
            ),
        )

        entity_id = int(
            cursor.lastrowid
        )

        cursor.execute(
            """
            UPDATE legal_entity
               SET storage_slug = %s
             WHERE id = %s
            """,
            (
                make_storage_slug(
                    short_name,
                    inn,
                    entity_id,
                ),
                entity_id,
            ),
        )

        cursor.execute(
            """
            INSERT INTO legal_entity_integration_config (
                legal_entity_id,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6)
            )
            """,
            (
                entity_id,
            ),
        )

        return entity_id

    finally:
        cursor.close()


def upsert_certificate(
    connection: MySQLConnection,
    entity_id: int,
    data: dict[str, Any],
) -> int:
    thumbprint = normalize_thumbprint(
        data.get(
            "thumbprint"
        )
    )

    inn = normalize_inn(
        data.get(
            "inn"
        )
    )

    store_location = str(
        data.get(
            "store_location"
        )
        or "CurrentUser"
    )

    if store_location not in {
        "CurrentUser",
        "LocalMachine",
    }:
        raise ApiError(
            "Некорректное хранилище сертификата."
        )

    subject = text(
        data.get(
            "subject_name"
        ),
        1000,
    )

    serial = text(
        data.get(
            "serial_number"
        ),
        128,
    )

    issuer = text(
        data.get(
            "issuer_name"
        ),
        1000,
    )

    valid_from = parse_datetime(
        data.get(
            "valid_from"
        )
    )

    valid_to = parse_datetime(
        data.get(
            "valid_to"
        )
    )

    store_name = text(
        data.get(
            "store_name"
        )
        or "My",
        64,
        True,
    )

    provider = text(
        data.get(
            "provider_name"
        ),
        255,
    )

    profile = text(
        data.get(
            "diskontrol_profile"
        ),
        255,
    )

    has_private_key = int(
        bool(
            data.get(
                "has_private_key",
                True,
            )
        )
    )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                id,
                legal_entity_id
            FROM legal_entity_certificate
            WHERE thumbprint = %s
            FOR UPDATE
            """,
            (
                thumbprint,
            ),
        )

        existing = cursor.fetchone()

        if (
            existing is not None
            and int(
                existing[
                    "legal_entity_id"
                ]
            ) != entity_id
        ):
            raise ApiError(
                "Сертификат уже привязан к другой организации.",
                409,
            )

        cursor.execute(
            """
            UPDATE legal_entity_certificate
               SET is_active = 0,
                   updated_at = UTC_TIMESTAMP(6)
             WHERE legal_entity_id = %s
               AND thumbprint <> %s
            """,
            (
                entity_id,
                thumbprint,
            ),
        )

        values = (
            inn,
            subject,
            serial,
            issuer,
            valid_from,
            valid_to,
            store_location,
            store_name,
            provider,
            profile,
            has_private_key,
        )

        if existing is None:
            cursor.execute(
                """
                INSERT INTO legal_entity_certificate (
                    legal_entity_id,
                    thumbprint,
                    certificate_inn,
                    subject_name,
                    serial_number,
                    issuer_name,
                    valid_from,
                    valid_to,
                    store_location,
                    store_name,
                    provider_name,
                    diskontrol_profile,
                    has_private_key,
                    is_active,
                    last_discovered_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    1,
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    entity_id,
                    thumbprint,
                    *values,
                ),
            )

            return int(
                cursor.lastrowid
            )

        certificate_id = int(
            existing["id"]
        )

        cursor.execute(
            """
            UPDATE legal_entity_certificate
               SET certificate_inn = %s,
                   subject_name = %s,
                   serial_number = %s,
                   issuer_name = %s,
                   valid_from = %s,
                   valid_to = %s,
                   store_location = %s,
                   store_name = %s,
                   provider_name = %s,
                   diskontrol_profile = %s,
                   has_private_key = %s,
                   is_active = 1,
                   last_discovered_at =
                       UTC_TIMESTAMP(6),
                   updated_at =
                       UTC_TIMESTAMP(6)
             WHERE id = %s
            """,
            (
                *values,
                certificate_id,
            ),
        )

        return certificate_id

    finally:
        cursor.close()


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
                        agent_certificate.is_present
                    ) AS certificate_present,

                    MAX(
                        agent.last_seen_at
                    ) AS agent_last_seen_at,

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

                LEFT JOIN sys_control_agent_certificate
                    agent_certificate
                  ON agent_certificate.legal_entity_id = e.id
                 AND agent_certificate.is_present = 1

                LEFT JOIN sys_control_agent agent
                  ON agent.id =
                     agent_certificate.agent_id

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
                    claimed_at,
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

            cursor.execute(
                """
                SELECT
                    agent_uuid,
                    host_name,
                    agent_version,
                    status,
                    current_certificate_inn,
                    current_certificate_thumbprint,
                    last_seen_at
                FROM sys_control_agent
                ORDER BY last_seen_at DESC
                """
            )

            agents = rows_to_json(
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
        "agents": agents,
    }


@app.errorhandler(
    ApiError
)
def api_error(
    exc: ApiError,
):
    return (
        jsonify(
            {
                "status": "ERROR",
                "error": str(
                    exc
                ),
            }
        ),
        exc.status_code,
    )


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


@app.post(
    "/api/auth-jobs"
)
def create_auth_jobs():
    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    if not isinstance(
        data,
        dict,
    ):
        raise ApiError(
            "Тело запроса должно быть JSON-объектом."
        )

    requested_by = text(
        data.get(
            "requested_by"
        )
        or "control-web",
        128,
        True,
    )

    requested_ids = data.get(
        "entity_ids"
    )

    entity_ids = None

    if requested_ids is not None:
        if not isinstance(
            requested_ids,
            list,
        ):
            raise ApiError(
                "entity_ids должен быть массивом."
            )

        try:
            entity_ids = [
                int(
                    value
                )
                for value
                in requested_ids
            ]

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ApiError(
                "entity_ids содержит некорректный ID."
            ) from exc

    created: list[
        dict[str, Any]
    ] = []

    skipped: list[
        dict[str, Any]
    ] = []

    with db_transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            query = """
                SELECT
                    e.id,
                    e.inn,
                    e.short_name
                FROM legal_entity e

                JOIN legal_entity_integration_config config
                  ON config.legal_entity_id = e.id

                WHERE e.status IN (
                    'SETUP',
                    'ACTIVE'
                )

                  AND config.true_api_enabled = 1
            """

            parameters: list[Any] = []

            if entity_ids:
                placeholders = ",".join(
                    [
                        "%s"
                    ]
                    * len(
                        entity_ids
                    )
                )

                query += (
                    " AND e.id IN ("
                    + placeholders
                    + ")"
                )

                parameters.extend(
                    entity_ids
                )

            query += (
                " ORDER BY e.id"
                " FOR UPDATE"
            )

            cursor.execute(
                query,
                tuple(
                    parameters
                ),
            )

            for entity in cursor.fetchall():
                job_uuid = str(
                    uuid4()
                )

                try:
                    cursor.execute(
                        """
                        INSERT INTO sys_auth_job (
                            job_uuid,
                            legal_entity_id,
                            requested_by,
                            requested_at,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            UTC_TIMESTAMP(6),
                            'PENDING',
                            UTC_TIMESTAMP(6),
                            UTC_TIMESTAMP(6)
                        )
                        """,
                        (
                            job_uuid,
                            int(
                                entity[
                                    "id"
                                ]
                            ),
                            requested_by,
                        ),
                    )

                    created.append(
                        {
                            "job_uuid": (
                                job_uuid
                            ),
                            "legal_entity_id": int(
                                entity[
                                    "id"
                                ]
                            ),
                            "inn": str(
                                entity[
                                    "inn"
                                ]
                            ),
                            "short_name": str(
                                entity[
                                    "short_name"
                                ]
                            ),
                        }
                    )

                except IntegrityError as exc:
                    if exc.errno != 1062:
                        raise

                    skipped.append(
                        {
                            "legal_entity_id": int(
                                entity[
                                    "id"
                                ]
                            ),
                            "inn": str(
                                entity[
                                    "inn"
                                ]
                            ),
                            "reason": (
                                "ACTIVE_AUTH_JOB_EXISTS"
                            ),
                        }
                    )

        finally:
            cursor.close()

    return jsonify(
        {
            "status": "OK",
            "created_count": len(
                created
            ),
            "skipped_count": len(
                skipped
            ),
            "created": created,
            "skipped": skipped,
        }
    )


@app.post(
    "/api/agent/heartbeat"
)
def heartbeat():
    require_agent_key()

    with db_transaction() as connection:
        agent_id = upsert_agent(
            connection,
            payload(),
        )

    return jsonify(
        {
            "status": "OK",
            "agent_id": agent_id,
        }
    )


@app.post(
    "/api/agent/certificates"
)
def certificates():
    require_agent_key()

    data = payload()

    raw_certificates = data.get(
        "certificates"
    )

    if not isinstance(
        raw_certificates,
        list,
    ):
        raise ApiError(
            "certificates должен быть массивом."
        )

    normalized: list[
        dict[str, Any]
    ] = []

    for item in raw_certificates:
        if not isinstance(
            item,
            dict,
        ):
            raise ApiError(
                "Сертификат должен быть JSON-объектом."
            )

        normalized.append(
            {
                **item,
                "inn": normalize_inn(
                    item.get(
                        "inn"
                    )
                ),
                "thumbprint": (
                    normalize_thumbprint(
                        item.get(
                            "thumbprint"
                        )
                    )
                ),
            }
        )

    if len(
        normalized
    ) == 1:
        data[
            "current_certificate_thumbprint"
        ] = normalized[0][
            "thumbprint"
        ]

        data[
            "current_certificate_inn"
        ] = normalized[0][
            "inn"
        ]

    data[
        "capabilities"
    ] = {
        "certificate_scan": True
    }

    discovered: list[
        dict[str, Any]
    ] = []

    with db_transaction() as connection:
        agent_id = upsert_agent(
            connection,
            data,
        )

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE sys_control_agent_certificate
                   SET is_present = 0,
                       last_missing_at =
                           UTC_TIMESTAMP(6),
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE agent_id = %s
                   AND is_present = 1
                """,
                (
                    agent_id,
                ),
            )

            for certificate in normalized:
                entity_id = get_or_create_entity(
                    connection,
                    certificate,
                )

                certificate_id = (
                    upsert_certificate(
                        connection,
                        entity_id,
                        certificate,
                    )
                )

                store_location = str(
                    certificate.get(
                        "store_location"
                    )
                    or "CurrentUser"
                )

                store_name = str(
                    certificate.get(
                        "store_name"
                    )
                    or "My"
                )

                cursor.execute(
                    """
                    INSERT INTO sys_control_agent_certificate (
                        agent_id,
                        legal_entity_id,
                        certificate_id,
                        thumbprint,
                        certificate_inn,
                        store_location,
                        store_name,
                        is_present,
                        first_seen_at,
                        last_seen_at,
                        last_missing_at,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        1,
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6),
                        NULL,
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6)
                    )
                    ON DUPLICATE KEY UPDATE
                        legal_entity_id =
                            VALUES(
                                legal_entity_id
                            ),

                        certificate_id =
                            VALUES(
                                certificate_id
                            ),

                        certificate_inn =
                            VALUES(
                                certificate_inn
                            ),

                        store_location =
                            VALUES(
                                store_location
                            ),

                        store_name =
                            VALUES(
                                store_name
                            ),

                        is_present = 1,

                        last_seen_at =
                            UTC_TIMESTAMP(6),

                        last_missing_at = NULL,

                        updated_at =
                            UTC_TIMESTAMP(6)
                    """,
                    (
                        agent_id,
                        entity_id,
                        certificate_id,
                        certificate[
                            "thumbprint"
                        ],
                        certificate[
                            "inn"
                        ],
                        store_location,
                        store_name,
                    ),
                )

                discovered.append(
                    {
                        "legal_entity_id": (
                            entity_id
                        ),
                        "certificate_id": (
                            certificate_id
                        ),
                        "inn": certificate[
                            "inn"
                        ],
                        "thumbprint": (
                            certificate[
                                "thumbprint"
                            ]
                        ),
                    }
                )

        finally:
            cursor.close()

    return jsonify(
        {
            "status": "OK",
            "agent_id": agent_id,
            "certificates": discovered,
        }
    )


@app.post(
    "/api/agent/auth-jobs/claim"
)
def claim_auth_job():
    require_agent_key()

    data = payload()

    agent_uuid = normalize_uuid(
        data.get(
            "agent_uuid"
        ),
        "agent_uuid",
    )

    available = data.get(
        "available_thumbprints"
    )

    if not isinstance(
        available,
        list,
    ):
        raise ApiError(
            "available_thumbprints должен быть массивом."
        )

    thumbprints = [
        normalize_thumbprint(
            value
        )
        for value
        in available
    ]

    if not thumbprints:
        return jsonify(
            {
                "status": "NO_MATCHING_JOB",
                "job": None,
            }
        )

    with db_transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT id
                FROM sys_control_agent
                WHERE agent_uuid = %s
                  AND status = 'ONLINE'
                FOR UPDATE
                """,
                (
                    agent_uuid,
                ),
            )

            agent = cursor.fetchone()

            if agent is None:
                raise ApiError(
                    "Агент не зарегистрирован.",
                    409,
                )

            placeholders = ",".join(
                [
                    "%s"
                ]
                * len(
                    thumbprints
                )
            )

            cursor.execute(
                f"""
                SELECT
                    auth_job.id,
                    auth_job.job_uuid,
                    auth_job.legal_entity_id,
                    entity.inn,
                    entity.short_name,
                    entity.storage_slug,
                    certificate.thumbprint,
                    certificate.store_location,
                    certificate.store_name

                FROM sys_auth_job auth_job

                JOIN legal_entity entity
                  ON entity.id =
                     auth_job.legal_entity_id

                JOIN legal_entity_certificate certificate
                  ON certificate.legal_entity_id =
                     entity.id
                 AND certificate.is_active = 1

                WHERE auth_job.status IN (
                    'PENDING',
                    'WAITING_CERTIFICATE'
                )

                  AND certificate.thumbprint
                      IN ({placeholders})

                ORDER BY
                    auth_job.requested_at,
                    auth_job.id

                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                tuple(
                    thumbprints
                ),
            )

            job = cursor.fetchone()

            if job is None:
                return jsonify(
                    {
                        "status": "NO_MATCHING_JOB",
                        "job": None,
                    }
                )

            cursor.execute(
                """
                UPDATE sys_auth_job
                   SET status = 'PROCESSING',
                       claimed_by_agent_id = %s,
                       certificate_thumbprint = %s,
                       claimed_at =
                           UTC_TIMESTAMP(6),
                       started_at =
                           UTC_TIMESTAMP(6),
                       last_error_type = NULL,
                       last_error_message = NULL,
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    int(
                        agent[
                            "id"
                        ]
                    ),
                    str(
                        job[
                            "thumbprint"
                        ]
                    ),
                    int(
                        job[
                            "id"
                        ]
                    ),
                ),
            )

            result = {
                key: json_value(
                    value
                )
                for key, value
                in dict(
                    job
                ).items()
                if key != "id"
            }

        finally:
            cursor.close()

    return jsonify(
        {
            "status": "CLAIMED",
            "job": result,
        }
    )


@app.post(
    "/api/agent/auth-jobs/<job_uuid>/result"
)
def auth_job_result(
    job_uuid: str,
):
    require_agent_key()

    prepared_job_uuid = normalize_uuid(
        job_uuid,
        "job_uuid",
    )

    data = payload()

    agent_uuid = normalize_uuid(
        data.get(
            "agent_uuid"
        ),
        "agent_uuid",
    )

    status = str(
        data.get(
            "status"
        )
        or ""
    ).upper()

    if status not in AUTH_TERMINAL:
        raise ApiError(
            "status должен быть SUCCESS, ERROR или CANCELLED."
        )

    sync_job_uuid = None

    if data.get(
        "sync_job_uuid"
    ):
        sync_job_uuid = normalize_uuid(
            data[
                "sync_job_uuid"
            ],
            "sync_job_uuid",
        )

    result_json = None

    if isinstance(
        data.get(
            "result"
        ),
        dict,
    ):
        result_json = json.dumps(
            data[
                "result"
            ],
            ensure_ascii=False,
        )

    with db_transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT id
                FROM sys_control_agent
                WHERE agent_uuid = %s
                FOR UPDATE
                """,
                (
                    agent_uuid,
                ),
            )

            agent = cursor.fetchone()

            if agent is None:
                raise ApiError(
                    "Агент не зарегистрирован.",
                    409,
                )

            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    claimed_by_agent_id
                FROM sys_auth_job
                WHERE job_uuid = %s
                FOR UPDATE
                """,
                (
                    prepared_job_uuid,
                ),
            )

            job = cursor.fetchone()

            if job is None:
                raise ApiError(
                    "Задание авторизации не найдено.",
                    404,
                )

            if str(
                job[
                    "status"
                ]
            ) in AUTH_TERMINAL:
                return jsonify(
                    {
                        "status": "ALREADY_FINISHED",
                        "job_status": str(
                            job[
                                "status"
                            ]
                        ),
                    }
                )

            if (
                job[
                    "claimed_by_agent_id"
                ] is not None
                and int(
                    job[
                        "claimed_by_agent_id"
                    ]
                ) != int(
                    agent[
                        "id"
                    ]
                )
            ):
                raise ApiError(
                    "Задание захвачено другим агентом.",
                    409,
                )

            cursor.execute(
                """
                UPDATE sys_auth_job
                   SET status = %s,
                       claimed_by_agent_id = %s,
                       sync_job_uuid = %s,
                       last_error_type = %s,
                       last_error_message = %s,
                       result_json = %s,
                       finished_at =
                           UTC_TIMESTAMP(6),
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    status,
                    int(
                        agent[
                            "id"
                        ]
                    ),
                    sync_job_uuid,
                    text(
                        data.get(
                            "error_type"
                        ),
                        128,
                    ),
                    text(
                        data.get(
                            "error_message"
                        ),
                        2000,
                    ),
                    result_json,
                    int(
                        job[
                            "id"
                        ]
                    ),
                ),
            )

        finally:
            cursor.close()

    return jsonify(
        {
            "status": "OK",
            "job_uuid": prepared_job_uuid,
            "job_status": status,
            "sync_job_uuid": sync_job_uuid,
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
    )