"""Append-only watchlist lifecycle event handling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from swingtrader_v2.tracking.history_store import AppendOnlyHistoryStore, HistoryRecord


LIFECYCLE_EVENTS = (
    "detected",
    "packet_built",
    "classified",
    "eligible",
    "warning_only",
    "ineligible",
    "selected_for_review",
    "entered_manual",
    "exited_manual",
    "invalidated",
    "expired_without_entry",
    "outcome_recorded",
)


@dataclass(frozen=True)
class LifecycleSnapshot:
    packet_id: str
    current_event: str | None
    event_types: tuple[str, ...]
    records: tuple[HistoryRecord, ...]


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _event_id(packet_id: str, event_type: str, recorded_at: datetime, details: dict[str, Any]) -> str:
    return f"life_{_digest({'packet_id': packet_id, 'event_type': event_type, 'recorded_at': recorded_at.isoformat(), 'details': details})}"


def append_lifecycle_event(
    store: AppendOnlyHistoryStore,
    *,
    packet_id: str,
    run_id: str,
    as_of_date: str,
    symbol: str,
    setup_family: str,
    event_type: str,
    recorded_at: datetime | None = None,
    details: dict[str, Any] | None = None,
    artifact_refs: tuple[dict[str, Any], ...] = (),
) -> tuple[AppendOnlyHistoryStore, HistoryRecord]:
    if event_type not in LIFECYCLE_EVENTS:
        raise ValueError(f"Unsupported lifecycle event '{event_type}'.")
    instant = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "lifecycle_event_id": _event_id(packet_id, event_type, instant, details or {}),
        "packet_id": packet_id,
        "run_id": run_id,
        "as_of_date": as_of_date,
        "symbol": symbol,
        "setup_family": setup_family,
        "event_type": event_type,
        "artifact_refs": [dict(reference) for reference in artifact_refs],
        "details": dict(details or {}),
    }
    return store.append(record_type="lifecycle", entity_id=packet_id, payload=payload, recorded_at=instant)


def append_packet_lifecycle(
    store: AppendOnlyHistoryStore,
    *,
    packet: dict[str, Any],
    classification: dict[str, Any] | None = None,
    eligibility_outcome: str | None = None,
    review_context: dict[str, Any] | None = None,
    recorded_at: datetime | None = None,
) -> tuple[AppendOnlyHistoryStore, tuple[HistoryRecord, ...]]:
    current = store
    created: list[HistoryRecord] = []
    packet_id = packet["packet_id"]
    base = {
        "packet_id": packet_id,
        "run_id": packet["run_id"],
        "as_of_date": packet["as_of_date"],
        "symbol": packet["symbol"],
        "setup_family": packet["setup"]["family"],
    }
    for event_type, details in (
        ("detected", {"scanner_label": packet["setup"].get("scanner_label", "unknown")}),
        ("packet_built", {"schema_version": packet["schema_version"]}),
    ):
        current, record = append_lifecycle_event(current, event_type=event_type, details=details, recorded_at=recorded_at, **base)
        created.append(record)
    if classification is not None:
        current, record = append_lifecycle_event(
            current,
            event_type="classified",
            details=dict(classification),
            recorded_at=recorded_at,
            **base,
        )
        created.append(record)
    if eligibility_outcome is not None:
        current, record = append_lifecycle_event(
            current,
            event_type=eligibility_outcome,
            details={"eligibility_status": eligibility_outcome},
            recorded_at=recorded_at,
            **base,
        )
        created.append(record)
    if review_context is not None:
        current, record = append_lifecycle_event(
            current,
            event_type="selected_for_review",
            details=dict(review_context),
            recorded_at=recorded_at,
            **base,
        )
        created.append(record)
    return current, tuple(created)


def replay_lifecycle(store: AppendOnlyHistoryStore, *, packet_id: str) -> LifecycleSnapshot:
    records = store.replay(entity_id=packet_id, record_type="lifecycle")
    event_types = tuple(record.payload["event_type"] for record in records)
    return LifecycleSnapshot(
        packet_id=packet_id,
        current_event=event_types[-1] if event_types else None,
        event_types=event_types,
        records=records,
    )
