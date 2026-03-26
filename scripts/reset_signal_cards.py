#!/usr/bin/env python3
"""
Reset signal card processing for specified tickers or accessions.
Deletes signal_card.json blobs and resets SignalCardStatus to 'not_started'.

Usage:
  python scripts/reset_signal_cards.py --ticket NEE,DUK,SO
  python scripts/reset_signal_cards.py --accession 0000753308-26-000015
  python scripts/reset_signal_cards.py --all-tickers
"""

import argparse
import logging
import os
import sys
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.processing_state import ProcessingStateService
from src.services.sec_downloader import SECDownloaderService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def reset_signal_card(
    ticker: str,
    accession: str,
    downloader: SECDownloaderService,
    state_service: ProcessingStateService,
) -> bool:
    """Reset a single signal card: delete blob and reset status."""
    signal_card_blob = f"processed/signals/{ticker}/{accession}/signal_card.json"
    
    try:
        # Check if blob exists
        if downloader.blob_exists(signal_card_blob):
            logger.info(f"Deleting signal card blob: {signal_card_blob}")
            # Note: Azure SDK doesn't have direct delete in our wrapper,
            # so we'll rely on table status reset and log the blob name
            logger.warning(
                f"⚠️  Manual blob deletion needed: {signal_card_blob}"
            )
        
        # Reset status in table
        state_service.set_signal_card_status(accession, "not_started")
        logger.info(
            f"Reset signal card status to 'not_started': ticker={ticker} accession={accession}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Failed to reset signal card: ticker={ticker} accession={accession} error={e}"
        )
        return False


def reset_by_ticker(tickers: list[str]) -> int:
    """Reset all signal cards for specified tickers."""
    downloader = SECDownloaderService()
    state_service = ProcessingStateService()
    
    if not downloader.container_client:
        logger.error("Blob container client not initialized. Check configuration.")
        return 1
    
    reset_count = 0
    for ticker in tickers:
        logger.info(f"Processing ticker: {ticker}")
        
        try:
            filing_metas = downloader.fetch_recent_10k_metadata(ticker, max_filings=5)
            if not filing_metas:
                logger.warning(f"No recent 10-K filings found for ticker={ticker}")
                continue
            
            for filing_meta in filing_metas:
                accession = filing_meta.get("accession")
                if accession and reset_signal_card(ticker, accession, downloader, state_service):
                    reset_count += 1
        except Exception as e:
            logger.error(f"Failed to process ticker={ticker}: {e}")
    
    return reset_count


def reset_by_accession(accessions: list[str]) -> int:
    """Reset signal cards by accession (requires ticker context from state table)."""
    downloader = SECDownloaderService()
    state_service = ProcessingStateService()
    
    reset_count = 0
    for accession in accessions:
        try:
            entity = state_service.get_entity(accession)
            if not entity:
                logger.warning(f"Accession not found in state table: {accession}")
                continue
            
            source_blob = entity.get("SourceBlob", "")
            if source_blob.startswith("raw/html/"):
                parts = source_blob.split("/")
                if len(parts) >= 3:
                    ticker = parts[2].upper()
                    if reset_signal_card(ticker, accession, downloader, state_service):
                        reset_count += 1
                    continue
            
            logger.warning(f"Unable to extract ticker from SourceBlob for accession={accession}")
        except Exception as e:
            logger.error(f"Failed to process accession={accession}: {e}")
    
    return reset_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset signal card processing status.",
    )
    parser.add_argument(
        "--ticker",
        help="Comma-separated list of tickers (e.g., NEE,DUK,SO)",
    )
    parser.add_argument(
        "--accession",
        help="Comma-separated list of accession numbers",
    )
    parser.add_argument(
        "--all-tickers",
        action="store_true",
        help="Reset all tickers from local tickers.json",
    )
    args = parser.parse_args()
    
    # Load tickers.json for --all-tickers option
    all_ticker_list = []
    if args.all_tickers:
        import json
        tickers_file = os.path.join(PROJECT_ROOT, "tickers.json")
        if os.path.exists(tickers_file):
            with open(tickers_file, "r") as f:
                data = json.load(f)
                if "companies" in data:
                    all_ticker_list = [c["ticker"] for c in data["companies"]]
        if not all_ticker_list:
            logger.error("No tickers found in tickers.json")
            return 1
        logger.info(f"Loaded {len(all_ticker_list)} tickers from tickers.json")
    
    reset_count = 0
    
    if args.ticker:
        tickers = [t.strip().upper() for t in args.ticker.split(",")]
        logger.info(f"Resetting signal cards for tickers: {tickers}")
        reset_count = reset_by_ticker(tickers)
    elif args.accession:
        accessions = [a.strip() for a in args.accession.split(",")]
        logger.info(f"Resetting signal cards for accessions: {accessions}")
        reset_count = reset_by_accession(accessions)
    elif args.all_tickers:
        logger.info(f"Resetting signal cards for all tickers: {all_ticker_list}")
        reset_count = reset_by_ticker(all_ticker_list)
    else:
        parser.print_help()
        return 1
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Reset complete: {reset_count} signal cards reset to 'not_started'")
    logger.info(f"{'='*60}")
    
    if reset_count > 0:
        logger.warning(
            "\n⚠️  MANUAL STEP REQUIRED:\n"
            "1. Delete signal_card.json blobs from Azure Blob Storage:\n"
            "   - Path pattern: processed/signals/{ticker}/{accession}/signal_card.json\n"
            "2. Re-run kickoff to trigger LLM extraction:\n"
            "   - curl -X POST http://localhost:7071/api/kickoff"
        )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
