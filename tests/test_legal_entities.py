from datetime import datetime

import pytest

from app.legal_entities import (
    ENTITY_TYPE_IP,
    ENTITY_TYPE_LEGAL,
    activation_problems,
    normalize_cron,
    normalize_entity_type,
    normalize_inn,
    normalize_kpp,
    normalize_product_group,
    normalize_thumbprint,
    parse_datetime_utc,
)


def test_normalize_entity_type_supports_common_aliases() -> None:
    assert (
        normalize_entity_type(
            "IP"
        )
        == ENTITY_TYPE_IP
    )

    assert (
        normalize_entity_type(
            "individual_entrepreneur"
        )
        == ENTITY_TYPE_IP
    )

    assert (
        normalize_entity_type(
            "organization"
        )
        == ENTITY_TYPE_LEGAL
    )

    with pytest.raises(
        ValueError,
        match="Неизвестный тип",
    ):
        normalize_entity_type(
            "UNKNOWN"
        )


def test_normalize_inn_checks_entity_type_length() -> None:
    assert normalize_inn(
        "123456789012",
        ENTITY_TYPE_IP,
    ) == "123456789012"

    assert normalize_inn(
        "1234567890",
        ENTITY_TYPE_LEGAL,
    ) == "1234567890"

    with pytest.raises(
        ValueError,
        match="12 цифр",
    ):
        normalize_inn(
            "1234567890",
            ENTITY_TYPE_IP,
        )


def test_normalize_kpp_rejects_kpp_for_ip() -> None:
    assert normalize_kpp(
        "123456789",
        ENTITY_TYPE_LEGAL,
    ) == "123456789"

    assert normalize_kpp(
        None,
        ENTITY_TYPE_IP,
    ) is None

    with pytest.raises(
        ValueError,
        match="не указывается",
    ):
        normalize_kpp(
            "123456789",
            ENTITY_TYPE_IP,
        )


def test_normalize_thumbprint_removes_spaces_and_colons() -> None:
    source = (
        "AA BB CC DD EE FF 00 11 22 33 "
        "44 55 66 77 88 99 AA BB CC DD"
    )

    assert normalize_thumbprint(
        source
    ) == (
        "AABBCCDDEEFF00112233"
        "445566778899AABBCCDD"
    )

    with pytest.raises(
        ValueError,
        match="40",
    ):
        normalize_thumbprint(
            "ABC"
        )


def test_parse_datetime_utc_converts_offset() -> None:
    result = parse_datetime_utc(
        "2026-07-22T15:00:00+03:00",
        field_name="valid_to",
    )

    assert result == datetime(
        2026,
        7,
        22,
        12,
        0,
        0,
    )

    assert result.tzinfo is None


def test_normalize_product_group_uses_lowercase() -> None:
    assert normalize_product_group(
        " SoftDrinks "
    ) == "softdrinks"

    with pytest.raises(
        ValueError,
        match="латинские буквы",
    ):
        normalize_product_group(
            "газировка"
        )


def test_normalize_cron_requires_five_parts_for_schedule() -> None:
    assert normalize_cron(
        "0 3 * * *",
        schedule_enabled=True,
    ) == "0 3 * * *"

    with pytest.raises(
        ValueError,
        match="пятичастном",
    ):
        normalize_cron(
            "0 3 * *",
            schedule_enabled=True,
        )

    with pytest.raises(
        ValueError,
        match="необходимо указать",
    ):
        normalize_cron(
            None,
            schedule_enabled=True,
        )


def test_activation_problems_reports_missing_configuration() -> None:
    problems = activation_problems(
        entity_type=ENTITY_TYPE_LEGAL,
        kpp=None,
        current_status="SETUP",
        active_certificate_count=0,
        enabled_product_group_count=0,
    )

    assert len(
        problems
    ) == 3

    assert any(
        "КПП" in item
        for item in problems
    )

    assert any(
        "сертификат" in item
        for item in problems
    )

    assert any(
        "товарная группа" in item
        for item in problems
    )

    assert activation_problems(
        entity_type=ENTITY_TYPE_IP,
        kpp=None,
        current_status="SETUP",
        active_certificate_count=1,
        enabled_product_group_count=1,
    ) == []