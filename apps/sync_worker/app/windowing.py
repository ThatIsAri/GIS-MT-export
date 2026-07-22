from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True, slots=True)
class DateWindow:
    """
    Интервал UTC, используемый адаптивным
    загрузчиком списка документов.
    """

    date_from: datetime
    date_to: datetime
    depth: int = 0


def parse_utc_datetime(
    value: str,
    parameter_name: str,
) -> datetime:
    """
    Разбирает строку ISO 8601 и возвращает
    timezone-aware datetime в UTC.

    Значение без часового пояса интерпретируется
    как UTC для совместимости с текущим CLI.
    """

    prepared = value.strip()

    if not prepared:
        raise ValueError(
            f"{parameter_name} не может быть пустым."
        )

    if prepared.endswith("Z"):
        prepared = (
            prepared[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            prepared
        )

    except ValueError as exc:
        raise ValueError(
            f"{parameter_name} должен быть "
            "в формате ISO 8601."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def format_utc_datetime(
    value: datetime,
) -> str:
    """
    Форматирует datetime в UTC.

    True API получает время с точностью
    до миллисекунд.
    """

    if value.tzinfo is None:
        raise ValueError(
            "datetime должен содержать "
            "информацию о часовом поясе."
        )

    normalized = value.astimezone(
        timezone.utc
    )

    if normalized.microsecond:
        milliseconds = (
            normalized.microsecond
            // 1000
        )

        return (
            normalized.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            + f".{milliseconds:03d}Z"
        )

    return normalized.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def format_request_params(
    params: dict[str, Any],
) -> str:
    """
    Возвращает детерминированную строку
    query-параметров для журнала.

    Ключи сортируются, чтобы одинаковые запросы
    имели одинаковое текстовое представление.
    """

    items: list[
        tuple[str, str]
    ] = []

    for key in sorted(params):
        value = params[key]

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
        ):
            items.extend(
                (
                    str(key),
                    str(item),
                )
                for item in value
            )

        else:
            items.append(
                (
                    str(key),
                    str(value),
                )
            )

    return urlencode(
        items,
        doseq=True,
    )


def split_window(
    window: DateWindow,
) -> tuple[
    DateWindow,
    DateWindow,
]:
    """
    Делит временной интервал пополам.

    Конец левого окна совпадает с началом правого.
    Возможные дубли на границе должны удаляться
    по идентификатору документа.
    """

    midpoint = (
        window.date_from
        + (
            window.date_to
            - window.date_from
        )
        / 2
    )

    if (
        midpoint
        <= window.date_from
        or midpoint
        >= window.date_to
    ):
        raise RuntimeError(
            "WINDOW_SPLIT_FAILED: "
            "не удалось разделить "
            "временное окно."
        )

    next_depth = (
        window.depth
        + 1
    )

    return (
        DateWindow(
            date_from=window.date_from,
            date_to=midpoint,
            depth=next_depth,
        ),
        DateWindow(
            date_from=midpoint,
            date_to=window.date_to,
            depth=next_depth,
        ),
    )


def validate_window_coverage(
    parent_document_ids: set[str],
    leaf_document_ids: set[str],
) -> None:
    """
    Проверяет, что конечные окна покрыли документы,
    полученные в переполненных родительских окнах.

    Проверка не гарантирует, что API вернула вообще
    все существующие документы, но обнаруживает
    потерю уже известных документов при разделении
    временного интервала.
    """

    missing = (
        parent_document_ids
        - leaf_document_ids
    )

    if not missing:
        return

    sample = ", ".join(
        sorted(missing)[:10]
    )

    raise RuntimeError(
        "WINDOW_COVERAGE_MISMATCH: "
        "дочерние окна не вернули "
        f"{len(missing)} документов "
        "из переполненных родительских окон. "
        f"Примеры: {sample}"
    )