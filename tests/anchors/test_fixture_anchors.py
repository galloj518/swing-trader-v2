from __future__ import annotations


def test_clean_avwap_fixture_has_active_daily_proxy_anchor_with_provenance(scenario_library):
    snapshot = scenario_library.snapshot("clean_avwap_reclaim")
    active = [anchor for anchor in snapshot.anchors if anchor.status == "active" and anchor.avwap_proxy is not None]

    assert active
    assert all(anchor.is_daily_proxy is True for anchor in active)
    assert all(anchor.provenance.source_date is not None for anchor in active)
    assert all("daily_bar_proxy_avwap" in anchor.provenance.notes for anchor in active)


def test_anchor_resolution_is_deterministic_for_conflicting_fixture(scenario_library):
    first = scenario_library.snapshot("conflicting_detector_symbol").anchors
    second = scenario_library.snapshot("conflicting_detector_symbol").anchors

    assert first == second
