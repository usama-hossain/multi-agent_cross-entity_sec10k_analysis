import os
import requests
import json
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

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
        container_name = os.getenv("BLOB_CONTAINER_NAME", "raw-10k-filings")
        
        if account_url:
            self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            self.container_client = self.blob_service_client.get_container_client(container_name)
            if not self.container_client.exists():
                self.container_client.create_container()
        else:
            print("WARNING: BLOB_ACCOUNT_URL not set. Uploads will be skipped.")
            self.container_client = None

        # Load Ticker -> CIK map (Cached for performance)
        self.ticker_map = self._load_ticker_map()

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

if __name__ == "__main__":
    # Local Test: Ensure 'az login' is run and BLOB_ACCOUNT_URL is set in environment
    service = SECDownloaderService()
    service.fetch_and_upload_10k(["NEE", "DUK", "SO"])