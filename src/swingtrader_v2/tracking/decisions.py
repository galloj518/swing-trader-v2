"""Explicit manual decision ingestion and append-only storage."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from swingtrader_v2.tracking.history_store import AppendOnlyHistoryStore, HistoryRecord
from swingtrader_v2.tracking.lifecycle import append_lifecycle_event


DECISION_SCHEMA_VERSION = "v1.0.0"
ALLOWED_ACTIONS = {"watch", "pass", "plan_trade", "invalidated"}


@dataclass(frozen=True)
class DecisionIngestionResult:
    decision_events: tuple[dict[str, Any], ...]
    lifecycle_records: tuple[HistoryRecord, ...]


def _decision_id(packet_id: str, action: str, recorded_at: str, rationale: str) -> str:
    payload = json.dumps(
        {
            "packet_id": packet_id,
            "action": action,
            "recorded_at": recorded_at,
            "rationale": rationale,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"dec_{packet_id.split('_', 1)[1]}_{digest}"


def _normalize_tags(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw)
    delimiter = "|" if "|" in text else ","
    return [item.strip() for item in text.split(delimiter) if item.strip()]


def _read_manual_rows(payload: str | Path | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, Path) or (isinstance(payload, str) and Path(payload).exists()):
        path = Path(payload)
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
    elif isinstance(payload, str):
        text = payload
        suffix = ".csv" if "," in text.partition("\n")[0] else ".jsonl"
    else:
        return [dict(item) for item in payload]

    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _normalize_recorded_at(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_decision_event(row: dict[str, Any]) -> dict[str, Any]:
    action = str(row["action"]).strip()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported manual decision action '{action}'.")
    rationale = str(row["rationale"]).strip()
    if not rationale:
        raise ValueError("Manual decision rationale is required.")
    recorded_at = _normalize_recorded_at(row.get("recorded_at"))
    packet_id = str(row["packet_id"]).strip()
    return {
        "artifact_type": "decision_event",
        "schema_version": DECISION_SCHEMA_VERSION,
        "decision_event_id": _decision_id(packet_id, action, recorded_at, rationale),
        "packet_id": packet_id,
        "run_id": str(row["run_id"]).strip(),
        "recorded_at": recorded_at,
        "as_of_date": str(row["as_of_date"]).strip(),
        "environment": str(row["environment"]).strip(),
        "decision": {
            "action": action,
            "rationale": rationale,
            "tags": _normalize_tags(row.get("tags")),
        },
    }


def ingest_manual_decisions(
    store: AppendOnlyHistoryStore,
    payload: str | Path | Iterable[dict[str, Any]],
) -> tuple[AppendOnlyHistoryStore, DecisionIngestionResult]:
    current = store
    decision_events: list[dict[str, Any]] = []
    lifecycle_records: list[HistoryRecord] = []

    for row in _read_manual_rows(payload):
        event = build_decision_event(row)
        current, _ = current.append(
            record_type="decision",
            entity_id=event["packet_id"],
            payload=event,
            recorded_at=datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00")),
        )
        decision_events.append(event)

        if event["decision"]["action"] == "plan_trade":
            lifecycle_event = "entered_manual"
        elif event["decision"]["action"] == "pass":
            lifecycle_event = "exited_manual"
        elif event["decision"]["action"] == "invalidated":
            lifecycle_event = "invalidated"
        else:
            lifecycle_event = None

        if lifecycle_event is not None:
            current, lifecycle_record = append_lifecycle_event(
                current,
                packet_id=event["packet_id"],
                run_id=event["run_id"],
                as_of_date=event["as_of_date"],
                symbol=str(row.get("symbol", "UNKNOWN")).upper(),
                setup_family=str(row.get("setup_family", "unknown")),
                event_type=lifecycle_event,
                recorded_at=datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00")),
                details={"decision_event_id": event["decision_event_id"], "action": event["decision"]["action"]},
            )
            lifecycle_records.append(lifecycle_record)

    return current, DecisionIngestionResult(
        decision_events=tuple(decision_events),
        lifecycle_records=tuple(lifecycle_records),
    )
