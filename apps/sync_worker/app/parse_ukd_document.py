from __future__ import annotations

from decimal import Decimal
from typing import Any

from defusedxml.ElementTree import fromstring

from app.parse_edo_document import (
    ParsedCode,
    ParsedLine,
    attr,
    build_code,
    build_line_hash,
    child,
    children,
    decimal_for_hash,
    element_text,
    parse_decimal,
    parse_product_code,
    unique_line_number,
)


SOURCE_TYPE_NOM_UPAK_BEFORE = (
    "NOM_UPAK_BEFORE"
)

SOURCE_TYPE_IDENT_TRANS_UPAK_BEFORE = (
    "IDENT_TRANS_UPAK_BEFORE"
)

# Состояние после корректировки является
# текущим состоянием документа.
#
# Поэтому используются стандартные типы,
# которые уже понимает datamatrix_storage.py.
SOURCE_TYPE_NOM_UPAK_AFTER = (
    "NOM_UPAK"
)

SOURCE_TYPE_IDENT_TRANS_UPAK_AFTER = (
    "IDENT_TRANS_UPAK"
)


def first_attr(
    element: Any | None,
    *names: str,
) -> str | None:
    """
    Возвращает первый найденный атрибут.
    """

    for name in names:
        value = attr(
            element,
            name,
        )

        if value is not None:
            return value

    return None


def first_decimal(
    element: Any | None,
    field_label: str,
    *names: str,
) -> Decimal | None:
    """
    Возвращает первое найденное
    числовое значение атрибута.
    """

    for name in names:
        value = attr(
            element,
            name,
        )

        if value is None:
            continue

        return parse_decimal(
            value,
            f"{field_label}/{name}",
        )

    return None


def first_not_none(
    *values: Decimal | None,
) -> Decimal | None:
    """
    Возвращает первое значение,
    отличное от None.

    Decimal("0") считается корректным
    значением и не пропускается.
    """

    for value in values:
        if value is not None:
            return value

    return None


def parse_compound_decimal(
    product_element: Any,
    element_name: str,
    *attribute_names: str,
) -> Decimal | None:
    """
    Извлекает число из сложного
    элемента УКД.

    Поддерживает варианты форматов,
    где значение хранится:

    - в атрибуте;
    - непосредственно в тексте элемента.
    """

    container = child(
        product_element,
        element_name,
    )

    if container is None:
        return None

    for attribute_name in (
        attribute_names
    ):
        value = attr(
            container,
            attribute_name,
        )

        if value is None:
            continue

        return parse_decimal(
            value,
            (
                f"{element_name}"
                f"/@{attribute_name}"
            ),
        )

    text = element_text(
        container
    )

    if text is not None:
        return parse_decimal(
            text,
            element_name,
        )

    return None


def code_containers(
    product_element: Any,
    container_name: str,
) -> list[Any]:
    """
    Находит контейнеры кодов УКД.

    Поддерживаются варианты:

    СведТов/НомСредИдентТовДо

    и:

    СведТов/ДопСведТов/
        НомСредИдентТовДо
    """

    result = list(
        children(
            product_element,
            container_name,
        )
    )

    for extra in children(
        product_element,
        "ДопСведТов",
    ):
        result.extend(
            children(
                extra,
                container_name,
            )
        )

    return result


def parse_code_group(
    *,
    product_element: Any,
    container_name: str,
    role: str,
    start_sequence: int,
) -> list[ParsedCode]:
    """
    Разбирает одну группу кодов:

    - состояние до изменения;
    - состояние после изменения.
    """

    result: list[
        ParsedCode
    ] = []

    is_before = (
        role == "BEFORE"
    )

    source_type_transport = (
        SOURCE_TYPE_IDENT_TRANS_UPAK_BEFORE
        if is_before
        else SOURCE_TYPE_IDENT_TRANS_UPAK_AFTER
    )

    source_type_package = (
        SOURCE_TYPE_NOM_UPAK_BEFORE
        if is_before
        else SOURCE_TYPE_NOM_UPAK_AFTER
    )

    for container in code_containers(
        product_element,
        container_name,
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
                        start_sequence
                        + len(result)
                    ),
                    source_element_name=(
                        f"{container_name}"
                        "/@ИдентТрансУпак"
                    ),
                    source_code_type=(
                        source_type_transport
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
                    f"Элемент {container_name}"
                    "/НомУпак не содержит "
                    "значения."
                )

            result.append(
                build_code(
                    sequence_number=(
                        start_sequence
                        + len(result)
                    ),
                    source_element_name=(
                        f"{container_name}"
                        "/НомУпак"
                    ),
                    source_code_type=(
                        source_type_package
                    ),
                    transport_package_identifier=(
                        transport_identifier
                    ),
                    code_text=code_text,
                )
            )

    return result


def parse_codes(
    product_element: Any,
) -> tuple[
    ParsedCode,
    ...,
]:
    """
    Сохраняет коды УКД
    до и после изменения.

    Коды из блока «после» получают типы:

    - NOM_UPAK;
    - IDENT_TRANS_UPAK.

    Поэтому существующий механизм
    хранилища DataMatrix воспринимает
    их как актуальное состояние.

    Коды «до» получают отдельные типы:

    - NOM_UPAK_BEFORE;
    - IDENT_TRANS_UPAK_BEFORE.
    """

    before = parse_code_group(
        product_element=(
            product_element
        ),
        container_name=(
            "НомСредИдентТовДо"
        ),
        role="BEFORE",
        start_sequence=1,
    )

    after = parse_code_group(
        product_element=(
            product_element
        ),
        container_name=(
            "НомСредИдентТовПосле"
        ),
        role="AFTER",
        start_sequence=(
            len(before) + 1
        ),
    )

    return tuple(
        [
            *before,
            *after,
        ]
    )


def parse_line(
    product_element: Any,
    fallback_number: int,
    used_numbers: set[int],
) -> ParsedLine:
    """
    Разбирает одну товарную строку УКД.

    Для текущего состояния используются
    значения «после изменения».

    Одновременно поддерживаются старый
    и новый варианты XML-атрибутов.
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

    line_number = (
        unique_line_number(
            source_value=(
                source_line_number
            ),
            fallback=fallback_number,
            used=used_numbers,
        )
    )

    product_name = attr(
        product_element,
        "НаимТов",
    )

    product_code = (
        parse_product_code(
            product_element
        )
        or attr(
            product_element,
            "КодТов",
        )
    )

    unit_code = first_attr(
        product_element,
        "ОКЕИ_ТовПосле",
        "ОКЕИ_Тов",
        "ОКЕИ_ТовДо",
    )

    unit_name = first_attr(
        product_element,
        "НаимЕдИзмПосле",
        "НаимЕдИзм",
        "НаимЕдИзмДо",
    )

    if unit_name is None:
        for extra in children(
            product_element,
            "ДопСведТов",
        ):
            unit_name = first_attr(
                extra,
                "НаимЕдИзмПосле",
                "НаимЕдИзм",
                "НаимЕдИзмДо",
            )

            if unit_name is not None:
                break

    quantity = first_decimal(
        product_element,
        "СведТов",
        "КолТовПосле",
        "КолТов",
        "КолТовДо",
    )

    unit_price = first_decimal(
        product_element,
        "СведТов",
        "ЦенаТовПосле",
        "ЦенаТов",
        "ЦенаТовДо",
    )

    amount_without_vat = (
        first_not_none(
            first_decimal(
                product_element,
                "СведТов",
                "СтТовБезНДСПосле",
            ),
            parse_compound_decimal(
                product_element,
                "СтТовБезНДС",
                "СтоимПосле",
                "СтТовБезНДСПосле",
            ),
        )
    )

    vat_rate = first_attr(
        product_element,
        "НалСтПосле",
        "НалСт",
        "НалСтДо",
    )

    vat_amount = (
        parse_compound_decimal(
            product_element,
            "СумНал",
            "СумПосле",
            "СумНалПосле",
        )
    )

    amount_with_vat = (
        first_not_none(
            first_decimal(
                product_element,
                "СведТов",
                "СтТовУчНалПосле",
            ),
            parse_compound_decimal(
                product_element,
                "СтТовУчНал",
                "СтоимПосле",
                "СтТовУчНалПосле",
            ),
        )
    )

    codes = parse_codes(
        product_element
    )

    hash_data = {
        "document_kind": "UKD",
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


def parse_ukd_xml(
    xml_content: bytes,
) -> tuple[
    str,
    tuple[
        ParsedLine,
        ...,
    ],
]:
    """
    Разбирает товарные строки
    титула продавца УКД/УКД(и).
    """

    root = fromstring(
        xml_content
    )

    external_document_id = attr(
        root,
        "ИдФайл",
    )

    if external_document_id is None:
        raise ValueError(
            "В XML отсутствует "
            "Файл/@ИдФайл."
        )

    document = child(
        root,
        "Документ",
    )

    table = child(
        document,
        "ТаблКСчФ",
    )

    if table is None:
        raise ValueError(
            "В XML не найден путь "
            "Документ/ТаблКСчФ."
        )

    product_elements = children(
        table,
        "СведТов",
    )

    if not product_elements:
        raise ValueError(
            "В XML УКД отсутствуют "
            "товарные строки СведТов."
        )

    used_numbers: set[
        int
    ] = set()

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