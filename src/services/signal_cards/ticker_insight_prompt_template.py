"""Prompt template builders for ticker insight generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TickerInsightPromptPackage:
    """Combined prompt package for a single ticker analysis run."""

    system_prompt: str
    user_prompt: str


def build_ticker_insight_prompt(
    ticker: str,
    signal_cards: list[dict[str, Any]],
    year_range: tuple[int, int] | None = None,
) -> TickerInsightPromptPackage:
    """Build system and user prompts with ticker + signal card payload injection."""
    cards_json = json.dumps(signal_cards, indent=2)

    year_info = ""
    if year_range:
        year_info = f"\nFiscal year range: {year_range[0]} to {year_range[1]}"

    system_prompt = """You are a senior energy sector analyst specializing in SEC 10-K signal analysis.

Your task is to generate five key insights from a company's multi-year signal cards:
1. Regime Shift Narrative: Identify strategic changes (expansion, contraction, pivot, stable) across years.
2. Risk Trajectory: Separate new risks from escalating risks; rank material escalations.
3. Demand-Supply Mismatch: Analyze gaps between demand signals and supply chain/capex constraints.
4. Forward-Looking Watchlist: Identify next 12-month indicators with bullish/bearish trigger conditions.
5. Thesis and Counter-Thesis: Ground an investment thesis with explicit confidence and counter-arguments.

CRITICAL RULES:
- Use ONLY information from the provided signal cards.
- Cite exact evidence fields (e.g., capital_allocation.capex_direction, fiscal_year).
- No external facts or speculative reasoning.
- Flag uncertainty when evidence is weak or conflicting.
- Keep each insight under 300 words.
- Ground confidence scoring in evidence quality: 0.0 (no evidence) to 1.0 (strong multi-year consensus)."""

    user_prompt = f"""Analyze the following signal cards for ticker {ticker} and generate the five insights.

Signal Cards (ordered chronologically, earliest to most recent):{year_info}

{cards_json}

Generate insights rooted only in the above data. Return your response as valid JSON matching the required schema."""

    return TickerInsightPromptPackage(system_prompt=system_prompt, user_prompt=user_prompt)
