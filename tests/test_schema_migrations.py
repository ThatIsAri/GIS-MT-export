from __future__ import annotations

from pathlib import Path

import pytest

from app.schema_migrations import (
    Migration,
    MigrationRecord,
    evaluate_migration_states,
    find_baseline_problems,
    load_migrations,
    migration_checksum,
    normalize_migration_text,
    split_sql_statements,
)


def write_migration(
    directory: Path,
    name: str,
    content: str,
) -> Path:
    path = (
        directory
        / name
    )

    path.write_text(
        content,
        encoding="utf-8",
    )

    return path


def make_migration(
    *,
    version: str,
    name: str,
    checksum: str = "a" * 64,
) -> Migration:
    return Migration(
        version=version,
        name=name,
        migration_type=(
            "BASELINE"
            if version == "0001"
            else "SQL"
        ),
        path=Path(
            f"{version}_{name}.sql"
        ),
        checksum=checksum,
        sql="",
    )


def test_normalize_migration_text_removes_bom_and_normalizes_lines() -> None:
    assert normalize_migration_text(
        "\ufeffA\r\nB\rC"
    ) == "A\nB\nC"


def test_migration_checksum_is_stable_for_lf_and_crlf() -> None:
    assert migration_checksum(
        "SELECT 1;\n"
    ) == migration_checksum(
        "SELECT 1;\r\n"
    )


def test_load_migrations_reads_order_and_types(
    tmp_path: Path,
) -> None:
    write_migration(
        tmp_path,
        "0001_baseline.sql",
        "-- baseline\n",
    )

    write_migration(
        tmp_path,
        "0002_add_table.sql",
        "CREATE TABLE test (id INT);\n",
    )

    migrations = load_migrations(
        tmp_path
    )

    assert [
        item.version
        for item in migrations
    ] == [
        "0001",
        "0002",
    ]

    assert (
        migrations[0].migration_type
        == "BASELINE"
    )

    assert (
        migrations[1].migration_type
        == "SQL"
    )


def test_load_migrations_rejects_missing_baseline(
    tmp_path: Path,
) -> None:
    write_migration(
        tmp_path,
        "0001_create_table.sql",
        "CREATE TABLE test (id INT);\n",
    )

    with pytest.raises(
        RuntimeError,
        match="0001_baseline.sql",
    ):
        load_migrations(
            tmp_path
        )


def test_load_migrations_rejects_version_gap(
    tmp_path: Path,
) -> None:
    write_migration(
        tmp_path,
        "0001_baseline.sql",
        "-- baseline\n",
    )

    write_migration(
        tmp_path,
        "0003_gap.sql",
        "SELECT 1;\n",
    )

    with pytest.raises(
        RuntimeError,
        match="без пропусков",
    ):
        load_migrations(
            tmp_path
        )


def test_load_migrations_rejects_duplicate_version(
    tmp_path: Path,
) -> None:
    write_migration(
        tmp_path,
        "0001_baseline.sql",
        "-- baseline\n",
    )

    write_migration(
        tmp_path,
        "0001_other.sql",
        "SELECT 1;\n",
    )

    with pytest.raises(
        RuntimeError,
        match="используется повторно",
    ):
        load_migrations(
            tmp_path
        )


def test_split_sql_statements_handles_comments_and_multiple_queries() -> None:
    sql = """
    -- first statement
    CREATE TABLE example (id INT);

    # second statement
    INSERT INTO example (id) VALUES (1);
    """

    assert split_sql_statements(
        sql
    ) == [
        "CREATE TABLE example (id INT)",
        "INSERT INTO example (id) VALUES (1)",
    ]


def test_split_sql_statements_preserves_semicolons_inside_strings() -> None:
    sql = """
    INSERT INTO example (value)
    VALUES ('a;b');

    INSERT INTO example (value)
    VALUES ("c;d");
    """

    assert split_sql_statements(
        sql
    ) == [
        (
            "INSERT INTO example (value)\n"
            "    VALUES ('a;b')"
        ),
        (
            "INSERT INTO example (value)\n"
            '    VALUES ("c;d")'
        ),
    ]


def test_split_sql_statements_rejects_delimiter_directive() -> None:
    with pytest.raises(
        ValueError,
        match="DELIMITER",
    ):
        split_sql_statements(
            "DELIMITER //\nSELECT 1//"
        )


def test_evaluate_migration_states_detects_applied_and_pending() -> None:
    migrations = [
        make_migration(
            version="0001",
            name="baseline",
            checksum="1" * 64,
        ),
        make_migration(
            version="0002",
            name="next",
            checksum="2" * 64,
        ),
    ]

    records = [
        MigrationRecord(
            version="0001",
            name="baseline",
            migration_type="BASELINE",
            checksum="1" * 64,
            status="APPLIED",
            error_message=None,
        )
    ]

    states = evaluate_migration_states(
        migrations,
        records,
    )

    assert [
        (
            item.version,
            item.state,
        )
        for item in states
    ] == [
        (
            "0001",
            "APPLIED",
        ),
        (
            "0002",
            "PENDING",
        ),
    ]


def test_evaluate_migration_states_detects_drift() -> None:
    migrations = [
        make_migration(
            version="0001",
            name="baseline",
            checksum="1" * 64,
        )
    ]

    records = [
        MigrationRecord(
            version="0001",
            name="baseline",
            migration_type="BASELINE",
            checksum="x" * 64,
            status="APPLIED",
            error_message=None,
        )
    ]

    states = evaluate_migration_states(
        migrations,
        records,
    )

    assert (
        states[0].state
        == "DRIFT"
    )


def test_evaluate_migration_states_detects_orphaned_record() -> None:
    migrations = [
        make_migration(
            version="0001",
            name="baseline",
            checksum="1" * 64,
        )
    ]

    records = [
        MigrationRecord(
            version="0002",
            name="missing_file",
            migration_type="SQL",
            checksum="2" * 64,
            status="APPLIED",
            error_message=None,
        )
    ]

    states = evaluate_migration_states(
        migrations,
        records,
    )

    assert [
        (
            item.version,
            item.state,
        )
        for item in states
    ] == [
        (
            "0001",
            "PENDING",
        ),
        (
            "0002",
            "ORPHANED",
        ),
    ]


def test_find_baseline_problems_reports_missing_objects() -> None:
    problems = find_baseline_problems(
        columns_by_table={
            "sys_sync_run": {
                "id",
            }
        },
        unique_indexes=set(),
    )

    assert any(
        "sys_sync_run" in item
        and "run_uuid" in item
        for item in problems
    )

    assert any(
        "core_document" in item
        for item in problems
    )

    assert any(
        "uq_sys_sync_run_uuid" in item
        for item in problems
    )