import os


class SECEdgarMarkdownService:
    def __init__(self):
        self.company_name = os.getenv("SEC_COMPANY_NAME", "EnergyAI-Research")
        self.email = os.getenv("SEC_EMAIL", "")

    def convert_10k_markdown(self, ticker: str, accession: str | None = None) -> str:
        """Returns markdown for a 10-K for a SEC ticker via edgartools.

        If accession is provided, the filing is selected by accession number.
        Otherwise, the latest 10-K is used.
        """
        from edgar import Company, set_identity

        if self.email:
            set_identity(f"{self.company_name} {self.email}")
        else:
            set_identity(self.company_name)

        company = Company(ticker)
        filings = company.get_filings(form="10-K")

        target_filing = None
        if accession:
            normalized = accession.replace("-", "")
            for filing in filings:
                accession_candidates = [
                    getattr(filing, "accession_number", None),
                    getattr(filing, "accession_no", None),
                    getattr(filing, "accessionNumber", None),
                ]
                matched = False
                for candidate in accession_candidates:
                    if not candidate:
                        continue
                    if str(candidate).replace("-", "") == normalized:
                        target_filing = filing
                        matched = True
                        break
                if matched:
                    break

            if not target_filing:
                raise ValueError(f"10-K accession not found for ticker={ticker}: {accession}")
        else:
            target_filing = filings.latest()

        doc = target_filing.document
        return doc.markdown()

    def convert_latest_10k_markdown(self, ticker: str) -> str:
        """Backward-compatible wrapper for latest filing conversion."""
        return self.convert_10k_markdown(ticker, accession=None)