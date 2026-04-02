"""Streamlit data-source contracts for signal-card dashboard reads."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from src.services.signal_cards.dashboard_catalog import (
    SIGNAL_CARD_BLOB_PREFIX,
    TickerSignalCoverageView,
    build_ticker_signal_coverage_views,
)


class BlobStorePort(Protocol):
    def list_blobs(self, prefix: str) -> list[str]:
        ...

    def download_blob(self, blob_name: str) -> bytes:
        ...


class TickerConfigPort(Protocol):
    def get_ticker_companies(self) -> list[dict[str, str]]:
        ...


@dataclass(frozen=True)
class TickerCatalogMetrics:
    blobs_scanned: int
    cards_loaded: int
    malformed_cards: int
    fetch_duration_ms: float


@dataclass(frozen=True)
class TickerCatalogResult:
    entries: list[TickerSignalCoverageView]
    metrics: TickerCatalogMetrics


class JsonTickerConfigProvider:
    """Read ticker companies from a ticker config file."""

    def __init__(self, config_path: str):
        self.config_path = config_path

    def get_ticker_companies(self) -> list[dict[str, str]]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        companies = payload.get("ecosystem", {}).get("companies", [])
        if not isinstance(companies, list):
            return []

        normalized: list[dict[str, str]] = []
        for item in companies:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker", "")).strip()
            if not ticker:
                continue
            normalized.append(
                {
                    "ticker": ticker,
                    "name": str(item.get("name", ticker)).strip() or ticker,
                }
            )
        return normalized


class StreamlitSignalCardDataSource:
    """Blob-backed, cached read model for Streamlit ticker catalog pages."""

    def __init__(
        self,
        blob_store: BlobStorePort,
        ticker_config: TickerConfigPort,
        ttl_seconds: int,
        now_fn: Callable[[], float] | None = None,
    ):
        self._blob_store = blob_store
        self._ticker_config = ticker_config
        self._ttl_seconds = ttl_seconds
        self._now_fn = now_fn or time.time

        self._cache_value: TickerCatalogResult | None = None
        self._cache_expires_at: float = 0.0

    def get_ticker_catalog(self) -> TickerCatalogResult:
        now = self._now_fn()
        if self._cache_value is not None and now < self._cache_expires_at:
            return self._cache_value

        started = time.perf_counter()
        blob_names = list(self._blob_store.list_blobs(prefix=SIGNAL_CARD_BLOB_PREFIX))
        ticker_companies = self._ticker_config.get_ticker_companies()

        entries = build_ticker_signal_coverage_views(
            ticker_companies=ticker_companies,
            list_blob_names=lambda: blob_names,
            download_blob=self._blob_store.download_blob,
        )

        metrics = TickerCatalogMetrics(
            blobs_scanned=len(blob_names),
            cards_loaded=sum(len(entry.cards) for entry in entries),
            malformed_cards=sum(entry.malformed_cards for entry in entries),
            fetch_duration_ms=(time.perf_counter() - started) * 1000.0,
        )
        result = TickerCatalogResult(entries=entries, metrics=metrics)

        self._cache_value = result
        self._cache_expires_at = now + max(0, int(self._ttl_seconds))
        return result
