"""Release gate checks for production deployment and rollback recommendation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseSmokeResult:
    overview_count: int
    required_ticker: str | None
    required_ticker_found: bool
    required_ticker_detail_ready: bool


@dataclass(frozen=True)
class ReleaseDecision:
    ready_to_release: bool
    rollback_recommended: bool
    reasons: list[str]


def run_release_smoke_checks(runtime, required_ticker: str | None) -> ReleaseSmokeResult:
    overview = runtime.load_overview(search_query="")
    rows = list(getattr(overview, "rows", []))
    tickers = {getattr(row, "ticker", "") for row in rows}

    found = True
    detail_ready = True
    if required_ticker:
        found = required_ticker in tickers
        if found:
            detail = runtime.load_detail(ticker=required_ticker, fiscal_year=None)
            detail_ready = getattr(detail, "state", "") == "ready"
        else:
            detail_ready = False

    return ReleaseSmokeResult(
        overview_count=len(rows),
        required_ticker=required_ticker,
        required_ticker_found=found,
        required_ticker_detail_ready=detail_ready,
    )


def build_release_decision(smoke: ReleaseSmokeResult) -> ReleaseDecision:
    reasons: list[str] = []

    if smoke.overview_count <= 0:
        reasons.append("Overview has no processed tickers.")
    if smoke.required_ticker and not smoke.required_ticker_found:
        reasons.append("Required ticker is missing from overview.")
    if smoke.required_ticker and smoke.required_ticker_found and not smoke.required_ticker_detail_ready:
        reasons.append("Required ticker detail page is not ready.")

    ready = len(reasons) == 0
    return ReleaseDecision(
        ready_to_release=ready,
        rollback_recommended=not ready,
        reasons=reasons,
    )
