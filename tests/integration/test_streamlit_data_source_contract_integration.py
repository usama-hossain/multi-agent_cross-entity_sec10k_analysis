"""Phase 2 integration contract tests for Streamlit data-source wiring.

These tests define integration expectations for adapter/config composition
without introducing live Azure dependencies in the default suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.signal_cards.streamlit_data_source import (  # noqa: F401 - intentionally red-phase import
    JsonTickerConfigProvider,
    StreamlitSignalCardDataSource,
)


class RecordingBlobStore:
    def __init__(self, blobs: dict[str, bytes]):
        self._blobs = blobs
        self.prefixes_seen: list[str] = []
        self.downloaded: list[str] = []

    def list_blobs(self, prefix: str) -> list[str]:
        self.prefixes_seen.append(prefix)
        return [name for name in self._blobs if name.startswith(prefix)]

    def download_blob(self, blob_name: str) -> bytes:
        self.downloaded.append(blob_name)
        return self._blobs[blob_name]


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
def test_data_source_integration__uses_json_ticker_config_and_blob_prefix_filter(tmp_path: Path):
    tickers_file = tmp_path / "tickers.json"
    tickers_file.write_text(
        json.dumps(
            {
                "ecosystem": {
                    "companies": [
                        {"ticker": "VST", "name": "Vistra"},
                        {"ticker": "EQIX", "name": "Equinix"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    blobs = {
        "processed/signals/VST/vst-2025/signal_card.json": _payload("VST", "vst-2025", 2025),
        "processed/signals/OUTSIDE/ext-2025/signal_card.json": _payload("OUTSIDE", "ext-2025", 2025),
    }
    blob_store = RecordingBlobStore(blobs=blobs)

    ds = StreamlitSignalCardDataSource(
        blob_store=blob_store,
        ticker_config=JsonTickerConfigProvider(config_path=str(tickers_file)),
        ttl_seconds=60,
    )

    result = ds.get_ticker_catalog()

    assert blob_store.prefixes_seen == ["processed/signals/"]
    assert [entry.ticker for entry in result.entries] == ["VST"]
    assert result.entries[0].available_years == [2025]


@pytest.mark.integration
def test_data_source_integration__emits_zero_entries_for_configured_but_unprocessed_tickers(tmp_path: Path):
    tickers_file = tmp_path / "tickers.json"
    tickers_file.write_text(
        json.dumps(
            {
                "ecosystem": {
                    "companies": [
                        {"ticker": "NEE", "name": "NextEra"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    ds = StreamlitSignalCardDataSource(
        blob_store=RecordingBlobStore(blobs={}),
        ticker_config=JsonTickerConfigProvider(config_path=str(tickers_file)),
        ttl_seconds=60,
    )

    result = ds.get_ticker_catalog()

    assert result.entries == []
    assert result.metrics.blobs_scanned == 0
    assert result.metrics.cards_loaded == 0
