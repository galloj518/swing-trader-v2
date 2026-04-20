"""Descriptive volume state for normalized end-of-day bars."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class VolumeMetric:
    name: str
    value: float | None
    status: DataSupportStatus
    reason: str | None = None


@dataclass(frozen=True)
class VolumeFeatureSet:
    status: DataSupportStatus
    metrics: tuple[VolumeMetric, ...]


def compute_volume_features(bars: tuple[NormalizedBar, ...], *, window: int = 50) -> VolumeFeatureSet:
    if not bars:
        missing = (
            VolumeMetric("median_volume_50d", None, DataSupportStatus.MISSING, "missing_bars"),
            VolumeMetric("median_dollar_volume_50d", None, DataSupportStatus.MISSING, "missing_bars"),
            VolumeMetric("relative_volume_20d", None, DataSupportStatus.MISSING, "missing_bars"),
            VolumeMetric("up_down_volume_ratio_20d", None, DataSupportStatus.MISSING, "missing_bars"),
        )
        return VolumeFeatureSet(status=DataSupportStatus.MISSING, metrics=missing)

    trailing = bars[-window:]
    volumes = [bar.volume for bar in trailing]
    dollar_volumes = [bar.dollar_volume for bar in trailing]
    relative_trailing = bars[-20:] if len(bars) >= 20 else bars
    rel_volume_baseline = median([bar.volume for bar in relative_trailing]) if relative_trailing else None
    relative_volume = bars[-1].volume / rel_volume_baseline if rel_volume_baseline not in (None, 0) else None
    up_volume = sum(bar.volume for index, bar in enumerate(relative_trailing[1:], start=1) if bar.close >= relative_trailing[index - 1].close)
    down_volume = sum(bar.volume for index, bar in enumerate(relative_trailing[1:], start=1) if bar.close < relative_trailing[index - 1].close)
    up_down_ratio = up_volume / down_volume if down_volume else None

    metrics = (
        VolumeMetric("median_volume_50d", float(median(volumes)), DataSupportStatus.OK),
        VolumeMetric("median_dollar_volume_50d", float(median(dollar_volumes)), DataSupportStatus.OK),
        VolumeMetric(
            "relative_volume_20d",
            relative_volume,
            DataSupportStatus.OK if relative_volume is not None else DataSupportStatus.LOW_CONFIDENCE,
            None if relative_volume is not None else "insufficient_nonzero_volume_baseline",
        ),
        VolumeMetric(
            "up_down_volume_ratio_20d",
            up_down_ratio,
            DataSupportStatus.OK if up_down_ratio is not None else DataSupportStatus.LOW_CONFIDENCE,
            None if up_down_ratio is not None else "insufficient_down_volume",
        ),
    )
    overall = DataSupportStatus.LOW_CONFIDENCE if any(metric.status is not DataSupportStatus.OK for metric in metrics) else DataSupportStatus.OK
    return VolumeFeatureSet(status=overall, metrics=metrics)
