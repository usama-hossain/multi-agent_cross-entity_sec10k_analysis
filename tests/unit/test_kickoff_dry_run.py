import importlib
import json
import os
import sys
import types
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _import_function_app_with_service_stubs():
    azure_storage_mod = types.ModuleType("azure.storage")
    azure_queue_mod = types.ModuleType("azure.storage.queue")

    class DummyQueueClient:
        @classmethod
        def from_connection_string(cls, _connection_string, _queue_name):
            return cls()

        def create_queue(self):
            return None

        def send_message(self, _msg):
            return None

    azure_queue_mod.QueueClient = DummyQueueClient
    sys.modules["azure.storage"] = azure_storage_mod
    sys.modules["azure.storage.queue"] = azure_queue_mod

    state_mod = types.ModuleType("src.services.processing_state")
    downloader_mod = types.ModuleType("src.services.sec_downloader")

    class DummyProcessingStateService:
        pass

    class DummySECDownloaderService:
        pass

    state_mod.ProcessingStateService = DummyProcessingStateService
    downloader_mod.SECDownloaderService = DummySECDownloaderService
    sys.modules["src.services.processing_state"] = state_mod
    sys.modules["src.services.sec_downloader"] = downloader_mod

    sec_md_mod = types.ModuleType("src.services.sec_edgar_markdown")
    sec_sections_mod = types.ModuleType("src.services.sec_edgar_sections")
    signal_mod = types.ModuleType("src.services.signal_card_extractor")
    signal_batch_mod = types.ModuleType("src.services.signal_card_batch")

    class DummySECEdgarMarkdownService:
        pass

    class DummySECSignalCardService:
        pass

    class DummySECEdgarSectionsService:
        pass

    class DummySECSignalCardBatchService:
        pass

    sec_md_mod.SECEdgarMarkdownService = DummySECEdgarMarkdownService
    sec_sections_mod.SECEdgarSectionsService = DummySECEdgarSectionsService
    signal_mod.SECSignalCardService = DummySECSignalCardService
    signal_batch_mod.SECSignalCardBatchService = DummySECSignalCardBatchService
    sys.modules["src.services.sec_edgar_markdown"] = sec_md_mod
    sys.modules["src.services.sec_edgar_sections"] = sec_sections_mod
    sys.modules["src.services.signal_card_extractor"] = signal_mod
    sys.modules["src.services.signal_card_batch"] = signal_batch_mod

    if "function_app" in sys.modules:
        del sys.modules["function_app"]

    return importlib.import_module("function_app")


class FakeQueueClient:
    sent = {"sec-convert-jobs": []}

    def __init__(self, queue_name):
        self.queue_name = queue_name

    def create_queue(self):
        return None

    def send_message(self, msg):
        FakeQueueClient.sent[self.queue_name].append(json.loads(msg))

    @classmethod
    def from_connection_string(cls, _connection_string, queue_name):
        return cls(queue_name)


class FakeStateService:
    statuses = {
        "ACC-MD": "markdown_converted",
        "ACC-PDF": "pdf_converted",
        "ACC-READY": "ready",
        "ACC-ERR": "error",
        "ACC-MISS": None,
    }
    upserts = []

    def get_status(self, accession):
        return self.statuses.get(accession)

    def upsert_filing(self, **kwargs):
        self.upserts.append(kwargs)

    def set_download_status(self, accession, status, error_message=None):
        return None


class FakeDownloader:
    downloads = []
    uploads = []

    def fetch_recent_10k_metadata(self, ticker, max_filings=5):
        accession_map = {
            "AEP": "ACC-MD",
            "CEG": "ACC-PDF",
            "DUK": "ACC-READY",
            "NEE": "ACC-ERR",
            "SO": "ACC-MISS",
        }
        acc = accession_map[ticker]
        return [
            {
                "ticker": ticker,
                "cik": "0000000001",
                "company_name": f"{ticker} Corp",
                "accession": acc,
                "primary_document": "doc.htm",
                "file_url": f"https://example.com/{acc}.htm",
            }
        ]

    def download_filing_html(self, file_url):
        self.downloads.append(file_url)
        return b"<html></html>"

    def blob_exists(self, _blob_name):
        return False

    def upload_blob(self, blob_name, data, content_type=None):
        self.uploads.append((blob_name, content_type, len(data)))


class KickoffDryRunTests(unittest.TestCase):
    def setUp(self):
        FakeQueueClient.sent = {"sec-convert-jobs": []}
        FakeStateService.upserts = []
        FakeDownloader.downloads = []
        FakeDownloader.uploads = []
        self.function_app = _import_function_app_with_service_stubs()

    def test_manual_kickoff_routes_by_ledger_state_without_real_services(self):
        with patch.object(self.function_app, "SECDownloaderService", FakeDownloader), patch.object(
            self.function_app, "ProcessingStateService", FakeStateService
        ), patch.object(self.function_app, "QueueClient", FakeQueueClient), patch.object(
            self.function_app,
            "_load_tickers",
            return_value=["AEP", "CEG", "DUK", "NEE", "SO"],
        ), patch.object(
            self.function_app.os,
            "getenv",
            side_effect=lambda key, default=None: "fake-conn" if key == "AzureWebJobsStorage" else default,
        ):
            response = self.function_app.manual_kickoff(None)
            body = json.loads(response.get_body().decode("utf-8"))

        self.assertEqual(body["enqueued"], 4)
        self.assertEqual(body["skipped"], 1)
        self.assertEqual(len(body["failed"]), 0)

        self.assertEqual(len(FakeDownloader.downloads), 1)
        self.assertEqual(len(FakeStateService.upserts), 1)


if __name__ == "__main__":
    unittest.main()
