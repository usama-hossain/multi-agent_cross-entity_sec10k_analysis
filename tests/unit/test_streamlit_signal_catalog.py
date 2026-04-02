"""Characterization tests for Streamlit signal-card dashboard read-model behavior."""

import json

import pytest

from src.apps.streamlit_dashboard.catalog import (
    SIGNAL_CARD_BLOB_PREFIX,
    SIGNAL_CARD_BLOB_SUFFIX,
    build_ticker_dashboard_entries,
    collect_processed_accessions,
    parse_signal_card_blob_name,
    select_latest_five_years,
)
from src.services.signal_card_schema import SignalCardWithAccession


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
        "supply_chain_tightness": [
            {"signal": "normal", "severity": "low", "evidence": "stable supply"}
        ],
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
class TestSignalCardBlobPathParsing:
    def test_parse_blob_name__valid_signal_card_path__returns_ticker_and_accession(self):
        blob = "processed/signals/EQIX/0001628280-25-005126/signal_card.json"
        assert parse_signal_card_blob_name(blob) == ("EQIX", "0001628280-25-005126")

    def test_parse_blob_name__non_signal_path_or_suffix__returns_none(self):
        assert parse_signal_card_blob_name("processed/md/EQIX/123/10-K.md") is None
        assert parse_signal_card_blob_name("processed/signals/EQIX/123/signal_card.txt") is None

    def test_collect_processed_accessions__mix_of_valid_invalid_paths__keeps_only_valid(self):
        blob_names = [
            f"{SIGNAL_CARD_BLOB_PREFIX}EQIX/acc-1{SIGNAL_CARD_BLOB_SUFFIX}",
            f"{SIGNAL_CARD_BLOB_PREFIX}EQIX/acc-2{SIGNAL_CARD_BLOB_SUFFIX}",
            f"{SIGNAL_CARD_BLOB_PREFIX}VST/acc-3{SIGNAL_CARD_BLOB_SUFFIX}",
            "processed/md/EQIX/acc-9/10-K.md",
        ]

        assert collect_processed_accessions(blob_names) == {
            "EQIX": ["acc-1", "acc-2"],
            "VST": ["acc-3"],
        }


@pytest.mark.unit
class TestFiveYearSelection:
    def test_select_latest_five_years__more_than_five_cards__returns_latest_five_years(self):
        cards = [
            SignalCardWithAccession.model_validate_json(
                _card_payload("EQIX", f"acc-{year}", year, f"{year}-12-31")
            )
            for year in range(2019, 2026)
        ]

        selected = select_latest_five_years(cards)
        assert [card.fiscal_year for card in selected] == [2025, 2024, 2023, 2022, 2021]

    def test_select_latest_five_years__duplicate_year__keeps_latest_filing_date(self):
        cards = [
            SignalCardWithAccession.model_validate_json(_card_payload("EQIX", "acc-old", 2025, "2025-01-10")),
            SignalCardWithAccession.model_validate_json(_card_payload("EQIX", "acc-new", 2025, "2025-02-15")),
            SignalCardWithAccession.model_validate_json(_card_payload("EQIX", "acc-2024", 2024, "2024-12-31")),
        ]

        selected = select_latest_five_years(cards)
        assert [card.accession for card in selected] == ["acc-new", "acc-2024"]


@pytest.mark.unit
class TestDashboardEntryAssembly:
    def test_build_entries__only_processed_configured_tickers__returns_expected_subset(self):
        ticker_companies = [
            {"ticker": "EQIX", "name": "Equinix"},
            {"ticker": "VST", "name": "Vistra"},
            {"ticker": "NEE", "name": "NextEra"},
        ]

        blob_names = [
            "processed/signals/EQIX/eqix-2025/signal_card.json",
            "processed/signals/EQIX/eqix-2024/signal_card.json",
            "processed/signals/VST/vst-2025/signal_card.json",
            "processed/signals/UNLISTED/x/signal_card.json",
        ]

        payloads = {
            "processed/signals/EQIX/eqix-2025/signal_card.json": _card_payload("EQIX", "eqix-2025", 2025, "2025-12-31"),
            "processed/signals/EQIX/eqix-2024/signal_card.json": _card_payload("EQIX", "eqix-2024", 2024, "2024-12-31"),
            "processed/signals/VST/vst-2025/signal_card.json": _card_payload("VST", "vst-2025", 2025, "2025-11-30"),
            "processed/signals/UNLISTED/x/signal_card.json": _card_payload("UNLISTED", "x", 2025, "2025-01-01"),
        }

        entries = build_ticker_dashboard_entries(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=lambda name: payloads[name],
        )

        assert [entry.ticker for entry in entries] == ["EQIX", "VST"]
        assert entries[0].available_years == [2025, 2024]
        assert entries[1].available_years == [2025]

    def test_build_entries__malformed_blob_payload__skips_blob_and_tracks_count(self):
        ticker_companies = [{"ticker": "EQIX", "name": "Equinix"}]
        blob_names = [
            "processed/signals/EQIX/eqix-good/signal_card.json",
            "processed/signals/EQIX/eqix-bad/signal_card.json",
        ]
        payloads = {
            "processed/signals/EQIX/eqix-good/signal_card.json": _card_payload("EQIX", "eqix-good", 2025, "2025-12-31"),
            "processed/signals/EQIX/eqix-bad/signal_card.json": b"{\"ticker\":\"EQIX\"}",
        }

        entries = build_ticker_dashboard_entries(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=lambda name: payloads[name],
        )

        assert len(entries) == 1
        assert entries[0].ticker == "EQIX"
        assert [card.accession for card in entries[0].cards] == ["eqix-good"]
        assert entries[0].malformed_cards == 1
