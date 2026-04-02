"""Dashboard catalog logic for ticker signal-card coverage views.

Service-layer ownership: compute read models from blob inventory + card payloads.
UI layers consume these contracts and should not reimplement this logic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from src.services.signal_card_schema import SignalCardWithAccession


SIGNAL_CARD_BLOB_PREFIX = "processed/signals/"
SIGNAL_CARD_BLOB_SUFFIX = "/signal_card.json"


@dataclass(frozen=True)
class TickerSignalCoverageView:
    ticker: str
    company_name: str
    expected_years: list[int]
    available_years: list[int]
    missing_years: list[int]
    coverage_complete: bool
    cards: list[SignalCardWithAccession]
    malformed_cards: int = 0


def _parse_signal_card_blob_name(blob_name: str) -> tuple[str, str] | None:
    if not blob_name.startswith(SIGNAL_CARD_BLOB_PREFIX):
        return None
    if not blob_name.endswith(SIGNAL_CARD_BLOB_SUFFIX):
        return None
    parts = blob_name.split("/")
    if len(parts) != 5:
        return None
    _, _, ticker, accession, filename = parts
    if filename != "signal_card.json" or not ticker.strip() or not accession.strip():
        return None
    return ticker, accession


def _collect_accessions_by_ticker(blob_names: list[str]) -> dict[str, list[str]]:
    by_ticker: dict[str, list[str]] = {}
    for blob_name in blob_names:
        parsed = _parse_signal_card_blob_name(blob_name)
        if not parsed:
            continue
        ticker, accession = parsed
        by_ticker.setdefault(ticker, []).append(accession)
    return by_ticker


def _load_card(blob_bytes: bytes, accession: str) -> SignalCardWithAccession:
    raw = json.loads(blob_bytes.decode("utf-8"))
    if "accession" not in raw:
        raw["accession"] = accession
    return SignalCardWithAccession.model_validate(raw)


def _select_latest_five_years(cards: list[SignalCardWithAccession]) -> list[SignalCardWithAccession]:
    # Keep one filing per fiscal year and prefer the latest filing date.
    best_per_year: dict[int, SignalCardWithAccession] = {}
    for card in cards:
        current = best_per_year.get(card.fiscal_year)
        if current is None or card.filing_date > current.filing_date:
            best_per_year[card.fiscal_year] = card

    return [best_per_year[year] for year in sorted(best_per_year.keys(), reverse=True)[:5]]


def _expected_years_from_available(available_years: list[int]) -> list[int]:
    if not available_years:
        return []
    max_year = max(available_years)
    return [max_year - offset for offset in range(5)]


def build_ticker_signal_coverage_views(
    ticker_companies: list[dict[str, str]],
    list_blob_names: Callable[[], list[str]],
    download_blob: Callable[[str], bytes],
) -> list[TickerSignalCoverageView]:
    """Build per-ticker five-year coverage views from signal-card blobs."""
    accessions_by_ticker = _collect_accessions_by_ticker(list_blob_names())
    views: list[TickerSignalCoverageView] = []

    for company in ticker_companies:
        ticker = str(company.get("ticker", "")).strip()
        if not ticker:
            continue
        company_name = str(company.get("name", "")).strip() or ticker
        accessions = accessions_by_ticker.get(ticker, [])
        if not accessions:
            continue

        cards: list[SignalCardWithAccession] = []
        malformed_cards = 0
        for accession in accessions:
            blob_name = f"{SIGNAL_CARD_BLOB_PREFIX}{ticker}/{accession}/signal_card.json"
            try:
                cards.append(_load_card(download_blob(blob_name), accession=accession))
            except Exception as exc:  # pragma: no cover
                malformed_cards += 1
                logging.warning(
                    "Skipping malformed signal card: ticker=%s accession=%s error=%s",
                    ticker,
                    accession,
                    exc,
                )

        selected_cards = _select_latest_five_years(cards)
        if not selected_cards:
            continue

        available_years = [card.fiscal_year for card in selected_cards]
        expected_years = _expected_years_from_available(available_years)
        missing_years = [year for year in expected_years if year not in set(available_years)]

        views.append(
            TickerSignalCoverageView(
                ticker=ticker,
                company_name=company_name,
                expected_years=expected_years,
                available_years=available_years,
                missing_years=missing_years,
                coverage_complete=len(missing_years) == 0,
                cards=selected_cards,
                malformed_cards=malformed_cards,
            )
        )

    return views
