from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.datamatrix_storage import (
    incoming_source_is_newer,
    normalize_document_date_value,
)
from app.db import Database


@dataclass(
    frozen=True,
    slots=True,
)
class UkdDatamatrixReconcileSummary:
    before_count: int
    after_count: int
    removed_count: int
    skipped_newer_count: int


def load_document_date(
    database: Database,
    core_document_id: int,
) -> date | None:
    """
    Возвращает каноническую дату
    корректировочного документа.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT DATE(
                    COALESCE(
                        doc_date,
                        invoice_date,
                        received_at
                    )
                )
                FROM core_document
                WHERE id = %s
                LIMIT 1
                """,
                (
                    core_document_id,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if row is None:
        raise ValueError(
            f"CORE-документ "
            f"{core_document_id} "
            "не найден."
        )

    return normalize_document_date_value(
        row[0]
    )


def load_code_hashes(
    database: Database,
    *,
    raw_document_id: int,
    core_document_id: int,
    source_code_type: str,
) -> set[str]:
    """
    Загружает SHA-256 кодов выбранного
    типа из обработанного УКД.
    """

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT DISTINCT
                    code_sha256
                FROM core_document_code
                WHERE raw_edo_document_id = %s
                  AND core_document_id = %s
                  AND source_code_type = %s
                """,
                (
                    raw_document_id,
                    core_document_id,
                    source_code_type,
                ),
            )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    return {
        str(
            row[0]
        ).strip()
        for row in rows
        if (
            row[0] is not None
            and str(
                row[0]
            ).strip()
        )
    }


def reconcile_ukd_datamatrix_units(
    *,
    database: Database,
    raw_document_id: int,
    core_document_id: int,
) -> UkdDatamatrixReconcileSummary:
    """
    Удаляет из текущего хранилища КИ,
    которые были указаны в УКД в блоке
    «до», но отсутствуют в блоке «после».

    История не удаляется.

    Исходные значения УКД остаются в:

    - raw_edo_document;
    - core_document_line;
    - core_document_code.

    Удаляется только текущая
    материализация из datamatrix_unit.
    """

    before_hashes = load_code_hashes(
        database,
        raw_document_id=(
            raw_document_id
        ),
        core_document_id=(
            core_document_id
        ),
        source_code_type=(
            "NOM_UPAK_BEFORE"
        ),
    )

    after_hashes = load_code_hashes(
        database,
        raw_document_id=(
            raw_document_id
        ),
        core_document_id=(
            core_document_id
        ),
        source_code_type=(
            "NOM_UPAK"
        ),
    )

    removed_hashes = sorted(
        before_hashes
        - after_hashes
    )

    if not removed_hashes:
        return (
            UkdDatamatrixReconcileSummary(
                before_count=(
                    len(before_hashes)
                ),
                after_count=(
                    len(after_hashes)
                ),
                removed_count=0,
                skipped_newer_count=0,
            )
        )

    incoming_date = load_document_date(
        database,
        core_document_id,
    )

    removed_count = 0
    skipped_newer_count = 0

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            for code_sha256 in (
                removed_hashes
            ):
                cursor.execute(
                    """
                    SELECT
                        id,
                        raw_edo_document_id,
                        source_document_date
                    FROM datamatrix_unit
                    WHERE code_sha256 = %s
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (
                        code_sha256,
                    ),
                )

                row: (
                    dict[str, Any]
                    | None
                ) = cursor.fetchone()

                if row is None:
                    continue

                is_newer_or_equal = (
                    incoming_source_is_newer(
                        incoming_document_date=(
                            incoming_date
                        ),
                        incoming_raw_document_id=(
                            raw_document_id
                        ),
                        current_document_date=(
                            row.get(
                                "source_document_date"
                            )
                        ),
                        current_raw_document_id=(
                            int(
                                row[
                                    "raw_edo_document_id"
                                ]
                            )
                        ),
                    )
                )

                if not is_newer_or_equal:
                    skipped_newer_count += 1
                    continue

                cursor.execute(
                    """
                    DELETE FROM datamatrix_unit
                    WHERE id = %s
                    """,
                    (
                        int(
                            row["id"]
                        ),
                    ),
                )

                removed_count += int(
                    cursor.rowcount
                    or 0
                )

        finally:
            cursor.close()

    return (
        UkdDatamatrixReconcileSummary(
            before_count=(
                len(before_hashes)
            ),
            after_count=(
                len(after_hashes)
            ),
            removed_count=(
                removed_count
            ),
            skipped_newer_count=(
                skipped_newer_count
            ),
        )
    )