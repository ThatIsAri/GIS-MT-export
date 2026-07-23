from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer
from mysql.connector import MySQLConnection

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.sync_pipeline import PipelineSummary, execute_pipeline
from app.windowing import format_utc_datetime, parse_utc_datetime


@dataclass(frozen=True, slots=True)
class ProductGroupPlan:
    product_group: str
    lookback_days: int
    request_limit: int
    max_list_requests: int
    details_delay_ms: int
    batch_size: int
    edo_delay_ms: int


@dataclass(frozen=True, slots=True)
class ProductGroupFailure:
    product_group: str
    error_type: str
    error_message: str


@dataclass(frozen=True, slots=True)
class LegalEntitySyncSummary:
    legal_entity_id: int
    short_name: str
    attempted_group_count: int
    successful_group_count: int
    failed_group_count: int
    successful_groups: tuple[PipelineSummary, ...]
    failed_groups: tuple[ProductGroupFailure, ...]


def get_legal_entity_sync_plan(
    connection: MySQLConnection,
    legal_entity_id: int,
) -> tuple[dict[str, Any], list[ProductGroupPlan]]:
    if legal_entity_id < 1:
        raise ValueError(
            "legal_entity_id должен быть больше 0."
        )

    entity_cursor = connection.cursor(
        dictionary=True
    )

    try:
        entity_cursor.execute(
            """
            SELECT
                e.id,
                e.inn,
                e.short_name,
                e.status,
                e.gis_mt_is_registered,
                e.gis_mt_last_sync_status,
                config.true_api_enabled
            FROM legal_entity e

            JOIN legal_entity_integration_config config
              ON config.legal_entity_id = e.id

            WHERE e.id = %s
            LIMIT 1
            """,
            (
                legal_entity_id,
            ),
        )

        entity = entity_cursor.fetchone()

    finally:
        entity_cursor.close()

    if entity is None:
        raise ValueError(
            "Карточка организации "
            f"id={legal_entity_id} не найдена."
        )

    if str(
        entity["status"]
    ).upper() != "ACTIVE":
        raise ValueError(
            "Запуск разрешён только для карточки "
            "со статусом ACTIVE. "
            f"Текущий статус: {entity['status']}."
        )

    if not bool(
        entity["true_api_enabled"]
    ):
        raise ValueError(
            "True API отключён "
            "в настройках организации."
        )

    if not bool(
        entity["gis_mt_is_registered"]
    ):
        raise ValueError(
            "Организация не отмечена как "
            "зарегистрированная в ГИС МТ."
        )

    group_cursor = connection.cursor(
        dictionary=True
    )

    try:
        group_cursor.execute(
            """
            SELECT
                product_group,
                lookback_days,
                request_limit,
                max_list_requests,
                details_delay_ms,
                batch_size,
                edo_delay_ms
            FROM legal_entity_product_group
            WHERE legal_entity_id = %s
              AND is_enabled = 1
              AND gis_mt_available = 1
            ORDER BY product_group
            """,
            (
                legal_entity_id,
            ),
        )

        rows = list(
            group_cursor.fetchall()
        )

    finally:
        group_cursor.close()

    if not rows:
        raise ValueError(
            "Для организации нет включённых "
            "и доступных товарных групп."
        )

    plans = [
        ProductGroupPlan(
            product_group=str(
                row["product_group"]
            ),
            lookback_days=int(
                row["lookback_days"]
            ),
            request_limit=int(
                row["request_limit"]
            ),
            max_list_requests=int(
                row["max_list_requests"]
            ),
            details_delay_ms=int(
                row["details_delay_ms"]
            ),
            batch_size=int(
                row["batch_size"]
            ),
            edo_delay_ms=int(
                row["edo_delay_ms"]
            ),
        )
        for row in rows
    ]

    return (
        dict(
            entity
        ),
        plans,
    )


def resolve_date_to(
    value: str | None,
) -> datetime:
    if value is None:
        return datetime.now(
            timezone.utc
        ).replace(
            microsecond=0
        )

    return parse_utc_datetime(
        value,
        "date_to",
    )


def resolve_explicit_date_from(
    value: str | None,
    date_to: datetime,
) -> datetime | None:
    if value is None:
        return None

    date_from = parse_utc_datetime(
        value,
        "date_from",
    )

    if date_from >= date_to:
        raise ValueError(
            "date_from должен быть раньше date_to."
        )

    return date_from


def sync_legal_entity(
    *,
    token: str,
    legal_entity_id: int,
    date_from: str | None,
    date_to: str | None,
    edo_output_root: Path,
    skip_edo: bool,
    force_edo: bool,
    edo_fail_fast: bool,
    continue_on_error: bool,
    database: Database | None = None,
) -> LegalEntitySyncSummary:
    active_database = (
        database
        if database is not None
        else Database(
            get_settings()
        )
    )

    connection = active_database.connect()

    try:
        entity, plans = (
            get_legal_entity_sync_plan(
                connection,
                legal_entity_id,
            )
        )

    finally:
        connection.close()

    resolved_date_to = resolve_date_to(
        date_to
    )

    explicit_date_from = (
        resolve_explicit_date_from(
            date_from,
            resolved_date_to,
        )
    )

    successful: list[
        PipelineSummary
    ] = []

    failed: list[
        ProductGroupFailure
    ] = []

    typer.echo(
        "Запуск организации: "
        f"id={legal_entity_id}; "
        f"наименование={entity['short_name']}."
    )

    typer.echo(
        "Товарных групп в плане: "
        f"{len(plans)}."
    )

    for index, plan in enumerate(
        plans,
        start=1,
    ):
        group_date_from = (
            explicit_date_from
            if explicit_date_from is not None
            else (
                resolved_date_to
                - timedelta(
                    days=plan.lookback_days
                )
            )
        )

        formatted_date_from = (
            format_utc_datetime(
                group_date_from
            )
        )

        formatted_date_to = (
            format_utc_datetime(
                resolved_date_to
            )
        )

        typer.echo("")

        typer.echo(
            f"Группа {index}/{len(plans)}: "
            f"{plan.product_group}; "
            f"период {formatted_date_from} — "
            f"{formatted_date_to}."
        )

        try:
            summary = execute_pipeline(
                token=token,
                legal_entity_id=legal_entity_id,
                product_group=plan.product_group,
                date_from=formatted_date_from,
                date_to=formatted_date_to,
                limit=plan.request_limit,
                max_pages=(
                    plan.max_list_requests
                ),
                details_delay_ms=(
                    plan.details_delay_ms
                ),
                batch_size=plan.batch_size,
                edo_delay_ms=(
                    plan.edo_delay_ms
                ),
                edo_output_root=(
                    edo_output_root
                ),
                skip_edo=skip_edo,
                force_edo=force_edo,
                edo_fail_fast=(
                    edo_fail_fast
                ),
                database=active_database,
            )

            successful.append(
                summary
            )

        except GisMtAuthError:
            raise

        except Exception as exc:
            failure = ProductGroupFailure(
                product_group=(
                    plan.product_group
                ),
                error_type=(
                    type(exc).__name__
                ),
                error_message=str(
                    exc
                ),
            )

            failed.append(
                failure
            )

            typer.echo(
                "Ошибка товарной группы "
                f"{plan.product_group}: "
                f"{failure.error_type}: "
                f"{failure.error_message}",
                err=True,
            )

            if not continue_on_error:
                raise

    return LegalEntitySyncSummary(
        legal_entity_id=legal_entity_id,
        short_name=str(
            entity["short_name"]
        ),
        attempted_group_count=len(
            plans
        ),
        successful_group_count=len(
            successful
        ),
        failed_group_count=len(
            failed
        ),
        successful_groups=tuple(
            successful
        ),
        failed_groups=tuple(
            failed
        ),
    )


def main(
    legal_entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help=(
            "ID существующей карточки "
            "организации."
        ),
    ),
    date_from: str | None = typer.Option(
        None,
        "--date-from",
        help=(
            "Общее начало периода ISO 8601. "
            "Если не указано, для каждой группы "
            "используется lookback_days."
        ),
    ),
    date_to: str | None = typer.Option(
        None,
        "--date-to",
        help=(
            "Конец периода ISO 8601. "
            "По умолчанию — текущее время UTC."
        ),
    ),
    edo_output_root: Path = typer.Option(
        Path(
            "/data/edo_inbox/official"
        ),
        "--edo-output-root",
        file_okay=False,
        dir_okay=True,
    ),
    skip_edo: bool = typer.Option(
        False,
        "--skip-edo",
    ),
    force_edo: bool = typer.Option(
        False,
        "--force-edo",
    ),
    edo_fail_fast: bool = typer.Option(
        False,
        "--edo-fail-fast",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        help=(
            "Продолжать со следующей группой "
            "после ошибки."
        ),
    ),
) -> None:
    token = read_token_from_stdin()

    try:
        summary = sync_legal_entity(
            token=token,
            legal_entity_id=legal_entity_id,
            date_from=date_from,
            date_to=date_to,
            edo_output_root=(
                edo_output_root
            ),
            skip_edo=skip_edo,
            force_edo=force_edo,
            edo_fail_fast=(
                edo_fail_fast
            ),
            continue_on_error=(
                continue_on_error
            ),
        )

    except GisMtAuthError as exc:
        typer.echo(
            "AUTH ERROR: токен True API "
            "отклонён или истёк: "
            f"{exc}",
            err=True,
        )

        raise typer.Exit(
            code=20
        ) from exc

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

    typer.echo("")
    typer.echo(
        "Синхронизация организации завершена."
    )

    typer.echo(
        "Организация: "
        f"{summary.legal_entity_id} — "
        f"{summary.short_name}"
    )

    typer.echo(
        "Групп в плане: "
        f"{summary.attempted_group_count}"
    )

    typer.echo(
        "Успешно: "
        f"{summary.successful_group_count}"
    )

    typer.echo(
        "С ошибкой: "
        f"{summary.failed_group_count}"
    )

    if summary.failed_group_count > 0:
        for failure in summary.failed_groups:
            typer.echo(
                "  "
                f"{failure.product_group}: "
                f"{failure.error_type}: "
                f"{failure.error_message}",
                err=True,
            )

        raise typer.Exit(
            code=2
        )


if __name__ == "__main__":
    typer.run(
        main
    )