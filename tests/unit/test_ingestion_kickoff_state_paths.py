"""
Module: test_ingestion_kickoff_state_paths.py
Purpose: Characterize kickoff state/artifact branch behavior for idempotent ingestion.
Dependencies: mocked queue client, mocked downloader/state services
Markers: unit
"""

import json
import unittest
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


class KickoffStatePathCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.function_app = import_function_app_with_service_stubs()
        FakeQueueClient.sent_messages = []
        FakeQueueClient.from_connection_calls = []
        FakeStateService.reset()
        FakeDownloader.reset()

    def test_manual_kickoff_skips_when_all_artifacts_exist_and_not_forced(self):
        filing = single_filing("AEP", "ACC-ALL")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}

        FakeDownloader.existing_blobs = {
            "processed/md/AEP/ACC-ALL/10-K.md",
            "processed/md/AEP/ACC-ALL/item1a.md",
            "processed/md/AEP/ACC-ALL/item7.md",
            "processed/signals/AEP/ACC-ALL/signal_card.json",
        }

        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP"]
        ), patch.object(self.function_app.os, "getenv", side_effect=default_getenv):
            response = self.function_app.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["skipped"], 1)
        self.assertEqual(body["enqueued"], 0)
        self.assertEqual(FakeDownloader.download_calls, [])
        self.assertEqual(FakeDownloader.upload_calls, [])
        self.assertEqual(FakeQueueClient.sent_messages, [])

    def test_manual_kickoff_skips_status_error_accession(self):
        filing = single_filing("AEP", "ACC-ERR")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}
        FakeStateService.statuses = {"ACC-ERR": "error"}

        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP"]
        ), patch.object(self.function_app.os, "getenv", side_effect=default_getenv):
            response = self.function_app.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["skipped"], 1)
        self.assertEqual(body["not_downloaded"][0]["reason"], "status_error")
        self.assertEqual(FakeDownloader.download_calls, [])
        self.assertEqual(FakeQueueClient.sent_messages, [])

    def test_manual_kickoff_enqueues_existing_when_ready_state_present(self):
        filing = single_filing("AEP", "ACC-READY")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}
        FakeStateService.statuses = {"ACC-READY": "ready"}

        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP"]
        ), patch.object(self.function_app.os, "getenv", side_effect=default_getenv):
            response = self.function_app.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["enqueued"], 1)
        self.assertEqual(len(FakeQueueClient.sent_messages), 1)
        queued = FakeQueueClient.sent_messages[0]
        self.assertEqual(queued["ticker"], "AEP")
        self.assertEqual(queued["accession"], "ACC-READY")
        self.assertEqual(queued["attempt"], 1)
        self.assertEqual(FakeDownloader.download_calls, [])

    def test_manual_kickoff_downloads_uploads_and_upserts_for_new_accession(self):
        filing = single_filing("AEP", "ACC-NEW")
        FakeDownloader.filings_by_ticker = {"AEP": [filing]}

        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP"]
        ), patch.object(self.function_app.os, "getenv", side_effect=default_getenv):
            response = self.function_app.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["enqueued"], 1)
        self.assertEqual(FakeDownloader.download_calls, ["https://example.com/ACC-NEW.htm"])
        self.assertEqual(
            FakeDownloader.upload_calls,
            [("raw/html/AEP/ACC-NEW/10-K.html", "text/html", len(b"<html>filing</html>"))],
        )
        self.assertEqual(len(FakeStateService.upserts), 1)
        self.assertEqual(FakeStateService.upserts[0]["accession"], "ACC-NEW")
        self.assertEqual(FakeStateService.download_updates, [("ACC-NEW", "downloaded", None)])
        self.assertEqual(len(FakeQueueClient.sent_messages), 1)


if __name__ == "__main__":
    unittest.main()
