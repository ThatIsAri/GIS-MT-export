from __future__ import annotations

import hashlib
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path

import typer
from mysql.connector import MySQLConnection

from app.config import get_settings
from app.db import Database


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Версионированные миграции схемы MySQL проекта GIS MT Export.",
)


MIGRATION_FILE_PATTERN = re.compile(
    r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$"
)

MIGRATION_LOCK_NAME = "gis_mt_schema_migration"


BASELINE_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "sys_sync_run": {
        "id",
        "run_uuid",
        "job_type",
        "status",
        "date_from",
        "date_to",
        "records_received",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
    },
    "sys_api_request": {
        "id",
        "sync_run_id",
        "http_method",
        "endpoint",
        "request_params",
        "requested_at",
        "response_received_at",
        "http_status",
        "response_time_ms",
        "attempt_number",
        "status",
        "error_message",
        "created_at",
    },
    "raw_api_response": {
        "id",
        "sync_run_id",
        "api_request_id",
        "source_system",
        "endpoint",
        "external_entity_id",
        "payload_json",
        "payload_hash",
        "received_at",
        "processing_status",
        "processing_error",
        "created_at",
    },
    "core_document": {
        "id",
        "external_document_id",
        "doc_date",
        "received_at",
        "document_type",
        "document_status",
        "sender_inn",
        "sender_name",
        "receiver_inn",
        "receiver_name",
        "invoice_number",
        "invoice_date",
        "related_document_id",
        "turnover_type",
        "product_groups",
        "product_group_ids",
        "errors_json",
        "source_item_count",
        "normalization_status",
        "normalization_conflicts",
        "source_sync_run_id",
        "source_raw_response_id",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    },
    "raw_edo_document": {
        "id",
        "source_system",
        "source_message_id",
        "original_file_name",
        "relative_path",
        "mime_type",
        "file_size_bytes",
        "content_sha256",
        "detected_encoding",
        "xml_content",
        "xml_well_formed",
        "parse_status",
        "parse_error",
        "external_document_id",
        "edo_document_number",
        "edo_document_date",
        "seller_inn",
        "buyer_inn",
        "total_amount",
        "core_document_id",
        "match_status",
        "match_method",
        "match_score",
        "match_candidate_count",
        "match_candidates_json",
        "matched_at",
        "duplicate_count",
        "first_imported_at",
        "last_seen_at",
        "parsed_at",
    },
    "core_document_line": {
        "id",
        "raw_edo_document_id",
        "core_document_id",
        "external_document_id",
        "line_number",
        "source_line_number",
        "product_name",
        "product_code",
        "unit_code",
        "unit_name",
        "quantity",
        "unit_price",
        "amount_without_vat",
        "vat_rate",
        "vat_amount",
        "amount_with_vat",
        "source_payload_hash",
        "created_at",
        "updated_at",
    },
    "core_document_code": {
        "id",
        "raw_edo_document_id",
        "core_document_id",
        "document_line_id",
        "external_document_id",
        "line_number",
        "sequence_number",
        "source_element_name",
        "source_code_type",
        "transport_package_identifier",
        "code_text",
        "code_value",
        "code_char_length",
        "code_byte_length",
        "code_sha256",
        "created_at",
    },
}


BASELINE_REQUIRED_UNIQUE_INDEXES: set[tuple[str, str]] = {
    (
        "sys_sync_run",
        "uq_sys_sync_run_uuid",
    ),
    (
        "core_document",
        "uk_core_document_external_id",
    ),
    (
        "raw_edo_document",
        "uk_raw_edo_document_sha256",
    ),
    (
        "core_document_line",
        "uk_core_document_line_raw_line",
    ),
    (
        "core_document_code",
        "uk_core_document_code_source",
    ),
}


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    migration_type: str
    path: Path
    checksum: str
    sql: str


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    version: str
    name: str
    migration_type: str
    checksum: str
    status: str
    error_message: str | None


@dataclass(frozen=True, slots=True)
class MigrationState:
    version: str
    name: str
    state: str
    detail: str


def default_migrations_directory() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "migrations"
    )


def normalize_migration_text(
    value: str,
) -> str:
    """
    Нормализует BOM и окончания строк.

    Благодаря этому один и тот же SQL-файл
    имеет одинаковый checksum на Windows
    и Linux.
    """

    return (
        value
        .lstrip("\ufeff")
        .replace(
            "\r\n",
            "\n",
        )
        .replace(
            "\r",
            "\n",
        )
    )


def migration_checksum(
    value: str,
) -> str:
    normalized = normalize_migration_text(
        value
    )

    return hashlib.sha256(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()


def load_migrations(
    directory: Path,
) -> list[Migration]:
    """
    Загружает файлы вида:

        0001_baseline.sql
        0002_legal_entity.sql
        0003_add_tenant_columns.sql

    Версии должны идти последовательно,
    без пропусков и повторов.
    """

    if not directory.is_dir():
        raise RuntimeError(
            "Каталог миграций не найден: "
            f"{directory}"
        )

    migrations: list[Migration] = []
    seen_versions: set[str] = set()

    for path in sorted(
        directory.glob(
            "*.sql"
        )
    ):
        match = MIGRATION_FILE_PATTERN.fullmatch(
            path.name
        )

        if match is None:
            raise RuntimeError(
                "Некорректное имя файла миграции: "
                f"{path.name}. "
                "Ожидается NNNN_name.sql."
            )

        version = match.group(
            "version"
        )

        name = match.group(
            "name"
        )

        if version in seen_versions:
            raise RuntimeError(
                "Версия миграции "
                f"{version} используется повторно."
            )

        text = normalize_migration_text(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

        migration_type = (
            "BASELINE"
            if (
                version == "0001"
                and name == "baseline"
            )
            else "SQL"
        )

        migrations.append(
            Migration(
                version=version,
                name=name,
                migration_type=migration_type,
                path=path,
                checksum=migration_checksum(
                    text
                ),
                sql=text,
            )
        )

        seen_versions.add(
            version
        )

    if not migrations:
        raise RuntimeError(
            "В каталоге отсутствуют миграции: "
            f"{directory}"
        )

    numeric_versions = [
        int(item.version)
        for item in migrations
    ]

    if numeric_versions[0] != 1:
        raise RuntimeError(
            "Первая миграция должна "
            "иметь версию 0001."
        )

    expected_versions = list(
        range(
            1,
            len(numeric_versions) + 1,
        )
    )

    if numeric_versions != expected_versions:
        raise RuntimeError(
            "Версии миграций должны идти "
            "без пропусков: "
            "0001, 0002, 0003 и далее."
        )

    if (
        migrations[0].migration_type
        != "BASELINE"
    ):
        raise RuntimeError(
            "Миграция 0001 должна называться "
            "0001_baseline.sql."
        )

    return migrations


def split_sql_statements(
    sql: str,
) -> list[str]:
    """
    Делит SQL-файл на отдельные операторы.

    Точки с запятой внутри строк и имён
    не считаются разделителями.

    DELIMITER и хранимые процедуры
    текущим runner-ом не поддерживаются.
    """

    normalized = normalize_migration_text(
        sql
    )

    if re.search(
        r"(?im)^\s*DELIMITER\b",
        normalized,
    ):
        raise ValueError(
            "Директива DELIMITER "
            "в миграциях не поддерживается."
        )

    statements: list[str] = []
    buffer: list[str] = []

    state = "normal"
    index = 0

    while index < len(
        normalized
    ):
        character = normalized[
            index
        ]

        next_character = (
            normalized[index + 1]
            if index + 1 < len(normalized)
            else ""
        )

        if state == "normal":
            if character == "'":
                state = "single_quote"
                buffer.append(
                    character
                )

            elif character == '"':
                state = "double_quote"
                buffer.append(
                    character
                )

            elif character == "`":
                state = "backtick"
                buffer.append(
                    character
                )

            elif (
                character == "-"
                and next_character == "-"
                and (
                    index + 2
                    >= len(normalized)
                    or normalized[
                        index + 2
                    ].isspace()
                )
            ):
                state = "line_comment"
                index += 1

            elif character == "#":
                state = "line_comment"

            elif (
                character == "/"
                and next_character == "*"
            ):
                state = "block_comment"
                index += 1

            elif character == ";":
                statement = "".join(
                    buffer
                ).strip()

                if statement:
                    statements.append(
                        statement
                    )

                buffer = []

            else:
                buffer.append(
                    character
                )

        elif state == "line_comment":
            if character == "\n":
                buffer.append(
                    "\n"
                )

                state = "normal"

        elif state == "block_comment":
            if (
                character == "*"
                and next_character == "/"
            ):
                buffer.append(
                    " "
                )

                state = "normal"
                index += 1

        elif state in {
            "single_quote",
            "double_quote",
            "backtick",
        }:
            buffer.append(
                character
            )

            if (
                character == "\\"
                and index + 1
                < len(normalized)
            ):
                buffer.append(
                    next_character
                )

                index += 1

            else:
                closing_character = {
                    "single_quote": "'",
                    "double_quote": '"',
                    "backtick": "`",
                }[state]

                if (
                    character
                    == closing_character
                ):
                    if (
                        next_character
                        == closing_character
                    ):
                        buffer.append(
                            next_character
                        )

                        index += 1

                    else:
                        state = "normal"

        index += 1

    if state in {
        "single_quote",
        "double_quote",
        "backtick",
        "block_comment",
    }:
        raise ValueError(
            "В SQL миграции обнаружена "
            "незакрытая строка или комментарий."
        )

    tail = "".join(
        buffer
    ).strip()

    if tail:
        statements.append(
            tail
        )

    return statements


def ensure_migration_table(
    connection: MySQLConnection,
) -> None:
    """
    Создаёт bootstrap-таблицу runner-а.

    Эта таблица не является бизнес-таблицей
    и должна существовать до применения
    первой миграции.
    """

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS
                sys_schema_migration
            (
                version VARCHAR(20) NOT NULL,
                name VARCHAR(255) NOT NULL,
                migration_type VARCHAR(32) NOT NULL,
                checksum CHAR(64) NOT NULL,
                status VARCHAR(16) NOT NULL,

                started_at DATETIME(6) NOT NULL,
                applied_at DATETIME(6) NULL,

                execution_ms BIGINT UNSIGNED NULL,
                applied_by VARCHAR(255) NOT NULL,
                error_message VARCHAR(2000) NULL,

                PRIMARY KEY (version),

                KEY ix_sys_schema_migration_status (
                    status,
                    started_at
                )
            )
            ENGINE = InnoDB
            DEFAULT CHARACTER SET = utf8mb4
            COLLATE = utf8mb4_unicode_ci
            """
        )

    finally:
        cursor.close()

    connection.commit()


def read_migration_records(
    connection: MySQLConnection,
) -> list[MigrationRecord]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                version,
                name,
                migration_type,
                checksum,
                status,
                error_message
            FROM sys_schema_migration
            ORDER BY version
            """
        )

        rows = cursor.fetchall()

    finally:
        cursor.close()

    return [
        MigrationRecord(
            version=str(
                row["version"]
            ),
            name=str(
                row["name"]
            ),
            migration_type=str(
                row["migration_type"]
            ),
            checksum=str(
                row["checksum"]
            ),
            status=str(
                row["status"]
            ),
            error_message=(
                str(
                    row["error_message"]
                )
                if row[
                    "error_message"
                ]
                is not None
                else None
            ),
        )
        for row in rows
    ]


def evaluate_migration_states(
    migrations: list[Migration],
    records: list[MigrationRecord],
) -> list[MigrationState]:
    """
    Сопоставляет локальные файлы
    с состоянием БД.
    """

    records_by_version = {
        item.version: item
        for item in records
    }

    migrations_by_version = {
        item.version: item
        for item in migrations
    }

    states: list[
        MigrationState
    ] = []

    for migration in migrations:
        record = records_by_version.get(
            migration.version
        )

        if record is None:
            states.append(
                MigrationState(
                    version=migration.version,
                    name=migration.name,
                    state="PENDING",
                    detail="ожидает применения",
                )
            )

            continue

        if (
            record.name
            != migration.name
            or record.migration_type
            != migration.migration_type
            or record.checksum
            != migration.checksum
        ):
            states.append(
                MigrationState(
                    version=migration.version,
                    name=migration.name,
                    state="DRIFT",
                    detail=(
                        "файл отличается "
                        "от зарегистрированной миграции"
                    ),
                )
            )

            continue

        states.append(
            MigrationState(
                version=migration.version,
                name=migration.name,
                state=record.status,
                detail=(
                    record.error_message
                    or "зарегистрирована в БД"
                ),
            )
        )

    for record in records:
        if (
            record.version
            in migrations_by_version
        ):
            continue

        states.append(
            MigrationState(
                version=record.version,
                name=record.name,
                state="ORPHANED",
                detail=(
                    "запись есть в БД, "
                    "но файл миграции отсутствует"
                ),
            )
        )

    return sorted(
        states,
        key=lambda item: item.version,
    )


def current_schema_name(
    connection: MySQLConnection,
) -> str:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT DATABASE() AS schema_name
            """
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if (
        row is None
        or not row.get(
            "schema_name"
        )
    ):
        raise RuntimeError(
            "Не удалось определить "
            "текущую схему MySQL."
        )

    return str(
        row["schema_name"]
    )


def read_schema_columns(
    connection: MySQLConnection,
    schema_name: str,
) -> dict[str, set[str]]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                TABLE_NAME,
                COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s
            ORDER BY
                TABLE_NAME,
                ORDINAL_POSITION
            """,
            (
                schema_name,
            ),
        )

        rows = cursor.fetchall()

    finally:
        cursor.close()

    result: dict[
        str,
        set[str],
    ] = {}

    for row in rows:
        table_name = str(
            row["TABLE_NAME"]
        )

        column_name = str(
            row["COLUMN_NAME"]
        )

        result.setdefault(
            table_name,
            set(),
        ).add(
            column_name
        )

    return result


def read_unique_indexes(
    connection: MySQLConnection,
    schema_name: str,
) -> set[tuple[str, str]]:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT DISTINCT
                TABLE_NAME,
                INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s
              AND NON_UNIQUE = 0
            """,
            (
                schema_name,
            ),
        )

        rows = cursor.fetchall()

    finally:
        cursor.close()

    return {
        (
            str(
                row["TABLE_NAME"]
            ),
            str(
                row["INDEX_NAME"]
            ),
        )
        for row in rows
    }


def find_baseline_problems(
    columns_by_table: dict[
        str,
        set[str],
    ],
    unique_indexes: set[
        tuple[str, str]
    ],
) -> list[str]:
    """
    Проверяет, что существующая база
    соответствует рабочему пилотному контуру.
    """

    problems: list[str] = []

    for (
        table_name,
        required_columns,
    ) in BASELINE_REQUIRED_COLUMNS.items():
        actual_columns = (
            columns_by_table.get(
                table_name
            )
        )

        if actual_columns is None:
            problems.append(
                "отсутствует таблица "
                f"{table_name}"
            )

            continue

        missing_columns = sorted(
            required_columns
            - actual_columns
        )

        if missing_columns:
            problems.append(
                "в таблице "
                f"{table_name} "
                "отсутствуют колонки: "
                + ", ".join(
                    missing_columns
                )
            )

    for (
        table_name,
        index_name,
    ) in sorted(
        BASELINE_REQUIRED_UNIQUE_INDEXES
    ):
        if (
            table_name,
            index_name,
        ) not in unique_indexes:
            problems.append(
                "отсутствует уникальный индекс "
                f"{table_name}.{index_name}"
            )

    return problems


def validate_baseline_schema(
    connection: MySQLConnection,
) -> None:
    schema_name = current_schema_name(
        connection
    )

    columns_by_table = read_schema_columns(
        connection,
        schema_name,
    )

    unique_indexes = read_unique_indexes(
        connection,
        schema_name,
    )

    problems = find_baseline_problems(
        columns_by_table,
        unique_indexes,
    )

    if not problems:
        return

    formatted = "\n".join(
        f"- {item}"
        for item in problems
    )

    raise RuntimeError(
        "BASELINE_SCHEMA_MISMATCH: "
        "текущая схема не соответствует "
        "базовой версии 0001:\n"
        f"{formatted}"
    )


def acquire_migration_lock(
    connection: MySQLConnection,
    timeout_seconds: int,
) -> None:
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                GET_LOCK(%s, %s)
                AS acquired
            """,
            (
                MIGRATION_LOCK_NAME,
                timeout_seconds,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if (
        row is None
        or int(
            row["acquired"]
            or 0
        )
        != 1
    ):
        raise RuntimeError(
            "Не удалось получить "
            "блокировку миграций. "
            "Возможно, другой процесс "
            "уже изменяет схему."
        )


def release_migration_lock(
    connection: MySQLConnection,
) -> None:
    """
    Освобождает advisory lock MySQL.

    RELEASE_LOCK выполняется через SELECT,
    поэтому результат обязательно считывается
    до закрытия курсора.
    """

    cursor = connection.cursor(
        dictionary=True
    )

    row = None

    try:
        cursor.execute(
            """
            SELECT
                RELEASE_LOCK(%s)
                AS released
            """,
            (
                MIGRATION_LOCK_NAME,
            ),
        )

        row = cursor.fetchone()

    finally:
        cursor.close()

    if (
        row is None
        or row.get(
            "released"
        )
        is None
    ):
        raise RuntimeError(
            "MySQL не вернула результат "
            "RELEASE_LOCK."
        )

    if int(
        row["released"]
    ) != 1:
        raise RuntimeError(
            "Блокировка миграций не была "
            "освобождена текущим соединением."
        )


def record_migration_start(
    connection: MySQLConnection,
    migration: Migration,
) -> None:
    cursor = connection.cursor()

    applied_by = (
        f"{socket.gethostname()}"
        ":schema_migrations"
    )

    try:
        cursor.execute(
            """
            INSERT INTO sys_schema_migration (
                version,
                name,
                migration_type,
                checksum,
                status,
                started_at,
                applied_at,
                execution_ms,
                applied_by,
                error_message
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                'APPLYING',
                UTC_TIMESTAMP(6),
                NULL,
                NULL,
                %s,
                NULL
            )
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                migration_type =
                    VALUES(migration_type),
                checksum = VALUES(checksum),
                status = 'APPLYING',
                started_at =
                    UTC_TIMESTAMP(6),
                applied_at = NULL,
                execution_ms = NULL,
                applied_by =
                    VALUES(applied_by),
                error_message = NULL
            """,
            (
                migration.version,
                migration.name,
                migration.migration_type,
                migration.checksum,
                applied_by,
            ),
        )

    finally:
        cursor.close()

    connection.commit()


def record_migration_success(
    connection: MySQLConnection,
    migration: Migration,
    execution_ms: int,
) -> None:
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE sys_schema_migration
               SET status = 'APPLIED',
                   applied_at =
                       UTC_TIMESTAMP(6),
                   execution_ms = %s,
                   error_message = NULL
             WHERE version = %s
            """,
            (
                execution_ms,
                migration.version,
            ),
        )

    finally:
        cursor.close()

    connection.commit()


def record_migration_failure(
    connection: MySQLConnection,
    migration: Migration,
    execution_ms: int,
    exc: Exception,
) -> None:
    safe_error = (
        f"{type(exc).__name__}: {exc}"
    )[:2000]

    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            UPDATE sys_schema_migration
               SET status = 'FAILED',
                   execution_ms = %s,
                   error_message = %s
             WHERE version = %s
            """,
            (
                execution_ms,
                safe_error,
                migration.version,
            ),
        )

    finally:
        cursor.close()

    connection.commit()


def apply_migration(
    connection: MySQLConnection,
    migration: Migration,
) -> None:
    started_at = time.monotonic()

    record_migration_start(
        connection,
        migration,
    )

    try:
        if (
            migration.migration_type
            == "BASELINE"
        ):
            validate_baseline_schema(
                connection
            )

        else:
            statements = split_sql_statements(
                migration.sql
            )

            if not statements:
                raise RuntimeError(
                    "SQL-миграция "
                    f"{migration.version} "
                    "не содержит операторов."
                )

            cursor = connection.cursor()

            try:
                for statement in statements:
                    cursor.execute(
                        statement
                    )

            finally:
                cursor.close()

            connection.commit()

        execution_ms = int(
            (
                time.monotonic()
                - started_at
            )
            * 1000
        )

        record_migration_success(
            connection,
            migration,
            execution_ms,
        )

    except Exception as exc:
        connection.rollback()

        execution_ms = int(
            (
                time.monotonic()
                - started_at
            )
            * 1000
        )

        record_migration_failure(
            connection,
            migration,
            execution_ms,
            exc,
        )

        raise


def print_states(
    states: list[MigrationState],
) -> None:
    typer.echo(
        "Версия  Состояние  "
        "Миграция              Описание"
    )

    for item in states:
        typer.echo(
            f"{item.version:<7}  "
            f"{item.state:<9}  "
            f"{item.name:<20}  "
            f"{item.detail}"
        )


@app.command("status")
def status_command(
    migrations_dir: Path = typer.Option(
        default_migrations_directory(),
        "--migrations-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Каталог файлов NNNN_name.sql.",
    ),
) -> None:
    """
    Показывает состояние файлов миграций
    относительно текущей базы.
    """

    migrations = load_migrations(
        migrations_dir
    )

    database = Database(
        get_settings()
    )

    connection = database.connect()

    try:
        ensure_migration_table(
            connection
        )

        records = read_migration_records(
            connection
        )

        states = evaluate_migration_states(
            migrations,
            records,
        )

        print_states(
            states
        )

    finally:
        connection.close()

    blocking_states = {
        "DRIFT",
        "FAILED",
        "APPLYING",
        "ORPHANED",
    }

    if any(
        item.state in blocking_states
        for item in states
    ):
        raise typer.Exit(
            code=2
        )


@app.command("up")
def up_command(
    migrations_dir: Path = typer.Option(
        default_migrations_directory(),
        "--migrations-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Каталог файлов NNNN_name.sql.",
    ),
    retry_incomplete: bool = typer.Option(
        False,
        "--retry-incomplete",
        help=(
            "Повторить миграцию со статусом "
            "FAILED или APPLYING. "
            "Использовать только после проверки "
            "частично выполненного DDL."
        ),
    ),
    lock_timeout_seconds: int = typer.Option(
        30,
        "--lock-timeout-seconds",
        min=1,
        max=300,
        help=(
            "Ожидание глобальной "
            "блокировки миграций."
        ),
    ),
) -> None:
    """
    Применяет все ожидающие миграции
    в порядке версий.
    """

    migrations = load_migrations(
        migrations_dir
    )

    database = Database(
        get_settings()
    )

    connection = database.connect()
    lock_acquired = False

    try:
        ensure_migration_table(
            connection
        )

        acquire_migration_lock(
            connection,
            lock_timeout_seconds,
        )

        lock_acquired = True

        records = read_migration_records(
            connection
        )

        states = evaluate_migration_states(
            migrations,
            records,
        )

        states_by_version = {
            item.version: item
            for item in states
        }

        invalid_states = [
            item
            for item in states
            if item.state in {
                "DRIFT",
                "ORPHANED",
            }
        ]

        if invalid_states:
            print_states(
                states
            )

            raise RuntimeError(
                "Миграции не могут быть "
                "применены из-за состояния "
                "DRIFT или ORPHANED."
            )

        incomplete_states = [
            item
            for item in states
            if item.state in {
                "FAILED",
                "APPLYING",
            }
        ]

        if (
            incomplete_states
            and not retry_incomplete
        ):
            print_states(
                states
            )

            raise RuntimeError(
                "Обнаружена незавершённая "
                "миграция. После проверки схемы "
                "используйте --retry-incomplete."
            )

        applied_count = 0

        for migration in migrations:
            state = states_by_version[
                migration.version
            ].state

            if state == "APPLIED":
                continue

            typer.echo(
                "Применение "
                f"{migration.version}_"
                f"{migration.name} "
                f"({migration.migration_type})..."
            )

            apply_migration(
                connection,
                migration,
            )

            typer.echo(
                "Миграция "
                f"{migration.version} "
                "применена."
            )

            applied_count += 1

        if applied_count == 0:
            typer.echo(
                "Новых миграций нет. "
                "Схема актуальна."
            )

        else:
            typer.echo(
                "Применено миграций: "
                f"{applied_count}."
            )

    except typer.Exit:
        raise

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

    finally:
        if lock_acquired:
            try:
                release_migration_lock(
                    connection
                )

            except Exception as exc:
                typer.echo(
                    "WARNING: не удалось "
                    "освободить блокировку "
                    f"миграций: {exc}",
                    err=True,
                )

        connection.close()


if __name__ == "__main__":
    app()