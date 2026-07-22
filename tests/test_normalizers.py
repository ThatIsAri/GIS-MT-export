import pytest

from app.normalizers import (
    DocumentNormalizationError,
    normalize_document_info,
)


def test_normalize_document_info_merges_arrays_and_tracks_conflicts() -> None:
    payload = [
        {
            "number": "doc-1",
            "status": "PROCESSED",
            "productGroup": [
                "beer",
            ],
        },
        {
            "number": "doc-1",
            "status": "ACCEPTED",
            "productGroup": [
                "beer",
                "water",
            ],
        },
        {
            "number": "other",
            "status": "IGNORED",
        },
    ]

    result = normalize_document_info(
        payload,
        "doc-1",
    )

    assert (
        result["number"]
        == "doc-1"
    )

    assert result["productGroup"] == [
        "beer",
        "water",
    ]

    assert (
        result["_source_item_count"]
        == 2
    )

    assert result["_conflicts"] == {
        "status": [
            "PROCESSED",
            "ACCEPTED",
        ]
    }


def test_normalize_document_info_rejects_missing_requested_document() -> None:
    with pytest.raises(
        DocumentNormalizationError,
        match="запрошенный",
    ):
        normalize_document_info(
            {
                "number": "other",
            },
            "doc-1",
        )


def test_normalize_document_info_rejects_non_object_payload() -> None:
    with pytest.raises(
        DocumentNormalizationError,
        match="объектом или массивом",
    ):
        normalize_document_info(
            "invalid",
            "doc-1",
        )