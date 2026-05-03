"""Runtime composition for Streamlit dashboard pages."""

from __future__ import annotations

import json
import os
from typing import Callable

from src.adapters.blob_storage import AzureBlobArtifactStore
from src.apps.streamlit_dashboard.controllers import (
    load_ticker_detail_page_model,
    load_ticker_overview_page_model,
)
from src.core.blob_paths import BlobPaths
from src.services.signal_cards.ticker_insight_orchestrator import TickerInsightOrchestrator
from src.services.signal_cards.streamlit_data_source import (
    JsonTickerConfigProvider,
    StreamlitSignalCardDataSource,
)


class StreamlitBlobStoreAdapter:
    """Adapter that exposes list/download API expected by Streamlit data source."""

    def __init__(self, store: AzureBlobArtifactStore):
        self._store = store

    def list_blobs(self, prefix: str) -> list[str]:
        if not self._store.container_client:
            return []
        return [blob.name for blob in self._store.container_client.list_blobs(name_starts_with=prefix)]

    def download_blob(self, blob_name: str) -> bytes:
        return self._store.download_blob(blob_name)

    def blob_exists(self, blob_name: str) -> bool:
        return self._store.blob_exists(blob_name)


class StreamlitDashboardRuntime:
    def __init__(self, data_source, blob_store: AzureBlobArtifactStore):
        self._data_source = data_source
        self._blob_store = blob_store

    def load_overview(self, search_query: str):
        return load_ticker_overview_page_model(data_source=self._data_source, search_query=search_query)

    def load_detail(self, ticker: str, fiscal_year: int | None):
        return load_ticker_detail_page_model(
            data_source=self._data_source,
            ticker=ticker,
            fiscal_year=fiscal_year,
        )

    def load_analysis(self, ticker: str) -> dict | None:
        normalized_ticker = str(ticker or "").strip().upper()
        if not normalized_ticker:
            return None

        blob_name = BlobPaths.ticker_insight(normalized_ticker)
        if not self._blob_store.blob_exists(blob_name):
            return None

        payload = self._blob_store.download_blob(blob_name).decode("utf-8")
        return json.loads(payload)

    def generate_analysis(self, ticker: str) -> dict:
        orchestrator = TickerInsightOrchestrator(blob_store=self._blob_store)
        return orchestrator.generate_and_store_for_ticker(ticker)


def build_runtime_from_environment(
    blob_store_factory: Callable[[], object] | None = None,
    ticker_config_cls=JsonTickerConfigProvider,
    data_source_cls=StreamlitSignalCardDataSource,
) -> StreamlitDashboardRuntime:
    config_path = os.getenv("STREAMLIT_TICKERS_CONFIG_PATH", "config/tickers.json")
    ttl_raw = os.getenv("STREAMLIT_CACHE_TTL_SECONDS", "300")

    try:
        ttl_seconds = int(ttl_raw)
    except ValueError as exc:
        raise ValueError("STREAMLIT_CACHE_TTL_SECONDS must be an integer") from exc

    if blob_store_factory is None:
        azure_blob_store = AzureBlobArtifactStore()
        blob_store = StreamlitBlobStoreAdapter(azure_blob_store)
    else:
        provided = blob_store_factory()
        blob_store = provided
        azure_blob_store = getattr(provided, "_store", provided)

    ticker_config = ticker_config_cls(config_path=config_path)
    data_source = data_source_cls(
        blob_store=blob_store,
        ticker_config=ticker_config,
        ttl_seconds=ttl_seconds,
    )
    return StreamlitDashboardRuntime(data_source=data_source, blob_store=azure_blob_store)
