"""Universe inclusion logic for point-in-time EOD snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from swingtrader_v2.data.symbol_master import SymbolMasterRecord
from swingtrader_v2.domain.enums import DataSupportStatus


@dataclass(frozen=True)
class UniverseRules:
    allowed_exchanges: tuple[str, ...] = ("NYSE", "NASDAQ", "NYSE_AMERICAN")
    allowed_asset_types: tuple[str, ...] = ("common_stock", "adr")
    min_close: float = 10.0
    min_median_50d_volume: float = 1_000_000.0
    min_median_50d_dollar_volume: float = 20_000_000.0
    min_completed_bars: int = 252


@dataclass(frozen=True)
class UniverseDecision:
    symbol: str
    included: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class UniverseSnapshot:
    as_of_date: date
    included: tuple[UniverseDecision, ...]
    excluded: tuple[UniverseDecision, ...]
    degraded: bool


DEFAULT_UNIVERSE_RULES = UniverseRules()


def evaluate_universe_membership(
    record: SymbolMasterRecord,
    *,
    rules: UniverseRules = DEFAULT_UNIVERSE_RULES,
) -> UniverseDecision:
    reasons: list[str] = []
    if record.exchange not in rules.allowed_exchanges:
        reasons.append("exchange_not_allowed")
    if record.asset_type not in rules.allowed_asset_types:
        reasons.append("asset_type_not_allowed")
    if record.last_close is None:
        reasons.append("missing_last_close")
    elif record.last_close < rules.min_close:
        reasons.append("close_below_minimum")
    if record.median_50d_volume < rules.min_median_50d_volume:
        reasons.append("median_50d_volume_below_minimum")
    if record.median_50d_dollar_volume < rules.min_median_50d_dollar_volume:
        reasons.append("median_50d_dollar_volume_below_minimum")
    if record.completed_bars < rules.min_completed_bars:
        reasons.append("completed_bars_below_minimum")
    if record.bar_status in {DataSupportStatus.MISSING, DataSupportStatus.STALE}:
        reasons.append("bar_data_unusable")
    if record.freshness_status in {DataSupportStatus.MISSING, DataSupportStatus.STALE}:
        reasons.append("freshness_unusable")
    reasons.extend(record.reason_codes)
    unique_reasons = tuple(dict.fromkeys(reasons))
    return UniverseDecision(symbol=record.symbol, included=not unique_reasons, reason_codes=unique_reasons)


def build_universe_snapshot(
    records: tuple[SymbolMasterRecord, ...],
    *,
    as_of_date: date,
    rules: UniverseRules = DEFAULT_UNIVERSE_RULES,
) -> UniverseSnapshot:
    included: list[UniverseDecision] = []
    excluded: list[UniverseDecision] = []
    degraded = False
    for record in sorted(records, key=lambda item: item.symbol):
        decision = evaluate_universe_membership(record, rules=rules)
        degraded = degraded or record.degraded
        if decision.included:
            included.append(decision)
        else:
            excluded.append(decision)
    return UniverseSnapshot(
        as_of_date=as_of_date,
        included=tuple(included),
        excluded=tuple(excluded),
        degraded=degraded,
    )
