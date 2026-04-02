"""Integration tests for Streamlit dashboard ticker/card read-model assembly."""

import json

import pytest

from src.apps.streamlit_dashboard.catalog import build_ticker_dashboard_entries


def _build_payload(ticker: str, accession: str, year: int, filing_date: str) -> bytes:
    return json.dumps(
        {
            "ticker": ticker,
            "accession": accession,
            "fiscal_year": year,
            "filing_date": filing_date,
            "capital_allocation": {
                "capex_direction": "growing",
                "capex_details": "multi-year program",
                "capex_split": "generation heavy",
                "language_tone": "confident",
            },
            "supply_chain_tightness": [
                {"signal": "minor delays", "severity": "moderate", "evidence": "supplier commentary"}
            ],
            "demand_signals": {
                "customer_growth": "up",
                "backlog_direction": "growing",
                "load_changes": "up",
                "evidence": "commercial updates",
            },
            "new_risk_factors": [{"risk": "inflation", "category": "macro", "evidence": "risk section"}],
            "escalated_risk_factors": [
                {
                    "risk": "weather",
                    "category": "operations",
                    "prior_language_summary": "known",
                    "current_language_summary": "elevated",
                    "evidence": "risk deltas",
                }
            ],
            "regulatory_exposure": {
                "pending_rate_cases": "one",
                "emissions_mandates": "tightening",
                "compliance_investments": "increasing",
                "evidence": "regulatory update",
            },
            "strategic_posture": {
                "direction": "expansion",
                "summary": "capacity build",
                "evidence": "strategy narrative",
            },
            "generation_mix_shift": {
                "coal_retirements": "planned",
                "renewable_additions": "significant",
                "battery_storage": "expanding",
                "dispatchable_adequacy": "maintained",
                "evidence": "portfolio section",
            },
            "fuel_and_input_exposure": {
                "price_sensitivity": "high",
                "hedging_changes": "increased",
                "ppa_terms": "longer duration",
                "evidence": "fuel strategy",
            },
        }
    ).encode("utf-8")


@pytest.mark.integration
class TestStreamlitDashboardCatalogIntegration:
    def test_catalog_assembly__full_and_partial_coverage__returns_ordered_entries(self):
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
            "processed/signals/VST/vst-2020/signal_card.json",
            "processed/signals/EQIX/eqix-2025/signal_card.json",
            "processed/signals/EQIX/eqix-2024/signal_card.json",
            "processed/signals/UNLISTED/x/signal_card.json",
        ]

        payloads = {
            f"processed/signals/VST/vst-{year}/signal_card.json": _build_payload("VST", f"vst-{year}", year, f"{year}-12-31")
            for year in [2025, 2024, 2023, 2022, 2021, 2020]
        }
        payloads["processed/signals/EQIX/eqix-2025/signal_card.json"] = _build_payload("EQIX", "eqix-2025", 2025, "2025-11-30")
        payloads["processed/signals/EQIX/eqix-2024/signal_card.json"] = _build_payload("EQIX", "eqix-2024", 2024, "2024-11-30")
        payloads["processed/signals/UNLISTED/x/signal_card.json"] = _build_payload("UNLISTED", "x", 2025, "2025-01-01")

        entries = build_ticker_dashboard_entries(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=lambda blob_name: payloads[blob_name],
        )

        assert [entry.ticker for entry in entries] == ["VST", "EQIX"]
        assert entries[0].available_years == [2025, 2024, 2023, 2022, 2021]
        assert [card.fiscal_year for card in entries[0].cards] == [2025, 2024, 2023, 2022, 2021]
        assert entries[1].available_years == [2025, 2024]

    def test_catalog_assembly__all_payloads_invalid_for_ticker__excludes_ticker(self):
        ticker_companies = [{"ticker": "VST", "name": "Vistra"}]
        blob_names = [
            "processed/signals/VST/vst-a/signal_card.json",
            "processed/signals/VST/vst-b/signal_card.json",
        ]

        payloads = {
            "processed/signals/VST/vst-a/signal_card.json": b"{}",
            "processed/signals/VST/vst-b/signal_card.json": b"{\"ticker\":\"VST\"}",
        }

        entries = build_ticker_dashboard_entries(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=lambda blob_name: payloads[blob_name],
        )

        assert entries == []

    def test_catalog_assembly__no_matching_processed_blobs__returns_empty(self):
        entries = build_ticker_dashboard_entries(
            ticker_companies=[{"ticker": "VST", "name": "Vistra"}],
            list_blob_names=lambda: ["processed/md/VST/acc/10-K.md"],
            download_blob=lambda _: b"{}",
        )

        assert entries == []
