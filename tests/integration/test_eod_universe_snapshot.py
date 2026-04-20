from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from swingtrader_v2.data.freshness import assess_freshness
from swingtrader_v2.data.symbol_master import build_symbol_master_snapshot
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.market.universe_builder import build_universe_snapshot


ROOT = Path(__file__).resolve().parents[2]
NY_TZ = ZoneInfo("America/New_York")


def test_can_build_point_in_time_eod_universe_snapshot_from_normalized_bars():
    fixture = json.loads((ROOT / "tests" / "fixtures" / "bars" / "universe_sample.json").read_text(encoding="utf-8"))

    metadata_by_symbol = {symbol: payload["metadata"] for symbol, payload in fixture.items()}
    bars_by_symbol = {}
    freshness_by_symbol = {}

    for symbol, payload in fixture.items():
        expanded_rows = []
        end_date = date(2025, 4, 17)
        for offset in range(260):
            source = payload["bars"][offset % len(payload["bars"])]
            expanded_rows.append(
                {
                    **source,
                    "date": (end_date - timedelta(days=259 - offset)).isoformat(),
                }
            )
        bars_result = normalize_daily_bars(symbol, expanded_rows)
        bars_by_symbol[symbol] = bars_result
        freshness_by_symbol[symbol] = assess_freshness(
            last_bar_date=bars_result.summary.last_bar_date,
            as_of=datetime(2025, 4, 18, 15, 0, tzinfo=NY_TZ),
        )

    records = build_symbol_master_snapshot(
        metadata_by_symbol=metadata_by_symbol,
        bars_by_symbol=bars_by_symbol,
        freshness_by_symbol=freshness_by_symbol,
    )
    snapshot = build_universe_snapshot(records, as_of_date=datetime(2025, 4, 18).date())

    assert [decision.symbol for decision in snapshot.included] == ["AAPL"]
    assert [decision.symbol for decision in snapshot.excluded] == ["OTCM"]
    assert "exchange_not_allowed" in snapshot.excluded[0].reason_codes
