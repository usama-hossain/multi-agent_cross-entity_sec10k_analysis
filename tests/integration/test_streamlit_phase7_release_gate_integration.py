"""Phase 7 integration contracts for production release gating and rollback signal."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.apps.streamlit_dashboard.release_gate import (
    build_release_decision,
    run_release_smoke_checks,
)


@dataclass
class OverviewRow:
    ticker: str


@dataclass
class OverviewPage:
    rows: list[OverviewRow]


@dataclass
class DetailPage:
    state: str


class FakeRuntime:
    def __init__(self, tickers: list[str], detail_state: str = "ready"):
        self._tickers = tickers
        self._detail_state = detail_state

    def load_overview(self, search_query: str):
        return OverviewPage(rows=[OverviewRow(ticker=t) for t in self._tickers])

    def load_detail(self, ticker: str, fiscal_year: int | None):
        return DetailPage(state=self._detail_state)


@pytest.mark.integration
def test_release_gate__passes_when_overview_non_empty_and_required_ticker_ready():
    runtime = FakeRuntime(tickers=["VST", "EQIX"], detail_state="ready")

    smoke = run_release_smoke_checks(runtime=runtime, required_ticker="VST")
    decision = build_release_decision(smoke)

    assert smoke.overview_count == 2
    assert smoke.required_ticker_found is True
    assert smoke.required_ticker_detail_ready is True
    assert decision.ready_to_release is True
    assert decision.rollback_recommended is False


@pytest.mark.integration
def test_release_gate__fails_and_recommends_rollback_when_required_ticker_missing():
    runtime = FakeRuntime(tickers=["EQIX"], detail_state="ready")

    smoke = run_release_smoke_checks(runtime=runtime, required_ticker="VST")
    decision = build_release_decision(smoke)

    assert smoke.required_ticker_found is False
    assert decision.ready_to_release is False
    assert decision.rollback_recommended is True
    assert any("required ticker" in r.lower() for r in decision.reasons)


@pytest.mark.integration
def test_release_gate__fails_when_required_ticker_detail_not_ready():
    runtime = FakeRuntime(tickers=["VST"], detail_state="empty")

    smoke = run_release_smoke_checks(runtime=runtime, required_ticker="VST")
    decision = build_release_decision(smoke)

    assert smoke.required_ticker_found is True
    assert smoke.required_ticker_detail_ready is False
    assert decision.ready_to_release is False
