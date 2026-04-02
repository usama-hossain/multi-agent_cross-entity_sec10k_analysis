"""Phase 4 contracts for Streamlit runtime wiring and environment configuration."""

from __future__ import annotations

import pytest

from src.apps.streamlit_dashboard.runtime import (
    StreamlitDashboardRuntime,
    build_runtime_from_environment,
)
from src.services.signal_cards.streamlit_data_source import (
    TickerCatalogMetrics,
    TickerCatalogResult,
)


class FakeDataSource:
    def __init__(self, result: TickerCatalogResult):
        self._result = result

    def get_ticker_catalog(self) -> TickerCatalogResult:
        return self._result


@pytest.mark.unit
def test_runtime__load_overview_returns_page_model_from_data_source():
    result = TickerCatalogResult(
        entries=[],
        metrics=TickerCatalogMetrics(
            blobs_scanned=0,
            cards_loaded=0,
            malformed_cards=0,
            fetch_duration_ms=0.1,
        ),
    )
    runtime = StreamlitDashboardRuntime(data_source=FakeDataSource(result))

    page = runtime.load_overview(search_query="")

    assert page.empty_state == "No processed tickers match the current filter."
    assert page.metrics.blobs_scanned == 0


@pytest.mark.unit
def test_build_runtime_from_environment__uses_env_path_and_ttl(monkeypatch):
    captured: dict[str, object] = {}

    class FakeBlobStore:
        pass

    class FakeTickerConfigProvider:
        def __init__(self, config_path: str):
            captured["config_path"] = config_path

    class FakeDataSource:
        def __init__(self, blob_store, ticker_config, ttl_seconds: int):
            captured["blob_store"] = blob_store
            captured["ticker_config"] = ticker_config
            captured["ttl_seconds"] = ttl_seconds

    monkeypatch.setenv("STREAMLIT_TICKERS_CONFIG_PATH", "config/custom_tickers.json")
    monkeypatch.setenv("STREAMLIT_CACHE_TTL_SECONDS", "123")

    runtime = build_runtime_from_environment(
        blob_store_factory=lambda: FakeBlobStore(),
        ticker_config_cls=FakeTickerConfigProvider,
        data_source_cls=FakeDataSource,
    )

    assert isinstance(runtime, StreamlitDashboardRuntime)
    assert captured["config_path"] == "config/custom_tickers.json"
    assert captured["ttl_seconds"] == 123


@pytest.mark.unit
def test_build_runtime_from_environment__invalid_ttl_raises_value_error(monkeypatch):
    monkeypatch.setenv("STREAMLIT_CACHE_TTL_SECONDS", "abc")

    with pytest.raises(ValueError) as exc_info:
        build_runtime_from_environment(
            blob_store_factory=lambda: object(),
            ticker_config_cls=lambda _: object(),
            data_source_cls=lambda **_: object(),
        )

    assert "STREAMLIT_CACHE_TTL_SECONDS" in str(exc_info.value)
