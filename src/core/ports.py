from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class PendingSignalCardBatch:
    accession: str
    signal_card_status: str
    batch_id: str
    custom_id: str
    source_blob: str = ""


class BlobStoragePort(Protocol):
    def blob_exists(self, blob_name: str) -> bool:
        ...

    def upload_blob(self, blob_name: str, data: bytes, content_type: Optional[str] = None) -> None:
        ...

    def download_blob(self, blob_name: str) -> bytes:
        ...


class SecFilingsPort(Protocol):
    def fetch_recent_10k_metadata(self, ticker: str, max_filings: int = 5) -> list[dict[str, Any]]:
        ...

    def download_filing_html(self, file_url: str) -> bytes:
        ...


class ProcessingStatePort(Protocol):
    def get_status(self, accession: str) -> Optional[str]:
        ...

    def upsert_filing(
        self,
        accession: str,
        cik: str,
        company_name: str,
        source_blob: str,
        status: str = "ready",
        error_message: Optional[str] = None,
    ) -> None:
        ...

    def update_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        ...

    def set_download_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        ...

    def set_markdown_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        ...

    def set_item1a_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        ...

    def set_item7_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        ...

    def set_signal_card_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        ...

    def set_signal_card_batch_info(
        self,
        accession: str,
        batch_id: str,
        custom_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        ...

    def update_signal_card_batch_status(
        self,
        accession: str,
        batch_status: str,
        error_message: Optional[str] = None,
    ) -> None:
        ...

    def list_pending_signal_card_batches(self) -> list[PendingSignalCardBatch]:
        ...


class QueueClientPort(Protocol):
    def send_message(self, msg: str) -> None:
        ...


class MarkdownConversionPort(Protocol):
    def convert_10k_markdown(self, ticker: str, accession: Optional[str] = None) -> str:
        ...


class SectionExtractionPort(Protocol):
    def extract_item_sections(self, ticker: str, accession: str) -> tuple[Optional[str], Optional[str]]:
        ...


class SignalCardExtractionPort(Protocol):
    @property
    def is_enabled(self) -> bool:
        ...

    def build_extraction_request(
        self,
        ticker: str,
        fiscal_year: Optional[int],
        filing_date: Optional[str],
        target_accession: Optional[str] = None,
        historical_filings: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        ...

    def extract_signal_card(
        self,
        ticker: str,
        fiscal_year: Optional[int],
        filing_date: Optional[str],
        target_accession: Optional[str] = None,
        historical_filings: Optional[list[dict[str, Any]]] = None,
    ) -> Any:
        ...

    def extract_ticker_signal_cards(
        self,
        ticker: str,
        historical_filings: list[dict[str, Any]],
    ) -> list[Any]:
        ...


class BatchServicePort(Protocol):
    @property
    def is_enabled(self) -> bool:
        ...

    def build_batch_request_item(
        self,
        custom_id: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    def submit_batch(self, batch_request_items: list[dict[str, Any]]) -> Optional[str]:
        ...

    def get_batch_status(self, batch_id: str) -> Optional[dict[str, Any]]:
        ...

    def fetch_batch_results(self, batch_id: str, output_file_id: str) -> Optional[list[dict[str, Any]]]:
        ...

    def parse_batch_result(self, result: dict[str, Any]) -> tuple[Optional[str], Optional[Any], Optional[str]]:
        ...
