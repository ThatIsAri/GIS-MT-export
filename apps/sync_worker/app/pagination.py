from dataclasses import dataclass
from typing import Any


class DocumentPageError(ValueError):
    """Ответ списка документов имеет неожиданную структуру."""


@dataclass(frozen=True, slots=True)
class DocumentPage:
    documents: list[dict[str, Any]]
    document_ids: list[str]
    next_page: bool
    cursor_document_id: str | None
    cursor_received_at: str | None


def parse_document_page(payload: Any) -> DocumentPage:
    """
    Разбирает ответ GET /api/v4/true-api/doc/list.

    Курсор следующей страницы формируется из:
    - number последнего документа;
    - receivedAt последнего документа.
    """

    if not isinstance(payload, dict):
        raise DocumentPageError(
            "Ответ списка документов должен быть JSON-объектом."
        )

    raw_results = payload.get("results")

    if not isinstance(raw_results, list):
        raise DocumentPageError(
            "В ответе отсутствует массив results."
        )

    next_page = payload.get("nextPage")

    if not isinstance(next_page, bool):
        raise DocumentPageError(
            "Поле nextPage должно иметь тип boolean."
        )

    documents = [
        item
        for item in raw_results
        if isinstance(item, dict)
    ]

    document_ids: list[str] = []

    for document in documents:
        document_id = document.get("number")

        if isinstance(document_id, str):
            document_id = document_id.strip()

            if document_id:
                document_ids.append(document_id)

    document_ids = list(dict.fromkeys(document_ids))

    cursor_document_id: str | None = None
    cursor_received_at: str | None = None

    if documents:
        last_document = documents[-1]

        raw_document_id = last_document.get("number")
        raw_received_at = last_document.get("receivedAt")

        if isinstance(raw_document_id, str):
            cursor_document_id = raw_document_id.strip() or None

        if isinstance(raw_received_at, str):
            cursor_received_at = raw_received_at.strip() or None

    if next_page:
        if not documents:
            raise DocumentPageError(
                "Сервер сообщил nextPage=true, "
                "но массив results оказался пустым."
            )

        if not cursor_document_id:
            raise DocumentPageError(
                "Для продолжения пагинации отсутствует "
                "number последнего документа."
            )

        if not cursor_received_at:
            raise DocumentPageError(
                "Для продолжения пагинации отсутствует "
                "receivedAt последнего документа."
            )

    return DocumentPage(
        documents=documents,
        document_ids=document_ids,
        next_page=next_page,
        cursor_document_id=cursor_document_id,
        cursor_received_at=cursor_received_at,
    )