from __future__ import annotations

from swingtrader_v2.domain.enums import SetupFamily
from swingtrader_v2.selector.classifier import classify_candidates
from swingtrader_v2.selector.eligibility import EligibilityInput, evaluate_eligibility
from swingtrader_v2.selector.prioritizer import (
    P1_ACTIONABLE_NOW,
    PrioritizationInput,
    prioritize_candidates,
)

from ._helpers import build_instrument_context, build_packet_bundle


def _selector_input(bundle):
    classification = classify_candidates((bundle["candidate"],))
    eligibility = evaluate_eligibility(
        EligibilityInput(
            packet=bundle["packet"],
            classification=classification,
            trade_plan=bundle["trade_plan"],
            completeness_state=bundle["completeness"].state,
            instrument_context=build_instrument_context(),
        )
    )
    return PrioritizationInput(
        packet=bundle["packet"],
        classification=classification,
        eligibility=eligibility,
        trade_plan=bundle["trade_plan"],
    )


def test_prioritizer_ranks_within_family_before_family_rotation():
    trend_a = build_packet_bundle(symbol="AAPL", family=SetupFamily.TREND_PULLBACK, evidence=("a", "b", "c"), evidence_count=3, excess_return_63d=0.20)
    trend_b = build_packet_bundle(symbol="MSFT", family=SetupFamily.TREND_PULLBACK, evidence=("a", "b"), evidence_count=2, excess_return_63d=0.15)
    breakout = build_packet_bundle(symbol="NVDA", family=SetupFamily.BASE_BREAKOUT, evidence=("a", "b", "c"), evidence_count=3, excess_return_63d=0.19)

    plan = prioritize_candidates((_selector_input(trend_a), _selector_input(trend_b), _selector_input(breakout)))

    assert [item.symbol for item in plan.ranked] == ["AAPL", "NVDA", "MSFT"]
    assert all("family_rotation_slot=" in " ".join(item.sort_key_explanations) for item in plan.ranked)
    assert plan.ranked[0].family_rank == 1
    assert plan.ranked[2].family_rank == 2


def test_prioritizer_assigns_actionable_band_and_suppresses_ineligible_packets():
    avwap = build_packet_bundle(symbol="AMD", family=SetupFamily.AVWAP_RECLAIM, evidence=("a", "b", "c"), evidence_count=3)
    avwap["packet"]["raw_snapshot"]["price_bar"]["close"] = float(avwap["trade_plan"].trigger_level)

    stale = build_packet_bundle(symbol="TSLA", family=SetupFamily.BASE_BREAKOUT, evidence=("a", "b"), evidence_count=2)
    stale["packet"]["raw_snapshot"]["snapshot_status"] = "stale"
    stale["packet"]["raw_snapshot"]["coverage"]["staleness_days"] = 2

    plan = prioritize_candidates((_selector_input(avwap), _selector_input(stale)))

    assert plan.ranked[0].symbol == "AMD"
    assert plan.ranked[0].priority_band == P1_ACTIONABLE_NOW
    assert plan.suppressed[0].symbol == "TSLA"
    assert plan.suppressed[0].reason == "eligibility_ineligible"
