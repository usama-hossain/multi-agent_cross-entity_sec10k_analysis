"""
Module: test_ingestion_kickoff_state_paths.py
Purpose: Characterize kickoff state/artifact branch behavior for idempotent ingestion.
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
    single_filing,
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
class TestKickoffStatePaths:
    """Tests for kickoff state/artifact branch behavior."""

    def test_kickoff__all_artifacts_exist__skips_processing(self, setup_pipeline):
        """Verify kickoff skips when all artifacts exist and not forced."""
        # Arrange
        ctx = setup_pipeline
        filing = single_filing("AEP", "ACC-ALL")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}
        FakeDownloader.existing_blobs = {
            "processed/md/AEP/ACC-ALL/10-K.md",
            "processed/md/AEP/ACC-ALL/item1a.md",
            "processed/md/AEP/ACC-ALL/item7.md",
            "processed/signals/AEP/ACC-ALL/signal_card.json",
        }

        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP"]), \
             patch.object(ctx.kickoff.os, "getenv", side_effect=default_getenv):
            response = ctx.kickoff.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert response.status_code == 200
        assert body["skipped"] == 1, (
            f"Should skip filing when all artifacts exist.\n"
            f"Expected skipped=1\n"
            f"Got: {body.get('skipped')}"
        )
        assert body["enqueued"] == 0
        assert FakeDownloader.download_calls == []
        assert FakeDownloader.upload_calls == []
        assert FakeQueueClient.sent_messages == []

    def test_kickoff__error_status__skips_accession(self, setup_pipeline):
        """Verify kickoff skips accession when status is error."""
        # Arrange
        ctx = setup_pipeline
        filing = single_filing("AEP", "ACC-ERR")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}
        FakeStateService.statuses = {"ACC-ERR": "error"}

        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP"]), \
             patch.object(ctx.kickoff.os, "getenv", side_effect=default_getenv):
            response = ctx.kickoff.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert response.status_code == 200
        assert body["skipped"] == 1
        assert body["not_downloaded"][0]["reason"] == "status_error", (
            f"Should indicate status_error as reason.\n"
            f"Got reason: {body['not_downloaded'][0].get('reason')}"
        )
        assert FakeDownloader.download_calls == []
        assert FakeQueueClient.sent_messages == []

    def test_kickoff__ready_status__enqueues_existing(self, setup_pipeline):
        """Verify kickoff enqueues existing filing when status is ready."""
        # Arrange
        ctx = setup_pipeline
        filing = single_filing("AEP", "ACC-READY")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}
        FakeStateService.statuses = {"ACC-READY": "ready"}

        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP"]), \
             patch.object(ctx.kickoff.os, "getenv", side_effect=default_getenv):
            response = ctx.kickoff.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert response.status_code == 200
        assert body["enqueued"] == 1
        assert len(FakeQueueClient.sent_messages) == 1
        queued = FakeQueueClient.sent_messages[0]
        assert queued["ticker"] == "AEP", (
            f"Queued message should have correct ticker.\n"
            f"Expected: AEP\n"
            f"Got: {queued.get('ticker')}"
        )
        assert queued["accession"] == "ACC-READY"
        assert queued["attempt"] == 1
        assert FakeDownloader.download_calls == []

    def test_kickoff__new_accession__downloads_uploads_and_upserts(self, setup_pipeline):
        """Verify kickoff downloads, uploads, and upserts for new accession."""
        # Arrange
        ctx = setup_pipeline
        filing = single_filing("AEP", "ACC-NEW")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}

        # Act
        with patch.object(ctx.shared, "SECDownloaderService", FakeDownloader), \
             patch.object(ctx.shared, "ProcessingStateService", FakeStateService), \
             patch.object(ctx.shared, "QueueClient", FakeQueueClient), \
             patch.object(ctx.shared, "_load_tickers", return_value=["AEP"]), \
             patch.object(ctx.kickoff.os, "getenv", side_effect=default_getenv):
            response = ctx.kickoff.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert response.status_code == 200
        assert body["enqueued"] == 1
        assert FakeDownloader.download_calls == ["https://example.com/ACC-NEW.htm"], (
            f"Should download filing.\n"
            f"Expected: ['https://example.com/ACC-NEW.htm']\n"
            f"Got: {FakeDownloader.download_calls}"
        )
        assert FakeDownloader.upload_calls == [
            ("raw/html/AEP/ACC-NEW/10-K.html", "text/html", len(b"<html>filing</html>"))
        ]
        assert len(FakeStateService.upserts) == 1
        assert FakeStateService.upserts[0]["accession"] == "ACC-NEW"
        assert FakeStateService.download_updates == [("ACC-NEW", "downloaded", None)]
        assert len(FakeQueueClient.sent_messages) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

