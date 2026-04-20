from __future__ import annotations

from datetime import date, timedelta

from swingtrader_v2.analysis.momentum import compute_momentum_features
from swingtrader_v2.analysis.moving_averages import compute_moving_averages
from swingtrader_v2.analysis.patterns import compute_pattern_features
from swingtrader_v2.analysis.relative_strength import compute_relative_strength_features
from swingtrader_v2.analysis.volume import compute_volume_features
from swingtrader_v2.analysis.volatility import compute_volatility_features
from swingtrader_v2.anchors.definitions import ManualAnchorDefinition
from swingtrader_v2.anchors.resolver import resolve_anchor
from swingtrader_v2.scanner.detectors import (
    ScannerInput,
    detect_avwap_reclaim,
    detect_base_breakout,
    detect_trend_pullback,
    run_all_detectors,
)
from swingtrader_v2.market.bars import NormalizedBar


def _bars_from_closes(closes: list[float], *, start: date = date(2025, 1, 1), volume: int = 2_000_000) -> tuple[NormalizedBar, ...]:
    bars: list[NormalizedBar] = []
    for index, close in enumerate(closes):
        bars.append(
            NormalizedBar(
                symbol="AAPL",
                session_date=start + timedelta(days=index),
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                adjusted_close=close,
                volume=volume + (index * 20_000),
                dividend=0.0,
                split_ratio=1.0,
                adjustment_factor=1.0,
            )
        )
    return tuple(bars)


def _scanner_input(bars: tuple[NormalizedBar, ...], anchors=()):
    benchmark = _bars_from_closes([100 + (index * 0.3) for index in range(len(bars))], start=bars[0].session_date)
    return ScannerInput(
        symbol="AAPL",
        as_of_date=bars[-1].session_date,
        bars=bars,
        moving_averages=compute_moving_averages(bars),
        volume=compute_volume_features(bars),
        volatility=compute_volatility_features(bars),
        patterns=compute_pattern_features(bars),
        relative_strength=compute_relative_strength_features(bars, benchmark, peer_excess_returns={63: [0.05, 0.1], 21: [0.01, 0.04]}),
        anchors=anchors,
    )


def test_trend_pullback_detector_routes_independently():
    closes = [100 + (index * 1.0) for index in range(220)]
    closes[-8:] = [300, 295, 292, 289, 291, 294, 297, 301]
    payload = _scanner_input(_bars_from_closes(closes))
    result = detect_trend_pullback(payload)
    assert result.detected is True
    assert "positive_63d_excess_return_vs_spy" in result.evidence
    assert "support_proximity_present" in result.evidence


def test_base_breakout_detector_routes_independently():
    closes = [120 - (index * 0.2) for index in range(20)]
    closes += [104, 101, 103, 100, 102, 101, 100.5, 101.5, 100.8, 102.0] * 5
    closes += [103.0, 103.5, 104.0, 104.8, 105.0]
    bars = _bars_from_closes(closes, volume=2_500_000)
    payload = _scanner_input(bars)
    result = detect_base_breakout(payload)
    assert result.detected is True
    assert "base_length_threshold_met" in result.evidence
    assert "pivot_proximity_present" in result.evidence


def test_avwap_reclaim_detector_requires_active_anchor_and_hold():
    closes = [100 + (index * 0.6) for index in range(80)]
    closes[-5:] = [140, 139, 141, 142, 144]
    bars = _bars_from_closes(closes)
    anchor = resolve_anchor(
        symbol="AAPL",
        bars=bars,
        definition=ManualAnchorDefinition(
            family="manual_anchor",
            name="manual_reclaim",
            anchor_date=bars[-10].session_date,
            anchor_value=bars[-10].close,
        ),
        config_fingerprint="a" * 64,
    )
    payload = _scanner_input(bars, anchors=(anchor,))
    result = detect_avwap_reclaim(payload)
    assert result.detected is True
    assert "close_above_avwap_proxy" in result.evidence
    assert "distance_to_avwap_in_band" in result.evidence


def test_run_all_detectors_is_family_sorted_and_keeps_rejections():
    bars = _bars_from_closes([100, 101, 102, 103, 104, 105])
    payload = _scanner_input(bars)
    results = run_all_detectors(payload)
    assert [item.family.value for item in results] == ["avwap_reclaim", "base_breakout", "trend_pullback"]
    assert any(result.detected is False for result in results)
