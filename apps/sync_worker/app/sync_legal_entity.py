from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from mysql.connector import MySQLConnection

from app.cli import read_token_from_stdin
from app.client import GisMtAuthError
from app.config import get_settings
from app.db import Database
from app.sales import (
    SalesSyncSummary,
    report_id_for_group,
    sync_retail_sales,
)
from app.sync_pipeline import (
    PipelineSummary,
    execute_pipeline,
)
from app.violations import (
    ViolationSyncSummary,
    sync_violations,
)
from app.windowing import (
    format_utc_datetime,
    parse_utc_datetime,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ProductGroupPlan:
    product_group: str
    product_group_code: int | None
    lookback_days: int
    request_limit: int
    max_list_requests: int
    details_delay_ms: int
    batch_size: int
    edo_delay_ms: int
    violations_enabled: bool
    violations_lookback_days: int
    violations_last_success_date: date | None
    sales_enabled: bool
    sales_lookback_days: int
    sales_last_success_date: date | None


@dataclass(
    frozen=True,
    slots=True,
)
class PipelineExecutionMode:
    pipeline_run_active: bool
    sync_documents: bool
    process_upd: bool
    sync_violations: bool


@dataclass(
    frozen=True,
    slots=True,
)
class ProductGroupFailure:
    product_group: str
    stage: str
    error_type: str
    error_message: str


@dataclass(
    frozen=True,
    slots=True,
)
class LegalEntitySyncSummary:
    legal_entity_id: int
    short_name: str
    attempted_group_count: int
    successful_group_count: int
    failed_group_count: int

    documents_enabled: bool
    process_upd_enabled: bool
    violations_enabled: bool

    successful_groups: tuple[
        PipelineSummary,
        ...,
    ]

    failed_groups: tuple[
        ProductGroupFailure,
        ...,
    ]

    violations_enabled_group_count: int
    violations_successful_group_count: int
    violations_failed_group_count: int
    violations_skipped_group_count: int
    violations_row_count: int
    violations_inserted_count: int
    violations_updated_count: int
    violations_rejected_count: int

    violation_summaries: tuple[
        ViolationSyncSummary,
        ...,
    ]

    sales_enabled_group_count: int
    sales_supported_group_count: int
    sales_successful_group_count: int
    sales_failed_group_count: int
    sales_skipped_group_count: int
    sales_remaining_day_count: int
    sales_row_count: int
    sales_inserted_count: int
    sales_rejected_count: int
    sales_total_quantity: Decimal
    sales_total_amount: Decimal

    sales_summaries: tuple[
        SalesSyncSummary,
        ...,
    ]


def get_legal_entity_sync_plan(
    connection: MySQLConnection,
    legal_entity_id: int,
) -> tuple[
    dict[str, Any],
    list[ProductGroupPlan],
]:
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
                entity.id,
                entity.inn,
                entity.short_name,
                entity.status,
                entity.gis_mt_is_registered,
                entity.gis_mt_last_sync_status,
                config.true_api_enabled

            FROM legal_entity AS entity

            JOIN legal_entity_integration_config
                 AS config
              ON config.legal_entity_id =
                 entity.id

            WHERE entity.id = %s
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

    if str(entity["status"]).upper() != "ACTIVE":
        raise ValueError(
            "Запуск разрешён только для карточки "
            "со статусом ACTIVE. Текущий статус: "
            f"{entity['status']}."
        )

    if not bool(entity["true_api_enabled"]):
        raise ValueError(
            "True API отключён в настройках организации."
        )

    if not bool(entity["gis_mt_is_registered"]):
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
                group_config.product_group,
                dictionary.product_group_code,
                group_config.lookback_days,
                group_config.request_limit,
                group_config.max_list_requests,
                group_config.details_delay_ms,
                group_config.batch_size,
                group_config.edo_delay_ms,
                group_config.violations_enabled,
                group_config.violations_lookback_days,
                group_config.violations_last_success_date,
                group_config.sales_enabled,
                group_config.sales_lookback_days,
                group_config.sales_last_success_date

            FROM legal_entity_product_group
                 AS group_config

            LEFT JOIN
                gis_mt_product_group_dictionary
                AS dictionary
              ON dictionary.product_group =
                 group_config.product_group
             AND dictionary.is_active = 1

            WHERE group_config.legal_entity_id = %s
              AND group_config.is_enabled = 1
              AND group_config.gis_mt_available = 1

            ORDER BY
                group_config.product_group
            """,
            (
                legal_entity_id,
            ),
        )

        rows = list(group_cursor.fetchall())

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
            product_group_code=(
                int(row["product_group_code"])
                if row["product_group_code"]
                is not None
                else None
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
            violations_enabled=bool(
                row["violations_enabled"]
            ),
            violations_lookback_days=int(
                row["violations_lookback_days"]
            ),
            violations_last_success_date=(
                row[
                    "violations_last_success_date"
                ]
            ),
            sales_enabled=bool(
                row["sales_enabled"]
            ),
            sales_lookback_days=int(
                row["sales_lookback_days"]
            ),
            sales_last_success_date=(
                row["sales_last_success_date"]
            ),
        )
        for row in rows
    ]

    return dict(entity), plans


def resolve_pipeline_execution_mode(
    connection: MySQLConnection,
    legal_entity_id: int,
) -> PipelineExecutionMode:
    """
    Определяет состав заданий текущего запуска панели.

    Вне активного запуска панели сохраняется прежнее
    поведение ручного запуска: документы скачиваются
    и обрабатываются, а отклонения определяются
    настройками товарных групп.
    """

    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                config.current_run_uuid,
                config.export_upd_enabled,
                config.process_upd_enabled,
                config.track_violations_enabled,

                EXISTS (
                    SELECT 1
                    FROM sys_pipeline_task_entity
                         AS export_selection
                    WHERE export_selection.task_code =
                          'EXPORT_UPD'
                      AND export_selection.legal_entity_id =
                          %s
                ) AS export_selected,

                EXISTS (
                    SELECT 1
                    FROM sys_pipeline_task_entity
                         AS process_selection
                    WHERE process_selection.task_code =
                          'PROCESS_UPD'
                      AND process_selection.legal_entity_id =
                          %s
                ) AS process_selected,

                EXISTS (
                    SELECT 1
                    FROM sys_pipeline_task_entity
                         AS violation_selection
                    WHERE violation_selection.task_code =
                          'TRACK_VIOLATIONS'
                      AND violation_selection.legal_entity_id =
                          %s
                ) AS violations_selected

            FROM sys_pipeline_config AS config
            WHERE config.id = 1
            LIMIT 1
            """,
            (
                legal_entity_id,
                legal_entity_id,
                legal_entity_id,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if row is None or not row["current_run_uuid"]:
        return PipelineExecutionMode(
            pipeline_run_active=False,
            sync_documents=True,
            process_upd=True,
            sync_violations=True,
        )

    sync_documents = bool(
        row["export_upd_enabled"]
        and row["export_selected"]
    )

    process_upd = bool(
        sync_documents
        and row["process_upd_enabled"]
        and row["process_selected"]
    )

    sync_violations = bool(
        row["track_violations_enabled"]
        and row["violations_selected"]
    )

    return PipelineExecutionMode(
        pipeline_run_active=True,
        sync_documents=sync_documents,
        process_upd=process_upd,
        sync_violations=sync_violations,
    )


DateTimeInput = datetime | str | None


def normalize_utc_datetime(
    value: DateTimeInput,
    field_name: str,
) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        prepared = value

        if prepared.tzinfo is None:
            prepared = prepared.replace(
                tzinfo=timezone.utc
            )

        return prepared.astimezone(timezone.utc)

    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} должен быть строкой ISO 8601, "
            "datetime или None."
        )

    return parse_utc_datetime(
        value,
        field_name,
    )


def resolve_date_to(value: DateTimeInput) -> datetime:
    resolved = normalize_utc_datetime(
        value,
        "date_to",
    )

    if resolved is None:
        return datetime.now(timezone.utc).replace(
            microsecond=0
        )

    return resolved


def resolve_explicit_date_from(
    value: DateTimeInput,
    date_to: datetime,
) -> datetime | None:
    date_from = normalize_utc_datetime(
        value,
        "date_from",
    )

    if date_from is not None and date_from >= date_to:
        raise ValueError(
            "date_from должен быть раньше date_to."
        )

    return date_from


def sync_legal_entity(
    *,
    token: str,
    legal_entity_id: int,
    date_from: DateTimeInput,
    date_to: DateTimeInput,
    edo_output_root: Path = Path(
        "/data/official"
    ),
    skip_edo: bool,
    force_edo: bool,
    edo_fail_fast: bool,
    continue_on_error: bool,
    execution_mode: PipelineExecutionMode | None = None,
    database: Database | None = None,
) -> LegalEntitySyncSummary:
    active_database = (
        database
        or Database(get_settings())
    )

    connection = active_database.connect()

    try:
        entity, plans = get_legal_entity_sync_plan(
            connection,
            legal_entity_id,
        )

        if execution_mode is None:
            execution_mode = (
                resolve_pipeline_execution_mode(
                    connection,
                    legal_entity_id,
                )
            )

    finally:
        connection.close()

    resolved_date_to = resolve_date_to(date_to)

    explicit_date_from = (
        resolve_explicit_date_from(
            date_from,
            resolved_date_to,
        )
    )

    successful_document_groups: list[
        PipelineSummary
    ] = []

    failed: list[ProductGroupFailure] = []

    violation_summaries: list[
        ViolationSyncSummary
    ] = []

    sales_summaries: list[
        SalesSyncSummary
    ] = []

    successful_group_count = 0

    violations_enabled_group_count = sum(
        1
        for plan in plans
        if (
            execution_mode.sync_violations
            and plan.violations_enabled
        )
    )

    violations_successful_group_count = 0
    violations_failed_group_count = 0
    violations_skipped_group_count = 0
    violations_row_count = 0
    violations_inserted_count = 0
    violations_updated_count = 0
    violations_rejected_count = 0

    sales_enabled_group_count = sum(
        1
        for plan in plans
        if (
            execution_mode.sync_violations
            and plan.sales_enabled
        )
    )
    sales_supported_group_count = sum(
        1
        for plan in plans
        if (
            execution_mode.sync_violations
            and plan.sales_enabled
            and plan.product_group_code is not None
            and report_id_for_group(
                plan.product_group_code
            ) is not None
        )
    )
    sales_successful_group_count = 0
    sales_failed_group_count = 0
    sales_skipped_group_count = 0
    sales_remaining_day_count = 0
    sales_row_count = 0
    sales_inserted_count = 0
    sales_rejected_count = 0
    sales_total_quantity = Decimal("0")
    sales_total_amount = Decimal("0")

    typer.echo(
        "Запуск организации: "
        f"id={legal_entity_id}; "
        f"наименование={entity['short_name']}."
    )

    typer.echo(
        "Товарных групп в плане: "
        f"{len(plans)}."
    )

    typer.echo(
        "Состав запуска: "
        "экспорт УПД="
        + (
            "да"
            if execution_mode.sync_documents
            else "нет"
        )
        + "; обработка УПД="
        + (
            "да"
            if execution_mode.process_upd
            else "нет"
        )
        + "; отклонения и продажи="
        + (
            "да"
            if execution_mode.sync_violations
            else "нет"
        )
        + "."
    )

    if (
        not execution_mode.sync_documents
        and not execution_mode.sync_violations
    ):
        raise ValueError(
            "Для организации не выбрано ни одного "
            "задания после авторизации."
        )

    for index, plan in enumerate(plans, start=1):
        group_date_from = (
            explicit_date_from
            or (
                resolved_date_to
                - timedelta(days=plan.lookback_days)
            )
        )

        formatted_date_from = format_utc_datetime(
            group_date_from
        )

        formatted_date_to = format_utc_datetime(
            resolved_date_to
        )

        typer.echo("")
        typer.echo(
            f"Группа {index}/{len(plans)}: "
            f"{plan.product_group}; "
            f"период {formatted_date_from} — "
            f"{formatted_date_to}."
        )

        stage = "DOCUMENTS"

        try:
            if execution_mode.sync_documents:
                pipeline_summary = execute_pipeline(
                    token=token,
                    legal_entity_id=legal_entity_id,
                    product_group=plan.product_group,
                    date_from=formatted_date_from,
                    date_to=formatted_date_to,
                    limit=plan.request_limit,
                    max_pages=plan.max_list_requests,
                    details_delay_ms=(
                        plan.details_delay_ms
                    ),
                    batch_size=plan.batch_size,
                    edo_delay_ms=plan.edo_delay_ms,
                    edo_output_root=edo_output_root,
                    skip_edo=skip_edo,
                    force_edo=force_edo,
                    edo_fail_fast=edo_fail_fast,
                    process_upd=(
                        execution_mode.process_upd
                    ),
                    database=active_database,
                )

                successful_document_groups.append(
                    pipeline_summary
                )

            if (
                execution_mode.sync_violations
                and plan.violations_enabled
            ):
                stage = "VIOLATIONS"

                if plan.product_group_code is None:
                    raise ValueError(
                        "Для товарной группы "
                        f"{plan.product_group} не найден "
                        "цифровой код ГИС МТ."
                    )

                violation_period_to = (
                    resolved_date_to.date()
                )

                already_loaded_today = (
                    explicit_date_from is None
                    and plan.violations_last_success_date
                    is not None
                    and plan.violations_last_success_date
                    >= violation_period_to
                )

                if already_loaded_today:
                    violations_skipped_group_count += 1

                    typer.echo(
                        "Отклонения за текущую дату "
                        "уже выгружены; повторное "
                        "задание не создаётся."
                    )
                else:
                    violation_period_from = (
                        explicit_date_from.date()
                        if explicit_date_from is not None
                        else (
                            violation_period_to
                            - timedelta(
                                days=max(
                                    0,
                                    plan.violations_lookback_days
                                    - 1,
                                )
                            )
                        )
                    )

                    violation_summary = asyncio.run(
                        sync_violations(
                            token=token,
                            legal_entity_id=(
                                legal_entity_id
                            ),
                            product_group=(
                                plan.product_group
                            ),
                            product_group_code=(
                                plan.product_group_code
                            ),
                            period_from=(
                                violation_period_from
                            ),
                            period_to=(
                                violation_period_to
                            ),
                            database=active_database,
                        )
                    )

                    violation_summaries.append(
                        violation_summary
                    )

                    violations_successful_group_count += 1
                    violations_row_count += (
                        violation_summary.row_count
                    )
                    violations_inserted_count += (
                        violation_summary.inserted_count
                    )
                    violations_updated_count += (
                        violation_summary.updated_count
                    )
                    violations_rejected_count += (
                        violation_summary.rejected_count
                    )

            if (
                execution_mode.sync_violations
                and plan.sales_enabled
            ):
                stage = "SALES"

                if plan.product_group_code is None:
                    raise ValueError(
                        "Для товарной группы "
                        f"{plan.product_group} не найден "
                        "цифровой код ГИС МТ."
                    )

                sales_period_to = resolved_date_to.date()
                sales_period_from = (
                    explicit_date_from.date()
                    if explicit_date_from is not None
                    else (
                        sales_period_to
                        - timedelta(
                            days=max(
                                0,
                                plan.sales_lookback_days - 1,
                            )
                        )
                    )
                )

                sales_summary = asyncio.run(
                    sync_retail_sales(
                        token=token,
                        legal_entity_id=legal_entity_id,
                        product_group=plan.product_group,
                        product_group_code=(
                            plan.product_group_code
                        ),
                        period_from=sales_period_from,
                        period_to=sales_period_to,
                        database=active_database,
                    )
                )

                sales_summaries.append(
                    sales_summary
                )

                if sales_summary.supported:
                    sales_successful_group_count += 1
                    sales_remaining_day_count += (
                        sales_summary.remaining_day_count
                    )
                    sales_row_count += (
                        sales_summary.row_count
                    )
                    sales_inserted_count += (
                        sales_summary.inserted_count
                    )
                    sales_rejected_count += (
                        sales_summary.rejected_count
                    )
                    sales_total_quantity += (
                        sales_summary.total_quantity
                    )
                    sales_total_amount += (
                        sales_summary.total_amount
                    )
                else:
                    sales_skipped_group_count += 1

            successful_group_count += 1

        except GisMtAuthError:
            raise

        except Exception as exc:
            if stage == "VIOLATIONS":
                violations_failed_group_count += 1
            elif stage == "SALES":
                sales_failed_group_count += 1

            failure = ProductGroupFailure(
                product_group=plan.product_group,
                stage=stage,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )

            failed.append(failure)

            typer.echo(
                "Ошибка товарной группы "
                f"{plan.product_group}; "
                f"этап={failure.stage}: "
                f"{failure.error_type}: "
                f"{failure.error_message}",
                err=True,
            )

            if not continue_on_error:
                raise

    return LegalEntitySyncSummary(
        legal_entity_id=legal_entity_id,
        short_name=str(entity["short_name"]),
        attempted_group_count=len(plans),
        successful_group_count=successful_group_count,
        failed_group_count=len(failed),
        documents_enabled=(
            execution_mode.sync_documents
        ),
        process_upd_enabled=(
            execution_mode.process_upd
        ),
        violations_enabled=(
            execution_mode.sync_violations
        ),
        successful_groups=tuple(
            successful_document_groups
        ),
        failed_groups=tuple(failed),
        violations_enabled_group_count=(
            violations_enabled_group_count
        ),
        violations_successful_group_count=(
            violations_successful_group_count
        ),
        violations_failed_group_count=(
            violations_failed_group_count
        ),
        violations_skipped_group_count=(
            violations_skipped_group_count
        ),
        violations_row_count=violations_row_count,
        violations_inserted_count=(
            violations_inserted_count
        ),
        violations_updated_count=(
            violations_updated_count
        ),
        violations_rejected_count=(
            violations_rejected_count
        ),
        violation_summaries=tuple(
            violation_summaries
        ),
        sales_enabled_group_count=(
            sales_enabled_group_count
        ),
        sales_supported_group_count=(
            sales_supported_group_count
        ),
        sales_successful_group_count=(
            sales_successful_group_count
        ),
        sales_failed_group_count=(
            sales_failed_group_count
        ),
        sales_skipped_group_count=(
            sales_skipped_group_count
        ),
        sales_remaining_day_count=(
            sales_remaining_day_count
        ),
        sales_row_count=sales_row_count,
        sales_inserted_count=(
            sales_inserted_count
        ),
        sales_rejected_count=(
            sales_rejected_count
        ),
        sales_total_quantity=(
            sales_total_quantity
        ),
        sales_total_amount=(
            sales_total_amount
        ),
        sales_summaries=tuple(
            sales_summaries
        ),
    )


def main(
    legal_entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
        help=(
            "ID существующей карточки организации."
        ),
    ),
    date_from: str | None = typer.Option(
        None,
        "--date-from",
        help=(
            "Общее начало периода ISO 8601. "
            "Без параметра используются lookback_days, "
            "violations_lookback_days и sales_lookback_days."
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
        Path("/data/official"),
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
            "Продолжать со следующей товарной "
            "группой после ошибки."
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
            edo_output_root=edo_output_root,
            skip_edo=skip_edo,
            force_edo=force_edo,
            edo_fail_fast=edo_fail_fast,
            continue_on_error=continue_on_error,
        )

    except GisMtAuthError as exc:
        typer.echo(
            "AUTH ERROR: токен True API "
            f"отклонён или истёк: {exc}",
            err=True,
        )

        raise typer.Exit(code=20) from exc

    except Exception as exc:
        typer.echo(
            "ERROR: "
            f"{type(exc).__name__}: {exc}",
            err=True,
        )

        raise typer.Exit(code=1) from exc

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
    typer.echo(
        "Экспорт УПД: "
        + (
            "включён"
            if summary.documents_enabled
            else "отключён"
        )
    )
    typer.echo(
        "Обработка УПД: "
        + (
            "включена"
            if summary.process_upd_enabled
            else "отключена"
        )
    )
    typer.echo(
        "Отслеживание отклонений: "
        + (
            "включено"
            if summary.violations_enabled
            else "отключено"
        )
    )
    typer.echo(
        "Групп с выгрузкой отклонений: "
        f"{summary.violations_enabled_group_count}"
    )
    typer.echo(
        "Выгрузка отклонений успешна: "
        f"{summary.violations_successful_group_count}"
    )
    typer.echo(
        "Выгрузка отклонений с ошибкой: "
        f"{summary.violations_failed_group_count}"
    )
    typer.echo(
        "Повторная выгрузка отклонений пропущена: "
        f"{summary.violations_skipped_group_count}"
    )
    typer.echo(
        "Строк отклонений: "
        f"{summary.violations_row_count}"
    )
    typer.echo(
        "Новых отклонений: "
        f"{summary.violations_inserted_count}"
    )
    typer.echo(
        "Обновлено отклонений: "
        f"{summary.violations_updated_count}"
    )
    typer.echo(
        "Отклонено строк при импорте: "
        f"{summary.violations_rejected_count}"
    )
    typer.echo(
        "Групп с выгрузкой корректных продаж: "
        f"{summary.sales_enabled_group_count}"
    )
    typer.echo(
        "Поддерживаемых групп продаж: "
        f"{summary.sales_supported_group_count}"
    )
    typer.echo(
        "Выгрузка продаж успешна: "
        f"{summary.sales_successful_group_count}"
    )
    typer.echo(
        "Выгрузка продаж с ошибкой: "
        f"{summary.sales_failed_group_count}"
    )
    typer.echo(
        "Неподдерживаемых групп продаж пропущено: "
        f"{summary.sales_skipped_group_count}"
    )
    typer.echo(
        "Дней продаж осталось догрузить: "
        f"{summary.sales_remaining_day_count}"
    )
    typer.echo(
        "Строк продаж: "
        f"{summary.sales_row_count}"
    )
    typer.echo(
        "Импортировано строк продаж: "
        f"{summary.sales_inserted_count}"
    )
    typer.echo(
        "Отклонено строк продаж: "
        f"{summary.sales_rejected_count}"
    )
    typer.echo(
        "Продажи без ошибок, шт.: "
        f"{summary.sales_total_quantity}"
    )

    if summary.failed_group_count > 0:
        for failure in summary.failed_groups:
            typer.echo(
                "  "
                f"{failure.product_group}; "
                f"этап={failure.stage}: "
                f"{failure.error_type}: "
                f"{failure.error_message}",
                err=True,
            )

        raise typer.Exit(code=2)


if __name__ == "__main__":
    typer.run(main)
