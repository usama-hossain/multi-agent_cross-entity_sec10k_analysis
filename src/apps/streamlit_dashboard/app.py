"""Streamlit dashboard entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.apps.streamlit_dashboard.runtime import build_runtime_from_environment


def _analysis_section_label(key: str) -> str:
    labels = {
        "regime_shift_narrative": "Regime Shift Narrative",
        "risk_trajectory": "Risk Trajectory",
        "demand_supply_mismatch": "Demand-Supply Mismatch",
        "forward_watchlist": "Forward Watchlist",
        "thesis_and_counter_thesis": "Thesis and Counter-Thesis",
    }
    return labels.get(key, key.replace("_", " ").title())


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    text = str(value).strip()
    return text if text else "N/A"


def _split_into_points(text: str) -> list[str]:
    normalized = str(text or "").replace("\n", " ").strip()
    if not normalized:
        return []

    candidates: list[str] = []
    for chunk in normalized.split(". "):
        piece = chunk.strip().strip(".")
        if piece:
            candidates.append(piece)

    return candidates or [normalized]


def _analysis_status_color(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "completed":
        return "#15803d"
    if normalized == "empty":
        return "#b45309"
    if normalized == "error":
        return "#b91c1c"
    return "#475569"


def _analysis_section_color(title: str) -> str:
    palette = {
        "Regime Shift Narrative": "#1d4ed8",
        "Risk Trajectory": "#b91c1c",
        "Demand-Supply Mismatch": "#7c3aed",
        "Forward Watchlist": "#0f766e",
        "Thesis and Counter-Thesis": "#a16207",
    }
    return palette.get(title, "#334155")


def _render_labeled_block(st: Any, label: str, value: Any) -> None:
    st.markdown(f"**{label}**")
    st.write(_format_value(value))


def _render_signal_card(st: Any, card: Any) -> None:
    with st.expander(f"FY{card.fiscal_year}  |  {card.accession}", expanded=False):
        left, middle, right = st.columns(3)
        left.metric("Filing Date", _format_value(card.filing_date))
        middle.metric("Ticker", _format_value(card.ticker))
        right.metric("Years", str(card.fiscal_year))

        st.markdown("---")

        with st.container(border=True):
            _render_labeled_block(st, "Strategic Posture", card.strategic_posture.direction)
            st.caption(_format_value(card.strategic_posture.summary))
            st.caption(f"Evidence: {_format_value(card.strategic_posture.evidence)}")

        with st.container(border=True):
            _render_labeled_block(st, "Capital Allocation", card.capital_allocation.capex_direction)
            st.caption(_format_value(card.capital_allocation.capex_details))
            st.caption(f"Split: {_format_value(card.capital_allocation.capex_split)}")
            st.caption(f"Tone: {_format_value(card.capital_allocation.language_tone)}")

        with st.container(border=True):
            _render_labeled_block(st, "Demand Signals", card.demand_signals.backlog_direction)
            st.caption(_format_value(card.demand_signals.customer_growth))
            st.caption(_format_value(card.demand_signals.load_changes))
            st.caption(f"Evidence: {_format_value(card.demand_signals.evidence)}")

        with st.container(border=True):
            st.markdown("**Supply Chain Tightness**")
            if card.supply_chain_tightness:
                for signal in card.supply_chain_tightness:
                    st.write(f"- {_format_value(signal.signal)} ({_format_value(signal.severity)})")
                    st.caption(f"Evidence: {_format_value(signal.evidence)}")
            else:
                st.caption("No supply chain signals.")

        with st.container(border=True):
            st.markdown("**New Risk Factors**")
            if card.new_risk_factors:
                for risk in card.new_risk_factors:
                    st.write(f"- {_format_value(risk.risk)}")
                    st.caption(f"Category: {_format_value(risk.category)}")
                    st.caption(f"Evidence: {_format_value(risk.evidence)}")
            else:
                st.caption("No new risk factors.")

        with st.container(border=True):
            st.markdown("**Escalated Risk Factors**")
            if card.escalated_risk_factors:
                for risk in card.escalated_risk_factors:
                    st.write(f"- {_format_value(risk.risk)}")
                    st.caption(f"Category: {_format_value(risk.category)}")
                    st.caption(f"Prior: {_format_value(risk.prior_language_summary)}")
                    st.caption(f"Current: {_format_value(risk.current_language_summary)}")
                    st.caption(f"Evidence: {_format_value(risk.evidence)}")
            else:
                st.caption("No escalated risk factors.")

        with st.container(border=True):
            _render_labeled_block(st, "Regulatory Exposure", card.regulatory_exposure.pending_rate_cases)
            st.caption(_format_value(card.regulatory_exposure.emissions_mandates))
            st.caption(_format_value(card.regulatory_exposure.compliance_investments))
            st.caption(f"Evidence: {_format_value(card.regulatory_exposure.evidence)}")

        with st.container(border=True):
            _render_labeled_block(st, "Generation Mix Shift", card.generation_mix_shift.coal_retirements)
            st.caption(_format_value(card.generation_mix_shift.renewable_additions))
            st.caption(_format_value(card.generation_mix_shift.battery_storage))
            st.caption(_format_value(card.generation_mix_shift.dispatchable_adequacy))
            st.caption(f"Evidence: {_format_value(card.generation_mix_shift.evidence)}")

        with st.container(border=True):
            _render_labeled_block(st, "Fuel and Input Exposure", card.fuel_and_input_exposure.price_sensitivity)
            st.caption(_format_value(card.fuel_and_input_exposure.hedging_changes))
            st.caption(_format_value(card.fuel_and_input_exposure.ppa_terms))
            st.caption(f"Evidence: {_format_value(card.fuel_and_input_exposure.evidence)}")


def _set_dashboard_view(view: str) -> None:
    import streamlit as st

    st.session_state["dashboard_view"] = view


def _render_analysis(st: Any, analysis_payload: dict[str, Any], ticker: str) -> None:
    insight = analysis_payload.get("insight", analysis_payload)
    if not isinstance(insight, dict):
        st.warning("Insight payload is not in the expected format.")
        st.json(analysis_payload)
        return

    status = str(insight.get("status", "completed")).strip().lower()
    confidence_raw = insight.get("confidence_score")
    try:
        confidence_pct = f"{float(confidence_raw) * 100:.0f}%"
    except (TypeError, ValueError):
        confidence_pct = "N/A"

    generated_at = analysis_payload.get("generated_at_utc", "N/A")
    cards_used = len(analysis_payload.get("source_accessions", []))

    st.subheader(f"LLM Analysis: {ticker}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Status", status.upper())
    c2.metric("Confidence", confidence_pct)
    c3.metric("Cards Used", cards_used)
    st.caption(f"Generated: {generated_at}")

    status_color = _analysis_status_color(status)
    st.markdown(
        f"""
        <div style="
            display:inline-block;
            padding:0.35rem 0.75rem;
            border-radius:999px;
            background:{status_color}22;
            color:{status_color};
            border:1px solid {status_color}55;
            font-weight:700;
            margin-bottom:0.75rem;
        ">
            {status.upper()}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if status == "error":
        st.error(insight.get("error_message", "Insight generation failed."))
    elif status == "empty":
        st.info("Not enough signal card data was available to produce a full analysis.")

    section_specs = [
        ("regime_shift_narrative", "Regime Shift Narrative", "Headline summary of the multi-year regime.", True),
        ("risk_trajectory", "Risk Trajectory", "What changed, escalated, or stayed stable.", True),
        ("demand_supply_mismatch", "Demand-Supply Mismatch", "Where demand signals and capacity pressures diverge.", True),
        ("forward_watchlist", "Forward Watchlist", "What to monitor next.", True),
        ("thesis_and_counter_thesis", "Thesis and Counter-Thesis", "Why this matters and what could invalidate it.", True),
    ]

    for key, title, subtitle, show_bullets in section_specs:
        section_text = str(insight.get(key, "")).strip() or "No content available."
        points = _split_into_points(section_text) if show_bullets else [section_text]
        with st.container(border=True):
            section_color = _analysis_section_color(title)
            st.markdown(
                f"""
                <div style="
                    border-left: 6px solid {section_color};
                    padding-left: 0.75rem;
                    margin-bottom: 0.5rem;
                ">
                    <div style="font-weight:700; color:{section_color}; font-size:1.02rem;">{title}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption(subtitle)
            if points:
                primary = points[0]
                st.markdown(f"<div style='padding:0.6rem 0.8rem; background:{section_color}10; border-radius:0.5rem;'> {primary} </div>", unsafe_allow_html=True)
                if len(points) > 1:
                    st.markdown("**Key points**")
                    for point in points[1:]:
                        st.markdown(f"- {point}")
            else:
                st.write("No content available.")


def run_app() -> None:
    import streamlit as st

    runtime = build_runtime_from_environment()

    st.set_page_config(page_title="Signal Card Dashboard", layout="wide")
    st.title("Signal Card Dashboard")

    overview = runtime.load_overview(search_query="")
    search = st.text_input("Search ticker/company", "")
    query = (search or "").strip().lower()

    rows = overview.rows
    if query:
        rows = [
            row
            for row in overview.rows
            if query in row.ticker.lower() or query in row.company_name.lower()
        ]

    if overview.warning_banner:
        st.warning(overview.warning_banner)

    if "dashboard_view" not in st.session_state:
        st.session_state["dashboard_view"] = None
    if "selected_ticker" not in st.session_state:
        st.session_state["selected_ticker"] = None

    selected_ticker = None
    selected_row = None
    if not overview.rows:
        st.info("No processed tickers are available yet.")
    elif not rows:
        st.info("No processed tickers match the current filter.")
    else:
        st.subheader("Processed Tickers")
        ticker_options = [row.ticker for row in rows]
        selected_ticker = st.selectbox("Select a ticker to view signal cards", ticker_options) if ticker_options else None
        if selected_ticker:
            selected_row = next((row for row in rows if row.ticker == selected_ticker), None)

        if selected_ticker != st.session_state["selected_ticker"]:
            st.session_state["selected_ticker"] = selected_ticker
            st.session_state["dashboard_view"] = None

        st.dataframe(
            [
                {
                    "ticker": row.ticker,
                    "company": row.company_name,
                    "available_years": ", ".join(str(y) for y in row.available_years),
                    "missing_years": ", ".join(str(y) for y in row.missing_years),
                    "coverage": row.coverage_status,
                }
                for row in rows
            ],
            hide_index=True,
            width="stretch",
        )

    if selected_ticker and selected_row:
        st.subheader(f"Ticker Overview: {selected_ticker}")
        st.markdown(f"**Company:** {selected_row.company_name}")
        st.markdown(
            f"**Coverage:** {selected_row.coverage_status} | "
            f"**Available years:** {', '.join(str(y) for y in selected_row.available_years) or 'None'} | "
            f"**Missing years:** {', '.join(str(y) for y in selected_row.missing_years) or 'None'}"
        )

        show_cards_col, generate_analysis_col = st.columns(2)

        with show_cards_col:
            show_cards = st.button("Show signal-cards", use_container_width=True, on_click=_set_dashboard_view, args=("cards",))

        with generate_analysis_col:
            generate_analysis = st.button("Generate analysis", use_container_width=True, on_click=_set_dashboard_view, args=("analysis",))

        current_view = st.session_state.get("dashboard_view")

        if current_view == "analysis":
            analysis_payload = runtime.load_analysis(selected_ticker)
            if analysis_payload:
                _render_analysis(st, analysis_payload, selected_ticker)
            else:
                st.info("No precomputed analysis is available in blob storage for this ticker.")

        if current_view == "cards":
            detail = runtime.load_detail(selected_ticker, None)
            st.subheader(f"Signal Cards for {selected_ticker}")
            if detail.state == "ready":
                for card in detail.cards:
                    _render_signal_card(st, card)
            elif detail.state == "empty":
                st.info(detail.message or "No signal cards available.")
            elif detail.state == "not_found":
                st.error("Ticker not found.")


if __name__ == "__main__":
    run_app()
