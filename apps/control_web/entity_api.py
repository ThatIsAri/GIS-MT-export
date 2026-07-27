from __future__ import annotations

import os
import re
import unicodedata
from contextlib import contextmanager
from typing import Any, Iterator
from uuid import uuid4

import mysql.connector
from flask import Blueprint, jsonify, request
from mysql.connector import MySQLConnection
from mysql.connector.errors import IntegrityError


entity_api = Blueprint(
    "entity_api",
    __name__,
)


ENTITY_TYPES = {
    "INDIVIDUAL_ENTREPRENEUR": {
        "inn_length": 12,
        "kpp_required": False,
    },
    "LEGAL_ENTITY": {
        "inn_length": 10,
        "kpp_required": True,
    },
}


STORE_LOCATIONS = {
    "CurrentUser",
    "LocalMachine",
}


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


class EntityApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        field: str | None = None,
    ) -> None:
        super().__init__(message)

        self.status_code = status_code
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
            f"Environment variable {name} is required."
        )

    return value


def database_settings() -> dict[str, Any]:
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
def database_transaction() -> Iterator[
    MySQLConnection
]:
    connection = mysql.connector.connect(
        **database_settings()
    )

    try:
        connection.set_charset_collation(
            charset="utf8mb4",
            collation="utf8mb4_0900_ai_ci",
        )

        connection.start_transaction()

        yield connection

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def request_payload() -> dict[str, Any]:
    value = request.get_json(
        silent=True
    )

    if not isinstance(
        value,
        dict,
    ):
        raise EntityApiError(
            "Тело запроса должно быть JSON-объектом."
        )

    return value


def required_text(
    data: dict[str, Any],
    field: str,
    max_length: int,
) -> str:
    value = " ".join(
        str(
            data.get(
                field
            )
            or ""
        ).split()
    )

    if not value:
        raise EntityApiError(
            "Поле не должно быть пустым.",
            field=field,
        )

    if len(
        value
    ) > max_length:
        raise EntityApiError(
            (
                "Значение слишком длинное. "
                f"Максимальная длина — {max_length} символов."
            ),
            field=field,
        )

    return value


def exact_digits(
    data: dict[str, Any],
    field: str,
    length: int,
) -> str:
    raw_value = str(
        data.get(
            field
        )
        or ""
    ).strip()

    if not raw_value:
        raise EntityApiError(
            "Поле не должно быть пустым.",
            field=field,
        )

    if not raw_value.isdigit():
        raise EntityApiError(
            "Поле должно содержать только цифры.",
            field=field,
        )

    if len(
        raw_value
    ) != length:
        raise EntityApiError(
            (
                "Некорректное значение, "
                f"должно быть {length} символов."
            ),
            field=field,
        )

    return raw_value


def exact_thumbprint(
    data: dict[str, Any],
) -> str:
    raw_value = str(
        data.get(
            "thumbprint"
        )
        or ""
    ).strip()

    if not raw_value:
        raise EntityApiError(
            "Поле не должно быть пустым.",
            field="thumbprint",
        )

    prepared = re.sub(
        r"\s+",
        "",
        raw_value,
    ).upper()

    if len(
        prepared
    ) != 40:
        raise EntityApiError(
            (
                "Некорректное значение, "
                "должно быть 40 символов."
            ),
            field="thumbprint",
        )

    if not re.fullmatch(
        r"[0-9A-F]{40}",
        prepared,
    ):
        raise EntityApiError(
            (
                "Отпечаток должен содержать "
                "только цифры и латинские буквы A–F."
            ),
            field="thumbprint",
        )

    return prepared


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
        .decode(
            "ascii"
        )
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
        f"{value[:105]}_"
        f"{entity_id}_"
        f"{inn}"
    )[:160]


def validate_entity(
    data: dict[str, Any],
) -> dict[str, Any]:
    entity_type = str(
        data.get(
            "entity_type"
        )
        or ""
    ).strip()

    if not entity_type:
        raise EntityApiError(
            "Поле не должно быть пустым.",
            field="entity_type",
        )

    entity_rules = ENTITY_TYPES.get(
        entity_type
    )

    if entity_rules is None:
        raise EntityApiError(
            "Выбран некорректный тип организации.",
            field="entity_type",
        )

    short_name = required_text(
        data,
        "short_name",
        255,
    )

    full_name = required_text(
        data,
        "full_name",
        1000,
    )

    inn = exact_digits(
        data,
        "inn",
        int(
            entity_rules[
                "inn_length"
            ]
        ),
    )

    if bool(
        entity_rules[
            "kpp_required"
        ]
    ):
        kpp = exact_digits(
            data,
            "kpp",
            9,
        )
    else:
        kpp = None

    thumbprint = exact_thumbprint(
        data
    )

    store_location = required_text(
        data,
        "store_location",
        32,
    )

    if store_location not in STORE_LOCATIONS:
        raise EntityApiError(
            "Выбрано некорректное хранилище сертификата.",
            field="store_location",
        )

    store_name = required_text(
        data,
        "store_name",
        64,
    )

    timezone_name = required_text(
        data,
        "timezone_name",
        128,
    )

    return {
        "entity_type": entity_type,
        "short_name": short_name,
        "full_name": full_name,
        "inn": inn,
        "kpp": kpp,
        "thumbprint": thumbprint,
        "store_location": store_location,
        "store_name": store_name,
        "timezone_name": timezone_name,
    }


@entity_api.errorhandler(
    EntityApiError
)
def handle_entity_api_error(
    exc: EntityApiError,
):
    body: dict[str, Any] = {
        "status": "ERROR",
        "error": str(
            exc
        ),
    }

    if exc.field:
        body["field"] = exc.field

    return (
        jsonify(
            body
        ),
        exc.status_code,
    )


@entity_api.post(
    "/api/entities"
)
def create_entity():
    values = validate_entity(
        request_payload()
    )

    with database_transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT id
                FROM legal_entity
                WHERE inn = %s
                LIMIT 1
                FOR UPDATE
                """,
                (
                    values[
                        "inn"
                    ],
                ),
            )

            existing_entity = cursor.fetchone()

            if existing_entity is not None:
                raise EntityApiError(
                    "Организация с таким ИНН уже существует.",
                    status_code=409,
                    field="inn",
                )

            cursor.execute(
                """
                SELECT id
                FROM legal_entity_certificate
                WHERE thumbprint = %s
                LIMIT 1
                FOR UPDATE
                """,
                (
                    values[
                        "thumbprint"
                    ],
                ),
            )

            existing_certificate = cursor.fetchone()

            if existing_certificate is not None:
                raise EntityApiError(
                    (
                        "Сертификат с таким отпечатком "
                        "уже зарегистрирован."
                    ),
                    status_code=409,
                    field="thumbprint",
                )

            entity_uuid = str(
                uuid4()
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
                    %s,
                    %s,
                    %s,
                    %s,
                    'SETUP',
                    %s,
                    %s,
                    %s,
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    entity_uuid,
                    values[
                        "inn"
                    ],
                    values[
                        "kpp"
                    ],
                    values[
                        "short_name"
                    ],
                    values[
                        "full_name"
                    ],
                    values[
                        "entity_type"
                    ],
                    values[
                        "timezone_name"
                    ],
                    temporary_slug,
                    (
                        "Организация добавлена "
                        "через панель администратора."
                    ),
                ),
            )

            entity_id = int(
                cursor.lastrowid
            )

            storage_slug = make_storage_slug(
                values[
                    "short_name"
                ],
                values[
                    "inn"
                ],
                entity_id,
            )

            cursor.execute(
                """
                UPDATE legal_entity
                   SET storage_slug = %s,
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    storage_slug,
                    entity_id,
                ),
            )

            cursor.execute(
                """
                INSERT INTO legal_entity_integration_config (
                    legal_entity_id,
                    true_api_enabled,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s,
                    1,
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    entity_id,
                ),
            )

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
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    %s,
                    %s,
                    NULL,
                    NULL,
                    1,
                    1,
                    NULL,
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    entity_id,
                    values[
                        "thumbprint"
                    ],
                    values[
                        "inn"
                    ],
                    values[
                        "full_name"
                    ],
                    values[
                        "store_location"
                    ],
                    values[
                        "store_name"
                    ],
                ),
            )

        except IntegrityError as exc:
            if exc.errno == 1062:
                raise EntityApiError(
                    (
                        "Организация или сертификат "
                        "с такими данными уже существует."
                    ),
                    status_code=409,
                ) from exc

            raise

        finally:
            cursor.close()

    return (
        jsonify(
            {
                "status": "CREATED",
                "entity": {
                    "id": entity_id,
                    "entity_uuid": entity_uuid,
                    "inn": values[
                        "inn"
                    ],
                    "kpp": values[
                        "kpp"
                    ],
                    "short_name": values[
                        "short_name"
                    ],
                    "full_name": values[
                        "full_name"
                    ],
                    "entity_type": values[
                        "entity_type"
                    ],
                    "storage_slug": storage_slug,
                    "status": "SETUP",
                },
            }
        ),
        201,
    )