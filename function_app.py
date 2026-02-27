import azure.functions as func
import datetime
import json
import logging
import os

from azure.core.exceptions import ResourceExistsError
from azure.storage.queue import QueueClient
from src.services.sec_downloader import SECDownloaderService
from src.services.html_to_pdf import HTMLToPDFService
from src.services.pdf_to_markdown import PDFToMarkdownService

app = func.FunctionApp()

HTML_QUEUE_NAME = os.getenv("SEC_HTML_QUEUE_NAME", "sec-html-jobs")
PDF_QUEUE_NAME = os.getenv("SEC_PDF_QUEUE_NAME", "sec-pdf-jobs")

TICKERS = ["NEE", "DUK", "SO", "AEP", "CEG"]


@app.function_name(name="manual_kickoff")
@app.route(route="kickoff", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def manual_kickoff(req: func.HttpRequest) -> func.HttpResponse:
	logging.info("Manual kickoff started")
	downloader = SECDownloaderService()

	queue_connection_string = os.getenv("AzureWebJobsStorage")
	if not queue_connection_string:
		return func.HttpResponse(
			json.dumps({"status": "error", "message": "AzureWebJobsStorage is not configured"}),
			status_code=500,
			mimetype="application/json"
		)

	queue_client = QueueClient.from_connection_string(queue_connection_string, HTML_QUEUE_NAME)
	try:
		queue_client.create_queue()
	except ResourceExistsError:
		pass

	enqueued = 0
	skipped = 0
	failed = []

	for ticker in TICKERS:
		try:
			filing = downloader.fetch_latest_10k(ticker)
			accession = filing["accession"]
			html_blob = f"raw/html/{ticker}/{accession}/10-K.html"
			pdf_blob = f"processed/pdf/{ticker}/{accession}/10-K.pdf"
			markdown_blob = f"processed/md/{ticker}/{accession}/10-K.md"

			if not downloader.blob_exists(html_blob):
				downloader.upload_blob(html_blob, filing["html_bytes"], content_type="text/html")

			if downloader.blob_exists(markdown_blob):
				skipped += 1
				continue

			message = {
				"ticker": ticker,
				"accession": accession,
				"html_blob": html_blob,
				"pdf_blob": pdf_blob,
				"markdown_blob": markdown_blob,
				"attempt": 1,
				"queued_at_utc": datetime.datetime.utcnow().isoformat()
			}
			queue_client.send_message(json.dumps(message))
			enqueued += 1
		except Exception as ex:
			failed.append({"ticker": ticker, "error": str(ex)})

	body = {
		"status": "ok",
		"enqueued": enqueued,
		"skipped": skipped,
		"failed": failed
	}
	return func.HttpResponse(json.dumps(body), status_code=200, mimetype="application/json")


@app.function_name(name="html_to_pdf_worker")
@app.queue_trigger(arg_name="msg", queue_name=HTML_QUEUE_NAME, connection="AzureWebJobsStorage")
@app.queue_output(arg_name="pdf_queue_message", queue_name=PDF_QUEUE_NAME, connection="AzureWebJobsStorage")
def html_to_pdf_worker(msg: func.QueueMessage, pdf_queue_message: func.Out[str]) -> None:
	payload = json.loads(msg.get_body().decode("utf-8"))
	ticker = payload["ticker"]
	accession = payload["accession"]
	html_blob = payload["html_blob"]
	pdf_blob = payload["pdf_blob"]
	markdown_blob = payload["markdown_blob"]

	downloader = SECDownloaderService()
	converter = HTMLToPDFService()

	if not downloader.blob_exists(pdf_blob):
		html_bytes = downloader.download_blob(html_blob)
		pdf_bytes = converter.convert_html_bytes(html_bytes)
		downloader.upload_blob(pdf_blob, pdf_bytes, content_type="application/pdf")

	next_message = {
		"ticker": ticker,
		"accession": accession,
		"pdf_blob": pdf_blob,
		"markdown_blob": markdown_blob,
		"attempt": payload.get("attempt", 1),
		"queued_at_utc": datetime.datetime.utcnow().isoformat()
	}
	pdf_queue_message.set(json.dumps(next_message))


@app.function_name(name="pdf_to_markdown_worker")
@app.queue_trigger(arg_name="msg", queue_name=PDF_QUEUE_NAME, connection="AzureWebJobsStorage")
def pdf_to_markdown_worker(msg: func.QueueMessage) -> None:
	payload = json.loads(msg.get_body().decode("utf-8"))
	pdf_blob = payload["pdf_blob"]
	markdown_blob = payload["markdown_blob"]

	downloader = SECDownloaderService()
	if downloader.blob_exists(markdown_blob):
		return

	markdown_service = PDFToMarkdownService()
	pdf_bytes = downloader.download_blob(pdf_blob)
	markdown = markdown_service.convert_pdf_bytes(pdf_bytes)
	downloader.upload_blob(markdown_blob, markdown.encode("utf-8"), content_type="text/markdown")