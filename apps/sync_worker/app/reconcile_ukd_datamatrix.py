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
    removed_unit_count: int

    skipped_newer_count: int


def load_document_date(
    database: Database,
    core_document_id: int,
) -> date | None:
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
            "CORE-документ "
            f"{core_document_id} "
            "не найден."
        )

    return normalize_document_date_value(
        row[0]
    )


def _normalize_optional_text(
    value: Any,
) -> str | None:
    if value is None:
        return None

    prepared = " ".join(
        str(
            value
        ).split()
    )

    return prepared or None


def load_root_code_hashes(
    database: Database,
    *,
    raw_document_id: int,
    core_document_id: int,

    package_source_type: str,
    transport_source_type: str,
) -> set[str]:
    """
    Возвращает корневые КИ
    выбранного состояния УКД.

    Если существует ИдентТрансУпак,
    НомУпак с тем же транспортным
    идентификатором не считается
    самостоятельным корнем.
    """

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            cursor.execute(
                """
                SELECT
                    document_line_id,
                    source_code_type,
                    transport_package_identifier,

                    code_text,
                    code_sha256,

                    sequence_number,
                    id

                FROM core_document_code

                WHERE raw_edo_document_id = %s

                  AND core_document_id = %s

                  AND source_code_type
                      IN (%s, %s)

                ORDER BY
                    document_line_id,
                    sequence_number,
                    id
                """,
                (
                    raw_document_id,
                    core_document_id,
                    package_source_type,
                    transport_source_type,
                ),
            )

            rows = [
                dict(
                    row
                )
                for row
                in cursor.fetchall()
            ]

        finally:
            cursor.close()

    by_line: dict[
        int,
        list[
            dict[
                str,
                Any,
            ]
        ],
    ] = {}

    for row in rows:
        by_line.setdefault(
            int(
                row[
                    "document_line_id"
                ]
            ),
            [],
        ).append(
            row
        )

    result: set[str] = set()

    for line_rows in by_line.values():
        transport_roots = {
            str(
                row[
                    "code_text"
                ]
            ).strip()

            for row in line_rows

            if (
                str(
                    row[
                        "source_code_type"
                    ]
                )
                == transport_source_type
            )

            and str(
                row[
                    "code_text"
                ]
            ).strip()
        }

        for row in line_rows:
            source_type = str(
                row[
                    "source_code_type"
                ]
            )

            if (
                source_type
                == package_source_type
            ):
                transport_identifier = (
                    _normalize_optional_text(
                        row.get(
                            "transport_package_identifier"
                        )
                    )
                )

                if (
                    transport_identifier
                    is not None

                    and transport_identifier
                    in transport_roots
                ):
                    continue

            code_hash = str(
                row[
                    "code_sha256"
                ]
            ).strip()

            if code_hash:
                result.add(
                    code_hash
                )

    return result


def reconcile_ukd_datamatrix_units(
    *,
    database: Database,
    raw_document_id: int,
    core_document_id: int,
) -> UkdDatamatrixReconcileSummary:
    """
    Удаляет из текущего хранилища
    корневые КИ, которые присутствовали
    в состоянии «до», но отсутствуют
    в состоянии «после».

    Удаление datamatrix_source_code
    каскадно удаляет:

    - дерево агрегации;
    - конечные КИ единиц, которые всё ещё
      относятся к этому корню.

    Исторические данные RAW и CORE
    не удаляются.
    """

    before_hashes = (
        load_root_code_hashes(
            database,

            raw_document_id=(
                raw_document_id
            ),

            core_document_id=(
                core_document_id
            ),

            package_source_type=(
                "NOM_UPAK_BEFORE"
            ),

            transport_source_type=(
                "IDENT_TRANS_UPAK_BEFORE"
            ),
        )
    )

    after_hashes = (
        load_root_code_hashes(
            database,

            raw_document_id=(
                raw_document_id
            ),

            core_document_id=(
                core_document_id
            ),

            package_source_type=(
                "NOM_UPAK"
            ),

            transport_source_type=(
                "IDENT_TRANS_UPAK"
            ),
        )
    )

    removed_hashes = sorted(
        before_hashes
        - after_hashes
    )

    if not removed_hashes:
        return (
            UkdDatamatrixReconcileSummary(
                before_count=len(
                    before_hashes
                ),

                after_count=len(
                    after_hashes
                ),

                removed_count=0,
                removed_unit_count=0,
                skipped_newer_count=0,
            )
        )

    incoming_date = (
        load_document_date(
            database,
            core_document_id,
        )
    )

    removed_source_count = 0
    removed_unit_count = 0
    skipped_newer_count = 0

    with database.transaction() as connection:
        cursor = connection.cursor(
            dictionary=True
        )

        try:
            for code_hash in removed_hashes:
                cursor.execute(
                    """
                    SELECT
                        id,
                        raw_edo_document_id,
                        source_document_date

                    FROM datamatrix_source_code

                    WHERE code_sha256 = %s

                    LIMIT 1
                    FOR UPDATE
                    """,
                    (
                        code_hash,
                    ),
                )

                row = cursor.fetchone()

                if row is None:
                    continue

                replace_current = (
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

                        current_raw_document_id=int(
                            row[
                                "raw_edo_document_id"
                            ]
                        ),
                    )
                )

                if not replace_current:
                    skipped_newer_count += 1
                    continue

                source_id = int(
                    row[
                        "id"
                    ]
                )

                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS unit_count

                    FROM datamatrix_unit

                    WHERE source_code_id = %s
                    """,
                    (
                        source_id,
                    ),
                )

                count_row = (
                    cursor.fetchone()
                )

                removed_unit_count += int(
                    (
                        count_row[
                            "unit_count"
                        ]
                        if count_row
                        else 0
                    )
                )

                cursor.execute(
                    """
                    DELETE FROM datamatrix_source_code
                    WHERE id = %s
                    """,
                    (
                        source_id,
                    ),
                )

                removed_source_count += int(
                    cursor.rowcount
                    or 0
                )

        finally:
            cursor.close()

    return UkdDatamatrixReconcileSummary(
        before_count=len(
            before_hashes
        ),

        after_count=len(
            after_hashes
        ),

        removed_count=(
            removed_source_count
        ),

        removed_unit_count=(
            removed_unit_count
        ),

        skipped_newer_count=(
            skipped_newer_count
        ),
    )