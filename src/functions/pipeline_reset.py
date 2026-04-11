import json
import logging

import azure.functions as func

from src.functions import pipeline_shared as shared


reset_bp = func.Blueprint()


@reset_bp.function_name(name="reset_signal_cards")
@reset_bp.route(route="reset-signal-cards", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def reset_signal_cards(req: func.HttpRequest) -> func.HttpResponse:
    """
    Reset signal card processing status for specified tickers/accessions.
    """
    try:
        tickers_param = req.params.get("tickers", "").strip()
        accessions_param = req.params.get("accessions", "").strip()

        if not tickers_param and not accessions_param:
            return func.HttpResponse(
                json.dumps(
                    {
                        "status": "error",
                        "message": "Provide either 'tickers' or 'accessions' query parameter",
                    }
                ),
                status_code=400,
                mimetype="application/json",
            )

        deps = shared._build_reset_dependencies()
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
                except Exception as exc:
                    logging.error("Failed to reset ticker=%s: %s", ticker, exc)

        elif accessions_param:
            accessions = [a.strip() for a in accessions_param.split(",") if a.strip()]
            logging.info("Resetting signal cards for accessions: %s", accessions)

            for accession in accessions:
                try:
                    state_service.set_signal_card_status(accession, "not_started")
                    logging.info("Reset signal card status: accession=%s", accession)
                    reset_count += 1
                except Exception as exc:
                    logging.error("Failed to reset accession=%s: %s", accession, exc)

        return func.HttpResponse(
            json.dumps(
                {
                    "status": "ok",
                    "reset_count": reset_count,
                    "message": f"Reset {reset_count} signal cards to 'not_started' status. Must manually delete signal_card.json blobs from Blob Storage.",
                }
            ),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as exc:
        logging.exception("Failed to reset signal cards")
        return func.HttpResponse(
            json.dumps(
                {
                    "status": "error",
                    "message": str(exc),
                }
            ),
            status_code=500,
            mimetype="application/json",
        )
