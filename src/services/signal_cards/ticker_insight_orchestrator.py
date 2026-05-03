"""Orchestration service for ticker-level insight generation."""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from src.adapters.blob_storage import AzureBlobArtifactStore
from src.core.blob_paths import BlobPaths
from src.services.processing_state import ProcessingStateService
from src.services.signal_card_schema import SignalCardWithAccession
from src.services.signal_cards.ticker_insight_llm import TickerInsightLLMClient

logger = logging.getLogger(__name__)


class TickerInsightOrchestrator:
    """Load cards, run LLM insights, persist output, and update state tracking."""

    def __init__(
        self,
        blob_store: AzureBlobArtifactStore | None = None,
        llm_client: TickerInsightLLMClient | None = None,
        processing_state: ProcessingStateService | None = None,
    ):
        self._blob_store = blob_store or AzureBlobArtifactStore()
        self._llm_client = llm_client or TickerInsightLLMClient()
        self._processing_state = processing_state or ProcessingStateService()

    def generate_and_store_for_ticker(self, ticker: str) -> dict[str, Any]:
        """Generate ticker insight from latest five yearly signal cards and persist result."""
        normalized_ticker = str(ticker or "").strip().upper()
        if not normalized_ticker:
            raise ValueError("Ticker is required")

        cards = self._load_latest_five_cards(normalized_ticker)
        accessions = [card.accession for card in cards]

        if not cards:
            logger.info("No signal cards found for ticker=%s; storing empty insight", normalized_ticker)
            insight_payload = self._llm_client.generate_insights(
                ticker=normalized_ticker,
                signal_cards=[],
            )
            blob_name = BlobPaths.ticker_insight(normalized_ticker)
            self._upload_json(blob_name, insight_payload)
            return {
                "ticker": normalized_ticker,
                "status": "empty",
                "blob_name": blob_name,
                "cards_used": 0,
            }

        self._set_status_for_accessions(accessions, status="in_progress")

        min_year = min(card.fiscal_year for card in cards)
        max_year = max(card.fiscal_year for card in cards)

        try:
            card_payload = [card.model_dump() for card in sorted(cards, key=lambda c: c.fiscal_year)]
            insight = self._llm_client.generate_insights(
                ticker=normalized_ticker,
                signal_cards=card_payload,
                year_range=(min_year, max_year),
            )

            generated_at = datetime.datetime.utcnow().isoformat()
            blob_name = BlobPaths.ticker_insight(normalized_ticker)
            output = {
                "ticker": normalized_ticker,
                "generated_at_utc": generated_at,
                "year_range": {"min": min_year, "max": max_year},
                "source_accessions": accessions,
                "insight": self._to_dict(insight),
            }
            self._upload_json(blob_name, output)

            final_status = "completed"
            error_message: str | None = None
            if isinstance(insight, dict) and insight.get("status") == "empty":
                final_status = "empty"
            elif isinstance(insight, dict) and insight.get("status") == "error":
                final_status = "error"
                error_message = str(insight.get("error_message", "Insight generation failed")).strip()[:2000]

            self._set_status_for_accessions(accessions, status=final_status, error_message=error_message)
            self._set_metadata_for_accessions(
                accessions,
                insight_blob_path=blob_name,
                generated_at_utc=generated_at,
            )

            logger.info(
                "Ticker insight generated ticker=%s cards=%d status=%s blob=%s",
                normalized_ticker,
                len(cards),
                final_status,
                blob_name,
            )

            return {
                "ticker": normalized_ticker,
                "status": final_status,
                "blob_name": blob_name,
                "cards_used": len(cards),
                "year_range": {"min": min_year, "max": max_year},
            }

        except Exception as exc:
            self._set_status_for_accessions(accessions, status="error", error_message=str(exc))
            logger.error("Ticker insight generation failed ticker=%s error=%s", normalized_ticker, exc)
            raise

    def _load_latest_five_cards(self, ticker: str) -> list[SignalCardWithAccession]:
        prefix = f"processed/signals/{ticker}/"
        blob_names = self._list_blob_names(prefix=prefix)

        cards: list[SignalCardWithAccession] = []
        for blob_name in blob_names:
            if not blob_name.endswith("/signal_card.json"):
                continue
            try:
                payload = json.loads(self._blob_store.download_blob(blob_name).decode("utf-8"))
                cards.append(SignalCardWithAccession.model_validate(payload))
            except Exception as exc:
                logger.warning("Skipping malformed signal card blob=%s error=%s", blob_name, exc)

        by_year: dict[int, SignalCardWithAccession] = {}
        for card in cards:
            current = by_year.get(card.fiscal_year)
            if current is None or card.filing_date > current.filing_date:
                by_year[card.fiscal_year] = card

        return [by_year[year] for year in sorted(by_year.keys(), reverse=True)[:5]]

    def _list_blob_names(self, prefix: str) -> list[str]:
        if not self._blob_store.container_client:
            return []
        return [blob.name for blob in self._blob_store.container_client.list_blobs(name_starts_with=prefix)]

    def _upload_json(self, blob_name: str, payload: dict[str, Any]) -> None:
        self._blob_store.upload_blob(
            blob_name=blob_name,
            data=json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def _set_status_for_accessions(self, accessions: list[str], status: str, error_message: str | None = None) -> None:
        for accession in accessions:
            self._processing_state.set_ticker_insight_status(
                accession=accession,
                status=status,
                error_message=error_message,
            )

    def _set_metadata_for_accessions(self, accessions: list[str], insight_blob_path: str, generated_at_utc: str) -> None:
        for accession in accessions:
            self._processing_state.set_ticker_insight_metadata(
                accession=accession,
                insight_blob_path=insight_blob_path,
                generated_at_utc=generated_at_utc,
            )

    @staticmethod
    def _to_dict(insight: Any) -> dict[str, Any]:
        if isinstance(insight, dict):
            return insight
        if is_dataclass(insight):
            return asdict(insight)
        return {"value": str(insight)}
