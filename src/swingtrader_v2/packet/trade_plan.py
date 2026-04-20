"""Structured discretionary trade-plan scaffolds for packet review.

This module remains descriptive only. It does not size positions, automate
execution, or decide whether a setup is eligible or should be ranked.
"""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.analysis.moving_averages import MovingAverageFeatureSet
from swingtrader_v2.analysis.patterns import PatternFeatureSet
from swingtrader_v2.anchors.resolver import ResolvedAnchor
from swingtrader_v2.domain.enums import DataSupportStatus, SetupFamily
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate


@dataclass(frozen=True)
class TradeChecklistItem:
    name: str
    status: str
    note: str | None = None


@dataclass(frozen=True)
class TradePlanScaffold:
    actionability_state: str
    trigger_level: float | None
    invalidation_level: float | None
    nearest_support: float | None
    nearest_overhead: float | None
    checklist_items: tuple[TradeChecklistItem, ...]
    structural_notes: tuple[str, ...]

    def to_summary(self) -> str:
        trigger = f"{self.trigger_level:.2f}" if self.trigger_level is not None else "n/a"
        invalidation = f"{self.invalidation_level:.2f}" if self.invalidation_level is not None else "n/a"
        support = f"{self.nearest_support:.2f}" if self.nearest_support is not None else "n/a"
        overhead = f"{self.nearest_overhead:.2f}" if self.nearest_overhead is not None else "n/a"
        notes = "; ".join(self.structural_notes) if self.structural_notes else "no structural notes"
        return (
            f"Actionability={self.actionability_state}; "
            f"trigger={trigger}; invalidation={invalidation}; "
            f"support={support}; overhead={overhead}; {notes}"
        )


def _ma_value(moving_averages: MovingAverageFeatureSet, name: str) -> float | None:
    for metric in moving_averages.values:
        if metric.name == name:
            return metric.value
    return None


def _pattern_value(patterns: PatternFeatureSet, name: str) -> float | None:
    for metric in patterns.metrics:
        if metric.name == name:
            return metric.value
    return None


def _level_candidates(
    *,
    close: float | None,
    moving_averages: MovingAverageFeatureSet,
    patterns: PatternFeatureSet,
    anchors: tuple[ResolvedAnchor, ...],
) -> tuple[list[float], list[float], tuple[str, ...]]:
    support_levels: list[float] = []
    overhead_levels: list[float] = []
    notes: list[str] = []
    if close is None:
        return support_levels, overhead_levels, ("latest_close_missing",)

    for name in ("ema21", "sma50", "sma100", "sma200"):
        level = _ma_value(moving_averages, name)
        if level is None:
            continue
        if level <= close:
            support_levels.append(level)
        else:
            overhead_levels.append(level)

    pivot = _pattern_value(patterns, "pivot_price")
    if pivot is not None:
        if pivot <= close:
            support_levels.append(pivot)
        else:
            overhead_levels.append(pivot)

    for anchor in anchors:
        if anchor.value is not None:
            if anchor.value <= close:
                support_levels.append(anchor.value)
            else:
                overhead_levels.append(anchor.value)
        if anchor.avwap_proxy and anchor.avwap_proxy.current_avwap is not None:
            avwap = anchor.avwap_proxy.current_avwap
            if avwap <= close:
                support_levels.append(avwap)
            else:
                overhead_levels.append(avwap)
            notes.append(f"{anchor.name} uses daily-bar AVWAP proxy")
        elif anchor.data_status is not DataSupportStatus.OK:
            notes.append(f"{anchor.name} anchor status={anchor.data_status.value}")

    return support_levels, overhead_levels, tuple(dict.fromkeys(notes))


def _nearest_support(levels: list[float], close: float | None) -> float | None:
    if close is None:
        return None
    below = [level for level in levels if level <= close]
    return max(below) if below else None


def _nearest_overhead(levels: list[float], close: float | None) -> float | None:
    if close is None:
        return None
    above = [level for level in levels if level >= close]
    return min(above) if above else None


def build_trade_plan_scaffold(
    *,
    candidate: ScannerCandidate,
    close: float | None,
    moving_averages: MovingAverageFeatureSet,
    patterns: PatternFeatureSet,
    anchors: tuple[ResolvedAnchor, ...],
) -> TradePlanScaffold:
    support_levels, overhead_levels, notes = _level_candidates(
        close=close,
        moving_averages=moving_averages,
        patterns=patterns,
        anchors=anchors,
    )
    nearest_support = _nearest_support(support_levels, close)
    nearest_overhead = _nearest_overhead(overhead_levels, close)

    pivot = _pattern_value(patterns, "pivot_price")
    active_avwap = next(
        (
            anchor.avwap_proxy.current_avwap
            for anchor in anchors
            if anchor.status == "active" and anchor.avwap_proxy and anchor.avwap_proxy.current_avwap is not None
        ),
        None,
    )

    trigger_level = close
    invalidation_level = nearest_support
    if candidate.family is SetupFamily.BASE_BREAKOUT:
        trigger_level = pivot if pivot is not None else close
    elif candidate.family is SetupFamily.AVWAP_RECLAIM:
        trigger_level = active_avwap if active_avwap is not None else close
        invalidation_level = active_avwap if active_avwap is not None else nearest_support

    if close is None:
        actionability_state = "blocked"
    elif trigger_level is None or invalidation_level is None:
        actionability_state = "watch"
    elif candidate.classification_status is DataSupportStatus.OK:
        actionability_state = "ready"
    else:
        actionability_state = "review"

    checklist_items = (
        TradeChecklistItem(
            name="scanner_context_present",
            status="ready" if candidate.evidence else "needs_review",
            note=", ".join(candidate.evidence) if candidate.evidence else "scanner evidence missing",
        ),
        TradeChecklistItem(
            name="levels_defined",
            status="ready" if trigger_level is not None and invalidation_level is not None else "needs_review",
            note=None if trigger_level is not None and invalidation_level is not None else "trigger or invalidation unavailable",
        ),
        TradeChecklistItem(
            name="support_context_present",
            status="ready" if nearest_support is not None else "needs_review",
            note=None if nearest_support is not None else "nearest support not resolved",
        ),
        TradeChecklistItem(
            name="overhead_context_present",
            status="ready" if nearest_overhead is not None else "needs_review",
            note=None if nearest_overhead is not None else "nearest overhead not resolved",
        ),
    )

    structural_notes = tuple(
        dict.fromkeys(
            (
                f"family={candidate.family.value}",
                *[f"evidence:{item}" for item in candidate.evidence],
                *notes,
            )
        )
    )
    return TradePlanScaffold(
        actionability_state=actionability_state,
        trigger_level=trigger_level,
        invalidation_level=invalidation_level,
        nearest_support=nearest_support,
        nearest_overhead=nearest_overhead,
        checklist_items=checklist_items,
        structural_notes=structural_notes,
    )
