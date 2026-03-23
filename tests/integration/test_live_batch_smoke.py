import json
import os
import sys
import time
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.signal_card_batch import SECSignalCardBatchService
from src.services.signal_card_extractor import SECSignalCardService


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


RUN_LIVE_BATCH_TESTS = _bool_env("RUN_LIVE_BATCH_TESTS", default=False)
RUN_LIVE_BATCH_COMPLETE = _bool_env("RUN_LIVE_BATCH_COMPLETE", default=False)


@unittest.skipUnless(RUN_LIVE_BATCH_TESTS, "Set RUN_LIVE_BATCH_TESTS=true to run live OpenAI batch smoke tests")
class LiveBatchSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.required = ["OPENAI_API_KEY"]
        missing = [name for name in cls.required if not os.getenv(name)]
        if missing:
            raise unittest.SkipTest(f"Missing required env vars for live tests: {', '.join(missing)}")

        cls.batch_service = SECSignalCardBatchService()
        if not cls.batch_service.is_enabled:
            raise unittest.SkipTest("Batch service is not enabled with current environment")

        cls.extractor = SECSignalCardService()

    def _build_request_item(self, custom_id: str) -> dict:
        request = self.extractor.build_extraction_request(
            ticker="VRT",
            fiscal_year=2024,
            filing_date="2024-12-31",
            target_accession="0001628280-22-004533",
            historical_filings=[
                {
                    "accession": "0001628280-22-004533",
                    "fiscal_year": 2024,
                    "filing_date": "2024-12-31",
                    "item1a_text": "Risk factors include supply chain disruption and cybersecurity incidents.",
                    "item7_text": "Management discussion indicates stable capex and moderate demand growth.",
                }
            ],
        )

        return self.batch_service.build_batch_request_item(
            custom_id=custom_id,
            system_prompt=request["system_prompt"],
            user_prompt=request["user_prompt"],
            schema=request["schema"],
        )

    def test_live_batch_submit_and_status(self):
        custom_id = f"live-smoke-{int(time.time())}"
        item = self._build_request_item(custom_id)

        batch_id = self.batch_service.submit_batch([item])
        self.assertIsNotNone(batch_id)

        status = self.batch_service.get_batch_status(batch_id)
        self.assertIsNotNone(status)
        self.assertEqual(status.get("batch_id"), batch_id)
        self.assertTrue(status.get("status"))

    @unittest.skipUnless(RUN_LIVE_BATCH_COMPLETE, "Set RUN_LIVE_BATCH_COMPLETE=true to run completion smoke test")
    def test_live_batch_end_to_end_completion(self):
        custom_id = f"live-e2e-{int(time.time())}"
        item = self._build_request_item(custom_id)

        batch_id = self.batch_service.submit_batch([item])
        self.assertIsNotNone(batch_id)

        timeout_seconds = int(os.getenv("LIVE_BATCH_TIMEOUT_SECONDS", "900"))
        poll_seconds = int(os.getenv("LIVE_BATCH_POLL_SECONDS", "10"))
        deadline = time.time() + timeout_seconds

        completed_status = None
        while time.time() < deadline:
            status = self.batch_service.get_batch_status(batch_id)
            self.assertIsNotNone(status)
            batch_status = (status.get("status") or "").strip().lower()
            if batch_status == "completed":
                completed_status = status
                break
            if batch_status in {"failed", "expired", "cancelled"}:
                self.fail(f"Live batch ended in terminal failure status={batch_status} batch_id={batch_id}")
            time.sleep(max(1, poll_seconds))

        if completed_status is None:
            self.skipTest(f"Batch did not complete within {timeout_seconds}s; batch_id={batch_id}")

        output_file_id = (completed_status.get("output_file_id") or "").strip()
        self.assertTrue(output_file_id, "Completed batch missing output_file_id")

        results = self.batch_service.fetch_batch_results(batch_id, output_file_id)
        self.assertIsNotNone(results)
        matched = [r for r in results if r.get("custom_id") == custom_id]
        self.assertTrue(matched, f"No matching result for custom_id={custom_id}")

        _, signal_card, err = self.batch_service.parse_batch_result(matched[0])
        self.assertIsNone(err)
        self.assertIsNotNone(signal_card)
        self.assertEqual(signal_card.ticker, "VRT")


if __name__ == "__main__":
    unittest.main()
