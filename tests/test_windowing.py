from datetime import datetime, timezone

import pytest

from app.windowing import (
    DateWindow,
    format_request_params,
    format_utc_datetime,
    parse_utc_datetime,
    split_window,
    validate_window_coverage,
)


def test_parse_utc_datetime_converts_offset_to_utc() -> None:
    result = parse_utc_datetime(
        "2026-07-21T15:00:00+03:00",
        "date_from",
    )

    assert result == datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=timezone.utc,
    )


def test_parse_utc_datetime_treats_naive_value_as_utc() -> None:
    result = parse_utc_datetime(
        "2026-07-21T12:00:00",
        "date_from",
    )

    assert (
        result.tzinfo
        == timezone.utc
    )

    assert result.hour == 12


def test_format_utc_datetime_truncates_to_milliseconds() -> None:
    value = datetime(
        2026,
        7,
        21,
        12,
        0,
        0,
        987654,
        tzinfo=timezone.utc,
    )

    assert (
        format_utc_datetime(value)
        == "2026-07-21T12:00:00.987Z"
    )


def test_format_utc_datetime_rejects_naive_datetime() -> None:
    with pytest.raises(
        ValueError,
        match="часовом поясе",
    ):
        format_utc_datetime(
            datetime(
                2026,
                7,
                21,
                12,
                0,
                0,
            )
        )


def test_split_window_has_no_gap_and_increments_depth() -> None:
    source = DateWindow(
        date_from=datetime(
            2026,
            7,
            1,
            tzinfo=timezone.utc,
        ),
        date_to=datetime(
            2026,
            7,
            3,
            tzinfo=timezone.utc,
        ),
        depth=2,
    )

    left, right = split_window(
        source
    )

    assert (
        left.date_from
        == source.date_from
    )

    assert (
        left.date_to
        == right.date_from
    )

    assert (
        right.date_to
        == source.date_to
    )

    assert (
        left.depth
        == right.depth
        == 3
    )


def test_split_window_rejects_zero_duration() -> None:
    moment = datetime(
        2026,
        7,
        21,
        12,
        0,
        tzinfo=timezone.utc,
    )

    source = DateWindow(
        date_from=moment,
        date_to=moment,
        depth=0,
    )

    with pytest.raises(
        RuntimeError,
        match="WINDOW_SPLIT_FAILED",
    ):
        split_window(
            source
        )


def test_format_request_params_is_deterministic() -> None:
    result = format_request_params(
        {
            "pg": "beer",
            "limit": 100,
        }
    )

    assert (
        result
        == "limit=100&pg=beer"
    )


def test_format_request_params_expands_multiple_values() -> None:
    result = format_request_params(
        {
            "did": [
                "doc-1",
                "doc-2",
            ],
            "limit": 100,
        }
    )

    assert (
        result
        == (
            "did=doc-1"
            "&did=doc-2"
            "&limit=100"
        )
    )


def test_validate_window_coverage_accepts_complete_leaf_set() -> None:
    validate_window_coverage(
        parent_document_ids={
            "doc-1",
            "doc-2",
        },
        leaf_document_ids={
            "doc-1",
            "doc-2",
            "doc-3",
        },
    )


def test_validate_window_coverage_rejects_missing_documents() -> None:
    with pytest.raises(
        RuntimeError,
        match="WINDOW_COVERAGE_MISMATCH",
    ):
        validate_window_coverage(
            parent_document_ids={
                "doc-1",
                "doc-2",
            },
            leaf_document_ids={
                "doc-1",
            },
        )