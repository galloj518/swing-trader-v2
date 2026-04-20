"""Descriptive volatility state for normalized end-of-day bars."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class VolatilityMetric:
    name: str
    value: float | None
    status: DataSupportStatus
    reason: str | None = None


@dataclass(frozen=True)
class VolatilityFeatureSet:
    status: DataSupportStatus
    metrics: tuple[VolatilityMetric, ...]


def _true_ranges(bars: tuple[NormalizedBar, ...]) -> list[float]:
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        if previous_close is None:
            ranges.append(bar.high - bar.low)
        else:
            ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
        previous_close = bar.close
    return ranges


def _average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def compute_volatility_features(bars: tuple[NormalizedBar, ...]) -> VolatilityFeatureSet:
    if not bars:
        metrics = (
            VolatilityMetric("atr14", None, DataSupportStatus.MISSING, "missing_bars"),
            VolatilityMetric("atr14_pct", None, DataSupportStatus.MISSING, "missing_bars"),
            VolatilityMetric("atr_contraction_ratio", None, DataSupportStatus.MISSING, "missing_bars"),
        )
        return VolatilityFeatureSet(status=DataSupportStatus.MISSING, metrics=metrics)

    tr = _true_ranges(bars)
    atr14 = _average(tr, 14)
    atr63 = _average(tr, 63)
    last_close = bars[-1].close
    atr_pct = atr14 / last_close if atr14 is not None and last_close else None
    contraction_ratio = atr14 / atr63 if atr14 is not None and atr63 not in (None, 0) else None
    metrics = (
        VolatilityMetric("atr14", atr14, DataSupportStatus.OK if atr14 is not None else DataSupportStatus.LOW_CONFIDENCE, None if atr14 is not None else "insufficient_bars_for_atr14"),
        VolatilityMetric("atr14_pct", atr_pct, DataSupportStatus.OK if atr_pct is not None else DataSupportStatus.LOW_CONFIDENCE, None if atr_pct is not None else "insufficient_bars_for_atr14_pct"),
        VolatilityMetric("atr_contraction_ratio", contraction_ratio, DataSupportStatus.OK if contraction_ratio is not None else DataSupportStatus.LOW_CONFIDENCE, None if contraction_ratio is not None else "insufficient_bars_for_contraction_ratio"),
    )
    overall = DataSupportStatus.LOW_CONFIDENCE if any(metric.status is not DataSupportStatus.OK for metric in metrics) else DataSupportStatus.OK
    return VolatilityFeatureSet(status=overall, metrics=metrics)
