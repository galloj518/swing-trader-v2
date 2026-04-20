"""Transparent lexicographic prioritization for eligible selector inputs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from swingtrader_v2.domain.enums import SetupFamily
from swingtrader_v2.packet.trade_plan import TradePlanScaffold
from swingtrader_v2.selector.classifier import ClassificationResult
from swingtrader_v2.selector.eligibility import ELIGIBLE, WARNING_ONLY, EligibilityResult


P1_ACTIONABLE_NOW = "P1_ACTIONABLE_NOW"
P2_NEAR_ACTIONABLE = "P2_NEAR_ACTIONABLE"
P3_MONITOR = "P3_MONITOR"
P4_INFORMATIONAL = "P4_INFORMATIONAL"

DEFAULT_SETUP_PRIORITIES: dict[SetupFamily, int] = {
    SetupFamily.TREND_PULLBACK: 1,
    SetupFamily.BASE_BREAKOUT: 2,
    SetupFamily.AVWAP_RECLAIM: 3,
}
PRIORITY_BAND_ORDER = {
    P1_ACTIONABLE_NOW: 1,
    P2_NEAR_ACTIONABLE: 2,
    P3_MONITOR: 3,
    P4_INFORMATIONAL: 4,
}
ACTIONABILITY_ORDER = {
    "ready": 1,
    "review": 2,
    "watch": 3,
    "blocked": 4,
}


@dataclass(frozen=True)
class PrioritizationInput:
    packet: dict
    classification: ClassificationResult
    eligibility: EligibilityResult
    trade_plan: TradePlanScaffold


@dataclass(frozen=True)
class PrioritizedCandidate:
    symbol: str
    primary_family: SetupFamily
    priority_band: str
    family_rank: int
    review_queue_position: int
    sort_key_explanations: tuple[str, ...]


@dataclass(frozen=True)
class SuppressedCandidate:
    symbol: str
    reason: str


@dataclass(frozen=True)
class PrioritizationPlan:
    ranked: tuple[PrioritizedCandidate, ...]
    suppressed: tuple[SuppressedCandidate, ...]


def _setup_priorities(config: dict | None = None) -> dict[SetupFamily, int]:
    if not config:
        return dict(DEFAULT_SETUP_PRIORITIES)
    priorities: dict[SetupFamily, int] = {}
    for item in config.get("setup_families", ()):
        try:
            family = SetupFamily(item["name"])
        except Exception:
            continue
        priorities[family] = int(item.get("priority_order", DEFAULT_SETUP_PRIORITIES[family]))
    return priorities or dict(DEFAULT_SETUP_PRIORITIES)


def _close(packet: dict) -> float:
    return float(packet["raw_snapshot"]["price_bar"]["close"])


def _distance_to_trigger(packet: dict, trade_plan: TradePlanScaffold) -> float:
    if trade_plan.trigger_level in (None, 0):
        return float("inf")
    return abs(_close(packet) - float(trade_plan.trigger_level)) / abs(float(trade_plan.trigger_level))


def _priority_band(input_data: PrioritizationInput) -> str:
    if input_data.eligibility.outcome == ELIGIBLE and input_data.trade_plan.actionability_state == "ready":
        if _distance_to_trigger(input_data.packet, input_data.trade_plan) <= 0.01:
            return P1_ACTIONABLE_NOW
        return P2_NEAR_ACTIONABLE
    if input_data.eligibility.outcome == ELIGIBLE:
        return P2_NEAR_ACTIONABLE if _distance_to_trigger(input_data.packet, input_data.trade_plan) <= 0.03 else P3_MONITOR
    if input_data.eligibility.outcome == WARNING_ONLY:
        return P3_MONITOR if input_data.trade_plan.actionability_state != "blocked" else P4_INFORMATIONAL
    return P4_INFORMATIONAL


def _family_sort_key(input_data: PrioritizationInput, band: str):
    primary = input_data.classification.primary_candidate
    return (
        PRIORITY_BAND_ORDER[band],
        ACTIONABILITY_ORDER.get(input_data.trade_plan.actionability_state, 99),
        _distance_to_trigger(input_data.packet, input_data.trade_plan),
        -(primary.evidence_count if primary is not None else 0),
        -(primary.excess_return_63d if primary is not None and primary.excess_return_63d is not None else float("-inf")),
        -float(input_data.packet["raw_snapshot"]["liquidity"]["avg_daily_dollar_volume_20d"]),
        input_data.packet["symbol"],
    )


def _sort_key_explanations(input_data: PrioritizationInput, band: str, family_rank: int) -> tuple[str, ...]:
    primary = input_data.classification.primary_candidate
    return (
        f"priority_band={band}",
        f"family_rank={family_rank}",
        f"actionability_state={input_data.trade_plan.actionability_state}",
        f"trigger_distance={_distance_to_trigger(input_data.packet, input_data.trade_plan):.6f}",
        f"evidence_count={primary.evidence_count if primary is not None else 0}",
        f"excess_return_63d={primary.excess_return_63d if primary is not None else None}",
        f"avg_daily_dollar_volume_20d={input_data.packet['raw_snapshot']['liquidity']['avg_daily_dollar_volume_20d']}",
        f"symbol={input_data.packet['symbol']}",
    )


def prioritize_candidates(
    inputs: tuple[PrioritizationInput, ...],
    *,
    config: dict | None = None,
) -> PrioritizationPlan:
    priorities = _setup_priorities(config)
    ranked_inputs: list[tuple[SetupFamily, str, PrioritizationInput]] = []
    suppressed: list[SuppressedCandidate] = []

    for input_data in inputs:
        family = input_data.classification.primary_family
        if family is None:
            suppressed.append(SuppressedCandidate(symbol=input_data.packet["symbol"], reason="primary_family_unresolved"))
            continue
        if input_data.eligibility.outcome not in {ELIGIBLE, WARNING_ONLY}:
            suppressed.append(SuppressedCandidate(symbol=input_data.packet["symbol"], reason=f"eligibility_{input_data.eligibility.outcome}"))
            continue
        ranked_inputs.append((family, _priority_band(input_data), input_data))

    family_buckets: dict[SetupFamily, list[tuple[str, PrioritizationInput]]] = defaultdict(list)
    for family, band, input_data in ranked_inputs:
        family_buckets[family].append((band, input_data))

    ordered_families = sorted(priorities, key=lambda family: priorities[family])
    ranked_by_family: dict[SetupFamily, list[PrioritizedCandidate]] = {}
    for family in ordered_families:
        bucket = family_buckets.get(family, [])
        bucket.sort(key=lambda item: _family_sort_key(item[1], item[0]))
        ranked_by_family[family] = [
            PrioritizedCandidate(
                symbol=input_data.packet["symbol"],
                primary_family=family,
                priority_band=band,
                family_rank=index + 1,
                review_queue_position=0,
                sort_key_explanations=_sort_key_explanations(input_data, band, index + 1),
            )
            for index, (band, input_data) in enumerate(bucket)
        ]

    queue: list[PrioritizedCandidate] = []
    rotation_index = 0
    while any(ranked_by_family.get(family) for family in ordered_families):
        for family in ordered_families:
            bucket = ranked_by_family.get(family, [])
            if not bucket:
                continue
            candidate = bucket.pop(0)
            rotation_index += 1
            queue.append(
                PrioritizedCandidate(
                    symbol=candidate.symbol,
                    primary_family=candidate.primary_family,
                    priority_band=candidate.priority_band,
                    family_rank=candidate.family_rank,
                    review_queue_position=rotation_index,
                    sort_key_explanations=tuple(
                        dict.fromkeys((*candidate.sort_key_explanations, f"family_rotation_slot={rotation_index}"))
                    ),
                )
            )

    return PrioritizationPlan(ranked=tuple(queue), suppressed=tuple(suppressed))
