from typing import Any


class DocumentNormalizationError(ValueError):
    """Ответ документа невозможно однозначно нормализовать."""


def normalize_document_info(
    payload: Any,
    expected_document_id: str,
) -> dict[str, Any]:
    """
    Объединяет повторяющиеся элементы ответа
    GET /api/v4/true-api/doc/{docId}/info.

    Исходный RAW-ответ должен быть сохранён до вызова
    этой функции и не должен изменяться.
    """

    if isinstance(payload, dict):
        items = [payload]

    elif isinstance(payload, list):
        items = [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    else:
        raise DocumentNormalizationError(
            "Ответ документа должен быть объектом или массивом объектов."
        )

    if not items:
        raise DocumentNormalizationError(
            "Ответ документа не содержит объектов."
        )

    expected_document_id = expected_document_id.strip()

    matching_items = [
        item
        for item in items
        if str(item.get("number", "")).strip()
        == expected_document_id
    ]

    if not matching_items:
        raise DocumentNormalizationError(
            "В ответе отсутствует запрошенный идентификатор документа."
        )

    normalized: dict[str, Any] = {
        "number": expected_document_id,
    }

    conflicts: dict[str, list[Any]] = {}

    for item in matching_items:
        for key, value in item.items():
            if value is None or value == "":
                continue

            current_value = normalized.get(key)

            if current_value is None or current_value == "":
                normalized[key] = value
                continue

            if current_value == value:
                continue

            # Массивы объединяем с удалением дублей.
            if isinstance(current_value, list) and isinstance(value, list):
                normalized[key] = list(
                    dict.fromkeys(current_value + value)
                )
                continue

            # Противоречивые скалярные значения не затираем.
            conflicts.setdefault(
                key,
                [current_value],
            )

            if value not in conflicts[key]:
                conflicts[key].append(value)

    normalized["_source_item_count"] = len(matching_items)

    if conflicts:
        normalized["_conflicts"] = conflicts

    return normalized