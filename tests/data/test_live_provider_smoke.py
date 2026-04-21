from __future__ import annotations

import os
import socket
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from zoneinfo import ZoneInfo

import pytest

from swingtrader_v2.data.freshness import assess_freshness
from swingtrader_v2.data.sources import YFinanceDailyBarSource
from swingtrader_v2.data.symbol_master import build_symbol_master_snapshot
from swingtrader_v2.domain.enums import DataSupportStatus, MarketDataProvider, ProviderMode
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.market.benchmarks import prepare_spy_benchmark
from swingtrader_v2.market.universe_builder import build_universe_snapshot


NY_TZ = ZoneInfo("America/New_York")
LIVE_SYMBOLS = ("AAPL", "MSFT", "NVDA")
EXTERNAL_MESSAGE_TOKENS = (
    "too many requests",
    "rate limit",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "name resolution",
    "network is unreachable",
    "connection reset",
    "unable to open database file",
    "readonly database",
    "database is locked",
)


def _require_live_smoke() -> None:
    if os.getenv("SWINGTRADER_RUN_LIVE_SMOKE") != "1":
        pytest.skip("live provider smoke disabled; set SWINGTRADER_RUN_LIVE_SMOKE=1 to enable")


def _iter_exception_chain(exc: BaseException):
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _format_exception_chain(exc: BaseException) -> str:
    parts = []
    for current in _iter_exception_chain(exc):
        parts.append(f"{current.__class__.__module__}.{current.__class__.__name__}: {current}")
    return " -> ".join(parts)


def _classify_external_live_text(text: str) -> str | None:
    lowered = text.lower()
    if any(token in lowered for token in EXTERNAL_MESSAGE_TOKENS):
        return "provider or environment unavailable"
    return None


def _classify_external_live_issue(exc: BaseException) -> str | None:
    """Return a narrow external skip reason, or None for product/code failures.

    External skip conditions are intentionally limited to provider/network/env
    availability failures. Empty normalized outputs without an explicit external
    cause are treated as regressions and must fail.
    """

    for current in _iter_exception_chain(exc):
        message = str(current).lower()
        qualified_name = f"{current.__class__.__module__}.{current.__class__.__name__}".lower()

        if isinstance(current, (TimeoutError, ConnectionError, socket.gaierror)):
            return "network/provider connection unavailable"
        if isinstance(current, PermissionError):
            return "provider environment permission failure"
        if "requests" in qualified_name and any(
            token in qualified_name
            for token in ("connectionerror", "timeout", "httperror", "requestexception")
        ):
            return "provider HTTP transport unavailable"
        text_reason = _classify_external_live_text(message)
        if text_reason is not None:
            return text_reason
    return None


def _skip_if_external_live_issue(stage: str, exc: BaseException) -> None:
    reason = _classify_external_live_issue(exc)
    if reason is not None:
        pytest.skip(
            f"{stage} skipped for external live-provider condition: {reason}; "
            f"exception chain: {_format_exception_chain(exc)}"
        )


@contextmanager
def _capture_provider_logs(logger_name: str = "yfinance"):
    logger = logging.getLogger(logger_name)
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler(level=logging.ERROR)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def _skip_if_external_provider_logs(stage: str, records: list[logging.LogRecord]) -> None:
    rendered = " | ".join(record.getMessage() for record in records)
    reason = _classify_external_live_text(rendered)
    if reason is not None:
        pytest.skip(
            f"{stage} skipped for external live-provider condition: {reason}; "
            f"provider logs: {rendered}"
        )


def _fetch_payloads():
    _require_live_smoke()
    pytest.importorskip("yfinance")
    source = YFinanceDailyBarSource()
    end = datetime.now(NY_TZ).date() + timedelta(days=1)
    start = end - timedelta(days=450)
    try:
        with _capture_provider_logs() as provider_logs:
            payloads = source.fetch_daily_bars(list(LIVE_SYMBOLS), start=start, end=end)
    except Exception as exc:  # pragma: no cover - live-provider only
        _skip_if_external_live_issue("provider fetch", exc)
        pytest.fail(f"provider fetch regression: {_format_exception_chain(exc)}")

    missing_symbols = sorted(symbol for symbol in LIVE_SYMBOLS if symbol not in payloads)
    assert not missing_symbols, f"provider fetch contract regression: missing payloads for {', '.join(missing_symbols)}"

    empty = sorted(symbol for symbol, payload in payloads.items() if symbol in LIVE_SYMBOLS and not payload.rows)
    if empty:
        _skip_if_external_provider_logs("provider fetch", provider_logs)
        pytest.fail(
            "provider normalization regression: empty normalized rows for "
            f"{', '.join(empty)} without an explicit external provider failure; "
            f"provider logs: {' | '.join(record.getMessage() for record in provider_logs) or '<none>'}"
        )
    return source, payloads, start, end


@pytest.mark.live_provider
def test_yfinance_live_provider_normalizes_representative_equities():
    _, payloads, _, _ = _fetch_payloads()

    for symbol in LIVE_SYMBOLS:
        payload = payloads[symbol]
        assert payload.provider is MarketDataProvider.YFINANCE
        assert payload.provider_mode is ProviderMode.BASELINE
        assert payload.degraded is False
        assert payload.reason_codes == ()
        assert payload.rows

        normalized = normalize_daily_bars(symbol, payload.rows)
        assert normalized.status in {DataSupportStatus.OK, DataSupportStatus.LOW_CONFIDENCE}
        assert normalized.summary.completed_bars >= 252
        assert normalized.summary.last_bar_date is not None
        assert normalized.bars[-1].session_date == normalized.summary.last_bar_date
        assert normalized.bars[-1].close > 0
        assert normalized.bars[-1].volume >= 0

        freshness = assess_freshness(last_bar_date=normalized.summary.last_bar_date, as_of=datetime.now(NY_TZ))
        assert freshness.last_bar_date is not None
        assert freshness.last_bar_date <= freshness.expected_session
        assert freshness.status in {DataSupportStatus.OK, DataSupportStatus.STALE}


@pytest.mark.live_provider
def test_live_provider_smoke_covers_benchmark_and_universe_contracts():
    source, payloads, start, end = _fetch_payloads()
    try:
        benchmark = prepare_spy_benchmark(provider=source, start=start, end=end, as_of=datetime.now(NY_TZ))
    except Exception as exc:  # pragma: no cover - live-provider only
        _skip_if_external_live_issue("benchmark preparation", exc)
        pytest.fail(f"benchmark preparation regression: {_format_exception_chain(exc)}")

    assert benchmark.bars.bars, (
        "benchmark preparation regression: SPY benchmark normalization returned "
        "no bars without an explicit external provider failure"
    )

    assert benchmark.symbol == "SPY"
    assert benchmark.bars.summary.completed_bars >= 252
    assert benchmark.bars.summary.last_bar_date is not None
    assert benchmark.freshness.last_bar_date == benchmark.bars.summary.last_bar_date

    bars_by_symbol = {
        symbol: normalize_daily_bars(symbol, payload.rows)
        for symbol, payload in payloads.items()
    }
    freshness_by_symbol = {
        symbol: assess_freshness(last_bar_date=bars.summary.last_bar_date, as_of=datetime.now(NY_TZ))
        for symbol, bars in bars_by_symbol.items()
    }
    metadata_by_symbol = {
        symbol: {
            "symbol": symbol,
            "exchange": "NASDAQ",
            "asset_type": "common_stock",
            "currency": "USD",
            "name": symbol,
        }
        for symbol in LIVE_SYMBOLS
    }
    snapshot = build_universe_snapshot(
        build_symbol_master_snapshot(
            metadata_by_symbol=metadata_by_symbol,
            bars_by_symbol=bars_by_symbol,
            freshness_by_symbol=freshness_by_symbol,
        ),
        as_of_date=datetime.now(NY_TZ).date(),
    )

    assert {decision.symbol for decision in snapshot.included} == set(LIVE_SYMBOLS), (
        "universe-input contract regression: representative live symbols did not "
        "survive the point-in-time inclusion contract"
    )
    assert snapshot.excluded == ()
