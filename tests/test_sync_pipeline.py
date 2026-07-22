from pathlib import Path
from typing import Any

import pytest

import app.sync_pipeline as pipeline
from app.load_core_documents import CoreLoadSummary
from app.sync_document_details import (
    DocumentDetailsSyncSummary,
)
from app.sync_edo_documents import EdoSyncSummary


def make_details_summary(
    *,
    run_id: int = 55,
    unique_count: int = 2,
    successful_count: int = 2,
    failed_count: int = 0,
) -> DocumentDetailsSyncSummary:
    return DocumentDetailsSyncSummary(
        run_id=run_id,
        run_uuid="test-run-uuid",
        list_request_count=1,
        leaf_window_count=1,
        split_count=0,
        unique_document_count=unique_count,
        successful_document_count=(
            successful_count
        ),
        failed_document_count=failed_count,
        duplicate_document_count=0,
    )


def make_core_summary(
    *,
    run_id: int = 55,
    selected_count: int = 2,
    processed_count: int = 2,
    conflict_count: int = 0,
    failed_count: int = 0,
) -> CoreLoadSummary:
    return CoreLoadSummary(
        run_id=run_id,
        selected_count=selected_count,
        processed_count=processed_count,
        conflict_count=conflict_count,
        failed_count=failed_count,
    )


def execute_test_pipeline(
    **overrides: Any,
) -> pipeline.PipelineSummary:
    arguments: dict[str, Any] = {
        "token": "test-token",
        "product_group": "beer",
        "date_from": (
            "2026-07-01T00:00:00Z"
        ),
        "date_to": (
            "2026-07-02T00:00:00Z"
        ),
        "limit": 100,
        "max_pages": 1000,
        "details_delay_ms": 0,
        "batch_size": 50,
        "edo_delay_ms": 0,
        "edo_output_root": Path(
            "/tmp/edo"
        ),
        "skip_edo": False,
        "force_edo": False,
        "edo_fail_fast": False,
        "database": object(),
    }

    arguments.update(
        overrides
    )

    return pipeline.execute_pipeline(
        **arguments
    )


def test_pipeline_skips_core_and_edo_when_no_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sync_document_details(
        **_: Any,
    ) -> DocumentDetailsSyncSummary:
        return make_details_summary(
            unique_count=0,
            successful_count=0,
        )

    def unexpected_core_call(
        **_: Any,
    ) -> CoreLoadSummary:
        raise AssertionError(
            "CORE не должен запускаться."
        )

    async def unexpected_edo_call(
        **_: Any,
    ) -> EdoSyncSummary:
        raise AssertionError(
            "ЭДО не должно запускаться."
        )

    monkeypatch.setattr(
        pipeline,
        "sync_document_details",
        fake_sync_document_details,
    )

    monkeypatch.setattr(
        pipeline,
        "load_core_documents",
        unexpected_core_call,
    )

    monkeypatch.setattr(
        pipeline,
        "sync_edo_documents",
        unexpected_edo_call,
    )

    summary = execute_test_pipeline()

    assert summary.details_run_id == 55

    assert (
        summary.unique_document_count
        == 0
    )

    assert (
        summary.core_processed_count
        == 0
    )

    assert (
        summary.edo_selected_count
        == 0
    )

    assert summary.edo_skipped is True


def test_pipeline_calls_core_directly_and_skips_edo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core_calls: list[
        dict[str, Any]
    ] = []

    async def fake_sync_document_details(
        **_: Any,
    ) -> DocumentDetailsSyncSummary:
        return make_details_summary()

    def fake_load_core_documents(
        **kwargs: Any,
    ) -> CoreLoadSummary:
        core_calls.append(
            kwargs
        )

        return make_core_summary()

    async def unexpected_edo_call(
        **_: Any,
    ) -> EdoSyncSummary:
        raise AssertionError(
            "ЭДО не должно запускаться "
            "при --skip-edo."
        )

    monkeypatch.setattr(
        pipeline,
        "sync_document_details",
        fake_sync_document_details,
    )

    monkeypatch.setattr(
        pipeline,
        "load_core_documents",
        fake_load_core_documents,
    )

    monkeypatch.setattr(
        pipeline,
        "sync_edo_documents",
        unexpected_edo_call,
    )

    summary = execute_test_pipeline(
        skip_edo=True
    )

    assert len(core_calls) == 1

    assert (
        core_calls[0]["run_id"]
        == 55
    )

    assert (
        core_calls[0]["batch_size"]
        == 50
    )

    assert (
        core_calls[0]["echo_progress"]
        is True
    )

    assert (
        summary.core_selected_count
        == 2
    )

    assert (
        summary.core_processed_count
        == 2
    )

    assert (
        summary.edo_selected_count
        == 0
    )

    assert summary.edo_skipped is True


def test_pipeline_runs_edo_after_successful_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edo_calls: list[
        dict[str, Any]
    ] = []

    async def fake_sync_document_details(
        **_: Any,
    ) -> DocumentDetailsSyncSummary:
        return make_details_summary()

    def fake_load_core_documents(
        **_: Any,
    ) -> CoreLoadSummary:
        return make_core_summary()

    async def fake_sync_edo_documents(
        **kwargs: Any,
    ) -> EdoSyncSummary:
        edo_calls.append(
            kwargs
        )

        return EdoSyncSummary(
            run_id=55,
            selected_count=1,
            unsupported_type_count=1,
            missing_uuid_count=0,
            already_processed_count=1,
            downloaded_count=0,
            matched_count=0,
            error_count=0,
        )

    monkeypatch.setattr(
        pipeline,
        "sync_document_details",
        fake_sync_document_details,
    )

    monkeypatch.setattr(
        pipeline,
        "load_core_documents",
        fake_load_core_documents,
    )

    monkeypatch.setattr(
        pipeline,
        "sync_edo_documents",
        fake_sync_edo_documents,
    )

    summary = execute_test_pipeline()

    assert len(edo_calls) == 1

    assert (
        edo_calls[0]["run_id"]
        == 55
    )

    assert (
        edo_calls[0]["token"]
        == "test-token"
    )

    assert (
        summary.edo_selected_count
        == 1
    )

    assert (
        summary.edo_already_processed_count
        == 1
    )

    assert (
        summary.edo_downloaded_count
        == 0
    )

    assert (
        summary.edo_error_count
        == 0
    )

    assert summary.edo_skipped is False


def test_pipeline_rejects_core_source_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sync_document_details(
        **_: Any,
    ) -> DocumentDetailsSyncSummary:
        return make_details_summary(
            unique_count=2,
            successful_count=2,
        )

    def fake_load_core_documents(
        **_: Any,
    ) -> CoreLoadSummary:
        return make_core_summary(
            selected_count=1,
            processed_count=1,
        )

    async def unexpected_edo_call(
        **_: Any,
    ) -> EdoSyncSummary:
        raise AssertionError(
            "ЭДО не должно запускаться "
            "после ошибки CORE."
        )

    monkeypatch.setattr(
        pipeline,
        "sync_document_details",
        fake_sync_document_details,
    )

    monkeypatch.setattr(
        pipeline,
        "load_core_documents",
        fake_load_core_documents,
    )

    monkeypatch.setattr(
        pipeline,
        "sync_edo_documents",
        unexpected_edo_call,
    )

    with pytest.raises(
        RuntimeError,
        match="CORE_SOURCE_COUNT_MISMATCH",
    ):
        execute_test_pipeline()