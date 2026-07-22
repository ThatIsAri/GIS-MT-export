import io

import pytest
import typer
from typer.testing import CliRunner

import app.cli as cli


runner = CliRunner()


def test_read_token_from_stdin_accepts_plain_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        io.StringIO(
            "plain-token"
        ),
    )

    assert (
        cli.read_token_from_stdin()
        == "plain-token"
    )


def test_read_token_from_stdin_removes_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        io.StringIO(
            "Bearer bearer-token"
        ),
    )

    assert (
        cli.read_token_from_stdin()
        == "bearer-token"
    )


def test_read_token_from_stdin_reads_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        io.StringIO(
            '{"token":"json-token"}'
        ),
    )

    assert (
        cli.read_token_from_stdin()
        == "json-token"
    )


def test_read_token_from_stdin_reads_json_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli.sys,
        "stdin",
        io.StringIO(
            '"quoted-token"'
        ),
    )

    assert (
        cli.read_token_from_stdin()
        == "quoted-token"
    )


def test_parse_extra_params_returns_dictionary() -> None:
    assert cli.parse_extra_params(
        [
            "order=ASC",
            "limit=100",
        ]
    ) == {
        "order": "ASC",
        "limit": "100",
    }


def test_parse_extra_params_rejects_invalid_value() -> None:
    with pytest.raises(
        typer.BadParameter,
        match="key=value",
    ):
        cli.parse_extra_params(
            [
                "invalid",
            ]
        )


def test_parse_extra_params_rejects_duplicate_key() -> None:
    with pytest.raises(
        typer.BadParameter,
        match="повторно",
    ):
        cli.parse_extra_params(
            [
                "order=ASC",
                "order=DESC",
            ]
        )


def test_deprecated_sync_document_list_is_blocked() -> None:
    result = runner.invoke(
        cli.app,
        [
            "sync-document-list",
            "--pg",
            "beer",
            "--date-from",
            "2026-07-01T00:00:00Z",
            "--date-to",
            "2026-07-21T00:00:00Z",
            "--limit",
            "100",
            "--max-pages",
            "1000",
        ],
    )

    assert result.exit_code == 2

    assert (
        "команда sync-document-list отключена"
        in result.output
    )

    assert (
        "адаптивное деление периода"
        in result.output
    )