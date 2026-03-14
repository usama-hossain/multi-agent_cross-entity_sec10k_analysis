import os


class SECEdgarMarkdownService:
    def __init__(self):
        self.company_name = os.getenv("SEC_COMPANY_NAME", "EnergyAI-Research")
        self.email = os.getenv("SEC_EMAIL", "")

    def convert_latest_10k_markdown(self, ticker: str) -> str:
        """Returns markdown for the latest 10-K for a SEC ticker via edgartools."""
        from edgar import Company, set_identity

        if self.email:
            set_identity(f"{self.company_name} {self.email}")
        else:
            set_identity(self.company_name)

        company = Company(ticker)
        filings = company.get_filings(form="10-K")
        latest = filings.latest()
        doc = latest.document
        return doc.markdown()