"""Deterministic anchor resolution for v1 anchor families."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.anchors.avwap import AvwapProxyResult, compute_daily_bar_avwap_proxy
from swingtrader_v2.anchors.definitions import AnchorDefinition, ManualAnchorDefinition, validate_anchor_definition
from swingtrader_v2.anchors.provenance import AnchorProvenance
from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.domain.ids import build_anchor_id
from swingtrader_v2.market.bars import NormalizedBar


@dataclass(frozen=True)
class ResolvedAnchor:
    anchor_id: str
    name: str
    family: str
    status: str
    data_status: DataSupportStatus
    value: float | None
    source: str
    is_daily_proxy: bool
    bar_index: int | None
    provenance: AnchorProvenance
    avwap_proxy: AvwapProxyResult | None = None
    reason: str | None = None


def _is_pivot_high(bars: tuple[NormalizedBar, ...], index: int, width: int) -> bool:
    if index - width < 0 or index + width >= len(bars):
        return False
    current = bars[index].high
    return all(current >= bars[probe].high for probe in range(index - width, index + width + 1) if probe != index)


def _is_pivot_low(bars: tuple[NormalizedBar, ...], index: int, width: int) -> bool:
    if index - width < 0 or index + width >= len(bars):
        return False
    current = bars[index].low
    return all(current <= bars[probe].low for probe in range(index - width, index + width + 1) if probe != index)


def _find_anchor_index(definition: AnchorDefinition, bars: tuple[NormalizedBar, ...]) -> tuple[int | None, float | None, str | None]:
    width = max(1, definition.window)
    if definition.family == "manual_anchor":
        manual = definition if isinstance(definition, ManualAnchorDefinition) else ManualAnchorDefinition(**definition.__dict__)
        if manual.anchor_date is None or manual.anchor_value is None:
            return None, None, "manual_anchor_missing_inputs"
        for index, bar in enumerate(bars):
            if bar.session_date == manual.anchor_date:
                return index, manual.anchor_value, None
        return None, None, "manual_anchor_date_not_found"

    if definition.family == "swing_pivot_high":
        for index in range(len(bars) - width - 1, width - 1, -1):
            if _is_pivot_high(bars, index, width):
                return index, bars[index].high, None
        return None, None, "pivot_high_not_found"

    if definition.family == "swing_pivot_low":
        for index in range(len(bars) - width - 1, width - 1, -1):
            if _is_pivot_low(bars, index, width):
                return index, bars[index].low, None
        return None, None, "pivot_low_not_found"

    if definition.family == "gap_up_day":
        for index in range(len(bars) - 1, 0, -1):
            previous = bars[index - 1]
            current = bars[index]
            if previous.close and (current.open - previous.high) / previous.close >= definition.minimum_gap_pct:
                return index, current.open, None
        return None, None, "gap_up_day_not_found"

    if definition.family == "gap_down_day":
        for index in range(len(bars) - 1, 0, -1):
            previous = bars[index - 1]
            current = bars[index]
            if previous.close and (previous.low - current.open) / previous.close >= definition.minimum_gap_pct:
                return index, current.open, None
        return None, None, "gap_down_day_not_found"

    if definition.family == "breakout_pivot_day":
        lookback = max(2, definition.breakout_lookback)
        for index in range(len(bars) - 1, lookback - 1, -1):
            trailing_high = max(bar.high for bar in bars[index - lookback:index])
            if bars[index].close > trailing_high:
                return index, bars[index].close, None
        return None, None, "breakout_pivot_not_found"

    if definition.family == "breakdown_pivot_day":
        lookback = max(2, definition.breakout_lookback)
        for index in range(len(bars) - 1, lookback - 1, -1):
            trailing_low = min(bar.low for bar in bars[index - lookback:index])
            if bars[index].close < trailing_low:
                return index, bars[index].close, None
        return None, None, "breakdown_pivot_not_found"

    return None, None, "unsupported_anchor_family"


def resolve_anchor(
    *,
    symbol: str,
    bars: tuple[NormalizedBar, ...],
    definition: AnchorDefinition,
    config_fingerprint: str,
) -> ResolvedAnchor:
    definition = validate_anchor_definition(definition)
    anchor_id = build_anchor_id(
        symbol=symbol,
        anchor_name=definition.name,
        anchor_source=definition.family,
        config_fingerprint=config_fingerprint,
    )
    index, value, reason = _find_anchor_index(definition, bars)
    if index is None:
        provenance = AnchorProvenance(definition.family, definition.name, None, None, (reason or "anchor_not_found",))
        return ResolvedAnchor(
            anchor_id=anchor_id,
            name=definition.name,
            family=definition.family,
            status="inactive",
            data_status=DataSupportStatus.LOW_CONFIDENCE if bars else DataSupportStatus.MISSING,
            value=None,
            source=definition.family,
            is_daily_proxy=False,
            bar_index=None,
            provenance=provenance,
            avwap_proxy=None,
            reason=reason,
        )

    anchor_bar = bars[index]
    age = len(bars) - 1 - index
    stale = age > definition.stale_after_bars
    avwap = compute_daily_bar_avwap_proxy(bars, anchor_index=index)
    provenance = AnchorProvenance(
        source_family=definition.family,
        source_name=definition.name,
        source_date=anchor_bar.session_date,
        source_bar_index=index,
        notes=("daily_bar_proxy_avwap" if avwap.is_daily_proxy else "non_proxy",),
    )
    return ResolvedAnchor(
        anchor_id=anchor_id,
        name=definition.name,
        family=definition.family,
        status="stale" if stale else "active",
        data_status=DataSupportStatus.STALE if stale else DataSupportStatus.OK,
        value=value,
        source=definition.family,
        is_daily_proxy=avwap.is_daily_proxy,
        bar_index=index,
        provenance=provenance,
        avwap_proxy=avwap,
        reason=None,
    )


def resolve_anchors(
    *,
    symbol: str,
    bars: tuple[NormalizedBar, ...],
    definitions: tuple[AnchorDefinition, ...],
    config_fingerprint: str,
) -> tuple[ResolvedAnchor, ...]:
    resolved = [
        resolve_anchor(
            symbol=symbol,
            bars=bars,
            definition=definition,
            config_fingerprint=config_fingerprint,
        )
        for definition in sorted(definitions, key=lambda item: (item.family, item.name))
        if definition.enabled
    ]
    return tuple(resolved)
