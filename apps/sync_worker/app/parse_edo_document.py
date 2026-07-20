from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import typer
from defusedxml.ElementTree import fromstring

from app.config import get_settings
from app.db import Database


MAX_ERROR_LENGTH = 65535

SOURCE_ELEMENT_NOM_UPAK = "НомУпак"
SOURCE_TYPE_NOM_UPAK = "NOM_UPAK"

SOURCE_ELEMENT_IDENT_TRANS_UPAK = (
    "НомСредИдентТов/@ИдентТрансУпак"
)
SOURCE_TYPE_IDENT_TRANS_UPAK = "IDENT_TRANS_UPAK"


@dataclass(frozen=True, slots=True)
class ParsedCode:
    sequence_number: int

    source_element_name: str
    source_code_type: str

    transport_package_identifier: str | None

    code_text: str
    code_value: bytes
    code_sha256: str


@dataclass(frozen=True, slots=True)
class ParsedLine:
    line_number: int
    source_line_number: str

    product_name: str | None
    product_code: str | None

    unit_code: str | None
    unit_name: str | None

    quantity: Decimal | None
    unit_price: Decimal | None

    amount_without_vat: Decimal | None
    vat_rate: str | None
    vat_amount: Decimal | None
    amount_with_vat: Decimal | None

    source_payload_hash: str

    codes: tuple[ParsedCode, ...]


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


def children(
    element: Any | None,
    name: str,
) -> list[Any]:
    """
    Возвращает непосредственных дочерних
    элементов с указанным именем.
    """

    if element is None:
        return []

    return [
        candidate
        for candidate in list(element)
        if local_name(
            candidate.tag
        ) == name
    ]


def child(
    element: Any | None,
    name: str,
) -> Any | None:
    """
    Возвращает первый непосредственный
    дочерний элемент с указанным именем.
    """

    if element is None:
        return None

    for candidate in list(element):
        if local_name(
            candidate.tag
        ) == name:
            return candidate

    return None


def attr(
    element: Any | None,
    name: str,
) -> str | None:
    """
    Возвращает значение XML-атрибута
    по локальному имени.
    """

    if element is None:
        return None

    for raw_name, raw_value in (
        element.attrib.items()
    ):
        if local_name(
            raw_name
        ) != name:
            continue

        value = str(
            raw_value
        ).strip()

        return value or None

    return None


def element_text(
    element: Any | None,
) -> str | None:
    """
    Возвращает текст XML-элемента
    без служебных пробелов.
    """

    if (
        element is None
        or element.text is None
    ):
        return None

    value = element.text.strip()

    return value or None


def parse_decimal(
    value: str | None,
    field_name: str,
) -> Decimal | None:
    """
    Преобразует число из XML
    без использования float.
    """

    if value is None:
        return None

    prepared = (
        value
        .replace(
            "\u00a0",
            "",
        )
        .replace(
            " ",
            "",
        )
        .replace(
            ",",
            ".",
        )
        .strip()
    )

    if not prepared:
        return None

    try:
        return Decimal(
            prepared
        )

    except InvalidOperation as exc:
        raise ValueError(
            "Некорректное числовое значение "
            f"в поле {field_name}."
        ) from exc


def decimal_for_hash(
    value: Decimal | None,
) -> str | None:
    """
    Возвращает стабильное строковое
    представление Decimal.
    """

    if value is None:
        return None

    return format(
        value,
        "f",
    )


def parse_vat_amount(
    product_element: Any,
) -> Decimal | None:
    """
    Извлекает сумму НДС из:

    СведТов/СумНал/СумНал
    """

    container = child(
        product_element,
        "СумНал",
    )

    value_element = child(
        container,
        "СумНал",
    )

    return parse_decimal(
        element_text(
            value_element
        ),
        "СведТов/СумНал/СумНал",
    )


def unique_line_number(
    source_value: str,
    fallback: int,
    used: set[int],
) -> int:
    """
    Формирует положительный уникальный
    номер товарной строки.
    """

    try:
        number = int(
            source_value
        )

    except ValueError:
        number = fallback

    if number <= 0:
        number = fallback

    while number in used:
        number += 1

    used.add(
        number
    )

    return number


def parse_product_code(
    product_element: Any,
) -> str | None:
    """
    Извлекает единственное значение
    ДопСведТов/@КодТов.
    """

    values = {
        value
        for extra in children(
            product_element,
            "ДопСведТов",
        )
        if (
            value := attr(
                extra,
                "КодТов",
            )
        )
    }

    if len(values) > 1:
        raise ValueError(
            "В одной товарной строке "
            "обнаружены разные значения КодТов."
        )

    return next(
        iter(values),
        None,
    )


def build_code(
    *,
    sequence_number: int,
    source_element_name: str,
    source_code_type: str,
    transport_package_identifier: str | None,
    code_text: str,
) -> ParsedCode:
    """
    Создаёт нормализованное представление
    одного кода из XML.
    """

    prepared = code_text.strip()

    if not prepared:
        raise ValueError(
            f"Источник {source_element_name} "
            "не содержит значения."
        )

    code_value = prepared.encode(
        "utf-8",
        errors="strict",
    )

    return ParsedCode(
        sequence_number=sequence_number,
        source_element_name=(
            source_element_name
        ),
        source_code_type=(
            source_code_type
        ),
        transport_package_identifier=(
            transport_package_identifier
        ),
        code_text=prepared,
        code_value=code_value,
        code_sha256=(
            hashlib.sha256(
                code_value
            ).hexdigest()
        ),
    )


def parse_codes(
    product_element: Any,
) -> tuple[ParsedCode, ...]:
    """
    Извлекает оба варианта представления кодов:

    1. НомСредИдентТов/@ИдентТрансУпак;
    2. НомСредИдентТов/НомУпак.

    Значения сохраняются по источнику XML.

    На этом этапе они не классифицируются
    как коды экземпляров или агрегации.
    """

    result: list[
        ParsedCode
    ] = []

    for extra in children(
        product_element,
        "ДопСведТов",
    ):
        for container in children(
            extra,
            "НомСредИдентТов",
        ):
            transport_identifier = attr(
                container,
                "ИдентТрансУпак",
            )

            if (
                transport_identifier
                is not None
            ):
                result.append(
                    build_code(
                        sequence_number=(
                            len(result) + 1
                        ),
                        source_element_name=(
                            SOURCE_ELEMENT_IDENT_TRANS_UPAK
                        ),
                        source_code_type=(
                            SOURCE_TYPE_IDENT_TRANS_UPAK
                        ),
                        transport_package_identifier=(
                            transport_identifier
                        ),
                        code_text=(
                            transport_identifier
                        ),
                    )
                )

            for code_element in children(
                container,
                "НомУпак",
            ):
                code_text = element_text(
                    code_element
                )

                if code_text is None:
                    raise ValueError(
                        "Элемент НомУпак "
                        "не содержит значения."
                    )

                result.append(
                    build_code(
                        sequence_number=(
                            len(result) + 1
                        ),
                        source_element_name=(
                            SOURCE_ELEMENT_NOM_UPAK
                        ),
                        source_code_type=(
                            SOURCE_TYPE_NOM_UPAK
                        ),
                        transport_package_identifier=(
                            transport_identifier
                        ),
                        code_text=code_text,
                    )
                )

    return tuple(
        result
    )


def build_line_hash(
    line_data: dict[
        str,
        Any,
    ],
    codes: tuple[
        ParsedCode,
        ...,
    ],
) -> str:
    """
    Формирует SHA-256 нормализованного
    содержимого товарной строки.
    """

    payload = {
        **line_data,
        "codes": [
            {
                "sequence_number": (
                    item.sequence_number
                ),
                "source_element_name": (
                    item.source_element_name
                ),
                "source_code_type": (
                    item.source_code_type
                ),
                "transport_package_identifier": (
                    item
                    .transport_package_identifier
                ),
                "code_sha256": (
                    item.code_sha256
                ),
            }
            for item in codes
        ],
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()


def parse_line(
    product_element: Any,
    fallback_number: int,
    used_numbers: set[int],
) -> ParsedLine:
    """
    Разбирает один элемент СведТов.
    """

    source_line_number = (
        attr(
            product_element,
            "НомСтр",
        )
        or str(
            fallback_number
        )
    )

    line_number = unique_line_number(
        source_value=source_line_number,
        fallback=fallback_number,
        used=used_numbers,
    )

    product_name = attr(
        product_element,
        "НаимТов",
    )

    product_code = parse_product_code(
        product_element
    )

    unit_code = attr(
        product_element,
        "ОКЕИ_Тов",
    )

    unit_name = attr(
        product_element,
        "НаимЕдИзм",
    )

    quantity = parse_decimal(
        attr(
            product_element,
            "КолТов",
        ),
        "КолТов",
    )

    unit_price = parse_decimal(
        attr(
            product_element,
            "ЦенаТов",
        ),
        "ЦенаТов",
    )

    amount_without_vat = parse_decimal(
        attr(
            product_element,
            "СтТовБезНДС",
        ),
        "СтТовБезНДС",
    )

    vat_rate = attr(
        product_element,
        "НалСт",
    )

    vat_amount = parse_vat_amount(
        product_element
    )

    amount_with_vat = parse_decimal(
        attr(
            product_element,
            "СтТовУчНал",
        ),
        "СтТовУчНал",
    )

    codes = parse_codes(
        product_element
    )

    hash_data = {
        "source_line_number": (
            source_line_number
        ),
        "product_name": (
            product_name
        ),
        "product_code": (
            product_code
        ),
        "unit_code": (
            unit_code
        ),
        "unit_name": (
            unit_name
        ),
        "quantity": (
            decimal_for_hash(
                quantity
            )
        ),
        "unit_price": (
            decimal_for_hash(
                unit_price
            )
        ),
        "amount_without_vat": (
            decimal_for_hash(
                amount_without_vat
            )
        ),
        "vat_rate": (
            vat_rate
        ),
        "vat_amount": (
            decimal_for_hash(
                vat_amount
            )
        ),
        "amount_with_vat": (
            decimal_for_hash(
                amount_with_vat
            )
        ),
    }

    return ParsedLine(
        line_number=line_number,
        source_line_number=(
            source_line_number
        ),
        product_name=product_name,
        product_code=product_code,
        unit_code=unit_code,
        unit_name=unit_name,
        quantity=quantity,
        unit_price=unit_price,
        amount_without_vat=(
            amount_without_vat
        ),
        vat_rate=vat_rate,
        vat_amount=vat_amount,
        amount_with_vat=(
            amount_with_vat
        ),
        source_payload_hash=(
            build_line_hash(
                hash_data,
                codes,
            )
        ),
        codes=codes,
    )


def parse_xml(
    xml_content: bytes,
) -> tuple[
    str,
    tuple[
        ParsedLine,
        ...,
    ],
]:
    """
    Разбирает товарные строки УПД.
    """

    root = fromstring(
        xml_content
    )

    if local_name(
        root.tag
    ) != "Файл":
        raise ValueError(
            "Корневой элемент XML "
            "не является элементом Файл."
        )

    external_document_id = attr(
        root,
        "ИдФайл",
    )

    if external_document_id is None:
        raise ValueError(
            "В корневом элементе "
            "отсутствует ИдФайл."
        )

    if len(
        external_document_id
    ) > 512:
        raise ValueError(
            "ИдФайл превышает 512 символов."
        )

    document = child(
        root,
        "Документ",
    )

    table = child(
        document,
        "ТаблСчФакт",
    )

    if table is None:
        raise ValueError(
            "В XML не найден путь "
            "Документ/ТаблСчФакт."
        )

    product_elements = children(
        table,
        "СведТов",
    )

    if not product_elements:
        raise ValueError(
            "В XML отсутствуют "
            "товарные строки СведТов."
        )

    used_numbers: set[int] = set()

    parsed_lines = tuple(
        parse_line(
            product_element=element,
            fallback_number=index,
            used_numbers=used_numbers,
        )
        for index, element
        in enumerate(
            product_elements,
            start=1,
        )
    )

    return (
        external_document_id,
        parsed_lines,
    )


def latest_raw_document_id(
    database: Database,
) -> int:
    """
    Возвращает ID последнего
    корректного XML.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT id
                FROM raw_edo_document
                WHERE xml_well_formed = 1
                ORDER BY id DESC
                LIMIT 1
                """
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        raise ValueError(
            "В RAW-слое нет корректного XML."
        )

    return int(
        row[0]
    )


def load_raw_document(
    database: Database,
    raw_document_id: int,
) -> tuple[
    bytes,
    bool,
]:
    """
    Загружает содержимое одного
    RAW-документа.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    xml_content,
                    xml_well_formed
                FROM raw_edo_document
                WHERE id = %s
                LIMIT 1
                """,
                (
                    raw_document_id,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        raise ValueError(
            f"RAW-документ "
            f"{raw_document_id} "
            "не найден."
        )

    xml_content = row[0]

    if isinstance(
        xml_content,
        memoryview,
    ):
        xml_content = (
            xml_content.tobytes()
        )

    elif isinstance(
        xml_content,
        bytearray,
    ):
        xml_content = bytes(
            xml_content
        )

    elif not isinstance(
        xml_content,
        bytes,
    ):
        raise TypeError(
            "Колонка xml_content "
            "не содержит байтовые данные."
        )

    return (
        xml_content,
        bool(
            row[1]
        ),
    )


def insert_line(
    cursor: Any,
    raw_document_id: int,
    core_document_id: int | None,
    external_document_id: str,
    line: ParsedLine,
) -> int:
    """
    Записывает одну товарную строку.
    """

    cursor.execute(
        """
        INSERT INTO core_document_line (
            raw_edo_document_id,
            core_document_id,
            external_document_id,
            line_number,
            source_line_number,
            product_name,
            product_code,
            unit_code,
            unit_name,
            quantity,
            unit_price,
            amount_without_vat,
            vat_rate,
            vat_amount,
            amount_with_vat,
            source_payload_hash
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        """,
        (
            raw_document_id,
            core_document_id,
            external_document_id,
            line.line_number,
            line.source_line_number,
            line.product_name,
            line.product_code,
            line.unit_code,
            line.unit_name,
            line.quantity,
            line.unit_price,
            line.amount_without_vat,
            line.vat_rate,
            line.vat_amount,
            line.amount_with_vat,
            line.source_payload_hash,
        ),
    )

    line_id = int(
        cursor.lastrowid
    )

    if line_id <= 0:
        raise RuntimeError(
            "MySQL не вернула "
            "ID товарной строки."
        )

    return line_id


def insert_code(
    cursor: Any,
    raw_document_id: int,
    core_document_id: int | None,
    line_id: int,
    external_document_id: str,
    line_number: int,
    code: ParsedCode,
) -> None:
    """
    Записывает одно исходное значение
    кода из XML.
    """

    cursor.execute(
        """
        INSERT INTO core_document_code (
            raw_edo_document_id,
            core_document_id,
            document_line_id,
            external_document_id,
            line_number,
            sequence_number,
            source_element_name,
            source_code_type,
            transport_package_identifier,
            code_text,
            code_value,
            code_char_length,
            code_byte_length,
            code_sha256
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        """,
        (
            raw_document_id,
            core_document_id,
            line_id,
            external_document_id,
            line_number,
            code.sequence_number,
            code.source_element_name,
            code.source_code_type,
            (
                code
                .transport_package_identifier
            ),
            code.code_text,
            code.code_value,
            len(
                code.code_text
            ),
            len(
                code.code_value
            ),
            code.code_sha256,
        ),
    )


def persist_document(
    database: Database,
    raw_document_id: int,
    external_document_id: str,
    lines: tuple[
        ParsedLine,
        ...,
    ],
) -> tuple[
    int | None,
    str,
    dict[
        str,
        int,
    ],
]:
    """
    Атомарно заменяет строки и коды,
    относящиеся к RAW-документу.
    """

    code_counts: dict[
        str,
        int,
    ] = {}

    for line in lines:
        for code in line.codes:
            code_counts[
                code.source_code_type
            ] = (
                code_counts.get(
                    code.source_code_type,
                    0,
                )
                + 1
            )

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT id
                FROM core_document
                WHERE external_document_id = %s
                LIMIT 1
                """,
                (
                    external_document_id,
                ),
            )

            row = cursor.fetchone()

            core_document_id = (
                int(
                    row[0]
                )
                if row is not None
                else None
            )

            cursor.execute(
                """
                DELETE FROM core_document_code
                WHERE raw_edo_document_id = %s
                """,
                (
                    raw_document_id,
                ),
            )

            cursor.execute(
                """
                DELETE FROM core_document_line
                WHERE raw_edo_document_id = %s
                """,
                (
                    raw_document_id,
                ),
            )

            for line in lines:
                line_id = insert_line(
                    cursor=cursor,
                    raw_document_id=(
                        raw_document_id
                    ),
                    core_document_id=(
                        core_document_id
                    ),
                    external_document_id=(
                        external_document_id
                    ),
                    line=line,
                )

                for code in line.codes:
                    insert_code(
                        cursor=cursor,
                        raw_document_id=(
                            raw_document_id
                        ),
                        core_document_id=(
                            core_document_id
                        ),
                        line_id=line_id,
                        external_document_id=(
                            external_document_id
                        ),
                        line_number=(
                            line.line_number
                        ),
                        code=code,
                    )

            parse_status = (
                "PARSED"
                if core_document_id
                is not None
                else "PARSED_UNMATCHED"
            )

            cursor.execute(
                """
                UPDATE raw_edo_document
                   SET external_document_id = %s,
                       core_document_id = %s,
                       parse_status = %s,
                       parse_error = NULL,
                       parsed_at = UTC_TIMESTAMP(3)
                 WHERE id = %s
                """,
                (
                    external_document_id,
                    core_document_id,
                    parse_status,
                    raw_document_id,
                ),
            )

        finally:
            cursor.close()

    return (
        core_document_id,
        parse_status,
        code_counts,
    )


def mark_parse_error(
    database: Database,
    raw_document_id: int,
    error: Exception,
) -> None:
    """
    Записывает безопасное описание
    ошибки разбора.
    """

    message = (
        f"{type(error).__name__}: "
        f"{error}"
    )[:MAX_ERROR_LENGTH]

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE raw_edo_document
                   SET parse_status = 'PARSE_ERROR',
                       parse_error = %s,
                       parsed_at = NULL
                 WHERE id = %s
                """,
                (
                    message,
                    raw_document_id,
                ),
            )

        finally:
            cursor.close()


def main(
    raw_document_id: int | None = typer.Option(
        None,
        "--raw-document-id",
        min=1,
        help=(
            "ID строки raw_edo_document. "
            "По умолчанию используется "
            "последний корректный XML."
        ),
    ),
) -> None:
    """
    Извлекает строки УПД и коды упаковки
    в CORE-таблицы.
    """

    database = Database(
        get_settings()
    )

    selected_id = (
        raw_document_id
        or latest_raw_document_id(
            database
        )
    )

    typer.echo(
        f"Выбран RAW-документ: "
        f"{selected_id}"
    )

    try:
        (
            xml_content,
            well_formed,
        ) = load_raw_document(
            database=database,
            raw_document_id=(
                selected_id
            ),
        )

        if not well_formed:
            raise ValueError(
                "RAW-документ не отмечен "
                "как корректный XML."
            )

        (
            external_document_id,
            lines,
        ) = parse_xml(
            xml_content
        )

        (
            core_document_id,
            parse_status,
            code_counts,
        ) = persist_document(
            database=database,
            raw_document_id=(
                selected_id
            ),
            external_document_id=(
                external_document_id
            ),
            lines=lines,
        )

    except Exception as exc:
        try:
            mark_parse_error(
                database=database,
                raw_document_id=(
                    selected_id
                ),
                error=exc,
            )

        except Exception as status_exc:
            typer.echo(
                "Не удалось записать "
                "статус ошибки: "
                f"{type(status_exc).__name__}: "
                f"{status_exc}",
                err=True,
            )

        typer.echo(
            "Ошибка разбора: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=2
        ) from exc

    total_code_count = sum(
        code_counts.values()
    )

    typer.echo(
        "Разбор XML завершён."
    )

    typer.echo(
        f"Товарных строк: "
        f"{len(lines)}"
    )

    typer.echo(
        f"Кодов всего: "
        f"{total_code_count}"
    )

    typer.echo(
        "Кодов НомУпак: "
        f"{code_counts.get(
            SOURCE_TYPE_NOM_UPAK,
            0,
        )}"
    )

    typer.echo(
        "Кодов ИдентТрансУпак: "
        f"{code_counts.get(
            SOURCE_TYPE_IDENT_TRANS_UPAK,
            0,
        )}"
    )

    typer.echo(
        "Связь с core_document: "
        + (
            str(
                core_document_id
            )
            if core_document_id
            is not None
            else "не найдена"
        )
    )

    typer.echo(
        f"Статус: "
        f"{parse_status}"
    )


if __name__ == "__main__":
    typer.run(
        main
    )