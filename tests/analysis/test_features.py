from __future__ import annotations

from datetime import date, timedelta

from swingtrader_v2.analysis.momentum import compute_momentum_features
from swingtrader_v2.analysis.moving_averages import compute_moving_averages
from swingtrader_v2.analysis.patterns import compute_pattern_features
from swingtrader_v2.analysis.relative_strength import compute_relative_strength_features
from swingtrader_v2.analysis.volume import compute_volume_features
from swingtrader_v2.analysis.volatility import compute_volatility_features
from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


def _bars(count: int, *, start: date = date(2025, 1, 1), slope: float = 1.0) -> tuple[NormalizedBar, ...]:
    bars = []
    for index in range(count):
        close = 100.0 + (index * slope)
        bars.append(
            NormalizedBar(
                symbol="AAPL",
                session_date=start + timedelta(days=index),
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                adjusted_close=close,
                volume=1_500_000 + (index * 10_000),
                dividend=0.0,
                split_ratio=1.0,
                adjustment_factor=1.0,
            )
        )
    return tuple(bars)


def test_moving_averages_emit_values_and_distances():
    result = compute_moving_averages(_bars(220))
    lookup = {item.name: item for item in result.values}
    assert result.status is DataSupportStatus.OK
    assert lookup["ema10"].value is not None
    assert lookup["sma200"].value is not None
    assert lookup["sma50"].distance_from_close_pct is not None


def test_momentum_volume_volatility_and_patterns_are_descriptive_only():
    bars = _bars(80)
    momentum = compute_momentum_features(bars)
    volume = compute_volume_features(bars)
    volatility = compute_volatility_features(bars)
    patterns = compute_pattern_features(bars)

    assert momentum.status is DataSupportStatus.OK
    assert volume.status is DataSupportStatus.LOW_CONFIDENCE
    assert any(metric.name == "up_down_volume_ratio_20d" and metric.status is DataSupportStatus.LOW_CONFIDENCE for metric in volume.metrics)
    assert volatility.metrics[0].value is not None
    assert patterns.metrics[0].name == "base_length_bars"


def test_relative_strength_uses_spy_and_percentile_hooks():
    asset = _bars(90, slope=1.2)
    spy = _bars(90, slope=0.7)
    result = compute_relative_strength_features(asset, spy, peer_excess_returns={21: [0.01, 0.03], 63: [0.04, 0.08]})
    lookup = {item.name: item for item in result.metrics}
    assert result.status is DataSupportStatus.OK
    assert lookup["excess_return_vs_spy_21d"].value is not None
    assert 0.0 <= lookup["excess_return_percentile_21d"].value <= 1.0


def test_insufficient_history_is_explicitly_low_confidence():
    short = _bars(8)
    ma = compute_moving_averages(short)
    momentum = compute_momentum_features(short)
    patterns = compute_pattern_features(short[:3])
    assert ma.status is DataSupportStatus.LOW_CONFIDENCE
    assert momentum.status is DataSupportStatus.LOW_CONFIDENCE
    assert patterns.status is DataSupportStatus.LOW_CONFIDENCE
