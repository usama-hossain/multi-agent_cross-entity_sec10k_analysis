import argparse
import csv
import json
import os
import re
from typing import Dict, Iterable, List, Optional

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from bs4 import BeautifulSoup


ACCESSION_PATTERN = re.compile(r"\d{10}-\d{2}-\d{6}")
ACCESSION_HEADER_PATTERN = re.compile(
    r"ACCESSION\s+NUMBER\s*[:\-]?\s*(\d{10}-\d{2}-\d{6})",
    re.IGNORECASE,
)


def _get_local_settings_value(key: str) -> Optional[str]:
    project_root = os.path.dirname(os.path.dirname(__file__))
    settings_path = os.path.join(project_root, "config", "local.settings.json")
    if not os.path.exists(settings_path):
        return None

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("Values", {}).get(key)
    except Exception:
        return None


def _create_blob_service_client() -> BlobServiceClient:
    account_url = os.getenv("BLOB_ACCOUNT_URL") or _get_local_settings_value("BLOB_ACCOUNT_URL")
    connection_string = os.getenv("AzureWebJobsStorage") or _get_local_settings_value("AzureWebJobsStorage")

    if account_url:
        return BlobServiceClient(account_url, credential=DefaultAzureCredential())

    if connection_string and connection_string != "UseDevelopmentStorage=true":
        return BlobServiceClient.from_connection_string(connection_string)

    raise RuntimeError(
        "Blob connection is not configured. Set BLOB_ACCOUNT_URL or AzureWebJobsStorage in the environment or in config/local.settings.json."
    )


def _first_value(values: Iterable[str]) -> Optional[str]:
    for value in values:
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _extract_accession(blob_name: str, html_text: str) -> Optional[str]:
    path_match = ACCESSION_PATTERN.search(blob_name)
    if path_match:
        return path_match.group(0)

    header_match = ACCESSION_HEADER_PATTERN.search(html_text)
    if header_match:
        return header_match.group(1)

    return None


def _extract_metadata_from_html(blob_name: str, html_bytes: bytes) -> Dict[str, Optional[str]]:
    html_text = html_bytes.decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html_text, "lxml")

    cik_candidates = []
    name_candidates = []

    for tag in soup.find_all(attrs={"name": True}):
        tag_name = str(tag.get("name", "")).strip()
        if tag_name == "dei:EntityCentralIndexKey":
            cik_candidates.append(tag.get_text(strip=True))
        elif tag_name == "dei:EntityRegistrantName":
            name_candidates.append(tag.get_text(strip=True))

    return {
        "blob_name": blob_name,
        "accession_key": _extract_accession(blob_name, html_text),
        "cik": _first_value(cik_candidates),
        "conformed_name": _first_value(name_candidates),
    }


def _write_json(rows: List[Dict[str, Optional[str]]], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _write_csv(rows: List[Dict[str, Optional[str]]], output_path: str) -> None:
    fieldnames = ["blob_name", "accession_key", "cik", "conformed_name"]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract accession key, CIK, and conformed name from SEC filing HTML blobs."
    )
    parser.add_argument(
        "--container",
        default=(
            os.getenv("BLOB_CONTAINER_NAME")
            or _get_local_settings_value("BLOB_CONTAINER_NAME")
            or "sec-filings"
        ),
        help="Azure Blob container name (default: env BLOB_CONTAINER_NAME or sec-filings)",
    )
    parser.add_argument(
        "--prefix",
        default="raw/html/",
        help="Blob prefix to scan (default: raw/html/)",
    )
    parser.add_argument(
        "--output",
        default="sec_metadata.json",
        help="Output file path (default: sec_metadata.json)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of HTML blobs to process (0 = no limit)",
    )
    args = parser.parse_args()

    blob_service_client = _create_blob_service_client()
    container_client = blob_service_client.get_container_client(args.container)

    rows: List[Dict[str, Optional[str]]] = []
    processed = 0

    for blob in container_client.list_blobs(name_starts_with=args.prefix):
        blob_name = blob.name
        if not blob_name.lower().endswith(".html"):
            continue

        blob_client = container_client.get_blob_client(blob_name)
        html_bytes = blob_client.download_blob().readall()
        rows.append(_extract_metadata_from_html(blob_name, html_bytes))

        processed += 1
        if args.limit > 0 and processed >= args.limit:
            break

    if args.format == "json":
        _write_json(rows, args.output)
    else:
        _write_csv(rows, args.output)

    print(f"Processed {processed} HTML blob(s).")
    print(f"Wrote {len(rows)} row(s) to {args.output}")


if __name__ == "__main__":
    main()