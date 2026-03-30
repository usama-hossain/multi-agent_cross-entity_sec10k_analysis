import importlib
import json
import os
import sys
import types
import pytest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _import_function_app_with_service_stubs():
    original_modules = {
        name: sys.modules.get(name)
        for name in [
            "azure.storage",
            "azure.storage.queue",
            "src.services.processing_state",
            "src.services.sec_downloader",
            "src.services.sec_edgar_markdown",
            "src.services.sec_edgar_sections",
            "src.services.signal_card_extractor",
            "src.services.signal_card_batch",
            "function_app",
        ]
    }

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

    imported = importlib.import_module("function_app")

    for name, original in original_modules.items():
        if name == "function_app":
            continue
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original

    return imported


class FakeRequest:
    def __init__(self, params=None):
        self.params = params or {}


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


@pytest.fixture
def setup_function_app():
    """Set up function app with fake services."""
    FakeQueueClient.sent = {"sec-convert-jobs": []}
    FakeStateService.upserts = []
    FakeDownloader.downloads = []
    FakeDownloader.uploads = []
    return _import_function_app_with_service_stubs()


@pytest.mark.unit
class TestKickoffDryRun:
    """Tests for kickoff routing by ledger state."""

    def test_kickoff__routes_by_state__without_real_services(self, setup_function_app):
        """Verify kickoff routes correctly by state without real services."""
        # Arrange
        function_app = setup_function_app

        # Act
        with patch.object(function_app, "SECDownloaderService", FakeDownloader), \
             patch.object(function_app, "ProcessingStateService", FakeStateService), \
             patch.object(function_app, "QueueClient", FakeQueueClient), \
             patch.object(function_app, "_load_tickers",
                        return_value=["AEP", "CEG", "DUK", "NEE", "SO"]), \
             patch.object(function_app.os, "getenv",
                        side_effect=lambda key, default=None: "fake-conn" if key == "AzureWebJobsStorage" else default):
            response = function_app.manual_kickoff(FakeRequest())
            body = json.loads(response.get_body().decode("utf-8"))

        # Assert
        assert body["enqueued"] == 4, (
            f"Should enqueue 4 filings (markdown_converted, pdf_converted, ready status).\n"
            f"Expected: 4\n"
            f"Got: {body['enqueued']}"
        )
        assert body["skipped"] == 1, (
            f"Should skip 1 filing (error status).\n"
            f"Expected: 1\n"
            f"Got: {body['skipped']}"
        )
        assert len(body["failed"]) == 0, (
            f"Should have no failures.\n"
            f"Got failures: {body['failed']}"
        )
        assert len(FakeDownloader.downloads) == 1, (
            f"Should download 1 new filing.\n"
            f"Expected: 1\n"
            f"Got: {len(FakeDownloader.downloads)}"
        )
        assert len(FakeStateService.upserts) == 1, (
            f"Should create 1 state upsert.\n"
            f"Expected: 1\n"
            f"Got: {len(FakeStateService.upserts)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

