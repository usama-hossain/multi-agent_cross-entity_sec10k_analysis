"""Phase 6 contracts for pre-production validation checks."""

from __future__ import annotations

import pytest

from src.apps.streamlit_dashboard.preflight import (
    PreflightCheck,
    run_preflight_checks,
)


class FakeBlobStoreHealthy:
    def list_blobs(self, prefix: str):
        return []


class FakeBlobStoreBroken:
    def list_blobs(self, prefix: str):
        raise RuntimeError("cannot access blob storage")


class FakeRuntimeHealthy:
    def load_overview(self, search_query: str):
        return {"ok": True}


class FakeRuntimeBroken:
    def load_overview(self, search_query: str):
        raise RuntimeError("runtime failed")


@pytest.mark.unit
def test_preflight__passes_when_storage_config_and_runtime_and_blob_access_are_ok():
    report = run_preflight_checks(
        env={"BLOB_ACCOUNT_URL": "https://acct.blob.core.windows.net"},
        blob_store=FakeBlobStoreHealthy(),
        runtime=FakeRuntimeHealthy(),
    )

    assert report.passed is True
    assert [c.name for c in report.checks if c.passed] == [
        "storage_configuration",
        "blob_access",
        "runtime_overview_load",
    ]


@pytest.mark.unit
def test_preflight__fails_when_storage_configuration_missing():
    report = run_preflight_checks(
        env={},
        blob_store=FakeBlobStoreHealthy(),
        runtime=FakeRuntimeHealthy(),
    )

    check = next(c for c in report.checks if c.name == "storage_configuration")
    assert check.passed is False
    assert "AzureWebJobsStorage" in check.message


@pytest.mark.unit
def test_preflight__captures_blob_or_runtime_failures_without_throwing():
    report = run_preflight_checks(
        env={"AzureWebJobsStorage": "UseDevelopmentStorage=true"},
        blob_store=FakeBlobStoreBroken(),
        runtime=FakeRuntimeBroken(),
    )

    by_name = {c.name: c for c in report.checks}
    assert by_name["blob_access"].passed is False
    assert by_name["runtime_overview_load"].passed is False
    assert report.passed is False


@pytest.mark.unit
def test_preflight__report_is_structured_with_named_checks():
    report = run_preflight_checks(
        env={"AzureWebJobsStorage": "x"},
        blob_store=FakeBlobStoreHealthy(),
        runtime=FakeRuntimeHealthy(),
    )

    assert all(isinstance(c, PreflightCheck) for c in report.checks)
    assert len(report.checks) == 3
