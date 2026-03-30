import json
import os
import sys
import pytest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import function_app


def _valid_signal_card_payload() -> dict:
    return {
        "ticker": "VRT",
        "fiscal_year": 2024,
        "filing_date": "2024-12-31",
        "capital_allocation": {
            "capex_direction": "stable",
            "capex_details": "CapEx remained stable year over year.",
            "capex_split": "Maintenance-heavy with selective growth.",
            "language_tone": "balanced",
        },
        "supply_chain_tightness": [
            {
                "signal": "Transformer lead times remained elevated",
                "severity": "moderate",
                "evidence": "Lead times for certain electrical equipment remained elevated.",
            }
        ],
        "demand_signals": {
            "customer_growth": "Customer additions were modest.",
            "backlog_direction": "stable",
            "load_changes": "Load growth was modest in commercial segments.",
            "evidence": "We experienced modest customer and load growth.",
        },
        "new_risk_factors": [
            {
                "risk": "Extreme weather volatility",
                "category": "operational",
                "evidence": "Increased frequency of severe weather events may affect operations.",
            }
        ],
        "escalated_risk_factors": [
            {
                "risk": "Cybersecurity",
                "category": "technology",
                "prior_language_summary": "General cyber risk discussion",
                "current_language_summary": "Expanded language on ransomware and OT systems",
                "evidence": "Recent ransomware events in the sector increase operational risk.",
            }
        ],
        "regulatory_exposure": {
            "pending_rate_cases": "Multiple pending rate proceedings",
            "emissions_mandates": "Evolving state emissions requirements",
            "compliance_investments": "Planned investment in compliance upgrades",
            "evidence": "Pending regulatory proceedings and emissions compliance investments are expected.",
        },
        "strategic_posture": {
            "direction": "stable",
            "summary": "Disciplined execution with selective growth",
            "evidence": "We remain focused on disciplined capital allocation and reliability.",
        },
        "generation_mix_shift": {
            "coal_retirements": "No major retirements announced",
            "renewable_additions": "Incremental renewable additions",
            "battery_storage": "Pilot battery projects underway",
            "dispatchable_adequacy": "Maintained through existing gas fleet",
            "evidence": "Portfolio changes include incremental renewable and storage additions.",
        },
        "fuel_and_input_exposure": {
            "price_sensitivity": "Moderate gas price sensitivity",
            "hedging_changes": "Hedging program largely unchanged",
            "ppa_terms": "Long-term PPAs remain in place",
            "evidence": "Commodity exposure is managed through hedging and contractual arrangements.",
        },
    }


class _FakeScheduleStatus:
    last = "2026-03-23T00:30:00Z"


class _FakeTimer:
    schedule_status = _FakeScheduleStatus()
    past_due = False


class _FakeStateService:
    def __init__(self):
        self.batch_updates = []
        self.signal_updates = []

    def list_pending_signal_card_batches(self):
        return [
            {
                "RowKey": "0001628280-22-004533",
                "SignalCardStatus": "batch_submitted",
                "SignalCardBatchId": "batch-1",
                "SignalCardCustomId": "VRT-0001628280-22-004533",
                "SourceBlob": "raw/html/VRT/0001628280-22-004533/10-K.html",
            }
        ]

    def update_signal_card_batch_status(self, accession, batch_status, error_message=None):
        self.batch_updates.append((accession, batch_status, error_message))

    def set_signal_card_status(self, accession, status, error_message=None):
        self.signal_updates.append((accession, status, error_message))


class _FakeStateServiceInProgress(_FakeStateService):
    pass


class _FakeDownloader:
    def __init__(self):
        self.uploads = []

    def upload_blob(self, blob_name, data, content_type=None):
        self.uploads.append((blob_name, content_type, len(data)))


class _FakeBatchServiceCompleted:
    is_enabled = True

    def get_batch_status(self, batch_id):
        return {
            "batch_id": batch_id,
            "status": "completed",
            "output_file_id": "out-file-1",
            "request_counts": {"total": 1, "completed": 1, "failed": 0, "errored": 0},
        }

    def fetch_batch_results(self, batch_id, output_file_id):
        return [
            {
                "custom_id": "VRT-0001628280-22-004533",
                "response": {
                    "status_code": 200,
                    "body": {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(_valid_signal_card_payload())
                                }
                            }
                        ]
                    },
                },
            }
        ]

    def parse_batch_result(self, result):
        from src.services.signal_card_schema import SignalCard

        payload = json.loads(result["response"]["body"]["choices"][0]["message"]["content"])
        return result["custom_id"], SignalCard.model_validate(payload), None


class _FakeBatchServiceInProgress:
    is_enabled = True

    def get_batch_status(self, batch_id):
        return {
            "batch_id": batch_id,
            "status": "in_progress",
            "output_file_id": None,
            "request_counts": {"total": 1, "completed": 0, "failed": 0, "errored": 0},
        }


@pytest.mark.unit
class TestBatchReconciler:
    """Tests for signal card batch reconciler orchestration logic."""
    
    def test_reconciler__completed_batch__materializes_results(self):
        """Reconciler: materializes completed batch results to blob storage."""
        fake_state = _FakeStateService()
        fake_downloader = _FakeDownloader()

        with patch.dict(os.environ, {"SIGNAL_CARD_EXECUTION_MODE": "batch"}), patch.object(
            function_app, "ProcessingStateService", return_value=fake_state
        ), patch.object(function_app, "SECDownloaderService", return_value=fake_downloader), patch.object(
            function_app, "SECSignalCardBatchService", return_value=_FakeBatchServiceCompleted()
        ):
            function_app.signal_card_batch_reconciler(_FakeTimer())

        # Assert
        assert len(fake_downloader.uploads) == 1, (
            f"Should upload exactly 1 signal card. Got {len(fake_downloader.uploads)} uploads."
        )
        assert fake_downloader.uploads[0][0] == "processed/signals/VRT/0001628280-22-004533/signal_card.json", (
            f"Should upload to correct path. Got: {fake_downloader.uploads[0][0]}"
        )
        assert ("0001628280-22-004533", "completed", None) in fake_state.batch_updates, (
            "Should mark batch as completed in state service."
        )
        assert ("0001628280-22-004533", "extracted", None) in fake_state.signal_updates, (
            "Should mark signal card as extracted in state service."
        )

    def test_reconciler__in_progress_batch__updates_status_without_upload(self):
        """Reconciler: marks in-progress batches without uploading results."""
        fake_state = _FakeStateServiceInProgress()
        fake_downloader = _FakeDownloader()

        with patch.dict(os.environ, {"SIGNAL_CARD_EXECUTION_MODE": "batch"}), patch.object(
            function_app, "ProcessingStateService", return_value=fake_state
        ), patch.object(function_app, "SECDownloaderService", return_value=fake_downloader), patch.object(
            function_app, "SECSignalCardBatchService", return_value=_FakeBatchServiceInProgress()
        ):
            function_app.signal_card_batch_reconciler(_FakeTimer())

        # Assert
        assert fake_downloader.uploads == [], (
            "Should not upload any files for in-progress batches."
        )
        assert ("0001628280-22-004533", "in_progress", None) in fake_state.batch_updates, (
            "Should mark batch as in_progress in state service."
        )
        assert ("0001628280-22-004533", "batch_submitted", None) in fake_state.signal_updates, (
            "Should mark signal card as batch_submitted in state service."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
