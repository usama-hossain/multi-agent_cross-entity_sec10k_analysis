"""Processing state bounded context.

This module is the source of truth for filing lifecycle persistence, status
validation, and idempotent state transitions. It intentionally avoids SEC
retrieval, conversion, and extraction orchestration concerns.
"""

import datetime
import logging
import os
from typing import Any, Dict, Optional

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableClient
from src.core.ports import PendingSignalCardBatch


ALLOWED_STATUSES = {"ready", "pdf_converted", "markdown_converted", "error"}
DOWNLOAD_STATUSES = {"not_started", "downloaded", "error"}
MARKDOWN_STATUSES = {"not_started", "ready", "pdf_converted", "markdown_converted", "error"}
SECTION_STATUSES = {"not_started", "extracted", "missing", "error"}
SIGNAL_CARD_STATUSES = {"not_started", "extracted", "skipped", "error", "queued_for_batch", "batch_submitted", "batch_completed", "batch_failed"}
BATCH_STATUSES = {"queued", "in_progress", "completed", "failed", "expired"}
TICKER_INSIGHT_STATUSES = {"not_started", "in_progress", "completed", "empty", "error"}


class ProcessingStateService:
    """State persistence service for accession-scoped processing lifecycle."""

    def __init__(self):
        connection_string = os.getenv("AzureWebJobsStorage") or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            raise RuntimeError("AzureWebJobsStorage (or AZURE_STORAGE_CONNECTION_STRING) is not configured.")

        self.table_name = os.getenv("SEC_STATE_TABLE_NAME", "SECProcessingState")
        self.partition_key = os.getenv("SEC_STATE_PARTITION_KEY", "Utility_10K_2026")
        self.table_client = TableClient.from_connection_string(connection_string, self.table_name)
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self.table_client.create_table()
        except ResourceExistsError:
            pass

    def get_entity(self, accession: str) -> Optional[Dict[str, Any]]:
        try:
            return self.table_client.get_entity(partition_key=self.partition_key, row_key=accession)
        except ResourceNotFoundError:
            return None

    def get_status(self, accession: str) -> Optional[str]:
        entity = self.get_entity(accession)
        if not entity:
            return None
        status = str(entity.get("Status", "")).strip().lower()
        return status if status else None

    def upsert_filing(
        self,
        accession: str,
        cik: str,
        company_name: str,
        source_blob: str,
        status: str = "ready",
        error_message: Optional[str] = None,
    ) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

        markdown_status = normalized_status if normalized_status in MARKDOWN_STATUSES else "not_started"

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "CIK": cik,
            "CompanyName": company_name,
            "SourceBlob": source_blob,
            "Status": normalized_status,
            "DownloadStatus": "downloaded",
            "MarkdownStatus": markdown_status,
            "Item1AStatus": "not_started",
            "Item7Status": "not_started",
            "SignalCardStatus": "not_started",
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["LastError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def update_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

        markdown_status = normalized_status if normalized_status in MARKDOWN_STATUSES else "not_started"

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "Status": normalized_status,
            "MarkdownStatus": markdown_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["LastError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def set_download_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in DOWNLOAD_STATUSES:
            raise ValueError(f"Unsupported download status: {status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "DownloadStatus": normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["DownloadError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def set_markdown_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in MARKDOWN_STATUSES:
            raise ValueError(f"Unsupported markdown status: {status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "MarkdownStatus": normalized_status,
            "Status": normalized_status if normalized_status in ALLOWED_STATUSES else "ready",
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["MarkdownError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def set_item1a_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        self._set_section_status(
            accession,
            "Item1AStatus",
            "Item1AError",
            status,
            error_message,
            allowed_statuses=SECTION_STATUSES,
        )

    def set_item7_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        self._set_section_status(
            accession,
            "Item7Status",
            "Item7Error",
            status,
            error_message,
            allowed_statuses=SECTION_STATUSES,
        )

    def set_signal_card_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        self._set_section_status(
            accession,
            "SignalCardStatus",
            "SignalCardError",
            status,
            error_message,
            allowed_statuses=SIGNAL_CARD_STATUSES,
        )

    def _set_section_status(
        self,
        accession: str,
        status_field: str,
        error_field: str,
        status: str,
        error_message: Optional[str] = None,
        allowed_statuses: set[str] = SECTION_STATUSES,
    ) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in allowed_statuses:
            raise ValueError(f"Unsupported section status: {status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            status_field: normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity[error_field] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def set_signal_card_batch_info(
        self,
        accession: str,
        batch_id: str,
        custom_id: str,
        status: str = "queued",
    ) -> None:
        """Store batch job information for a signal card extraction."""
        normalized_status = status.strip().lower()
        if normalized_status not in BATCH_STATUSES:
            raise ValueError(f"Unsupported batch status: {status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "SignalCardBatchId": batch_id,
            "SignalCardCustomId": custom_id,
            "SignalCardBatchStatus": normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        self.table_client.upsert_entity(entity)

    def set_ticker_insight_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        """Track ticker-level insight generation status on accession rows."""
        normalized_status = status.strip().lower()
        if normalized_status not in TICKER_INSIGHT_STATUSES:
            raise ValueError(f"Unsupported ticker insight status: {status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "TickerInsightStatus": normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["TickerInsightError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def set_ticker_insight_metadata(
        self,
        accession: str,
        insight_blob_path: str,
        generated_at_utc: str,
    ) -> None:
        """Store insight artifact metadata for traceability on accession rows."""
        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "TickerInsightBlob": insight_blob_path,
            "TickerInsightGeneratedUtc": generated_at_utc,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        self.table_client.upsert_entity(entity)

    def reset_ticker_insight_state(self, accession: str, clear_metadata: bool = True) -> None:
        """Reset only ticker-insight lifecycle fields for an accession."""
        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "TickerInsightStatus": "not_started",
            "TickerInsightError": "",
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if clear_metadata:
            entity["TickerInsightBlob"] = ""
            entity["TickerInsightGeneratedUtc"] = ""

        self.table_client.upsert_entity(entity)

    def update_signal_card_batch_status(
        self,
        accession: str,
        batch_status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Update batch status for a signal card extraction."""
        normalized_status = batch_status.strip().lower()
        if normalized_status not in BATCH_STATUSES:
            raise ValueError(f"Unsupported batch status: {batch_status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "SignalCardBatchStatus": normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["SignalCardBatchError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def list_pending_signal_card_batches(self) -> list[PendingSignalCardBatch]:
        """
        List entities requiring batch reconciliation.
        Includes filings queued for batch submission and submitted batches awaiting completion.
        """
        entities: list[PendingSignalCardBatch] = []
        filter_expr = f"PartitionKey eq '{self.partition_key}'"

        for entity in self.table_client.query_entities(query_filter=filter_expr):
            signal_card_status = str(entity.get("SignalCardStatus", "")).strip().lower()
            batch_status = str(entity.get("SignalCardBatchStatus", "")).strip().lower()
            batch_id = str(entity.get("SignalCardBatchId", "")).strip()

            if signal_card_status == "queued_for_batch":
                entities.append(
                    PendingSignalCardBatch(
                        accession=str(entity.get("RowKey", "")).strip(),
                        signal_card_status=signal_card_status,
                        batch_id=batch_id,
                        custom_id=str(entity.get("SignalCardCustomId", "")).strip(),
                        source_blob=str(entity.get("SourceBlob", "")).strip(),
                    )
                )
                continue

            if signal_card_status == "batch_submitted" and batch_id and batch_id != "pending":
                entities.append(
                    PendingSignalCardBatch(
                        accession=str(entity.get("RowKey", "")).strip(),
                        signal_card_status=signal_card_status,
                        batch_id=batch_id,
                        custom_id=str(entity.get("SignalCardCustomId", "")).strip(),
                        source_blob=str(entity.get("SourceBlob", "")).strip(),
                    )
                )
                continue

            if batch_status in {"queued", "in_progress"} and batch_id and batch_id != "pending":
                entities.append(
                    PendingSignalCardBatch(
                        accession=str(entity.get("RowKey", "")).strip(),
                        signal_card_status=signal_card_status,
                        batch_id=batch_id,
                        custom_id=str(entity.get("SignalCardCustomId", "")).strip(),
                        source_blob=str(entity.get("SourceBlob", "")).strip(),
                    )
                )

        logging.info(
            "Loaded pending signal card batch entities: count=%d partition_key=%s",
            len(entities),
            self.partition_key,
        )
        return entities

    # TODO: Future enhancement - add atomic claim/lease to prevent concurrent kickoff races.
