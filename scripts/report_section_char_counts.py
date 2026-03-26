#!/usr/bin/env python3
"""Report Item 1A / Item 7 character counts for all filings in Blob Storage.

The script scans blob paths under processed/md/{ticker}/{accession}/ and finds:
- item1a.md
- item7.md

For each accession, it reports char counts and available metadata from the
processing state table.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.processing_state import ProcessingStateService
from src.services.sec_downloader import SECDownloaderService

SECTION_BLOB_PATTERN = re.compile(
    r"^processed/md/(?P<ticker>[^/]+)/(?P<accession>[^/]+)/(?P<name>item1a\.md|item7\.md)$",
    re.IGNORECASE,
)


@dataclass
class FilingSectionRecord:
    ticker: str
    accession: str
    item1a_blob: str | None = None
    item7_blob: str | None = None
    item1a_chars: int | None = None
    item7_chars: int | None = None
    item1a_bytes: int | None = None
    item7_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def combined_chars(self) -> int:
        return (self.item1a_chars or 0) + (self.item7_chars or 0)

    @property
    def has_item1a(self) -> bool:
        return self.item1a_blob is not None

    @property
    def has_item7(self) -> bool:
        return self.item7_blob is not None


def _safe_decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _extract_char_and_byte_counts(downloader: SECDownloaderService, blob_name: str) -> tuple[int, int]:
    content = downloader.download_blob(blob_name)
    text = _safe_decode(content)
    return len(text), len(content)


def _load_state_metadata(state_service: ProcessingStateService, accession: str) -> dict[str, Any]:
    entity = state_service.get_entity(accession)
    if not entity:
        return {}

    keys_of_interest = [
        "CIK",
        "CompanyName",
        "Status",
        "DownloadStatus",
        "MarkdownStatus",
        "Item1AStatus",
        "Item7Status",
        "SignalCardStatus",
        "LastUpdatedUtc",
    ]
    return {key: entity.get(key) for key in keys_of_interest if key in entity}


def build_report(ticker_filter: str | None = None) -> list[FilingSectionRecord]:
    downloader = SECDownloaderService()
    state_service = ProcessingStateService()

    if not downloader.container_client:
        raise RuntimeError("Blob container client is not initialized. Check storage configuration.")

    records: dict[tuple[str, str], FilingSectionRecord] = {}

    for blob in downloader.container_client.list_blobs(name_starts_with="processed/md/"):
        blob_name = str(blob.name)
        match = SECTION_BLOB_PATTERN.match(blob_name)
        if not match:
            continue

        ticker = match.group("ticker").upper()
        accession = match.group("accession")
        section_name = match.group("name").lower()

        if ticker_filter and ticker != ticker_filter.upper():
            continue

        key = (ticker, accession)
        if key not in records:
            records[key] = FilingSectionRecord(ticker=ticker, accession=accession)

        record = records[key]
        if section_name == "item1a.md":
            record.item1a_blob = blob_name
        elif section_name == "item7.md":
            record.item7_blob = blob_name

    for record in records.values():
        if record.item1a_blob:
            record.item1a_chars, record.item1a_bytes = _extract_char_and_byte_counts(downloader, record.item1a_blob)
        if record.item7_blob:
            record.item7_chars, record.item7_bytes = _extract_char_and_byte_counts(downloader, record.item7_blob)

        record.metadata = _load_state_metadata(state_service, record.accession)

    return sorted(records.values(), key=lambda r: (r.ticker, r.accession))


def _to_output_rows(records: list[FilingSectionRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in records:
        row = {
            "ticker": rec.ticker,
            "accession": rec.accession,
            "item1a_blob": rec.item1a_blob,
            "item7_blob": rec.item7_blob,
            "item1a_chars": rec.item1a_chars,
            "item7_chars": rec.item7_chars,
            "combined_chars": rec.combined_chars,
            "item1a_bytes": rec.item1a_bytes,
            "item7_bytes": rec.item7_bytes,
            "has_item1a": rec.has_item1a,
            "has_item7": rec.has_item7,
            "cik": rec.metadata.get("CIK"),
            "company_name": rec.metadata.get("CompanyName"),
            "status": rec.metadata.get("Status"),
            "download_status": rec.metadata.get("DownloadStatus"),
            "markdown_status": rec.metadata.get("MarkdownStatus"),
            "item1a_status": rec.metadata.get("Item1AStatus"),
            "item7_status": rec.metadata.get("Item7Status"),
            "signal_card_status": rec.metadata.get("SignalCardStatus"),
            "last_updated_utc": rec.metadata.get("LastUpdatedUtc"),
        }
        rows.append(row)
    return rows


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print(f"Total filings discovered: {len(rows)}")
    print(
        "ticker | accession | item1a_chars | item7_chars | combined_chars | status | company_name"
    )
    print("-" * 120)
    for row in rows:
        print(
            f"{row['ticker']} | {row['accession']} | "
            f"{row['item1a_chars'] or 0} | {row['item7_chars'] or 0} | "
            f"{row['combined_chars']} | {row['status'] or '-'} | {row['company_name'] or '-'}"
        )


def _write_json(rows: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _write_csv(rows: list[dict[str, Any]], path: str) -> None:
    if not rows:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("")
        return

    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report Item 1A and Item 7 character counts for all tickers in blob storage.",
    )
    parser.add_argument(
        "--ticker",
        help="Optional ticker filter (e.g., VRT).",
    )
    parser.add_argument(
        "--json-out",
        help="Optional output path for JSON report.",
    )
    parser.add_argument(
        "--csv-out",
        help="Optional output path for CSV report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = build_report(ticker_filter=args.ticker)
    rows = _to_output_rows(records)

    _print_summary(rows)

    if args.json_out:
        _write_json(rows, args.json_out)
        print(f"\nWrote JSON report: {args.json_out}")

    if args.csv_out:
        _write_csv(rows, args.csv_out)
        print(f"Wrote CSV report: {args.csv_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
