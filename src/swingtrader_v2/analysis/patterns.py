"""Descriptive pattern state for normalized end-of-day bars."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class PatternMetric:
    name: str
    value: float | None
    status: DataSupportStatus
    reason: str | None = None


@dataclass(frozen=True)
class PatternFeatureSet:
    status: DataSupportStatus
    metrics: tuple[PatternMetric, ...]


def compute_pattern_features(bars: tuple[NormalizedBar, ...], *, window: int = 30) -> PatternFeatureSet:
    if len(bars) < 5:
        metrics = (
            PatternMetric("base_length_bars", None, DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING, "insufficient_bars_for_pattern_state"),
            PatternMetric("base_depth_pct", None, DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING, "insufficient_bars_for_pattern_state"),
            PatternMetric("pullback_depth_pct", None, DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING, "insufficient_bars_for_pattern_state"),
            PatternMetric("pivot_price", None, DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING, "insufficient_bars_for_pattern_state"),
            PatternMetric("support_touches", None, DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING, "insufficient_bars_for_pattern_state"),
            PatternMetric("overhead_supply_proximity_pct", None, DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING, "insufficient_bars_for_pattern_state"),
        )
        return PatternFeatureSet(status=metrics[0].status, metrics=metrics)

    trailing = bars[-window:]
    highs = [bar.high for bar in trailing]
    lows = [bar.low for bar in trailing]
    closes = [bar.close for bar in trailing]
    range_high = max(highs)
    range_low = min(lows)
    base_depth = ((range_high - range_low) / range_high) if range_high else None
    last_close = closes[-1]
    pivot_price = max(highs[-10:]) if len(highs) >= 10 else max(highs)
    pullback_low = min(lows[-10:]) if len(lows) >= 10 else min(lows)
    pullback_depth = ((pivot_price - pullback_low) / pivot_price) if pivot_price else None
    support_band = range_low * 1.02 if range_low else None
    support_touches = sum(1 for bar in trailing if support_band is not None and bar.low <= support_band)
    overhead_supply = ((range_high - last_close) / last_close) if last_close else None
    metrics = (
        PatternMetric("base_length_bars", float(len(trailing)), DataSupportStatus.OK),
        PatternMetric("base_depth_pct", base_depth, DataSupportStatus.OK if base_depth is not None else DataSupportStatus.LOW_CONFIDENCE),
        PatternMetric("pullback_depth_pct", pullback_depth, DataSupportStatus.OK if pullback_depth is not None else DataSupportStatus.LOW_CONFIDENCE),
        PatternMetric("pivot_price", pivot_price, DataSupportStatus.OK),
        PatternMetric("support_touches", float(support_touches), DataSupportStatus.OK),
        PatternMetric("overhead_supply_proximity_pct", overhead_supply, DataSupportStatus.OK if overhead_supply is not None else DataSupportStatus.LOW_CONFIDENCE),
    )
    overall = DataSupportStatus.LOW_CONFIDENCE if any(metric.status is not DataSupportStatus.OK for metric in metrics) else DataSupportStatus.OK
    return PatternFeatureSet(status=overall, metrics=metrics)
