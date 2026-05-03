#!/usr/bin/env python3
"""Reset ticker-insight state so only the final LLM analysis step is retried.

Examples:
  python scripts/admin/reset_ticker_insights.py --ticker CEG
  python scripts/admin/reset_ticker_insights.py --ticker CEG,EQIX
  python scripts/admin/reset_ticker_insights.py --accession 0001868275-26-000032
  python scripts/admin/reset_ticker_insights.py --all-accessions
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.processing_state import ProcessingStateService


def _load_local_settings_into_env(settings_path: Path) -> None:
    if not settings_path.exists():
        return

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return

    values = payload.get("Values", {})
    if not isinstance(values, dict):
        return

    for key, value in values.items():
        if key in os.environ:
            continue
        if value is None:
            continue
        os.environ[key] = str(value)


def _extract_ticker_from_source_blob(source_blob: str) -> str:
    parts = str(source_blob or "").split("/")
    if len(parts) >= 3 and parts[0] == "raw" and parts[1] == "html":
        return parts[2].strip().upper()
    return ""


def _iter_partition_entities(state_service: ProcessingStateService):
    query = f"PartitionKey eq '{state_service.partition_key}'"
    return state_service.table_client.query_entities(query_filter=query)


def _collect_accessions_by_ticker(state_service: ProcessingStateService, tickers: set[str]) -> list[str]:
    accessions: list[str] = []
    for entity in _iter_partition_entities(state_service):
        ticker = _extract_ticker_from_source_blob(entity.get("SourceBlob", ""))
        if ticker and ticker in tickers:
            accession = str(entity.get("RowKey", "")).strip()
            if accession:
                accessions.append(accession)
    return sorted(set(accessions))


def _collect_all_accessions(state_service: ProcessingStateService) -> list[str]:
    accessions: list[str] = []
    for entity in _iter_partition_entities(state_service):
        accession = str(entity.get("RowKey", "")).strip()
        if accession:
            accessions.append(accession)
    return sorted(set(accessions))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset ticker insight status for retry.")
    parser.add_argument("--ticker", help="Comma-separated tickers, e.g. CEG,EQIX")
    parser.add_argument("--accession", help="Comma-separated accessions")
    parser.add_argument("--all-accessions", action="store_true", help="Reset all accessions in current partition")
    parser.add_argument(
        "--keep-metadata",
        action="store_true",
        help="Keep TickerInsightBlob and TickerInsightGeneratedUtc values",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    _load_local_settings_into_env(PROJECT_ROOT / "config" / "local.settings.json")
    _load_local_settings_into_env(PROJECT_ROOT / "local.settings.json")

    state_service = ProcessingStateService()

    accessions: list[str] = []
    if args.ticker:
        tickers = {t.strip().upper() for t in args.ticker.split(",") if t.strip()}
        accessions = _collect_accessions_by_ticker(state_service, tickers)
    elif args.accession:
        accessions = sorted({a.strip() for a in args.accession.split(",") if a.strip()})
    elif args.all_accessions:
        accessions = _collect_all_accessions(state_service)
    else:
        print("Provide one of --ticker, --accession, or --all-accessions")
        return 1

    if not accessions:
        print("No matching accessions found to reset")
        return 0

    clear_metadata = not args.keep_metadata
    for accession in accessions:
        state_service.reset_ticker_insight_state(accession, clear_metadata=clear_metadata)

    print(f"Reset ticker insight state for {len(accessions)} accession(s)")
    print("Next: trigger kickoff without force flag to rerun only final insight leg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
