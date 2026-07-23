from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import typer
from mysql.connector import MySQLConnection
from mysql.connector.errors import IntegrityError

from app.config import get_settings
from app.db import Database


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Управление справочником юридических лиц, "
        "сертификатами и товарными группами."
    ),
)


ENTITY_TYPE_LEGAL = "LEGAL_ENTITY"
ENTITY_TYPE_IP = "INDIVIDUAL_ENTREPRENEUR"

ENTITY_TYPES = {
    ENTITY_TYPE_LEGAL,
    ENTITY_TYPE_IP,
}

ENTITY_STATUSES = {
    "SETUP",
    "ACTIVE",
    "SUSPENDED",
    "DISABLED",
}

STORE_LOCATIONS = {
    "CurrentUser",
    "LocalMachine",
}

ENTITY_TYPE_ALIASES = {
    "LEGAL_ENTITY": ENTITY_TYPE_LEGAL,
    "LEGAL": ENTITY_TYPE_LEGAL,
    "ORGANIZATION": ENTITY_TYPE_LEGAL,
    "ORG": ENTITY_TYPE_LEGAL,
    "OOO": ENTITY_TYPE_LEGAL,
    "INDIVIDUAL_ENTREPRENEUR": ENTITY_TYPE_IP,
    "INDIVIDUAL-ENTREPRENEUR": ENTITY_TYPE_IP,
    "IP": ENTITY_TYPE_IP,
    "IE": ENTITY_TYPE_IP,
}

PRODUCT_GROUP_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9_-]{0,63}$"
)

THUMBPRINT_PATTERN = re.compile(
    r"^[0-9A-F]{40}$"
)

T = TypeVar("T")


def normalize_entity_type(
    value: str,
) -> str:
    prepared = (
        value
        .strip()
        .upper()
        .replace(
            " ",
            "_",
        )
    )

    entity_type = ENTITY_TYPE_ALIASES.get(
        prepared
    )

    if entity_type is None:
        raise ValueError(
            "Неизвестный тип субъекта. "
            "Используйте LEGAL_ENTITY или IP."
        )

    return entity_type


def normalize_inn(
    value: str,
    entity_type: str,
) -> str:
    prepared = value.strip()

    if not prepared.isdigit():
        raise ValueError(
            "ИНН должен содержать только цифры."
        )

    expected_length = (
        12
        if entity_type == ENTITY_TYPE_IP
        else 10
    )

    if len(prepared) != expected_length:
        raise ValueError(
            f"Для типа {entity_type} "
            "ИНН должен содержать "
            f"{expected_length} цифр."
        )

    return prepared


def normalize_kpp(
    value: str | None,
    entity_type: str,
) -> str | None:
    if value is None:
        return None

    prepared = value.strip()

    if not prepared:
        return None

    if entity_type == ENTITY_TYPE_IP:
        raise ValueError(
            "Для индивидуального предпринимателя "
            "КПП не указывается."
        )

    if (
        len(prepared) != 9
        or not prepared.isdigit()
    ):
        raise ValueError(
            "КПП должен содержать 9 цифр."
        )

    return prepared


def normalize_optional_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None

    prepared = value.strip()

    if not prepared:
        return None

    if len(prepared) > max_length:
        raise ValueError(
            f"{field_name} не может быть длиннее "
            f"{max_length} символов."
        )

    return prepared


def normalize_required_text(
    value: str,
    *,
    field_name: str,
    max_length: int,
) -> str:
    prepared = value.strip()

    if not prepared:
        raise ValueError(
            f"{field_name} не может быть пустым."
        )

    if len(prepared) > max_length:
        raise ValueError(
            f"{field_name} не может быть длиннее "
            f"{max_length} символов."
        )

    return prepared


def normalize_thumbprint(
    value: str,
) -> str:
    prepared = re.sub(
        r"[\s:]+",
        "",
        value,
    ).upper()

    if not THUMBPRINT_PATTERN.fullmatch(
        prepared
    ):
        raise ValueError(
            "Отпечаток сертификата должен "
            "содержать 40 шестнадцатеричных символов."
        )

    return prepared


def normalize_store_location(
    value: str,
) -> str:
    prepared = value.strip()

    if prepared not in STORE_LOCATIONS:
        raise ValueError(
            "Хранилище сертификата должно быть "
            "CurrentUser или LocalMachine."
        )

    return prepared


def normalize_product_group(
    value: str,
) -> str:
    prepared = value.strip().lower()

    if not PRODUCT_GROUP_PATTERN.fullmatch(
        prepared
    ):
        raise ValueError(
            "Товарная группа должна содержать "
            "латинские буквы, цифры, дефис "
            "или подчёркивание."
        )

    return prepared


def normalize_cron(
    value: str | None,
    *,
    schedule_enabled: bool,
) -> str | None:
    if value is None:
        prepared = None

    else:
        prepared = value.strip() or None

    if not schedule_enabled:
        return prepared

    if prepared is None:
        raise ValueError(
            "Для включённого расписания "
            "необходимо указать schedule_cron."
        )

    if len(
        prepared.split()
    ) != 5:
        raise ValueError(
            "Расписание должно быть указано "
            "в стандартном пятичастном cron-формате."
        )

    if len(prepared) > 255:
        raise ValueError(
            "Cron-выражение слишком длинное."
        )

    return prepared


def parse_datetime_utc(
    value: str | None,
    *,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    prepared = value.strip()

    if not prepared:
        return None

    if prepared.endswith("Z"):
        prepared = (
            prepared[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            prepared
        )

    except ValueError as exc:
        raise ValueError(
            f"{field_name} должен быть "
            "в формате ISO 8601."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return (
        parsed
        .astimezone(
            timezone.utc
        )
        .replace(
            tzinfo=None
        )
    )


def activation_problems(
    *,
    entity_type: str,
    kpp: str | None,
    current_status: str,
    active_certificate_count: int,
    enabled_product_group_count: int,
) -> list[str]:
    problems: list[str] = []

    if current_status == "DISABLED":
        problems.append(
            "организация находится "
            "в статусе DISABLED"
        )

    if (
        entity_type == ENTITY_TYPE_LEGAL
        and not kpp
    ):
        problems.append(
            "для юридического лица "
            "не указан КПП"
        )

    if active_certificate_count < 1:
        problems.append(
            "отсутствует действующий "
            "активный сертификат"
        )

    if enabled_product_group_count < 1:
        problems.append(
            "не включена ни одна "
            "товарная группа"
        )

    return problems


def run_cli(
    action: Callable[[], T],
) -> T:
    try:
        return action()

    except typer.Exit:
        raise

    except Exception as exc:
        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc


def get_entity(
    connection: MySQLConnection,
    entity_id: int,
) -> dict[str, Any]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                id,
                entity_uuid,
                inn,
                kpp,
                short_name,
                full_name,
                entity_type,
                status,
                timezone_name,
                notes,
                created_at,
                updated_at
            FROM legal_entity
            WHERE id = %s
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
        raise ValueError(
            "Юридическое лицо "
            f"с id={entity_id} не найдено."
        )

    return row


def create_legal_entity(
    *,
    database: Database,
    entity_type: str,
    inn: str,
    kpp: str | None,
    short_name: str,
    full_name: str | None,
    timezone_name: str,
    notes: str | None,
) -> tuple[int, str]:
    prepared_type = normalize_entity_type(
        entity_type
    )

    prepared_inn = normalize_inn(
        inn,
        prepared_type,
    )

    prepared_kpp = normalize_kpp(
        kpp,
        prepared_type,
    )

    prepared_short_name = normalize_required_text(
        short_name,
        field_name="Краткое наименование",
        max_length=255,
    )

    prepared_full_name = normalize_optional_text(
        full_name,
        field_name="Полное наименование",
        max_length=512,
    )

    prepared_timezone = normalize_required_text(
        timezone_name,
        field_name="Часовой пояс",
        max_length=64,
    )

    prepared_notes = normalize_optional_text(
        notes,
        field_name="Примечание",
        max_length=2000,
    )

    entity_uuid = str(
        uuid.uuid4()
    )

    try:
        with database.transaction() as connection:
            cursor = connection.cursor()

            try:
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
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        entity_uuid,
                        prepared_inn,
                        prepared_kpp,
                        prepared_short_name,
                        prepared_full_name,
                        prepared_type,
                        prepared_timezone,
                        prepared_notes,
                    ),
                )

                entity_id = int(
                    cursor.lastrowid
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

            finally:
                cursor.close()

    except IntegrityError as exc:
        if exc.errno == 1062:
            raise ValueError(
                "Юридическое лицо "
                f"с ИНН {prepared_inn} "
                "уже существует."
            ) from exc

        raise

    return (
        entity_id,
        entity_uuid,
    )


def list_legal_entities(
    database: Database,
) -> list[dict[str, Any]]:
    connection = database.connect()

    try:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    e.id,
                    e.inn,
                    e.kpp,
                    e.short_name,
                    e.entity_type,
                    e.status,
                    e.timezone_name,

                    (
                        SELECT COUNT(*)
                        FROM legal_entity_certificate c
                        WHERE c.legal_entity_id = e.id
                          AND c.is_active = 1
                          AND (
                              c.valid_from IS NULL
                              OR c.valid_from <= UTC_TIMESTAMP(6)
                          )
                          AND (
                              c.valid_to IS NULL
                              OR c.valid_to > UTC_TIMESTAMP(6)
                          )
                    ) AS active_certificate_count,

                    (
                        SELECT COUNT(*)
                        FROM legal_entity_product_group pg
                        WHERE pg.legal_entity_id = e.id
                          AND pg.is_enabled = 1
                    ) AS enabled_product_group_count

                FROM legal_entity e
                ORDER BY
                    e.short_name,
                    e.id
                """
            )

            return list(
                cursor.fetchall()
            )

        finally:
            cursor.close()

    finally:
        connection.close()


def read_legal_entity_card(
    database: Database,
    entity_id: int,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    connection = database.connect()

    try:
        entity = get_entity(
            connection,
            entity_id,
        )

        certificate_cursor = connection.cursor(
            dictionary=True
        )

        try:
            certificate_cursor.execute(
                """
                SELECT
                    id,
                    thumbprint,
                    subject_name,
                    serial_number,
                    issuer_name,
                    valid_from,
                    valid_to,
                    store_location,
                    store_name,
                    provider_name,
                    diskontrol_profile,
                    is_active,
                    created_at,
                    updated_at
                FROM legal_entity_certificate
                WHERE legal_entity_id = %s
                ORDER BY
                    is_active DESC,
                    valid_to DESC,
                    id DESC
                """,
                (
                    entity_id,
                ),
            )

            certificates = list(
                certificate_cursor.fetchall()
            )

        finally:
            certificate_cursor.close()

        group_cursor = connection.cursor(
            dictionary=True
        )

        try:
            group_cursor.execute(
                """
                SELECT
                    id,
                    product_group,
                    is_enabled,
                    schedule_enabled,
                    schedule_cron,
                    lookback_days,
                    request_limit,
                    max_list_requests,
                    details_delay_ms,
                    batch_size,
                    edo_delay_ms,
                    created_at,
                    updated_at
                FROM legal_entity_product_group
                WHERE legal_entity_id = %s
                ORDER BY product_group
                """,
                (
                    entity_id,
                ),
            )

            groups = list(
                group_cursor.fetchall()
            )

        finally:
            group_cursor.close()

        return (
            entity,
            certificates,
            groups,
        )

    finally:
        connection.close()


def register_certificate(
    *,
    database: Database,
    entity_id: int,
    thumbprint: str,
    subject_name: str | None,
    serial_number: str | None,
    issuer_name: str | None,
    valid_from: str | None,
    valid_to: str | None,
    store_location: str,
    store_name: str,
    provider_name: str | None,
    diskontrol_profile: str | None,
    is_active: bool,
    deactivate_other: bool,
) -> int:
    prepared_thumbprint = normalize_thumbprint(
        thumbprint
    )

    prepared_subject = normalize_optional_text(
        subject_name,
        field_name="Subject сертификата",
        max_length=1000,
    )

    prepared_serial = normalize_optional_text(
        serial_number,
        field_name="Серийный номер",
        max_length=128,
    )

    prepared_issuer = normalize_optional_text(
        issuer_name,
        field_name="Issuer сертификата",
        max_length=1000,
    )

    prepared_valid_from = parse_datetime_utc(
        valid_from,
        field_name="valid_from",
    )

    prepared_valid_to = parse_datetime_utc(
        valid_to,
        field_name="valid_to",
    )

    if (
        prepared_valid_from is not None
        and prepared_valid_to is not None
        and prepared_valid_from
        >= prepared_valid_to
    ):
        raise ValueError(
            "valid_from должен быть "
            "раньше valid_to."
        )

    prepared_store_location = (
        normalize_store_location(
            store_location
        )
    )

    prepared_store_name = normalize_required_text(
        store_name,
        field_name="Хранилище сертификатов",
        max_length=64,
    )

    prepared_provider = normalize_optional_text(
        provider_name,
        field_name="Криптопровайдер",
        max_length=255,
    )

    prepared_diskontrol = normalize_optional_text(
        diskontrol_profile,
        field_name="Профиль DiskKontrol",
        max_length=255,
    )

    with database.transaction() as connection:
        get_entity(
            connection,
            entity_id,
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
                LIMIT 1
                """,
                (
                    prepared_thumbprint,
                ),
            )

            existing = cursor.fetchone()

        finally:
            cursor.close()

        if (
            existing is not None
            and int(
                existing["legal_entity_id"]
            )
            != entity_id
        ):
            raise ValueError(
                "Этот отпечаток уже зарегистрирован "
                "за другим юридическим лицом."
            )

        if (
            deactivate_other
            and is_active
        ):
            deactivate_cursor = connection.cursor()

            try:
                deactivate_cursor.execute(
                    """
                    UPDATE legal_entity_certificate
                       SET is_active = 0,
                           updated_at = UTC_TIMESTAMP(6)
                     WHERE legal_entity_id = %s
                    """,
                    (
                        entity_id,
                    ),
                )

            finally:
                deactivate_cursor.close()

        if existing is None:
            insert_cursor = connection.cursor()

            try:
                insert_cursor.execute(
                    """
                    INSERT INTO legal_entity_certificate (
                        legal_entity_id,
                        thumbprint,
                        subject_name,
                        serial_number,
                        issuer_name,
                        valid_from,
                        valid_to,
                        store_location,
                        store_name,
                        provider_name,
                        diskontrol_profile,
                        is_active,
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
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        entity_id,
                        prepared_thumbprint,
                        prepared_subject,
                        prepared_serial,
                        prepared_issuer,
                        prepared_valid_from,
                        prepared_valid_to,
                        prepared_store_location,
                        prepared_store_name,
                        prepared_provider,
                        prepared_diskontrol,
                        int(is_active),
                    ),
                )

                certificate_id = int(
                    insert_cursor.lastrowid
                )

            finally:
                insert_cursor.close()

        else:
            certificate_id = int(
                existing["id"]
            )

            update_cursor = connection.cursor()

            try:
                update_cursor.execute(
                    """
                    UPDATE legal_entity_certificate
                       SET subject_name =
                               COALESCE(%s, subject_name),
                           serial_number =
                               COALESCE(%s, serial_number),
                           issuer_name =
                               COALESCE(%s, issuer_name),
                           valid_from =
                               COALESCE(%s, valid_from),
                           valid_to =
                               COALESCE(%s, valid_to),
                           store_location = %s,
                           store_name = %s,
                           provider_name =
                               COALESCE(%s, provider_name),
                           diskontrol_profile =
                               COALESCE(
                                   %s,
                                   diskontrol_profile
                               ),
                           is_active = %s,
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = %s
                    """,
                    (
                        prepared_subject,
                        prepared_serial,
                        prepared_issuer,
                        prepared_valid_from,
                        prepared_valid_to,
                        prepared_store_location,
                        prepared_store_name,
                        prepared_provider,
                        prepared_diskontrol,
                        int(is_active),
                        certificate_id,
                    ),
                )

            finally:
                update_cursor.close()

    return certificate_id


def set_product_group(
    *,
    database: Database,
    entity_id: int,
    product_group: str,
    is_enabled: bool,
    schedule_enabled: bool,
    schedule_cron: str | None,
    lookback_days: int,
    request_limit: int,
    max_list_requests: int,
    details_delay_ms: int,
    batch_size: int,
    edo_delay_ms: int,
) -> int:
    prepared_group = normalize_product_group(
        product_group
    )

    prepared_cron = normalize_cron(
        schedule_cron,
        schedule_enabled=schedule_enabled,
    )

    if not 1 <= lookback_days <= 365:
        raise ValueError(
            "lookback_days должен быть "
            "от 1 до 365."
        )

    if not 1 <= request_limit <= 1000:
        raise ValueError(
            "request_limit должен быть "
            "от 1 до 1000."
        )

    if not 1 <= max_list_requests <= 10000:
        raise ValueError(
            "max_list_requests должен быть "
            "от 1 до 10000."
        )

    if details_delay_ms < 0:
        raise ValueError(
            "details_delay_ms не может "
            "быть отрицательным."
        )

    if not 1 <= batch_size <= 1000:
        raise ValueError(
            "batch_size должен быть "
            "от 1 до 1000."
        )

    if edo_delay_ms < 0:
        raise ValueError(
            "edo_delay_ms не может "
            "быть отрицательным."
        )

    with database.transaction() as connection:
        get_entity(
            connection,
            entity_id,
        )

        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT id
                FROM legal_entity_product_group
                WHERE legal_entity_id = %s
                  AND product_group = %s
                LIMIT 1
                """,
                (
                    entity_id,
                    prepared_group,
                ),
            )

            existing = cursor.fetchone()

        finally:
            cursor.close()

        if existing is None:
            insert_cursor = connection.cursor()

            try:
                insert_cursor.execute(
                    """
                    INSERT INTO legal_entity_product_group (
                        legal_entity_id,
                        product_group,
                        is_enabled,
                        schedule_enabled,
                        schedule_cron,
                        lookback_days,
                        request_limit,
                        max_list_requests,
                        details_delay_ms,
                        batch_size,
                        edo_delay_ms,
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
                        UTC_TIMESTAMP(6),
                        UTC_TIMESTAMP(6)
                    )
                    """,
                    (
                        entity_id,
                        prepared_group,
                        int(is_enabled),
                        int(schedule_enabled),
                        prepared_cron,
                        lookback_days,
                        request_limit,
                        max_list_requests,
                        details_delay_ms,
                        batch_size,
                        edo_delay_ms,
                    ),
                )

                group_id = int(
                    insert_cursor.lastrowid
                )

            finally:
                insert_cursor.close()

        else:
            group_id = int(
                existing["id"]
            )

            update_cursor = connection.cursor()

            try:
                update_cursor.execute(
                    """
                    UPDATE legal_entity_product_group
                       SET is_enabled = %s,
                           schedule_enabled = %s,
                           schedule_cron = %s,
                           lookback_days = %s,
                           request_limit = %s,
                           max_list_requests = %s,
                           details_delay_ms = %s,
                           batch_size = %s,
                           edo_delay_ms = %s,
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = %s
                    """,
                    (
                        int(is_enabled),
                        int(schedule_enabled),
                        prepared_cron,
                        lookback_days,
                        request_limit,
                        max_list_requests,
                        details_delay_ms,
                        batch_size,
                        edo_delay_ms,
                        group_id,
                    ),
                )

            finally:
                update_cursor.close()

    return group_id


def activate_legal_entity(
    *,
    database: Database,
    entity_id: int,
) -> None:
    with database.transaction() as connection:
        entity = get_entity(
            connection,
            entity_id,
        )

        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM legal_entity_certificate c
                        WHERE c.legal_entity_id = e.id
                          AND c.is_active = 1
                          AND (
                              c.valid_from IS NULL
                              OR c.valid_from <= UTC_TIMESTAMP(6)
                          )
                          AND (
                              c.valid_to IS NULL
                              OR c.valid_to > UTC_TIMESTAMP(6)
                          )
                    ) AS active_certificate_count,

                    (
                        SELECT COUNT(*)
                        FROM legal_entity_product_group pg
                        WHERE pg.legal_entity_id = e.id
                          AND pg.is_enabled = 1
                    ) AS enabled_product_group_count

                FROM legal_entity e
                WHERE e.id = %s
                """,
                (
                    entity_id,
                ),
            )

            counts = cursor.fetchone()

        finally:
            cursor.close()

        if counts is None:
            raise RuntimeError(
                "Не удалось проверить "
                "готовность юридического лица."
            )

        problems = activation_problems(
            entity_type=str(
                entity["entity_type"]
            ),
            kpp=(
                str(
                    entity["kpp"]
                )
                if entity["kpp"] is not None
                else None
            ),
            current_status=str(
                entity["status"]
            ),
            active_certificate_count=int(
                counts["active_certificate_count"]
            ),
            enabled_product_group_count=int(
                counts["enabled_product_group_count"]
            ),
        )

        if problems:
            raise ValueError(
                "Юридическое лицо не готово "
                "к активации: "
                + "; ".join(
                    problems
                )
                + "."
            )

        update_cursor = connection.cursor()

        try:
            update_cursor.execute(
                """
                UPDATE legal_entity
                   SET status = 'ACTIVE',
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    entity_id,
                ),
            )

        finally:
            update_cursor.close()


def set_legal_entity_status(
    *,
    database: Database,
    entity_id: int,
    status: str,
) -> None:
    prepared_status = status.strip().upper()

    if prepared_status not in ENTITY_STATUSES:
        raise ValueError(
            "Допустимые статусы: "
            "SETUP, ACTIVE, SUSPENDED, DISABLED."
        )

    if prepared_status == "ACTIVE":
        raise ValueError(
            "Для перехода в ACTIVE "
            "используйте команду activate."
        )

    with database.transaction() as connection:
        get_entity(
            connection,
            entity_id,
        )

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE legal_entity
                   SET status = %s,
                       updated_at = UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    prepared_status,
                    entity_id,
                ),
            )

        finally:
            cursor.close()


def format_datetime(
    value: Any,
) -> str:
    if value is None:
        return "—"

    if isinstance(
        value,
        datetime,
    ):
        return (
            value.isoformat(
                sep=" ",
                timespec="seconds",
            )
            + " UTC"
        )

    return str(
        value
    )


def format_boolean(
    value: Any,
) -> str:
    return (
        "да"
        if bool(value)
        else "нет"
    )


@app.command("create")
def create_command(
    entity_type: str = typer.Option(
        ...,
        "--entity-type",
        help=(
            "Тип субъекта: "
            "LEGAL_ENTITY или IP."
        ),
    ),
    inn: str = typer.Option(
        ...,
        "--inn",
        help="ИНН.",
    ),
    short_name: str = typer.Option(
        ...,
        "--short-name",
        help="Краткое наименование.",
    ),
    kpp: str | None = typer.Option(
        None,
        "--kpp",
        help="КПП юридического лица.",
    ),
    full_name: str | None = typer.Option(
        None,
        "--full-name",
        help="Полное наименование.",
    ),
    timezone_name: str = typer.Option(
        "Europe/Moscow",
        "--timezone",
        help="Часовой пояс.",
    ),
    notes: str | None = typer.Option(
        None,
        "--notes",
        help="Примечание.",
    ),
) -> None:
    def action() -> None:
        entity_id, entity_uuid = create_legal_entity(
            database=Database(
                get_settings()
            ),
            entity_type=entity_type,
            inn=inn,
            kpp=kpp,
            short_name=short_name,
            full_name=full_name,
            timezone_name=timezone_name,
            notes=notes,
        )

        typer.echo(
            "Карточка создана."
        )
        typer.echo(
            f"id: {entity_id}"
        )
        typer.echo(
            f"uuid: {entity_uuid}"
        )
        typer.echo(
            "status: SETUP"
        )

    run_cli(
        action
    )


@app.command("list")
def list_command() -> None:
    def action() -> None:
        rows = list_legal_entities(
            Database(
                get_settings()
            )
        )

        if not rows:
            typer.echo(
                "Справочник юридических лиц пуст."
            )
            return

        typer.echo(
            "ID  Статус     ИНН           "
            "Сертификаты  Группы  Наименование"
        )

        for row in rows:
            typer.echo(
                f"{int(row['id']):<3} "
                f"{str(row['status']):<10} "
                f"{str(row['inn']):<13} "
                f"{int(row['active_certificate_count']):<12} "
                f"{int(row['enabled_product_group_count']):<6} "
                f"{row['short_name']}"
            )

    run_cli(
        action
    )


@app.command("show")
def show_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help="ID карточки.",
    ),
) -> None:
    def action() -> None:
        entity, certificates, groups = (
            read_legal_entity_card(
                Database(
                    get_settings()
                ),
                entity_id,
            )
        )

        typer.echo(
            "Карточка юридического лица"
        )
        typer.echo(
            f"id: {entity['id']}"
        )
        typer.echo(
            f"uuid: {entity['entity_uuid']}"
        )
        typer.echo(
            f"ИНН: {entity['inn']}"
        )
        typer.echo(
            f"КПП: {entity['kpp'] or '—'}"
        )
        typer.echo(
            f"Наименование: {entity['short_name']}"
        )
        typer.echo(
            f"Полное наименование: "
            f"{entity['full_name'] or '—'}"
        )
        typer.echo(
            f"Тип: {entity['entity_type']}"
        )
        typer.echo(
            f"Статус: {entity['status']}"
        )
        typer.echo(
            f"Часовой пояс: {entity['timezone_name']}"
        )
        typer.echo(
            f"Примечание: {entity['notes'] or '—'}"
        )

        typer.echo("")
        typer.echo(
            "Сертификаты"
        )

        if not certificates:
            typer.echo(
                "  не зарегистрированы"
            )

        for certificate in certificates:
            typer.echo(
                "  "
                f"id={certificate['id']}; "
                f"active="
                f"{format_boolean(certificate['is_active'])}; "
                f"thumbprint="
                f"{certificate['thumbprint']}; "
                f"valid_to="
                f"{format_datetime(certificate['valid_to'])}; "
                f"store="
                f"{certificate['store_location']}"
                "\\"
                f"{certificate['store_name']}"
            )

        typer.echo("")
        typer.echo(
            "Товарные группы"
        )

        if not groups:
            typer.echo(
                "  не настроены"
            )

        for group in groups:
            typer.echo(
                "  "
                f"{group['product_group']}; "
                f"enabled="
                f"{format_boolean(group['is_enabled'])}; "
                f"schedule="
                f"{format_boolean(group['schedule_enabled'])}; "
                f"cron={group['schedule_cron'] or '—'}; "
                f"lookback_days={group['lookback_days']}"
            )

    run_cli(
        action
    )


@app.command("register-certificate")
def register_certificate_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help="ID карточки.",
    ),
    thumbprint: str = typer.Option(
        ...,
        "--thumbprint",
        help="Отпечаток сертификата.",
    ),
    subject_name: str | None = typer.Option(
        None,
        "--subject-name",
    ),
    serial_number: str | None = typer.Option(
        None,
        "--serial-number",
    ),
    issuer_name: str | None = typer.Option(
        None,
        "--issuer-name",
    ),
    valid_from: str | None = typer.Option(
        None,
        "--valid-from",
        help="Начало срока действия ISO 8601.",
    ),
    valid_to: str | None = typer.Option(
        None,
        "--valid-to",
        help="Окончание срока действия ISO 8601.",
    ),
    store_location: str = typer.Option(
        "CurrentUser",
        "--store-location",
    ),
    store_name: str = typer.Option(
        "My",
        "--store-name",
    ),
    provider_name: str | None = typer.Option(
        None,
        "--provider-name",
    ),
    diskontrol_profile: str | None = typer.Option(
        None,
        "--diskontrol-profile",
    ),
    is_active: bool = typer.Option(
        True,
        "--active/--inactive",
    ),
    deactivate_other: bool = typer.Option(
        True,
        "--deactivate-other/--keep-other-active",
    ),
) -> None:
    def action() -> None:
        certificate_id = register_certificate(
            database=Database(
                get_settings()
            ),
            entity_id=entity_id,
            thumbprint=thumbprint,
            subject_name=subject_name,
            serial_number=serial_number,
            issuer_name=issuer_name,
            valid_from=valid_from,
            valid_to=valid_to,
            store_location=store_location,
            store_name=store_name,
            provider_name=provider_name,
            diskontrol_profile=diskontrol_profile,
            is_active=is_active,
            deactivate_other=deactivate_other,
        )

        typer.echo(
            "Сертификат зарегистрирован."
        )
        typer.echo(
            f"id: {certificate_id}"
        )

    run_cli(
        action
    )


@app.command("set-product-group")
def set_product_group_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
    ),
    product_group: str = typer.Option(
        ...,
        "--product-group",
    ),
    is_enabled: bool = typer.Option(
        True,
        "--enabled/--disabled",
    ),
    schedule_enabled: bool = typer.Option(
        False,
        "--schedule-enabled/--schedule-disabled",
    ),
    schedule_cron: str | None = typer.Option(
        None,
        "--schedule-cron",
    ),
    lookback_days: int = typer.Option(
        3,
        "--lookback-days",
        min=1,
        max=365,
    ),
    request_limit: int = typer.Option(
        100,
        "--request-limit",
        min=1,
        max=1000,
    ),
    max_list_requests: int = typer.Option(
        1000,
        "--max-list-requests",
        min=1,
        max=10000,
    ),
    details_delay_ms: int = typer.Option(
        100,
        "--details-delay-ms",
        min=0,
    ),
    batch_size: int = typer.Option(
        50,
        "--batch-size",
        min=1,
        max=1000,
    ),
    edo_delay_ms: int = typer.Option(
        150,
        "--edo-delay-ms",
        min=0,
    ),
) -> None:
    def action() -> None:
        group_id = set_product_group(
            database=Database(
                get_settings()
            ),
            entity_id=entity_id,
            product_group=product_group,
            is_enabled=is_enabled,
            schedule_enabled=schedule_enabled,
            schedule_cron=schedule_cron,
            lookback_days=lookback_days,
            request_limit=request_limit,
            max_list_requests=max_list_requests,
            details_delay_ms=details_delay_ms,
            batch_size=batch_size,
            edo_delay_ms=edo_delay_ms,
        )

        typer.echo(
            "Товарная группа сохранена."
        )
        typer.echo(
            f"id: {group_id}"
        )

    run_cli(
        action
    )


@app.command("activate")
def activate_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
    ),
) -> None:
    def action() -> None:
        activate_legal_entity(
            database=Database(
                get_settings()
            ),
            entity_id=entity_id,
        )

        typer.echo(
            "Юридическое лицо переведено "
            "в статус ACTIVE."
        )

    run_cli(
        action
    )


@app.command("set-status")
def set_status_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
    ),
    status: str = typer.Option(
        ...,
        "--status",
        help=(
            "SETUP, SUSPENDED или DISABLED. "
            "Для ACTIVE используйте activate."
        ),
    ),
) -> None:
    def action() -> None:
        set_legal_entity_status(
            database=Database(
                get_settings()
            ),
            entity_id=entity_id,
            status=status,
        )

        typer.echo(
            "Статус обновлён."
        )

    run_cli(
        action
    )


if __name__ == "__main__":
    app()