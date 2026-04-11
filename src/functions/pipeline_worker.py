import json
import logging
import os

import azure.functions as func

from src.core.blob_paths import BlobPaths
from src.functions import pipeline_shared as shared


worker_bp = func.Blueprint()


@worker_bp.function_name(name="sec_markdown_worker")
@worker_bp.queue_trigger(arg_name="msg", queue_name=shared.CONVERT_QUEUE_NAME, connection="AzureWebJobsStorage")
def sec_markdown_worker(msg: func.QueueMessage) -> None:
    deps = shared._build_worker_dependencies()
    blob_store = deps.blob_store
    state_service = deps.state_store
    markdown_service = deps.markdown_service
    section_service = deps.section_service
    signal_card_service = deps.signal_card_service

    try:
        payload = shared._parse_worker_payload(json.loads(msg.get_body().decode("utf-8")))
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
                                    "fiscal_year": shared._safe_int(entry.get("fiscal_year")),
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
                                    -(shared._safe_int(e.get("fiscal_year")) or -1),
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
                state_service.update_status(accession, "error", error_message=shared._bounded_error_message(ex))
        except Exception:
            logging.exception("Failed to persist error status for sec_markdown_worker")
