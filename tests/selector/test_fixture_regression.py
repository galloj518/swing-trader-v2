from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from swingtrader_v2.domain.enums import ArtifactType, EnvironmentName
from swingtrader_v2.domain.ids import build_run_id
from swingtrader_v2.domain.models import ArtifactRef
from swingtrader_v2.packet.assembler import PacketAssemblyInput, assemble_packet
from swingtrader_v2.packet.completeness import assess_packet_completeness
from swingtrader_v2.selector.classifier import classify_candidates
from swingtrader_v2.selector.eligibility import INELIGIBLE, EligibilityInput, evaluate_eligibility
from swingtrader_v2.selector.prioritizer import prioritize_candidates, PrioritizationInput


UTC = ZoneInfo("UTC")


def _assembled_bundle(snapshot, candidate, *, as_of_date):
    run_id = build_run_id(
        as_of_date=as_of_date,
        environment=EnvironmentName.LOCAL.value,
        universe_name="liquid_us_equities",
        config_fingerprint="a" * 64,
    )
    assembled = assemble_packet(
        PacketAssemblyInput(
            candidate=candidate,
            bar_result=snapshot.bar_result,
            freshness=snapshot.freshness,
            moving_averages=snapshot.moving_averages,
            momentum=snapshot.momentum,
            volume=snapshot.volume,
            volatility=snapshot.volatility,
            patterns=snapshot.patterns,
            relative_strength=snapshot.relative_strength,
            anchors=snapshot.anchors,
            run_id=run_id,
            as_of_date=as_of_date,
            generated_at=datetime(2025, 9, 18, 21, 15, tzinfo=UTC),
            environment=EnvironmentName.LOCAL,
            config_fingerprint="a" * 64,
            artifact_lineage=(
                ArtifactRef(
                    artifact_type=ArtifactType.CANDIDATE_LIST,
                    artifact_id=f"cand_{candidate.symbol.lower()}_{candidate.family.value}",
                    schema_version="v1.0.0",
                ),
            ),
        )
    )
    return {
        "packet": assembled.payload,
        "trade_plan": assembled.trade_plan,
        "completeness": assess_packet_completeness(assembled.payload),
    }


def test_conflicting_fixture_resolves_primary_family_deterministically(scenario_library):
    snapshot = scenario_library.snapshot("conflicting_detector_symbol")
    classification = classify_candidates(snapshot.candidates, config=scenario_library._config.documents["setups"])

    assert classification.primary_family.value == "base_breakout"
    assert "multi_family_overlap" in classification.secondary_tags
    assert any(
        resolution.family.value == "avwap_reclaim" and resolution.decision == "secondary"
        for resolution in classification.resolutions
    )


def test_stale_and_split_fixture_candidates_fail_ordered_eligibility_gates(scenario_library):
    stale_snapshot = scenario_library.snapshot("stale_data_symbol")
    split_snapshot = scenario_library.snapshot("split_distorted_symbol")

    stale_candidate = stale_snapshot.candidates[0]
    split_candidate = split_snapshot.candidates[0]

    stale_bundle = _assembled_bundle(stale_snapshot, stale_candidate, as_of_date=scenario_library.as_of_date)
    split_bundle = _assembled_bundle(split_snapshot, split_candidate, as_of_date=scenario_library.as_of_date)

    stale_classification = classify_candidates((stale_candidate,), config=scenario_library._config.documents["setups"])
    split_classification = classify_candidates((split_candidate,), config=scenario_library._config.documents["setups"])

    stale_result = evaluate_eligibility(
        EligibilityInput(
            packet=stale_bundle["packet"],
            classification=stale_classification,
            trade_plan=stale_bundle["trade_plan"],
            completeness_state=stale_bundle["completeness"].state,
            instrument_context=stale_snapshot.metadata,
            corporate_actions=stale_snapshot.corporate_actions,
            config=scenario_library._config.documents["eligibility"],
        )
    )
    split_result = evaluate_eligibility(
        EligibilityInput(
            packet=split_bundle["packet"],
            classification=split_classification,
            trade_plan=split_bundle["trade_plan"],
            completeness_state=split_bundle["completeness"].state,
            instrument_context=split_snapshot.metadata,
            corporate_actions=split_snapshot.corporate_actions,
            config=scenario_library._config.documents["eligibility"],
        )
    )

    assert stale_result.outcome == INELIGIBLE
    assert stale_result.gate_results[1].gate_name == "freshness"
    assert stale_result.gate_results[1].outcome == "failed"
    assert split_result.outcome == INELIGIBLE
    assert split_result.gate_results[4].gate_name == "corporate_action_distortion"
    assert split_result.gate_results[4].outcome == "failed"


def test_clean_family_fixtures_keep_priority_logic_transparent_and_explicit(scenario_library):
    inputs = []
    for name in ("clean_trend_pullback", "clean_base_breakout", "clean_avwap_reclaim"):
        snapshot = scenario_library.snapshot(name)
        candidate = snapshot.candidates[0]
        bundle = _assembled_bundle(snapshot, candidate, as_of_date=scenario_library.as_of_date)
        classification = classify_candidates((candidate,), config=scenario_library._config.documents["setups"])
        eligibility = evaluate_eligibility(
            EligibilityInput(
                packet=bundle["packet"],
                classification=classification,
                trade_plan=bundle["trade_plan"],
                completeness_state=bundle["completeness"].state,
                instrument_context=snapshot.metadata,
                corporate_actions=snapshot.corporate_actions,
                config=scenario_library._config.documents["eligibility"],
            )
        )
        inputs.append(
            PrioritizationInput(
                packet=bundle["packet"],
                classification=classification,
                eligibility=eligibility,
                trade_plan=bundle["trade_plan"],
            )
        )

    plan = prioritize_candidates(tuple(inputs), config=scenario_library._config.documents["setups"])

    assert [item.primary_family.value for item in plan.ranked] == ["base_breakout", "avwap_reclaim"]
    assert plan.suppressed[0].symbol == "TRND"
    assert plan.suppressed[0].reason == "eligibility_ineligible"
    assert all("priority_band=" in " ".join(item.sort_key_explanations) for item in plan.ranked)
    assert all("family_rotation_slot=" in " ".join(item.sort_key_explanations) for item in plan.ranked)
