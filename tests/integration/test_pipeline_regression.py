from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from swingtrader_v2.pipelines.common import read_json
from swingtrader_v2.pipelines.run_daily_scan import run_daily_scan
from swingtrader_v2.pipelines.run_dashboard import run_dashboard
from swingtrader_v2.pipelines.run_packet_build import run_packet_build
from swingtrader_v2.pipelines.run_rankings import run_rankings
from swingtrader_v2.pipelines.run_tracking_update import run_tracking_update


GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "final_pipeline"


def _write_manual_decisions(path: Path, packet_bundles: list[dict]) -> Path:
    trend_bundle = next(
        bundle
        for bundle in packet_bundles
        if bundle["packet"]["symbol"] == "TRND" and bundle["packet"]["setup"]["family"] == "trend_pullback"
    )
    bars = trend_bundle["bar_result"]["bars"]
    entry_bar = bars[-21]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "packet_id",
            "run_id",
            "as_of_date",
            "environment",
            "recorded_at",
            "action",
            "rationale",
            "tags",
            "symbol",
            "setup_family",
            "entry_date",
            "entry_price",
            "invalidation_level",
            "reference_high",
        ],
    )
    writer.writeheader()
    writer.writerow(
        {
            "packet_id": trend_bundle["packet"]["packet_id"],
            "run_id": trend_bundle["packet"]["run_id"],
            "as_of_date": trend_bundle["packet"]["as_of_date"],
            "environment": trend_bundle["packet"]["environment"],
            "recorded_at": "2025-09-18T21:30:00Z",
            "action": "plan_trade",
            "rationale": "Fixture regression tracking coverage",
            "tags": "golden|manual",
            "symbol": trend_bundle["packet"]["symbol"],
            "setup_family": trend_bundle["packet"]["setup"]["family"],
            "entry_date": entry_bar["session_date"],
            "entry_price": entry_bar["close"],
            "invalidation_level": trend_bundle["trade_plan"]["invalidation_level"],
            "reference_high": entry_bar["high"],
        }
    )
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return path


def _run_pipeline_chain(pipeline_fixture_bundle, freeze_pipeline_time) -> dict[str, object]:
    freeze_pipeline_time()
    scan_result = run_daily_scan(
        symbol_metadata_path=pipeline_fixture_bundle["metadata_path"],
        bars_input_path=pipeline_fixture_bundle["bars_path"],
        as_of_date=None,
        artifact_root=pipeline_fixture_bundle["artifact_root"],
    )
    packet_result = run_packet_build(
        scan_state_path=scan_result["scan_state_path"],
        artifact_root=pipeline_fixture_bundle["artifact_root"],
    )
    packet_bundle_payload = read_json(packet_result["packet_bundle_path"])
    manual_decisions_path = _write_manual_decisions(
        pipeline_fixture_bundle["root"] / "inputs" / "manual_decisions.csv",
        packet_bundle_payload["packet_bundles"],
    )
    ranking_result = run_rankings(
        packet_bundle_path=packet_result["packet_bundle_path"],
        artifact_root=pipeline_fixture_bundle["artifact_root"],
    )
    run_root = Path(ranking_result["run_root"])
    manifest_path = run_root / "manifests" / "run_manifest.json"
    dashboard_result = run_dashboard(
        ranking_path=ranking_result["ranking_path"],
        run_manifest_path=manifest_path,
        packets_dir=run_root / "packets",
        artifact_root=pipeline_fixture_bundle["artifact_root"],
    )
    tracking_result = run_tracking_update(
        packet_bundle_path=packet_result["packet_bundle_path"],
        selector_state_path=ranking_result["selector_state_path"],
        manual_decisions_path=manual_decisions_path,
        history_path=pipeline_fixture_bundle["history_path"],
        artifact_root=pipeline_fixture_bundle["artifact_root"],
    )
    return {
        "run_root": run_root,
        "scan_result": scan_result,
        "packet_result": packet_result,
        "ranking_result": ranking_result,
        "dashboard_result": dashboard_result,
        "tracking_result": tracking_result,
    }


def _artifact_map(run_root: Path) -> dict[str, object]:
    return {
        "candidate_list_avwap_reclaim.json": read_json(run_root / "scan" / "candidate_list_avwap_reclaim.json"),
        "candidate_list_base_breakout.json": read_json(run_root / "scan" / "candidate_list_base_breakout.json"),
        "candidate_list_trend_pullback.json": read_json(run_root / "scan" / "candidate_list_trend_pullback.json"),
        "scanner_rejections.json": read_json(run_root / "scan" / "scanner_rejections.json"),
        "packet_bundles.json": read_json(run_root / "packets" / "packet_bundles.json"),
        "run_manifest.json": read_json(run_root / "manifests" / "run_manifest.json"),
        "ranking.json": read_json(run_root / "rankings" / "ranking.json"),
        "selector_state.json": read_json(run_root / "rankings" / "selector_state.json"),
        "dashboard_payload.json": read_json(run_root / "dashboard" / "dashboard_payload.json"),
        "dashboard.html": (run_root / "dashboard" / "dashboard.html").read_text(encoding="utf-8"),
        "tracking_history_snapshot.json": read_json(run_root / "tracking" / "tracking_history_snapshot.json"),
    }


def _workspace_bundle(root: Path, scenario_library) -> dict[str, object]:
    metadata_path, bars_path = scenario_library.write_pipeline_inputs(root / "inputs")
    return {
        "root": root,
        "metadata_path": metadata_path,
        "bars_path": bars_path,
        "artifact_root": root / "artifacts",
        "history_path": root / "history" / "tracking_history.json",
    }


def test_pipeline_chain_is_deterministic_for_offline_fixture_run(workspace_tmp_root, scenario_library, freeze_pipeline_time):
    first_bundle = _workspace_bundle(workspace_tmp_root / "first", scenario_library)
    second_bundle = _workspace_bundle(workspace_tmp_root / "second", scenario_library)

    first_run = _run_pipeline_chain(first_bundle, freeze_pipeline_time)
    second_run = _run_pipeline_chain(second_bundle, freeze_pipeline_time)

    assert _artifact_map(first_run["run_root"]) == _artifact_map(second_run["run_root"])


def test_pipeline_chain_matches_checked_in_golden_artifacts(pipeline_fixture_bundle, freeze_pipeline_time):
    run = _run_pipeline_chain(pipeline_fixture_bundle, freeze_pipeline_time)
    artifacts = _artifact_map(run["run_root"])

    for filename, actual in artifacts.items():
        golden_path = GOLDEN_ROOT / filename
        assert golden_path.exists(), f"Missing golden artifact: {golden_path}"
        if filename.endswith(".html"):
            expected = golden_path.read_text(encoding="utf-8")
        else:
            expected = json.loads(golden_path.read_text(encoding="utf-8"))
        assert actual == expected


def test_pipeline_outputs_preserve_replayable_tracking_inputs(pipeline_fixture_bundle, freeze_pipeline_time):
    run = _run_pipeline_chain(pipeline_fixture_bundle, freeze_pipeline_time)
    artifacts = _artifact_map(run["run_root"])
    packet_bundles = artifacts["packet_bundles.json"]["packet_bundles"]
    tracking_history = artifacts["tracking_history_snapshot.json"]["records"]

    assert any(bundle["packet"]["symbol"] == "TRND" for bundle in packet_bundles)
    assert all("raw_snapshot" in bundle["packet"] for bundle in packet_bundles)
    assert all("trade_plan" in bundle for bundle in packet_bundles)
    assert all("bar_result" in bundle for bundle in packet_bundles)
    assert any(record["payload"]["event_type"] == "outcome_recorded" for record in tracking_history if record["record_type"] == "lifecycle")
    assert all(record["entity_id"].startswith("pkt_") for record in tracking_history)
