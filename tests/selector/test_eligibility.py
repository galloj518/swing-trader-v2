from __future__ import annotations

from copy import deepcopy

from swingtrader_v2.selector.eligibility import ELIGIBLE, INELIGIBLE, WARNING_ONLY, GATE_SEQUENCE, EligibilityInput, evaluate_eligibility

from ._helpers import (
    build_classification,
    build_instrument_context,
    build_packet_bundle,
    build_portfolio_snapshot,
    build_recent_dividend,
    build_recent_split,
)


def test_eligibility_runs_gates_in_order_and_flags_warning_only_for_portfolio_overlap():
    bundle = build_packet_bundle()
    classification = build_classification(bundle["candidate"])

    result = evaluate_eligibility(
        EligibilityInput(
            packet=bundle["packet"],
            classification=classification,
            trade_plan=bundle["trade_plan"],
            completeness_state=bundle["completeness"].state,
            instrument_context=build_instrument_context(),
            portfolio_snapshot=build_portfolio_snapshot("AAPL"),
        )
    )

    assert [gate.gate_name for gate in result.gate_results] == list(GATE_SEQUENCE)
    assert result.outcome == WARNING_ONLY
    assert result.gate_results[-1].outcome == "warning"


def test_eligibility_blocks_stale_or_distorted_inputs_before_prioritization():
    bundle = build_packet_bundle()
    packet = deepcopy(bundle["packet"])
    packet["raw_snapshot"]["snapshot_status"] = "stale"
    packet["raw_snapshot"]["coverage"]["staleness_days"] = 1
    classification = build_classification(bundle["candidate"])

    result = evaluate_eligibility(
        EligibilityInput(
            packet=packet,
            classification=classification,
            trade_plan=bundle["trade_plan"],
            completeness_state=bundle["completeness"].state,
            instrument_context=build_instrument_context(),
            corporate_actions=build_recent_split(),
        )
    )

    assert result.outcome == INELIGIBLE
    assert result.gate_results[1].gate_name == "freshness"
    assert result.gate_results[1].outcome == "failed"
    assert result.gate_results[4].gate_name == "corporate_action_distortion"
    assert result.gate_results[4].outcome == "failed"


def test_eligibility_passes_clean_packet_and_tags_recent_dividend_as_warning():
    bundle = build_packet_bundle()
    classification = build_classification(bundle["candidate"])

    clean = evaluate_eligibility(
        EligibilityInput(
            packet=bundle["packet"],
            classification=classification,
            trade_plan=bundle["trade_plan"],
            completeness_state=bundle["completeness"].state,
            instrument_context=build_instrument_context(),
        )
    )
    assert clean.outcome == ELIGIBLE

    dividend_warning = evaluate_eligibility(
        EligibilityInput(
            packet=bundle["packet"],
            classification=classification,
            trade_plan=bundle["trade_plan"],
            completeness_state=bundle["completeness"].state,
            instrument_context=build_instrument_context(),
            corporate_actions=build_recent_dividend(),
        )
    )
    assert dividend_warning.outcome == WARNING_ONLY
