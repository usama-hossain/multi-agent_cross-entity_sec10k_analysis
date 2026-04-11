import datetime
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from azure.core.exceptions import ResourceExistsError
from azure.storage.queue import QueueClient

from src.core.blob_paths import BlobPaths
from src.core.logging_config import setup_logging
from src.core.ports import (
    BatchServicePort,
    BlobStoragePort,
    MarkdownConversionPort,
    PendingSignalCardBatch,
    ProcessingStatePort,
    QueueClientPort,
    SecFilingsPort,
    SectionExtractionPort,
    SignalCardExtractionPort,
)
from src.services.processing_state import ProcessingStateService
from src.services.sec_downloader import SECDownloaderService
from src.services.sec_edgar_markdown import SECEdgarMarkdownService
from src.services.sec_edgar_sections import SECEdgarSectionsService
from src.services.signal_card_batch import SECSignalCardBatchService
from src.services.signal_card_extractor import SECSignalCardService


# Initialize logging once for all pipeline modules.
log_file = setup_logging()

CONVERT_QUEUE_NAME = os.getenv("SEC_CONVERT_QUEUE_NAME", "sec-convert-jobs")


@dataclass(frozen=True)
class KickoffDependencies:
    filing_source: SecFilingsPort
    blob_store: BlobStoragePort
    state_store: ProcessingStatePort
    queue_client: QueueClientPort


@dataclass(frozen=True)
class WorkerDependencies:
    filing_service: SecFilingsPort
    blob_store: BlobStoragePort
    state_store: ProcessingStatePort
    markdown_service: MarkdownConversionPort
    section_service: SectionExtractionPort
    signal_card_service: SignalCardExtractionPort
    batch_service: BatchServicePort


@dataclass(frozen=True)
class ReconcilerDependencies:
    filing_service: SecFilingsPort
    blob_store: BlobStoragePort
    state_store: ProcessingStatePort
    batch_service: BatchServicePort


@dataclass(frozen=True)
class ResetDependencies:
    filing_source: SecFilingsPort
    state_store: ProcessingStatePort


@dataclass(frozen=True)
class KickoffQueueMessage:
    ticker: str
    accession: str
    force_reprocess_signal_cards: bool
    fiscal_year: Optional[Any]
    filing_date: Optional[str]
    ticker_filing_context: list[dict[str, Any]]
    attempt: int = 1
    queued_at_utc: Optional[str] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "accession": self.accession,
            "force_reprocess_signal_cards": self.force_reprocess_signal_cards,
            "fiscal_year": self.fiscal_year,
            "filing_date": self.filing_date,
            "ticker_filing_context": self.ticker_filing_context,
            "attempt": self.attempt,
            "queued_at_utc": self.queued_at_utc or datetime.datetime.now(datetime.UTC).isoformat(),
        }


class WorkerPayloadError(ValueError):
    pass


def _safe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _bounded_error_message(error: Exception, max_length: int = 500) -> str:
    text = str(error).strip() or error.__class__.__name__
    return text[:max_length]


def _build_kickoff_queue_message(
    ticker: str,
    accession: str,
    force_reprocess_signal_cards: bool,
    filing_meta: dict[str, Any],
    ticker_filing_context: list[dict[str, Any]],
) -> dict[str, Any]:
    return KickoffQueueMessage(
        ticker=ticker,
        accession=accession,
        force_reprocess_signal_cards=force_reprocess_signal_cards,
        fiscal_year=filing_meta.get("fiscal_year"),
        filing_date=filing_meta.get("filing_date"),
        ticker_filing_context=ticker_filing_context,
    ).to_payload()


def _parse_worker_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
    ticker = str(raw_payload.get("ticker", "")).strip()
    accession = str(raw_payload.get("accession", "")).strip()
    if not ticker or not accession:
        raise WorkerPayloadError("Queue payload missing required fields: ticker and accession")

    markdown_blob = raw_payload.get("markdown_blob", BlobPaths.markdown(ticker, accession))
    item1a_blob = raw_payload.get("item1a_blob", BlobPaths.item1a(ticker, accession))
    item7_blob = raw_payload.get("item7_blob", BlobPaths.item7(ticker, accession))
    signal_card_blob = raw_payload.get("signal_card_blob", BlobPaths.signal_card(ticker, accession))
    ticker_filing_context = raw_payload.get("ticker_filing_context") or []
    if not isinstance(ticker_filing_context, list):
        raise WorkerPayloadError("Queue payload field 'ticker_filing_context' must be a list when provided")

    return {
        "ticker": ticker,
        "accession": accession,
        "markdown_blob": str(markdown_blob),
        "item1a_blob": str(item1a_blob),
        "item7_blob": str(item7_blob),
        "signal_card_blob": str(signal_card_blob),
        "filing_date": raw_payload.get("filing_date"),
        "fiscal_year": _safe_int(raw_payload.get("fiscal_year")),
        "ticker_filing_context": ticker_filing_context,
        "force_reprocess_signal_cards": bool(raw_payload.get("force_reprocess_signal_cards", False)),
    }


def _build_ticker_filing_context(ticker: str, filing_metas: list[dict]) -> list[dict]:
    context_entries: list[dict] = []
    for filing_meta in filing_metas:
        accession = str(filing_meta.get("accession", "")).strip()
        if not accession:
            continue
        context_entries.append(
            {
                "accession": accession,
                "fiscal_year": filing_meta.get("fiscal_year"),
                "filing_date": filing_meta.get("filing_date"),
                "item1a_blob": BlobPaths.item1a(ticker, accession),
                "item7_blob": BlobPaths.item7(ticker, accession),
            }
        )
    return context_entries


def _normalize_pending_batch(entity: Any) -> Optional[PendingSignalCardBatch]:
    if isinstance(entity, PendingSignalCardBatch):
        return entity

    if isinstance(entity, dict):
        accession = str(entity.get("RowKey", "")).strip()
        signal_card_status = str(entity.get("SignalCardStatus", "")).strip().lower()
        batch_id = str(entity.get("SignalCardBatchId", "")).strip()
        custom_id = str(entity.get("SignalCardCustomId", "")).strip()
        source_blob = str(entity.get("SourceBlob", "")).strip()
        return PendingSignalCardBatch(
            accession=accession,
            signal_card_status=signal_card_status,
            batch_id=batch_id,
            custom_id=custom_id,
            source_blob=source_blob,
        )

    return None


def _resolve_ticker_for_batch_entity(entity: PendingSignalCardBatch) -> Optional[str]:
    custom_id = entity.custom_id
    if custom_id and "-" in custom_id:
        return custom_id.split("-", 1)[0].upper()

    source_blob = entity.source_blob
    if source_blob.startswith("raw/html/"):
        parts = source_blob.split("/")
        if len(parts) >= 4 and parts[2]:
            return parts[2].upper()

    logging.warning(
        "Unable to resolve ticker for batch entity: accession=%s custom_id=%s source_blob=%s",
        entity.accession,
        custom_id,
        source_blob,
    )
    return None


def _load_tickers() -> list[str]:
    tickers_path = Path(__file__).with_name("config") / "tickers.json"
    if not tickers_path.exists():
        tickers_path = Path(__file__).resolve().parents[2] / "config" / "tickers.json"
    with tickers_path.open("r", encoding="utf-8") as tickers_file:
        payload = json.load(tickers_file)

    companies = payload.get("ecosystem", {}).get("companies", [])
    tickers = []
    seen = set()

    for company in companies:
        ticker = str(company.get("ticker", "")).strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    if not tickers:
        raise ValueError("config/tickers.json does not contain any valid tickers.")

    return tickers


def _get_queue_client(connection_string: str, queue_name: str) -> QueueClient:
    queue_client = QueueClient.from_connection_string(connection_string, queue_name)
    try:
        queue_client.create_queue()
    except ResourceExistsError:
        pass
    return queue_client


def _resolve_blob_store(filing_service: SecFilingsPort) -> BlobStoragePort:
    """Resolve a blob adapter from filing service, with test-friendly fallback."""

    blob_candidate = getattr(filing_service, "blob_store", None)
    if blob_candidate and all(
        hasattr(blob_candidate, method) for method in ("blob_exists", "upload_blob", "download_blob")
    ):
        return blob_candidate
    return filing_service  # type: ignore[return-value]


def _build_kickoff_dependencies(queue_connection_string: str) -> KickoffDependencies:
    filing_service = SECDownloaderService()
    blob_store = _resolve_blob_store(filing_service)
    state_service = ProcessingStateService()
    queue_client = _get_queue_client(queue_connection_string, CONVERT_QUEUE_NAME)
    return KickoffDependencies(
        filing_source=filing_service,
        blob_store=blob_store,
        state_store=state_service,
        queue_client=queue_client,
    )


def _build_worker_dependencies() -> WorkerDependencies:
    filing_service = SECDownloaderService()
    blob_store = _resolve_blob_store(filing_service)
    state_service = ProcessingStateService()
    return WorkerDependencies(
        filing_service=filing_service,
        blob_store=blob_store,
        state_store=state_service,
        markdown_service=SECEdgarMarkdownService(),
        section_service=SECEdgarSectionsService(),
        signal_card_service=SECSignalCardService(),
        batch_service=SECSignalCardBatchService(),
    )


def _build_reconciler_dependencies() -> ReconcilerDependencies:
    filing_service = SECDownloaderService()
    blob_store = _resolve_blob_store(filing_service)
    state_service = ProcessingStateService()
    return ReconcilerDependencies(
        filing_service=filing_service,
        blob_store=blob_store,
        state_store=state_service,
        batch_service=SECSignalCardBatchService(),
    )


def _build_reset_dependencies() -> ResetDependencies:
    return ResetDependencies(
        filing_source=SECDownloaderService(),
        state_store=ProcessingStateService(),
    )
