from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import typer

from app.client import GisMtError
from app.config import Settings, get_settings
from app.db import Database
from app.violations import (
    TERMINAL_TASK_FAILURES,
    ViolationExportClient,
    archive_csv_files,
    clean_text,
    decode_csv,
    delimiter,
    identifier,
    normalize_header,
    parse_decimal,
    parse_gtin,
    parse_inn,
    result_item,
    task_status,
)


REPORT_ID_COUNTABLE = (
    "gismt-participant-withdrawal-circulation-c"
)
REPORT_ID_MIXED = (
    "gismt-participant-withdrawal-circulation-cw"
)

# Коды товарных групп из справочника проекта, для которых
# официальный отчёт доступен. Для смешанных/весовых групп
# используется вариант отчёта с суффиксом cw.
COUNTABLE_PRODUCT_GROUP_CODES = {
    1,   # Лёгкая промышленность
    2,   # Обувные товары
    5,   # Шины
    6,   # Фотокамеры
    9,   # Велосипеды
    10,  # Медицинские изделия
    14,  # Товары из натурального меха
    17,  # БАД
    26,  # Ветеринарные препараты
    27,  # Игры и игрушки
    28,  # Радиоэлектронная продукция
    44,  # Полимерные трубы
    48,  # Автозапчасти
    49,  # Натуральный мех
    50,  # Электронные системы доставки никотина
    51,  # Ноутбуки и смартфоны
    54,  # Товары для дома и интерьера
}

MIXED_PRODUCT_GROUP_CODES = {
    3,   # Табачная продукция
    4,   # Духи и туалетная вода
    8,   # Молочная продукция
    12,  # Альтернативная табачная продукция
    13,  # Упакованная вода
    15,  # Пиво и слабоалкогольные напитки
    16,  # Никотиносодержащая продукция
    19,  # Антисептики
    20,  # Корма для животных
    21,  # Морепродукты
    22,  # Безалкогольное пиво
    23,  # Соки и безалкогольные напитки
    25,  # Мясные изделия
    32,  # Консервированная продукция
    33,  # Растительные масла
    35,  # Косметика и бытовая химия
    37,  # Бакалея
    43,  # Моторные масла
    53,  # Удобрения
}

SUPPORTED_PRODUCT_GROUP_CODES = (
    COUNTABLE_PRODUCT_GROUP_CODES
    | MIXED_PRODUCT_GROUP_CODES
)

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "participant_inn": (
        "ИНН",
        "ИНН участника",
    ),
    "participant_name": (
        "Наименование УОТ",
        "Наименование участника оборота товаров",
        "Наименование участника",
    ),
    "gtin": (
        "Код товара",
        "GTIN",
    ),
    "tnved": (
        "ТН ВЭД",
        "Код ТН ВЭД",
    ),
    "okpd2": (
        "ОКПД2",
        "Код ОКПД2",
    ),
    "package_type": (
        "Тип упаковки",
    ),
    "product_type": (
        "Вид товара",
    ),
    "manufacturer": (
        "Производитель",
    ),
    "package_quantity": (
        "Кол-во единиц в упаковке/объем упаковки",
        "Кол-во единиц в упаковке/объём упаковки",
        "Количество единиц в упаковке/объем упаковки",
        "Количество единиц в упаковке/объём упаковки",
    ),
    "package_unit": (
        "Единицы измерения кол-ва/объема упаковки",
        "Единицы измерения кол-ва/объёма упаковки",
        "Единицы измерения количества/объема упаковки",
        "Единицы измерения количества/объёма упаковки",
    ),
    "product_name": (
        "Наименование товара",
    ),
    "withdrawal_reason": (
        "Причина вывода из оборота",
    ),
    "turnover_reason": (
        "Группа причин вывода из оборота",
        "Основание для вывода из оборота",
    ),
    "region_name": (
        "Регион точки продаж",
        "Регион точки продажи",
    ),
    "sales_point_address": (
        "Адрес точки продаж",
        "Адрес точки продажи",
    ),
    "sold_quantity": (
        "Количество выведенных из оборота товаров, шт.",
        "Количество выведенных из оборота товаров, шт",
        "Количество проданных товаров, шт.",
        "Количество проданных товаров, шт",
    ),
    "sold_amount": (
        "Стоимость выведенных из оборота товаров, руб.",
        "Стоимость выведенных из оборота товаров, руб",
        "Стоимость проданных товаров, руб.",
        "Стоимость проданных товаров, руб",
    ),
}

TEXT_LIMITS = {
    "participant_name": 512,
    "tnved": 32,
    "okpd2": 64,
    "package_type": 128,
    "product_type": 512,
    "manufacturer": 1000,
    "package_unit": 128,
    "product_name": 1000,
    "withdrawal_reason": 512,
    "turnover_reason": 512,
    "region_name": 512,
    "sales_point_address": 2000,
}

SALE_COLUMNS = (
    "participant_inn",
    "participant_name",
    "gtin",
    "tnved",
    "okpd2",
    "package_type",
    "product_type",
    "manufacturer",
    "package_quantity",
    "package_unit",
    "product_name",
    "withdrawal_reason",
    "turnover_reason",
    "region_name",
    "sales_point_address",
    "sold_quantity",
    "sold_amount",
    "raw_row_json",
)


@dataclass(frozen=True, slots=True)
class SalesSyncSettings:
    archive_root: Path
    task_poll_seconds: float
    result_poll_seconds: float
    timeout_seconds: int
    max_new_days_per_run: int


@dataclass(frozen=True, slots=True)
class SalesDaySummary:
    export_run_id: int
    sale_date: date
    task_id: str
    result_id: str
    csv_file_count: int
    row_count: int
    inserted_count: int
    rejected_count: int
    total_quantity: Decimal
    total_amount: Decimal
    archive_path: str


@dataclass(frozen=True, slots=True)
class SalesSyncSummary:
    legal_entity_id: int
    product_group: str
    product_group_code: int
    period_from: date
    period_to: date
    supported: bool
    requested_day_count: int
    processed_day_count: int
    already_loaded_day_count: int
    remaining_day_count: int
    row_count: int
    inserted_count: int
    rejected_count: int
    total_quantity: Decimal
    total_amount: Decimal
    days: tuple[SalesDaySummary, ...]


def load_sync_settings() -> SalesSyncSettings:
    timeout = int(
        os.getenv(
            "SALES_TASK_TIMEOUT_SECONDS",
            os.getenv(
                "VIOLATIONS_TASK_TIMEOUT_SECONDS",
                "1800",
            ),
        )
    )

    if timeout < 60:
        raise ValueError(
            "SALES_TASK_TIMEOUT_SECONDS должен быть не меньше 60."
        )

    max_days = int(
        os.getenv(
            "SALES_MAX_NEW_DAYS_PER_RUN",
            "10",
        )
    )

    if not 1 <= max_days <= 10:
        raise ValueError(
            "SALES_MAX_NEW_DAYS_PER_RUN должен быть от 1 до 10."
        )

    return SalesSyncSettings(
        archive_root=Path(
            os.getenv(
                "SALES_ARCHIVE_ROOT",
                "/data/edo_inbox/sales",
            )
        ),
        task_poll_seconds=max(
            12.0,
            float(
                os.getenv(
                    "SALES_TASK_POLL_SECONDS",
                    os.getenv(
                        "VIOLATIONS_TASK_POLL_SECONDS",
                        "15",
                    ),
                )
            ),
        ),
        result_poll_seconds=max(
            5.0,
            float(
                os.getenv(
                    "SALES_RESULT_POLL_SECONDS",
                    os.getenv(
                        "VIOLATIONS_RESULT_POLL_SECONDS",
                        "6",
                    ),
                )
            ),
        ),
        timeout_seconds=timeout,
        max_new_days_per_run=max_days,
    )


def report_id_for_group(product_group_code: int) -> str | None:
    if product_group_code in MIXED_PRODUCT_GROUP_CODES:
        return REPORT_ID_MIXED

    if product_group_code in COUNTABLE_PRODUCT_GROUP_CODES:
        return REPORT_ID_COUNTABLE

    return None


def header_lookup(fieldnames: Iterable[str | None]) -> dict[str, str]:
    return {
        normalize_header(name): name
        for name in fieldnames
        if name and normalize_header(name)
    }


def read_field(
    row: dict[str, Any],
    lookup: dict[str, str],
    logical_name: str,
) -> str | None:
    for alias in HEADER_ALIASES[logical_name]:
        source = lookup.get(normalize_header(alias))

        if source is not None:
            return clean_text(row.get(source), 4000)

    return None


def sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def parse_row(
    row: dict[str, Any],
    lookup: dict[str, str],
    legal_entity_id: int,
    product_group_code: int,
    sale_date: date,
) -> tuple[str, dict[str, Any]]:
    values = {
        name: read_field(
            row,
            lookup,
            name,
        )
        for name in HEADER_ALIASES
    }

    values["participant_inn"] = parse_inn(
        values["participant_inn"]
    )
    values["gtin"] = parse_gtin(
        values["gtin"]
    )

    for name, limit in TEXT_LIMITS.items():
        values[name] = clean_text(
            values[name],
            limit,
        )

    values["package_quantity"] = parse_decimal(
        values["package_quantity"]
    )
    values["sold_quantity"] = parse_decimal(
        values["sold_quantity"]
    )
    values["sold_amount"] = parse_decimal(
        values["sold_amount"]
    )

    if values["sold_quantity"] is None:
        raise ValueError(
            "Строка не содержит количество проданных товаров."
        )

    if values["sold_quantity"] < 0:
        raise ValueError(
            "Количество проданных товаров не может быть отрицательным."
        )

    values["raw_row_json"] = json.dumps(
        {
            str(key): "" if value is None else str(value)
            for key, value in row.items()
            if key
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    identity = {
        "legal_entity_id": legal_entity_id,
        "product_group_code": product_group_code,
        "sale_date": sale_date.isoformat(),
        "participant_inn": values["participant_inn"],
        "participant_name": values["participant_name"],
        "gtin": values["gtin"],
        "tnved": values["tnved"],
        "okpd2": values["okpd2"],
        "package_type": values["package_type"],
        "product_type": values["product_type"],
        "manufacturer": values["manufacturer"],
        "package_quantity": (
            str(values["package_quantity"])
            if values["package_quantity"] is not None
            else None
        ),
        "package_unit": values["package_unit"],
        "product_name": values["product_name"],
        "withdrawal_reason": values["withdrawal_reason"],
        "turnover_reason": values["turnover_reason"],
        "region_name": values["region_name"],
        "sales_point_address": values["sales_point_address"],
    }

    key = sha256_text(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    return key, values


class SalesExportClient(ViolationExportClient):
    async def create_sales_task(
        self,
        group_code: int,
        report_id: str,
        sale_date: date,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        report_params = {
            "0202_IC_Date_From": sale_date.isoformat(),
            "0203_IC_Date_To": sale_date.isoformat(),
            "1250_IC_Product_Reason_withdrawal": [
                "Розничная продажа"
            ],
            "1251_IC_Product_Reason_turnover": "Чек",
        }

        body = {
            "name": (
                "Розничные продажи "
                f"{sale_date.strftime('%d.%m.%Y')}"
            ),
            "taskTypeShortName": "REPORT",
            "format": "CSV",
            "periodicity": "SINGLE",
            "reportId": report_id,
            "productGroupCode": group_code,
            "params": json.dumps(
                report_params,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }

        return body, await self.json_request(
            "POST",
            "/dispenser/tasks",
            json=body,
        )


async def wait_sales_task(
    client: SalesExportClient,
    task_id: str,
    group_code: int,
    poll: float,
    timeout: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout

    while True:
        payload = await client.task(
            task_id,
            group_code,
        )
        status = task_status(payload)

        if status == "COMPLETED":
            return payload

        if status in TERMINAL_TASK_FAILURES:
            raise GisMtError(
                "Задание выгрузки продаж завершилось "
                f"со статусом {status}."
            )

        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Истёк таймаут ожидания задания выгрузки продаж."
            )

        await asyncio.sleep(poll)


async def wait_sales_result(
    client: SalesExportClient,
    task_id: str,
    group_code: int,
    poll: float,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout

    while True:
        payload = await client.results(
            task_id,
            group_code,
        )
        item = result_item(
            payload,
            task_id,
        )

        if item:
            status = str(
                item.get("downloadStatus") or ""
            ).upper()
            available = str(
                item.get("available") or ""
            ).upper()

            if status == "FAILED":
                raise GisMtError(
                    str(
                        item.get("fullErrorMessage")
                        or item.get("errorMessage")
                        or item
                    )
                )

            if status == "SUCCESS" and available in {
                "",
                "AVAILABLE",
            }:
                return payload, item

        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Истёк таймаут ожидания файла продаж."
            )

        await asyncio.sleep(poll)


def create_run(
    database: Database,
    entity_id: int,
    product_group: str,
    group_code: int,
    report_id: str,
    sale_date: date,
) -> int:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO sales_export_run (
                    run_uuid,
                    legal_entity_id,
                    product_group,
                    product_group_code,
                    report_id,
                    period_from,
                    period_to,
                    status,
                    started_at,
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
                    'NEW',
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    str(uuid4()),
                    entity_id,
                    product_group,
                    group_code,
                    report_id,
                    sale_date,
                    sale_date,
                ),
            )

            return int(cursor.lastrowid)

        finally:
            cursor.close()


def update_run(
    database: Database,
    run_id: int,
    **values: Any,
) -> None:
    json_fields = {
        "request_json",
        "task_response_json",
        "result_response_json",
    }
    assignments: list[str] = []
    params: list[Any] = []

    for name, value in values.items():
        assignments.append(f"{name} = %s")
        params.append(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if name in json_fields and value is not None
            else value
        )

    assignments.append("updated_at = UTC_TIMESTAMP(6)")
    params.append(run_id)

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "UPDATE sales_export_run SET "
                + ", ".join(assignments)
                + " WHERE id = %s",
                tuple(params),
            )

        finally:
            cursor.close()


def mark_group(
    database: Database,
    entity_id: int,
    product_group: str,
    status: str,
    success_date: date | None,
    error: str | None,
) -> None:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                UPDATE legal_entity_product_group

                   SET sales_last_success_date =
                       CASE
                           WHEN %s = 'SUCCESS'
                           THEN GREATEST(
                               COALESCE(
                                   sales_last_success_date,
                                   '1000-01-01'
                               ),
                               %s
                           )
                           ELSE sales_last_success_date
                       END,

                       sales_last_sync_at = UTC_TIMESTAMP(6),
                       sales_last_sync_status = %s,
                       sales_last_error = %s,
                       updated_at = UTC_TIMESTAMP(6)

                 WHERE legal_entity_id = %s
                   AND product_group = %s
                """,
                (
                    status,
                    success_date,
                    status,
                    error,
                    entity_id,
                    product_group,
                ),
            )

        finally:
            cursor.close()


def save_archive(
    root: Path,
    entity_id: int,
    product_group: str,
    sale_date: date,
    task_id: str,
    content: bytes,
) -> tuple[Path, str]:
    def safe(value: str) -> str:
        return re.sub(
            r"[^0-9A-Za-zА-Яа-я._-]+",
            "_",
            value,
        ).strip("._-")

    directory = (
        root
        / str(entity_id)
        / safe(product_group)
        / sale_date.isoformat()
    )
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = directory / f"{safe(task_id)}.zip"
    temporary = path.with_suffix(".zip.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)

    return path, hashlib.sha256(content).hexdigest()


def import_archive(
    database: Database,
    content: bytes,
    run_id: int,
    entity_id: int,
    product_group: str,
    group_code: int,
    sale_date: date,
) -> tuple[
    int,
    int,
    int,
    int,
    Decimal,
    Decimal,
]:
    files = 0
    rows = 0
    inserted = 0
    rejected = 0
    total_quantity = Decimal("0")
    total_amount = Decimal("0")

    connection = database.connect()

    try:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                DELETE FROM gis_mt_retail_sale_daily
                WHERE legal_entity_id = %s
                  AND product_group = %s
                  AND sale_date = %s
                """,
                (
                    entity_id,
                    product_group,
                    sale_date,
                ),
            )

            for file_name, csv_content in archive_csv_files(content):
                files += 1
                text = decode_csv(csv_content)
                reader = csv.DictReader(
                    io.StringIO(text),
                    delimiter=delimiter(text),
                )
                lookup = header_lookup(
                    reader.fieldnames or []
                )

                if not lookup:
                    raise ValueError(
                        f"CSV {file_name!r} не содержит заголовков."
                    )

                for row_number, row in enumerate(reader, start=2):
                    if not any(
                        str(value or "").strip()
                        for value in row.values()
                    ):
                        continue

                    rows += 1

                    try:
                        key, values = parse_row(
                            row,
                            lookup,
                            entity_id,
                            group_code,
                            sale_date,
                        )

                        columns = ", ".join(SALE_COLUMNS)
                        placeholders = ", ".join(
                            ["%s"] * len(SALE_COLUMNS)
                        )
                        column_values = [
                            values[name]
                            for name in SALE_COLUMNS
                        ]

                        cursor.execute(
                            f"""
                            INSERT INTO gis_mt_retail_sale_daily (
                                sale_key_sha256,
                                legal_entity_id,
                                product_group,
                                product_group_code,
                                sale_date,
                                source_run_id,
                                {columns},
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
                                {placeholders},
                                UTC_TIMESTAMP(6),
                                UTC_TIMESTAMP(6)
                            )
                            ON DUPLICATE KEY UPDATE
                                source_run_id = VALUES(source_run_id),
                                sold_quantity =
                                    sold_quantity
                                    + VALUES(sold_quantity),
                                sold_amount =
                                    COALESCE(sold_amount, 0)
                                    + COALESCE(VALUES(sold_amount), 0),
                                raw_row_json = VALUES(raw_row_json),
                                updated_at = UTC_TIMESTAMP(6)
                            """,
                            (
                                key,
                                entity_id,
                                product_group,
                                group_code,
                                sale_date,
                                run_id,
                                *column_values,
                            ),
                        )

                        inserted += 1
                        total_quantity += values["sold_quantity"]

                        if values["sold_amount"] is not None:
                            total_amount += values["sold_amount"]

                    except Exception as exc:
                        rejected += 1
                        cursor.execute(
                            """
                            INSERT INTO sales_import_reject (
                                export_run_id,
                                csv_file_name,
                                source_row_number,
                                error_message,
                                raw_row_json,
                                created_at
                            )
                            VALUES (
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                UTC_TIMESTAMP(6)
                            )
                            """,
                            (
                                run_id,
                                file_name[:512],
                                row_number,
                                (
                                    f"{type(exc).__name__}: {exc}"
                                )[:4000],
                                json.dumps(
                                    row,
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            ),
                        )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()

    finally:
        connection.close()

    return (
        files,
        rows,
        inserted,
        rejected,
        total_quantity,
        total_amount,
    )


def loaded_dates(
    database: Database,
    entity_id: int,
    product_group: str,
    period_from: date,
    period_to: date,
) -> set[date]:
    connection = database.connect()

    try:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT period_from
                FROM sales_export_run
                WHERE legal_entity_id = %s
                  AND product_group = %s
                  AND period_from = period_to
                  AND period_from >= %s
                  AND period_from <= %s
                  AND status IN (
                      'COMPLETED',
                      'EMPTY'
                  )
                GROUP BY period_from
                """,
                (
                    entity_id,
                    product_group,
                    period_from,
                    period_to,
                ),
            )

            return {
                row[0]
                for row in cursor.fetchall()
            }

        finally:
            cursor.close()

    finally:
        connection.close()


def requested_dates(
    period_from: date,
    period_to: date,
) -> tuple[date, ...]:
    if period_from > period_to:
        raise ValueError(
            "Дата начала периода позже даты окончания."
        )

    result: list[date] = []
    current = period_from

    while current <= period_to:
        result.append(current)
        current += timedelta(days=1)

    return tuple(result)


async def sync_day(
    client: SalesExportClient,
    database: Database,
    settings: SalesSyncSettings,
    entity_id: int,
    product_group: str,
    group_code: int,
    report_id: str,
    sale_date: date,
) -> SalesDaySummary:
    run_id = create_run(
        database,
        entity_id,
        product_group,
        group_code,
        report_id,
        sale_date,
    )

    try:
        request_body, create_payload = await client.create_sales_task(
            group_code,
            report_id,
            sale_date,
        )
        task_id = identifier(
            create_payload,
            "id",
            "taskId",
        )

        update_run(
            database,
            run_id,
            task_id=task_id,
            status="TASK_CREATED",
            request_json=request_body,
            task_response_json=create_payload,
        )

        task_payload = await wait_sales_task(
            client,
            task_id,
            group_code,
            settings.task_poll_seconds,
            settings.timeout_seconds,
        )

        update_run(
            database,
            run_id,
            status="WAITING_RESULT",
            task_status=task_status(task_payload),
            task_response_json=task_payload,
        )

        result_payload, item = await wait_sales_result(
            client,
            task_id,
            group_code,
            settings.result_poll_seconds,
            settings.timeout_seconds,
        )
        result_id = identifier(
            item,
            "id",
            "resultId",
        )
        content = await client.download(
            result_id,
            group_code,
        )
        archive_path, archive_hash = save_archive(
            settings.archive_root,
            entity_id,
            product_group,
            sale_date,
            task_id,
            content,
        )

        update_run(
            database,
            run_id,
            result_id=result_id,
            status="DOWNLOADED",
            download_status=str(
                item.get("downloadStatus") or "SUCCESS"
            )[:32],
            result_response_json=result_payload,
            archive_path=str(archive_path),
            archive_sha256=archive_hash,
            archive_size=len(content),
        )

        (
            files,
            rows,
            inserted,
            rejected,
            total_quantity,
            total_amount,
        ) = import_archive(
            database,
            content,
            run_id,
            entity_id,
            product_group,
            group_code,
            sale_date,
        )

        update_run(
            database,
            run_id,
            status="EMPTY" if rows == 0 else "COMPLETED",
            csv_file_count=files,
            row_count=rows,
            inserted_count=inserted,
            rejected_count=rejected,
            total_quantity=total_quantity,
            total_amount=total_amount,
            finished_at=datetime.now(
                timezone.utc
            ).replace(tzinfo=None),
            error_message=None,
        )

        return SalesDaySummary(
            export_run_id=run_id,
            sale_date=sale_date,
            task_id=task_id,
            result_id=result_id,
            csv_file_count=files,
            row_count=rows,
            inserted_count=inserted,
            rejected_count=rejected,
            total_quantity=total_quantity,
            total_amount=total_amount,
            archive_path=str(archive_path),
        )

    except Exception as exc:
        update_run(
            database,
            run_id,
            status="FAILED",
            finished_at=datetime.now(
                timezone.utc
            ).replace(tzinfo=None),
            error_message=(
                f"{type(exc).__name__}: {exc}"
            )[:4000],
        )
        raise


async def sync_retail_sales(
    *,
    token: str,
    legal_entity_id: int,
    product_group: str,
    product_group_code: int,
    period_from: date,
    period_to: date,
    database: Database | None = None,
) -> SalesSyncSummary:
    if legal_entity_id < 1 or product_group_code < 1:
        raise ValueError(
            "Некорректный идентификатор организации "
            "или товарной группы."
        )

    prepared_group = product_group.strip().lower()

    if not prepared_group:
        raise ValueError(
            "product_group не может быть пустым."
        )

    dates = requested_dates(
        period_from,
        period_to,
    )
    report_id = report_id_for_group(
        product_group_code
    )

    if report_id is None:
        typer.echo(
            "Розничные продажи: отчёт не поддерживается "
            f"для группы {prepared_group} "
            f"({product_group_code}); пропуск."
        )
        return SalesSyncSummary(
            legal_entity_id=legal_entity_id,
            product_group=prepared_group,
            product_group_code=product_group_code,
            period_from=period_from,
            period_to=period_to,
            supported=False,
            requested_day_count=len(dates),
            processed_day_count=0,
            already_loaded_day_count=0,
            remaining_day_count=0,
            row_count=0,
            inserted_count=0,
            rejected_count=0,
            total_quantity=Decimal("0"),
            total_amount=Decimal("0"),
            days=(),
        )

    active_database = database or Database(
        get_settings()
    )
    settings = load_sync_settings()
    already_loaded = loaded_dates(
        active_database,
        legal_entity_id,
        prepared_group,
        period_from,
        period_to,
    )
    pending = [
        item
        for item in dates
        if item not in already_loaded
    ]

    # В совокупности для отчётов этой группы True API допускает
    # не более 10 новых заданий в сутки. Загружаем сначала самые
    # свежие отсутствующие дни; старые дни будут добраны следующими
    # запусками задания TRACK_VIOLATIONS.
    selected = pending[
        -settings.max_new_days_per_run:
    ]
    remaining_count = max(
        0,
        len(pending) - len(selected),
    )
    summaries: list[SalesDaySummary] = []

    try:
        if selected:
            async with SalesExportClient(
                get_settings(),
                token,
            ) as client:
                for index, sale_date in enumerate(
                    selected,
                    start=1,
                ):
                    typer.echo(
                        "Розничные продажи "
                        f"{index}/{len(selected)}: "
                        f"{prepared_group} "
                        f"({product_group_code}); "
                        f"{sale_date}."
                    )
                    summary = await sync_day(
                        client,
                        active_database,
                        settings,
                        legal_entity_id,
                        prepared_group,
                        product_group_code,
                        report_id,
                        sale_date,
                    )
                    summaries.append(summary)
                    typer.echo(
                        f"Строк={summary.row_count}; "
                        f"продано={summary.total_quantity}; "
                        f"отклонено={summary.rejected_count}."
                    )

        loaded_after = (
            already_loaded
            | {item.sale_date for item in summaries}
        )
        success_date = (
            max(loaded_after)
            if loaded_after
            else None
        )
        mark_group(
            active_database,
            legal_entity_id,
            prepared_group,
            "SUCCESS",
            success_date,
            None,
        )

    except Exception as exc:
        mark_group(
            active_database,
            legal_entity_id,
            prepared_group,
            "ERROR",
            None,
            (
                f"{type(exc).__name__}: {exc}"
            )[:2000],
        )
        raise

    return SalesSyncSummary(
        legal_entity_id=legal_entity_id,
        product_group=prepared_group,
        product_group_code=product_group_code,
        period_from=period_from,
        period_to=period_to,
        supported=True,
        requested_day_count=len(dates),
        processed_day_count=len(summaries),
        already_loaded_day_count=len(already_loaded),
        remaining_day_count=remaining_count,
        row_count=sum(
            item.row_count
            for item in summaries
        ),
        inserted_count=sum(
            item.inserted_count
            for item in summaries
        ),
        rejected_count=sum(
            item.rejected_count
            for item in summaries
        ),
        total_quantity=sum(
            (
                item.total_quantity
                for item in summaries
            ),
            Decimal("0"),
        ),
        total_amount=sum(
            (
                item.total_amount
                for item in summaries
            ),
            Decimal("0"),
        ),
        days=tuple(summaries),
    )


@dataclass(frozen=True, slots=True)
class SalesProductGroupFailure:
    product_group: str
    error_type: str
    error_message: str


@dataclass(frozen=True, slots=True)
class SalesLegalEntitySummary:
    legal_entity_id: int
    period_from: date
    period_to: date
    selected_group_count: int
    supported_group_count: int
    successful_group_count: int
    skipped_group_count: int
    failed_group_count: int
    processed_day_count: int
    already_loaded_day_count: int
    remaining_day_count: int
    row_count: int
    inserted_count: int
    rejected_count: int
    total_quantity: Decimal
    total_amount: Decimal
    group_summaries: tuple[SalesSyncSummary, ...]
    failures: tuple[SalesProductGroupFailure, ...]


def load_sales_group_plans(
    database: Database,
    legal_entity_id: int,
) -> tuple[tuple[str, int], ...]:
    connection = database.connect()

    try:
        cursor = connection.cursor(dictionary=True)

        try:
            cursor.execute(
                """
                SELECT
                    group_config.product_group,
                    dictionary.product_group_code

                FROM legal_entity_product_group AS group_config

                JOIN gis_mt_product_group_dictionary AS dictionary
                  ON dictionary.product_group =
                     group_config.product_group
                 AND dictionary.is_active = 1

                WHERE group_config.legal_entity_id = %s
                  AND group_config.is_enabled = 1
                  AND group_config.gis_mt_available = 1
                  AND group_config.sales_enabled = 1

                ORDER BY group_config.product_group
                """,
                (legal_entity_id,),
            )

            return tuple(
                (
                    str(row["product_group"]),
                    int(row["product_group_code"]),
                )
                for row in cursor.fetchall()
                if row["product_group_code"] is not None
            )

        finally:
            cursor.close()

    finally:
        connection.close()


async def sync_legal_entity_sales(
    *,
    token: str,
    legal_entity_id: int,
    period_from: date,
    period_to: date,
    continue_on_error: bool = True,
    database: Database | None = None,
) -> SalesLegalEntitySummary:
    if period_from > period_to:
        raise ValueError(
            "Дата начала периода продаж позже даты окончания."
        )

    active_database = database or Database(
        get_settings()
    )
    plans = load_sales_group_plans(
        active_database,
        legal_entity_id,
    )

    if not plans:
        raise ValueError(
            "Для организации нет включённых товарных групп "
            "для скачивания продаж."
        )

    summaries: list[SalesSyncSummary] = []
    failures: list[SalesProductGroupFailure] = []

    for product_group, product_group_code in plans:
        try:
            summary = await sync_retail_sales(
                token=token,
                legal_entity_id=legal_entity_id,
                product_group=product_group,
                product_group_code=product_group_code,
                period_from=period_from,
                period_to=period_to,
                database=active_database,
            )
            summaries.append(summary)

        except Exception as exc:
            failures.append(
                SalesProductGroupFailure(
                    product_group=product_group,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:2000],
                )
            )

            if not continue_on_error:
                raise

    supported = [
        item
        for item in summaries
        if item.supported
    ]

    return SalesLegalEntitySummary(
        legal_entity_id=legal_entity_id,
        period_from=period_from,
        period_to=period_to,
        selected_group_count=len(plans),
        supported_group_count=len(supported),
        successful_group_count=len(supported),
        skipped_group_count=sum(
            1
            for item in summaries
            if not item.supported
        ),
        failed_group_count=len(failures),
        processed_day_count=sum(
            item.processed_day_count
            for item in supported
        ),
        already_loaded_day_count=sum(
            item.already_loaded_day_count
            for item in supported
        ),
        remaining_day_count=sum(
            item.remaining_day_count
            for item in supported
        ),
        row_count=sum(
            item.row_count
            for item in supported
        ),
        inserted_count=sum(
            item.inserted_count
            for item in supported
        ),
        rejected_count=sum(
            item.rejected_count
            for item in supported
        ),
        total_quantity=sum(
            (
                item.total_quantity
                for item in supported
            ),
            Decimal("0"),
        ),
        total_amount=sum(
            (
                item.total_amount
                for item in supported
            ),
            Decimal("0"),
        ),
        group_summaries=tuple(summaries),
        failures=tuple(failures),
    )
