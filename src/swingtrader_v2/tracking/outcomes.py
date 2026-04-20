"""Forward outcome calculations and append-only outcome records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from swingtrader_v2.market.bars import NormalizedBar
from swingtrader_v2.tracking.history_store import AppendOnlyHistoryStore
from swingtrader_v2.tracking.lifecycle import append_lifecycle_event


OUTCOME_SCHEMA_VERSION = "v1.0.0"
SCHEMA_HORIZONS = {5: "t_plus_5", 10: "t_plus_10", 20: "t_plus_20"}
ALL_HORIZONS = (1, 5, 10, 20)


@dataclass(frozen=True)
class HorizonOutcome:
    bars_ahead: int
    status: str
    return_pct: float | None


@dataclass(frozen=True)
class OutcomeAnalysis:
    horizon_returns: tuple[HorizonOutcome, ...]
    mfe_pct: float | None
    mae_pct: float | None
    time_to_invalidated: int | None
    time_to_new_high: int | None


def _outcome_id(packet_id: str, decision_event_id: str, horizon_label: str, recorded_at: str) -> str:
    payload = json.dumps(
        {
            "packet_id": packet_id,
            "decision_event_id": decision_event_id,
            "horizon": horizon_label,
            "recorded_at": recorded_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"out_{packet_id.split('_', 1)[1]}_{digest}"


def _bar_index(bars: tuple[NormalizedBar, ...], session_date: date) -> int:
    for index, bar in enumerate(bars):
        if bar.session_date == session_date:
            return index
    raise ValueError(f"Entry date {session_date.isoformat()} not found in bar series.")


def calculate_outcome_analysis(
    *,
    bars: tuple[NormalizedBar, ...],
    entry_date: date,
    entry_price: float,
    invalidation_level: float | None = None,
    reference_high: float | None = None,
) -> OutcomeAnalysis:
    index = _bar_index(bars, entry_date)
    forward = bars[index + 1:]
    reference_high = reference_high if reference_high is not None else entry_price

    horizon_returns: list[HorizonOutcome] = []
    for horizon in ALL_HORIZONS:
        if index + horizon >= len(bars):
            horizon_returns.append(HorizonOutcome(bars_ahead=horizon, status="pending", return_pct=None))
            continue
        close = bars[index + horizon].close
        horizon_returns.append(
            HorizonOutcome(
                bars_ahead=horizon,
                status="complete",
                return_pct=(close - entry_price) / entry_price if entry_price else None,
            )
        )

    mfe_pct = max(((bar.high - entry_price) / entry_price for bar in forward), default=None) if entry_price else None
    mae_pct = min(((bar.low - entry_price) / entry_price for bar in forward), default=None) if entry_price else None

    time_to_invalidated = None
    if invalidation_level is not None:
        for offset, bar in enumerate(forward, start=1):
            if bar.low <= invalidation_level:
                time_to_invalidated = offset
                break

    time_to_new_high = None
    for offset, bar in enumerate(forward, start=1):
        if bar.high > reference_high:
            time_to_new_high = offset
            break

    return OutcomeAnalysis(
        horizon_returns=tuple(horizon_returns),
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        time_to_invalidated=time_to_invalidated,
        time_to_new_high=time_to_new_high,
    )


def build_outcome_records(
    *,
    packet_id: str,
    decision_event_id: str,
    recorded_at: datetime,
    analysis: OutcomeAnalysis,
) -> tuple[dict[str, Any], ...]:
    recorded_at_text = recorded_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    horizon_map = {item.bars_ahead: item for item in analysis.horizon_returns}
    records: list[dict[str, Any]] = []
    for bars_ahead, label in SCHEMA_HORIZONS.items():
        horizon = horizon_map[bars_ahead]
        metrics = {
            "notes": (
                f"mfe_pct={analysis.mfe_pct}; "
                f"mae_pct={analysis.mae_pct}; "
                f"time_to_invalidated={analysis.time_to_invalidated}; "
                f"time_to_new_high={analysis.time_to_new_high}"
            )
        }
        if horizon.return_pct is not None:
            metrics["return_pct"] = horizon.return_pct
            metrics["max_drawdown_pct"] = analysis.mae_pct if analysis.mae_pct is not None else 0.0
        records.append(
            {
                "artifact_type": "outcome_record",
                "schema_version": OUTCOME_SCHEMA_VERSION,
                "outcome_record_id": _outcome_id(packet_id, decision_event_id, label, recorded_at_text),
                "packet_id": packet_id,
                "decision_event_id": decision_event_id,
                "recorded_at": recorded_at_text,
                "horizon": label,
                "status": "complete" if horizon.status == "complete" else "pending",
                "metrics": metrics,
            }
        )
    return tuple(records)


def append_outcome_records(
    store: AppendOnlyHistoryStore,
    *,
    packet: dict[str, Any],
    decision_event: dict[str, Any],
    analysis: OutcomeAnalysis,
    recorded_at: datetime | None = None,
) -> tuple[AppendOnlyHistoryStore, tuple[dict[str, Any], ...]]:
    instant = recorded_at or datetime.now(timezone.utc)
    current = store
    records = build_outcome_records(
        packet_id=packet["packet_id"],
        decision_event_id=decision_event["decision_event_id"],
        recorded_at=instant,
        analysis=analysis,
    )
    for record in records:
        current, _ = current.append(
            record_type="outcome",
            entity_id=record["packet_id"],
            payload=record,
            recorded_at=instant,
        )
    current, _ = append_lifecycle_event(
        current,
        packet_id=packet["packet_id"],
        run_id=packet["run_id"],
        as_of_date=packet["as_of_date"],
        symbol=packet["symbol"],
        setup_family=packet["setup"]["family"],
        event_type="outcome_recorded",
        recorded_at=instant,
        details={"decision_event_id": decision_event["decision_event_id"]},
    )
    return current, records
