"""Daily-bar proxy AVWAP calculations for v1.

This intentionally computes a daily-bar anchored VWAP proxy, not an exact
intraday AVWAP. The output is labeled as a proxy everywhere it is emitted.
"""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class AvwapProxyResult:
    status: DataSupportStatus
    current_avwap: float | None
    distance_from_close_pct: float | None
    short_slope: float | None
    bars_since_anchor: int | None
    is_daily_proxy: bool
    reason: str | None = None


def _typical_price(bar: NormalizedBar) -> float:
    return (bar.high + bar.low + bar.close) / 3.0


def compute_daily_bar_avwap_proxy(bars: tuple[NormalizedBar, ...], *, anchor_index: int) -> AvwapProxyResult:
    if not bars:
        return AvwapProxyResult(DataSupportStatus.MISSING, None, None, None, None, True, "missing_bars")
    if anchor_index < 0 or anchor_index >= len(bars):
        return AvwapProxyResult(DataSupportStatus.UNSUPPORTED, None, None, None, None, True, "anchor_index_out_of_range")

    anchored = bars[anchor_index:]
    cumulative_volume = 0.0
    cumulative_price_volume = 0.0
    proxy_series: list[float] = []
    for bar in anchored:
        cumulative_volume += bar.volume
        cumulative_price_volume += _typical_price(bar) * bar.volume
        proxy_series.append(cumulative_price_volume / cumulative_volume if cumulative_volume else 0.0)

    current = proxy_series[-1] if proxy_series else None
    close = anchored[-1].close if anchored else None
    distance = None if current in (None, 0) or close is None else (close - current) / current
    slope = None
    if len(proxy_series) >= 3 and proxy_series[-3] != 0:
        slope = (proxy_series[-1] - proxy_series[-3]) / abs(proxy_series[-3])
    status = DataSupportStatus.OK if current is not None else DataSupportStatus.LOW_CONFIDENCE
    return AvwapProxyResult(
        status=status,
        current_avwap=current,
        distance_from_close_pct=distance,
        short_slope=slope,
        bars_since_anchor=len(anchored) - 1,
        is_daily_proxy=True,
        reason=None if current is not None else "insufficient_bars_for_avwap_proxy",
    )
