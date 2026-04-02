"""Controller helpers for Streamlit dashboard pages."""

from __future__ import annotations

from src.apps.streamlit_dashboard.view_models import (
    OverviewPageModel,
    build_overview_page_model,
    build_ticker_detail_page_model,
)


def load_ticker_overview_page_model(data_source, search_query: str) -> OverviewPageModel:
    result = data_source.get_ticker_catalog()
    page = build_overview_page_model(catalog_result=result, search_query=search_query)

    warning = None
    if result.metrics.malformed_cards > 0:
        warning = f"{result.metrics.malformed_cards} malformed signal card file(s) were skipped."

    return OverviewPageModel(
        rows=page.rows,
        empty_state=page.empty_state,
        metrics=page.metrics,
        warning_banner=warning,
    )


def load_ticker_detail_page_model(data_source, ticker: str, fiscal_year: int | None):
    result = data_source.get_ticker_catalog()
    return build_ticker_detail_page_model(
        catalog_result=result,
        ticker=ticker,
        fiscal_year=fiscal_year,
    )
