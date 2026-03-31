import datetime
import json
import logging
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional

import azure.functions as func
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
from src.services.sec_edgar_sections import SECEdgarSectionsService
from src.services.sec_edgar_markdown import SECEdgarMarkdownService
from src.services.signal_card_extractor import SECSignalCardService
from src.services.signal_card_batch import SECSignalCardBatchService

app = func.FunctionApp()

# Initialize logging (writes to logs/ directory locally, feeds to Application Insights in production)
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


def _handle_signal_card_extraction(
    ticker: str,
    accession: str,
    fiscal_year: Optional[int],
    filing_date: Optional[str],
    signal_card_blob: str,
    historical_filings: list[dict],
    state_service: ProcessingStatePort,
    downloader: BlobStoragePort,
    signal_card_service: SignalCardExtractionPort,
    batch_service: BatchServicePort,
) -> bool:
    """
    Handle signal card extraction in sync or batch mode.
    Returns True if extraction was initiated/completed, False if skipped/failed.
    """
    execution_mode = os.getenv("SIGNAL_CARD_EXECUTION_MODE", "sync").strip().lower()

    logging.info(
        "Signal card extraction mode selected: ticker=%s accession=%s execution_mode=%s",
        ticker,
        accession,
        execution_mode,
    )

    if execution_mode == "batch":
        return _extract_signal_card_batch(
            ticker,
            accession,
            fiscal_year,
            filing_date,
            signal_card_blob,
            historical_filings,
            state_service,
            extraction_service=signal_card_service,
            batch_service=batch_service,
        )
    else:
        return _extract_signal_card_sync(
            ticker,
            accession,
            fiscal_year,
            filing_date,
            signal_card_blob,
            historical_filings,
            state_service,
            downloader,
            signal_card_service=signal_card_service,
        )


def _extract_signal_card_sync(
    ticker: str,
    accession: str,
    fiscal_year: Optional[int],
    filing_date: Optional[str],
    signal_card_blob: str,
    historical_filings: list[dict],
    state_service: ProcessingStatePort,
    downloader: BlobStoragePort,
    signal_card_service: SignalCardExtractionPort,
) -> bool:
    """Extract signal card synchronously (immediate API call)."""
    logging.info(
        "Invoking signal card extraction (SYNC mode): ticker=%s target_accession=%s historical_filings_count=%d",
        ticker,
        accession,
        len(historical_filings),
    )

    try:
        signal_card = signal_card_service.extract_signal_card(
            ticker=ticker,
            fiscal_year=fiscal_year,
            filing_date=filing_date,
            target_accession=accession,
            historical_filings=historical_filings,
        )
        logging.debug(
            "Signal card generated successfully: ticker=%s target_accession=%s",
            ticker,
            accession,
        )
        downloader.upload_blob(
            signal_card_blob,
            json.dumps(signal_card.model_dump(mode="json"), indent=2).encode("utf-8"),
            content_type="application/json",
        )
        logging.info(
            "Signal card uploaded: ticker=%s target_accession=%s signal_card_blob=%s",
            ticker,
            accession,
            signal_card_blob,
        )
        state_service.set_signal_card_status(accession, "extracted")
        return True
    except Exception:
        logging.exception(
            "Signal card extraction failed: ticker=%s target_accession=%s",
            ticker,
            accession,
        )
        state_service.set_signal_card_status(accession, "error")
        return False


def _extract_signal_card_batch(
    ticker: str,
    accession: str,
    fiscal_year: Optional[int],
    filing_date: Optional[str],
    signal_card_blob: str,
    historical_filings: list[dict],
    state_service: ProcessingStatePort,
    extraction_service: SignalCardExtractionPort,
    batch_service: BatchServicePort,
) -> bool:
    """Submit signal card extraction request to OpenAI Batch API."""
    logging.info(
        "Queuing signal card extraction for batch processing: ticker=%s target_accession=%s historical_filings_count=%d",
        ticker,
        accession,
        len(historical_filings),
    )

    if not batch_service.is_enabled:
        logging.warning(
            "Batch service is not enabled (OPENAI_API_KEY missing), falling back to skipped: ticker=%s accession=%s",
            ticker,
            accession,
        )
        state_service.set_signal_card_status(accession, "skipped")
        return False

    logging.debug("Building extraction request for batch submission: ticker=%s accession=%s", ticker, accession)
    request = extraction_service.build_extraction_request(
        ticker=ticker,
        fiscal_year=fiscal_year,
        filing_date=filing_date,
        target_accession=accession,
        historical_filings=historical_filings,
    )

    custom_id = f"{ticker}-{accession}"
    logging.debug(
        "Built extraction request: ticker=%s custom_id=%s system_prompt_len=%d user_prompt_len=%d",
        ticker,
        custom_id,
        len(request["system_prompt"]),
        len(request["user_prompt"]),
    )

    batch_item = batch_service.build_batch_request_item(
        custom_id=custom_id,
        system_prompt=request["system_prompt"],
        user_prompt=request["user_prompt"],
        schema=request["schema"],
    )

    state_service.set_signal_card_status(accession, "queued_for_batch")
    logging.info(
        "Submitting signal card batch request: ticker=%s accession=%s custom_id=%s",
        ticker,
        accession,
        custom_id,
    )
    batch_id = batch_service.submit_batch([batch_item])
    if not batch_id:
        logging.error(
            "Batch submission failed: ticker=%s accession=%s custom_id=%s",
            ticker,
            accession,
            custom_id,
        )
        state_service.update_signal_card_batch_status(accession, "failed", error_message="Batch submission failed")
        state_service.set_signal_card_status(accession, "batch_failed", error_message="Batch submission failed")
        return False

    state_service.set_signal_card_batch_info(
        accession=accession,
        batch_id=batch_id,
        custom_id=custom_id,
        status="in_progress",
    )
    state_service.set_signal_card_status(accession, "batch_submitted")
    logging.info(
        "Signal card batch submitted successfully: ticker=%s accession=%s custom_id=%s batch_id=%s",
        ticker,
        accession,
        custom_id,
        batch_id,
    )
    return True


def _load_tickers() -> list[str]:
    tickers_path = Path(__file__).with_name("config") / "tickers.json"
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
    """Resolve a blob adapter from filing service, with test-friendly fallback.

    Production SEC downloader exposes `.blob_store`; unit test stubs often expose
    blob methods directly on the downloader fake.
    """

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


@app.function_name(name="manual_kickoff")
@app.route(route="kickoff", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def manual_kickoff(req: func.HttpRequest) -> func.HttpResponse:
    # Check for force-reprocess query parameter (for signal card retry)
    force_reprocess_signal_cards = req.params.get("force_reprocess_signal_cards", "false").lower() == "true"
    tickers_filter = req.params.get("tickers", "").strip()
    
    logging.info(
        "Manual kickoff started: force_reprocess_signal_cards=%s",
        force_reprocess_signal_cards,
    )

    queue_connection_string = os.getenv("AzureWebJobsStorage")
    if not queue_connection_string:
        return func.HttpResponse(
            json.dumps({"status": "error", "message": "AzureWebJobsStorage is not configured"}),
            status_code=500,
            mimetype="application/json",
        )

    deps = _build_kickoff_dependencies(queue_connection_string)
    filing_source = deps.filing_source
    blob_store = deps.blob_store
    state_store = deps.state_store
    queue_client = deps.queue_client

    tickers = _load_tickers()

    if tickers_filter:
        requested_tickers = [t.strip().upper() for t in tickers_filter.split(",") if t.strip()]
        allowed = set(tickers)
        filtered_tickers = [t for t in requested_tickers if t in allowed]
        invalid_tickers = [t for t in requested_tickers if t not in allowed]

        if invalid_tickers:
            logging.warning("Ignoring unknown kickoff tickers: %s", invalid_tickers)

        if not filtered_tickers:
            return func.HttpResponse(
                json.dumps(
                    {
                        "status": "error",
                        "message": "No valid tickers provided in 'tickers' query parameter",
                        "requested_tickers": requested_tickers,
                    }
                ),
                status_code=400,
                mimetype="application/json",
            )

        tickers = filtered_tickers
        logging.info("Kickoff restricted to tickers=%s", tickers)

    enqueued = 0
    skipped = 0
    failed = []
    downloaded = []
    not_downloaded = []

    for ticker in tickers:
        try:
            filing_metas = filing_source.fetch_recent_10k_metadata(ticker, max_filings=5)
            if not filing_metas:
                logging.warning("No recent 10-K filings found for ticker=%s", ticker)
                not_downloaded.append({"ticker": ticker, "reason": "no_10k_filings"})
                continue

            logging.info(
                "Ticker %s: preparing %d filing(s) (max requested: 5)",
                ticker,
                len(filing_metas),
            )

            ticker_filing_context = _build_ticker_filing_context(ticker, filing_metas)

            for filing_meta in filing_metas:
                accession = filing_meta["accession"]
                try:
                    html_blob = BlobPaths.raw_html(ticker, accession)
                    markdown_blob = BlobPaths.markdown(ticker, accession)
                    item1a_blob = BlobPaths.item1a(ticker, accession)
                    item7_blob = BlobPaths.item7(ticker, accession)
                    signal_card_blob = BlobPaths.signal_card(ticker, accession)
                    status = state_store.get_status(accession)

                    markdown_exists = blob_store.blob_exists(markdown_blob)
                    item1a_exists = blob_store.blob_exists(item1a_blob)
                    item7_exists = blob_store.blob_exists(item7_blob)
                    signal_card_exists = blob_store.blob_exists(signal_card_blob)

                    if markdown_exists:
                        state_store.set_markdown_status(accession, "markdown_converted")
                    if item1a_exists:
                        state_store.set_item1a_status(accession, "extracted")
                    if item7_exists:
                        state_store.set_item7_status(accession, "extracted")
                    if signal_card_exists:
                        state_store.set_signal_card_status(accession, "extracted")

                    # Skip if all artifacts exist AND not forcing reprocessing
                    # If force_reprocess_signal_cards=true, still need markdown + sections but allow signal card retry
                    skip_reason = None
                    if markdown_exists and item1a_exists and item7_exists and signal_card_exists:
                        if not force_reprocess_signal_cards:
                            skip_reason = "already_complete"
                    elif markdown_exists and item1a_exists and item7_exists:
                        # Has all prerequisites, can retrieve signal card
                        pass
                    elif not (markdown_exists and item1a_exists and item7_exists):
                        # Missing prerequisites for signal card extraction, but might still enqueue for markdown/sections
                        pass

                    if skip_reason:
                        skipped += 1
                        logging.info(
                            "Skipping ticker=%s accession=%s because markdown, item sections, and signal card already exist",
                            ticker,
                            accession,
                        )
                        not_downloaded.append(
                            {
                                "ticker": ticker,
                                "accession": accession,
                                "reason": skip_reason,
                            }
                        )
                        continue

                    if status == "error":
                        skipped += 1
                        logging.info(
                            "Skipping ticker=%s accession=%s because filing status is error",
                            ticker,
                            accession,
                        )
                        not_downloaded.append(
                            {
                                "ticker": ticker,
                                "accession": accession,
                                "reason": "status_error",
                            }
                        )
                        continue

                    if status in ("ready", "pdf_converted", "markdown_converted") or markdown_exists:
                        message = _build_kickoff_queue_message(
                            ticker=ticker,
                            accession=accession,
                            force_reprocess_signal_cards=force_reprocess_signal_cards,
                            filing_meta=filing_meta,
                            ticker_filing_context=ticker_filing_context,
                        )
                        queue_client.send_message(json.dumps(message))
                        enqueued += 1
                        logging.info(
                            "Enqueued existing filing ticker=%s accession=%s status=%s",
                            ticker,
                            accession,
                            status,
                        )
                        downloaded.append(
                            {
                                "ticker": ticker,
                                "accession": accession,
                                "action": "enqueued_existing",
                            }
                        )
                        continue

                    # TODO: Future enhancement - add atomic claim/lease before download to prevent concurrent kickoff races.
                    html_bytes = filing_source.download_filing_html(filing_meta["file_url"])
                    if not blob_store.blob_exists(html_blob):
                        blob_store.upload_blob(html_blob, html_bytes, content_type="text/html")

                    state_store.upsert_filing(
                        accession=accession,
                        cik=filing_meta["cik"],
                        company_name=filing_meta.get("company_name") or ticker,
                        source_blob=html_blob,
                        status="ready",
                    )
                    state_store.set_download_status(accession, "downloaded")

                    message = _build_kickoff_queue_message(
                        ticker=ticker,
                        accession=accession,
                        force_reprocess_signal_cards=force_reprocess_signal_cards,
                        filing_meta=filing_meta,
                        ticker_filing_context=ticker_filing_context,
                    )
                    queue_client.send_message(json.dumps(message))
                    enqueued += 1
                    logging.info("Downloaded and enqueued ticker=%s accession=%s", ticker, accession)
                    downloaded.append(
                        {
                            "ticker": ticker,
                            "accession": accession,
                            "action": "downloaded_and_enqueued",
                        }
                    )
                except Exception as filing_ex:
                    logging.exception(
                        "Kickoff failed for ticker=%s accession=%s",
                        ticker,
                        accession,
                    )
                    failed.append(
                        {
                            "ticker": ticker,
                            "accession": accession,
                                "error": _bounded_error_message(filing_ex),
                        }
                    )
                    not_downloaded.append(
                        {
                            "ticker": ticker,
                            "accession": accession,
                                "reason": _bounded_error_message(filing_ex),
                        }
                    )

        except Exception as ex:
            logging.exception("Kickoff failed for ticker=%s", ticker)
            failed.append({"ticker": ticker, "error": _bounded_error_message(ex)})
            not_downloaded.append({"ticker": ticker, "reason": _bounded_error_message(ex)})

    return func.HttpResponse(
        json.dumps(
            {
                "status": "ok",
                "enqueued": enqueued,
                "skipped": skipped,
                "downloaded": downloaded,
                "not_downloaded": not_downloaded,
                "failed": failed,
            }
        ),
        status_code=200,
        mimetype="application/json",
    )


@app.function_name(name="reset_signal_cards")
@app.route(route="reset-signal-cards", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def reset_signal_cards(req: func.HttpRequest) -> func.HttpResponse:
    """
    Reset signal card processing status for specified tickers/accessions.
    
    Query parameters:
    - tickers: comma-separated list (e.g., "NEE,DUK,SO")
    - accessions: comma-separated list of accession numbers
    
    Returns: count of signal cards reset to "not_started" status in table storage.
    
    NOTE: You must separately delete signal_card.json blobs from Blob Storage:
    - Path pattern: processed/signals/{ticker}/{accession}/signal_card.json
    """
    try:
        tickers_param = req.params.get("tickers", "").strip()
        accessions_param = req.params.get("accessions", "").strip()
        
        if not tickers_param and not accessions_param:
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "message": "Provide either 'tickers' or 'accessions' query parameter"
                }),
                status_code=400,
                mimetype="application/json",
            )
        
        deps = _build_reset_dependencies()
        filing_source = deps.filing_source
        state_service = deps.state_store
        reset_count = 0
        
        if tickers_param:
            tickers = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]
            logging.info("Resetting signal cards for tickers: %s", tickers)
            
            for ticker in tickers:
                try:
                    filing_metas = filing_source.fetch_recent_10k_metadata(ticker, max_filings=5)
                    for filing_meta in filing_metas:
                        accession = filing_meta.get("accession")
                        if accession:
                            state_service.set_signal_card_status(accession, "not_started")
                            logging.info(
                                "Reset signal card status: ticker=%s accession=%s",
                                ticker,
                                accession,
                            )
                            reset_count += 1
                except Exception as e:
                    logging.error("Failed to reset ticker=%s: %s", ticker, e)
        
        elif accessions_param:
            accessions = [a.strip() for a in accessions_param.split(",") if a.strip()]
            logging.info("Resetting signal cards for accessions: %s", accessions)
            
            for accession in accessions:
                try:
                    state_service.set_signal_card_status(accession, "not_started")
                    logging.info("Reset signal card status: accession=%s", accession)
                    reset_count += 1
                except Exception as e:
                    logging.error("Failed to reset accession=%s: %s", accession, e)
        
        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "reset_count": reset_count,
                "message": f"Reset {reset_count} signal cards to 'not_started' status. Must manually delete signal_card.json blobs from Blob Storage.",
            }),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logging.exception("Failed to reset signal cards")
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "message": str(e),
            }),
            status_code=500,
            mimetype="application/json",
        )


@app.function_name(name="sec_markdown_worker")
@app.queue_trigger(arg_name="msg", queue_name=CONVERT_QUEUE_NAME, connection="AzureWebJobsStorage")
def sec_markdown_worker(msg: func.QueueMessage) -> None:
    deps = _build_worker_dependencies()
    filing_service = deps.filing_service
    blob_store = deps.blob_store
    state_service = deps.state_store
    markdown_service = deps.markdown_service
    section_service = deps.section_service
    signal_card_service = deps.signal_card_service
    batch_service = deps.batch_service
    try:
        payload = _parse_worker_payload(json.loads(msg.get_body().decode("utf-8")))
        ticker = payload["ticker"]
        accession = payload["accession"]
        markdown_blob = payload["markdown_blob"]
        item1a_blob = payload["item1a_blob"]
        item7_blob = payload["item7_blob"]
        signal_card_blob = payload["signal_card_blob"]
        filing_date = payload["filing_date"]
        fiscal_year = payload["fiscal_year"]
        ticker_filing_context = payload["ticker_filing_context"]
        force_reprocess_signal_cards = payload["force_reprocess_signal_cards"]

        current_status = state_service.get_status(accession)
        markdown_exists = blob_store.blob_exists(markdown_blob)
        item1a_exists = blob_store.blob_exists(item1a_blob)
        item7_exists = blob_store.blob_exists(item7_blob)
        signal_card_exists = blob_store.blob_exists(signal_card_blob)

        if force_reprocess_signal_cards and signal_card_exists:
            logging.info(
                "Force signal-card reprocess enabled: proceeding despite existing signal card blob ticker=%s accession=%s",
                ticker,
                accession,
            )
            signal_card_exists = False

        if markdown_exists and item1a_exists and item7_exists and signal_card_exists:
            state_service.set_markdown_status(accession, "markdown_converted")
            state_service.set_item1a_status(accession, "extracted")
            state_service.set_item7_status(accession, "extracted")
            state_service.set_signal_card_status(accession, "extracted")
            return

        if current_status == "error":
            state_service.set_markdown_status(accession, "ready")

        if not markdown_exists:
            markdown = markdown_service.convert_10k_markdown(ticker, accession=accession)
            blob_store.upload_blob(markdown_blob, markdown.encode("utf-8"), content_type="text/markdown")

        state_service.set_markdown_status(accession, "markdown_converted")

        if not (item1a_exists and item7_exists):
            item1a_text, item7_text = section_service.extract_item_sections(ticker, accession)

            if not item1a_exists:
                if item1a_text:
                    blob_store.upload_blob(item1a_blob, item1a_text.encode("utf-8"), content_type="text/markdown")
                    state_service.set_item1a_status(accession, "extracted")
                else:
                    state_service.set_item1a_status(accession, "missing")

            if not item7_exists:
                if item7_text:
                    blob_store.upload_blob(item7_blob, item7_text.encode("utf-8"), content_type="text/markdown")
                    state_service.set_item7_status(accession, "extracted")
                else:
                    state_service.set_item7_status(accession, "missing")

        if not signal_card_exists:
            if not item1a_exists or not item7_exists:
                logging.info(
                    "Skipping signal card extraction for ticker=%s accession=%s: item1a_exists=%s, item7_exists=%s",
                    ticker,
                    accession,
                    item1a_exists,
                    item7_exists,
                )
                state_service.set_signal_card_status(accession, "skipped")
            else:
                if signal_card_service.is_enabled:
                    try:
                        context_entries = ticker_filing_context
                        if not context_entries:
                            logging.info(
                                "No ticker_filing_context provided, using current filing only: accession=%s",
                                accession,
                            )
                            context_entries = [
                                {
                                    "accession": accession,
                                    "fiscal_year": fiscal_year,
                                    "filing_date": filing_date,
                                    "item1a_blob": item1a_blob,
                                    "item7_blob": item7_blob,
                                }
                            ]
                        else:
                            context_accessions = [e.get("accession", "") for e in context_entries]
                            logging.info(
                                "Processing multi-year context for ticker=%s: total_context_entries=%d accessions=%s",
                                ticker,
                                len(context_entries),
                                context_accessions,
                            )

                        historical_filings: list[dict] = []
                        missing_context = []
                        for entry in context_entries:
                            entry_accession = str(entry.get("accession", "")).strip()
                            if not entry_accession:
                                continue
                            entry_item1a_blob = entry.get(
                                "item1a_blob",
                                BlobPaths.item1a(ticker, entry_accession),
                            )
                            entry_item7_blob = entry.get(
                                "item7_blob",
                                BlobPaths.item7(ticker, entry_accession),
                            )

                            logging.debug(
                                "Checking context entry: accession=%s item1a_blob=%s item7_blob=%s",
                                entry_accession,
                                entry_item1a_blob,
                                entry_item7_blob,
                            )

                            if not blob_store.blob_exists(entry_item1a_blob) or not blob_store.blob_exists(entry_item7_blob):
                                logging.warning(
                                    "Missing context blob for accession=%s: item1a_exists=%s item7_exists=%s",
                                    entry_accession,
                                    blob_store.blob_exists(entry_item1a_blob),
                                    blob_store.blob_exists(entry_item7_blob),
                                )
                                missing_context.append(entry_accession)
                                continue

                            logging.debug("Downloading context blobs for accession=%s", entry_accession)
                            entry_item1a_bytes = blob_store.download_blob(entry_item1a_blob)
                            entry_item7_bytes = blob_store.download_blob(entry_item7_blob)
                            historical_filings.append(
                                {
                                    "accession": entry_accession,
                                    "fiscal_year": _safe_int(entry.get("fiscal_year")),
                                    "filing_date": entry.get("filing_date"),
                                    "item1a_text": entry_item1a_bytes.decode("utf-8", errors="replace"),
                                    "item7_text": entry_item7_bytes.decode("utf-8", errors="replace"),
                                }
                            )
                            logging.debug(
                                "Downloaded context blob for accession=%s: item1a_bytes=%d item7_bytes=%d",
                                entry_accession,
                                len(entry_item1a_bytes),
                                len(entry_item7_bytes),
                            )

                        if missing_context:
                            logging.info(
                                "Proceeding with available context for ticker=%s accession=%s. Missing years: %s. Available years: %d/%d",
                                ticker,
                                accession,
                                ",".join(missing_context),
                                len(historical_filings),
                                len(context_entries),
                            )
                        
                        if not historical_filings:
                            logging.warning(
                                "No historical filings available for extraction: ticker=%s accession=%s",
                                ticker,
                                accession,
                            )
                            state_service.set_signal_card_status(accession, "skipped")
                            return

                        if signal_card_service.is_enabled:
                            sorted_entries = sorted(
                                [e for e in context_entries if str(e.get("accession", "")).strip()],
                                key=lambda e: (
                                    -(_safe_int(e.get("fiscal_year")) or -1),
                                    str(e.get("accession", "")),
                                ),
                            )
                            coordinator_accession = (
                                str(sorted_entries[0].get("accession", "")).strip() if sorted_entries else accession
                            )

                            if accession != coordinator_accession:
                                logging.info(
                                    "Skipping non-coordinator filing for ticker-level extraction: ticker=%s accession=%s coordinator_accession=%s",
                                    ticker,
                                    accession,
                                    coordinator_accession,
                                )
                                return

                            execution_mode = os.getenv("SIGNAL_CARD_EXECUTION_MODE", "sync").strip().lower()
                            if execution_mode == "batch":
                                logging.warning(
                                    "Ticker-level extraction currently runs synchronously; execution_mode=batch will be ignored for ticker=%s coordinator_accession=%s",
                                    ticker,
                                    coordinator_accession,
                                )

                            cards = signal_card_service.extract_ticker_signal_cards(
                                ticker=ticker,
                                historical_filings=historical_filings,
                            )
                            cards_by_accession = {str(card.accession).strip(): card for card in cards}

                            logging.info(
                                "Materializing ticker-level extraction results: ticker=%s expected_cards=%d returned_cards=%d",
                                ticker,
                                len(sorted_entries),
                                len(cards_by_accession),
                            )

                            for entry in sorted_entries:
                                entry_accession = str(entry.get("accession", "")).strip()
                                if not entry_accession:
                                    continue

                                card = cards_by_accession.get(entry_accession)
                                entry_signal_card_blob = BlobPaths.signal_card(ticker, entry_accession)

                                if not card:
                                    logging.error(
                                        "Ticker-level extraction missing card for accession: ticker=%s accession=%s",
                                        ticker,
                                        entry_accession,
                                    )
                                    state_service.set_signal_card_status(
                                        entry_accession,
                                        "error",
                                        error_message="Missing card in ticker-level extraction response",
                                    )
                                    continue

                                blob_store.upload_blob(
                                    entry_signal_card_blob,
                                    json.dumps(card.model_dump(mode="json"), indent=2).encode("utf-8"),
                                    content_type="application/json",
                                )
                                state_service.set_signal_card_status(entry_accession, "extracted")
                                logging.info(
                                    "Signal card uploaded from ticker-level extraction: ticker=%s accession=%s signal_card_blob=%s",
                                    ticker,
                                    entry_accession,
                                    entry_signal_card_blob,
                                )
                        else:
                            logging.info(
                                "Signal card extraction is disabled for ticker=%s accession=%s",
                                ticker,
                                accession,
                            )
                            state_service.set_signal_card_status(accession, "skipped")
                    except Exception:
                        logging.exception(
                            "Signal card extraction failed for ticker=%s accession=%s",
                            ticker,
                            accession,
                        )
                        state_service.set_signal_card_status(accession, "error")
                else:
                    logging.info(
                        "Signal card extraction is disabled for ticker=%s accession=%s",
                        ticker,
                        accession,
                    )
                    state_service.set_signal_card_status(accession, "skipped")
    except Exception as ex:
        logging.exception("sec_markdown_worker failed")
        try:
            accession = json.loads(msg.get_body().decode("utf-8")).get("accession")
            if accession:
                state_service.update_status(accession, "error", error_message=_bounded_error_message(ex))
        except Exception:
            logging.exception("Failed to persist error status for sec_markdown_worker")
        return


@app.function_name(name="signal_card_batch_reconciler")
@app.timer_trigger(arg_name="timer", schedule="0 */15 * * * *")  # Every 15 minutes
def signal_card_batch_reconciler(timer: func.TimerRequest) -> None:
    """
    Reconciler function to poll OpenAI batch jobs and materialize completed results.
    Runs every 15 minutes to check batch status and fetch results.
    """
    schedule_status = getattr(timer, "schedule_status", None)
    trigger_time = getattr(schedule_status, "last", None) if schedule_status else None
    logging.info(
        "Signal card batch reconciler started: trigger_time=%s is_past_due=%s",
        trigger_time or "unknown",
        getattr(timer, "past_due", False),
    )

    execution_mode = os.getenv("SIGNAL_CARD_EXECUTION_MODE", "sync").strip().lower()
    if execution_mode != "batch":
        logging.info(
            "Skipping signal card batch reconciler because execution mode is not batch: execution_mode=%s",
            execution_mode,
        )
        return

    deps = _build_reconciler_dependencies()
    state_service = deps.state_store
    blob_store = deps.blob_store
    batch_service = deps.batch_service

    if not batch_service.is_enabled:
        logging.info("Batch service is not enabled, skipping batch reconciliation")
        return

    reconciliation_stats = {
        "batches_checked": 0,
        "batches_completed": 0,
        "batches_failed": 0,
        "batches_in_progress": 0,
        "results_processed": 0,
        "results_successful": 0,
        "results_failed": 0,
    }

    raw_pending_entities = state_service.list_pending_signal_card_batches()
    pending_entities = []
    for raw_entity in raw_pending_entities:
        normalized = _normalize_pending_batch(raw_entity)
        if normalized is None:
            logging.warning("Skipping unsupported pending batch contract object type=%s", type(raw_entity).__name__)
            continue
        pending_entities.append(normalized)

    if not pending_entities:
        logging.info("No pending signal card batches found for reconciliation")
    else:
        logging.info("Reconciling pending signal card batches: entity_count=%d", len(pending_entities))

    entities_by_batch_id: dict[str, list[PendingSignalCardBatch]] = {}

    for entity in pending_entities:
        accession = entity.accession
        signal_card_status = entity.signal_card_status
        batch_id = entity.batch_id

        if signal_card_status == "queued_for_batch" and (not batch_id or batch_id == "pending"):
            logging.warning(
                "Found queued_for_batch entity without submitted batch_id; marking batch_failed: accession=%s",
                accession,
            )
            state_service.update_signal_card_batch_status(
                accession,
                "failed",
                error_message="Queued for batch without a submitted batch id",
            )
            state_service.set_signal_card_status(
                accession,
                "batch_failed",
                error_message="Queued for batch without a submitted batch id",
            )
            reconciliation_stats["results_failed"] += 1
            continue

        if not batch_id or batch_id == "pending":
            logging.warning(
                "Skipping entity without usable batch_id: accession=%s signal_card_status=%s batch_id=%s",
                accession,
                signal_card_status,
                batch_id,
            )
            continue

        if batch_id not in entities_by_batch_id:
            entities_by_batch_id[batch_id] = []
        entities_by_batch_id[batch_id].append(entity)

    for batch_id, batch_entities in entities_by_batch_id.items():
        reconciliation_stats["batches_checked"] += 1
        accessions = [e.accession for e in batch_entities]
        logging.info(
            "Polling batch status: batch_id=%s filings_in_batch=%d accessions=%s",
            batch_id,
            len(batch_entities),
            accessions,
        )

        status_info = batch_service.get_batch_status(batch_id)
        if not status_info:
            logging.warning("Batch status unavailable; will retry on next run: batch_id=%s", batch_id)
            continue

        batch_status = str(status_info.get("status", "")).strip().lower()
        logging.info(
            "Batch status evaluated: batch_id=%s status=%s output_file_id=%s",
            batch_id,
            batch_status,
            status_info.get("output_file_id"),
        )

        if batch_status in {"queued", "validating", "in_progress", "finalizing", "cancelling"}:
            reconciliation_stats["batches_in_progress"] += 1
            for entity in batch_entities:
                accession = entity.accession
                state_service.update_signal_card_batch_status(accession, "in_progress")
                state_service.set_signal_card_status(accession, "batch_submitted")
            continue

        if batch_status == "completed":
            reconciliation_stats["batches_completed"] += 1
            output_file_id = str(status_info.get("output_file_id", "")).strip()
            if not output_file_id:
                logging.error(
                    "Completed batch missing output_file_id; marking all entities failed: batch_id=%s",
                    batch_id,
                )
                for entity in batch_entities:
                    accession = entity.accession
                    state_service.update_signal_card_batch_status(
                        accession,
                        "failed",
                        error_message="Batch completed without output file",
                    )
                    state_service.set_signal_card_status(
                        accession,
                        "batch_failed",
                        error_message="Batch completed without output file",
                    )
                    reconciliation_stats["results_failed"] += 1
                continue

            batch_results = batch_service.fetch_batch_results(batch_id, output_file_id)
            if batch_results is None:
                logging.error(
                    "Failed to fetch completed batch output; will retry next run: batch_id=%s output_file_id=%s",
                    batch_id,
                    output_file_id,
                )
                continue

            result_by_custom_id = {
                str(result.get("custom_id", "")).strip(): result
                for result in batch_results
                if str(result.get("custom_id", "")).strip()
            }

            logging.info(
                "Processing completed batch results: batch_id=%s result_items=%d expected_entities=%d",
                batch_id,
                len(result_by_custom_id),
                len(batch_entities),
            )

            for entity in batch_entities:
                accession = entity.accession
                custom_id = entity.custom_id
                ticker = _resolve_ticker_for_batch_entity(entity)

                reconciliation_stats["results_processed"] += 1

                if not ticker:
                    error_message = "Unable to resolve ticker for batch entity"
                    logging.error(
                        "Failed to materialize batch result: accession=%s custom_id=%s reason=%s",
                        accession,
                        custom_id,
                        error_message,
                    )
                    state_service.update_signal_card_batch_status(accession, "failed", error_message=error_message)
                    state_service.set_signal_card_status(accession, "batch_failed", error_message=error_message)
                    reconciliation_stats["results_failed"] += 1
                    continue

                result = result_by_custom_id.get(custom_id)
                if not result:
                    error_message = f"No batch result item found for custom_id={custom_id}"
                    logging.error(
                        "Missing batch result item: batch_id=%s accession=%s custom_id=%s",
                        batch_id,
                        accession,
                        custom_id,
                    )
                    state_service.update_signal_card_batch_status(accession, "failed", error_message=error_message)
                    state_service.set_signal_card_status(accession, "batch_failed", error_message=error_message)
                    reconciliation_stats["results_failed"] += 1
                    continue

                _, signal_card, error_message = batch_service.parse_batch_result(result)
                if error_message or signal_card is None:
                    final_error = error_message or "Unknown batch parse error"
                    logging.error(
                        "Batch result parse failed: batch_id=%s accession=%s custom_id=%s error=%s",
                        batch_id,
                        accession,
                        custom_id,
                        final_error,
                    )
                    state_service.update_signal_card_batch_status(accession, "failed", error_message=final_error)
                    state_service.set_signal_card_status(accession, "batch_failed", error_message=final_error)
                    reconciliation_stats["results_failed"] += 1
                    continue

                signal_card_blob = BlobPaths.signal_card(ticker, accession)
                try:
                    blob_store.upload_blob(
                        signal_card_blob,
                        json.dumps(signal_card.model_dump(mode="json"), indent=2).encode("utf-8"),
                        content_type="application/json",
                    )
                    state_service.update_signal_card_batch_status(accession, "completed")
                    state_service.set_signal_card_status(accession, "extracted")
                    logging.info(
                        "Batch result materialized successfully: batch_id=%s accession=%s custom_id=%s signal_card_blob=%s",
                        batch_id,
                        accession,
                        custom_id,
                        signal_card_blob,
                    )
                    reconciliation_stats["results_successful"] += 1
                except Exception:
                    logging.exception(
                        "Failed to upload batch signal card artifact: batch_id=%s accession=%s custom_id=%s signal_card_blob=%s",
                        batch_id,
                        accession,
                        custom_id,
                        signal_card_blob,
                    )
                    state_service.update_signal_card_batch_status(
                        accession,
                        "failed",
                        error_message="Artifact upload failed after batch completion",
                    )
                    state_service.set_signal_card_status(
                        accession,
                        "batch_failed",
                        error_message="Artifact upload failed after batch completion",
                    )
                    reconciliation_stats["results_failed"] += 1
            continue

        if batch_status in {"failed", "expired", "cancelled"}:
            reconciliation_stats["batches_failed"] += 1
            mapped_status = "expired" if batch_status == "expired" else "failed"
            for entity in batch_entities:
                accession = entity.accession
                error_message = f"OpenAI batch ended with status={batch_status}"
                state_service.update_signal_card_batch_status(accession, mapped_status, error_message=error_message)
                state_service.set_signal_card_status(accession, "batch_failed", error_message=error_message)
                reconciliation_stats["results_failed"] += 1
                logging.error(
                    "Batch marked failed for accession due to terminal status: batch_id=%s accession=%s status=%s",
                    batch_id,
                    accession,
                    batch_status,
                )
            continue

        logging.warning(
            "Unhandled batch status encountered; preserving in-progress state: batch_id=%s status=%s",
            batch_id,
            batch_status,
        )
        reconciliation_stats["batches_in_progress"] += 1
        for entity in batch_entities:
            accession = entity.accession
            state_service.update_signal_card_batch_status(accession, "in_progress")
            state_service.set_signal_card_status(accession, "batch_submitted")

    logging.info(
        "Signal card batch reconciler completed: batches_checked=%d completed=%d failed=%d in_progress=%d results_processed=%d successful=%d failed=%d",
        reconciliation_stats["batches_checked"],
        reconciliation_stats["batches_completed"],
        reconciliation_stats["batches_failed"],
        reconciliation_stats["batches_in_progress"],
        reconciliation_stats["results_processed"],
        reconciliation_stats["results_successful"],
        reconciliation_stats["results_failed"],
    )
