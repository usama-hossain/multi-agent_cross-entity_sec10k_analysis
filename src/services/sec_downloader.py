import os
import requests
import logging
from typing import Optional
from src.adapters.blob_storage import AzureBlobArtifactStore


class BlobArtifactStore(AzureBlobArtifactStore):
    """Compatibility alias for blob adapter usage in existing call sites."""

    pass

class SECDownloaderService:
    _ticker_map_cache = None

    def __init__(self):
        # Professional Config: Load from Env, fail gracefully if missing
        self.company_name = os.getenv("SEC_COMPANY_NAME", "EnergyAI-Research")
        self.email = os.getenv("SEC_EMAIL", "scarredentos@gmail.com")
        self.user_agent = f"{self.company_name} {self.email}"
        self.request_timeout_seconds = float(os.getenv("SEC_HTTP_TIMEOUT_SECONDS", "20"))
        
        # Headers required by SEC to prevent 403 Forbidden errors
        self.headers = {"User-Agent": self.user_agent}

        # Keep blob operations in dedicated adapter while preserving legacy methods.
        self.blob_store = BlobArtifactStore()

        # Load Ticker -> CIK map once per worker process.
        if SECDownloaderService._ticker_map_cache is None:
            SECDownloaderService._ticker_map_cache = self._load_ticker_map()
        self.ticker_map = SECDownloaderService._ticker_map_cache

    def blob_exists(self, blob_name: str) -> bool:
        # Backward-compatible facade for existing call sites.
        return self.blob_store.blob_exists(blob_name)

    def upload_blob(self, blob_name: str, data: bytes, content_type: Optional[str] = None):
        # Backward-compatible facade for existing call sites.
        self.blob_store.upload_blob(blob_name, data, content_type=content_type)

    def download_blob(self, blob_name: str) -> bytes:
        # Backward-compatible facade for existing call sites.
        return self.blob_store.download_blob(blob_name)

    def _load_ticker_map(self):
        """Fetches the official SEC map of Ticker -> CIK."""
        logging.info("Loading SEC ticker map from SEC endpoint")
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.request_timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            # Transform {0: {cik_str, ticker, title}, ...} -> {TICKER: CIK}
            return {item["ticker"]: item["cik_str"] for item in data.values()}
        except Exception as e:
            logging.exception("Failed to load SEC ticker map")
            return {}

    def fetch_and_upload_10k(self, tickers: list):
        results = {}
        for ticker in tickers:
            cik = self.ticker_map.get(ticker.upper())
            if not cik:
                print(f"Error: CIK not found for {ticker}")
                continue

            # 1. Get Filing History (Submissions API)
            # CIK must be 10 digits, zero-padded for this API
            cik_padded = str(cik).zfill(10)
            print(f"Fetching metadata for {ticker} (CIK: {cik_padded})...")
            
            meta_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
            resp = requests.get(meta_url, headers=self.headers, timeout=self.request_timeout_seconds)
            
            if resp.status_code != 200:
                print(f"Failed to fetch metadata for {ticker}")
                continue
                
            data = resp.json()
            filings = data.get("filings", {}).get("recent", {})
            
            # 2. Find the latest 10-K
            # We iterate through the lists to find the first index where form is "10-K"
            accession_num = None
            primary_doc = None
            
            if "form" in filings:
                for i, form in enumerate(filings["form"]):
                    if form == "10-K":
                        accession_num = filings["accessionNumber"][i]
                        primary_doc = filings["primaryDocument"][i]
                        break
            
            if not accession_num:
                print(f"No 10-K found for {ticker}")
                continue

            # 3. Construct the Download URL
            # SEC URL logic: archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}
            accession_no_dashes = accession_num.replace("-", "")
            file_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"
            
            # 4. Stream Download -> Memory -> Azure Blob
            print(f"Downloading {ticker} 10-K from {file_url}...")
            file_resp = requests.get(file_url, headers=self.headers, timeout=self.request_timeout_seconds)
            
            if file_resp.status_code == 200:
                blob_name = f"{ticker}/{accession_num}/10-K.html"
                if self.blob_store.container_client:
                    print(f"Uploading to Azure Blob: {blob_name}")
                    self.blob_store.upload_blob(blob_name, file_resp.content)
                    results[ticker] = "Uploaded"
                else:
                    results[ticker] = "Downloaded (No Azure Context)"
            else:
                print(f"Failed to download file content for {ticker}")

        return results

    def fetch_latest_10k(self, ticker: str):
        metadata = self.fetch_latest_10k_metadata(ticker)
        html_bytes = self.download_filing_html(metadata["file_url"])

        return {
            "ticker": metadata["ticker"],
            "cik": metadata["cik"],
            "company_name": metadata.get("company_name"),
            "accession": metadata["accession"],
            "primary_document": metadata["primary_document"],
            "file_url": metadata["file_url"],
            "html_bytes": html_bytes,
        }

    def fetch_recent_10k_metadata(self, ticker: str, max_filings: int = 5):
        if max_filings < 1:
            raise ValueError("max_filings must be at least 1")

        cik = self.ticker_map.get(ticker.upper())
        if not cik:
            raise ValueError(f"CIK not found for {ticker}")

        cik_padded = str(cik).zfill(10)
        meta_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        resp = requests.get(meta_url, headers=self.headers, timeout=self.request_timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
        filings = data.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])
        report_dates = filings.get("reportDate", [])
        filing_dates = filings.get("filingDate", [])

        results = []
        for i, form in enumerate(forms):
            if form != "10-K":
                continue

            accession_num = accessions[i] if i < len(accessions) else None
            primary_doc = primary_docs[i] if i < len(primary_docs) else None
            report_date = report_dates[i] if i < len(report_dates) else None
            filing_date = filing_dates[i] if i < len(filing_dates) else None

            if not accession_num or not primary_doc:
                continue

            accession_no_dashes = accession_num.replace("-", "")
            file_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"
            fiscal_year = None
            if isinstance(report_date, str) and len(report_date) >= 4:
                fiscal_year = report_date[:4]
            elif isinstance(filing_date, str) and len(filing_date) >= 4:
                fiscal_year = filing_date[:4]

            results.append(
                {
                    "ticker": ticker.upper(),
                    "cik": str(cik).zfill(10),
                    "company_name": data.get("name") or ticker.upper(),
                    "accession": accession_num,
                    "primary_document": primary_doc,
                    "file_url": file_url,
                    "form": form,
                    "report_date": report_date,
                    "filing_date": filing_date,
                    "fiscal_year": fiscal_year,
                }
            )

            if len(results) >= max_filings:
                break

        if not results:
            print(f"No 10-K filings found for {ticker}")
            return []

        if len(results) < max_filings:
            print(
                f"{ticker.upper()}: only found {len(results)} 10-K filing(s); requested {max_filings}."
            )

        return results

    def fetch_latest_10k_metadata(self, ticker: str):
        return self.fetch_recent_10k_metadata(ticker, max_filings=1)[0]

    def download_filing_html(self, file_url: str) -> bytes:
        file_resp = requests.get(file_url, headers=self.headers, timeout=self.request_timeout_seconds)
        file_resp.raise_for_status()
        return file_resp.content

if __name__ == "__main__":
    # Local Test: Ensure 'az login' is run and BLOB_ACCOUNT_URL is set in environment
    service = SECDownloaderService()
    service.fetch_and_upload_10k(["NEE", "DUK", "SO"])