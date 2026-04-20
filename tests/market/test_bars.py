from __future__ import annotations

from swingtrader_v2.data.corporate_actions import extract_corporate_actions
from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.bars import DUPLICATE_SESSION_BAR, normalize_daily_bars


def test_normalize_daily_bars_sorts_deduplicates_and_keeps_raw_vs_adjusted():
    result = normalize_daily_bars(
        "AAPL",
        [
            {"date": "2025-04-16", "open": 101, "high": 103, "low": 100, "close": 102, "adjusted_close": 101.5, "volume": 2000000, "dividend": 0.0, "split_ratio": 1.0},
            {"date": "2025-04-15", "open": 100, "high": 102, "low": 99, "close": 101, "adjusted_close": 100.5, "volume": 1800000, "dividend": 0.0, "split_ratio": 1.0},
            {"date": "2025-04-15", "open": 100, "high": 102.5, "low": 99, "close": 101.2, "adjusted_close": 100.7, "volume": 1900000, "dividend": 0.0, "split_ratio": 1.0},
        ],
    )

    assert result.status is DataSupportStatus.LOW_CONFIDENCE
    assert result.duplicate_count == 1
    assert DUPLICATE_SESSION_BAR in result.reason_codes
    assert [bar.session_date.isoformat() for bar in result.bars] == ["2025-04-15", "2025-04-16"]
    assert result.bars[0].close == 101.2
    assert result.bars[0].adjusted_close == 100.7


def test_corporate_actions_extract_split_and_dividend_tags():
    result = normalize_daily_bars(
        "MSFT",
        [
            {"date": "2025-04-15", "open": 49, "high": 51, "low": 48, "close": 50, "adjusted_close": 25, "volume": 5000000, "dividend": 0.5, "split_ratio": "2:1"},
        ],
    )

    actions = extract_corporate_actions(
        {
            "date": bar.session_date,
            "dividend": bar.dividend,
            "split_ratio": bar.split_ratio,
        }
        for bar in result.bars
    )

    assert [action.action_type for action in actions] == ["dividend", "split"]
    assert actions[0].value == 0.5
    assert actions[1].value == 2.0
