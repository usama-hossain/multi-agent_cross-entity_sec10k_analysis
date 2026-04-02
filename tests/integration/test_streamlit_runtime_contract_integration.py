"""Phase 4 integration contracts for Streamlit runtime and adapter composition."""

from __future__ import annotations

import json

import pytest

from src.apps.streamlit_dashboard.runtime import StreamlitDashboardRuntime
from src.services.signal_cards.streamlit_data_source import (
    JsonTickerConfigProvider,
    StreamlitSignalCardDataSource,
)


class FakeBlobStore:
    def __init__(self, blob_names: list[str], payloads: dict[str, bytes]):
        self._blob_names = blob_names
        self._payloads = payloads

    def list_blobs(self, prefix: str) -> list[str]:
        return [name for name in self._blob_names if name.startswith(prefix)]

    def download_blob(self, blob_name: str) -> bytes:
        return self._payloads[blob_name]


def _signal_payload(ticker: str, accession: str, year: int) -> bytes:
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
def test_runtime_integration__loads_overview_and_detail_models(tmp_path):
    config_file = tmp_path / "tickers.json"
    config_file.write_text(
        json.dumps(
            {
                "ecosystem": {
                    "companies": [
                        {"ticker": "VST", "name": "Vistra"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    blob_name = "processed/signals/VST/vst-2025/signal_card.json"
    blob_store = FakeBlobStore(
        blob_names=[blob_name],
        payloads={blob_name: _signal_payload("VST", "vst-2025", 2025)},
    )

    data_source = StreamlitSignalCardDataSource(
        blob_store=blob_store,
        ticker_config=JsonTickerConfigProvider(config_path=str(config_file)),
        ttl_seconds=60,
    )
    runtime = StreamlitDashboardRuntime(data_source=data_source)

    overview = runtime.load_overview(search_query="")
    detail = runtime.load_detail(ticker="VST", fiscal_year=2025)

    assert [row.ticker for row in overview.rows] == ["VST"]
    assert detail.state == "ready"
    assert [card.fiscal_year for card in detail.cards] == [2025]


@pytest.mark.integration
def test_runtime_integration__detail_returns_not_found_for_unknown_ticker(tmp_path):
    config_file = tmp_path / "tickers.json"
    config_file.write_text(
        json.dumps({"ecosystem": {"companies": [{"ticker": "VST", "name": "Vistra"}]}}),
        encoding="utf-8",
    )

    blob_name = "processed/signals/VST/vst-2025/signal_card.json"
    blob_store = FakeBlobStore(
        blob_names=[blob_name],
        payloads={blob_name: _signal_payload("VST", "vst-2025", 2025)},
    )

    runtime = StreamlitDashboardRuntime(
        data_source=StreamlitSignalCardDataSource(
            blob_store=blob_store,
            ticker_config=JsonTickerConfigProvider(config_path=str(config_file)),
            ttl_seconds=60,
        )
    )

    detail = runtime.load_detail(ticker="NEE", fiscal_year=None)

    assert detail.state == "not_found"
    assert detail.cards == []
