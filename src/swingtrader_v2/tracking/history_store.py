"""Immutable append-only history store abstractions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


ALLOWED_RECORD_TYPES = {"lifecycle", "decision", "outcome"}


@dataclass(frozen=True)
class HistoryRecord:
    sequence: int
    record_type: str
    entity_id: str
    recorded_at: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AppendOnlyHistoryStore:
    records: tuple[HistoryRecord, ...] = field(default_factory=tuple)

    def append(
        self,
        *,
        record_type: str,
        entity_id: str,
        payload: dict[str, Any],
        recorded_at: datetime | None = None,
    ) -> tuple["AppendOnlyHistoryStore", HistoryRecord]:
        if record_type not in ALLOWED_RECORD_TYPES:
            raise ValueError(f"Unsupported record type '{record_type}'.")
        instant = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        record = HistoryRecord(
            sequence=len(self.records) + 1,
            record_type=record_type,
            entity_id=entity_id,
            recorded_at=instant,
            payload=dict(payload),
        )
        return AppendOnlyHistoryStore(records=(*self.records, record)), record

    def replay(
        self,
        *,
        entity_id: str | None = None,
        record_type: str | None = None,
    ) -> tuple[HistoryRecord, ...]:
        return tuple(
            record
            for record in self.records
            if (entity_id is None or record.entity_id == entity_id)
            and (record_type is None or record.record_type == record_type)
        )

    def latest(
        self,
        *,
        entity_id: str,
        record_type: str | None = None,
    ) -> HistoryRecord | None:
        records = self.replay(entity_id=entity_id, record_type=record_type)
        return records[-1] if records else None
