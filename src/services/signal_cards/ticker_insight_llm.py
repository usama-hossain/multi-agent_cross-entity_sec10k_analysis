"""LLM client service for generating ticker insights from signal cards."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from openai import AzureOpenAI, OpenAI

from src.services.signal_cards.ticker_insight_prompt_template import build_ticker_insight_prompt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerInsight:
    """Structure for LLM-generated ticker insights."""

    ticker: str
    regime_shift_narrative: str
    risk_trajectory: str
    demand_supply_mismatch: str
    forward_watchlist: str
    thesis_and_counter_thesis: str
    confidence_score: float
    usage_tokens: int


class TickerInsightLLMClient:
    """
    LLM client for generating insights from ticker signal cards.
    Supports Azure OpenAI or OpenAI depending on configuration.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-prod").strip()
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.api_version = os.getenv("OPENAI_API_VERSION", "2024-10-21").strip()

        if self.api_key and self.azure_endpoint:
            self._client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.azure_endpoint,
                api_version=self.api_version,
            )
            self._is_azure = True
        elif self.api_key:
            self._client = OpenAI(api_key=self.api_key)
            self._is_azure = False
        else:
            self._client = None
            self._is_azure = False

    @property
    def is_enabled(self) -> bool:
        """Check if LLM client is properly configured."""
        return self._client is not None

    def generate_insights(
        self,
        ticker: str,
        signal_cards: list[dict[str, Any]],
        year_range: tuple[int, int] | None = None,
    ) -> TickerInsight | dict[str, Any]:
        """
        Generate five key insights from signal cards for a ticker.

        Args:
            ticker: Stock ticker symbol.
            signal_cards: List of yearly signal card dicts, ordered oldest to newest.
            year_range: Optional (min_year, max_year) filter tuple.

        Returns:
            TickerInsight dataclass if successful, fallback dict if cards are empty or error.
        """
        if not signal_cards:
            logger.warning("No signal cards provided for ticker %s", ticker)
            return self._empty_insight_fallback(ticker)

        if not self.is_enabled:
            logger.warning("LLM client not configured; returning error insight for ticker %s", ticker)
            return self._error_insight_fallback(ticker, "LLM client is not configured")

        try:
            prompt_package = build_ticker_insight_prompt(
                ticker=ticker,
                signal_cards=signal_cards,
                year_range=year_range,
            )

            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt_package.system_prompt},
                    {"role": "user", "content": prompt_package.user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ticker_insights",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "regime_shift_narrative": {
                                    "type": "string",
                                    "description": "Multi-year strategic regime changes and inflections.",
                                },
                                "risk_trajectory": {
                                    "type": "string",
                                    "description": "New vs escalated risk timeline with materiality ranking.",
                                },
                                "demand_supply_mismatch": {
                                    "type": "string",
                                    "description": "Gaps between demand signals and supply/capex constraints.",
                                },
                                "forward_watchlist": {
                                    "type": "string",
                                    "description": "Next 12-month indicators with bullish/bearish triggers.",
                                },
                                "thesis_and_counter_thesis": {
                                    "type": "string",
                                    "description": "Investment thesis with counter-thesis and confidence.",
                                },
                                "confidence_score": {
                                    "type": "number",
                                    "description": "0.0 to 1.0 confidence based on evidence quality.",
                                },
                            },
                            "required": [
                                "regime_shift_narrative",
                                "risk_trajectory",
                                "demand_supply_mismatch",
                                "forward_watchlist",
                                "thesis_and_counter_thesis",
                                "confidence_score",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                temperature=0.7,
                max_tokens=2000,
            )

            result = json.loads(response.choices[0].message.content)
            usage_tokens = response.usage.total_tokens if response.usage else 0

            logger.info(
                "Generated insights for ticker=%s cards=%d tokens=%d confidence=%.2f",
                ticker,
                len(signal_cards),
                usage_tokens,
                result.get("confidence_score", 0),
            )

            return TickerInsight(
                ticker=ticker,
                regime_shift_narrative=result.get("regime_shift_narrative", ""),
                risk_trajectory=result.get("risk_trajectory", ""),
                demand_supply_mismatch=result.get("demand_supply_mismatch", ""),
                forward_watchlist=result.get("forward_watchlist", ""),
                thesis_and_counter_thesis=result.get("thesis_and_counter_thesis", ""),
                confidence_score=result.get("confidence_score", 0.0),
                usage_tokens=usage_tokens,
            )

        except Exception as exc:
            logger.error("Failed to generate insights for ticker %s: %s", ticker, exc)
            return self._error_insight_fallback(ticker, str(exc))

    @staticmethod
    def _empty_insight_fallback(ticker: str) -> dict[str, Any]:
        """Return a fallback insight structure when no data or LLM is unavailable."""
        return {
            "ticker": ticker,
            "regime_shift_narrative": "Insufficient signal card data available for analysis.",
            "risk_trajectory": "No signal cards available.",
            "demand_supply_mismatch": "No signal cards available.",
            "forward_watchlist": "No signal cards available.",
            "thesis_and_counter_thesis": "No signal cards available.",
            "confidence_score": 0.0,
            "usage_tokens": 0,
            "status": "empty",
        }

    @staticmethod
    def _error_insight_fallback(ticker: str, error_message: str) -> dict[str, Any]:
        """Return a fallback insight structure when LLM execution fails."""
        bounded_error = (error_message or "Unknown insight generation error")[:500]
        return {
            "ticker": ticker,
            "regime_shift_narrative": "Insight generation failed before completion.",
            "risk_trajectory": "LLM analysis unavailable due to an execution error.",
            "demand_supply_mismatch": "LLM analysis unavailable due to an execution error.",
            "forward_watchlist": "LLM analysis unavailable due to an execution error.",
            "thesis_and_counter_thesis": "LLM analysis unavailable due to an execution error.",
            "confidence_score": 0.0,
            "usage_tokens": 0,
            "status": "error",
            "error_message": bounded_error,
        }
