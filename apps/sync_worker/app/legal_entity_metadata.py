from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import typer
from mysql.connector import MySQLConnection

from app.client import GisMtClient
from app.config import get_settings
from app.db import Database


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Синхронизация сертификата и данных ГИС МТ "
        "для существующей карточки организации."
    ),
)


THUMBPRINT_PATTERN = re.compile(
    r"^[0-9A-F]{40}$"
)

INN_PATTERN = re.compile(
    r"^(?:\d{10}|\d{12})$"
)

PRODUCT_GROUP_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9_-]{0,63}$"
)


@dataclass(
    frozen=True,
    slots=True,
)
class CertificateData:
    thumbprint: str
    inn: str
    subject_name: str | None
    serial_number: str | None
    issuer_name: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    store_location: str
    store_name: str
    provider_name: str | None
    diskontrol_profile: str | None
    has_private_key: bool


@dataclass(
    frozen=True,
    slots=True,
)
class ParticipantData:
    inn: str
    name: str | None
    status_code: str | None
    status_name: str
    is_registered: bool
    product_groups: tuple[str, ...]
    raw_payload: dict[str, Any]


@dataclass(
    frozen=True,
    slots=True,
)
class MetadataSyncSummary:
    entity_id: int
    inn: str
    participant_name: str | None
    participant_status: str
    certificate_id: int
    product_group_count: int
    added_product_group_count: int
    confirmed_product_group_count: int
    unavailable_product_group_count: int

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "inn": self.inn,
            "participant_name": self.participant_name,
            "participant_status": self.participant_status,
            "certificate_id": self.certificate_id,
            "product_group_count": self.product_group_count,
            "added_product_group_count": (
                self.added_product_group_count
            ),
            "confirmed_product_group_count": (
                self.confirmed_product_group_count
            ),
            "unavailable_product_group_count": (
                self.unavailable_product_group_count
            ),
        }


def normalize_optional_text(
    value: Any,
    *,
    max_length: int,
) -> str | None:
    if value is None:
        return None

    prepared = str(
        value
    ).strip()

    if not prepared:
        return None

    return prepared[
        :max_length
    ]


def parse_boolean(
    value: Any,
    *,
    field_name: str,
) -> bool:
    if isinstance(
        value,
        bool,
    ):
        return value

    if isinstance(
        value,
        int,
    ) and value in {
        0,
        1,
    }:
        return bool(
            value
        )

    prepared = str(
        value
    ).strip().lower()

    if prepared in {
        "true",
        "1",
        "yes",
    }:
        return True

    if prepared in {
        "false",
        "0",
        "no",
        "",
    }:
        return False

    raise ValueError(
        f"Поле {field_name} должно "
        "содержать логическое значение."
    )


def parse_utc_datetime(
    value: Any,
    *,
    field_name: str,
) -> datetime | None:
    prepared = str(
        value or ""
    ).strip()

    if not prepared:
        return None

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
        raise ValueError(
            f"Поле {field_name} должно "
            "содержать дату ISO 8601."
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


def parse_certificate(
    payload: Any,
) -> CertificateData:
    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Входные данные не содержат "
            "объект certificate."
        )

    thumbprint = re.sub(
        r"[^0-9A-Fa-f]",
        "",
        str(
            payload.get(
                "thumbprint",
                "",
            )
        ),
    ).upper()

    if not THUMBPRINT_PATTERN.fullmatch(
        thumbprint
    ):
        raise ValueError(
            "Отпечаток сертификата должен "
            "содержать 40 шестнадцатеричных символов."
        )

    inn = str(
        payload.get(
            "certificate_inn",
            "",
        )
    ).strip()

    if not INN_PATTERN.fullmatch(
        inn
    ):
        raise ValueError(
            "ИНН сертификата должен "
            "содержать 10 или 12 цифр."
        )

    store_location = str(
        payload.get(
            "store_location",
            "",
        )
    ).strip()

    if store_location not in {
        "CurrentUser",
        "LocalMachine",
    }:
        raise ValueError(
            "Хранилище сертификата должно быть "
            "CurrentUser или LocalMachine."
        )

    store_name = (
        normalize_optional_text(
            payload.get(
                "store_name"
            ),
            max_length=64,
        )
        or "My"
    )

    valid_from = parse_utc_datetime(
        payload.get(
            "valid_from"
        ),
        field_name="valid_from",
    )

    valid_to = parse_utc_datetime(
        payload.get(
            "valid_to"
        ),
        field_name="valid_to",
    )

    if (
        valid_from is not None
        and valid_to is not None
        and valid_from >= valid_to
    ):
        raise ValueError(
            "Дата начала действия сертификата "
            "должна быть раньше даты окончания."
        )

    return CertificateData(
        thumbprint=thumbprint,
        inn=inn,
        subject_name=normalize_optional_text(
            payload.get(
                "subject_name"
            ),
            max_length=1000,
        ),
        serial_number=normalize_optional_text(
            payload.get(
                "serial_number"
            ),
            max_length=128,
        ),
        issuer_name=normalize_optional_text(
            payload.get(
                "issuer_name"
            ),
            max_length=1000,
        ),
        valid_from=valid_from,
        valid_to=valid_to,
        store_location=store_location,
        store_name=store_name,
        provider_name=normalize_optional_text(
            payload.get(
                "provider_name"
            ),
            max_length=255,
        ),
        diskontrol_profile=normalize_optional_text(
            payload.get(
                "diskontrol_profile"
            ),
            max_length=255,
        ),
        has_private_key=parse_boolean(
            payload.get(
                "has_private_key"
            ),
            field_name="has_private_key",
        ),
    )


def participant_candidates(
    payload: Any,
) -> list[dict[str, Any]]:
    if isinstance(
        payload,
        list,
    ):
        return [
            item
            for item in payload
            if isinstance(
                item,
                dict,
            )
        ]

    if not isinstance(
        payload,
        dict,
    ):
        return []

    if "inn" in payload:
        return [
            payload
        ]

    for key in (
        "result",
        "participants",
        "items",
        "data",
    ):
        nested = payload.get(
            key
        )

        if isinstance(
            nested,
            dict,
        ):
            if "inn" in nested:
                return [
                    nested
                ]

            continue

        if isinstance(
            nested,
            list,
        ):
            return [
                item
                for item in nested
                if isinstance(
                    item,
                    dict,
                )
            ]

    return []


def parse_participant(
    payload: Any,
    expected_inn: str,
) -> ParticipantData:
    participant = next(
        (
            item
            for item in participant_candidates(
                payload
            )
            if str(
                item.get(
                    "inn",
                    "",
                )
            ).strip()
            == expected_inn
        ),
        None,
    )

    if participant is None:
        raise ValueError(
            "Ответ /participants не содержит "
            f"карточку ИНН {expected_inn}."
        )

    error_code = normalize_optional_text(
        participant.get(
            "error_code"
        ),
        max_length=64,
    )

    error_message = normalize_optional_text(
        participant.get(
            "error_message"
        ),
        max_length=1000,
    )

    if error_code or error_message:
        raise ValueError(
            "ГИС МТ не вернула карточку участника: "
            f"{error_code or 'UNKNOWN'} — "
            f"{error_message or 'неизвестная ошибка'}."
        )

    status_name = normalize_optional_text(
        participant.get(
            "status"
        ),
        max_length=255,
    )

    if status_name is None:
        raise ValueError(
            "Ответ /participants не содержит "
            "статус участника."
        )

    raw_groups = participant.get(
        "productGroups"
    )

    if raw_groups is None:
        raw_groups = []

    if not isinstance(
        raw_groups,
        list,
    ):
        raise ValueError(
            "Поле productGroups имеет "
            "неожиданный формат."
        )

    product_groups: set[str] = set()

    for item in raw_groups:
        group = str(
            item
        ).strip().lower()

        if not PRODUCT_GROUP_PATTERN.fullmatch(
            group
        ):
            raise ValueError(
                "ГИС МТ вернула некорректный "
                f"код товарной группы: {item!r}."
            )

        product_groups.add(
            group
        )

    raw_is_registered = participant.get(
        "is_registered"
    )

    if isinstance(
        raw_is_registered,
        bool,
    ):
        is_registered = raw_is_registered

    else:
        status_code = str(
            participant.get(
                "statusInn",
                "",
            )
        ).strip().upper()

        is_registered = status_code in {
            "REGISTERED",
            "RESTORED",
            "BLOCKED",
        }

    return ParticipantData(
        inn=expected_inn,
        name=normalize_optional_text(
            participant.get(
                "name"
            ),
            max_length=512,
        ),
        status_code=normalize_optional_text(
            participant.get(
                "statusInn"
            ),
            max_length=64,
        ),
        status_name=status_name,
        is_registered=is_registered,
        product_groups=tuple(
            sorted(
                product_groups
            )
        ),
        raw_payload=participant,
    )


def read_input_payload() -> dict[str, Any]:
    encoded = sys.stdin.read().strip()

    if not encoded:
        raise ValueError(
            "В stdin отсутствуют входные данные."
        )

    try:
        decoded = base64.b64decode(
            encoded,
            validate=True,
        ).decode(
            "utf-8"
        )

        payload = json.loads(
            decoded
        )

    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Не удалось прочитать "
            "Base64 JSON из stdin."
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Входной JSON должен быть объектом."
        )

    return payload


def ensure_integration_config(
    connection: MySQLConnection,
    entity_id: int,
) -> None:
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT IGNORE INTO
                legal_entity_integration_config
            (
                legal_entity_id,
                created_at,
                updated_at
            )
            SELECT
                id,
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6)
            FROM legal_entity
            WHERE id = %s
            """,
            (
                entity_id,
            ),
        )

    finally:
        cursor.close()


def get_sync_target(
    connection: MySQLConnection,
    entity_id: int,
    *,
    for_update: bool = False,
) -> dict[str, Any]:
    ensure_integration_config(
        connection,
        entity_id,
    )

    lock_clause = (
        " FOR UPDATE"
        if for_update
        else ""
    )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            f"""
            SELECT
                e.id,
                e.inn,
                e.short_name,
                e.entity_type,
                e.status,

                config.true_api_enabled,
                config.auto_discover_certificate,
                config.auto_discover_product_groups,
                config.new_group_default_enabled,

                config.default_lookback_days,
                config.default_request_limit,
                config.default_max_list_requests,
                config.default_details_delay_ms,
                config.default_batch_size,
                config.default_edo_delay_ms

            FROM legal_entity e

            JOIN legal_entity_integration_config config
              ON config.legal_entity_id = e.id

            WHERE e.id = %s

            LIMIT 1
            {lock_clause}
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
            "Карточка организации "
            f"id={entity_id} не найдена."
        )

    return row


def validate_sync_target(
    target: dict[str, Any],
    certificate: CertificateData,
) -> None:
    status = str(
        target["status"]
    ).strip().upper()

    if status in {
        "SUSPENDED",
        "DISABLED",
    }:
        raise ValueError(
            "Синхронизация запрещена "
            f"для карточки со статусом {status}."
        )

    if not bool(
        target[
            "true_api_enabled"
        ]
    ):
        raise ValueError(
            "True API отключён "
            "в конфигурации организации."
        )

    if not bool(
        target[
            "auto_discover_certificate"
        ]
    ):
        raise ValueError(
            "Автоматический поиск сертификата "
            "отключён в конфигурации организации."
        )

    if not bool(
        target[
            "auto_discover_product_groups"
        ]
    ):
        raise ValueError(
            "Автоматическое получение "
            "товарных групп отключено."
        )

    entity_inn = str(
        target["inn"]
    ).strip()

    if entity_inn != certificate.inn:
        raise ValueError(
            "ИНН сертификата не совпадает "
            "с ИНН карточки организации."
        )

    if not certificate.has_private_key:
        raise ValueError(
            "У сертификата отсутствует "
            "закрытый ключ."
        )

    now = datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )

    if (
        certificate.valid_from is not None
        and certificate.valid_from > now
    ):
        raise ValueError(
            "Срок действия сертификата "
            "ещё не начался."
        )

    if (
        certificate.valid_to is not None
        and certificate.valid_to <= now
    ):
        raise ValueError(
            "Сертификат просрочен."
        )


def save_certificate(
    connection: MySQLConnection,
    *,
    entity_id: int,
    certificate: CertificateData,
) -> int:
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
                certificate.thumbprint,
            ),
        )

        existing = cursor.fetchone()

    finally:
        cursor.close()

    if (
        existing is not None
        and int(
            existing[
                "legal_entity_id"
            ]
        )
        != entity_id
    ):
        raise ValueError(
            "Сертификат уже привязан "
            "к другой организации."
        )

    cursor = connection.cursor()

    try:
        cursor.execute(
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

        if existing is not None:
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
                    certificate.inn,
                    certificate.subject_name,
                    certificate.serial_number,
                    certificate.issuer_name,
                    certificate.valid_from,
                    certificate.valid_to,
                    certificate.store_location,
                    certificate.store_name,
                    certificate.provider_name,
                    certificate.diskontrol_profile,
                    int(
                        certificate.has_private_key
                    ),
                    certificate_id,
                ),
            )

        else:
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
                    certificate.thumbprint,
                    certificate.inn,
                    certificate.subject_name,
                    certificate.serial_number,
                    certificate.issuer_name,
                    certificate.valid_from,
                    certificate.valid_to,
                    certificate.store_location,
                    certificate.store_name,
                    certificate.provider_name,
                    certificate.diskontrol_profile,
                    int(
                        certificate.has_private_key
                    ),
                ),
            )

            certificate_id = int(
                cursor.lastrowid
            )

    finally:
        cursor.close()

    return certificate_id


def synchronize_product_groups(
    connection: MySQLConnection,
    *,
    target: dict[str, Any],
    participant: ParticipantData,
) -> tuple[int, int, int]:
    entity_id = int(
        target["id"]
    )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                product_group,
                gis_mt_available
            FROM legal_entity_product_group
            WHERE legal_entity_id = %s
            """,
            (
                entity_id,
            ),
        )

        rows = list(
            cursor.fetchall()
        )

    finally:
        cursor.close()

    existing_groups = {
        str(
            row["product_group"]
        ): bool(
            row["gis_mt_available"]
        )
        for row in rows
    }

    returned_groups = set(
        participant.product_groups
    )

    previously_available = {
        group
        for group, available
        in existing_groups.items()
        if available
    }

    unavailable_count = len(
        previously_available
        - returned_groups
    )

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE legal_entity_product_group
               SET gis_mt_available = 0,
                   gis_mt_unavailable_at =
                       COALESCE(
                           gis_mt_unavailable_at,
                           UTC_TIMESTAMP(6)
                       ),
                   updated_at =
                       UTC_TIMESTAMP(6)
             WHERE legal_entity_id = %s
               AND gis_mt_available = 1
            """,
            (
                entity_id,
            ),
        )

        for product_group in participant.product_groups:
            cursor.execute(
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
                    gis_mt_available,
                    gis_mt_first_seen_at,
                    gis_mt_last_seen_at,
                    gis_mt_unavailable_at,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    0,
                    NULL,
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
                    gis_mt_available = 1,
                    gis_mt_first_seen_at =
                        COALESCE(
                            gis_mt_first_seen_at,
                            UTC_TIMESTAMP(6)
                        ),
                    gis_mt_last_seen_at =
                        UTC_TIMESTAMP(6),
                    gis_mt_unavailable_at = NULL,
                    updated_at =
                        UTC_TIMESTAMP(6)
                """,
                (
                    entity_id,
                    product_group,
                    int(
                        bool(
                            target[
                                "new_group_default_enabled"
                            ]
                        )
                    ),
                    int(
                        target[
                            "default_lookback_days"
                        ]
                    ),
                    int(
                        target[
                            "default_request_limit"
                        ]
                    ),
                    int(
                        target[
                            "default_max_list_requests"
                        ]
                    ),
                    int(
                        target[
                            "default_details_delay_ms"
                        ]
                    ),
                    int(
                        target[
                            "default_batch_size"
                        ]
                    ),
                    int(
                        target[
                            "default_edo_delay_ms"
                        ]
                    ),
                ),
            )

    finally:
        cursor.close()

    added_count = sum(
        product_group not in existing_groups
        for product_group
        in participant.product_groups
    )

    confirmed_count = (
        len(
            participant.product_groups
        )
        - added_count
    )

    return (
        added_count,
        confirmed_count,
        unavailable_count,
    )


def save_successful_sync(
    database: Database,
    *,
    entity_id: int,
    certificate: CertificateData,
    participant: ParticipantData,
) -> MetadataSyncSummary:
    with database.transaction() as connection:
        target = get_sync_target(
            connection,
            entity_id,
            for_update=True,
        )

        validate_sync_target(
            target,
            certificate,
        )

        if participant.inn != certificate.inn:
            raise ValueError(
                "ИНН участника ГИС МТ "
                "не совпадает с ИНН сертификата."
            )

        certificate_id = save_certificate(
            connection,
            entity_id=entity_id,
            certificate=certificate,
        )

        (
            added_count,
            confirmed_count,
            unavailable_count,
        ) = synchronize_product_groups(
            connection,
            target=target,
            participant=participant,
        )

        participant_json = json.dumps(
            participant.raw_payload,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )

        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE legal_entity
                   SET gis_mt_name = %s,
                       gis_mt_status_code = %s,
                       gis_mt_status_name = %s,
                       gis_mt_is_registered = %s,
                       gis_mt_participant_json = %s,
                       gis_mt_last_sync_at =
                           UTC_TIMESTAMP(6),
                       gis_mt_last_sync_status =
                           'SUCCESS',
                       gis_mt_last_error = NULL,
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE id = %s
                """,
                (
                    participant.name,
                    participant.status_code,
                    participant.status_name,
                    int(
                        participant.is_registered
                    ),
                    participant_json,
                    entity_id,
                ),
            )

            cursor.execute(
                """
                UPDATE legal_entity_integration_config
                   SET last_metadata_sync_at =
                           UTC_TIMESTAMP(6),
                       last_metadata_sync_status =
                           'SUCCESS',
                       last_metadata_sync_error = NULL,
                       updated_at =
                           UTC_TIMESTAMP(6)
                 WHERE legal_entity_id = %s
                """,
                (
                    entity_id,
                ),
            )

        finally:
            cursor.close()

    return MetadataSyncSummary(
        entity_id=entity_id,
        inn=participant.inn,
        participant_name=participant.name,
        participant_status=participant.status_name,
        certificate_id=certificate_id,
        product_group_count=len(
            participant.product_groups
        ),
        added_product_group_count=added_count,
        confirmed_product_group_count=confirmed_count,
        unavailable_product_group_count=unavailable_count,
    )


def record_failed_sync(
    database: Database,
    *,
    entity_id: int,
    exc: Exception,
) -> None:
    error_message = (
        f"{type(exc).__name__}: {exc}"
    )[:2000]

    try:
        with database.transaction() as connection:
            ensure_integration_config(
                connection,
                entity_id,
            )

            cursor = connection.cursor()

            try:
                cursor.execute(
                    """
                    UPDATE legal_entity
                       SET gis_mt_last_sync_at =
                               UTC_TIMESTAMP(6),
                           gis_mt_last_sync_status =
                               'ERROR',
                           gis_mt_last_error = %s,
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE id = %s
                    """,
                    (
                        error_message,
                        entity_id,
                    ),
                )

                cursor.execute(
                    """
                    UPDATE legal_entity_integration_config
                       SET last_metadata_sync_at =
                               UTC_TIMESTAMP(6),
                           last_metadata_sync_status =
                               'ERROR',
                           last_metadata_sync_error = %s,
                           updated_at =
                               UTC_TIMESTAMP(6)
                     WHERE legal_entity_id = %s
                    """,
                    (
                        error_message,
                        entity_id,
                    ),
                )

            finally:
                cursor.close()

    except Exception:
        return


async def run_metadata_sync(
    database: Database,
    *,
    entity_id: int,
    token: str,
    certificate: CertificateData,
) -> MetadataSyncSummary:
    prepared_token = token.strip()

    if not prepared_token:
        raise ValueError(
            "Токен True API отсутствует."
        )

    with database.transaction() as connection:
        target = get_sync_target(
            connection,
            entity_id,
        )

    validate_sync_target(
        target,
        certificate,
    )

    settings = get_settings()

    async with GisMtClient(
        settings,
        prepared_token,
    ) as client:
        api_result = await client.get_participants(
            inns=[
                certificate.inn
            ]
        )

    participant = parse_participant(
        api_result.payload,
        certificate.inn,
    )

    return save_successful_sync(
        database,
        entity_id=entity_id,
        certificate=certificate,
        participant=participant,
    )


@app.command("target")
def target_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help="ID существующей карточки организации.",
    ),
) -> None:
    database = Database(
        get_settings()
    )

    try:
        with database.transaction() as connection:
            target = get_sync_target(
                connection,
                entity_id,
            )

        result = {
            "entity_id": int(
                target["id"]
            ),
            "inn": str(
                target["inn"]
            ),
            "short_name": str(
                target["short_name"]
            ),
            "entity_type": str(
                target["entity_type"]
            ),
            "status": str(
                target["status"]
            ),
            "true_api_enabled": bool(
                target[
                    "true_api_enabled"
                ]
            ),
            "auto_discover_certificate": bool(
                target[
                    "auto_discover_certificate"
                ]
            ),
            "auto_discover_product_groups": bool(
                target[
                    "auto_discover_product_groups"
                ]
            ),
        }

        typer.echo(
            json.dumps(
                result,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
        )

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


@app.command("sync")
def sync_command(
    entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help="ID существующей карточки организации.",
    ),
) -> None:
    database = Database(
        get_settings()
    )

    try:
        payload = read_input_payload()

        token = str(
            payload.get(
                "token",
                "",
            )
        ).strip()

        certificate = parse_certificate(
            payload.get(
                "certificate"
            )
        )

        summary = asyncio.run(
            run_metadata_sync(
                database,
                entity_id=entity_id,
                token=token,
                certificate=certificate,
            )
        )

        typer.echo(
            json.dumps(
                summary.as_dict(),
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
        )

    except Exception as exc:
        record_failed_sync(
            database,
            entity_id=entity_id,
            exc=exc,
        )

        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc


if __name__ == "__main__":
    app()