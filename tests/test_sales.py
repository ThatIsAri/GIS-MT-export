from datetime import date
from decimal import Decimal

from app.sales import (
    REPORT_ID_COUNTABLE,
    REPORT_ID_MIXED,
    header_lookup,
    parse_row,
    report_id_for_group,
    requested_dates,
)


def test_report_id_for_supported_groups() -> None:
    assert report_id_for_group(1) == REPORT_ID_COUNTABLE
    assert report_id_for_group(13) == REPORT_ID_MIXED
    assert report_id_for_group(23) == REPORT_ID_MIXED
    assert report_id_for_group(999) is None


def test_requested_dates_are_inclusive() -> None:
    assert requested_dates(
        date(2026, 7, 1),
        date(2026, 7, 3),
    ) == (
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
    )


def test_parse_sales_row_from_official_headers() -> None:
    row = {
        "ИНН": "7700000000",
        "Наименование УОТ": "ООО Тест",
        "Код товара": "04601234567890",
        "Наименование товара": "Напиток",
        "Причина вывода из оборота": "Розничная продажа",
        "Группа причин вывода из оборота": "Продажа конечному потребителю",
        "Регион точки продаж": "Воронежская область",
        "Адрес точки продаж": "г. Воронеж, ул. Тестовая, 1",
        "Количество выведенных из оборота товаров, шт.": "1 234,5",
        "Стоимость выведенных из оборота товаров, руб.": "98 765,43",
    }

    sale_key, values = parse_row(
        row=row,
        lookup=header_lookup(row.keys()),
        legal_entity_id=7,
        product_group_code=23,
        sale_date=date(2026, 8, 4),
    )

    assert len(sale_key) == 64
    assert values["participant_inn"] == "7700000000"
    assert values["gtin"] == "04601234567890"
    assert values["sold_quantity"] == Decimal("1234.5")
    assert values["sold_amount"] == Decimal("98765.43")
    assert values["withdrawal_reason"] == "Розничная продажа"
    assert values["turnover_reason"] == "Продажа конечному потребителю"
