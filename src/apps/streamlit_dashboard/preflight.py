"""Pre-production checks for Streamlit dashboard deployment validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    passed: bool
    checks: list[PreflightCheck]


def _storage_configuration_check(env: dict[str, str]) -> PreflightCheck:
    has_connection_string = bool(str(env.get("AzureWebJobsStorage", "")).strip())
    has_account_url = bool(str(env.get("BLOB_ACCOUNT_URL", "")).strip())
    passed = has_connection_string or has_account_url
    message = "Storage configuration present."
    if not passed:
        message = "Missing storage configuration: set AzureWebJobsStorage or BLOB_ACCOUNT_URL."
    return PreflightCheck(name="storage_configuration", passed=passed, message=message)


def _blob_access_check(blob_store: Any) -> PreflightCheck:
    try:
        blob_store.list_blobs(prefix="processed/signals/")
        return PreflightCheck(name="blob_access", passed=True, message="Blob listing succeeded.")
    except Exception as exc:
        return PreflightCheck(name="blob_access", passed=False, message=f"Blob access failed: {exc}")


def _runtime_overview_check(runtime: Any) -> PreflightCheck:
    try:
        runtime.load_overview(search_query="")
        return PreflightCheck(name="runtime_overview_load", passed=True, message="Overview load succeeded.")
    except Exception as exc:
        return PreflightCheck(name="runtime_overview_load", passed=False, message=f"Overview load failed: {exc}")


def run_preflight_checks(env: dict[str, str], blob_store: Any, runtime: Any) -> PreflightReport:
    checks = [
        _storage_configuration_check(env),
        _blob_access_check(blob_store),
        _runtime_overview_check(runtime),
    ]
    return PreflightReport(passed=all(c.passed for c in checks), checks=checks)
