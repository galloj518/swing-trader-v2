"""Descriptive momentum state for normalized end-of-day bars."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class MomentumMetric:
    name: str
    value: float | None
    status: DataSupportStatus
    reason: str | None = None


@dataclass(frozen=True)
class MomentumFeatureSet:
    status: DataSupportStatus
    metrics: tuple[MomentumMetric, ...]


def _return_pct(bars: tuple[NormalizedBar, ...], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    prior_close = bars[-(lookback + 1)].close
    if prior_close == 0:
        return None
    return (bars[-1].close - prior_close) / prior_close


def _gap_measure(bars: tuple[NormalizedBar, ...]) -> tuple[float | None, float | None]:
    if len(bars) < 2:
        return None, None
    previous_close = bars[-2].close
    if previous_close == 0:
        return None, None
    gap_pct = (bars[-1].open - previous_close) / previous_close
    gap_to_range = (bars[-1].open - bars[-2].high) / previous_close if bars[-1].open >= previous_close else (bars[-1].open - bars[-2].low) / previous_close
    return gap_pct, gap_to_range


def compute_momentum_features(bars: tuple[NormalizedBar, ...]) -> MomentumFeatureSet:
    lookbacks = (5, 10, 21, 63)
    metrics: list[MomentumMetric] = []
    statuses: list[DataSupportStatus] = []
    for lookback in lookbacks:
        value = _return_pct(bars, lookback)
        status = DataSupportStatus.OK if value is not None else DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING
        metrics.append(
            MomentumMetric(
                name=f"return_{lookback}d",
                value=value,
                status=status,
                reason=None if value is not None else f"insufficient_bars_for_return_{lookback}d",
            )
        )
        statuses.append(status)

    gap_pct, gap_range = _gap_measure(bars)
    for name, value in (("gap_pct", gap_pct), ("gap_vs_prior_range_pct", gap_range)):
        status = DataSupportStatus.OK if value is not None else DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING
        metrics.append(
            MomentumMetric(
                name=name,
                value=value,
                status=status,
                reason=None if value is not None else f"insufficient_bars_for_{name}",
            )
        )
        statuses.append(status)

    overall = (
        DataSupportStatus.MISSING
        if all(status is DataSupportStatus.MISSING for status in statuses)
        else DataSupportStatus.LOW_CONFIDENCE
        if any(status is not DataSupportStatus.OK for status in statuses)
        else DataSupportStatus.OK
    )
    return MomentumFeatureSet(status=overall, metrics=tuple(metrics))
