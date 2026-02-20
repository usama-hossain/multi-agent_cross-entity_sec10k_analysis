import os
from sec_edgar_downloader import Downloader # type: ignore

class SECDownloaderService:
    def __init__(self, download_path: str = "data/raw"):
        # SEC requires: "Company Name AdminContact@domain.com"
        # In production, pull these from environment variables
        self.company_name = os.getenv("SEC_COMPANY_NAME", "EnergyAI-Research")
        self.email = os.getenv("SEC_EMAIL", "scarredentos@gmail.com")
        self.download_path = download_path
        
        # Initialize the downloader with a specific save location
        self.downloader = Downloader(self.company_name, self.email, self.download_path)

    def fetch_10k_filings(self, tickers: list, limit: int = 1):
        """
        Downloads the latest 10-K filings for a list of utility companies.
        """
        results = {}
        for ticker in tickers:
            print(f"Fetching latest 10-K for: {ticker}...")
            # 'limit=1' ensures we only get the most recent annual report
            count = self.downloader.get("10-K", ticker, limit=limit, download_details=True)
            results[ticker] = count
            print(f"Successfully downloaded {count} filing(s) for {ticker}")
        
        return results

# Logic First: Test locally by running 'python services/sec_downloader.py'
if __name__ == "__main__":
    # Your target utility companies
    energy_utilities = ["NEE", "DUK", "SO", "CEG", "AEP"]
    
    service = SECDownloaderService()
    summary = service.fetch_10k_filings(energy_utilities)
    print("\nDownload Summary:", summary)