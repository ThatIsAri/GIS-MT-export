from __future__ import annotations

from typing import Any

from defusedxml.ElementTree import fromstring


DOCUMENT_KIND_UPD = "UPD"
DOCUMENT_KIND_UKD = "UKD"

DOCUMENT_TYPE_UPD = "UNIVERSAL_TRANSFER_DOCUMENT"
DOCUMENT_TYPE_UPDI = "UNIVERSAL_TRANSFER_DOCUMENT_FIX"
DOCUMENT_TYPE_UKD = "UNIVERSAL_CORRECTION_DOCUMENT"
DOCUMENT_TYPE_UKDI = "UNIVERSAL_CORRECTION_DOCUMENT_FIX"

UPD_DOCUMENT_TYPES = frozenset(
    {
        DOCUMENT_TYPE_UPD,
        DOCUMENT_TYPE_UPDI,
    }
)

UKD_DOCUMENT_TYPES = frozenset(
    {
        DOCUMENT_TYPE_UKD,
        DOCUMENT_TYPE_UKDI,
    }
)

SUPPORTED_EDO_DOCUMENT_TYPES = frozenset(
    {
        *UPD_DOCUMENT_TYPES,
        *UKD_DOCUMENT_TYPES,
    }
)


def local_name(value: str) -> str:
    """
    Возвращает локальное имя XML-тега
    или XML-атрибута.
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


def child(
    element: Any | None,
    name: str,
) -> Any | None:
    """
    Возвращает первого непосредственного
    потомка по локальному имени.
    """

    if element is None:
        return None

    for candidate in list(
        element
    ):
        if local_name(
            candidate.tag
        ) == name:
            return candidate

    return None


def has_product_rows(
    table: Any | None,
) -> bool:
    """
    Проверяет наличие хотя бы одной
    товарной строки СведТов.
    """

    if table is None:
        return False

    return any(
        local_name(
            candidate.tag
        ) == "СведТов"
        for candidate in list(
            table
        )
    )


def document_kind_from_api_type(
    document_type: str | None,
) -> str | None:
    """
    Определяет вид документа
    по коду типа True API.
    """

    prepared = str(
        document_type or ""
    ).strip().upper()

    if prepared in UPD_DOCUMENT_TYPES:
        return DOCUMENT_KIND_UPD

    if prepared in UKD_DOCUMENT_TYPES:
        return DOCUMENT_KIND_UKD

    return None


def document_kind_from_xml(
    xml_content: bytes,
) -> str:
    """
    Определяет вид титула продавца
    по структуре XML.

    Поддерживаются:

    - УПД;
    - УПД(и);
    - УКД;
    - УКД(и).
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

    document = child(
        root,
        "Документ",
    )

    if document is None:
        raise ValueError(
            "В XML отсутствует "
            "элемент Документ."
        )

    if has_product_rows(
        child(
            document,
            "ТаблСчФакт",
        )
    ):
        return DOCUMENT_KIND_UPD

    if has_product_rows(
        child(
            document,
            "ТаблКСчФ",
        )
    ):
        return DOCUMENT_KIND_UKD

    raise ValueError(
        "XML не является поддерживаемым "
        "товарным титулом продавца "
        "УПД/УПД(и) или УКД/УКД(и)."
    )


def is_supported_edo_xml(
    xml_content: bytes,
) -> bool:
    """
    Без исключения проверяет,
    поддерживается ли XML документа.
    """

    try:
        document_kind_from_xml(
            xml_content
        )

    except Exception:
        return False

    return True