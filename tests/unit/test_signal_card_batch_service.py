import json
import os
import sys
import types
import unittest
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.signal_card_batch import SECSignalCardBatchService


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


class _FakeStableFilesAPI:
    def __init__(self):
        self.created = False

    def create(self, file, purpose):
        self.created = True
        return SimpleNamespace(id="file-123")

    def content(self, file_id):
        payload = {
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
        return SimpleNamespace(text=json.dumps(payload))


class _FakeStableBatchesAPI:
    def create(self, input_file_id, endpoint, completion_window):
        return SimpleNamespace(
            id="batch-123",
            status="validating",
            created_at=1774225572,
        )

    def retrieve(self, batch_id):
        return SimpleNamespace(
            id=batch_id,
            status="in_progress",
            request_counts={"total": 1, "completed": 0, "failed": 0, "errored": 0},
            output_file_id=None,
            error_file_id=None,
            created_at=1774225572,
            expires_at=1774311972,
        )


class _FakeClientStable:
    def __init__(self):
        self.files = _FakeStableFilesAPI()
        self.batches = _FakeStableBatchesAPI()


class SignalCardBatchServiceTests(unittest.TestCase):
    def test_build_batch_request_item_shape(self):
        svc = SECSignalCardBatchService()
        item = svc.build_batch_request_item(
            custom_id="VRT-0001628280-22-004533",
            system_prompt="sys",
            user_prompt="usr",
            schema={"name": "SignalCard", "strict": True, "schema": {}},
        )

        self.assertEqual(item["custom_id"], "VRT-0001628280-22-004533")
        self.assertEqual(item["method"], "POST")
        self.assertEqual(item["url"], "/v1/chat/completions")
        self.assertIn("body", item)
        self.assertEqual(item["body"]["model"], svc.model)
        self.assertEqual(item["body"]["messages"][0]["role"], "system")
        self.assertEqual(item["body"]["messages"][1]["role"], "user")

    def test_submit_batch_success_with_stable_sdk(self):
        svc = SECSignalCardBatchService()
        svc._client = _FakeClientStable()

        batch_id = svc.submit_batch(
            [
                svc.build_batch_request_item(
                    custom_id="VRT-0001628280-22-004533",
                    system_prompt="sys",
                    user_prompt="usr",
                    schema={"name": "SignalCard", "strict": True, "schema": {}},
                )
            ]
        )

        self.assertEqual(batch_id, "batch-123")

    def test_submit_batch_returns_none_on_exception(self):
        svc = SECSignalCardBatchService()

        class _BrokenFiles:
            def create(self, file, purpose):
                raise RuntimeError("upload failed")

        class _BrokenClient:
            def __init__(self):
                self.files = _BrokenFiles()

        svc._client = _BrokenClient()
        batch_id = svc.submit_batch([
            {
                "custom_id": "x",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {"model": "gpt-4.1", "messages": []},
            }
        ])
        self.assertIsNone(batch_id)

    def test_get_batch_status_handles_dict_request_counts(self):
        svc = SECSignalCardBatchService()
        svc._client = _FakeClientStable()

        status = svc.get_batch_status("batch-xyz")

        self.assertIsNotNone(status)
        self.assertEqual(status["batch_id"], "batch-xyz")
        self.assertEqual(status["status"], "in_progress")
        self.assertEqual(status["request_counts"]["total"], 1)

    def test_parse_batch_result_success(self):
        svc = SECSignalCardBatchService()
        result = {
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

        custom_id, signal_card, err = svc.parse_batch_result(result)
        self.assertEqual(custom_id, "VRT-0001628280-22-004533")
        self.assertIsNone(err)
        self.assertIsNotNone(signal_card)
        self.assertEqual(signal_card.ticker, "VRT")

    def test_parse_batch_result_http_error(self):
        svc = SECSignalCardBatchService()
        result = {
            "custom_id": "VRT-0001628280-22-004533",
            "response": {
                "status_code": 429,
                "body": {"error": {"message": "rate limited"}},
            },
        }

        custom_id, signal_card, err = svc.parse_batch_result(result)
        self.assertEqual(custom_id, "VRT-0001628280-22-004533")
        self.assertIsNone(signal_card)
        self.assertIn("HTTP 429", err)


if __name__ == "__main__":
    unittest.main()
