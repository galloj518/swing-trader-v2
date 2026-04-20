from __future__ import annotations

from datetime import date, timedelta

from swingtrader_v2.anchors.definitions import AnchorDefinition, ManualAnchorDefinition
from swingtrader_v2.anchors.resolver import resolve_anchor, resolve_anchors
from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


def _bars() -> tuple[NormalizedBar, ...]:
    closes = [100, 101, 103, 102, 104, 110, 108, 112, 111, 115, 114, 118]
    bars = []
    for index, close in enumerate(closes):
        bars.append(
            NormalizedBar(
                symbol="AAPL",
                session_date=date(2025, 1, 1) + timedelta(days=index),
                open=close - 0.5,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                adjusted_close=close,
                volume=1_000_000 + (index * 50_000),
                dividend=0.0,
                split_ratio=1.0,
                adjustment_factor=1.0,
            )
        )
    return tuple(bars)


def test_manual_anchor_resolves_with_explicit_provenance_and_proxy_avwap():
    bars = _bars()
    anchor = resolve_anchor(
        symbol="AAPL",
        bars=bars,
        definition=ManualAnchorDefinition(
            family="manual_anchor",
            name="manual_test",
            anchor_date=bars[4].session_date,
            anchor_value=bars[4].close,
        ),
        config_fingerprint="a" * 64,
    )
    assert anchor.status == "active"
    assert anchor.data_status is DataSupportStatus.OK
    assert anchor.provenance.source_date == bars[4].session_date
    assert anchor.avwap_proxy is not None
    assert anchor.avwap_proxy.is_daily_proxy is True


def test_resolver_marks_missing_anchor_inactive_and_low_confidence():
    bars = _bars()[:2]
    anchor = resolve_anchor(
        symbol="AAPL",
        bars=bars,
        definition=AnchorDefinition(family="swing_pivot_high", name="pivot_high", window=2),
        config_fingerprint="b" * 64,
    )
    assert anchor.status == "inactive"
    assert anchor.data_status in {DataSupportStatus.LOW_CONFIDENCE, DataSupportStatus.MISSING}
    assert anchor.reason is not None


def test_resolve_anchors_is_deterministic_and_sorted():
    bars = _bars()
    definitions = (
        AnchorDefinition(family="breakout_pivot_day", name="breakout"),
        AnchorDefinition(family="swing_pivot_low", name="pivot_low", window=1),
    )
    first = resolve_anchors(symbol="AAPL", bars=bars, definitions=definitions, config_fingerprint="c" * 64)
    second = resolve_anchors(symbol="AAPL", bars=bars, definitions=definitions, config_fingerprint="c" * 64)
    assert [anchor.name for anchor in first] == ["breakout", "pivot_low"]
    assert first == second
