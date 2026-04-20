"""Descriptive moving-average state for normalized end-of-day bars."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


def _close_series(bars: tuple[NormalizedBar, ...]) -> list[float]:
    return [bar.close for bar in bars]


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _ema(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    multiplier = 2.0 / (window + 1)
    ema = sum(values[:window]) / window
    for value in values[window:]:
        ema = ((value - ema) * multiplier) + ema
    return ema


def _slope(values: list[float], *, window: int, calculator) -> float | None:
    current = calculator(values, window)
    previous = calculator(values[:-1], window) if len(values) > window else None
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous)


@dataclass(frozen=True)
class MovingAverageValue:
    name: str
    value: float | None
    slope: float | None
    distance_from_close_pct: float | None
    status: DataSupportStatus
    reason: str | None = None


@dataclass(frozen=True)
class MovingAverageFeatureSet:
    status: DataSupportStatus
    values: tuple[MovingAverageValue, ...]


def compute_moving_averages(bars: tuple[NormalizedBar, ...]) -> MovingAverageFeatureSet:
    closes = _close_series(bars)
    last_close = closes[-1] if closes else None
    specs = (
        ("ema10", 10, _ema),
        ("ema21", 21, _ema),
        ("sma50", 50, _sma),
        ("sma100", 100, _sma),
        ("sma200", 200, _sma),
    )
    values: list[MovingAverageValue] = []
    statuses: list[DataSupportStatus] = []
    for name, window, calculator in specs:
        metric = calculator(closes, window)
        slope = _slope(closes, window=window, calculator=calculator)
        if not bars:
            status = DataSupportStatus.MISSING
            reason = "missing_bars"
        elif metric is None or last_close is None:
            status = DataSupportStatus.LOW_CONFIDENCE
            reason = f"insufficient_bars_for_{name}"
        else:
            status = DataSupportStatus.OK
            reason = None
        distance = None
        if metric is not None and last_close is not None and metric != 0:
            distance = (last_close - metric) / metric
        values.append(
            MovingAverageValue(
                name=name,
                value=metric,
                slope=slope,
                distance_from_close_pct=distance,
                status=status,
                reason=reason,
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
    return MovingAverageFeatureSet(status=overall, values=tuple(values))
