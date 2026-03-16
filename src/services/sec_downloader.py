import os
import requests
import json
from typing import Optional
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.blob import ContentSettings

class SECDownloaderService:
    def __init__(self):
        # Professional Config: Load from Env, fail gracefully if missing
        self.company_name = os.getenv("SEC_COMPANY_NAME", "EnergyAI-Research")
        self.email = os.getenv("SEC_EMAIL", "scarredentos@gmail.com")
        self.user_agent = f"{self.company_name} {self.email}"
        
        # Headers required by SEC to prevent 403 Forbidden errors
        self.headers = {"User-Agent": self.user_agent}

        # Initialize Azure Clients
        account_url = os.getenv("BLOB_ACCOUNT_URL")
        connection_string = os.getenv("AzureWebJobsStorage")
        container_name = os.getenv("BLOB_CONTAINER_NAME", "sec-filings")
        
        if account_url:
            self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            self.container_client = self.blob_service_client.get_container_client(container_name)
            if not self.container_client.exists():
                self.container_client.create_container()
        elif connection_string and connection_string != "UseDevelopmentStorage=true":
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            self.container_client = self.blob_service_client.get_container_client(container_name)
            if not self.container_client.exists():
                self.container_client.create_container()
        else:
            print("WARNING: Blob connection not configured. Uploads will be skipped.")
            self.container_client = None

        # Load Ticker -> CIK map (Cached for performance)
        self.ticker_map = self._load_ticker_map()

    def blob_exists(self, blob_name: str) -> bool:
        if not self.container_client:
            return False
        return self.container_client.get_blob_client(blob_name).exists()

    def upload_blob(self, blob_name: str, data: bytes, content_type: Optional[str] = None):
        if not self.container_client:
            raise RuntimeError("Blob container client is not initialized.")
        self.container_client.upload_blob(
            name=blob_name,
            data=data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type) if content_type else None
        )

    def download_blob(self, blob_name: str) -> bytes:
        if not self.container_client:
            raise RuntimeError("Blob container client is not initialized.")
        blob_client = self.container_client.get_blob_client(blob_name)
        return blob_client.download_blob().readall()

    def _load_ticker_map(self):
        """Fetches the official SEC map of Ticker -> CIK."""
        print("Loading SEC Ticker Map...")
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            resp = requests.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            # Transform {0: {cik_str, ticker, title}, ...} -> {TICKER: CIK}
            return {item["ticker"]: item["cik_str"] for item in data.values()}
        except Exception as e:
            print(f"Failed to load ticker map: {e}")
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
            resp = requests.get(meta_url, headers=self.headers)
            
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
            file_resp = requests.get(file_url, headers=self.headers)
            
            if file_resp.status_code == 200:
                blob_name = f"{ticker}/{accession_num}/10-K.html"
                if self.container_client:
                    print(f"Uploading to Azure Blob: {blob_name}")
                    self.container_client.upload_blob(
                        name=blob_name,
                        data=file_resp.content, # Bytes in memory
                        overwrite=True
                    )
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
        resp = requests.get(meta_url, headers=self.headers)
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
        file_resp = requests.get(file_url, headers=self.headers)
        file_resp.raise_for_status()
        return file_resp.content

if __name__ == "__main__":
    # Local Test: Ensure 'az login' is run and BLOB_ACCOUNT_URL is set in environment
    service = SECDownloaderService()
    service.fetch_and_upload_10k(["NEE", "DUK", "SO"])