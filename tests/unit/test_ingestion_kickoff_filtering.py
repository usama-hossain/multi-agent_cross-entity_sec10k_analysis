"""
Module: test_ingestion_kickoff_filtering.py
Purpose: Characterize kickoff validation and ticker-filter behavior.
Dependencies: mocked queue client, mocked downloader/state services
Markers: unit
"""

import json
import pytest
from unittest.mock import patch

from tests.unit._ingestion_test_helpers import (
    FakeDownloader,
    FakeQueueClient,
    FakeRequest,
    FakeStateService,
    default_getenv,
    import_function_app_with_service_stubs,
)


@pytest.fixture
def setup_pipeline():
    """Set up modular pipeline modules with mocked services."""
    ctx = import_function_app_with_service_stubs()
    FakeQueueClient.sent_messages = []
    FakeQueueClient.from_connection_calls = []
    FakeStateService.reset()
    FakeDownloader.reset()
    return ctx


@pytest.mark.unit
class TestKickoffFiltering:
    """Tests for kickoff validation and ticker-filter behavior."""

    def test_kickoff__missing_storage_config__returns_500(self, setup_pipeline):
        """Verify kickoff returns 500 error when storage connection not configured."""
        # Arrange
        ctx = setup_pipeline
        
        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP"]), \
             patch.object(
                 ctx.kickoff.os,
                 "getenv",
                 side_effect=lambda key, default=None: None if key == "AzureWebJobsStorage" else default,
             ):
            response = ctx.kickoff.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert response.status_code == 500, (
            f"Should return 500 for missing storage config.\n"
            f"Expected: 500\n"
            f"Got: {response.status_code}"
        )
        assert "not configured" in body["message"], (
            f"Error message should indicate storage not configured.\n"
            f"Got: {body['message']}"
        )
        assert FakeQueueClient.from_connection_calls == [], (
            f"Should not attempt to connect to queue.\n"
            f"Got calls: {FakeQueueClient.from_connection_calls}"
        )

    def test_kickoff__all_invalid_tickers__returns_400(self, setup_pipeline):
        """Verify kickoff returns 400 when all filtered tickers are invalid."""
        # Arrange
        ctx = setup_pipeline

        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP", "CEG"]), \
             patch.object(ctx.kickoff.os, "getenv", side_effect=default_getenv):
            response = ctx.kickoff.manual_kickoff(FakeRequest({"tickers": "XYZ,ABC"}))
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert response.status_code == 400, (
            f"Should return 400 for invalid tickers.\n"
            f"Expected: 400\n"
            f"Got: {response.status_code}"
        )
        assert body["requested_tickers"] == ["XYZ", "ABC"], (
            f"Should include requested tickers in response.\n"
            f"Expected: ['XYZ', 'ABC']\n"
            f"Got: {body['requested_tickers']}"
        )
        assert FakeDownloader.fetch_calls == [], (
            f"Should not fetch for invalid tickers.\n"
            f"Got calls: {FakeDownloader.fetch_calls}"
        )

    def test_kickoff__mixed_valid_invalid_tickers__filters_to_valid(self, setup_pipeline):
        """Verify kickoff filters to valid subset when mix of valid and invalid tickers provided."""
        # Arrange
        ctx = setup_pipeline
        FakeDownloader.filings_by_ticker = {"AEP": []}

        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP", "CEG"]), \
             patch.object(ctx.kickoff.os, "getenv", side_effect=default_getenv):
            response = ctx.kickoff.manual_kickoff(FakeRequest({"tickers": "AEP,ZZZ"}))

        # Assert
        assert response.status_code == 200, (
            f"Should return 200 for valid filtered tickers.\n"
            f"Expected: 200\n"
            f"Got: {response.status_code}"
        )
        assert FakeDownloader.fetch_calls == [("AEP", 5)], (
            f"Should fetch only valid ticker.\n"
            f"Expected: [('AEP', 5)]\n"
            f"Got: {FakeDownloader.fetch_calls}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

