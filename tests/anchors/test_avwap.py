from __future__ import annotations

from datetime import date, timedelta

from swingtrader_v2.anchors.avwap import compute_daily_bar_avwap_proxy
from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import NormalizedBar


def _bars() -> tuple[NormalizedBar, ...]:
    bars = []
    for index in range(8):
        close = 100 + (index * 2)
        bars.append(
            NormalizedBar(
                symbol="AAPL",
                session_date=date(2025, 2, 1) + timedelta(days=index),
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                adjusted_close=close,
                volume=1_000_000 + (index * 100_000),
                dividend=0.0,
                split_ratio=1.0,
                adjustment_factor=1.0,
            )
        )
    return tuple(bars)


def test_daily_bar_avwap_proxy_is_explicitly_labeled_and_descriptive():
    result = compute_daily_bar_avwap_proxy(_bars(), anchor_index=2)
    assert result.status is DataSupportStatus.OK
    assert result.current_avwap is not None
    assert result.distance_from_close_pct is not None
    assert result.short_slope is not None
    assert result.bars_since_anchor == 5
    assert result.is_daily_proxy is True


def test_daily_bar_avwap_proxy_marks_invalid_anchor_explicitly():
    result = compute_daily_bar_avwap_proxy(_bars(), anchor_index=50)
    assert result.status is DataSupportStatus.UNSUPPORTED
    assert result.reason == "anchor_index_out_of_range"
