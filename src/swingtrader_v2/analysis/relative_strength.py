"""Descriptive relative-strength state versus SPY and peers."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class RelativeStrengthMetric:
    name: str
    value: float | None
    status: DataSupportStatus
    reason: str | None = None


@dataclass(frozen=True)
class RelativeStrengthFeatureSet:
    status: DataSupportStatus
    metrics: tuple[RelativeStrengthMetric, ...]


def _return_pct(bars: tuple[NormalizedBar, ...], lookback: int) -> float | None:
    if len(bars) <= lookback:
        return None
    base = bars[-(lookback + 1)].close
    if base == 0:
        return None
    return (bars[-1].close - base) / base


def _percentile_rank(value: float, peers: list[float]) -> float:
    if not peers:
        return 1.0
    less_or_equal = sum(1 for peer in peers if peer <= value)
    return less_or_equal / len(peers)


def compute_relative_strength_features(
    bars: tuple[NormalizedBar, ...],
    benchmark_bars: tuple[NormalizedBar, ...],
    *,
    peer_excess_returns: dict[int, list[float]] | None = None,
) -> RelativeStrengthFeatureSet:
    lookbacks = (21, 63)
    metrics: list[RelativeStrengthMetric] = []
    statuses: list[DataSupportStatus] = []
    peer_excess_returns = peer_excess_returns or {}

    for lookback in lookbacks:
        asset_return = _return_pct(bars, lookback)
        benchmark_return = _return_pct(benchmark_bars, lookback)
        excess = None if asset_return is None or benchmark_return is None else asset_return - benchmark_return
        status = DataSupportStatus.OK if excess is not None else DataSupportStatus.LOW_CONFIDENCE if bars and benchmark_bars else DataSupportStatus.MISSING
        metrics.append(
            RelativeStrengthMetric(
                name=f"excess_return_vs_spy_{lookback}d",
                value=excess,
                status=status,
                reason=None if excess is not None else f"insufficient_bars_for_excess_return_{lookback}d",
            )
        )
        statuses.append(status)
        percentile = None if excess is None else _percentile_rank(excess, peer_excess_returns.get(lookback, []))
        percentile_status = DataSupportStatus.OK if percentile is not None else status
        metrics.append(
            RelativeStrengthMetric(
                name=f"excess_return_percentile_{lookback}d",
                value=percentile,
                status=percentile_status,
                reason=None if percentile is not None else f"percentile_hook_unavailable_{lookback}d",
            )
        )
        statuses.append(percentile_status)

    overall = (
        DataSupportStatus.MISSING
        if all(status is DataSupportStatus.MISSING for status in statuses)
        else DataSupportStatus.LOW_CONFIDENCE
        if any(status is not DataSupportStatus.OK for status in statuses)
        else DataSupportStatus.OK
    )
    return RelativeStrengthFeatureSet(status=overall, metrics=tuple(metrics))
