#!/usr/bin/env python3
"""Download signal card JSON files for a ticker into a single local folder.

Default behavior downloads EQIX signal cards to ./EQIX.

Examples:
  python scripts/download_signal_cards.py
  python scripts/download_signal_cards.py --ticker EQIX --output-dir EQIX
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sys

from azure.storage.blob import BlobServiceClient


def _load_connection_string(project_root: Path) -> str:
    env_candidates = [
        os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip(),
        os.getenv("AzureWebJobsStorage", "").strip(),
    ]
    for candidate in env_candidates:
        if candidate:
            return candidate

    settings_path = project_root / "config" / "local.settings.json"
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        values = data.get("Values", {})
        from_file = str(values.get("AzureWebJobsStorage", "")).strip()
        if from_file:
            return from_file

    raise RuntimeError(
        "Could not find Azure storage connection string. Set AZURE_STORAGE_CONNECTION_STRING or AzureWebJobsStorage."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download signal-card blobs for one ticker into a local folder.",
    )
    parser.add_argument("--ticker", default="EQIX", help="Ticker symbol (default: EQIX)")
    parser.add_argument("--output-dir", default="EQIX", help="Local output folder (default: EQIX)")
    parser.add_argument(
        "--container",
        default="sec-filings",
        help="Blob container name (default: sec-filings)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    ticker = args.ticker.strip().upper()

    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    output_dir = (project_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    connection_string = _load_connection_string(project_root)

    service = BlobServiceClient.from_connection_string(connection_string)
    container = service.get_container_client(args.container)

    prefix = f"processed/signals/{ticker}/"
    signal_blobs = [
        blob.name
        for blob in container.list_blobs(name_starts_with=prefix)
        if blob.name.endswith("/signal_card.json")
    ]

    if not signal_blobs:
        print(f"No signal-card blobs found for ticker={ticker} under prefix={prefix}")
        return 0

    downloaded = 0
    for blob_name in sorted(signal_blobs):
        # Expected: processed/signals/{ticker}/{accession}/signal_card.json
        parts = blob_name.split("/")
        accession = parts[3] if len(parts) >= 5 else f"unknown_{downloaded + 1}"
        target_file = output_dir / f"{accession}.json"

        blob_client = container.get_blob_client(blob_name)
        content = blob_client.download_blob().readall()
        target_file.write_bytes(content)

        downloaded += 1
        print(f"Downloaded {blob_name} -> {target_file}")

    print(f"Done. Downloaded {downloaded} files to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
