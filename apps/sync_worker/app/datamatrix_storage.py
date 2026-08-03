from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from defusedxml.ElementTree import fromstring

from app.datamatrix_expansion import (
    DatamatrixResolution,
    ExpandedCode,
    ProductCard,
    code_sha256,
    extract_gtin,
    resolve_datamatrix_codes,
)
from app.db import Database


SOURCE_TYPE_NOM_UPAK = "NOM_UPAK"
SOURCE_TYPE_IDENT_TRANS_UPAK = "IDENT_TRANS_UPAK"

MAX_ADDRESS_LENGTH = 2000
MAX_ERROR_LENGTH = 2000

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
    ("Индекс", ""),
    ("НаимРегион", ""),
    ("КодРегион", "регион "),
    ("Район", ""),
    ("Город", ""),
    ("НаселПункт", ""),
    ("Улица", ""),
    ("Дом", "д. "),
    ("Корпус", "корп. "),
    ("Строен", "стр. "),
    ("Кварт", "кв. "),
    ("Помещ", "пом. "),
    ("Комната", "комн. "),
)


@dataclass(
    frozen=True,
    slots=True,
)
class DatamatrixSource:
    source_document_code_id: int
    document_line_id: int
    sequence_number: int
    source_code_type: str
    transport_package_identifier: str | None

    code_text: str
    code_value: bytes
    code_sha256: str

    external_document_id: str
    product_name: str | None
    product_code: str | None

    source_line_quantity: Decimal | None
    source_line_code_count: int
    source_document_date: date | None


@dataclass(
    frozen=True,
    slots=True,
)
class CachedProduct:
    gtin: str
    product_name: str | None
    brand: str | None
    package_type: str | None
    product_group: str | None
    raw_payload_json: str | None


@dataclass(
    frozen=True,
    slots=True,
)
class SourcePersistResult:
    source_state: str

    unit_inserted_count: int
    unit_updated_count: int
    unit_unchanged_count: int
    unit_removed_count: int

    terminal_count: int
    aggregate: bool
    quantity_match_status: str


@dataclass(
    frozen=True,
    slots=True,
)
class DatamatrixSyncSummary:
    raw_document_id: int
    core_document_id: int
    legal_entity_id: int | None
    product_group: str

    source_count: int
    aggregate_count: int
    terminal_count: int

    inserted_count: int
    updated_count: int
    unchanged_count: int
    removed_count: int

    source_inserted_count: int
    source_updated_count: int
    source_unchanged_count: int

    mismatch_count: int
    product_count: int

    aggregate_request_count: int
    product_request_count: int

    product_lookup_error: str | None

    receiver_warehouse_address: str | None


class DatamatrixStorageError(
    RuntimeError
):
    pass


def local_name(
    value: str,
) -> str:
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
    values: Iterable[str],
) -> list[str]:
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

        if (
            local_name(
                descendant.tag
            )
            not in ADDRESS_ELEMENT_NAMES
        ):
            continue

        nested = (
            format_address_element(
                descendant
            )
        )

        if nested:
            return nested

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
    for element in container.iter():
        if (
            local_name(
                element.tag
            )
            not in ADDRESS_ELEMENT_NAMES
        ):
            continue

        address = (
            format_address_element(
                element
            )
        )

        if address:
            return address

    return None


def parse_receiver_warehouse_address(
    xml_content: bytes,
) -> str | None:
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
                "Некорректная дата "
                f"документа: {prepared}"
            ) from exc

    raise TypeError(
        "Дата документа имеет "
        "неподдерживаемый тип: "
        f"{type(value).__name__}."
    )


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
    current_date = (
        normalize_document_date_value(
            current_document_date
        )
    )

    incoming_date = (
        normalize_document_date_value(
            incoming_document_date
        )
    )

    if (
        incoming_date is not None
        and current_date is None
    ):
        return True

    if (
        incoming_date is None
        and current_date is not None
    ):
        return False

    if (
        incoming_date is not None
        and current_date is not None
    ):
        if incoming_date > current_date:
            return True

        if incoming_date < current_date:
            return False

    return (
        incoming_raw_document_id
        >= current_raw_document_id
    )


def entity_ids_from_rows(
    rows: list[
        tuple[Any, ...]
    ],
) -> list[int]:
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
    if not entity_ids:
        return None

    if len(
        entity_ids
    ) == 1:
        return entity_ids[0]

    raise DatamatrixStorageError(
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

            direct_id = (
                resolve_single_entity(
                    entity_ids=(
                        entity_ids_from_rows(
                            cursor.fetchall()
                        )
                    ),
                    core_document_id=(
                        core_document_id
                    ),
                    source_name=(
                        "legal_entity_document"
                    ),
                )
            )

            if direct_id is not None:
                return direct_id

            cursor.execute(
                """
                SELECT DISTINCT
                    legal_entity_id
                FROM core_document_observation
                WHERE core_document_id = %s
                  AND legal_entity_id
                      IS NOT NULL
                ORDER BY legal_entity_id
                """,
                (
                    core_document_id,
                ),
            )

            observation_id = (
                resolve_single_entity(
                    entity_ids=(
                        entity_ids_from_rows(
                            cursor.fetchall()
                        )
                    ),
                    core_document_id=(
                        core_document_id
                    ),
                    source_name=(
                        "core_document_observation"
                    ),
                )
            )

            if observation_id is not None:
                return observation_id

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

            receiver_ids = (
                entity_ids_from_rows(
                    cursor.fetchall()
                )
            )

        finally:
            cursor.close()

    receiver_id = resolve_single_entity(
        entity_ids=receiver_ids,
        core_document_id=(
            core_document_id
        ),
        source_name=(
            "ИНН получателя"
        ),
    )

    if receiver_id is not None:
        return receiver_id

    raise DatamatrixStorageError(
        "DATAMATRIX_ENTITY_NOT_FOUND: "
        "для документа CORE "
        f"id={core_document_id} "
        "не удалось определить "
        "организацию."
    )


def _normalize_optional_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    prepared = " ".join(
        str(
            value
        ).split()
    )

    return prepared or None


def _decimal_value(
    value: Any,
) -> Decimal | None:
    if value is None:
        return None

    if isinstance(
        value,
        Decimal,
    ):
        return value

    try:
        return Decimal(
            str(
                value
            )
        )

    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Некорректное количество "
            "товарной строки: "
            f"{value!r}."
        ) from exc


def _row_to_source(
    row: dict[
        str,
        Any,
    ],
    *,
    source_line_code_count: int,
) -> DatamatrixSource:
    code_text = str(
        row["code_text"]
    )

    code_value = bytes_value(
        row["code_value"]
    )

    stored_hash = str(
        row["code_sha256"]
    )

    calculated_hash = (
        hashlib.sha256(
            code_value
        ).hexdigest()
    )

    if stored_hash != calculated_hash:
        raise DatamatrixStorageError(
            "DATAMATRIX_SOURCE_HASH_MISMATCH: "
            "SHA-256 в CORE не соответствует "
            "бинарному значению КИ."
        )

    if (
        code_value
        != code_text.encode(
            "utf-8"
        )
    ):
        raise DatamatrixStorageError(
            "DATAMATRIX_SOURCE_TEXT_MISMATCH: "
            "текстовое и бинарное значение "
            "КИ в CORE различаются."
        )

    return DatamatrixSource(
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

        sequence_number=int(
            row[
                "sequence_number"
            ]
        ),

        source_code_type=str(
            row[
                "source_code_type"
            ]
        ),

        transport_package_identifier=(
            _normalize_optional_text(
                row.get(
                    "transport_package_identifier"
                )
            )
        ),

        code_text=code_text,
        code_value=code_value,
        code_sha256=stored_hash,

        external_document_id=str(
            row[
                "external_document_id"
            ]
        ),

        product_name=(
            _normalize_optional_text(
                row.get(
                    "product_name"
                )
            )
        ),

        product_code=(
            _normalize_optional_text(
                row.get(
                    "product_code"
                )
            )
        ),

        source_line_quantity=(
            _decimal_value(
                row.get(
                    "source_line_quantity"
                )
            )
        ),

        source_line_code_count=(
            source_line_code_count
        ),

        source_document_date=(
            normalize_document_date_value(
                row.get(
                    "source_document_date"
                )
            )
        ),
    )


def load_datamatrix_sources(
    database: Database,
    *,
    raw_document_id: int,
    core_document_id: int,
) -> list[DatamatrixSource]:
    """
    Загружает корневые КИ
    товарных строк.

    Если присутствует ИдентТрансУпак,
    он считается корнем дерева.

    НомУпак с тем же значением
    transport_package_identifier
    повторно корнем не считается.
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

                    code.sequence_number,
                    code.source_code_type,
                    code.transport_package_identifier,

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

                  AND code.source_code_type
                      IN (%s, %s)

                ORDER BY
                    line.line_number,
                    code.sequence_number,
                    code.id
                """,
                (
                    raw_document_id,
                    core_document_id,
                    SOURCE_TYPE_NOM_UPAK,
                    SOURCE_TYPE_IDENT_TRANS_UPAK,
                ),
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

    rows_by_line: dict[
        int,
        list[
            dict[
                str,
                Any,
            ]
        ],
    ] = defaultdict(
        list
    )

    for row in rows:
        rows_by_line[
            int(
                row[
                    "document_line_id"
                ]
            )
        ].append(
            row
        )

    result: list[
        DatamatrixSource
    ] = []

    for line_rows in (
        rows_by_line.values()
    ):
        transport_roots = {
            str(
                row[
                    "code_text"
                ]
            ).strip()

            for row in line_rows

            if (
                str(
                    row[
                        "source_code_type"
                    ]
                )
                == SOURCE_TYPE_IDENT_TRANS_UPAK
            )

            and str(
                row[
                    "code_text"
                ]
            ).strip()
        }

        selected_rows: list[
            dict[
                str,
                Any,
            ]
        ] = []

        selected_hashes: set[
            str
        ] = set()

        for row in line_rows:
            source_type = str(
                row[
                    "source_code_type"
                ]
            )

            code_hash = str(
                row[
                    "code_sha256"
                ]
            )

            if (
                source_type
                == SOURCE_TYPE_NOM_UPAK
            ):
                transport_identifier = (
                    _normalize_optional_text(
                        row.get(
                            "transport_package_identifier"
                        )
                    )
                )

                if (
                    transport_identifier
                    is not None

                    and transport_identifier
                    in transport_roots
                ):
                    continue

            if code_hash in selected_hashes:
                continue

            selected_hashes.add(
                code_hash
            )

            selected_rows.append(
                row
            )

        source_count = len(
            selected_rows
        )

        if source_count == 0:
            continue

        for row in selected_rows:
            result.append(
                _row_to_source(
                    row,
                    source_line_code_count=(
                        source_count
                    ),
                )
            )

    return result


def load_cached_products(
    database: Database,
    gtins: Iterable[str] | None = None,
) -> dict[
    str,
    CachedProduct,
]:
    prepared_gtins = sorted(
        {
            str(
                gtin
            ).strip()

            for gtin in (
                gtins or []
            )

            if str(
                gtin
            ).strip()
        }
    )

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            if prepared_gtins:
                placeholders = ",".join(
                    [
                        "%s"
                    ]
                    * len(
                        prepared_gtins
                    )
                )

                cursor.execute(
                    f"""
                    SELECT
                        gtin,
                        product_name,
                        brand,
                        package_type,
                        product_group,
                        raw_payload_json

                    FROM datamatrix_product

                    WHERE gtin
                          IN ({placeholders})
                    """,
                    tuple(
                        prepared_gtins
                    ),
                )

            else:
                cursor.execute(
                    """
                    SELECT
                        gtin,
                        product_name,
                        brand,
                        package_type,
                        product_group,
                        raw_payload_json

                    FROM datamatrix_product
                    """
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

    result: dict[
        str,
        CachedProduct,
    ] = {}

    for row in rows:
        gtin = str(
            row[
                "gtin"
            ]
        )

        raw_payload = row.get(
            "raw_payload_json"
        )

        if (
            raw_payload is not None
            and not isinstance(
                raw_payload,
                str,
            )
        ):
            raw_payload = json.dumps(
                raw_payload,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
                default=str,
            )

        result[
            gtin
        ] = CachedProduct(
            gtin=gtin,

            product_name=(
                _normalize_optional_text(
                    row.get(
                        "product_name"
                    )
                )
            ),

            brand=(
                _normalize_optional_text(
                    row.get(
                        "brand"
                    )
                )
            ),

            package_type=(
                _normalize_optional_text(
                    row.get(
                        "package_type"
                    )
                )
            ),

            product_group=(
                _normalize_optional_text(
                    row.get(
                        "product_group"
                    )
                )
            ),

            raw_payload_json=(
                raw_payload
            ),
        )

    return result


def upsert_product_cards(
    cursor: Any,
    products: dict[
        str,
        ProductCard,
    ],
) -> None:
    for product in products.values():
        cursor.execute(
            """
            INSERT INTO datamatrix_product (
                gtin,
                product_name,
                brand,
                package_type,
                product_group,
                raw_payload_json,
                fetched_at,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                CAST(%s AS JSON),
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6)
            )

            ON DUPLICATE KEY UPDATE
                product_name =
                    VALUES(product_name),

                brand =
                    VALUES(brand),

                package_type =
                    VALUES(package_type),

                product_group =
                    VALUES(product_group),

                raw_payload_json =
                    VALUES(raw_payload_json),

                fetched_at =
                    UTC_TIMESTAMP(6),

                updated_at =
                    UTC_TIMESTAMP(6)
            """,
            (
                product.gtin,
                product.name,
                product.brand,
                product.package_type,
                product.product_group,
                product.raw_payload_json,
            ),
        )


def _expected_units_per_source(
    source: DatamatrixSource,
) -> Decimal | None:
    if (
        source.source_line_quantity
        is None
    ):
        return None

    if (
        source.source_line_code_count
        <= 0
    ):
        return None

    return (
        source.source_line_quantity
        / Decimal(
            source.source_line_code_count
        )
    )


def _line_quantity_statuses(
    sources: list[
        DatamatrixSource
    ],
    expansions: dict[
        str,
        ExpandedCode,
    ],
) -> dict[
    int,
    str,
]:
    by_line: dict[
        int,
        list[
            DatamatrixSource
        ],
    ] = defaultdict(
        list
    )

    for source in sources:
        by_line[
            source.document_line_id
        ].append(
            source
        )

    result: dict[
        int,
        str,
    ] = {}

    for (
        line_id,
        line_sources,
    ) in by_line.items():
        expected = (
            line_sources[0]
            .source_line_quantity
        )

        if expected is None:
            result[
                line_id
            ] = "NOT_CHECKED"

            continue

        actual = sum(
            len(
                expansions[
                    source.code_text
                ].terminal_codes
            )
            for source in line_sources
        )

        result[
            line_id
        ] = (
            "MATCHED"
            if Decimal(
                actual
            ) == expected
            else "MISMATCH"
        )

    return result


def _product_name_for_unit(
    *,
    gtin: str | None,
    source: DatamatrixSource,

    fetched_products: dict[
        str,
        ProductCard,
    ],

    cached_products: dict[
        str,
        CachedProduct,
    ],
) -> tuple[
    str | None,
    str,
]:
    if gtin is not None:
        fetched = (
            fetched_products.get(
                gtin
            )
        )

        if (
            fetched is not None
            and fetched.name
        ):
            return (
                fetched.name,
                "GIS_MT_PRODUCT",
            )

        cached = (
            cached_products.get(
                gtin
            )
        )

        if (
            cached is not None
            and cached.product_name
        ):
            return (
                cached.product_name,
                "GIS_MT_PRODUCT",
            )

    if source.product_name:
        return (
            source.product_name,
            "EDO_DOCUMENT",
        )

    return (
        None,
        "UNKNOWN",
    )


def _verify_code_identity(
    *,
    current_code_text: Any,
    current_code_value: Any,

    incoming_code_text: str,
    incoming_code_value: bytes,

    error_prefix: str,
) -> None:
    if (
        str(
            current_code_text
        )
        != incoming_code_text

        or bytes_value(
            current_code_value
        )
        != incoming_code_value
    ):
        raise DatamatrixStorageError(
            f"{error_prefix}: "
            "один SHA-256 соответствует "
            "разным значениям КИ."
        )


def _insert_source_code(
    cursor: Any,
    *,
    source: DatamatrixSource,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    receiver_warehouse_address: (
        str
        | None
    ),

    expansion: ExpandedCode,
    quantity_match_status: str,
) -> int:
    expected_unit_count = (
        _expected_units_per_source(
            source
        )
    )

    actual_unit_count = len(
        expansion.terminal_codes
    )

    cursor.execute(
        """
        INSERT INTO datamatrix_source_code (
            code_sha256,
            code_text,
            code_value,

            legal_entity_id,
            core_document_id,
            raw_edo_document_id,
            document_line_id,
            source_document_code_id,

            external_document_id,
            product_group,

            document_product_name,
            product_code,
            source_gtin,

            source_line_quantity,
            source_line_code_count,

            expected_unit_count,
            actual_unit_count,

            code_kind,
            expansion_status,
            quantity_match_status,
            expansion_error,

            receiver_warehouse_address,
            source_document_date,

            first_seen_at,
            last_seen_at,
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

            %s,
            %s,

            %s,
            %s,

            %s,
            %s,
            %s,
            NULL,

            %s,
            %s,

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
            product_group,

            source.product_name,
            source.product_code,

            extract_gtin(
                source.code_text
            ),

            source.source_line_quantity,
            source.source_line_code_count,

            expected_unit_count,
            actual_unit_count,

            (
                "AGGREGATE"
                if expansion.is_aggregate
                else "UNIT"
            ),

            (
                "EXPANDED"
                if expansion.is_aggregate
                else "UNIT"
            ),

            quantity_match_status,

            receiver_warehouse_address,
            source.source_document_date,
        ),
    )

    return int(
        cursor.lastrowid
    )


def _update_source_code(
    cursor: Any,
    *,
    source_id: int,
    source: DatamatrixSource,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    receiver_warehouse_address: (
        str
        | None
    ),

    expansion: ExpandedCode,
    quantity_match_status: str,
) -> None:
    cursor.execute(
        """
        UPDATE datamatrix_source_code

           SET code_text = %s,
               code_value = %s,

               legal_entity_id = %s,
               core_document_id = %s,
               raw_edo_document_id = %s,
               document_line_id = %s,
               source_document_code_id = %s,

               external_document_id = %s,
               product_group = %s,

               document_product_name = %s,
               product_code = %s,
               source_gtin = %s,

               source_line_quantity = %s,
               source_line_code_count = %s,

               expected_unit_count = %s,
               actual_unit_count = %s,

               code_kind = %s,
               expansion_status = %s,
               quantity_match_status = %s,
               expansion_error = NULL,

               receiver_warehouse_address = %s,
               source_document_date = %s,

               last_seen_at =
                   UTC_TIMESTAMP(6),

               updated_at =
                   UTC_TIMESTAMP(6)

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
            product_group,

            source.product_name,
            source.product_code,

            extract_gtin(
                source.code_text
            ),

            source.source_line_quantity,
            source.source_line_code_count,

            _expected_units_per_source(
                source
            ),

            len(
                expansion.terminal_codes
            ),

            (
                "AGGREGATE"
                if expansion.is_aggregate
                else "UNIT"
            ),

            (
                "EXPANDED"
                if expansion.is_aggregate
                else "UNIT"
            ),

            quantity_match_status,

            receiver_warehouse_address,
            source.source_document_date,

            source_id,
        ),
    )


def _upsert_source_code(
    cursor: Any,
    *,
    source: DatamatrixSource,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    receiver_warehouse_address: (
        str
        | None
    ),

    expansion: ExpandedCode,
    quantity_match_status: str,
) -> tuple[
    int,
    str,
    bool,
]:
    cursor.execute(
        """
        SELECT
            id,
            code_text,
            code_value,
            raw_edo_document_id,
            source_document_date

        FROM datamatrix_source_code

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
        source_id = (
            _insert_source_code(
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

                product_group=(
                    product_group
                ),

                receiver_warehouse_address=(
                    receiver_warehouse_address
                ),

                expansion=expansion,

                quantity_match_status=(
                    quantity_match_status
                ),
            )
        )

        return (
            source_id,
            "INSERTED",
            True,
        )

    _verify_code_identity(
        current_code_text=(
            current[
                "code_text"
            ]
        ),

        current_code_value=(
            current[
                "code_value"
            ]
        ),

        incoming_code_text=(
            source.code_text
        ),

        incoming_code_value=(
            source.code_value
        ),

        error_prefix=(
            "DATAMATRIX_SOURCE_HASH_CONFLICT"
        ),
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

    source_id = int(
        current[
            "id"
        ]
    )

    if not replace_current:
        cursor.execute(
            """
            UPDATE datamatrix_source_code
               SET last_seen_at =
                   UTC_TIMESTAMP(6)
             WHERE id = %s
            """,
            (
                source_id,
            ),
        )

        return (
            source_id,
            "UNCHANGED",
            False,
        )

    _update_source_code(
        cursor,
        source_id=source_id,
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

        product_group=(
            product_group
        ),

        receiver_warehouse_address=(
            receiver_warehouse_address
        ),

        expansion=expansion,

        quantity_match_status=(
            quantity_match_status
        ),
    )

    return (
        source_id,
        "UPDATED",
        True,
    )


def _replace_aggregation_edges(
    cursor: Any,
    *,
    source_id: int,
    expansion: ExpandedCode,
) -> None:
    cursor.execute(
        """
        DELETE FROM datamatrix_aggregation_edge
        WHERE source_code_id = %s
        """,
        (
            source_id,
        ),
    )

    for edge in expansion.edges:
        cursor.execute(
            """
            INSERT INTO datamatrix_aggregation_edge (
                source_code_id,

                parent_code_sha256,
                parent_code_text,

                child_code_sha256,
                child_code_text,
                child_gtin,

                depth,
                is_terminal,

                created_at
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

                UTC_TIMESTAMP(6)
            )
            """,
            (
                source_id,

                code_sha256(
                    edge.parent_code
                ),

                edge.parent_code,

                code_sha256(
                    edge.child_code
                ),

                edge.child_code,

                extract_gtin(
                    edge.child_code
                ),

                edge.depth,

                (
                    1
                    if edge.is_terminal
                    else 0
                ),
            ),
        )


def _insert_unit(
    cursor: Any,
    *,
    source_id: int,
    source: DatamatrixSource,
    terminal_code: str,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    product_name: str | None,
    product_name_source: str,

    receiver_warehouse_address: (
        str
        | None
    ),
) -> int:
    terminal_value = (
        terminal_code.encode(
            "utf-8"
        )
    )

    terminal_hash = (
        code_sha256(
            terminal_code
        )
    )

    cursor.execute(
        """
        INSERT INTO datamatrix_unit (
            code_sha256,
            code_text,
            code_value,

            source_code_id,

            legal_entity_id,
            core_document_id,
            raw_edo_document_id,
            document_line_id,
            source_document_code_id,

            external_document_id,
            product_group,

            gtin,
            product_name,
            product_name_source,
            document_product_name,
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
            %s,
            %s,
            %s,

            1.000000,
            %s,

            %s,
            %s,

            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6),
            UTC_TIMESTAMP(6)
        )
        """,
        (
            terminal_hash,
            terminal_code,
            terminal_value,

            source_id,

            legal_entity_id,
            core_document_id,
            raw_document_id,
            source.document_line_id,
            source.source_document_code_id,

            source.external_document_id,
            product_group,

            extract_gtin(
                terminal_code
            ),

            product_name,
            product_name_source,
            source.product_name,
            source.product_code,

            source.source_line_quantity,

            receiver_warehouse_address,
            source.source_document_date,
        ),
    )

    return int(
        cursor.lastrowid
    )


def _update_unit(
    cursor: Any,
    *,
    unit_id: int,
    source_id: int,
    source: DatamatrixSource,
    terminal_code: str,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    product_name: str | None,
    product_name_source: str,

    receiver_warehouse_address: (
        str
        | None
    ),
) -> None:
    cursor.execute(
        """
        UPDATE datamatrix_unit

           SET code_text = %s,
               code_value = %s,

               source_code_id = %s,

               legal_entity_id = %s,
               core_document_id = %s,
               raw_edo_document_id = %s,
               document_line_id = %s,
               source_document_code_id = %s,

               external_document_id = %s,
               product_group = %s,

               gtin = %s,
               product_name = %s,
               product_name_source = %s,
               document_product_name = %s,
               product_code = %s,

               quantity = 1.000000,
               source_line_quantity = %s,

               receiver_warehouse_address = %s,
               source_document_date = %s,

               last_seen_at =
                   UTC_TIMESTAMP(6),

               updated_at =
                   UTC_TIMESTAMP(6)

         WHERE id = %s
        """,
        (
            terminal_code,
            terminal_code.encode(
                "utf-8"
            ),

            source_id,

            legal_entity_id,
            core_document_id,
            raw_document_id,
            source.document_line_id,
            source.source_document_code_id,

            source.external_document_id,
            product_group,

            extract_gtin(
                terminal_code
            ),

            product_name,
            product_name_source,
            source.product_name,
            source.product_code,

            source.source_line_quantity,

            receiver_warehouse_address,
            source.source_document_date,

            unit_id,
        ),
    )


def _upsert_unit(
    cursor: Any,
    *,
    source_id: int,
    source: DatamatrixSource,
    terminal_code: str,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    product_name: str | None,
    product_name_source: str,

    receiver_warehouse_address: (
        str
        | None
    ),
) -> str:
    terminal_hash = code_sha256(
        terminal_code
    )

    terminal_value = (
        terminal_code.encode(
            "utf-8"
        )
    )

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
            terminal_hash,
        ),
    )

    current = cursor.fetchone()

    if current is None:
        _insert_unit(
            cursor,

            source_id=source_id,
            source=source,

            terminal_code=(
                terminal_code
            ),

            legal_entity_id=(
                legal_entity_id
            ),

            core_document_id=(
                core_document_id
            ),

            raw_document_id=(
                raw_document_id
            ),

            product_group=(
                product_group
            ),

            product_name=(
                product_name
            ),

            product_name_source=(
                product_name_source
            ),

            receiver_warehouse_address=(
                receiver_warehouse_address
            ),
        )

        return "INSERTED"

    _verify_code_identity(
        current_code_text=(
            current[
                "code_text"
            ]
        ),

        current_code_value=(
            current[
                "code_value"
            ]
        ),

        incoming_code_text=(
            terminal_code
        ),

        incoming_code_value=(
            terminal_value
        ),

        error_prefix=(
            "DATAMATRIX_UNIT_HASH_CONFLICT"
        ),
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

    if not replace_current:
        cursor.execute(
            """
            UPDATE datamatrix_unit
               SET last_seen_at =
                   UTC_TIMESTAMP(6)
             WHERE id = %s
            """,
            (
                int(
                    current[
                        "id"
                    ]
                ),
            ),
        )

        return "UNCHANGED"

    _update_unit(
        cursor,

        unit_id=int(
            current[
                "id"
            ]
        ),

        source_id=source_id,
        source=source,

        terminal_code=(
            terminal_code
        ),

        legal_entity_id=(
            legal_entity_id
        ),

        core_document_id=(
            core_document_id
        ),

        raw_document_id=(
            raw_document_id
        ),

        product_group=(
            product_group
        ),

        product_name=(
            product_name
        ),

        product_name_source=(
            product_name_source
        ),

        receiver_warehouse_address=(
            receiver_warehouse_address
        ),
    )

    return "UPDATED"


def _remove_stale_units(
    cursor: Any,
    *,
    source_id: int,
    terminal_hashes: set[str],
) -> int:
    cursor.execute(
        """
        SELECT
            id,
            code_sha256

        FROM datamatrix_unit

        WHERE source_code_id = %s

        FOR UPDATE
        """,
        (
            source_id,
        ),
    )

    stale_ids = [
        int(
            row[
                "id"
            ]
        )

        for row in cursor.fetchall()

        if (
            str(
                row[
                    "code_sha256"
                ]
            )
            not in terminal_hashes
        )
    ]

    if not stale_ids:
        return 0

    placeholders = ",".join(
        [
            "%s"
        ]
        * len(
            stale_ids
        )
    )

    cursor.execute(
        f"""
        DELETE FROM datamatrix_unit
        WHERE id IN ({placeholders})
        """,
        tuple(
            stale_ids
        ),
    )

    return int(
        cursor.rowcount
        or 0
    )


def _persist_one_source(
    cursor: Any,
    *,
    source: DatamatrixSource,
    expansion: ExpandedCode,
    quantity_match_status: str,

    legal_entity_id: int,
    core_document_id: int,
    raw_document_id: int,

    product_group: str,

    receiver_warehouse_address: (
        str
        | None
    ),

    fetched_products: dict[
        str,
        ProductCard,
    ],

    cached_products: dict[
        str,
        CachedProduct,
    ],
) -> SourcePersistResult:
    (
        source_id,
        source_state,
        replace_materialization,
    ) = _upsert_source_code(
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

        product_group=(
            product_group
        ),

        receiver_warehouse_address=(
            receiver_warehouse_address
        ),

        expansion=expansion,

        quantity_match_status=(
            quantity_match_status
        ),
    )

    if not replace_materialization:
        return SourcePersistResult(
            source_state=(
                source_state
            ),

            unit_inserted_count=0,
            unit_updated_count=0,

            unit_unchanged_count=len(
                expansion.terminal_codes
            ),

            unit_removed_count=0,

            terminal_count=len(
                expansion.terminal_codes
            ),

            aggregate=(
                expansion.is_aggregate
            ),

            quantity_match_status=(
                quantity_match_status
            ),
        )

    _replace_aggregation_edges(
        cursor,
        source_id=source_id,
        expansion=expansion,
    )

    inserted = 0
    updated = 0
    unchanged = 0

    terminal_hashes = {
        code_sha256(
            code
        )
        for code
        in expansion.terminal_codes
    }

    removed = _remove_stale_units(
        cursor,
        source_id=source_id,
        terminal_hashes=(
            terminal_hashes
        ),
    )

    for terminal_code in (
        expansion.terminal_codes
    ):
        gtin = extract_gtin(
            terminal_code
        )

        (
            product_name,
            product_name_source,
        ) = _product_name_for_unit(
            gtin=gtin,
            source=source,

            fetched_products=(
                fetched_products
            ),

            cached_products=(
                cached_products
            ),
        )

        unit_state = _upsert_unit(
            cursor,

            source_id=source_id,
            source=source,

            terminal_code=(
                terminal_code
            ),

            legal_entity_id=(
                legal_entity_id
            ),

            core_document_id=(
                core_document_id
            ),

            raw_document_id=(
                raw_document_id
            ),

            product_group=(
                product_group
            ),

            product_name=(
                product_name
            ),

            product_name_source=(
                product_name_source
            ),

            receiver_warehouse_address=(
                receiver_warehouse_address
            ),
        )

        if unit_state == "INSERTED":
            inserted += 1

        elif unit_state == "UPDATED":
            updated += 1

        else:
            unchanged += 1

    return SourcePersistResult(
        source_state=source_state,

        unit_inserted_count=(
            inserted
        ),

        unit_updated_count=(
            updated
        ),

        unit_unchanged_count=(
            unchanged
        ),

        unit_removed_count=(
            removed
        ),

        terminal_count=len(
            expansion.terminal_codes
        ),

        aggregate=(
            expansion.is_aggregate
        ),

        quantity_match_status=(
            quantity_match_status
        ),
    )


def sync_datamatrix_units(
    *,
    database: Database,

    raw_document_id: int,
    core_document_id: int,

    xml_content: bytes,

    token: str,
    product_group: str,
) -> DatamatrixSyncSummary:
    prepared_token = token.strip()

    prepared_group = (
        product_group
        .strip()
        .lower()
    )

    if not prepared_token:
        raise ValueError(
            "Для раскрытия КИ "
            "не передан токен True API."
        )

    if not prepared_group:
        raise ValueError(
            "Для раскрытия КИ "
            "не указана товарная группа."
        )

    sources = load_datamatrix_sources(
        database,

        raw_document_id=(
            raw_document_id
        ),

        core_document_id=(
            core_document_id
        ),
    )

    receiver_address = (
        parse_receiver_warehouse_address(
            xml_content
        )
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

            product_group=(
                prepared_group
            ),

            source_count=0,
            aggregate_count=0,
            terminal_count=0,

            inserted_count=0,
            updated_count=0,
            unchanged_count=0,
            removed_count=0,

            source_inserted_count=0,
            source_updated_count=0,
            source_unchanged_count=0,

            mismatch_count=0,
            product_count=0,

            aggregate_request_count=0,
            product_request_count=0,

            product_lookup_error=None,

            receiver_warehouse_address=(
                receiver_address
            ),
        )

    legal_entity_id = (
        resolve_legal_entity_id(
            database,
            core_document_id,
        )
    )

    cached_products = (
        load_cached_products(
            database
        )
    )

    resolution: DatamatrixResolution = (
        resolve_datamatrix_codes(
            token=prepared_token,

            product_group=(
                prepared_group
            ),

            source_codes=(
                source.code_text
                for source in sources
            ),

            cached_gtins=(
                gtin

                for (
                    gtin,
                    product,
                ) in cached_products.items()

                if product.product_name
            ),
        )
    )

    missing_expansions = [
        source.code_text

        for source in sources

        if (
            source.code_text
            not in resolution.expansions
        )
    ]

    if missing_expansions:
        raise DatamatrixStorageError(
            "True API не вернул "
            "результат раскрытия для КИ: "
            + ", ".join(
                missing_expansions[
                    :10
                ]
            )
        )

    line_statuses = (
        _line_quantity_statuses(
            sources,
            resolution.expansions,
        )
    )

    unit_inserted = 0
    unit_updated = 0
    unit_unchanged = 0
    unit_removed = 0

    source_inserted = 0
    source_updated = 0
    source_unchanged = 0

    aggregate_count = 0
    terminal_count = 0

    mismatch_count = sum(
        1

        for status
        in line_statuses.values()

        if status == "MISMATCH"
    )

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            upsert_product_cards(
                cursor,
                resolution.products,
            )

            for source in sources:
                expansion = (
                    resolution.expansions[
                        source.code_text
                    ]
                )

                quantity_status = (
                    line_statuses[
                        source.document_line_id
                    ]
                )

                persisted = (
                    _persist_one_source(
                        cursor,

                        source=source,
                        expansion=expansion,

                        quantity_match_status=(
                            quantity_status
                        ),

                        legal_entity_id=(
                            legal_entity_id
                        ),

                        core_document_id=(
                            core_document_id
                        ),

                        raw_document_id=(
                            raw_document_id
                        ),

                        product_group=(
                            prepared_group
                        ),

                        receiver_warehouse_address=(
                            receiver_address
                        ),

                        fetched_products=(
                            resolution.products
                        ),

                        cached_products=(
                            cached_products
                        ),
                    )
                )

                unit_inserted += (
                    persisted
                    .unit_inserted_count
                )

                unit_updated += (
                    persisted
                    .unit_updated_count
                )

                unit_unchanged += (
                    persisted
                    .unit_unchanged_count
                )

                unit_removed += (
                    persisted
                    .unit_removed_count
                )

                terminal_count += (
                    persisted
                    .terminal_count
                )

                if persisted.aggregate:
                    aggregate_count += 1

                if (
                    persisted.source_state
                    == "INSERTED"
                ):
                    source_inserted += 1

                elif (
                    persisted.source_state
                    == "UPDATED"
                ):
                    source_updated += 1

                else:
                    source_unchanged += 1

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

        product_group=(
            prepared_group
        ),

        source_count=len(
            sources
        ),

        aggregate_count=(
            aggregate_count
        ),

        terminal_count=(
            terminal_count
        ),

        inserted_count=(
            unit_inserted
        ),

        updated_count=(
            unit_updated
        ),

        unchanged_count=(
            unit_unchanged
        ),

        removed_count=(
            unit_removed
        ),

        source_inserted_count=(
            source_inserted
        ),

        source_updated_count=(
            source_updated
        ),

        source_unchanged_count=(
            source_unchanged
        ),

        mismatch_count=(
            mismatch_count
        ),

        product_count=len(
            resolution.products
        ),

        aggregate_request_count=(
            resolution
            .aggregate_request_count
        ),

        product_request_count=(
            resolution
            .product_request_count
        ),

        product_lookup_error=(
            resolution
            .product_lookup_error
        ),

        receiver_warehouse_address=(
            receiver_address
        ),
    )