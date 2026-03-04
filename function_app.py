import datetime
import json
import logging
import os

import azure.functions as func
from azure.core.exceptions import ResourceExistsError
from azure.storage.queue import QueueClient

from src.services.html_to_pdf import HTMLToPDFService
from src.services.pdf_to_markdown import PDFToMarkdownService
from src.services.processing_state import ProcessingStateService
from src.services.sec_downloader import SECDownloaderService

app = func.FunctionApp()

HTML_QUEUE_NAME = os.getenv("SEC_HTML_QUEUE_NAME", "sec-html-jobs")
PDF_QUEUE_NAME = os.getenv("SEC_PDF_QUEUE_NAME", "sec-pdf-jobs")
TICKERS = ["NEE", "DUK", "SO", "AEP", "CEG"]


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

    html_queue_client = _get_queue_client(queue_connection_string, HTML_QUEUE_NAME)
    pdf_queue_client = _get_queue_client(queue_connection_string, PDF_QUEUE_NAME)

    enqueued_html = 0
    enqueued_pdf = 0
    skipped = 0
    failed = []

    for ticker in TICKERS:
        try:
            filing_meta = downloader.fetch_latest_10k_metadata(ticker)
            accession = filing_meta["accession"]

            html_blob = f"raw/html/{ticker}/{accession}/10-K.html"
            pdf_blob = f"processed/pdf/{ticker}/{accession}/10-K.pdf"
            markdown_blob = f"processed/md/{ticker}/{accession}/10-K.md"
            status = state_service.get_status(accession)

            if status == "markdown_converted":
                skipped += 1
                continue

            if status == "pdf_converted":
                message = {
                    "ticker": ticker,
                    "accession": accession,
                    "pdf_blob": pdf_blob,
                    "markdown_blob": markdown_blob,
                    "attempt": 1,
                    "queued_at_utc": datetime.datetime.utcnow().isoformat(),
                }
                pdf_queue_client.send_message(json.dumps(message))
                enqueued_pdf += 1
                continue

            if status == "ready":
                message = {
                    "ticker": ticker,
                    "accession": accession,
                    "html_blob": html_blob,
                    "pdf_blob": pdf_blob,
                    "markdown_blob": markdown_blob,
                    "attempt": 1,
                    "queued_at_utc": datetime.datetime.utcnow().isoformat(),
                }
                html_queue_client.send_message(json.dumps(message))
                enqueued_html += 1
                continue

            if status == "error":
                skipped += 1
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
                "html_blob": html_blob,
                "pdf_blob": pdf_blob,
                "markdown_blob": markdown_blob,
                "attempt": 1,
                "queued_at_utc": datetime.datetime.utcnow().isoformat(),
            }
            html_queue_client.send_message(json.dumps(message))
            enqueued_html += 1

        except Exception as ex:
            logging.exception("Kickoff failed for ticker=%s", ticker)
            failed.append({"ticker": ticker, "error": str(ex)})

    return func.HttpResponse(
        json.dumps(
            {
                "status": "ok",
                "enqueued_html": enqueued_html,
                "enqueued_pdf": enqueued_pdf,
                "skipped": skipped,
                "failed": failed,
            }
        ),
        status_code=200,
        mimetype="application/json",
    )


@app.function_name(name="html_to_pdf_worker")
@app.queue_trigger(arg_name="msg", queue_name=HTML_QUEUE_NAME, connection="AzureWebJobsStorage")
def html_to_pdf_worker(msg: func.QueueMessage) -> None:
    state_service = ProcessingStateService()
    try:
        payload = json.loads(msg.get_body().decode("utf-8"))
        ticker = payload["ticker"]
        accession = payload["accession"]
        html_blob = payload["html_blob"]
        pdf_blob = payload["pdf_blob"]
        markdown_blob = payload["markdown_blob"]

        logging.info("html_to_pdf_worker start ticker=%s accession=%s", ticker, accession)

        downloader = SECDownloaderService()
        converter = HTMLToPDFService()
        current_status = state_service.get_status(accession)

        if current_status == "markdown_converted":
            return

        if current_status == "pdf_converted":
            return

        if current_status != "ready":
            logging.warning("Skipping html_to_pdf_worker due to unexpected status=%s accession=%s", current_status, accession)
            return

        if not downloader.blob_exists(pdf_blob):
            html_bytes = downloader.download_blob(html_blob)
            pdf_bytes = converter.convert_html_bytes(html_bytes)
            downloader.upload_blob(pdf_blob, pdf_bytes, content_type="application/pdf")

        state_service.update_status(accession, "pdf_converted")

        queue_connection_string = os.getenv("AzureWebJobsStorage")
        if not queue_connection_string:
            raise RuntimeError("AzureWebJobsStorage is not configured.")

        next_queue_client = _get_queue_client(queue_connection_string, PDF_QUEUE_NAME)

        next_message = {
            "ticker": ticker,
            "accession": accession,
            "pdf_blob": pdf_blob,
            "markdown_blob": markdown_blob,
            "attempt": payload.get("attempt", 1),
            "queued_at_utc": datetime.datetime.utcnow().isoformat(),
        }
        next_queue_client.send_message(json.dumps(next_message))
    except Exception as ex:
        logging.exception("html_to_pdf_worker failed")
        try:
            accession = json.loads(msg.get_body().decode("utf-8")).get("accession")
            if accession:
                state_service.update_status(accession, "error", error_message=str(ex))
        except Exception:
            logging.exception("Failed to persist error status for html_to_pdf_worker")
        return


@app.function_name(name="pdf_to_markdown_worker")
@app.queue_trigger(arg_name="msg", queue_name=PDF_QUEUE_NAME, connection="AzureWebJobsStorage")
def pdf_to_markdown_worker(msg: func.QueueMessage) -> None:
    state_service = ProcessingStateService()
    try:
        payload = json.loads(msg.get_body().decode("utf-8"))
        accession = payload["accession"]
        pdf_blob = payload["pdf_blob"]
        markdown_blob = payload["markdown_blob"]

        downloader = SECDownloaderService()
        current_status = state_service.get_status(accession)

        if current_status == "markdown_converted":
            return

        if current_status != "pdf_converted":
            logging.warning(
                "Skipping pdf_to_markdown_worker due to unexpected status=%s accession=%s",
                current_status,
                accession,
            )
            return

        if downloader.blob_exists(markdown_blob):
            state_service.update_status(accession, "markdown_converted")
            return

        markdown_service = PDFToMarkdownService()
        pdf_bytes = downloader.download_blob(pdf_blob)
        markdown = markdown_service.convert_pdf_bytes(pdf_bytes)
        downloader.upload_blob(markdown_blob, markdown.encode("utf-8"), content_type="text/markdown")
        state_service.update_status(accession, "markdown_converted")
    except Exception as ex:
        logging.exception("pdf_to_markdown_worker failed")
        try:
            accession = json.loads(msg.get_body().decode("utf-8")).get("accession")
            if accession:
                state_service.update_status(accession, "error", error_message=str(ex))
        except Exception:
            logging.exception("Failed to persist error status for pdf_to_markdown_worker")
        return