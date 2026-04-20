"""Benchmark preparation for point-in-time EOD comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from swingtrader_v2.data.freshness import FreshnessReport, assess_freshness
from swingtrader_v2.data.sources import DailyBarProvider
from swingtrader_v2.market.bars import BarNormalizationResult, normalize_daily_bars
from swingtrader_v2.market.calendar import NYSECalendar


@dataclass(frozen=True)
class BenchmarkSnapshot:
    symbol: str
    bars: BarNormalizationResult
    freshness: FreshnessReport


def prepare_spy_benchmark(
    provider: DailyBarProvider,
    *,
    start,
    end,
    as_of: datetime,
    calendar: NYSECalendar | None = None,
) -> BenchmarkSnapshot:
    payload = provider.fetch_daily_bars(["SPY"], start=start, end=end)["SPY"]
    bars = normalize_daily_bars("SPY", payload.rows)
    freshness = assess_freshness(
        last_bar_date=bars.summary.last_bar_date,
        as_of=as_of,
        calendar=calendar,
    )
    return BenchmarkSnapshot(symbol="SPY", bars=bars, freshness=freshness)
