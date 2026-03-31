import os
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings


class AzureBlobArtifactStore:
    """Azure Blob adapter for filing artifact storage."""

    def __init__(self):
        account_url = os.getenv("BLOB_ACCOUNT_URL")
        connection_string = os.getenv("AzureWebJobsStorage")
        container_name = os.getenv("BLOB_CONTAINER_NAME", "sec-filings")

        if account_url:
            self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            self.container_client = self.blob_service_client.get_container_client(container_name)
            if not self.container_client.exists():
                self.container_client.create_container()
        elif connection_string and connection_string != "UseDevelopmentStorage=true":
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            self.container_client = self.blob_service_client.get_container_client(container_name)
            if not self.container_client.exists():
                self.container_client.create_container()
        else:
            print("WARNING: Blob connection not configured. Uploads will be skipped.")
            self.container_client = None

    def blob_exists(self, blob_name: str) -> bool:
        if not self.container_client:
            return False
        return self.container_client.get_blob_client(blob_name).exists()

    def upload_blob(self, blob_name: str, data: bytes, content_type: Optional[str] = None) -> None:
        if not self.container_client:
            raise RuntimeError("Blob container client is not initialized.")
        self.container_client.upload_blob(
            name=blob_name,
            data=data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type) if content_type else None,
        )

    def download_blob(self, blob_name: str) -> bytes:
        if not self.container_client:
            raise RuntimeError("Blob container client is not initialized.")
        blob_client = self.container_client.get_blob_client(blob_name)
        return blob_client.download_blob().readall()
