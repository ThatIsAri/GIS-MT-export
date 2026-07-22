import pytest

from app.pagination import (
    DocumentPageError,
    parse_document_page,
)


def test_parse_document_page_deduplicates_ids_preserving_order() -> None:
    page = parse_document_page(
        {
            "results": [
                {
                    "number": "doc-1",
                    "receivedAt": (
                        "2026-07-01T00:00:00Z"
                    ),
                },
                {
                    "number": "doc-1",
                    "receivedAt": (
                        "2026-07-01T00:00:00Z"
                    ),
                },
                {
                    "number": "doc-2",
                    "receivedAt": (
                        "2026-07-01T00:00:01Z"
                    ),
                },
            ],
            "nextPage": False,
        }
    )

    assert page.document_ids == [
        "doc-1",
        "doc-2",
    ]

    assert page.next_page is False


def test_parse_document_page_requires_cursor_when_next_page_is_true() -> None:
    with pytest.raises(
        DocumentPageError,
        match="receivedAt",
    ):
        parse_document_page(
            {
                "results": [
                    {
                        "number": "doc-1",
                    },
                ],
                "nextPage": True,
            }
        )


def test_parse_document_page_rejects_empty_continuation_page() -> None:
    with pytest.raises(
        DocumentPageError,
        match="results оказался пустым",
    ):
        parse_document_page(
            {
                "results": [],
                "nextPage": True,
            }
        )