"""Deployment/runtime configuration helpers for Streamlit on Azure App Service."""

from __future__ import annotations

from collections.abc import Mapping


def build_streamlit_startup_command(app_path: str) -> str:
    return (
        f"streamlit run {app_path} "
        "--server.address=0.0.0.0 "
        "--server.port=${PORT:-8000}"
    )


def resolve_runtime_port(env: Mapping[str, str], default_port: int = 8000) -> int:
    value = env.get("PORT")
    if value is None or str(value).strip() == "":
        return default_port

    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError("PORT must be an integer") from exc

    if port <= 0:
        raise ValueError("PORT must be a positive integer")
    return port


def build_app_service_settings(base: dict[str, str] | None = None) -> dict[str, str]:
    settings = {
        "WEBSITES_PORT": "8000",
        "PYTHONUNBUFFERED": "1",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    if base:
        settings.update(base)
    return settings
