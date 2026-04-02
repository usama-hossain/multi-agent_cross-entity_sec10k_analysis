"""Phase 2 contract tests for Streamlit data-source behavior.

Tests in this module define requirements only (TDD red phase):
- Source of truth comes from blob signal-card files.
- Data source returns configured tickers with latest five years.
- Data source uses caching to avoid repeated blob scans/downloads.
- Data source emits observability metrics for fetch/parsing behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from src.services.signal_cards.streamlit_data_source import (  # noqa: F401 - intentionally red-phase import
    StreamlitSignalCardDataSource,
)


@dataclass
class FakeTickerConfigProvider:
    tickers: list[dict[str, str]]

    def get_ticker_companies(self) -> list[dict[str, str]]:
        return self.tickers


class FakeBlobStore:
    def __init__(self, blob_names: list[str], payloads: dict[str, bytes]):
        self._blob_names = blob_names
        self._payloads = payloads
        self.list_calls = 0
        self.download_calls = 0

    def list_blobs(self, prefix: str) -> list[str]:
        self.list_calls += 1
        return [name for name in self._blob_names if name.startswith(prefix)]

    def download_blob(self, blob_name: str) -> bytes:
        self.download_calls += 1
        return self._payloads[blob_name]


def _signal_payload(ticker: str, accession: str, year: int, filing_date: str) -> bytes:
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


@pytest.mark.unit
class TestStreamlitDataSourceContract:
    def test_catalog__reads_signal_cards_from_blob_and_returns_latest_five_years(self):
        blob_names = [
            f"processed/signals/VST/vst-{year}/signal_card.json"
            for year in [2025, 2024, 2023, 2022, 2021, 2020]
        ]
        payloads = {
            f"processed/signals/VST/vst-{year}/signal_card.json": _signal_payload("VST", f"vst-{year}", year, f"{year}-12-31")
            for year in [2025, 2024, 2023, 2022, 2021, 2020]
        }

        ds = StreamlitSignalCardDataSource(
            blob_store=FakeBlobStore(blob_names=blob_names, payloads=payloads),
            ticker_config=FakeTickerConfigProvider(tickers=[{"ticker": "VST", "name": "Vistra"}]),
            ttl_seconds=30,
        )

        result = ds.get_ticker_catalog()

        assert [entry.ticker for entry in result.entries] == ["VST"]
        assert result.entries[0].available_years == [2025, 2024, 2023, 2022, 2021]

    def test_catalog__within_ttl_uses_cache_and_avoids_repeat_blob_calls(self):
        blob_names = ["processed/signals/EQIX/eqix-2025/signal_card.json"]
        payloads = {
            "processed/signals/EQIX/eqix-2025/signal_card.json": _signal_payload("EQIX", "eqix-2025", 2025, "2025-12-31")
        }
        blob = FakeBlobStore(blob_names=blob_names, payloads=payloads)

        ds = StreamlitSignalCardDataSource(
            blob_store=blob,
            ticker_config=FakeTickerConfigProvider(tickers=[{"ticker": "EQIX", "name": "Equinix"}]),
            ttl_seconds=300,
        )

        ds.get_ticker_catalog()
        ds.get_ticker_catalog()

        assert blob.list_calls == 1
        assert blob.download_calls == 1

    def test_catalog__after_ttl_expiry_refreshes_blob_inventory(self):
        blob_names = ["processed/signals/NEE/nee-2025/signal_card.json"]
        payloads = {
            "processed/signals/NEE/nee-2025/signal_card.json": _signal_payload("NEE", "nee-2025", 2025, "2025-12-31")
        }
        blob = FakeBlobStore(blob_names=blob_names, payloads=payloads)

        class FakeClock:
            def __init__(self):
                self.now = 10_000.0

            def time(self) -> float:
                return self.now

        clock = FakeClock()
        ds = StreamlitSignalCardDataSource(
            blob_store=blob,
            ticker_config=FakeTickerConfigProvider(tickers=[{"ticker": "NEE", "name": "NextEra"}]),
            ttl_seconds=60,
            now_fn=clock.time,
        )

        ds.get_ticker_catalog()
        clock.now += 61.0
        ds.get_ticker_catalog()

        assert blob.list_calls == 2

    def test_catalog__returns_observability_metrics_for_scan_and_parse(self):
        blob_names = [
            "processed/signals/VST/vst-good/signal_card.json",
            "processed/signals/VST/vst-bad/signal_card.json",
        ]
        payloads = {
            "processed/signals/VST/vst-good/signal_card.json": _signal_payload("VST", "vst-good", 2025, "2025-12-31"),
            "processed/signals/VST/vst-bad/signal_card.json": b"{}",
        }

        ds = StreamlitSignalCardDataSource(
            blob_store=FakeBlobStore(blob_names=blob_names, payloads=payloads),
            ticker_config=FakeTickerConfigProvider(tickers=[{"ticker": "VST", "name": "Vistra"}]),
            ttl_seconds=30,
        )

        result = ds.get_ticker_catalog()

        assert result.metrics.blobs_scanned == 2
        assert result.metrics.cards_loaded == 1
        assert result.metrics.malformed_cards == 1
        assert result.metrics.fetch_duration_ms >= 0.0
