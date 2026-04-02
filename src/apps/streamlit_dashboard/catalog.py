"""Read-model builders for the Streamlit signal-card dashboard.

This module is intentionally UI-agnostic so its behavior can be fully
characterized in unit/integration tests before Streamlit rendering is added.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from src.services.signal_cards.dashboard_catalog import build_ticker_signal_coverage_views
from src.services.signal_card_schema import SignalCardWithAccession


SIGNAL_CARD_BLOB_SUFFIX = "/signal_card.json"
SIGNAL_CARD_BLOB_PREFIX = "processed/signals/"


@dataclass(frozen=True)
class TickerDashboardEntry:
    ticker: str
    company_name: str
    available_years: list[int]
    cards: list[SignalCardWithAccession]
    malformed_cards: int = 0


def parse_signal_card_blob_name(blob_name: str) -> tuple[str, str] | None:
    """Parse ticker/accession from a standard signal card blob path."""
    if not blob_name.startswith(SIGNAL_CARD_BLOB_PREFIX):
        return None
    if not blob_name.endswith(SIGNAL_CARD_BLOB_SUFFIX):
        return None

    parts = blob_name.split("/")
    if len(parts) != 5:
        return None

    _, _, ticker, accession, filename = parts
    if filename != "signal_card.json":
        return None
    if not ticker.strip() or not accession.strip():
        return None
    return ticker, accession


def collect_processed_accessions(blob_names: list[str]) -> dict[str, list[str]]:
    """Collect accessions by ticker from discovered signal card blob names."""
    by_ticker: dict[str, list[str]] = {}
    for blob_name in blob_names:
        parsed = parse_signal_card_blob_name(blob_name)
        if not parsed:
            continue
        ticker, accession = parsed
        by_ticker.setdefault(ticker, []).append(accession)
    return by_ticker


def select_latest_five_years(cards: list[SignalCardWithAccession]) -> list[SignalCardWithAccession]:
    """Return up to five cards, one per fiscal year, sorted by descending year.

    If multiple filings exist for the same fiscal year, prefer the one with the
    lexicographically greatest filing_date (ISO date string expected).
    """
    best_per_year: dict[int, SignalCardWithAccession] = {}
    for card in cards:
        current = best_per_year.get(card.fiscal_year)
        if current is None or card.filing_date > current.filing_date:
            best_per_year[card.fiscal_year] = card

    return [
        best_per_year[year]
        for year in sorted(best_per_year.keys(), reverse=True)[:5]
    ]


def _load_card(blob_bytes: bytes, fallback_accession: str) -> SignalCardWithAccession:
    raw = json.loads(blob_bytes.decode("utf-8"))
    if "accession" not in raw:
        raw["accession"] = fallback_accession
    return SignalCardWithAccession.model_validate(raw)


def build_ticker_dashboard_entries(
    ticker_companies: list[dict[str, str]],
    list_blob_names: Callable[[], list[str]],
    download_blob: Callable[[str], bytes],
) -> list[TickerDashboardEntry]:
    """Build dashboard entries for tickers that currently have valid signal cards."""
    coverage_views = build_ticker_signal_coverage_views(
        ticker_companies=ticker_companies,
        list_blob_names=list_blob_names,
        download_blob=download_blob,
    )

    return [
        TickerDashboardEntry(
            ticker=view.ticker,
            company_name=view.company_name,
            available_years=view.available_years,
            cards=view.cards,
            malformed_cards=view.malformed_cards,
        )
        for view in coverage_views
    ]
