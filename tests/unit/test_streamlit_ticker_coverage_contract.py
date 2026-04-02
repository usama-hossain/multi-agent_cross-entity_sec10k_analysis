"""TDD contract tests for ticker + five-year signal-card coverage behavior."""

import json

import pytest

from src.services.signal_cards.dashboard_catalog import build_ticker_signal_coverage_views


def _card_payload(ticker: str, accession: str, fiscal_year: int, filing_date: str) -> bytes:
    payload = {
        "ticker": ticker,
        "accession": accession,
        "fiscal_year": fiscal_year,
        "filing_date": filing_date,
        "capital_allocation": {
            "capex_direction": "stable",
            "capex_details": "stable investment",
            "capex_split": "balanced",
            "language_tone": "neutral",
        },
        "supply_chain_tightness": [{"signal": "normal", "severity": "low", "evidence": "stable supply"}],
        "demand_signals": {
            "customer_growth": "steady",
            "backlog_direction": "stable",
            "load_changes": "flat",
            "evidence": "consistent demand",
        },
        "new_risk_factors": [{"risk": "none material", "category": "general", "evidence": "n/a"}],
        "escalated_risk_factors": [
            {
                "risk": "weather volatility",
                "category": "operations",
                "prior_language_summary": "limited impact",
                "current_language_summary": "slightly elevated",
                "evidence": "management commentary",
            }
        ],
        "regulatory_exposure": {
            "pending_rate_cases": "none",
            "emissions_mandates": "stable",
            "compliance_investments": "ongoing",
            "evidence": "regulatory section",
        },
        "strategic_posture": {
            "direction": "stable",
            "summary": "steady execution",
            "evidence": "strategy section",
        },
        "generation_mix_shift": {
            "coal_retirements": "none",
            "renewable_additions": "incremental",
            "battery_storage": "pilot",
            "dispatchable_adequacy": "adequate",
            "evidence": "generation section",
        },
        "fuel_and_input_exposure": {
            "price_sensitivity": "moderate",
            "hedging_changes": "unchanged",
            "ppa_terms": "stable",
            "evidence": "fuel section",
        },
    }
    return json.dumps(payload).encode("utf-8")


@pytest.mark.unit
class TestTickerCoverageContract:
    def test_ticker_coverage__partial_five_year_data__computes_missing_years(self):
        ticker_companies = [{"ticker": "EQIX", "name": "Equinix"}]
        blob_names = [
            "processed/signals/EQIX/eqix-2025/signal_card.json",
            "processed/signals/EQIX/eqix-2023/signal_card.json",
        ]
        payloads = {
            "processed/signals/EQIX/eqix-2025/signal_card.json": _card_payload("EQIX", "eqix-2025", 2025, "2025-12-31"),
            "processed/signals/EQIX/eqix-2023/signal_card.json": _card_payload("EQIX", "eqix-2023", 2023, "2023-12-31"),
        }

        views = build_ticker_signal_coverage_views(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=lambda blob_name: payloads[blob_name],
        )

        assert len(views) == 1
        assert views[0].ticker == "EQIX"
        assert views[0].expected_years == [2025, 2024, 2023, 2022, 2021]
        assert views[0].available_years == [2025, 2023]
        assert views[0].missing_years == [2024, 2022, 2021]
        assert views[0].coverage_complete is False

    def test_ticker_coverage__full_five_year_data__marks_complete(self):
        ticker_companies = [{"ticker": "VST", "name": "Vistra"}]
        blob_names = [f"processed/signals/VST/vst-{year}/signal_card.json" for year in [2025, 2024, 2023, 2022, 2021]]
        payloads = {
            blob: _card_payload("VST", f"vst-{year}", year, f"{year}-12-31")
            for blob, year in zip(blob_names, [2025, 2024, 2023, 2022, 2021])
        }

        views = build_ticker_signal_coverage_views(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=lambda blob_name: payloads[blob_name],
        )

        assert len(views) == 1
        assert views[0].available_years == [2025, 2024, 2023, 2022, 2021]
        assert views[0].missing_years == []
        assert views[0].coverage_complete is True
