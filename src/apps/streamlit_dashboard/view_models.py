"""View-model builders for Streamlit dashboard pages."""

from __future__ import annotations

from dataclasses import dataclass

from src.services.signal_cards.streamlit_data_source import (
    TickerCatalogMetrics,
    TickerCatalogResult,
)


@dataclass(frozen=True)
class OverviewRowModel:
    ticker: str
    company_name: str
    available_years: list[int]
    missing_years: list[int]
    coverage_status: str


@dataclass(frozen=True)
class OverviewPageModel:
    rows: list[OverviewRowModel]
    empty_state: str | None
    metrics: TickerCatalogMetrics
    warning_banner: str | None = None


@dataclass(frozen=True)
class TickerDetailPageModel:
    state: str
    ticker: str
    cards: list[object]
    available_years: list[int]
    message: str | None = None


def build_overview_page_model(
    catalog_result: TickerCatalogResult,
    search_query: str,
) -> OverviewPageModel:
    query = (search_query or "").strip().lower()

    rows: list[OverviewRowModel] = []
    for entry in catalog_result.entries:
        if query and query not in entry.ticker.lower() and query not in entry.company_name.lower():
            continue

        rows.append(
            OverviewRowModel(
                ticker=entry.ticker,
                company_name=entry.company_name,
                available_years=entry.available_years,
                missing_years=entry.missing_years,
                coverage_status="complete" if entry.coverage_complete else "partial",
            )
        )

    empty_state = None
    if not rows:
        empty_state = "No processed tickers match the current filter."

    return OverviewPageModel(
        rows=rows,
        empty_state=empty_state,
        metrics=catalog_result.metrics,
    )


def build_ticker_detail_page_model(
    catalog_result: TickerCatalogResult,
    ticker: str,
    fiscal_year: int | None,
) -> TickerDetailPageModel:
    normalized = (ticker or "").strip().upper()
    selected = None
    for entry in catalog_result.entries:
        if entry.ticker.upper() == normalized:
            selected = entry
            break

    if selected is None:
        return TickerDetailPageModel(
            state="not_found",
            ticker=normalized,
            cards=[],
            available_years=[],
        )

    cards = sorted(selected.cards, key=lambda card: card.fiscal_year, reverse=True)
    if fiscal_year is not None:
        cards = [card for card in cards if card.fiscal_year == fiscal_year]

    if not cards:
        return TickerDetailPageModel(
            state="empty",
            ticker=selected.ticker,
            cards=[],
            available_years=selected.available_years,
            message="No signal card is available for the selected year.",
        )

    return TickerDetailPageModel(
        state="ready",
        ticker=selected.ticker,
        cards=cards,
        available_years=selected.available_years,
    )
