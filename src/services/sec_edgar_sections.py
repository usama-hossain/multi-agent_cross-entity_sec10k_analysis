# pyright: reportMissingImports=false

import os
from typing import Optional


class SECEdgarSectionsService:
    def __init__(self):
        self.company_name = os.getenv("SEC_COMPANY_NAME", "EnergyAI-Research")
        self.email = os.getenv("SEC_EMAIL", "")

    def _get_target_filing(self, ticker: str, accession: str):
        from edgar import Company, set_identity

        if self.email:
            set_identity(f"{self.company_name} {self.email}")
        else:
            set_identity(self.company_name)

        company = Company(ticker)
        filings = company.get_filings(form="10-K")

        normalized = accession.replace("-", "")
        for filing in filings:
            accession_candidates = [
                getattr(filing, "accession_number", None),
                getattr(filing, "accession_no", None),
                getattr(filing, "accessionNumber", None),
            ]
            for candidate in accession_candidates:
                if not candidate:
                    continue
                if str(candidate).replace("-", "") == normalized:
                    return filing

        raise ValueError(f"10-K accession not found for ticker={ticker}: {accession}")

    def _normalize_section(self, content: Optional[str]) -> Optional[str]:
        if content is None:
            return None
        text = str(content).strip()
        return text if text else None

    def extract_item_sections(self, ticker: str, accession: str) -> tuple[Optional[str], Optional[str]]:
        filing = self._get_target_filing(ticker, accession)

        # Prefer TenK object extraction; fallback to filing attributes if needed.
        tenk_obj = None
        try:
            from edgar import TenK

            tenk_obj = TenK(filing)
        except Exception:
            tenk_obj = None

        if tenk_obj is None:
            try:
                obj_candidate = getattr(filing, "obj", None)
                if callable(obj_candidate):
                    tenk_obj = obj_candidate()
                else:
                    tenk_obj = obj_candidate
            except Exception:
                tenk_obj = None

        source = tenk_obj if tenk_obj is not None else filing

        # edgartools TenK exposes these as properties; avoid Item-number lookups.
        item1a = self._normalize_section(getattr(source, "risk_factors", None))
        item7 = self._normalize_section(getattr(source, "management_discussion", None))

        # Fallback to section-key indexing when property access returns empty.
        if item1a is None or item7 is None:
            document = getattr(source, "document", None)
            sections = getattr(document, "sections", None) if document is not None else None

            if sections is not None:
                if item1a is None:
                    section = sections.get("risk_factors") if hasattr(sections, "get") else None
                    if section is not None and hasattr(section, "text"):
                        item1a = self._normalize_section(section.text())

                if item7 is None:
                    section = sections.get("mda") if hasattr(sections, "get") else None
                    if section is not None and hasattr(section, "text"):
                        item7 = self._normalize_section(section.text())

        return item1a, item7
