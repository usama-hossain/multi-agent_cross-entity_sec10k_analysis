"""Phase 3 Streamlit UI specification tests (contracts only).

These tests intentionally target a not-yet-implemented UI view-model layer.
"""

from __future__ import annotations

import json

import pytest

from src.apps.streamlit_dashboard.view_models import (  # noqa: F401 - red-phase import
    build_overview_page_model,
    build_ticker_detail_page_model,
)
from src.services.signal_card_schema import SignalCardWithAccession
from src.services.signal_cards.dashboard_catalog import TickerSignalCoverageView
from src.services.signal_cards.streamlit_data_source import (
    TickerCatalogMetrics,
    TickerCatalogResult,
)


def _card_payload(ticker: str, accession: str, year: int, filing_date: str) -> bytes:
    return json.dumps(
        {
            "ticker": ticker,
            "accession": accession,
            "fiscal_year": year,
            "filing_date": filing_date,
            "capital_allocation": {
                "capex_direction": "stable",
                "capex_details": "stable",
                "capex_split": "balanced",
                "language_tone": "neutral",
            },
            "supply_chain_tightness": [{"signal": "ok", "severity": "low", "evidence": "n/a"}],
            "demand_signals": {
                "customer_growth": "steady",
                "backlog_direction": "stable",
                "load_changes": "flat",
                "evidence": "n/a",
            },
            "new_risk_factors": [{"risk": "none", "category": "general", "evidence": "n/a"}],
            "escalated_risk_factors": [
                {
                    "risk": "none",
                    "category": "general",
                    "prior_language_summary": "none",
                    "current_language_summary": "none",
                    "evidence": "n/a",
                }
            ],
            "regulatory_exposure": {
                "pending_rate_cases": "none",
                "emissions_mandates": "none",
                "compliance_investments": "none",
                "evidence": "n/a",
            },
            "strategic_posture": {"direction": "stable", "summary": "steady", "evidence": "n/a"},
            "generation_mix_shift": {
                "coal_retirements": "none",
                "renewable_additions": "some",
                "battery_storage": "some",
                "dispatchable_adequacy": "adequate",
                "evidence": "n/a",
            },
            "fuel_and_input_exposure": {
                "price_sensitivity": "moderate",
                "hedging_changes": "unchanged",
                "ppa_terms": "stable",
                "evidence": "n/a",
            },
        }
    ).encode("utf-8")


def _card(ticker: str, accession: str, year: int, filing_date: str) -> SignalCardWithAccession:
    return SignalCardWithAccession.model_validate_json(_card_payload(ticker, accession, year, filing_date))


def _catalog_result() -> TickerCatalogResult:
    vst = TickerSignalCoverageView(
        ticker="VST",
        company_name="Vistra",
        expected_years=[2025, 2024, 2023, 2022, 2021],
        available_years=[2025, 2024, 2023, 2022, 2021],
        missing_years=[],
        coverage_complete=True,
        cards=[
            _card("VST", "vst-2025", 2025, "2025-12-31"),
            _card("VST", "vst-2024", 2024, "2024-12-31"),
            _card("VST", "vst-2023", 2023, "2023-12-31"),
            _card("VST", "vst-2022", 2022, "2022-12-31"),
            _card("VST", "vst-2021", 2021, "2021-12-31"),
        ],
        malformed_cards=0,
    )
    eqix = TickerSignalCoverageView(
        ticker="EQIX",
        company_name="Equinix",
        expected_years=[2025, 2024, 2023, 2022, 2021],
        available_years=[2025, 2023],
        missing_years=[2024, 2022, 2021],
        coverage_complete=False,
        cards=[
            _card("EQIX", "eqix-2025", 2025, "2025-11-30"),
            _card("EQIX", "eqix-2023", 2023, "2023-11-30"),
        ],
        malformed_cards=1,
    )
    return TickerCatalogResult(
        entries=[vst, eqix],
        metrics=TickerCatalogMetrics(
            blobs_scanned=8,
            cards_loaded=7,
            malformed_cards=1,
            fetch_duration_ms=12.5,
        ),
    )


@pytest.mark.unit
class TestStreamlitOverviewPageSpec:
    def test_overview__shows_processed_ticker_rows_with_coverage_fields(self):
        page = build_overview_page_model(catalog_result=_catalog_result(), search_query="")

        assert page.empty_state is None
        assert [row.ticker for row in page.rows] == ["VST", "EQIX"]
        assert page.rows[0].coverage_status == "complete"
        assert page.rows[1].coverage_status == "partial"
        assert page.rows[1].missing_years == [2024, 2022, 2021]

    def test_overview__search_filters_by_ticker_or_company_case_insensitive(self):
        by_ticker = build_overview_page_model(catalog_result=_catalog_result(), search_query="eqix")
        by_company = build_overview_page_model(catalog_result=_catalog_result(), search_query="vistra")

        assert [row.ticker for row in by_ticker.rows] == ["EQIX"]
        assert [row.ticker for row in by_company.rows] == ["VST"]

    def test_overview__no_matching_rows_returns_empty_state_message(self):
        page = build_overview_page_model(catalog_result=_catalog_result(), search_query="does-not-exist")

        assert page.rows == []
        assert page.empty_state == "No processed tickers match the current filter."


@pytest.mark.unit
class TestStreamlitTickerDetailPageSpec:
    def test_detail__ui_spec__selecting_ticker_shows_signal_cards(self):
        """
        When a ticker is selected, the detail page model should provide its signal cards for display.
        """
        detail = build_ticker_detail_page_model(
            catalog_result=_catalog_result(),
            ticker="EQIX",
            fiscal_year=None,
        )
        # Should be in ready state and cards should match available years for EQIX
        assert detail.state == "ready"
        assert detail.ticker == "EQIX"
        assert [card.fiscal_year for card in detail.cards] == [2025, 2023]

    def test_detail__returns_selected_ticker_cards_sorted_desc_year(self):
        detail = build_ticker_detail_page_model(
            catalog_result=_catalog_result(),
            ticker="VST",
            fiscal_year=None,
        )

        assert detail.state == "ready"
        assert [card.fiscal_year for card in detail.cards] == [2025, 2024, 2023, 2022, 2021]

    def test_detail__year_filter_returns_single_year_when_available(self):
        detail = build_ticker_detail_page_model(
            catalog_result=_catalog_result(),
            ticker="EQIX",
            fiscal_year=2023,
        )

        assert detail.state == "ready"
        assert [card.fiscal_year for card in detail.cards] == [2023]

    def test_detail__missing_ticker_returns_not_found_state(self):
        detail = build_ticker_detail_page_model(
            catalog_result=_catalog_result(),
            ticker="NEE",
            fiscal_year=None,
        )

        assert detail.state == "not_found"
        assert detail.cards == []

    def test_detail__unavailable_year_filter_returns_empty_state(self):
        detail = build_ticker_detail_page_model(
            catalog_result=_catalog_result(),
            ticker="EQIX",
            fiscal_year=2024,
        )

        assert detail.state == "empty"
        assert detail.cards == []
        assert detail.message == "No signal card is available for the selected year."
