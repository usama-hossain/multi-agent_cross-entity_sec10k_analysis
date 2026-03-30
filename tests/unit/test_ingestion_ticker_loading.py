"""
Module: test_ingestion_ticker_loading.py
Purpose: Characterize ticker-loading behavior for ingestion kickoff.
Dependencies: temporary JSON fixtures, function_app import stubs
Markers: unit
"""

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.unit._ingestion_test_helpers import import_function_app_with_service_stubs


@pytest.fixture
def function_app():
    """Import function app with service stubs."""
    return import_function_app_with_service_stubs()


@pytest.mark.unit
class TestTickerLoading:
    """Tests for ticker loading behavior."""

    def test_load__mixed_case_and_duplicates__normalizes_and_deduplicates(self, function_app):
        """Verify ticker loading normalizes case and removes duplicates."""
        # Arrange
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            tickers_file = config_dir / "tickers.json"
            tickers_file.write_text(
                json.dumps({
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
                }),
                encoding="utf-8",
            )

            with patch.object(function_app, "Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.with_name.return_value = config_dir
                mock_path_cls.return_value = path_instance

                # Act
                tickers = function_app._load_tickers()

        # Assert
        assert tickers == ["AEP", "CEG", "DUK"], (
            f"Should normalize and deduplicate tickers.\n"
            f"Expected: ['AEP', 'CEG', 'DUK']\n"
            f"Got: {tickers}"
        )

    def test_load__no_valid_symbols__raises_error(self, function_app):
        """Verify loader raises error when no valid symbols found."""
        # Arrange
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            tickers_file = config_dir / "tickers.json"
            tickers_file.write_text(
                json.dumps({"ecosystem": {"companies": [{"ticker": "  "}, {}]}}),
                encoding="utf-8",
            )

            with patch.object(function_app, "Path") as mock_path_cls:
                path_instance = MagicMock()
                path_instance.with_name.return_value = config_dir
                mock_path_cls.return_value = path_instance

                # Act & Assert
                with pytest.raises(ValueError) as exc_info:
                    function_app._load_tickers()

        assert "does not contain any valid tickers" in str(exc_info.value), (
            f"Error should indicate no valid tickers found.\n"
            f"Got: {exc_info.value}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

