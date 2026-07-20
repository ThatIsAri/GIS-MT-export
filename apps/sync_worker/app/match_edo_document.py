from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import typer
from defusedxml.ElementTree import fromstring

from app.config import get_settings
from app.db import Database


MATCH_THRESHOLD = 70
MAX_CANDIDATES = 500
MAX_STORED_CANDIDATES = 20
DATE_SEARCH_WINDOW_DAYS = 2


@dataclass(frozen=True, slots=True)
class EdoMetadata:
    external_document_id: str
    document_number: str | None
    document_date: date | None
    seller_inn: str | None
    buyer_inn: str | None
    total_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class CoreCandidate:
    id: int
    external_document_id: str
    doc_date: datetime | date | None
    invoice_number: str | None
    invoice_date: datetime | date | None
    sender_inn: str | None
    receiver_inn: str | None


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate: CoreCandidate
    score: int
    method: str


@dataclass(frozen=True, slots=True)
class MatchDecision:
    status: str
    core_document_id: int | None
    method: str | None
    score: int | None
    candidates: tuple[ScoredCandidate, ...]


def local_name(value: str) -> str:
    """
    Удаляет namespace или XML-префикс.
    """

    if "}" in value:
        return value.rsplit("}", 1)[1]

    if ":" in value:
        return value.rsplit(":", 1)[1]

    return value


def child(
    element: Any | None,
    name: str,
) -> Any | None:
    """
    Возвращает первый непосредственный
    дочерний элемент с указанным именем.
    """

    if element is None:
        return None

    for candidate in list(element):
        if local_name(candidate.tag) == name:
            return candidate

    return None


def attr(
    element: Any | None,
    name: str,
) -> str | None:
    """
    Возвращает значение XML-атрибута
    по локальному имени.
    """

    if element is None:
        return None

    for raw_name, raw_value in element.attrib.items():
        if local_name(raw_name) != name:
            continue

        value = str(raw_value).strip()

        return value or None

    return None


def normalize_inn(
    value: str | None,
) -> str | None:
    """
    Оставляет только цифры ИНН
    и проверяет его длину.
    """

    if value is None:
        return None

    digits = "".join(
        character
        for character in value
        if character.isdigit()
    )

    if len(digits) not in {10, 12}:
        return None

    return digits


def normalize_document_number(
    value: str | None,
) -> str | None:
    """
    Нормализует регистр, Unicode и пробелы
    в номере документа.
    """

    if value is None:
        return None

    prepared = unicodedata.normalize(
        "NFKC",
        value,
    )

    prepared = (
        prepared
        .strip()
        .upper()
    )

    prepared = re.sub(
        r"\s+",
        "",
        prepared,
    )

    return prepared or None


def relaxed_document_number(
    value: str | None,
) -> str | None:
    """
    Формирует дополнительный вариант номера
    без разделителей.
    """

    normalized = normalize_document_number(
        value
    )

    if normalized is None:
        return None

    prepared = re.sub(
        r"[^0-9A-ZА-ЯЁ]",
        "",
        normalized,
    )

    return prepared or None


def parse_document_date(
    value: str | None,
) -> date | None:
    """
    Преобразует дату XML УПД в date.
    """

    if value is None:
        return None

    prepared = value.strip()

    for pattern in (
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(
                prepared,
                pattern,
            ).date()

        except ValueError:
            continue

    raise ValueError(
        "Не удалось распознать дату УПД: "
        f"{prepared!r}."
    )


def parse_decimal(
    value: str | None,
) -> Decimal | None:
    """
    Преобразует сумму из XML без float.
    """

    if value is None:
        return None

    prepared = (
        value
        .replace(
            "\u00a0",
            "",
        )
        .replace(
            " ",
            "",
        )
        .replace(
            ",",
            ".",
        )
        .strip()
    )

    if not prepared:
        return None

    try:
        return Decimal(
            prepared
        )

    except InvalidOperation as exc:
        raise ValueError(
            "Не удалось распознать сумму УПД."
        ) from exc


def extract_party_inn(
    invoice_element: Any,
    party_name: str,
) -> str | None:
    """
    Извлекает ИНН из СвПрод или СвПокуп.
    """

    identity = child(
        child(
            invoice_element,
            party_name,
        ),
        "ИдСв",
    )

    if identity is None:
        return None

    direct_value = normalize_inn(
        attr(
            identity,
            "ИННЮЛ",
        )
        or attr(
            identity,
            "ИННФЛ",
        )
    )

    if direct_value is not None:
        return direct_value

    for identity_variant in list(
        identity
    ):
        value = normalize_inn(
            attr(
                identity_variant,
                "ИННЮЛ",
            )
            or attr(
                identity_variant,
                "ИННФЛ",
            )
        )

        if value is not None:
            return value

    return None


def extract_edo_metadata(
    xml_content: bytes,
) -> EdoMetadata:
    """
    Извлекает реквизиты УПД,
    необходимые для сопоставления.
    """

    root = fromstring(
        xml_content
    )

    if local_name(
        root.tag
    ) != "Файл":
        raise ValueError(
            "Корневой элемент XML "
            "не является элементом Файл."
        )

    external_document_id = attr(
        root,
        "ИдФайл",
    )

    if external_document_id is None:
        raise ValueError(
            "В XML отсутствует "
            "Файл/@ИдФайл."
        )

    document = child(
        root,
        "Документ",
    )

    invoice = child(
        document,
        "СвСчФакт",
    )

    table = child(
        document,
        "ТаблСчФакт",
    )

    totals = child(
        table,
        "ВсегоОпл",
    )

    return EdoMetadata(
        external_document_id=(
            external_document_id
        ),
        document_number=attr(
            invoice,
            "НомерДок",
        ),
        document_date=parse_document_date(
            attr(
                invoice,
                "ДатаДок",
            )
        ),
        seller_inn=(
            extract_party_inn(
                invoice,
                "СвПрод",
            )
            if invoice is not None
            else None
        ),
        buyer_inn=(
            extract_party_inn(
                invoice,
                "СвПокуп",
            )
            if invoice is not None
            else None
        ),
        total_amount=parse_decimal(
            attr(
                totals,
                "СтТовУчНалВсего",
            )
        ),
    )


def to_bytes(
    value: Any,
) -> bytes:
    """
    Приводит значение BLOB MySQL к bytes.
    """

    if isinstance(
        value,
        bytes,
    ):
        return value

    if isinstance(
        value,
        bytearray,
    ):
        return bytes(
            value
        )

    if isinstance(
        value,
        memoryview,
    ):
        return value.tobytes()

    raise TypeError(
        "Колонка xml_content "
        "не содержит байтовые данные."
    )


def load_raw_xml(
    database: Database,
    raw_document_id: int,
) -> bytes:
    """
    Загружает XML из raw_edo_document.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    xml_content,
                    xml_well_formed
                FROM raw_edo_document
                WHERE id = %s
                LIMIT 1
                """,
                (
                    raw_document_id,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        raise ValueError(
            f"RAW-документ "
            f"{raw_document_id} "
            "не найден."
        )

    if not bool(
        row[1]
    ):
        raise ValueError(
            f"RAW-документ "
            f"{raw_document_id} "
            "не является корректным XML."
        )

    return to_bytes(
        row[0]
    )


def latest_parsed_raw_document_id(
    database: Database,
) -> int:
    """
    Возвращает последний разобранный XML.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT id
                FROM raw_edo_document
                WHERE xml_well_formed = 1
                  AND parse_status IN (
                      'PARSED',
                      'PARSED_UNMATCHED'
                  )
                ORDER BY id DESC
                LIMIT 1
                """
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        raise ValueError(
            "Не найден разобранный XML ЭДО."
        )

    return int(
        row[0]
    )


def unmatched_raw_document_ids(
    database: Database,
) -> list[int]:
    """
    Возвращает разобранные XML,
    ещё не связанные с CORE.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT id
                FROM raw_edo_document
                WHERE xml_well_formed = 1
                  AND parse_status IN (
                      'PARSED',
                      'PARSED_UNMATCHED'
                  )
                  AND core_document_id IS NULL
                ORDER BY id
                """
            )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    return [
        int(
            row[0]
        )
        for row in rows
    ]


def row_to_candidate(
    row: tuple[Any, ...],
) -> CoreCandidate:
    """
    Преобразует строку MySQL
    в объект кандидата.
    """

    return CoreCandidate(
        id=int(
            row[0]
        ),
        external_document_id=str(
            row[1]
        ),
        doc_date=row[2],
        invoice_number=(
            str(
                row[3]
            ).strip()
            if row[3] is not None
            else None
        ),
        invoice_date=row[4],
        sender_inn=(
            normalize_inn(
                str(
                    row[5]
                )
            )
            if row[5] is not None
            else None
        ),
        receiver_inn=(
            normalize_inn(
                str(
                    row[6]
                )
            )
            if row[6] is not None
            else None
        ),
    )


def load_candidates(
    database: Database,
    metadata: EdoMetadata,
) -> list[CoreCandidate]:
    """
    Ищет кандидатов по:

    1. точному внешнему идентификатору;
    2. датам в диапазоне плюс-минус два дня;
    3. ИНН участников документа.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    id,
                    external_document_id,
                    doc_date,
                    invoice_number,
                    invoice_date,
                    sender_inn,
                    receiver_inn
                FROM core_document
                WHERE external_document_id = %s
                LIMIT 1
                """,
                (
                    metadata.external_document_id,
                ),
            )

            exact_row = cursor.fetchone()

            if exact_row is not None:
                return [
                    row_to_candidate(
                        exact_row
                    )
                ]

            conditions: list[str] = []
            parameters: list[Any] = []

            if metadata.document_date is not None:
                date_from = (
                    metadata.document_date
                    - timedelta(
                        days=DATE_SEARCH_WINDOW_DAYS
                    )
                )

                date_to = (
                    metadata.document_date
                    + timedelta(
                        days=(
                            DATE_SEARCH_WINDOW_DAYS
                            + 1
                        )
                    )
                )

                conditions.append(
                    """
                    (
                        doc_date >= %s
                        AND doc_date < %s
                    )
                    """
                )

                parameters.extend(
                    [
                        date_from,
                        date_to,
                    ]
                )

                conditions.append(
                    """
                    (
                        invoice_date >= %s
                        AND invoice_date < %s
                    )
                    """
                )

                parameters.extend(
                    [
                        date_from,
                        date_to,
                    ]
                )

            party_values = [
                value
                for value in (
                    metadata.seller_inn,
                    metadata.buyer_inn,
                )
                if value is not None
            ]

            if party_values:
                placeholders = ", ".join(
                    ["%s"] * len(
                        party_values
                    )
                )

                conditions.append(
                    f"sender_inn IN ({placeholders})"
                )

                parameters.extend(
                    party_values
                )

                conditions.append(
                    f"receiver_inn IN ({placeholders})"
                )

                parameters.extend(
                    party_values
                )

            if not conditions:
                return []

            query = f"""
                SELECT
                    id,
                    external_document_id,
                    doc_date,
                    invoice_number,
                    invoice_date,
                    sender_inn,
                    receiver_inn
                FROM core_document
                WHERE {' OR '.join(conditions)}
                ORDER BY id
                LIMIT %s
            """

            parameters.append(
                MAX_CANDIDATES
            )

            cursor.execute(
                query,
                tuple(
                    parameters
                ),
            )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    return [
        row_to_candidate(
            row
        )
        for row in rows
    ]


def as_date(
    value: datetime | date | None,
) -> date | None:
    """
    Приводит DATETIME или DATE к date.
    """

    if isinstance(
        value,
        datetime,
    ):
        return value.date()

    if isinstance(
        value,
        date,
    ):
        return value

    return None


def exact_date_match(
    metadata: EdoMetadata,
    candidate: CoreCandidate,
) -> bool:
    """
    Проверяет дату УПД отдельно
    против doc_date и invoice_date.
    """

    if metadata.document_date is None:
        return False

    return metadata.document_date in {
        as_date(
            candidate.doc_date
        ),
        as_date(
            candidate.invoice_date
        ),
    }


def near_date_match(
    metadata: EdoMetadata,
    candidate: CoreCandidate,
) -> bool:
    """
    Проверяет расхождение даты на один день.
    """

    if metadata.document_date is None:
        return False

    candidate_dates = {
        value
        for value in (
            as_date(
                candidate.doc_date
            ),
            as_date(
                candidate.invoice_date
            ),
        )
        if value is not None
    }

    return any(
        abs(
            (
                value
                - metadata.document_date
            ).days
        ) == 1
        for value in candidate_dates
    )


def score_candidate(
    metadata: EdoMetadata,
    candidate: CoreCandidate,
) -> ScoredCandidate:
    """
    Рассчитывает балл совпадения.

    Максимальный балл — 100.
    """

    if (
        candidate.external_document_id
        == metadata.external_document_id
    ):
        return ScoredCandidate(
            candidate=candidate,
            score=100,
            method="EXTERNAL_ID",
        )

    score = 0
    reasons: list[str] = []

    xml_number = normalize_document_number(
        metadata.document_number
    )

    core_number = normalize_document_number(
        candidate.invoice_number
    )

    if (
        xml_number is not None
        and core_number is not None
    ):
        if xml_number == core_number:
            score += 45
            reasons.append(
                "NUMBER"
            )

        elif (
            relaxed_document_number(
                xml_number
            )
            == relaxed_document_number(
                core_number
            )
        ):
            score += 35
            reasons.append(
                "NUMBER_RELAXED"
            )

    if exact_date_match(
        metadata,
        candidate,
    ):
        score += 25
        reasons.append(
            "DATE"
        )

    elif near_date_match(
        metadata,
        candidate,
    ):
        score += 10
        reasons.append(
            "DATE_NEAR"
        )

    same_seller = (
        metadata.seller_inn is not None
        and candidate.sender_inn
        == metadata.seller_inn
    )

    same_buyer = (
        metadata.buyer_inn is not None
        and candidate.receiver_inn
        == metadata.buyer_inn
    )

    reversed_seller = (
        metadata.seller_inn is not None
        and candidate.receiver_inn
        == metadata.seller_inn
    )

    reversed_buyer = (
        metadata.buyer_inn is not None
        and candidate.sender_inn
        == metadata.buyer_inn
    )

    if same_seller:
        score += 20
        reasons.append(
            "SELLER_INN"
        )

    if same_buyer:
        score += 20
        reasons.append(
            "BUYER_INN"
        )

    if (
        not same_seller
        and not same_buyer
    ):
        if reversed_seller:
            score += 10
            reasons.append(
                "SELLER_INN_REVERSED"
            )

        if reversed_buyer:
            score += 10
            reasons.append(
                "BUYER_INN_REVERSED"
            )

    return ScoredCandidate(
        candidate=candidate,
        score=min(
            score,
            100,
        ),
        method=(
            "+".join(
                reasons
            )
            or "NO_MATCH"
        ),
    )


def decide_match(
    metadata: EdoMetadata,
    candidates: list[CoreCandidate],
) -> MatchDecision:
    """
    Выбирает единственного кандидата
    с достаточным баллом.
    """

    scored = tuple(
        sorted(
            (
                score_candidate(
                    metadata,
                    candidate,
                )
                for candidate
                in candidates
            ),
            key=lambda item: (
                -item.score,
                item.candidate.id,
            ),
        )
    )

    if not scored:
        return MatchDecision(
            status="UNMATCHED",
            core_document_id=None,
            method=None,
            score=None,
            candidates=tuple(),
        )

    best = scored[0]

    if best.score < MATCH_THRESHOLD:
        return MatchDecision(
            status="UNMATCHED",
            core_document_id=None,
            method=best.method,
            score=best.score,
            candidates=scored,
        )

    best_count = sum(
        item.score == best.score
        for item in scored
    )

    if best_count > 1:
        return MatchDecision(
            status="AMBIGUOUS",
            core_document_id=None,
            method=best.method,
            score=best.score,
            candidates=scored,
        )

    return MatchDecision(
        status="MATCHED",
        core_document_id=(
            best.candidate.id
        ),
        method=best.method,
        score=best.score,
        candidates=scored,
    )


def candidates_json(
    candidates: tuple[
        ScoredCandidate,
        ...,
    ],
) -> str | None:
    """
    Сохраняет безопасную диагностику кандидатов
    без ИНН и номеров документов.
    """

    if not candidates:
        return None

    payload = [
        {
            "core_document_id": (
                item.candidate.id
            ),
            "score": item.score,
            "method": item.method,
        }
        for item
        in candidates[
            :MAX_STORED_CANDIDATES
        ]
    ]

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )


def persist_match(
    database: Database,
    raw_document_id: int,
    metadata: EdoMetadata,
    decision: MatchDecision,
) -> None:
    """
    Сохраняет результат сопоставления
    и обновляет строки и коды документа.
    """

    parse_status = (
        "PARSED"
        if decision.status == "MATCHED"
        else "PARSED_UNMATCHED"
    )

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE raw_edo_document
                   SET external_document_id = %s,
                       edo_document_number = %s,
                       edo_document_date = %s,
                       seller_inn = %s,
                       buyer_inn = %s,
                       total_amount = %s,
                       core_document_id = %s,
                       match_status = %s,
                       match_method = %s,
                       match_score = %s,
                       match_candidate_count = %s,
                       match_candidates_json = %s,
                       matched_at = UTC_TIMESTAMP(3),
                       parse_status = %s,
                       parse_error = NULL
                 WHERE id = %s
                """,
                (
                    metadata.external_document_id,
                    metadata.document_number,
                    metadata.document_date,
                    metadata.seller_inn,
                    metadata.buyer_inn,
                    metadata.total_amount,
                    decision.core_document_id,
                    decision.status,
                    decision.method,
                    decision.score,
                    len(
                        decision.candidates
                    ),
                    candidates_json(
                        decision.candidates
                    ),
                    parse_status,
                    raw_document_id,
                ),
            )

            cursor.execute(
                """
                UPDATE core_document_line
                   SET core_document_id = %s
                 WHERE raw_edo_document_id = %s
                """,
                (
                    decision.core_document_id,
                    raw_document_id,
                ),
            )

            cursor.execute(
                """
                UPDATE core_document_code
                   SET core_document_id = %s
                 WHERE raw_edo_document_id = %s
                """,
                (
                    decision.core_document_id,
                    raw_document_id,
                ),
            )

        finally:
            cursor.close()


def mark_match_error(
    database: Database,
    raw_document_id: int,
    error: Exception,
) -> None:
    """
    Сохраняет ошибку сопоставления.
    """

    message = (
        f"{type(error).__name__}: "
        f"{error}"
    )[:65535]

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE raw_edo_document
                   SET match_status = 'ERROR',
                       match_method = NULL,
                       match_score = NULL,
                       match_candidate_count = 0,
                       match_candidates_json = NULL,
                       matched_at = UTC_TIMESTAMP(3),
                       parse_error = %s
                 WHERE id = %s
                """,
                (
                    message,
                    raw_document_id,
                ),
            )

        finally:
            cursor.close()


def match_one(
    database: Database,
    raw_document_id: int,
) -> MatchDecision:
    """
    Сопоставляет один XML ЭДО.
    """

    xml_content = load_raw_xml(
        database,
        raw_document_id,
    )

    metadata = extract_edo_metadata(
        xml_content
    )

    candidates = load_candidates(
        database,
        metadata,
    )

    decision = decide_match(
        metadata,
        candidates,
    )

    persist_match(
        database=database,
        raw_document_id=raw_document_id,
        metadata=metadata,
        decision=decision,
    )

    return decision


def main(
    raw_document_id: int | None = typer.Option(
        None,
        "--raw-document-id",
        min=1,
        help=(
            "ID raw_edo_document. "
            "По умолчанию используется "
            "последний разобранный XML."
        ),
    ),

    all_unmatched: bool = typer.Option(
        False,
        "--all-unmatched",
        help=(
            "Сопоставить все разобранные XML "
            "без связи с CORE."
        ),
    ),
) -> None:
    """
    Сопоставляет XML ЭДО
    с документами True API.
    """

    database = Database(
        get_settings()
    )

    if (
        all_unmatched
        and raw_document_id is not None
    ):
        raise typer.BadParameter(
            "Параметры --raw-document-id "
            "и --all-unmatched "
            "нельзя использовать вместе."
        )

    selected_ids = (
        unmatched_raw_document_ids(
            database
        )
        if all_unmatched
        else [
            raw_document_id
            or latest_parsed_raw_document_id(
                database
            )
        ]
    )

    if not selected_ids:
        typer.echo(
            "Нет разобранных XML, "
            "требующих сопоставления."
        )
        return

    counters = {
        "MATCHED": 0,
        "UNMATCHED": 0,
        "AMBIGUOUS": 0,
        "ERROR": 0,
    }

    for index, selected_id in enumerate(
        selected_ids,
        start=1,
    ):
        try:
            decision = match_one(
                database,
                selected_id,
            )

            counters[
                decision.status
            ] += 1

            typer.echo(
                f"{index}/{len(selected_ids)} "
                f"RAW id={selected_id}: "
                f"{decision.status}; "
                "core_document_id="
                f"{decision.core_document_id or '-'}; "
                "score="
                f"{decision.score if decision.score is not None else '-'}; "
                f"method={decision.method or '-'}; "
                f"candidates={len(decision.candidates)}"
            )

        except Exception as exc:
            counters[
                "ERROR"
            ] += 1

            try:
                mark_match_error(
                    database,
                    selected_id,
                    exc,
                )

            except Exception:
                pass

            typer.echo(
                f"{index}/{len(selected_ids)} "
                f"RAW id={selected_id}: "
                f"ERROR "
                f"{type(exc).__name__}: "
                f"{exc}",
                err=True,
            )

    typer.echo("")
    typer.echo(
        "Сопоставление завершено."
    )

    for status in (
        "MATCHED",
        "UNMATCHED",
        "AMBIGUOUS",
        "ERROR",
    ):
        typer.echo(
            f"{status}: "
            f"{counters[status]}"
        )

    if counters["ERROR"]:
        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(
        main
    )