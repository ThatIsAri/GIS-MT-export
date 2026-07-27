from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


COLLECTION_PATH = (
    Path(__file__).resolve().parents[1]
    / "postman"
    / "GIS_MT.postman_collection.json"
)


def load_collection() -> dict[str, Any]:
    return json.loads(
        COLLECTION_PATH.read_text(
            encoding="utf-8-sig"
        )
    )


def iter_requests(
    items: list[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    for item in items:
        nested_items = item.get(
            "item"
        )

        if isinstance(
            nested_items,
            list,
        ):
            yield from iter_requests(
                nested_items
            )

            continue

        if "request" in item:
            yield item


def request_url(
    item: dict[str, Any],
) -> str:
    url = item["request"].get(
        "url"
    )

    if isinstance(
        url,
        str,
    ):
        return url

    if isinstance(
        url,
        dict,
    ):
        raw = url.get(
            "raw"
        )

        if isinstance(
            raw,
            str,
        ):
            return raw

    raise AssertionError(
        f"У запроса {item.get('name')!r} "
        "отсутствует URL."
    )


def request_headers(
    item: dict[str, Any],
) -> dict[str, str]:
    headers: dict[str, str] = {}

    for header in item["request"].get(
        "header",
        [],
    ):
        key = str(
            header.get(
                "key",
                "",
            )
        ).strip()

        value = str(
            header.get(
                "value",
                "",
            )
        ).strip()

        if key:
            headers[
                key.lower()
            ] = value

    return headers


def test_collection_has_expected_schema_and_name() -> None:
    collection = load_collection()

    assert (
        collection["info"]["schema"]
        == (
            "https://schema.getpostman.com/"
            "json/collection/v2.1.0/"
            "collection.json"
        )
    )

    assert (
        collection["info"]["name"]
        == "GIS MT True API — рабочие запросы"
    )


def test_collection_contains_safe_variables() -> None:
    collection = load_collection()

    variables = {
        item["key"]: item.get(
            "value"
        )
        for item in collection[
            "variable"
        ]
    }

    required_variables = {
        "true_api_v3_url",
        "true_api_v4_url",
        "token",
        "participant_inn",
        "auth_uuid",
        "auth_signature",
        "product_group",
        "date_from",
        "date_to",
        "limit",
        "document_number",
        "edo_document_uuid",
        "aggregation_code",
    }

    assert required_variables.issubset(
        variables
    )

    assert variables[
        "token"
    ] == ""

    assert variables[
        "auth_uuid"
    ] == ""

    assert variables[
        "auth_signature"
    ] == ""

    assert variables[
        "participant_inn"
    ] == "0000000000"

    assert variables[
        "document_number"
    ] == "PASTE_DOCUMENT_NUMBER_HERE"

    assert variables[
        "aggregation_code"
    ] == "PASTE_AGGREGATION_CODE_HERE"


def test_collection_contains_all_required_requests() -> None:
    collection = load_collection()

    requests = {
        item["name"]: item
        for item in iter_requests(
            collection["item"]
        )
    }

    assert set(
        requests
    ) == {
        "1. Получить данные для подписи",
        "2. Обменять подпись на токен",
        "Список документов",
        "Сведения о документе",
        "Содержимое входящего документа ЭДО",
        "Получить состав кода агрегации",
    }

    assert request_url(
        requests[
            "Список документов"
        ]
    ).startswith(
        "{{true_api_v4_url}}/doc/list?"
    )

    assert request_url(
        requests[
            "Сведения о документе"
        ]
    ) == (
        "{{true_api_v4_url}}/doc/"
        "{{document_number}}/info"
    )

    assert request_url(
        requests[
            "Содержимое входящего документа ЭДО"
        ]
    ) == (
        "{{true_api_v3_url}}/elk/"
        "incoming-documents/"
        "{{edo_document_uuid}}/content"
    )

    assert request_url(
        requests[
            "Получить состав кода агрегации"
        ]
    ) == (
        "{{true_api_v3_url}}/cises/"
        "aggregated/list?pg={{product_group}}"
    )


def test_protected_requests_use_authorization_header() -> None:
    collection = load_collection()

    protected_request_names = {
        "Список документов",
        "Сведения о документе",
        "Содержимое входящего документа ЭДО",
        "Получить состав кода агрегации",
    }

    for item in iter_requests(
        collection["item"]
    ):
        headers = request_headers(
            item
        )

        assert "aut" not in headers

        if (
            item["name"]
            in protected_request_names
        ):
            assert headers.get(
                "authorization"
            ) == "Bearer {{token}}"


def test_auth_requests_are_explicitly_noauth() -> None:
    collection = load_collection()

    auth_request_names = {
        "1. Получить данные для подписи",
        "2. Обменять подпись на токен",
    }

    for item in iter_requests(
        collection["item"]
    ):
        if (
            item["name"]
            not in auth_request_names
        ):
            continue

        assert item[
            "request"
        ]["auth"] == {
            "type": "noauth"
        }

        assert (
            "authorization"
            not in request_headers(
                item
            )
        )


def test_every_request_has_success_status_test() -> None:
    collection = load_collection()

    for item in iter_requests(
        collection["item"]
    ):
        scripts = [
            event.get(
                "script",
                {},
            ).get(
                "exec",
                [],
            )
            for event in item.get(
                "event",
                [],
            )
            if event.get(
                "listen"
            ) == "test"
        ]

        script_text = "\n".join(
            line
            for script in scripts
            for line in script
        )

        assert (
            "pm.response.code"
            in script_text
        )

        assert (
            "within(200, 299)"
            in script_text
        )


def test_collection_does_not_contain_postman_template_or_export_link() -> None:
    collection = load_collection()

    serialized = json.dumps(
        collection,
        ensure_ascii=False,
    )

    assert (
        "Welcome to Postman"
        not in serialized
    )

    assert (
        "_collection_link"
        not in serialized
    )

    assert (
        "Bearer eyJ"
        not in serialized
    )