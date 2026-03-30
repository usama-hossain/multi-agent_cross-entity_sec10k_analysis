"""
Module: test_processing_state_service.py
Purpose: Unit tests for ProcessingStateService covering status validation, transitions,
         idempotent upsert semantics, and pending-batch selection logic.
Dependencies: mocked TableClient, test fixtures
Markers: unit
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from typing import Any, Dict

from src.core.ports import PendingSignalCardBatch
from src.services.processing_state import (
    ProcessingStateService,
    ALLOWED_STATUSES,
    DOWNLOAD_STATUSES,
    MARKDOWN_STATUSES,
    SECTION_STATUSES,
    SIGNAL_CARD_STATUSES,
    BATCH_STATUSES,
)


@pytest.fixture
def processing_state_service():
    """Set up ProcessingStateService with mocked TableClient."""
    mock_table_client = MagicMock()
    partition_key = "TestPartition"
    
    with patch.dict(os.environ, {
        "AzureWebJobsStorage": "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test==",
        "SEC_STATE_TABLE_NAME": "TestTable",
        "SEC_STATE_PARTITION_KEY": partition_key,
    }):
        with patch("src.services.processing_state.TableClient") as mock_table_class:
            mock_table_class.from_connection_string.return_value = mock_table_client
            service = ProcessingStateService()
    
    mock_table_client.reset_mock()
    return service, mock_table_client, partition_key


@pytest.mark.unit
class TestProcessingStateServiceValidation:
    """Tests for status validation in ProcessingStateService."""

    def test_upsert__invalid_status__raises_error(self, processing_state_service):
        """Verify upsert_filing rejects invalid status values."""
        service, mock_client, _ = processing_state_service
        
        with pytest.raises(ValueError) as exc_info:
            service.upsert_filing(
                accession="0001234567-89-000001",
                cik="0000067000",
                company_name="Test Corp",
                source_blob="raw/html/TEST/0001234567-89-000001/10-K.html",
                status="invalid_status",
            )
        
        assert "Unsupported status" in str(exc_info.value)
        mock_client.upsert_entity.assert_not_called()

    def test_update_status__invalid_status__raises_error(self, processing_state_service):
        """Verify update_status rejects invalid status values."""
        service, mock_client, _ = processing_state_service
        
        with pytest.raises(ValueError) as exc_info:
            service.update_status("0001234567-89-000001", "invalid_status")
        
        assert "Unsupported status" in str(exc_info.value)
        mock_client.upsert_entity.assert_not_called()

    def test_set_download_status__invalid_status__raises_error(self, processing_state_service):
        """Verify set_download_status rejects invalid status values."""
        service, mock_client, _ = processing_state_service
        
        with pytest.raises(ValueError) as exc_info:
            service.set_download_status("0001234567-89-000001", "invalid_status")
        
        assert "Unsupported download status" in str(exc_info.value)
        mock_client.upsert_entity.assert_not_called()

    def test_set_markdown_status__invalid_status__raises_error(self, processing_state_service):
        """Verify set_markdown_status rejects invalid status values."""
        service, mock_client, _ = processing_state_service
        
        with pytest.raises(ValueError) as exc_info:
            service.set_markdown_status("0001234567-89-000001", "invalid_status")
        
        assert "Unsupported markdown status" in str(exc_info.value)
        mock_client.upsert_entity.assert_not_called()

    def test_set_item1a_status__invalid_status__raises_error(self, processing_state_service):
        """Verify set_item1a_status rejects invalid status values."""
        service, mock_client, _ = processing_state_service
        
        with pytest.raises(ValueError) as exc_info:
            service.set_item1a_status("0001234567-89-000001", "invalid_status")
        
        assert "Unsupported section status" in str(exc_info.value)
        mock_client.upsert_entity.assert_not_called()

    def test_set_batch_info__invalid_batch_status__raises_error(self, processing_state_service):
        """Verify set_signal_card_batch_info rejects invalid batch status."""
        service, mock_client, _ = processing_state_service
        
        with pytest.raises(ValueError) as exc_info:
            service.set_signal_card_batch_info(
                accession="0001234567-89-000001",
                batch_id="batch-123",
                custom_id="TEST-0001234567-89-000001",
                status="invalid_batch_status",
            )
        
        assert "Unsupported batch status" in str(exc_info.value)
        mock_client.upsert_entity.assert_not_called()


@pytest.mark.unit
class TestProcessingStateServiceIdempotency:
    """Tests for idempotent upsert semantics in ProcessingStateService."""

    def test_upsert_filing__called_twice__produces_same_result(self, processing_state_service):
        """Verify upsert_filing is idempotent."""
        service, mock_client, partition_key = processing_state_service
        accession = "0001234567-89-000001"
        cik = "0000067000"
        company_name = "Test Corp"
        source_blob = "raw/html/TEST/0001234567-89-000001/10-K.html"
        
        # Act: call twice
        service.upsert_filing(accession, cik, company_name, source_blob, status="ready")
        service.upsert_filing(accession, cik, company_name, source_blob, status="ready")
        
        # Assert
        assert mock_client.upsert_entity.call_count == 2
        call1_entity = mock_client.upsert_entity.call_args_list[0][0][0]
        call2_entity = mock_client.upsert_entity.call_args_list[1][0][0]
        
        assert call1_entity["PartitionKey"] == call2_entity["PartitionKey"], (
            f"PartitionKey should match on idempotent calls.\n"
            f"Call1: {call1_entity['PartitionKey']}\n"
            f"Call2: {call2_entity['PartitionKey']}"
        )
        assert call1_entity["RowKey"] == call2_entity["RowKey"]
        assert call1_entity["Status"] == call2_entity["Status"]

    def test_update_status__called_twice__produces_same_result(self, processing_state_service):
        """Verify update_status is idempotent."""
        service, mock_client, _ = processing_state_service
        accession = "0001234567-89-000001"
        
        # Act
        service.update_status(accession, "markdown_converted")
        service.update_status(accession, "markdown_converted")
        
        # Assert
        assert mock_client.upsert_entity.call_count == 2
        call1_entity = mock_client.upsert_entity.call_args_list[0][0][0]
        call2_entity = mock_client.upsert_entity.call_args_list[1][0][0]
        
        assert call1_entity["Status"] == call2_entity["Status"]
        assert call1_entity["MarkdownStatus"] == call2_entity["MarkdownStatus"]


@pytest.mark.unit
class TestProcessingStateServiceEntityShape:
    """Tests for entity field shapes in ProcessingStateService."""

    def test_upsert_filing__entity_shape__contains_required_fields(self, processing_state_service):
        """Verify upsert_filing entity contains required fields."""
        service, mock_client, partition_key = processing_state_service
        accession = "0001234567-89-000001"
        cik = "0000067000"
        company_name = "Test Corp"
        source_blob = "raw/html/TEST/0001234567-89-000001/10-K.html"
        
        # Act
        service.upsert_filing(accession, cik, company_name, source_blob, status="ready")
        
        # Assert
        entity = mock_client.upsert_entity.call_args[0][0]
        
        assert entity["PartitionKey"] == partition_key
        assert entity["RowKey"] == accession, (
            f"RowKey should be accession.\n"
            f"Expected: {accession}\n"
            f"Got: {entity.get('RowKey')}"
        )
        assert entity["CIK"] == cik
        assert entity["CompanyName"] == company_name
        assert entity["SourceBlob"] == source_blob
        assert entity["Status"] == "ready"
        assert entity["DownloadStatus"] == "downloaded"
        assert entity["MarkdownStatus"] == "ready"
        assert entity["Item1AStatus"] == "not_started"
        assert entity["Item7Status"] == "not_started"
        assert entity["SignalCardStatus"] == "not_started"
        assert "LastUpdatedUtc" in entity
        assert "LastError" not in entity

    def test_upsert_filing__with_error__truncates_message(self, processing_state_service):
        """Verify upsert_filing truncates error messages to 2000 chars."""
        service, mock_client, _ = processing_state_service
        long_error = "x" * 3000
        
        # Act
        service.upsert_filing(
            "0001234567-89-000001", "0000067000", "Test", "blob.html",
            error_message=long_error
        )
        
        # Assert
        entity = mock_client.upsert_entity.call_args[0][0]
        assert len(entity["LastError"]) == 2000, (
            f"Error message should be truncated to 2000 chars.\n"
            f"Expected length: 2000\n"
            f"Got length: {len(entity['LastError'])}"
        )
        assert entity["LastError"] == "x" * 2000


@pytest.mark.unit
class TestProcessingStateServiceTransitions:
    """Tests for status transitions in ProcessingStateService."""

    def test_all_allowed_statuses__accepted_by_upsert(self, processing_state_service):
        """Verify all ALLOWED_STATUSES are accepted by upsert_filing."""
        service, mock_client, _ = processing_state_service
        accession = "0001234567-89-000001"
        
        # Act: try each allowed status
        for status in ALLOWED_STATUSES:
            service.upsert_filing(accession, "cik", "name", "blob", status=status)
        
        # Assert
        assert mock_client.upsert_entity.call_count == len(ALLOWED_STATUSES), (
            f"Should accept all {len(ALLOWED_STATUSES)} allowed statuses.\n"
            f"Got: {mock_client.upsert_entity.call_count} calls"
        )

    def test_all_download_statuses__accepted_by_set(self, processing_state_service):
        """Verify all DOWNLOAD_STATUSES are accepted by set_download_status."""
        service, mock_client, _ = processing_state_service
        accession = "0001234567-89-000001"
        
        # Act
        for status in DOWNLOAD_STATUSES:
            service.set_download_status(accession, status)
        
        # Assert
        assert mock_client.upsert_entity.call_count == len(DOWNLOAD_STATUSES), (
            f"Should accept all {len(DOWNLOAD_STATUSES)} download statuses."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
