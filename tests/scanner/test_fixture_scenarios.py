from __future__ import annotations

from swingtrader_v2.domain.enums import DataSupportStatus


def _detected_families(snapshot) -> set[str]:
    return {result.family.value for result in snapshot.detector_results if result.detected}


def _rejection_map(snapshot) -> dict[str, tuple[str, ...]]:
    return {result.family.value: result.rejection_reasons for result in snapshot.detector_results}


def test_required_fixture_scenarios_are_present(scenario_library):
    assert set(scenario_library.names) == {
        "clean_trend_pullback",
        "clean_base_breakout",
        "clean_avwap_reclaim",
        "stale_data_symbol",
        "split_distorted_symbol",
        "insufficient_history_symbol",
        "conflicting_detector_symbol",
    }


def test_clean_supported_family_fixtures_route_to_expected_detectors(scenario_library):
    assert _detected_families(scenario_library.snapshot("clean_trend_pullback")) == {"trend_pullback"}
    assert _detected_families(scenario_library.snapshot("clean_base_breakout")) == {"base_breakout"}
    assert _detected_families(scenario_library.snapshot("clean_avwap_reclaim")) == {"avwap_reclaim"}


def test_failure_mode_fixtures_keep_reason_codes_explicit(scenario_library):
    stale = scenario_library.snapshot("stale_data_symbol")
    insufficient = scenario_library.snapshot("insufficient_history_symbol")
    conflicting = scenario_library.snapshot("conflicting_detector_symbol")

    assert stale.freshness.status is DataSupportStatus.STALE
    assert "stale_expected_session" in stale.freshness.reason_codes
    assert "long_trend_mas_unavailable" in _rejection_map(insufficient)["trend_pullback"]
    assert "active_anchor_missing" in _rejection_map(insufficient)["avwap_reclaim"]
    assert _detected_families(conflicting) == {"avwap_reclaim", "base_breakout"}


def test_split_distorted_fixture_preserves_explicit_split_action(scenario_library):
    split = scenario_library.snapshot("split_distorted_symbol")
    assert len(split.corporate_actions) == 1
    assert split.corporate_actions[0].action_type == "split"
    assert split.corporate_actions[0].value == 2.0
