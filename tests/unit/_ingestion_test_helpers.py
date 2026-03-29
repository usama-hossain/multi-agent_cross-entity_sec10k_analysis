import importlib
import json
import os
import sys
import types


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def import_function_app_with_service_stubs():
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

    class DummySECEdgarSectionsService:
        pass

    class DummySECSignalCardService:
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
    sent_messages = []
    from_connection_calls = []

    def __init__(self, queue_name):
        self.queue_name = queue_name

    @classmethod
    def from_connection_string(cls, connection_string, queue_name):
        cls.from_connection_calls.append((connection_string, queue_name))
        return cls(queue_name)

    def create_queue(self):
        return None

    def send_message(self, payload):
        self.sent_messages.append(json.loads(payload))


class FakeStateService:
    statuses = {}
    upserts = []
    download_updates = []
    markdown_updates = []
    item1a_updates = []
    item7_updates = []
    signal_card_updates = []

    @classmethod
    def reset(cls):
        cls.statuses = {}
        cls.upserts = []
        cls.download_updates = []
        cls.markdown_updates = []
        cls.item1a_updates = []
        cls.item7_updates = []
        cls.signal_card_updates = []

    def get_status(self, accession):
        return self.statuses.get(accession)

    def upsert_filing(self, **kwargs):
        self.upserts.append(kwargs)

    def set_download_status(self, accession, status, error_message=None):
        self.download_updates.append((accession, status, error_message))

    def set_markdown_status(self, accession, status, error_message=None):
        self.markdown_updates.append((accession, status, error_message))

    def set_item1a_status(self, accession, status, error_message=None):
        self.item1a_updates.append((accession, status, error_message))

    def set_item7_status(self, accession, status, error_message=None):
        self.item7_updates.append((accession, status, error_message))

    def set_signal_card_status(self, accession, status, error_message=None):
        self.signal_card_updates.append((accession, status, error_message))


class FakeDownloader:
    filings_by_ticker = {}
    existing_blobs = set()
    fetch_calls = []
    download_calls = []
    upload_calls = []

    @classmethod
    def reset(cls):
        cls.filings_by_ticker = {}
        cls.existing_blobs = set()
        cls.fetch_calls = []
        cls.download_calls = []
        cls.upload_calls = []

    def fetch_recent_10k_metadata(self, ticker, max_filings=5):
        self.fetch_calls.append((ticker, max_filings))
        return list(self.filings_by_ticker.get(ticker, []))

    def blob_exists(self, blob_name):
        return blob_name in self.existing_blobs

    def download_filing_html(self, file_url):
        self.download_calls.append(file_url)
        return b"<html>filing</html>"

    def upload_blob(self, blob_name, data, content_type=None):
        self.upload_calls.append((blob_name, content_type, len(data)))


def default_getenv(key, default=None):
    if key == "AzureWebJobsStorage":
        return "fake-conn"
    return default


def single_filing(ticker="AEP", accession="ACC-001"):
    return {
        "ticker": ticker,
        "cik": "0000000001",
        "company_name": f"{ticker} Corp",
        "accession": accession,
        "primary_document": "doc.htm",
        "file_url": f"https://example.com/{accession}.htm",
        "fiscal_year": "2025",
        "filing_date": "2026-02-15",
    }
