import json
import logging
import os

import azure.functions as func

from src.core.blob_paths import BlobPaths
from src.functions import pipeline_shared as shared


kickoff_bp = func.Blueprint()


@kickoff_bp.function_name(name="manual_kickoff")
@kickoff_bp.route(route="kickoff", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def manual_kickoff(req: func.HttpRequest) -> func.HttpResponse:
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

    deps = shared._build_kickoff_dependencies(queue_connection_string)
    filing_source = deps.filing_source
    blob_store = deps.blob_store
    state_store = deps.state_store
    queue_client = deps.queue_client

    tickers = shared._load_tickers()

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

            ticker_filing_context = shared._build_ticker_filing_context(ticker, filing_metas)

            for filing_meta in filing_metas:
                accession = filing_meta["accession"]
                try:
                    html_blob = BlobPaths.raw_html(ticker, accession)
                    markdown_blob = BlobPaths.markdown(ticker, accession)
                    item1a_blob = BlobPaths.item1a(ticker, accession)
                    item7_blob = BlobPaths.item7(ticker, accession)
                    signal_card_blob = BlobPaths.signal_card(ticker, accession)
                    status = state_store.get_status(accession)
                    insight_blob = BlobPaths.ticker_insight(ticker)

                    insight_exists = blob_store.blob_exists(insight_blob)
                    entity = state_store.get_entity(accession) or {}
                    ticker_insight_status = str(entity.get("TickerInsightStatus", "")).strip().lower()
                    insight_complete = insight_exists and ticker_insight_status in {"completed", "empty"}
                    if not insight_complete:
                        state_store.set_ticker_insight_status(accession, "not_started")

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

                    skip_reason = None
                    if markdown_exists and item1a_exists and item7_exists and signal_card_exists and insight_complete:
                        if not force_reprocess_signal_cards:
                            skip_reason = "already_complete"

                    if skip_reason:
                        skipped += 1
                        logging.info(
                            "Skipping ticker=%s accession=%s because filing artifacts and ticker insight are complete",
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

                    if markdown_exists and item1a_exists and item7_exists and signal_card_exists and not insight_complete:
                        logging.info(
                            "Final insight missing for ticker=%s accession=%s; enqueueing for final-leg generation",
                            ticker,
                            accession,
                        )

                    if status == "error":
                        if force_reprocess_signal_cards:
                            logging.info(
                                "Force retry enabled: reprocessing ticker=%s accession=%s despite filing status=error",
                                ticker,
                                accession,
                            )
                            state_store.update_status(accession, "ready")
                            status = "ready"
                        else:
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
                        message = shared._build_kickoff_queue_message(
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

                    message = shared._build_kickoff_queue_message(
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
                            "error": shared._bounded_error_message(filing_ex),
                        }
                    )
                    not_downloaded.append(
                        {
                            "ticker": ticker,
                            "accession": accession,
                            "reason": shared._bounded_error_message(filing_ex),
                        }
                    )

        except Exception as ex:
            logging.exception("Kickoff failed for ticker=%s", ticker)
            failed.append({"ticker": ticker, "error": shared._bounded_error_message(ex)})
            not_downloaded.append({"ticker": ticker, "reason": shared._bounded_error_message(ex)})

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
