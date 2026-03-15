import datetime
import json
import logging
import os
from pathlib import Path

import azure.functions as func
from azure.core.exceptions import ResourceExistsError
from azure.storage.queue import QueueClient

from src.services.processing_state import ProcessingStateService
from src.services.sec_downloader import SECDownloaderService
from src.services.sec_edgar_markdown import SECEdgarMarkdownService

app = func.FunctionApp()

CONVERT_QUEUE_NAME = os.getenv("SEC_CONVERT_QUEUE_NAME", "sec-convert-jobs")


def _load_tickers() -> list[str]:
    tickers_path = Path(__file__).with_name("tickers.json")
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
        raise ValueError("tickers.json does not contain any valid tickers.")

    return tickers


def _get_queue_client(connection_string: str, queue_name: str) -> QueueClient:
    queue_client = QueueClient.from_connection_string(connection_string, queue_name)
    try:
        queue_client.create_queue()
    except ResourceExistsError:
        pass
    return queue_client


@app.function_name(name="manual_kickoff")
@app.route(route="kickoff", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def manual_kickoff(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Manual kickoff started")
    downloader = SECDownloaderService()
    state_service = ProcessingStateService()

    queue_connection_string = os.getenv("AzureWebJobsStorage")
    if not queue_connection_string:
        return func.HttpResponse(
            json.dumps({"status": "error", "message": "AzureWebJobsStorage is not configured"}),
            status_code=500,
            mimetype="application/json",
        )

    convert_queue_client = _get_queue_client(queue_connection_string, CONVERT_QUEUE_NAME)
    tickers = _load_tickers()

    enqueued = 0
    skipped = 0
    failed = []

    for ticker in tickers:
        try:
            filing_meta = downloader.fetch_latest_10k_metadata(ticker)
            accession = filing_meta["accession"]

            html_blob = f"raw/html/{ticker}/{accession}/10-K.html"
            markdown_blob = f"processed/md/{ticker}/{accession}/10-K.md"
            status = state_service.get_status(accession)

            if status in ("markdown_converted", "error"):
                skipped += 1
                continue

            if status in ("ready", "pdf_converted"):
                message = {
                    "ticker": ticker,
                    "accession": accession,
                    "markdown_blob": markdown_blob,
                    "attempt": 1,
                    "queued_at_utc": datetime.datetime.utcnow().isoformat(),
                }
                convert_queue_client.send_message(json.dumps(message))
                enqueued += 1
                continue

            # TODO: Future enhancement - add atomic claim/lease before download to prevent concurrent kickoff races.
            html_bytes = downloader.download_filing_html(filing_meta["file_url"])
            if not downloader.blob_exists(html_blob):
                downloader.upload_blob(html_blob, html_bytes, content_type="text/html")

            state_service.upsert_filing(
                accession=accession,
                cik=filing_meta["cik"],
                company_name=filing_meta.get("company_name") or ticker,
                source_blob=html_blob,
                status="ready",
            )

            message = {
                "ticker": ticker,
                "accession": accession,
                "markdown_blob": markdown_blob,
                "attempt": 1,
                "queued_at_utc": datetime.datetime.utcnow().isoformat(),
            }
            convert_queue_client.send_message(json.dumps(message))
            enqueued += 1

        except Exception as ex:
            logging.exception("Kickoff failed for ticker=%s", ticker)
            failed.append({"ticker": ticker, "error": str(ex)})

    return func.HttpResponse(
        json.dumps(
            {
                "status": "ok",
                "enqueued": enqueued,
                "skipped": skipped,
                "failed": failed,
            }
        ),
        status_code=200,
        mimetype="application/json",
    )


@app.function_name(name="sec_markdown_worker")
@app.queue_trigger(arg_name="msg", queue_name=CONVERT_QUEUE_NAME, connection="AzureWebJobsStorage")
def sec_markdown_worker(msg: func.QueueMessage) -> None:
    state_service = ProcessingStateService()
    try:
        payload = json.loads(msg.get_body().decode("utf-8"))
        ticker = payload["ticker"]
        accession = payload["accession"]
        markdown_blob = payload["markdown_blob"]

        downloader = SECDownloaderService()
        current_status = state_service.get_status(accession)

        if current_status == "markdown_converted":
            return

        if downloader.blob_exists(markdown_blob):
            state_service.update_status(accession, "markdown_converted")
            return

        sec_markdown_service = SECEdgarMarkdownService()
        markdown = sec_markdown_service.convert_latest_10k_markdown(ticker)
        downloader.upload_blob(markdown_blob, markdown.encode("utf-8"), content_type="text/markdown")
        state_service.update_status(accession, "markdown_converted")
    except Exception as ex:
        logging.exception("sec_markdown_worker failed")
        try:
            accession = json.loads(msg.get_body().decode("utf-8")).get("accession")
            if accession:
                state_service.update_status(accession, "error", error_message=str(ex))
        except Exception:
            logging.exception("Failed to persist error status for sec_markdown_worker")
        return