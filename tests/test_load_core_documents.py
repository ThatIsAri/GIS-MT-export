from datetime import datetime

import pytest

from app.load_core_documents import (
    decode_payload,
    json_for_mysql,
    parse_iso_datetime,
)


def test_decode_payload_accepts_dict_without_conversion() -> None:
    payload = {
        "number": "doc-1",
    }

    assert (
        decode_payload(
            payload
        )
        is payload
    )


def test_decode_payload_decodes_json_bytes() -> None:
    result = decode_payload(
        b'{"number":"doc-1"}'
    )

    assert result == {
        "number": "doc-1",
    }


def test_decode_payload_rejects_unsupported_type() -> None:
    with pytest.raises(
        ValueError,
        match="неподдерживаемый тип",
    ):
        decode_payload(
            123
        )


def test_parse_iso_datetime_converts_offset_to_naive_utc() -> None:
    result = parse_iso_datetime(
        "2026-07-21T15:10:00+03:00"
    )

    assert result == datetime(
        2026,
        7,
        21,
        12,
        10,
        0,
    )

    assert result.tzinfo is None


def test_parse_iso_datetime_returns_none_for_invalid_value() -> None:
    assert (
        parse_iso_datetime(
            "invalid"
        )
        is None
    )

    assert (
        parse_iso_datetime(
            None
        )
        is None
    )


def test_json_for_mysql_uses_compact_utf8_json() -> None:
    result = json_for_mysql(
        {
            "name": "Вода",
        }
    )

    assert (
        result
        == '{"name":"Вода"}'
    )