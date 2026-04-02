"""Phase 5 contracts for Streamlit Azure packaging/runtime configuration."""

from __future__ import annotations

import pytest

from src.apps.streamlit_dashboard.deployment_config import (
    build_app_service_settings,
    build_streamlit_startup_command,
    resolve_runtime_port,
)


@pytest.mark.unit
def test_packaging__startup_command_binds_to_dynamic_port_and_all_interfaces():
    command = build_streamlit_startup_command(app_path="src/apps/streamlit_dashboard/app.py")

    assert "streamlit run src/apps/streamlit_dashboard/app.py" in command
    assert "--server.address=0.0.0.0" in command
    assert "--server.port=${PORT:-8000}" in command


@pytest.mark.unit
def test_packaging__resolve_runtime_port_prefers_port_env_then_default():
    assert resolve_runtime_port({"PORT": "9001"}, default_port=8000) == 9001
    assert resolve_runtime_port({}, default_port=8000) == 8000


@pytest.mark.unit
def test_packaging__resolve_runtime_port_invalid_value_raises():
    with pytest.raises(ValueError):
        resolve_runtime_port({"PORT": "not-a-number"}, default_port=8000)


@pytest.mark.unit
def test_packaging__app_service_settings_include_required_defaults():
    settings = build_app_service_settings(base={"STREAMLIT_CACHE_TTL_SECONDS": "120"})

    assert settings["WEBSITES_PORT"] == "8000"
    assert settings["PYTHONUNBUFFERED"] == "1"
    assert settings["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] == "false"
    assert settings["STREAMLIT_CACHE_TTL_SECONDS"] == "120"
