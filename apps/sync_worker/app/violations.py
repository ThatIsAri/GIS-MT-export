from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import random
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import uuid4

import httpx
import typer

from app.cli import read_token_from_stdin
from app.client import (
    GisMtAuthError,
    GisMtError,
    GisMtHttpError,
)
from app.config import Settings, get_settings
from app.db import Database


MAX_EXPORT_DAYS = 91

TERMINAL_TASK_FAILURES = {
    "FAILED",
    "CANCELED",
    "ARCHIVE",
}


HEADER_ALIASES: dict[
    str,
    tuple[str, ...],
] = {
    "violation_kind": (
        "Вид отклонения",
    ),

    "violation_result": (
        "Результат проверки",
    ),

    "registered_at": (
        "Дата и время регистрации отклонения",
    ),

    "product_group_name": (
        "Товарная группа",
    ),

    "subject_name": (
        "Субъект",
    ),

    "location_address": (
        "Адрес места фиксации отклонения",
    ),

    "document_number": (
        "Номер документа",
    ),

    "code_text": (
        "Код",
    ),

    "vsd_id": (
        "Идентификатор ВСД",
    ),

    "kkt_registration_number": (
        "Регистрационный номер ККТ (из чека)",
        "Регистрационный номер ККТ",
    ),

    "operation_at": (
        "Дата и время выполнения операции, "
        "в результате которой было выявлено отклонение",
    ),

    "participant_inn": (
        "ИНН участника",
    ),

    "violation_number": (
        "Номер отклонения",
    ),

    "is_nivellated": (
        "Нивелировано",
    ),

    "vsd_volume": (
        "Объем из ВСД",
        "Объём из ВСД",
    ),

    "vsd_unit": (
        "Единицы измерения из ВСД",
    ),

    "gis_mt_volume": (
        "Объем из ГИС МТ",
        "Объём из ГИС МТ",
    ),

    "gis_mt_unit": (
        "Единицы измерения из ГИС МТ",
    ),

    "volume_difference": (
        "Разницы между объемами",
        "Разница между объемами",
        "Разницы между объёмами",
        "Разница между объёмами",
    ),

    "volume_difference_unit": (
        "Единицы измерения разницы",
    ),

    "excess_percent": (
        "% превышения",
    ),

    "gtin": (
        "GTIN",
    ),

    "fias_id": (
        "Идентификатор ФИАС",
    ),

    "municipal_district": (
        "Муниципальный округ",
    ),

    "fiscal_drive_number": (
        "Фискальный номер накопителя из чека операции",
        "Фискальный номер накопителя",
    ),

    "permission_mode_result": (
        "Проверка РР",
    ),

    "withdrawal_volume": (
        "Объём вывода из оборота",
        "Объем вывода из оборота",
    ),

    "expansion_stage": (
        "Этап расширения",
    ),
}


VIOLATION_COLUMNS = (
    "violation_kind",
    "violation_result",
    "registered_at",
    "product_group_name",
    "subject_name",
    "location_address",
    "document_number",
    "code_text",
    "code_sha256",
    "vsd_id",
    "kkt_registration_number",
    "operation_at",
    "participant_inn",
    "violation_number",
    "is_nivellated",
    "vsd_volume",
    "vsd_unit",
    "gis_mt_volume",
    "gis_mt_unit",
    "volume_difference",
    "volume_difference_unit",
    "excess_percent",
    "gtin",
    "fias_id",
    "municipal_district",
    "fiscal_drive_number",
    "permission_mode_result",
    "withdrawal_volume",
    "expansion_stage",
    "raw_row_json",
)


TEXT_LIMITS = {
    "violation_kind": 1000,
    "violation_result": 1000,
    "product_group_name": 512,
    "subject_name": 512,
    "location_address": 2000,
    "document_number": 512,
    "code_text": 2048,
    "vsd_id": 255,
    "kkt_registration_number": 128,
    "violation_number": 255,
    "vsd_unit": 64,
    "gis_mt_unit": 64,
    "volume_difference_unit": 64,
    "fias_id": 36,
    "municipal_district": 1000,
    "fiscal_drive_number": 128,
    "permission_mode_result": 512,
    "expansion_stage": 255,
}


@dataclass(
    frozen=True,
    slots=True,
)
class ViolationSyncSettings:
    archive_root: Path
    task_poll_seconds: float
    result_poll_seconds: float
    timeout_seconds: int


@dataclass(
    frozen=True,
    slots=True,
)
class ViolationExportWindow:
    period_from: date
    period_to: date


@dataclass(
    frozen=True,
    slots=True,
)
class ViolationWindowSummary:
    export_run_id: int
    period_from: date
    period_to: date
    task_id: str
    result_id: str
    csv_file_count: int
    row_count: int
    inserted_count: int
    updated_count: int
    rejected_count: int
    archive_path: str


@dataclass(
    frozen=True,
    slots=True,
)
class ViolationSyncSummary:
    legal_entity_id: int
    product_group: str
    product_group_code: int
    period_from: date
    period_to: date
    window_count: int
    row_count: int
    inserted_count: int
    updated_count: int
    rejected_count: int

    windows: tuple[
        ViolationWindowSummary,
        ...,
    ]


def load_sync_settings() -> ViolationSyncSettings:
    timeout = int(
        os.getenv(
            "VIOLATIONS_TASK_TIMEOUT_SECONDS",
            "1800",
        )
    )

    if timeout < 60:
        raise ValueError(
            "VIOLATIONS_TASK_TIMEOUT_SECONDS "
            "должен быть не меньше 60."
        )

    return ViolationSyncSettings(
        archive_root=Path(
            os.getenv(
                "VIOLATIONS_ARCHIVE_ROOT",
                "/data/edo_inbox/violations",
            )
        ),

        task_poll_seconds=max(
            12.0,
            float(
                os.getenv(
                    "VIOLATIONS_TASK_POLL_SECONDS",
                    "15",
                )
            ),
        ),

        result_poll_seconds=max(
            5.0,
            float(
                os.getenv(
                    "VIOLATIONS_RESULT_POLL_SECONDS",
                    "6",
                )
            ),
        ),

        timeout_seconds=timeout,
    )


def clean_text(
    value: Any,
    limit: int = 4000,
) -> str | None:
    if value is None:
        return None

    result = " ".join(
        str(
            value
        ).split()
    ).strip()

    return (
        result[:limit]
        if result
        else None
    )


def clean_code_text(
    value: Any,
    limit: int = 2048,
) -> str | None:
    if value is None:
        return None

    result = str(value).strip(
        " \t\r\n"
    )

    return (
        result[:limit]
        if result
        else None
    )


def extract_gtin_from_marking_code(
    value: str | None,
) -> str | None:
    if not value:
        return None

    prepared = value.strip(
        " \t\r\n"
    )

    if prepared[:3].lower() == "]d2":
        prepared = prepared[3:]

    if prepared.startswith("(01)"):
        candidate = prepared[4:18]

    elif prepared.startswith("01"):
        candidate = prepared[2:16]

    elif len(prepared) >= 14:
        candidate = prepared[:14]

    else:
        return None

    if len(candidate) != 14 or not candidate.isdigit():
        return None

    return candidate


def normalize_header(
    value: str,
) -> str:
    value = (
        value
        .replace(
            "\ufeff",
            "",
        )
        .strip()
        .casefold()
        .replace(
            "ё",
            "е",
        )
    )

    value = re.sub(
        r"[^0-9a-zа-я%]+",
        " ",
        value,
    )

    return " ".join(
        value.split()
    )


def header_lookup(
    fieldnames: Iterable[
        str | None
    ],
) -> dict[
    str,
    str,
]:
    return {
        normalize_header(
            name
        ): name

        for name in fieldnames

        if (
            name
            and normalize_header(
                name
            )
        )
    }


def read_field(
    row: dict[
        str,
        Any,
    ],
    lookup: dict[
        str,
        str,
    ],
    logical_name: str,
) -> str | None:
    for alias in (
        HEADER_ALIASES[
            logical_name
        ]
    ):
        source = lookup.get(
            normalize_header(
                alias
            )
        )

        if source is not None:
            value = row.get(
                source
            )

            if logical_name == "code_text":
                return clean_code_text(
                    value
                )

            return clean_text(
                value
            )

    return None


def parse_datetime(
    value: str | None,
) -> datetime | None:
    if (
        not value
        or value in {
            "-",
            "—",
        }
    ):
        return None

    try:
        result = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

        if result.tzinfo is not None:
            result = (
                result
                .astimezone(
                    timezone.utc
                )
                .replace(
                    tzinfo=None
                )
            )

        return result

    except ValueError:
        pass

    for date_format in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S.%f",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(
                value,
                date_format,
            )

        except ValueError:
            continue

    raise ValueError(
        "Не удалось разобрать "
        f"дату и время: {value!r}."
    )


def parse_decimal(
    value: str | None,
) -> Decimal | None:
    if (
        not value
        or value in {
            "-",
            "—",
        }
    ):
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
            "%",
            "",
        )
        .replace(
            ",",
            ".",
        )
    )

    try:
        return Decimal(
            prepared
        )

    except InvalidOperation as exc:
        raise ValueError(
            "Не удалось разобрать "
            f"число: {value!r}."
        ) from exc


def parse_bool(
    value: str | None,
) -> bool | None:
    if (
        not value
        or value in {
            "-",
            "—",
        }
    ):
        return None

    prepared = value.casefold()

    if prepared in {
        "да",
        "true",
        "1",
        "yes",
    }:
        return True

    if prepared in {
        "нет",
        "false",
        "0",
        "no",
    }:
        return False

    raise ValueError(
        "Не удалось разобрать "
        f"логическое значение: {value!r}."
    )


def parse_inn(
    value: str | None,
) -> str | None:
    if not value:
        return None

    digits = "".join(
        character
        for character in value
        if character.isdigit()
    )

    if len(
        digits
    ) in {
        10,
        12,
    }:
        return digits

    return clean_text(
        value,
        12,
    )


def parse_gtin(
    value: str | None,
) -> str | None:
    if not value:
        return None

    digits = "".join(
        character
        for character in value
        if character.isdigit()
    )

    if not digits:
        return None

    if len(
        digits
    ) <= 14:
        return digits.zfill(
            14
        )

    return digits[:14]


def sha256_text(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def parse_row(
    row: dict[
        str,
        Any,
    ],
    lookup: dict[
        str,
        str,
    ],
    legal_entity_id: int,
    product_group_code: int,
) -> tuple[
    str,
    dict[
        str,
        Any,
    ],
]:
    values: dict[
        str,
        Any,
    ] = {}

    for name in HEADER_ALIASES:
        values[name] = read_field(
            row,
            lookup,
            name,
        )

    for (
        name,
        limit,
    ) in TEXT_LIMITS.items():
        if name not in values:
            continue

        if name == "code_text":
            values[name] = clean_code_text(
                values[name],
                limit,
            )
        else:
            values[name] = clean_text(
                values[name],
                limit,
            )

    values[
        "registered_at"
    ] = parse_datetime(
        values[
            "registered_at"
        ]
    )

    values[
        "operation_at"
    ] = parse_datetime(
        values[
            "operation_at"
        ]
    )

    values[
        "participant_inn"
    ] = parse_inn(
        values[
            "participant_inn"
        ]
    )

    values[
        "is_nivellated"
    ] = parse_bool(
        values[
            "is_nivellated"
        ]
    )

    values[
        "gtin"
    ] = (
        parse_gtin(
            values[
                "gtin"
            ]
        )
        or extract_gtin_from_marking_code(
            values[
                "code_text"
            ]
        )
    )

    for name in (
        "vsd_volume",
        "gis_mt_volume",
        "volume_difference",
        "excess_percent",
        "withdrawal_volume",
    ):
        values[name] = parse_decimal(
            values[name]
        )

    values[
        "code_sha256"
    ] = (
        sha256_text(
            values[
                "code_text"
            ]
        )
        if values[
            "code_text"
        ]
        else None
    )

    values[
        "raw_row_json"
    ] = json.dumps(
        {
            str(
                key
            ): (
                ""
                if value is None
                else str(
                    value
                )
            )

            for (
                key,
                value,
            ) in row.items()

            if key
        },
        ensure_ascii=False,
        separators=(
            ",",
            ":",
        ),
    )

    if not any(
        values[
            name
        ]
        for name in (
            "violation_kind",
            "violation_result",
            "violation_number",
            "code_text",
            "document_number",
        )
    ):
        raise ValueError(
            "Строка не содержит "
            "идентифицирующих данных отклонения."
        )

    if values[
        "violation_number"
    ]:
        identity = {
            "legal_entity_id": (
                legal_entity_id
            ),

            "violation_number": (
                values[
                    "violation_number"
                ]
            ),
        }

    else:
        identity = {
            "legal_entity_id": (
                legal_entity_id
            ),

            "product_group_code": (
                product_group_code
            ),

            "code_text": (
                values[
                    "code_text"
                ]
            ),

            "operation_at": (
                values[
                    "operation_at"
                ].isoformat()
                if values[
                    "operation_at"
                ]
                else None
            ),

            "document_number": (
                values[
                    "document_number"
                ]
            ),

            "violation_kind": (
                values[
                    "violation_kind"
                ]
            ),

            "violation_result": (
                values[
                    "violation_result"
                ]
            ),

            "kkt_registration_number": (
                values[
                    "kkt_registration_number"
                ]
            ),
        }

    key = sha256_text(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )
    )

    return (
        key,
        values,
    )


def decode_csv(
    content: bytes,
) -> str:
    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp1251",
    ):
        try:
            return content.decode(
                encoding
            )

        except UnicodeDecodeError:
            continue

    raise ValueError(
        "Не удалось определить кодировку CSV."
    )


def delimiter(
    text: str,
) -> str:
    sample = text[:10000]

    try:
        return (
            csv.Sniffer()
            .sniff(
                sample,
                delimiters=",;\t",
            )
            .delimiter
        )

    except csv.Error:
        first = (
            sample.splitlines()[0]
            if sample.splitlines()
            else ""
        )

        return (
            ";"
            if first.count(";")
            > first.count(",")
            else ","
        )


def archive_csv_files(
    content: bytes,
) -> Iterator[
    tuple[
        str,
        bytes,
    ]
]:
    try:
        with zipfile.ZipFile(
            io.BytesIO(
                content
            )
        ) as archive:
            members = [
                item

                for item in (
                    archive.infolist()
                )

                if (
                    not item.is_dir()
                    and item.filename
                    .lower()
                    .endswith(
                        ".csv"
                    )
                )
            ]

            if not members:
                raise ValueError(
                    "ZIP-архив не содержит CSV-файлов."
                )

            for item in members:
                yield (
                    item.filename,
                    archive.read(
                        item
                    ),
                )

    except zipfile.BadZipFile:
        yield (
            "violations.csv",
            content,
        )


def export_windows(
    start: date,
    end: date,
) -> tuple[
    ViolationExportWindow,
    ...,
]:
    if start > end:
        raise ValueError(
            "Дата начала периода позже даты окончания."
        )

    result: list[
        ViolationExportWindow
    ] = []

    current = start

    while current <= end:
        current_end = min(
            end,
            current
            + timedelta(
                days=(
                    MAX_EXPORT_DAYS
                    - 1
                )
            ),
        )

        result.append(
            ViolationExportWindow(
                current,
                current_end,
            )
        )

        current = (
            current_end
            + timedelta(
                days=1
            )
        )

    return tuple(
        result
    )


class ViolationExportClient:
    RETRYABLE = {
        429,
        500,
        502,
        503,
        504,
    }

    def __init__(
        self,
        settings: Settings,
        token: str,
    ) -> None:
        token = token.strip()

        if not token:
            raise ValueError(
                "Токен ГИС МТ пуст."
            )

        self.settings = settings

        self.base_url = (
            settings
            .gis_mt_true_api_v3_url
            .rstrip(
                "/"
            )
        )

        self.headers = {
            "Authorization": (
                f"Bearer {token}"
            ),

            "User-Agent": (
                settings.user_agent
            ),
        }

        self.client: (
            httpx.AsyncClient
            | None
        ) = None

    async def __aenter__(
        self,
    ) -> "ViolationExportClient":
        self.client = httpx.AsyncClient(
            headers=self.headers,

            timeout=httpx.Timeout(
                self.settings
                .http_timeout_seconds
            ),

            follow_redirects=False,
        )

        return self

    async def __aexit__(
        self,
        *_: object,
    ) -> None:
        if self.client:
            await self.client.aclose()

    async def create_task(
        self,
        group_code: int,
        start: date,
        end: date,
    ) -> tuple[
        dict[
            str,
            Any,
        ],
        dict[
            str,
            Any,
        ],
    ]:
        body = {
            "name": "VIOLATIONS",

            "dataStartDate": (
                start.isoformat()
            ),

            "dataEndDate": (
                end.isoformat()
            ),

            "format": "CSV",
            "periodicity": "SINGLE",
            "params": "{}",

            "productGroupCode": (
                group_code
            ),
        }

        return (
            body,

            await self.json_request(
                "POST",
                "/dispenser/tasks",
                json=body,
            ),
        )

    async def task(
        self,
        task_id: str,
        group_code: int,
    ) -> dict[
        str,
        Any,
    ]:
        return await self.json_request(
            "GET",

            (
                "/dispenser/tasks/"
                f"{task_id}"
            ),

            params={
                "pg": group_code
            },
        )

    async def results(
        self,
        task_id: str,
        group_code: int,
    ) -> dict[
        str,
        Any,
    ]:
        return await self.json_request(
            "GET",
            "/dispenser/results",

            params=[
                (
                    "page",
                    "0",
                ),

                (
                    "size",
                    "100",
                ),

                (
                    "pg",
                    str(
                        group_code
                    ),
                ),

                (
                    "task_ids",
                    task_id,
                ),
            ],
        )

    async def download(
        self,
        result_id: str,
        group_code: int,
    ) -> bytes:
        response = await self.request(
            "GET",

            (
                "/dispenser/results/"
                f"{result_id}/file"
            ),

            params={
                "pg": group_code
            },

            accept="*/*",
        )

        return response.content

    async def json_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[
        str,
        Any,
    ]:
        response = await self.request(
            method,
            path,
            accept="application/json",
            **kwargs,
        )

        try:
            payload = response.json()

        except json.JSONDecodeError as exc:
            raise GisMtError(
                "True API вернул не-JSON: "
                f"{response.text[:1000]!r}."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise GisMtError(
                "True API вернул JSON "
                "неожиданного типа."
            )

        return payload

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json: Any = None,
        accept: str,
    ) -> httpx.Response:
        if not self.client:
            raise RuntimeError(
                "Клиент должен использоваться "
                "через async with."
            )

        last_error: (
            Exception
            | None
        ) = None

        for attempt in range(
            1,
            (
                self.settings
                .http_max_attempts
                + 1
            ),
        ):
            try:
                response = (
                    await self.client.request(
                        method,

                        (
                            f"{self.base_url}"
                            f"{path}"
                        ),

                        params=params,
                        json=json,

                        headers={
                            "Accept": accept
                        },
                    )
                )

                if (
                    response.status_code
                    in {
                        401,
                        403,
                    }
                ):
                    raise GisMtAuthError(
                        "ГИС МТ отклонила "
                        "авторизацию: "
                        "HTTP "
                        f"{response.status_code}."
                    )

                if (
                    response.status_code
                    in self.RETRYABLE
                ):
                    if (
                        attempt
                        == self.settings
                        .http_max_attempts
                    ):
                        raise GisMtHttpError(
                            response.status_code,
                            self.error_text(
                                response
                            ),
                        )

                    await asyncio.sleep(
                        self.retry_delay(
                            response,
                            attempt,
                        )
                    )

                    continue

                if response.is_error:
                    raise GisMtHttpError(
                        response.status_code,
                        self.error_text(
                            response
                        ),
                    )

                return response

            except (
                GisMtAuthError,
                GisMtHttpError,
            ):
                raise

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as exc:
                last_error = exc

                if (
                    attempt
                    == self.settings
                    .http_max_attempts
                ):
                    break

                await asyncio.sleep(
                    min(
                        30.0,

                        (
                            2
                            ** (
                                attempt
                                - 1
                            )
                        )
                        + random.random(),
                    )
                )

        raise GisMtError(
            "Запрос к сервису выгрузок "
            "ГИС МТ не выполнен: "
            + (
                type(
                    last_error
                ).__name__
                if last_error
                else "unknown error"
            )
            + "."
        )

    @staticmethod
    def error_text(
        response: httpx.Response,
    ) -> str:
        text = response.text.strip()

        return (
            f"HTTP {response.status_code}: "
            + (
                text[:2000]
                or response.reason_phrase
            )
        )

    @staticmethod
    def retry_delay(
        response: httpx.Response,
        attempt: int,
    ) -> float:
        value = response.headers.get(
            "Retry-After"
        )

        if value:
            try:
                return max(
                    0.0,
                    float(
                        value
                    ),
                )

            except ValueError:
                try:
                    return max(
                        0.0,

                        parsedate_to_datetime(
                            value
                        ).timestamp()
                        - time.time(),
                    )

                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    pass

        return min(
            60.0,

            (
                2
                ** (
                    attempt
                    - 1
                )
            )
            + random.random(),
        )


def identifier(
    payload: dict[
        str,
        Any,
    ],
    *names: str,
) -> str:
    candidates = [
        payload
    ]

    candidates.extend(
        nested

        for key in (
            "data",
            "result",
            "task",
        )

        if isinstance(
            (
                nested
                := payload.get(
                    key
                )
            ),
            dict,
        )
    )

    for candidate in candidates:
        for name in names:
            if (
                candidate.get(
                    name
                )
                is not None

                and str(
                    candidate[
                        name
                    ]
                ).strip()
            ):
                return str(
                    candidate[
                        name
                    ]
                ).strip()

    raise GisMtError(
        "Ответ True API не содержит "
        "идентификатор: "
        + ", ".join(
            names
        )
    )


def task_status(
    payload: dict[
        str,
        Any,
    ],
) -> str:
    value = str(
        payload.get(
            "currentStatus"
        )
        or payload.get(
            "status"
        )
        or ""
    ).strip().upper()

    if not value:
        raise GisMtError(
            "Ответ задания не содержит "
            "currentStatus."
        )

    return value


def result_item(
    payload: dict[
        str,
        Any,
    ],
    task_id: str,
) -> dict[
    str,
    Any,
] | None:
    items = payload.get(
        "list"
    )

    if not isinstance(
        items,
        list,
    ):
        return None

    matches = [
        item

        for item in items

        if (
            isinstance(
                item,
                dict,
            )

            and str(
                item.get(
                    "taskId"
                )
                or ""
            )
            == task_id
        )
    ]

    matches.sort(
        key=lambda item: str(
            item.get(
                "generationEndDate"
            )
            or ""
        ),
        reverse=True,
    )

    return (
        matches[0]
        if matches
        else None
    )


def create_run(
    database: Database,
    entity_id: int,
    product_group: str,
    group_code: int,
    window: ViolationExportWindow,
) -> int:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO violation_export_run (
                    run_uuid,
                    legal_entity_id,
                    product_group,
                    product_group_code,
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
                    'NEW',
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6),
                    UTC_TIMESTAMP(6)
                )
                """,
                (
                    str(
                        uuid4()
                    ),
                    entity_id,
                    product_group,
                    group_code,
                    window.period_from,
                    window.period_to,
                ),
            )

            return int(
                cursor.lastrowid
            )

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

    assignments: list[
        str
    ] = []

    params: list[
        Any
    ] = []

    for (
        name,
        value,
    ) in values.items():
        assignments.append(
            f"{name} = %s"
        )

        params.append(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
            if (
                name in json_fields
                and value is not None
            )
            else value
        )

    assignments.append(
        "updated_at = UTC_TIMESTAMP(6)"
    )

    params.append(
        run_id
    )

    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                (
                    "UPDATE violation_export_run "
                    "SET "
                    + ", ".join(
                        assignments
                    )
                    + " WHERE id = %s"
                ),
                tuple(
                    params
                ),
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

                   SET violations_last_success_date =
                       CASE
                           WHEN %s = 'SUCCESS'
                           THEN %s
                           ELSE violations_last_success_date
                       END,

                       violations_last_sync_at =
                           UTC_TIMESTAMP(6),

                       violations_last_sync_status =
                           %s,

                       violations_last_error =
                           %s,

                       updated_at =
                           UTC_TIMESTAMP(6)

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
    window: ViolationExportWindow,
    task_id: str,
    content: bytes,
) -> tuple[
    Path,
    str,
]:
    def safe(
        value: str,
    ) -> str:
        return re.sub(
            r"[^0-9A-Za-zА-Яа-я._-]+",
            "_",
            value,
        ).strip(
            "._-"
        )

    directory = (
        root
        / str(
            entity_id
        )
        / safe(
            product_group
        )
        / (
            f"{window.period_from}_"
            f"{window.period_to}"
        )
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        directory
        / f"{safe(task_id)}.zip"
    )

    temporary = path.with_suffix(
        ".zip.tmp"
    )

    temporary.write_bytes(
        content
    )

    temporary.replace(
        path
    )

    return (
        path,

        hashlib.sha256(
            content
        ).hexdigest(),
    )


def upsert_violation(
    cursor: Any,
    run_id: int,
    entity_id: int,
    product_group: str,
    group_code: int,
    key: str,
    values: dict[
        str,
        Any,
    ],
) -> bool:
    cursor.execute(
        """
        SELECT id
        FROM gis_mt_violation
        WHERE violation_key_sha256 = %s
        LIMIT 1
        """,
        (
            key,
        ),
    )

    existing = cursor.fetchone()

    datamatrix_id = None

    if values[
        "code_sha256"
    ]:
        cursor.execute(
            """
            SELECT id
            FROM datamatrix_unit
            WHERE code_sha256 = %s
            LIMIT 1
            """,
            (
                values[
                    "code_sha256"
                ],
            ),
        )

        row = cursor.fetchone()

        datamatrix_id = (
            int(
                row[0]
            )
            if row
            else None
        )

    column_values = [
        values[
            name
        ]

        for name in (
            VIOLATION_COLUMNS
        )
    ]

    if existing is None:
        columns = (
            "violation_key_sha256, "
            "legal_entity_id, "
            "product_group, "
            "product_group_code, "
            "first_seen_run_id, "
            "last_seen_run_id, "
            "datamatrix_unit_id, "
            + ", ".join(
                VIOLATION_COLUMNS
            )
        )

        placeholders = ", ".join(
            [
                "%s"
            ]
            * (
                7
                + len(
                    VIOLATION_COLUMNS
                )
            )
        )

        cursor.execute(
            f"""
            INSERT INTO gis_mt_violation (
                {columns},
                first_seen_at,
                last_seen_at,
                created_at,
                updated_at
            )
            VALUES (
                {placeholders},
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6),
                UTC_TIMESTAMP(6)
            )
            """,
            (
                key,
                entity_id,
                product_group,
                group_code,
                run_id,
                run_id,
                datamatrix_id,
                *column_values,
            ),
        )

        return True

    assignments = [
        "legal_entity_id = %s",
        "product_group = %s",
        "product_group_code = %s",
        "last_seen_run_id = %s",
        "datamatrix_unit_id = %s",

        *[
            f"{name} = %s"

            for name in (
                VIOLATION_COLUMNS
            )
        ],

        "last_seen_at = UTC_TIMESTAMP(6)",
        "updated_at = UTC_TIMESTAMP(6)",
    ]

    cursor.execute(
        (
            "UPDATE gis_mt_violation "
            "SET "
            + ", ".join(
                assignments
            )
            + " WHERE id = %s"
        ),
        (
            entity_id,
            product_group,
            group_code,
            run_id,
            datamatrix_id,
            *column_values,
            int(
                existing[0]
            ),
        ),
    )

    return False


def import_archive(
    database: Database,
    content: bytes,
    run_id: int,
    entity_id: int,
    product_group: str,
    group_code: int,
) -> tuple[
    int,
    int,
    int,
    int,
    int,
]:
    files = 0
    rows = 0
    inserted = 0
    updated = 0
    rejected = 0

    connection = database.connect()

    try:
        cursor = connection.cursor()

        try:
            for (
                file_name,
                csv_content,
            ) in archive_csv_files(
                content
            ):
                files += 1

                text = decode_csv(
                    csv_content
                )

                reader = csv.DictReader(
                    io.StringIO(
                        text
                    ),
                    delimiter=delimiter(
                        text
                    ),
                )

                lookup = header_lookup(
                    reader.fieldnames
                    or []
                )

                if not lookup:
                    raise ValueError(
                        f"CSV {file_name!r} "
                        "не содержит заголовков."
                    )

                for (
                    row_number,
                    row,
                ) in enumerate(
                    reader,
                    start=2,
                ):
                    if not any(
                        str(
                            value
                            or ""
                        ).strip()

                        for value in (
                            row.values()
                        )
                    ):
                        continue

                    rows += 1

                    try:
                        (
                            key,
                            values,
                        ) = parse_row(
                            row,
                            lookup,
                            entity_id,
                            group_code,
                        )

                        was_inserted = (
                            upsert_violation(
                                cursor,
                                run_id,
                                entity_id,
                                product_group,
                                group_code,
                                key,
                                values,
                            )
                        )

                        if was_inserted:
                            inserted += 1

                        else:
                            updated += 1

                    except Exception as exc:
                        rejected += 1

                        cursor.execute(
                            """
                            INSERT INTO
                                violation_import_reject (
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
                                    f"{type(exc).__name__}: "
                                    f"{exc}"
                                )[:4000],

                                json.dumps(
                                    row,
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            ),
                        )

                    if rows % 500 == 0:
                        connection.commit()

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
        updated,
        rejected,
    )


async def wait_task(
    client: ViolationExportClient,
    task_id: str,
    group_code: int,
    poll: float,
    timeout: int,
) -> dict[
    str,
    Any,
]:
    deadline = (
        time.monotonic()
        + timeout
    )

    while True:
        payload = await client.task(
            task_id,
            group_code,
        )

        status = task_status(
            payload
        )

        if status == "COMPLETED":
            return payload

        if (
            status
            in TERMINAL_TASK_FAILURES
        ):
            raise GisMtError(
                "Задание отклонений "
                "завершилось со статусом "
                f"{status}."
            )

        if (
            time.monotonic()
            >= deadline
        ):
            raise TimeoutError(
                "Истёк таймаут ожидания "
                "задания отклонений."
            )

        await asyncio.sleep(
            poll
        )


async def wait_result(
    client: ViolationExportClient,
    task_id: str,
    group_code: int,
    poll: float,
    timeout: int,
) -> tuple[
    dict[
        str,
        Any,
    ],
    dict[
        str,
        Any,
    ],
]:
    deadline = (
        time.monotonic()
        + timeout
    )

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
                item.get(
                    "downloadStatus"
                )
                or ""
            ).upper()

            available = str(
                item.get(
                    "available"
                )
                or ""
            ).upper()

            if status == "FAILED":
                raise GisMtError(
                    str(
                        item.get(
                            "fullErrorMessage"
                        )
                        or item.get(
                            "errorMessage"
                        )
                        or item
                    )
                )

            if (
                status == "SUCCESS"
                and available
                in {
                    "",
                    "AVAILABLE",
                }
            ):
                return (
                    payload,
                    item,
                )

        if (
            time.monotonic()
            >= deadline
        ):
            raise TimeoutError(
                "Истёк таймаут ожидания "
                "файла отклонений."
            )

        await asyncio.sleep(
            poll
        )


async def sync_window(
    client: ViolationExportClient,
    database: Database,
    settings: ViolationSyncSettings,
    entity_id: int,
    product_group: str,
    group_code: int,
    window: ViolationExportWindow,
) -> ViolationWindowSummary:
    run_id = create_run(
        database,
        entity_id,
        product_group,
        group_code,
        window,
    )

    try:
        (
            request_body,
            create_payload,
        ) = await client.create_task(
            group_code,
            window.period_from,
            window.period_to,
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

        task_payload = await wait_task(
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
            task_status=task_status(
                task_payload
            ),
            task_response_json=task_payload,
        )

        (
            result_payload,
            item,
        ) = await wait_result(
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

        (
            archive_path,
            archive_hash,
        ) = save_archive(
            settings.archive_root,
            entity_id,
            product_group,
            window,
            task_id,
            content,
        )

        update_run(
            database,
            run_id,
            result_id=result_id,
            status="DOWNLOADED",

            download_status=str(
                item.get(
                    "downloadStatus"
                )
                or "SUCCESS"
            )[:32],

            result_response_json=result_payload,

            archive_path=str(
                archive_path
            ),

            archive_sha256=archive_hash,

            archive_size=len(
                content
            ),
        )

        (
            files,
            rows,
            inserted,
            updated,
            rejected,
        ) = import_archive(
            database,
            content,
            run_id,
            entity_id,
            product_group,
            group_code,
        )

        update_run(
            database,
            run_id,

            status=(
                "EMPTY"
                if rows == 0
                else "COMPLETED"
            ),

            csv_file_count=files,
            row_count=rows,
            inserted_count=inserted,
            updated_count=updated,
            rejected_count=rejected,

            finished_at=(
                datetime.now(
                    timezone.utc
                ).replace(
                    tzinfo=None
                )
            ),

            error_message=None,
        )

        return ViolationWindowSummary(
            run_id,
            window.period_from,
            window.period_to,
            task_id,
            result_id,
            files,
            rows,
            inserted,
            updated,
            rejected,
            str(
                archive_path
            ),
        )

    except Exception as exc:
        update_run(
            database,
            run_id,
            status="FAILED",

            finished_at=(
                datetime.now(
                    timezone.utc
                ).replace(
                    tzinfo=None
                )
            ),

            error_message=(
                f"{type(exc).__name__}: "
                f"{exc}"
            )[:4000],
        )

        raise


async def sync_violations(
    *,
    token: str,
    legal_entity_id: int,
    product_group: str,
    product_group_code: int,
    period_from: date,
    period_to: date,
    database: Database | None = None,
) -> ViolationSyncSummary:
    if (
        legal_entity_id < 1
        or product_group_code < 1
    ):
        raise ValueError(
            "Некорректный идентификатор "
            "организации или товарной группы."
        )

    product_group = (
        product_group
        .strip()
        .lower()
    )

    if not product_group:
        raise ValueError(
            "product_group не может быть пустым."
        )

    database = (
        database
        or Database(
            get_settings()
        )
    )

    settings = load_sync_settings()

    summaries: list[
        ViolationWindowSummary
    ] = []

    try:
        async with ViolationExportClient(
            get_settings(),
            token,
        ) as client:
            windows = export_windows(
                period_from,
                period_to,
            )

            for (
                index,
                window,
            ) in enumerate(
                windows,
                start=1,
            ):
                typer.echo(
                    "Отклонения "
                    f"{index}/{len(windows)}: "
                    f"{product_group} "
                    f"({product_group_code}); "
                    f"{window.period_from} — "
                    f"{window.period_to}."
                )

                summary = await sync_window(
                    client,
                    database,
                    settings,
                    legal_entity_id,
                    product_group,
                    product_group_code,
                    window,
                )

                summaries.append(
                    summary
                )

                typer.echo(
                    f"Строк={summary.row_count}; "
                    f"новых={summary.inserted_count}; "
                    f"обновлено={summary.updated_count}; "
                    f"отклонено={summary.rejected_count}."
                )

        mark_group(
            database,
            legal_entity_id,
            product_group,
            "SUCCESS",
            period_to,
            None,
        )

    except Exception as exc:
        mark_group(
            database,
            legal_entity_id,
            product_group,
            "ERROR",
            None,

            (
                f"{type(exc).__name__}: "
                f"{exc}"
            )[:2000],
        )

        raise

    return ViolationSyncSummary(
        legal_entity_id,
        product_group,
        product_group_code,
        period_from,
        period_to,
        len(
            summaries
        ),

        sum(
            item.row_count
            for item in summaries
        ),

        sum(
            item.inserted_count
            for item in summaries
        ),

        sum(
            item.updated_count
            for item in summaries
        ),

        sum(
            item.rejected_count
            for item in summaries
        ),

        tuple(
            summaries
        ),
    )


def group_code_from_db(
    database: Database,
    product_group: str,
) -> int:
    with database.transaction() as connection:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT product_group_code
                FROM gis_mt_product_group_dictionary
                WHERE product_group = %s
                  AND is_active = 1
                LIMIT 1
                """,
                (
                    product_group,
                ),
            )

            row = cursor.fetchone()

        finally:
            cursor.close()

    if not row:
        raise ValueError(
            "Не найден цифровой код "
            f"группы {product_group!r}."
        )

    return int(
        row[0]
    )


def cli_date(
    value: str,
    name: str,
) -> date:
    try:
        return date.fromisoformat(
            value.strip()
        )

    except ValueError as exc:
        raise typer.BadParameter(
            f"{name}: требуется формат YYYY-MM-DD."
        ) from exc


def main(
    legal_entity_id: int = typer.Option(
        ...,
        "--entity-id",
        min=1,
    ),

    product_group: str = typer.Option(
        ...,
        "--product-group",
    ),

    date_from: str = typer.Option(
        ...,
        "--date-from",
    ),

    date_to: str = typer.Option(
        ...,
        "--date-to",
    ),

    product_group_code: (
        int
        | None
    ) = typer.Option(
        None,
        "--product-group-code",
        min=1,
    ),
) -> None:
    token = read_token_from_stdin()

    database = Database(
        get_settings()
    )

    product_group = (
        product_group
        .strip()
        .lower()
    )

    group_code = (
        product_group_code

        or group_code_from_db(
            database,
            product_group,
        )
    )

    try:
        summary = asyncio.run(
            sync_violations(
                token=token,

                legal_entity_id=(
                    legal_entity_id
                ),

                product_group=(
                    product_group
                ),

                product_group_code=(
                    group_code
                ),

                period_from=cli_date(
                    date_from,
                    "date_from",
                ),

                period_to=cli_date(
                    date_to,
                    "date_to",
                ),

                database=database,
            )
        )

    except GisMtAuthError as exc:
        typer.echo(
            f"AUTH ERROR: {exc}",
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
        "Выгрузка отклонений завершена."
    )

    typer.echo(
        f"Строк: {summary.row_count}"
    )

    typer.echo(
        f"Новых: {summary.inserted_count}"
    )

    typer.echo(
        f"Обновлено: {summary.updated_count}"
    )

    typer.echo(
        "Отклонено при импорте: "
        f"{summary.rejected_count}"
    )


if __name__ == "__main__":
    typer.run(
        main
    )