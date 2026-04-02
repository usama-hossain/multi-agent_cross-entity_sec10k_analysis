"""Phase 3 integration specification tests for Streamlit page-model orchestration."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.apps.streamlit_dashboard.controllers import (  # noqa: F401 - red-phase import
    load_ticker_detail_page_model,
    load_ticker_overview_page_model,
)
from src.services.signal_cards.dashboard_catalog import TickerSignalCoverageView
from src.services.signal_cards.streamlit_data_source import (
    TickerCatalogMetrics,
    TickerCatalogResult,
)


@dataclass
class DummyCard:
    ticker: str
    accession: str
    fiscal_year: int
    filing_date: str


class FakeDataSource:
    def __init__(self, result: TickerCatalogResult):
        self._result = result
        self.calls = 0

    def get_ticker_catalog(self) -> TickerCatalogResult:
        self.calls += 1
        return self._result


def _result_fixture() -> TickerCatalogResult:
    entries = [
        TickerSignalCoverageView(
            ticker="VST",
            company_name="Vistra",
            expected_years=[2025, 2024, 2023, 2022, 2021],
            available_years=[2025, 2024, 2023, 2022, 2021],
            missing_years=[],
            coverage_complete=True,
            cards=[
                DummyCard("VST", "vst-2025", 2025, "2025-12-31"),
                DummyCard("VST", "vst-2024", 2024, "2024-12-31"),
            ],
            malformed_cards=0,
        ),
        TickerSignalCoverageView(
            ticker="EQIX",
            company_name="Equinix",
            expected_years=[2025, 2024, 2023, 2022, 2021],
            available_years=[2025, 2023],
            missing_years=[2024, 2022, 2021],
            coverage_complete=False,
            cards=[DummyCard("EQIX", "eqix-2025", 2025, "2025-11-30")],
            malformed_cards=2,
        ),
    ]
    return TickerCatalogResult(
        entries=entries,
        metrics=TickerCatalogMetrics(
            blobs_scanned=7,
            cards_loaded=3,
            malformed_cards=2,
            fetch_duration_ms=10.0,
        ),
    )


@pytest.mark.integration
def test_overview_controller__loads_catalog_once_and_exposes_metrics_banner():
    ds = FakeDataSource(result=_result_fixture())

    page = load_ticker_overview_page_model(data_source=ds, search_query="")

    assert ds.calls == 1
    assert page.metrics.blobs_scanned == 7
    assert page.metrics.cards_loaded == 3
    assert page.warning_banner == "2 malformed signal card file(s) were skipped."


@pytest.mark.integration
def test_detail_controller__returns_not_found_when_ticker_absent():
    ds = FakeDataSource(result=_result_fixture())

    page = load_ticker_detail_page_model(data_source=ds, ticker="NEE", fiscal_year=None)

    assert ds.calls == 1
    assert page.state == "not_found"
    assert page.cards == []


@pytest.mark.integration
def test_detail_controller__applies_year_filter_from_request():
    ds = FakeDataSource(result=_result_fixture())

    page = load_ticker_detail_page_model(data_source=ds, ticker="VST", fiscal_year=2024)

    assert ds.calls == 1
    assert page.state == "ready"
    assert [card.fiscal_year for card in page.cards] == [2024]
