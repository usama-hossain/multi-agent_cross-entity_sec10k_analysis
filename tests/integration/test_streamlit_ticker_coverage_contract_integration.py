"""Integration characterization for ticker/card listing coverage behavior."""

import json

import pytest

from src.services.signal_cards.dashboard_catalog import build_ticker_signal_coverage_views


def _payload(ticker: str, accession: str, year: int) -> bytes:
    return json.dumps(
        {
            "ticker": ticker,
            "accession": accession,
            "fiscal_year": year,
            "filing_date": f"{year}-12-31",
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


@pytest.mark.integration
def test_ticker_coverage_integration__configured_processed_tickers_only_with_coverage_status():
    ticker_companies = [
        {"ticker": "VST", "name": "Vistra"},
        {"ticker": "EQIX", "name": "Equinix"},
        {"ticker": "NEE", "name": "NextEra"},
    ]

    blob_names = [
        "processed/signals/VST/vst-2025/signal_card.json",
        "processed/signals/VST/vst-2024/signal_card.json",
        "processed/signals/VST/vst-2023/signal_card.json",
        "processed/signals/VST/vst-2022/signal_card.json",
        "processed/signals/VST/vst-2021/signal_card.json",
        "processed/signals/EQIX/eqix-2025/signal_card.json",
        "processed/signals/OUTSIDE/ext-2025/signal_card.json",
    ]
    payloads = {
        "processed/signals/VST/vst-2025/signal_card.json": _payload("VST", "vst-2025", 2025),
        "processed/signals/VST/vst-2024/signal_card.json": _payload("VST", "vst-2024", 2024),
        "processed/signals/VST/vst-2023/signal_card.json": _payload("VST", "vst-2023", 2023),
        "processed/signals/VST/vst-2022/signal_card.json": _payload("VST", "vst-2022", 2022),
        "processed/signals/VST/vst-2021/signal_card.json": _payload("VST", "vst-2021", 2021),
        "processed/signals/EQIX/eqix-2025/signal_card.json": _payload("EQIX", "eqix-2025", 2025),
        "processed/signals/OUTSIDE/ext-2025/signal_card.json": _payload("OUTSIDE", "ext-2025", 2025),
    }

    views = build_ticker_signal_coverage_views(
        ticker_companies=ticker_companies,
        list_blob_names=lambda: blob_names,
        download_blob=lambda blob_name: payloads[blob_name],
    )

    assert [v.ticker for v in views] == ["VST", "EQIX"]
    assert views[0].coverage_complete is True
    assert views[1].coverage_complete is False
    assert views[1].missing_years == [2024, 2023, 2022, 2021]
