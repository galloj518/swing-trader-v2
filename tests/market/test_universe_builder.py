from __future__ import annotations

from swingtrader_v2.data.symbol_master import SymbolMasterRecord
from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.universe_builder import evaluate_universe_membership


def _record(**overrides) -> SymbolMasterRecord:
    base = dict(
        symbol="AAPL",
        exchange="NASDAQ",
        asset_type="common_stock",
        currency="USD",
        name="Apple Inc.",
        last_close=150.0,
        median_50d_volume=2_000_000.0,
        median_50d_dollar_volume=300_000_000.0,
        completed_bars=300,
        bar_status=DataSupportStatus.OK,
        freshness_status=DataSupportStatus.OK,
        degraded=False,
        reason_codes=(),
    )
    base.update(overrides)
    return SymbolMasterRecord(**base)


def test_universe_membership_accepts_architecture_defaults():
    decision = evaluate_universe_membership(_record())
    assert decision.included is True
    assert decision.reason_codes == ()


def test_universe_membership_emits_explicit_reason_codes():
    decision = evaluate_universe_membership(
        _record(
            exchange="OTC",
            last_close=8.0,
            median_50d_volume=900_000.0,
            median_50d_dollar_volume=18_000_000.0,
            completed_bars=200,
            freshness_status=DataSupportStatus.STALE,
        )
    )

    assert decision.included is False
    assert "exchange_not_allowed" in decision.reason_codes
    assert "close_below_minimum" in decision.reason_codes
    assert "median_50d_volume_below_minimum" in decision.reason_codes
    assert "median_50d_dollar_volume_below_minimum" in decision.reason_codes
    assert "completed_bars_below_minimum" in decision.reason_codes
    assert "freshness_unusable" in decision.reason_codes
