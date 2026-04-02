"""Runtime composition for Streamlit dashboard pages."""

from __future__ import annotations

import os
from typing import Callable

from src.adapters.blob_storage import AzureBlobArtifactStore
from src.apps.streamlit_dashboard.controllers import (
    load_ticker_detail_page_model,
    load_ticker_overview_page_model,
)
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


class StreamlitDashboardRuntime:
    def __init__(self, data_source):
        self._data_source = data_source

    def load_overview(self, search_query: str):
        return load_ticker_overview_page_model(data_source=self._data_source, search_query=search_query)

    def load_detail(self, ticker: str, fiscal_year: int | None):
        return load_ticker_detail_page_model(
            data_source=self._data_source,
            ticker=ticker,
            fiscal_year=fiscal_year,
        )


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
        blob_store = StreamlitBlobStoreAdapter(AzureBlobArtifactStore())
    else:
        blob_store = blob_store_factory()

    ticker_config = ticker_config_cls(config_path=config_path)
    data_source = data_source_cls(
        blob_store=blob_store,
        ticker_config=ticker_config,
        ttl_seconds=ttl_seconds,
    )
    return StreamlitDashboardRuntime(data_source=data_source)
