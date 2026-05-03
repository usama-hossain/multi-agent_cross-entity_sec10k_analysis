#!/usr/bin/env python3
"""Generate and persist ticker insights using latest five yearly signal cards.

Examples:
  python scripts/admin/generate_ticker_insight.py --ticker EQIX
  python scripts/admin/generate_ticker_insight.py --ticker VST --fail-on-empty
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ticker-level LLM insights from stored signal cards.",
    )
    parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g., EQIX)")
    parser.add_argument(
        "--settings-path",
        default="config/local.settings.json",
        help="Path to local settings JSON (default: config/local.settings.json)",
    )
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Exit non-zero if no signal cards exist for ticker.",
    )
    return parser.parse_args()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_local_settings_into_env(project_root: Path, settings_path: str) -> None:
    candidate = (project_root / settings_path).resolve()
    if not candidate.exists():
        return

    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return

    values = payload.get("Values", {})
    if not isinstance(values, dict):
        return

    # Respect existing shell env vars; only fill missing values.
    for key, value in values.items():
        if key in os.environ:
            continue
        if value is None:
            continue
        os.environ[key] = str(value)


def _validate_required_config() -> list[str]:
    required = [
        "AzureWebJobsStorage",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "AZURE_OPENAI_ENDPOINT",
        "OPENAI_API_VERSION",
    ]
    return [key for key in required if not str(os.getenv(key, "")).strip()]


def _print_result(result: dict[str, Any]) -> None:
    print("Ticker insight generation result")
    print(f"  ticker: {result.get('ticker')}")
    print(f"  status: {result.get('status')}")
    print(f"  cards_used: {result.get('cards_used')}")
    if result.get("year_range"):
        yr = result["year_range"]
        print(f"  year_range: {yr.get('min')} - {yr.get('max')}")
    print(f"  blob_name: {result.get('blob_name')}")


def main() -> int:
    args = _parse_args()
    project_root = _project_root()

    # Make project imports available for direct script execution.
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    _load_local_settings_into_env(project_root, args.settings_path)

    missing = _validate_required_config()
    if missing:
        print("Missing required configuration values:")
        for key in missing:
            print(f"  - {key}")
        print("Set them via environment variables or local settings before running.")
        return 2

    from src.services.signal_cards.ticker_insight_orchestrator import TickerInsightOrchestrator

    orchestrator = TickerInsightOrchestrator()
    result = orchestrator.generate_and_store_for_ticker(args.ticker)
    _print_result(result)

    if args.fail_on_empty and str(result.get("status", "")).lower() == "empty":
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
