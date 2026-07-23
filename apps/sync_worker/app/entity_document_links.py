from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import typer
from mysql.connector import MySQLConnection

from app.config import get_settings
from app.db import Database


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "Привязка документов CORE к организации "
        "и товарной группе исходного запуска."
    ),
)


@dataclass(
    frozen=True,
    slots=True,
)
class EntityDocumentLinkSummary:
    """
    Итог привязки документов одного запуска.
    """

    run_id: int
    legal_entity_id: int
    product_group: str
    source_document_count: int
    linked_document_count: int


def get_scoped_details_run(
    connection: MySQLConnection,
    run_id: int,
) -> dict[str, Any]:
    """
    Возвращает область запуска подробностей.
    """

    if run_id < 1:
        raise ValueError(
            "run_id должен быть больше 0."
        )

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                id,
                legal_entity_id,
                product_group,
                job_type,
                status
            FROM sys_sync_run
            WHERE id = %s
            LIMIT 1
            """,
            (
                run_id,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if row is None:
        raise ValueError(
            "Служебный запуск "
            f"id={run_id} не найден."
        )

    if str(
        row["job_type"]
    ).strip().upper() != (
        "SYNC_DOCUMENT_DETAILS"
    ):
        raise ValueError(
            "Запуск не относится к "
            "SYNC_DOCUMENT_DETAILS."
        )

    if row["legal_entity_id"] is None:
        raise ValueError(
            "У запуска отсутствует "
            "legal_entity_id."
        )

    legal_entity_id = int(
        row["legal_entity_id"]
    )

    if legal_entity_id < 1:
        raise ValueError(
            "У запуска указан некорректный "
            "legal_entity_id."
        )

    product_group_value = row[
        "product_group"
    ]

    if product_group_value is None:
        raise ValueError(
            "У запуска отсутствует "
            "товарная группа."
        )

    product_group = str(
        product_group_value
    ).strip().lower()

    if not product_group:
        raise ValueError(
            "Товарная группа запуска пуста."
        )

    row["legal_entity_id"] = (
        legal_entity_id
    )

    row["product_group"] = (
        product_group
    )

    return dict(
        row
    )


def read_run_observations(
    connection: MySQLConnection,
    *,
    run_id: int,
) -> list[dict[str, Any]]:
    """
    Возвращает неизменяемые наблюдения
    документов выбранного запуска.
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                id,
                core_document_id,
                legal_entity_id,
                product_group,
                sync_run_id,
                raw_response_id,
                observed_at
            FROM core_document_observation
            WHERE sync_run_id = %s
            ORDER BY
                observed_at,
                id
            """,
            (
                run_id,
            ),
        )

        return [
            dict(
                row
            )
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()


def validate_observation_scope(
    *,
    observation: dict[str, Any],
    run_id: int,
    legal_entity_id: int,
    product_group: str,
) -> None:
    """
    Проверяет соответствие наблюдения
    области служебного запуска.
    """

    observation_run_id = int(
        observation["sync_run_id"]
    )

    observation_entity_id = int(
        observation["legal_entity_id"]
    )

    observation_product_group = str(
        observation["product_group"]
    ).strip().lower()

    if observation_run_id != run_id:
        raise RuntimeError(
            "DOCUMENT_OBSERVATION_RUN_MISMATCH: "
            "наблюдение относится к другому "
            "служебному запуску."
        )

    if (
        observation_entity_id
        != legal_entity_id
    ):
        raise RuntimeError(
            "DOCUMENT_OBSERVATION_ENTITY_MISMATCH: "
            "наблюдение относится к другой "
            "организации."
        )

    if (
        observation_product_group
        != product_group
    ):
        raise RuntimeError(
            "DOCUMENT_OBSERVATION_GROUP_MISMATCH: "
            "наблюдение относится к другой "
            "товарной группе."
        )

    if not isinstance(
        observation["observed_at"],
        datetime,
    ):
        raise RuntimeError(
            "Наблюдение документа не содержит "
            "корректный observed_at."
        )


UPSERT_ENTITY_DOCUMENT_SQL = """
    INSERT INTO legal_entity_document (
        legal_entity_id,
        core_document_id,
        product_group,
        first_seen_sync_run_id,
        last_seen_sync_run_id,
        first_seen_raw_response_id,
        last_seen_raw_response_id,
        first_seen_at,
        last_seen_at,
        created_at,
        updated_at
    )
    VALUES (
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        %s,
        UTC_TIMESTAMP(6),
        UTC_TIMESTAMP(6)
    )
    ON DUPLICATE KEY UPDATE
        first_seen_sync_run_id =
            IF(
                VALUES(first_seen_at)
                    < first_seen_at,
                VALUES(
                    first_seen_sync_run_id
                ),
                first_seen_sync_run_id
            ),

        first_seen_raw_response_id =
            IF(
                VALUES(first_seen_at)
                    < first_seen_at,
                VALUES(
                    first_seen_raw_response_id
                ),
                first_seen_raw_response_id
            ),

        last_seen_sync_run_id =
            IF(
                VALUES(last_seen_at)
                    >= last_seen_at,
                VALUES(
                    last_seen_sync_run_id
                ),
                last_seen_sync_run_id
            ),

        last_seen_raw_response_id =
            IF(
                VALUES(last_seen_at)
                    >= last_seen_at,
                VALUES(
                    last_seen_raw_response_id
                ),
                last_seen_raw_response_id
            ),

        first_seen_at =
            LEAST(
                first_seen_at,
                VALUES(first_seen_at)
            ),

        last_seen_at =
            GREATEST(
                last_seen_at,
                VALUES(last_seen_at)
            ),

        updated_at =
            UTC_TIMESTAMP(6)
"""


def upsert_entity_document(
    connection: MySQLConnection,
    *,
    legal_entity_id: int,
    product_group: str,
    run_id: int,
    core_document_id: int,
    raw_response_id: int,
    observed_at: datetime,
) -> None:
    """
    Добавляет одно наблюдение в агрегированную
    связь организации с документом.

    Для более старого наблюдения обновляются
    только first_seen_*.

    Для более нового наблюдения обновляются
    только last_seen_*.
    """

    cursor = connection.cursor()

    try:
        cursor.execute(
            UPSERT_ENTITY_DOCUMENT_SQL,
            (
                legal_entity_id,
                core_document_id,
                product_group,
                run_id,
                run_id,
                raw_response_id,
                raw_response_id,
                observed_at,
                observed_at,
            ),
        )

    finally:
        cursor.close()


def count_distinct_observed_documents(
    observations: list[
        dict[str, Any]
    ],
) -> int:
    """
    Считает уникальные канонические документы
    среди наблюдений запуска.
    """

    return len(
        {
            int(
                observation[
                    "core_document_id"
                ]
            )
            for observation in observations
        }
    )


def count_linked_documents_for_run(
    connection: MySQLConnection,
    *,
    run_id: int,
    legal_entity_id: int,
    product_group: str,
) -> int:
    """
    Считает уникальные документы запуска,
    для которых существует агрегированная связь
    legal_entity_document.
    """

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT
                COUNT(
                    DISTINCT observation
                    .core_document_id
                )
            FROM core_document_observation
                AS observation

            JOIN legal_entity_document
                AS entity_document
              ON entity_document
                    .legal_entity_id =
                 observation
                    .legal_entity_id

             AND entity_document
                    .core_document_id =
                 observation
                    .core_document_id

             AND entity_document
                    .product_group =
                 observation
                    .product_group

            WHERE observation.sync_run_id = %s
              AND observation.legal_entity_id = %s
              AND observation.product_group = %s
            """,
            (
                run_id,
                legal_entity_id,
                product_group,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if row is None:
        return 0

    return int(
        row[0]
    )


def count_invalid_link_ranges(
    connection: MySQLConnection,
    *,
    run_id: int,
    legal_entity_id: int,
    product_group: str,
) -> int:
    """
    Проверяет, что диапазон first_seen/last_seen
    агрегированной связи включает все наблюдения
    выбранного запуска.
    """

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT
                COUNT(*)
            FROM (
                SELECT
                    core_document_id,
                    MIN(observed_at)
                        AS minimum_observed_at,
                    MAX(observed_at)
                        AS maximum_observed_at
                FROM core_document_observation
                WHERE sync_run_id = %s
                  AND legal_entity_id = %s
                  AND product_group = %s
                GROUP BY core_document_id
            ) AS observed_range

            LEFT JOIN legal_entity_document
                AS entity_document
              ON entity_document
                    .legal_entity_id = %s

             AND entity_document
                    .core_document_id =
                 observed_range
                    .core_document_id

             AND entity_document
                    .product_group = %s

            WHERE entity_document.id IS NULL

               OR entity_document.first_seen_at
                    > observed_range
                        .minimum_observed_at

               OR entity_document.last_seen_at
                    < observed_range
                        .maximum_observed_at
            """,
            (
                run_id,
                legal_entity_id,
                product_group,
                legal_entity_id,
                product_group,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if row is None:
        return 0

    return int(
        row[0]
    )


def link_core_documents_for_run(
    *,
    database: Database,
    run_id: int,
) -> EntityDocumentLinkSummary:
    """
    Привязывает наблюдения выбранного запуска
    к организации и товарной группе.

    Канонический документ остаётся единым
    в core_document.

    Каждое появление документа хранится
    в core_document_observation.

    legal_entity_document содержит
    агрегированное первое и последнее
    обнаружение документа организацией.
    """

    with database.transaction() as connection:
        run = get_scoped_details_run(
            connection,
            run_id,
        )

        legal_entity_id = int(
            run["legal_entity_id"]
        )

        product_group = str(
            run["product_group"]
        )

        observations = read_run_observations(
            connection,
            run_id=run_id,
        )

        if not observations:
            raise RuntimeError(
                "Для запуска отсутствуют "
                "core_document_observation. "
                "Сначала необходимо выполнить "
                "перенос RAW в CORE."
            )

        for observation in observations:
            validate_observation_scope(
                observation=observation,
                run_id=run_id,
                legal_entity_id=(
                    legal_entity_id
                ),
                product_group=(
                    product_group
                ),
            )

            upsert_entity_document(
                connection,
                legal_entity_id=(
                    legal_entity_id
                ),
                product_group=(
                    product_group
                ),
                run_id=run_id,
                core_document_id=int(
                    observation[
                        "core_document_id"
                    ]
                ),
                raw_response_id=int(
                    observation[
                        "raw_response_id"
                    ]
                ),
                observed_at=observation[
                    "observed_at"
                ],
            )

        source_document_count = (
            count_distinct_observed_documents(
                observations
            )
        )

        linked_document_count = (
            count_linked_documents_for_run(
                connection,
                run_id=run_id,
                legal_entity_id=(
                    legal_entity_id
                ),
                product_group=(
                    product_group
                ),
            )
        )

        if (
            linked_document_count
            != source_document_count
        ):
            raise RuntimeError(
                "ENTITY_DOCUMENT_LINK_COUNT_MISMATCH: "
                "количество агрегированных связей "
                "не совпало с количеством "
                "наблюдаемых документов. "
                f"Источник: {source_document_count}; "
                f"связано: {linked_document_count}."
            )

        invalid_range_count = (
            count_invalid_link_ranges(
                connection,
                run_id=run_id,
                legal_entity_id=(
                    legal_entity_id
                ),
                product_group=(
                    product_group
                ),
            )
        )

        if invalid_range_count > 0:
            raise RuntimeError(
                "ENTITY_DOCUMENT_SEEN_RANGE_MISMATCH: "
                "диапазон first_seen/last_seen "
                "не покрывает все наблюдения. "
                "Ошибочных связей: "
                f"{invalid_range_count}."
            )

    return EntityDocumentLinkSummary(
        run_id=run_id,
        legal_entity_id=legal_entity_id,
        product_group=product_group,
        source_document_count=(
            source_document_count
        ),
        linked_document_count=(
            linked_document_count
        ),
    )


@app.command("run")
def run_command(
    run_id: int = typer.Option(
        ...,
        "--run-id",
        min=1,
        help=(
            "ID scoped-запуска "
            "SYNC_DOCUMENT_DETAILS."
        ),
    ),
) -> None:
    try:
        summary = link_core_documents_for_run(
            database=Database(
                get_settings()
            ),
            run_id=run_id,
        )

    except Exception as exc:
        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=1
        ) from exc

    typer.echo(
        "Привязка документов завершена."
    )

    typer.echo(
        f"run_id: {summary.run_id}"
    )

    typer.echo(
        "legal_entity_id: "
        f"{summary.legal_entity_id}"
    )

    typer.echo(
        "product_group: "
        f"{summary.product_group}"
    )

    typer.echo(
        "source_document_count: "
        f"{summary.source_document_count}"
    )

    typer.echo(
        "linked_document_count: "
        f"{summary.linked_document_count}"
    )


if __name__ == "__main__":
    app()