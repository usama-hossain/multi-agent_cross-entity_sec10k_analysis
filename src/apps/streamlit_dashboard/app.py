"""Streamlit dashboard entrypoint."""

from __future__ import annotations

from src.apps.streamlit_dashboard.runtime import build_runtime_from_environment


def run_app() -> None:
    import streamlit as st

    runtime = build_runtime_from_environment()

    st.set_page_config(page_title="Signal Card Dashboard", layout="wide")
    st.title("Signal Card Dashboard")

    search = st.text_input("Search ticker/company", "")
    overview = runtime.load_overview(search_query=search)

    if overview.warning_banner:
        st.warning(overview.warning_banner)

    selected_ticker = None
    if overview.empty_state:
        st.info(overview.empty_state)
    else:
        st.subheader("Processed Tickers")
        ticker_options = [row.ticker for row in overview.rows]
        selected_ticker = st.selectbox("Select a ticker to view signal cards", ticker_options) if ticker_options else None

        st.dataframe(
            [
                {
                    "ticker": row.ticker,
                    "company": row.company_name,
                    "available_years": ", ".join(str(y) for y in row.available_years),
                    "missing_years": ", ".join(str(y) for y in row.missing_years),
                    "coverage": row.coverage_status,
                }
                for row in overview.rows
            ],
            hide_index=True,
            width="stretch",
        )

    # Show signal cards for selected ticker
    if selected_ticker:
        detail = runtime.load_detail(selected_ticker, None)
        st.subheader(f"Signal Cards for {selected_ticker}")
        if detail.state == "ready":
            for card in detail.cards:
                st.markdown(f"**Year:** {card.fiscal_year}  ")
                st.json(card.model_dump())
        elif detail.state == "empty":
            st.info(detail.message or "No signal cards available.")
        elif detail.state == "not_found":
            st.error("Ticker not found.")


if __name__ == "__main__":
    run_app()
