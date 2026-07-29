from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import typer
from defusedxml.ElementTree import (
    fromstring,
)

from app.config import get_settings
from app.db import Database
from app.parse_edo_document import (
    load_raw_document,
)


DATAMATRIX_SOURCE_CODE_TYPE = (
    "NOM_UPAK"
)

UNIT_QUANTITY = Decimal(
    "1.000000"
)

MAX_ADDRESS_LENGTH = 2000


RECEIVER_CONTAINER_PRIORITY = (
    "ГрузПолуч",
    "СвГрузПолуч",
    "СвПолуч",
    "Получатель",
    "СвПокуп",
)


ADDRESS_ELEMENT_NAMES = {
    "АдрРФ",
    "АдрИнф",
    "Адрес",
}


FULL_ADDRESS_ATTRIBUTE_NAMES = (
    "АдрТекст",
    "Адрес",
)


ADDRESS_COMPONENTS = (
    (
        "Индекс",
        "",
    ),
    (
        "НаимРегион",
        "",
    ),
    (
        "КодРегион",
        "регион ",
    ),
    (
        "Район",
        "",
    ),
    (
        "Город",
        "",
    ),
    (
        "НаселПункт",
        "",
    ),
    (
        "Улица",
        "",
    ),
    (
        "Дом",
        "д. ",
    ),
    (
        "Корпус",
        "корп. ",
    ),
    (
        "Строен",
        "стр. ",
    ),
    (
        "Кварт",
        "кв. ",
    ),
    (
        "Помещ",
        "пом. ",
    ),
    (
        "Комната",
        "комн. ",
    ),
)


@dataclass(
    frozen=True,
    slots=True,
)
class DatamatrixSource:
    source_document_code_id: int
    document_line_id: int

    code_text: str
    code_value: bytes
    code_sha256: str

    external_document_id: str

    product_name: str | None
    product_code: str | None

    source_line_quantity: Decimal | None
    source_document_date: date | None


@dataclass(
    frozen=True,
    slots=True,
)
class DatamatrixSyncSummary:
    raw_document_id: int
    core_document_id: int
    legal_entity_id: int | None

    source_count: int
    inserted_count: int
    updated_count: int
    unchanged_count: int

    receiver_warehouse_address: str | None


@dataclass(
    frozen=True,
    slots=True,
)
class DatamatrixBackfillSummary:
    document_count: int
    success_count: int
    error_count: int
    unit_count: int


def local_name(
    value: str,
) -> str:
    """
    Удаляет namespace или XML-префикс.
    """

    if "}" in value:
        return value.rsplit(
            "}",
            1,
        )[1]

    if ":" in value:
        return value.rsplit(
            ":",
            1,
        )[1]

    return value


def attr(
    element: Any | None,
    name: str,
) -> str | None:
    """
    Возвращает XML-атрибут
    по локальному имени.
    """

    if element is None:
        return None

    for (
        raw_name,
        raw_value,
    ) in element.attrib.items():
        if (
            local_name(
                raw_name
            )
            != name
        ):
            continue

        prepared = " ".join(
            str(
                raw_value
            ).split()
        )

        return prepared or None

    return None


def element_text(
    element: Any | None,
) -> str | None:
    """
    Возвращает очищенный текст элемента.
    """

    if (
        element is None
        or element.text is None
    ):
        return None

    prepared = " ".join(
        element.text.split()
    )

    return prepared or None


def unique_parts(
    values: list[str],
) -> list[str]:
    """
    Удаляет пустые и повторяющиеся
    части адреса с сохранением порядка.
    """

    result: list[str] = []
    used: set[str] = set()

    for value in values:
        prepared = " ".join(
            str(
                value
            ).split()
        ).strip(
            " ,;"
        )

        if not prepared:
            continue

        key = prepared.casefold()

        if key in used:
            continue

        used.add(
            key
        )

        result.append(
            prepared
        )

    return result


def format_address_element(
    element: Any,
) -> str | None:
    """
    Формирует человекочитаемый адрес
    из АдрРФ, АдрИнф или Адрес.
    """

    for attribute_name in (
        FULL_ADDRESS_ATTRIBUTE_NAMES
    ):
        value = attr(
            element,
            attribute_name,
        )

        if value:
            return value[
                :MAX_ADDRESS_LENGTH
            ]

    for descendant in element.iter():
        if descendant is element:
            continue

        descendant_name = local_name(
            descendant.tag
        )

        if (
            descendant_name
            not in ADDRESS_ELEMENT_NAMES
        ):
            continue

        nested_address = (
            format_address_element(
                descendant
            )
        )

        if nested_address:
            return nested_address

    parts: list[str] = []

    country_name = attr(
        element,
        "НаимСтран",
    )

    if country_name:
        parts.append(
            country_name
        )

    used_attributes: set[str] = set()

    for (
        attribute_name,
        prefix,
    ) in ADDRESS_COMPONENTS:
        value = attr(
            element,
            attribute_name,
        )

        if not value:
            continue

        used_attributes.add(
            attribute_name
        )

        parts.append(
            f"{prefix}{value}"
        )

    text_value = element_text(
        element
    )

    if text_value:
        parts.append(
            text_value
        )

    if not parts:
        for (
            raw_name,
            raw_value,
        ) in element.attrib.items():
            name = local_name(
                raw_name
            )

            if (
                name in used_attributes
                or name
                in FULL_ADDRESS_ATTRIBUTE_NAMES
            ):
                continue

            value = " ".join(
                str(
                    raw_value
                ).split()
            )

            if value:
                parts.append(
                    value
                )

    prepared_parts = unique_parts(
        parts
    )

    if not prepared_parts:
        return None

    return ", ".join(
        prepared_parts
    )[:MAX_ADDRESS_LENGTH]


def find_address_in_container(
    container: Any,
) -> str | None:
    """
    Ищет первый адрес внутри
    выбранного участника документа.
    """

    for element in container.iter():
        if (
            local_name(
                element.tag
            )
            not in ADDRESS_ELEMENT_NAMES
        ):
            continue

        address = format_address_element(
            element
        )

        if address:
            return address

    return None


def parse_receiver_warehouse_address(
    xml_content: bytes,
) -> str | None:
    """
    Извлекает адрес склада получателя.

    Приоритет:

    1. грузополучатель;
    2. специальный получатель;
    3. покупатель.
    """

    root = fromstring(
        xml_content
    )

    elements = list(
        root.iter()
    )

    for container_name in (
        RECEIVER_CONTAINER_PRIORITY
    ):
        for element in elements:
            if (
                local_name(
                    element.tag
                )
                != container_name
            ):
                continue

            address = (
                find_address_in_container(
                    element
                )
            )

            if address:
                return address

    return None


def bytes_value(
    value: Any,
) -> bytes:
    """
    Нормализует бинарное значение MySQL.
    """

    if isinstance(
        value,
        bytes,
    ):
        return value

    if isinstance(
        value,
        bytearray,
    ):
        return bytes(
            value
        )

    if isinstance(
        value,
        memoryview,
    ):
        return value.tobytes()

    raise TypeError(
        "Значение кода не является "
        "байтовой последовательностью."
    )


def normalize_document_date_value(
    value: Any,
) -> date | None:
    """
    Приводит DATE, DATETIME и ISO-строки
    к единому типу datetime.date.
    """

    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return value.date()

    if isinstance(
        value,
        date,
    ):
        return value

    if isinstance(
        value,
        str,
    ):
        prepared = value.strip()

        if not prepared:
            return None

        try:
            return datetime.fromisoformat(
                prepared.replace(
                    "Z",
                    "+00:00",
                )
            ).date()

        except ValueError:
            pass

        try:
            return date.fromisoformat(
                prepared[:10]
            )

        except ValueError as exc:
            raise ValueError(
                "Некорректная дата документа: "
                f"{prepared}"
            ) from exc

    raise TypeError(
        "Дата документа имеет "
        "неподдерживаемый тип: "
        f"{type(value).__name__}."
    )


def entity_ids_from_rows(
    rows: list[
        tuple[Any, ...]
    ],
) -> list[int]:
    """
    Приводит результат SQL-запроса
    к уникальному списку ID организаций.
    """

    return sorted(
        {
            int(
                row[0]
            )
            for row in rows
            if row[0] is not None
        }
    )


def resolve_single_entity(
    *,
    entity_ids: list[int],
    core_document_id: int,
    source_name: str,
) -> int | None:
    """
    Возвращает единственную организацию
    либо сообщает о неоднозначности.
    """

    if not entity_ids:
        return None

    if len(
        entity_ids
    ) == 1:
        return entity_ids[0]

    raise RuntimeError(
        "DATAMATRIX_ENTITY_AMBIGUOUS: "
        "документ CORE "
        f"id={core_document_id} "
        f"связан через {source_name} "
        "с несколькими организациями: "
        + ", ".join(
            str(
                value
            )
            for value in entity_ids
        )
    )


def resolve_legal_entity_id(
    database: Database,
    core_document_id: int,
) -> int:
    """
    Определяет организацию документа.

    Приоритет источников:

    1. legal_entity_document;
    2. core_document_observation;
    3. ИНН получателя из core_document.

    Последние два источника используются
    для исторических документов, загруженных
    до появления обязательной связи
    legal_entity_document.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT DISTINCT
                    legal_entity_id
                FROM legal_entity_document
                WHERE core_document_id = %s
                ORDER BY legal_entity_id
                """,
                (
                    core_document_id,
                ),
            )

            direct_entity_ids = (
                entity_ids_from_rows(
                    cursor.fetchall()
                )
            )

            direct_entity_id = (
                resolve_single_entity(
                    entity_ids=(
                        direct_entity_ids
                    ),
                    core_document_id=(
                        core_document_id
                    ),
                    source_name=(
                        "legal_entity_document"
                    ),
                )
            )

            if direct_entity_id is not None:
                return direct_entity_id

            cursor.execute(
                """
                SELECT DISTINCT
                    legal_entity_id
                FROM core_document_observation
                WHERE core_document_id = %s
                  AND legal_entity_id IS NOT NULL
                ORDER BY legal_entity_id
                """,
                (
                    core_document_id,
                ),
            )

            observation_entity_ids = (
                entity_ids_from_rows(
                    cursor.fetchall()
                )
            )

            observation_entity_id = (
                resolve_single_entity(
                    entity_ids=(
                        observation_entity_ids
                    ),
                    core_document_id=(
                        core_document_id
                    ),
                    source_name=(
                        "core_document_observation"
                    ),
                )
            )

            if (
                observation_entity_id
                is not None
            ):
                return observation_entity_id

            cursor.execute(
                """
                SELECT DISTINCT
                    entity.id
                FROM core_document AS document

                JOIN legal_entity AS entity
                  ON entity.inn =
                     document.receiver_inn

                WHERE document.id = %s

                  AND document.receiver_inn
                      IS NOT NULL

                  AND document.receiver_inn
                      <> ''

                ORDER BY entity.id
                """,
                (
                    core_document_id,
                ),
            )

            receiver_entity_ids = (
                entity_ids_from_rows(
                    cursor.fetchall()
                )
            )

        finally:
            cursor.close()

    receiver_entity_id = (
        resolve_single_entity(
            entity_ids=(
                receiver_entity_ids
            ),
            core_document_id=(
                core_document_id
            ),
            source_name=(
                "ИНН получателя"
            ),
        )
    )

    if receiver_entity_id is not None:
        return receiver_entity_id

    raise RuntimeError(
        "DATAMATRIX_ENTITY_NOT_FOUND: "
        "для документа CORE "
        f"id={core_document_id} "
        "не удалось определить организацию "
        "ни по связи документа, "
        "ни по наблюдениям, "
        "ни по ИНН получателя."
    )


def load_datamatrix_sources(
    database: Database,
    *,
    raw_document_id: int,
    core_document_id: int,
) -> list[DatamatrixSource]:
    """
    Загружает единичные коды НомУпак.

    ИдентТрансУпак в единичное
    хранилище не включается.
    """

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    code.id
                        AS source_document_code_id,

                    line.id
                        AS document_line_id,

                    code.code_text,
                    code.code_value,
                    code.code_sha256,

                    code.external_document_id,

                    line.product_name,
                    line.product_code,

                    line.quantity
                        AS source_line_quantity,

                    DATE(
                        COALESCE(
                            document.doc_date,
                            document.invoice_date,
                            document.received_at
                        )
                    ) AS source_document_date

                FROM core_document_code AS code

                JOIN core_document_line AS line
                  ON line.id =
                     code.document_line_id

                JOIN core_document AS document
                  ON document.id =
                     code.core_document_id

                WHERE code.raw_edo_document_id = %s

                  AND code.core_document_id = %s

                  AND code.source_code_type = %s

                ORDER BY
                    line.line_number,
                    code.sequence_number,
                    code.id
                """,
                (
                    raw_document_id,
                    core_document_id,
                    DATAMATRIX_SOURCE_CODE_TYPE,
                ),
            )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    result: list[
        DatamatrixSource
    ] = []

    for row in rows:
        result.append(
            DatamatrixSource(
                source_document_code_id=int(
                    row[
                        "source_document_code_id"
                    ]
                ),

                document_line_id=int(
                    row[
                        "document_line_id"
                    ]
                ),

                code_text=str(
                    row[
                        "code_text"
                    ]
                ),

                code_value=bytes_value(
                    row[
                        "code_value"
                    ]
                ),

                code_sha256=str(
                    row[
                        "code_sha256"
                    ]
                ),

                external_document_id=str(
                    row[
                        "external_document_id"
                    ]
                ),

                product_name=(
                    str(
                        row[
                            "product_name"
                        ]
                    )
                    if row[
                        "product_name"
                    ] is not None
                    else None
                ),

                product_code=(
                    str(
                        row[
                            "product_code"
                        ]
                    )
                    if row[
                        "product_code"
                    ] is not None
                    else None
                ),

                source_line_quantity=(
                    Decimal(
                        row[
                            "source_line_quantity"
                        ]
                    )
                    if row[
                        "source_line_quantity"
                    ] is not None
                    else None
                ),

                source_document_date=(
                    normalize_document_date_value(
                        row[
                            "source_document_date"
                        ]
                    )
                ),
            )
        )

    return result


def incoming_source_is_newer(
    *,
    current_document_date: (
        date
        | datetime
        | str
        | None
    ),
    current_raw_document_id: int,
    incoming_document_date: (
        date
        | datetime
        | str
        | None
    ),
    incoming_raw_document_id: int,
) -> bool:
    """
    Не позволяет более старому документу
    перезаписать актуальное состояние КИ.

    DATE и DATETIME предварительно приводятся
    к одному типу datetime.date.
    """

    normalized_current_date = (
        normalize_document_date_value(
            current_document_date
        )
    )

    normalized_incoming_date = (
        normalize_document_date_value(
            incoming_document_date
        )
    )

    if (
        normalized_incoming_date
        is not None
        and normalized_current_date
        is None
    ):
        return True

    if (
        normalized_incoming_date
        is None
        and normalized_current_date
        is not None
    ):
        return False

    if (
        normalized_incoming_date
        is not None
        and normalized_current_date
        is not None
    ):
        if (
            normalized_incoming_date
            > normalized_current_date
        ):
            return True

        if (
            normalized_incoming_date
            < normalized_current_date
        ):
            return False

    return (
        incoming_raw_document_id
        >= current_raw_document_id
    )


def insert_datamatrix_unit(
    cursor: Any,
    *,
    source: DatamatrixSource,
    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,
    receiver_warehouse_address: str | None,
) -> None:
    """
    Создаёт новую единицу DataMatrix.
    """

    cursor.execute(
        """
        INSERT INTO datamatrix_unit (
            code_sha256,
            code_text,
            code_value,

            legal_entity_id,
            core_document_id,
            raw_edo_document_id,
            document_line_id,
            source_document_code_id,

            external_document_id,

            product_name,
            product_code,

            quantity,
            source_line_quantity,

            receiver_warehouse_address,
            source_document_date,

            first_seen_at,
            last_seen_at,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s,
            %s, %s,
            %s, %s,
            %s, %s,
            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6)
        )
        """,
        (
            source.code_sha256,
            source.code_text,
            source.code_value,

            legal_entity_id,
            core_document_id,
            raw_document_id,
            source.document_line_id,
            source.source_document_code_id,

            source.external_document_id,

            source.product_name,
            source.product_code,

            UNIT_QUANTITY,
            source.source_line_quantity,

            receiver_warehouse_address,
            source.source_document_date,
        ),
    )


def update_datamatrix_unit(
    cursor: Any,
    *,
    unit_id: int,
    source: DatamatrixSource,
    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,
    receiver_warehouse_address: str | None,
) -> None:
    """
    Обновляет текущее состояние КИ
    по более новому документу.
    """

    cursor.execute(
        """
        UPDATE datamatrix_unit
           SET code_text = %s,
               code_value = %s,

               legal_entity_id = %s,
               core_document_id = %s,
               raw_edo_document_id = %s,
               document_line_id = %s,
               source_document_code_id = %s,

               external_document_id = %s,

               product_name = %s,
               product_code = %s,

               quantity = %s,
               source_line_quantity = %s,

               receiver_warehouse_address = %s,
               source_document_date = %s,

               last_seen_at = UTC_TIMESTAMP(6),
               updated_at = UTC_TIMESTAMP(6)

         WHERE id = %s
        """,
        (
            source.code_text,
            source.code_value,

            legal_entity_id,
            core_document_id,
            raw_document_id,
            source.document_line_id,
            source.source_document_code_id,

            source.external_document_id,

            source.product_name,
            source.product_code,

            UNIT_QUANTITY,
            source.source_line_quantity,

            receiver_warehouse_address,
            source.source_document_date,

            unit_id,
        ),
    )


def touch_datamatrix_unit(
    cursor: Any,
    unit_id: int,
) -> None:
    """
    Обновляет время повторного
    обнаружения существующей записи.
    """

    cursor.execute(
        """
        UPDATE datamatrix_unit
           SET last_seen_at = UTC_TIMESTAMP(6)
         WHERE id = %s
        """,
        (
            unit_id,
        ),
    )


def sync_datamatrix_units(
    *,
    database: Database,
    raw_document_id: int,
    core_document_id: int,
    xml_content: bytes,
) -> DatamatrixSyncSummary:
    """
    Материализует единицы DataMatrix
    из уже разобранного и сопоставленного УПД.
    """

    sources = load_datamatrix_sources(
        database,
        raw_document_id=(
            raw_document_id
        ),
        core_document_id=(
            core_document_id
        ),
    )

    if not sources:
        return DatamatrixSyncSummary(
            raw_document_id=(
                raw_document_id
            ),
            core_document_id=(
                core_document_id
            ),
            legal_entity_id=None,
            source_count=0,
            inserted_count=0,
            updated_count=0,
            unchanged_count=0,
            receiver_warehouse_address=None,
        )

    legal_entity_id = (
        resolve_legal_entity_id(
            database,
            core_document_id,
        )
    )

    receiver_warehouse_address = (
        parse_receiver_warehouse_address(
            xml_content
        )
    )

    inserted_count = 0
    updated_count = 0
    unchanged_count = 0

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            for source in sources:
                cursor.execute(
                    """
                    SELECT
                        id,
                        code_text,
                        code_value,
                        raw_edo_document_id,
                        source_document_date

                    FROM datamatrix_unit

                    WHERE code_sha256 = %s

                    LIMIT 1
                    FOR UPDATE
                    """,
                    (
                        source.code_sha256,
                    ),
                )

                current = cursor.fetchone()

                if current is None:
                    insert_datamatrix_unit(
                        cursor,
                        source=source,
                        legal_entity_id=(
                            legal_entity_id
                        ),
                        core_document_id=(
                            core_document_id
                        ),
                        raw_document_id=(
                            raw_document_id
                        ),
                        receiver_warehouse_address=(
                            receiver_warehouse_address
                        ),
                    )

                    inserted_count += 1
                    continue

                current_code_value = (
                    bytes_value(
                        current[
                            "code_value"
                        ]
                    )
                )

                current_code_text = str(
                    current[
                        "code_text"
                    ]
                )

                if (
                    current_code_text
                    != source.code_text
                    or current_code_value
                    != source.code_value
                ):
                    raise RuntimeError(
                        "DATAMATRIX_HASH_CONFLICT: "
                        "один SHA-256 соответствует "
                        "разным значениям кода."
                    )

                replace_current = (
                    incoming_source_is_newer(
                        current_document_date=(
                            current[
                                "source_document_date"
                            ]
                        ),
                        current_raw_document_id=int(
                            current[
                                "raw_edo_document_id"
                            ]
                        ),
                        incoming_document_date=(
                            source
                            .source_document_date
                        ),
                        incoming_raw_document_id=(
                            raw_document_id
                        ),
                    )
                )

                if replace_current:
                    update_datamatrix_unit(
                        cursor,
                        unit_id=int(
                            current[
                                "id"
                            ]
                        ),
                        source=source,
                        legal_entity_id=(
                            legal_entity_id
                        ),
                        core_document_id=(
                            core_document_id
                        ),
                        raw_document_id=(
                            raw_document_id
                        ),
                        receiver_warehouse_address=(
                            receiver_warehouse_address
                        ),
                    )

                    updated_count += 1

                else:
                    touch_datamatrix_unit(
                        cursor,
                        int(
                            current[
                                "id"
                            ]
                        ),
                    )

                    unchanged_count += 1

        finally:
            cursor.close()

    return DatamatrixSyncSummary(
        raw_document_id=(
            raw_document_id
        ),
        core_document_id=(
            core_document_id
        ),
        legal_entity_id=(
            legal_entity_id
        ),
        source_count=len(
            sources
        ),
        inserted_count=(
            inserted_count
        ),
        updated_count=(
            updated_count
        ),
        unchanged_count=(
            unchanged_count
        ),
        receiver_warehouse_address=(
            receiver_warehouse_address
        ),
    )


def load_matched_documents(
    database: Database,
    raw_document_id: int | None,
) -> list[
    tuple[
        int,
        int,
    ]
]:
    """
    Возвращает сопоставленные RAW-документы
    для первоначального заполнения хранилища.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            if raw_document_id is None:
                cursor.execute(
                    """
                    SELECT
                        id,
                        core_document_id
                    FROM raw_edo_document
                    WHERE xml_well_formed = 1
                      AND parse_status = 'PARSED'
                      AND match_status = 'MATCHED'
                      AND core_document_id IS NOT NULL
                    ORDER BY id
                    """
                )

            else:
                cursor.execute(
                    """
                    SELECT
                        id,
                        core_document_id
                    FROM raw_edo_document
                    WHERE id = %s
                      AND xml_well_formed = 1
                      AND parse_status = 'PARSED'
                      AND match_status = 'MATCHED'
                      AND core_document_id IS NOT NULL
                    LIMIT 1
                    """,
                    (
                        raw_document_id,
                    ),
                )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    return [
        (
            int(
                row[0]
            ),
            int(
                row[1]
            ),
        )
        for row in rows
    ]


def backfill_datamatrix_storage(
    *,
    database: Database,
    raw_document_id: int | None,
    fail_fast: bool,
) -> DatamatrixBackfillSummary:
    """
    Заполняет хранилище по ранее
    обработанным XML УПД.
    """

    documents = load_matched_documents(
        database,
        raw_document_id,
    )

    success_count = 0
    error_count = 0
    unit_count = 0

    for (
        index,
        (
            current_raw_document_id,
            current_core_document_id,
        ),
    ) in enumerate(
        documents,
        start=1,
    ):
        try:
            (
                xml_content,
                well_formed,
            ) = load_raw_document(
                database=database,
                raw_document_id=(
                    current_raw_document_id
                ),
            )

            if not well_formed:
                raise ValueError(
                    "RAW-документ не является "
                    "корректным XML."
                )

            summary = (
                sync_datamatrix_units(
                    database=database,
                    raw_document_id=(
                        current_raw_document_id
                    ),
                    core_document_id=(
                        current_core_document_id
                    ),
                    xml_content=(
                        xml_content
                    ),
                )
            )

            success_count += 1

            unit_count += (
                summary.source_count
            )

            entity_value = (
                str(
                    summary.legal_entity_id
                )
                if summary.legal_entity_id
                is not None
                else "-"
            )

            typer.echo(
                f"{index}/{len(documents)} "
                f"RAW id="
                f"{current_raw_document_id}; "
                f"CORE id="
                f"{current_core_document_id}; "
                f"организация="
                f"{entity_value}; "
                f"КИ="
                f"{summary.source_count}; "
                f"новых="
                f"{summary.inserted_count}; "
                f"обновлено="
                f"{summary.updated_count}; "
                f"без изменений="
                f"{summary.unchanged_count}"
            )

        except Exception as exc:
            error_count += 1

            typer.echo(
                f"{index}/{len(documents)} "
                f"RAW id="
                f"{current_raw_document_id}: "
                f"ERROR "
                f"{type(exc).__name__}: "
                f"{exc}",
                err=True,
            )

            if fail_fast:
                raise

    return DatamatrixBackfillSummary(
        document_count=len(
            documents
        ),
        success_count=(
            success_count
        ),
        error_count=(
            error_count
        ),
        unit_count=(
            unit_count
        ),
    )


def main(
    raw_document_id: int | None = (
        typer.Option(
            None,
            "--raw-document-id",
            min=1,
            help=(
                "Обработать один RAW-документ. "
                "Без параметра обрабатываются "
                "все сопоставленные XML."
            ),
        )
    ),

    fail_fast: bool = typer.Option(
        False,
        "--fail-fast",
        help=(
            "Остановиться после первой ошибки."
        ),
    ),
) -> None:
    """
    Первичное заполнение хранилища DataMatrix
    по ранее разобранным УПД.
    """

    database = Database(
        get_settings()
    )

    summary = (
        backfill_datamatrix_storage(
            database=database,
            raw_document_id=(
                raw_document_id
            ),
            fail_fast=(
                fail_fast
            ),
        )
    )

    typer.echo("")

    typer.echo(
        "Заполнение хранилища "
        "DataMatrix завершено."
    )

    typer.echo(
        "Документов: "
        f"{summary.document_count}"
    )

    typer.echo(
        "Успешно: "
        f"{summary.success_count}"
    )

    typer.echo(
        "Ошибок: "
        f"{summary.error_count}"
    )

    typer.echo(
        "Обработано КИ: "
        f"{summary.unit_count}"
    )

    if summary.error_count > 0:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(
        main
    )