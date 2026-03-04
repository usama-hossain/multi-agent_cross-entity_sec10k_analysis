import datetime
import os
from typing import Any, Dict, Optional

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableClient


ALLOWED_STATUSES = {"ready", "pdf_converted", "markdown_converted", "error"}


class ProcessingStateService:
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

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "CIK": cik,
            "CompanyName": company_name,
            "SourceBlob": source_blob,
            "Status": normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["LastError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    def update_status(self, accession: str, status: str, error_message: Optional[str] = None) -> None:
        normalized_status = status.strip().lower()
        if normalized_status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported status: {status}")

        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": accession,
            "Status": normalized_status,
            "LastUpdatedUtc": datetime.datetime.utcnow().isoformat(),
        }

        if error_message:
            entity["LastError"] = error_message[:2000]

        self.table_client.upsert_entity(entity)

    # TODO: Future enhancement - add atomic claim/lease to prevent concurrent kickoff races.
