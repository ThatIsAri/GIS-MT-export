from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from app.client import (
    GisMtAuthError,
    GisMtClient,
    GisMtError,
)
from app.config import get_settings


AGGREGATE_BATCH_SIZE = 100
PRODUCT_BATCH_SIZE = 100
MAX_AGGREGATION_DEPTH = 32


class DatamatrixExpansionError(RuntimeError):
    """Ошибка раскрытия КИ до уровня единицы товара."""


@dataclass(
    frozen=True,
    slots=True,
)
class AggregationEdge:
    parent_code: str
    child_code: str
    depth: int
    is_terminal: bool


@dataclass(
    frozen=True,
    slots=True,
)
class ExpandedCode:
    source_code: str
    is_aggregate: bool
    terminal_codes: tuple[str, ...]
    edges: tuple[AggregationEdge, ...]


@dataclass(
    frozen=True,
    slots=True,
)
class ProductCard:
    gtin: str
    name: str | None
    brand: str | None
    package_type: str | None
    product_group: str | None
    raw_payload_json: str


@dataclass(
    frozen=True,
    slots=True,
)
class DatamatrixResolution:
    expansions: dict[str, ExpandedCode]
    products: dict[str, ProductCard]
    product_lookup_error: str | None
    aggregate_request_count: int
    product_request_count: int


def normalize_code(value: Any) -> str:
    prepared = str(value or "").strip()

    if not prepared:
        raise DatamatrixExpansionError(
            "ГИС МТ вернула пустой КИ "
            "в дереве агрегации."
        )

    return prepared


def code_sha256(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def extract_gtin(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    prepared = str(value).strip()

    if prepared[:3].lower() == "]d2":
        prepared = prepared[3:]

    if prepared.startswith("(01)"):
        candidate = prepared[4:18]

    elif prepared.startswith("01"):
        candidate = prepared[2:16]

    elif len(prepared) >= 14:
        candidate = prepared[:14]

    else:
        return None

    if (
        len(candidate) != 14
        or not candidate.isdigit()
    ):
        return None

    return candidate


def chunked(
    values: list[str],
    size: int,
) -> Iterable[list[str]]:
    for index in range(
        0,
        len(values),
        size,
    ):
        yield values[
            index:index + size
        ]


def unique_codes(
    values: Iterable[str],
) -> list[str]:
    result: list[str] = []
    used: set[str] = set()

    for value in values:
        prepared = normalize_code(value)

        if prepared in used:
            continue

        used.add(prepared)
        result.append(prepared)

    return result


def _mapping_for_requested_codes(
    payload: Any,
    requested_codes: list[str],
) -> dict[str, Any]:
    requested = set(requested_codes)

    if isinstance(payload, dict):
        if requested.intersection(
            payload.keys()
        ):
            return payload

        for key in (
            "result",
            "results",
            "data",
            "response",
            "aggregations",
            "items",
        ):
            nested = payload.get(key)

            if (
                isinstance(nested, dict)
                and requested.intersection(
                    nested.keys()
                )
            ):
                return nested

    raise DatamatrixExpansionError(
        "Ответ aggregated/list не содержит "
        "запрошенные КИ."
    )


def _object_code(
    value: dict[str, Any],
) -> str | None:
    for key in (
        "cis",
        "code",
        "ki",
        "markingCode",
        "identificationCode",
    ):
        candidate = value.get(key)

        if (
            candidate is not None
            and str(candidate).strip()
        ):
            return str(candidate).strip()

    return None


def _object_children(
    value: dict[str, Any],
) -> Any:
    for key in (
        "children",
        "childs",
        "codes",
        "items",
        "content",
    ):
        if key in value:
            return value[key]

    return []


def _child_entries(
    node: Any,
) -> list[tuple[str, Any]]:
    if node is None:
        return []

    if isinstance(node, str):
        prepared = node.strip()

        return (
            [(prepared, [])]
            if prepared
            else []
        )

    if isinstance(node, list):
        result: list[tuple[str, Any]] = []

        for item in node:
            if isinstance(item, str):
                prepared = item.strip()

                if prepared:
                    result.append(
                        (
                            prepared,
                            [],
                        )
                    )

                continue

            if isinstance(item, dict):
                object_code = _object_code(
                    item
                )

                if object_code is not None:
                    result.append(
                        (
                            object_code,
                            _object_children(
                                item
                            ),
                        )
                    )
                    continue

                if len(item) == 1:
                    key, value = next(
                        iter(
                            item.items()
                        )
                    )

                    result.append(
                        (
                            normalize_code(
                                key
                            ),
                            value,
                        )
                    )

                    continue

        return result

    if isinstance(node, dict):
        object_code = _object_code(
            node
        )

        if object_code is not None:
            return [
                (
                    object_code,
                    _object_children(
                        node
                    ),
                )
            ]

        metadata_keys = {
            "error",
            "errorCode",
            "errorMessage",
            "message",
            "status",
        }

        return [
            (
                normalize_code(key),
                value,
            )
            for key, value in node.items()
            if key not in metadata_keys
        ]

    return []


def parse_expanded_code(
    source_code: str,
    node: Any,
) -> ExpandedCode:
    source = normalize_code(
        source_code
    )

    edges: list[
        AggregationEdge
    ] = []

    terminals: list[str] = []
    terminal_set: set[str] = set()

    def add_terminal(
        code: str,
    ) -> None:
        if code in terminal_set:
            return

        terminal_set.add(code)
        terminals.append(code)

    def walk(
        parent_code: str,
        current_node: Any,
        depth: int,
        ancestry: frozenset[str],
    ) -> None:
        if depth > MAX_AGGREGATION_DEPTH:
            raise DatamatrixExpansionError(
                "Превышена максимальная "
                "глубина агрегации для КИ "
                f"{source}."
            )

        entries = _child_entries(
            current_node
        )

        if not entries:
            add_terminal(
                parent_code
            )
            return

        for (
            child_code,
            child_node,
        ) in entries:
            child = normalize_code(
                child_code
            )

            if child in ancestry:
                raise DatamatrixExpansionError(
                    "В дереве агрегации "
                    "обнаружен цикл: "
                    f"{parent_code} -> "
                    f"{child}."
                )

            child_entries = (
                _child_entries(
                    child_node
                )
            )

            is_terminal = (
                not child_entries
            )

            edges.append(
                AggregationEdge(
                    parent_code=(
                        parent_code
                    ),
                    child_code=child,
                    depth=depth,
                    is_terminal=(
                        is_terminal
                    ),
                )
            )

            if is_terminal:
                add_terminal(
                    child
                )

            else:
                walk(
                    child,
                    child_node,
                    depth + 1,
                    ancestry
                    | frozenset(
                        {
                            child,
                        }
                    ),
                )

    root_entries = _child_entries(
        node
    )

    if not root_entries:
        add_terminal(source)

    else:
        walk(
            source,
            node,
            1,
            frozenset(
                {
                    source,
                }
            ),
        )

    if not terminals:
        raise DatamatrixExpansionError(
            "Для КИ "
            f"{source} "
            "не найден ни один "
            "конечный КИ."
        )

    return ExpandedCode(
        source_code=source,
        is_aggregate=bool(edges),
        terminal_codes=tuple(
            terminals
        ),
        edges=tuple(edges),
    )


def parse_aggregate_payload(
    payload: Any,
    requested_codes: list[str],
) -> dict[str, ExpandedCode]:
    mapping = (
        _mapping_for_requested_codes(
            payload,
            requested_codes,
        )
    )

    result: dict[
        str,
        ExpandedCode,
    ] = {}

    for code in requested_codes:
        if code not in mapping:
            raise DatamatrixExpansionError(
                "Ответ aggregated/list "
                "не содержит КИ: "
                f"{code}."
            )

        result[code] = (
            parse_expanded_code(
                code,
                mapping[code],
            )
        )

    return result


def _find_product_objects(
    payload: Any,
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(
                item,
                dict,
            )
        ]

    if not isinstance(
        payload,
        dict,
    ):
        return []

    if payload.get("gtin") is not None:
        return [payload]

    for key in (
        "results",
        "result",
        "products",
        "items",
        "data",
        "response",
    ):
        nested = payload.get(key)

        if isinstance(
            nested,
            list,
        ):
            return [
                item
                for item in nested
                if isinstance(
                    item,
                    dict,
                )
            ]

        if isinstance(
            nested,
            dict,
        ):
            objects = (
                _find_product_objects(
                    nested
                )
            )

            if objects:
                return objects

    keyed_products: list[
        dict[str, Any]
    ] = []

    for (
        key,
        value,
    ) in payload.items():
        if (
            isinstance(
                key,
                str,
            )
            and len(key) == 14
            and key.isdigit()
            and isinstance(
                value,
                dict,
            )
        ):
            item = dict(value)

            item.setdefault(
                "gtin",
                key,
            )

            keyed_products.append(
                item
            )

    return keyed_products


def _first_text(
    item: dict[str, Any],
    names: tuple[str, ...],
) -> str | None:
    for name in names:
        value = item.get(name)

        if value is None:
            continue

        prepared = " ".join(
            str(value).split()
        )

        if prepared:
            return prepared

    return None


def parse_product_payload(
    payload: Any,
) -> dict[str, ProductCard]:
    result: dict[
        str,
        ProductCard,
    ] = {}

    for item in _find_product_objects(
        payload
    ):
        gtin = _first_text(
            item,
            (
                "gtin",
                "code",
                "productGtin",
            ),
        )

        if (
            gtin is None
            or len(gtin) != 14
            or not gtin.isdigit()
        ):
            continue

        result[gtin] = ProductCard(
            gtin=gtin,
            name=_first_text(
                item,
                (
                    "name",
                    "productName",
                    "goodName",
                    "fullName",
                    "shortName",
                ),
            ),
            brand=_first_text(
                item,
                (
                    "brand",
                    "brandName",
                ),
            ),
            package_type=_first_text(
                item,
                (
                    "packageType",
                    "package_type",
                ),
            ),
            product_group=_first_text(
                item,
                (
                    "productGroup",
                    "productGroupName",
                ),
            ),
            raw_payload_json=(
                json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                    default=str,
                )
            ),
        )

    return result


async def _resolve_async(
    *,
    token: str,
    product_group: str,
    source_codes: list[str],
    gtins_without_lookup: set[str],
) -> DatamatrixResolution:
    settings = get_settings()

    expansions: dict[
        str,
        ExpandedCode,
    ] = {}

    aggregate_request_count = 0
    product_request_count = 0

    product_lookup_error: (
        str | None
    ) = None

    async with GisMtClient(
        settings,
        token,
    ) as client:
        for batch in chunked(
            source_codes,
            AGGREGATE_BATCH_SIZE,
        ):
            response = (
                await client.get_aggregate(
                    product_group=(
                        product_group
                    ),
                    codes=batch,
                )
            )

            aggregate_request_count += 1

            expansions.update(
                parse_aggregate_payload(
                    response.payload,
                    batch,
                )
            )

        gtins = unique_codes(
            gtin
            for expansion in (
                expansions.values()
            )
            for code in (
                expansion.terminal_codes
            )
            if (
                (
                    gtin := extract_gtin(
                        code
                    )
                )
                is not None
                and gtin
                not in (
                    gtins_without_lookup
                )
            )
        )

        products: dict[
            str,
            ProductCard,
        ] = {}

        for batch in chunked(
            gtins,
            PRODUCT_BATCH_SIZE,
        ):
            try:
                response = (
                    await client.get_products(
                        gtins=batch
                    )
                )

                product_request_count += 1

                products.update(
                    parse_product_payload(
                        response.payload
                    )
                )

            except GisMtAuthError:
                raise

            except GisMtError as exc:
                product_lookup_error = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )[:2000]

                break

    return DatamatrixResolution(
        expansions=expansions,
        products=products,
        product_lookup_error=(
            product_lookup_error
        ),
        aggregate_request_count=(
            aggregate_request_count
        ),
        product_request_count=(
            product_request_count
        ),
    )


def resolve_datamatrix_codes(
    *,
    token: str,
    product_group: str,
    source_codes: Iterable[str],
    cached_gtins: Iterable[str] = (),
) -> DatamatrixResolution:
    prepared_token = token.strip()

    prepared_group = (
        product_group
        .strip()
        .lower()
    )

    prepared_codes = unique_codes(
        source_codes
    )

    if not prepared_token:
        raise ValueError(
            "Токен True API не передан."
        )

    if not prepared_group:
        raise ValueError(
            "Товарная группа True API "
            "не передана."
        )

    if not prepared_codes:
        return DatamatrixResolution(
            expansions={},
            products={},
            product_lookup_error=None,
            aggregate_request_count=0,
            product_request_count=0,
        )

    cached = {
        str(value).strip()
        for value in cached_gtins
        if str(value).strip()
    }

    return asyncio.run(
        _resolve_async(
            token=prepared_token,
            product_group=(
                prepared_group
            ),
            source_codes=(
                prepared_codes
            ),
            gtins_without_lookup=(
                cached
            ),
        )
    )