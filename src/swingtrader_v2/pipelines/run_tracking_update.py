"""Tracking orchestration over packets, selector state, and manual decisions."""

from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from swingtrader_v2.domain.enums import EnvironmentName
from swingtrader_v2.pipelines.common import (
    artifact_ref,
    build_run_context,
    deserialize_bar_result,
    history_store_to_payload,
    load_history_store,
    read_json,
    update_run_manifest,
    write_json,
)
from swingtrader_v2.tracking.decisions import ingest_manual_decisions
from swingtrader_v2.tracking.lifecycle import append_packet_lifecycle
from swingtrader_v2.tracking.outcomes import append_outcome_records, calculate_outcome_analysis


def _read_manual_rows(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def run_tracking_update(
    *,
    packet_bundle_path: str | Path,
    selector_state_path: str | Path,
    manual_decisions_path: str | Path | None = None,
    history_path: str | Path | None = None,
    as_of_date: date | None = None,
    environment: EnvironmentName = EnvironmentName.LOCAL,
    config_root: str | Path = "config",
    artifact_root: str | Path = "artifacts",
) -> dict[str, str]:
    packet_bundles = read_json(packet_bundle_path)["packet_bundles"]
    selector_state = {item["packet_id"]: item for item in read_json(selector_state_path)["selector_state"]}
    context = build_run_context(
        as_of_date=as_of_date or date.fromisoformat(packet_bundles[0]["packet"]["as_of_date"]),
        environment=environment,
        config_root=config_root,
        artifact_root=artifact_root,
    )
    history_target = Path(history_path) if history_path else context.artifact_root / "history" / "tracking_history.json"
    history_target.parent.mkdir(parents=True, exist_ok=True)
    store = load_history_store(history_target)

    for bundle in packet_bundles:
        packet = bundle["packet"]
        selector = selector_state.get(packet["packet_id"], {})
        store, _ = append_packet_lifecycle(
            store,
            packet=packet,
            classification=selector.get("classification"),
            eligibility_outcome=selector.get("eligibility_outcome"),
            review_context={"review_queue_position": selector["review_queue_position"]} if "review_queue_position" in selector else None,
            recorded_at=context.generated_at,
        )

    decision_events = []
    outcome_records = []
    manifest_outputs = []
    if manual_decisions_path:
        rows = _read_manual_rows(manual_decisions_path)
        store, ingestion = ingest_manual_decisions(store, manual_decisions_path)
        decision_events = list(ingestion.decision_events)
        rows_by_packet = {row["packet_id"]: row for row in rows}
        bundle_by_packet = {bundle["packet"]["packet_id"]: bundle for bundle in packet_bundles}
        for decision in decision_events:
            if decision["decision"]["action"] != "plan_trade":
                continue
            row = rows_by_packet.get(decision["packet_id"])
            if row is None or "entry_date" not in row or "entry_price" not in row:
                continue
            bundle = bundle_by_packet.get(decision["packet_id"])
            if bundle is None:
                continue
            analysis = calculate_outcome_analysis(
                bars=deserialize_bar_result(bundle["bar_result"]).bars,
                entry_date=date.fromisoformat(row["entry_date"]),
                entry_price=float(row["entry_price"]),
                invalidation_level=float(row["invalidation_level"]) if row.get("invalidation_level") else None,
                reference_high=float(row["reference_high"]) if row.get("reference_high") else None,
            )
            store, records = append_outcome_records(
                store,
                packet=bundle["packet"],
                decision_event=decision,
                analysis=analysis,
                recorded_at=datetime.now(timezone.utc),
            )
            outcome_records.extend(records)
        decision_path = write_json(context.tracking_dir / "decision_events.json", {"decision_events": decision_events})
        outcome_path = write_json(context.tracking_dir / "outcome_records.json", {"outcome_records": outcome_records})
        manifest_outputs.append(artifact_ref("decision_event", str(decision_path.relative_to(context.run_root))))
        if outcome_records:
            manifest_outputs.append(artifact_ref("outcome_record", str(outcome_path.relative_to(context.run_root))))

    history_path_written = write_json(history_target, history_store_to_payload(store))
    snapshot_path = write_json(context.tracking_dir / "tracking_history_snapshot.json", history_store_to_payload(store))
    if manifest_outputs:
        update_run_manifest(context, manifest_outputs)
    return {
        "run_root": str(context.run_root),
        "history_path": str(history_path_written),
        "run_tracking_snapshot_path": str(snapshot_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Update append-only tracking history.")
    parser.add_argument("--packet-bundles", required=True)
    parser.add_argument("--selector-state", required=True)
    parser.add_argument("--manual-decisions")
    parser.add_argument("--history-path")
    parser.add_argument("--as-of-date")
    parser.add_argument("--environment", default="local", choices=[item.value for item in EnvironmentName])
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--artifact-root", default="artifacts")
    args = parser.parse_args()
    result = run_tracking_update(
        packet_bundle_path=args.packet_bundles,
        selector_state_path=args.selector_state,
        manual_decisions_path=args.manual_decisions,
        history_path=args.history_path,
        as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        environment=EnvironmentName(args.environment),
        config_root=args.config_root,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
