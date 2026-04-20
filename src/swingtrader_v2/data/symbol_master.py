"""Symbol master snapshot contracts built from normalized EOD inputs."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.data.freshness import FreshnessReport
from swingtrader_v2.market.bars import BarNormalizationResult
from swingtrader_v2.domain.enums import DataSupportStatus


@dataclass(frozen=True)
class SymbolMasterRecord:
    symbol: str
    exchange: str
    asset_type: str
    currency: str
    name: str | None
    last_close: float | None
    median_50d_volume: float
    median_50d_dollar_volume: float
    completed_bars: int
    bar_status: DataSupportStatus
    freshness_status: DataSupportStatus
    degraded: bool
    reason_codes: tuple[str, ...]


def build_symbol_master_record(
    *,
    metadata: dict,
    bars: BarNormalizationResult,
    freshness: FreshnessReport,
) -> SymbolMasterRecord:
    last_close = bars.bars[-1].close if bars.bars else None
    combined_reasons = tuple(dict.fromkeys((*bars.reason_codes, *freshness.reason_codes)))
    return SymbolMasterRecord(
        symbol=metadata["symbol"],
        exchange=metadata["exchange"],
        asset_type=metadata["asset_type"],
        currency=metadata.get("currency", "USD"),
        name=metadata.get("name"),
        last_close=last_close,
        median_50d_volume=bars.summary.median_50d_volume,
        median_50d_dollar_volume=bars.summary.median_50d_dollar_volume,
        completed_bars=bars.summary.completed_bars,
        bar_status=bars.status,
        freshness_status=freshness.status,
        degraded=bars.degraded or freshness.degraded,
        reason_codes=combined_reasons,
    )


def build_symbol_master_snapshot(
    *,
    metadata_by_symbol: dict[str, dict],
    bars_by_symbol: dict[str, BarNormalizationResult],
    freshness_by_symbol: dict[str, FreshnessReport],
) -> tuple[SymbolMasterRecord, ...]:
    records: list[SymbolMasterRecord] = []
    for symbol in sorted(metadata_by_symbol):
        records.append(
            build_symbol_master_record(
                metadata=metadata_by_symbol[symbol],
                bars=bars_by_symbol[symbol],
                freshness=freshness_by_symbol[symbol],
            )
        )
    return tuple(records)
