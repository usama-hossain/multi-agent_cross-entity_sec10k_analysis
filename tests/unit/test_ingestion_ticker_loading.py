"""
Module: test_ingestion_ticker_loading.py
Purpose: Characterize ticker-loading behavior for ingestion kickoff.
Dependencies: temporary JSON fixtures, function_app import stubs
Markers: unit
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.unit._ingestion_test_helpers import import_function_app_with_service_stubs


class TickerLoadingCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.function_app = import_function_app_with_service_stubs()

    def test_load_tickers_normalizes_and_deduplicates_symbols(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            tickers_file = config_dir / "tickers.json"
            tickers_file.write_text(
                json.dumps(
                    {
                        "ecosystem": {
                            "companies": [
                                {"ticker": " aep "},
                                {"ticker": "AEP"},
                                {"ticker": "ceg"},
                                {"ticker": "  "},
                                {},
                                {"ticker": "duk"},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(self.function_app, "Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.with_name.return_value = config_dir
                mock_path_cls.return_value = path_instance

                tickers = self.function_app._load_tickers()

        self.assertEqual(tickers, ["AEP", "CEG", "DUK"])

    def test_load_tickers_raises_when_no_valid_symbols(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            tickers_file = config_dir / "tickers.json"
            tickers_file.write_text(
                json.dumps({"ecosystem": {"companies": [{"ticker": "  "}, {}]}}),
                encoding="utf-8",
            )

            with patch.object(self.function_app, "Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.with_name.return_value = config_dir
                mock_path_cls.return_value = path_instance

                with self.assertRaises(ValueError) as ctx:
                    self.function_app._load_tickers()

        self.assertIn("does not contain any valid tickers", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
