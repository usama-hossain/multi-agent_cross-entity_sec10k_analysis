"""
Module: test_sec_downloader_characterization.py
Purpose: Characterize SEC metadata selection behavior used by ingestion orchestration.
Dependencies: mocked SEC HTTP response
Markers: unit
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.sec_downloader import SECDownloaderService


@pytest.fixture
def sec_downloader_service():
    """Fixture: instantiate SECDownloaderService with test configuration."""
    svc = SECDownloaderService.__new__(SECDownloaderService)
    svc.ticker_map = {"AEP": "4904"}
    svc.headers = {"User-Agent": "test-agent"}
    svc.request_timeout_seconds = 20
    return svc


@pytest.mark.unit
class TestSECDownloader:
    """Tests for SEC downloader metadata selection behavior."""
    
    def test_fetch_recent_10k_metadata__limits_to_five_and_only_10k_forms(self, sec_downloader_service):
        """Metadata selection: fetches only 10-K forms, limits to max_filings."""
        mock_payload = {
            "name": "AEP Corp",
            "filings": {
                "recent": {
                    "form": [
                        "10-Q",
                        "10-K",
                        "8-K",
                        "10-K",
                        "10-K",
                        "10-K",
                        "10-K",
                        "10-K",
                    ],
                    "accessionNumber": [
                        "Q-IGNORE",
                        "ACC-001",
                        "E-IGNORE",
                        "ACC-002",
                        "ACC-003",
                        "ACC-004",
                        "ACC-005",
                        "ACC-006",
                    ],
                    "primaryDocument": [
                        "q.htm",
                        "k1.htm",
                        "e.htm",
                        "k2.htm",
                        "k3.htm",
                        "k4.htm",
                        "k5.htm",
                        "k6.htm",
                    ],
                    "reportDate": [
                        "2025-09-30",
                        "2025-12-31",
                        "2025-11-30",
                        "2024-12-31",
                        "2023-12-31",
                        "2022-12-31",
                        "2021-12-31",
                        "2020-12-31",
                    ],
                    "filingDate": [
                        "2025-11-01",
                        "2026-02-20",
                        "2025-12-05",
                        "2025-02-20",
                        "2024-02-20",
                        "2023-02-20",
                        "2022-02-20",
                        "2021-02-20",
                    ],
                }
            },
        }

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = mock_payload

        with patch("src.services.sec_downloader.requests.get", return_value=mock_response) as mock_get:
            results = sec_downloader_service.fetch_recent_10k_metadata("AEP", max_filings=5)

        # Assert
        assert len(results) == 5, f"Should return exactly 5 filings, got {len(results)}."
        assert [row["form"] for row in results] == ["10-K", "10-K", "10-K", "10-K", "10-K"], (
            "Should filter to only 10-K forms."
        )
        assert [row["accession"] for row in results] == ["ACC-001", "ACC-002", "ACC-003", "ACC-004", "ACC-005"], (
            "Should return correct accession numbers in order."
        )
        assert [row["fiscal_year"] for row in results] == ["2025", "2024", "2023", "2022", "2021"], (
            "Should extract correct fiscal years."
        )
        
        called_url = mock_get.call_args.args[0]
        assert "CIK0000004904.json" in called_url, (
            f"Should call SEC API with correct CIK URL. Got: {called_url}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])