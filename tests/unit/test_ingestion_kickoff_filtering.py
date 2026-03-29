"""
Module: test_ingestion_kickoff_filtering.py
Purpose: Characterize kickoff validation and ticker-filter behavior.
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
)


class KickoffFilteringCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.function_app = import_function_app_with_service_stubs()
        FakeQueueClient.sent_messages = []
        FakeQueueClient.from_connection_calls = []
        FakeStateService.reset()
        FakeDownloader.reset()

    def test_manual_kickoff_returns_500_without_storage_connection(self):
        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP"]
        ), patch.object(
            self.function_app.os,
            "getenv",
            side_effect=lambda key, default=None: None if key == "AzureWebJobsStorage" else default,
        ):
            response = self.function_app.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(response.status_code, 500)
        self.assertIn("not configured", body["message"])
        self.assertEqual(FakeQueueClient.from_connection_calls, [])

    def test_manual_kickoff_rejects_all_invalid_ticker_filter(self):
        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP", "CEG"]
        ), patch.object(self.function_app.os, "getenv", side_effect=default_getenv):
            response = self.function_app.manual_kickoff(FakeRequest({"tickers": "XYZ,ABC"}))
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["requested_tickers"], ["XYZ", "ABC"])
        self.assertEqual(FakeDownloader.fetch_calls, [])

    def test_manual_kickoff_filters_to_valid_subset(self):
        FakeDownloader.filings_by_ticker = {"AEP": []}

        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app, "_load_tickers", return_value=["AEP", "CEG"]
        ), patch.object(self.function_app.os, "getenv", side_effect=default_getenv):
            response = self.function_app.manual_kickoff(FakeRequest({"tickers": "AEP,ZZZ"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(FakeDownloader.fetch_calls, [("AEP", 5)])


if __name__ == "__main__":
    unittest.main()
