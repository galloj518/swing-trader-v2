from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swingtrader_v2.market.bars import NormalizedBar
from swingtrader_v2.tracking.decisions import ingest_manual_decisions
from swingtrader_v2.tracking.history_store import AppendOnlyHistoryStore
from swingtrader_v2.tracking.lifecycle import append_lifecycle_event, append_packet_lifecycle, replay_lifecycle
from swingtrader_v2.tracking.outcomes import append_outcome_records, calculate_outcome_analysis


UTC = ZoneInfo("UTC")


def _packet() -> dict:
    return {
        "packet_id": "pkt_aapl_20250918_0123456789abcdef",
        "run_id": "run_local_20250918_fedcba9876543210",
        "as_of_date": "2025-09-18",
        "symbol": "AAPL",
        "setup": {"family": "trend_pullback"},
        "schema_version": "v1.0.0",
    }


def _bars() -> tuple[NormalizedBar, ...]:
    closes = [100.0, 102.0, 105.0, 103.0, 108.0, 110.0, 107.0, 112.0]
    bars = []
    for index, close in enumerate(closes):
        bars.append(
            NormalizedBar(
                symbol="AAPL",
                session_date=date(2025, 9, 18).fromordinal(date(2025, 9, 18).toordinal() + index),
                open=close - 1.0,
                high=close + 2.0,
                low=close - 3.0,
                close=close,
                adjusted_close=close,
                volume=1_500_000,
                dividend=0.0,
                split_ratio=1.0,
                adjustment_factor=1.0,
            )
        )
    return tuple(bars)


def test_history_store_is_append_only_and_replayable():
    store = AppendOnlyHistoryStore()
    packet = _packet()
    store2, first = append_lifecycle_event(
        store,
        packet_id=packet["packet_id"],
        run_id=packet["run_id"],
        as_of_date=packet["as_of_date"],
        symbol=packet["symbol"],
        setup_family=packet["setup"]["family"],
        event_type="detected",
        recorded_at=datetime(2025, 9, 18, 21, 0, tzinfo=UTC),
    )
    store3, _ = append_lifecycle_event(
        store2,
        packet_id=packet["packet_id"],
        run_id=packet["run_id"],
        as_of_date=packet["as_of_date"],
        symbol=packet["symbol"],
        setup_family=packet["setup"]["family"],
        event_type="packet_built",
        recorded_at=datetime(2025, 9, 18, 21, 1, tzinfo=UTC),
    )

    assert store.records == ()
    assert len(store2.records) == 1
    assert len(store3.records) == 2
    replay = replay_lifecycle(store3, packet_id=packet["packet_id"])
    assert replay.current_event == "packet_built"
    assert replay.event_types == ("detected", "packet_built")
    assert first.sequence == 1


def test_packet_lifecycle_appends_selector_states_without_rewriting_history():
    store = AppendOnlyHistoryStore()
    packet = _packet()
    store2, records = append_packet_lifecycle(
        store,
        packet=packet,
        classification={"primary_family": "trend_pullback"},
        eligibility_outcome="eligible",
        review_context={"review_queue_position": 1},
        recorded_at=datetime(2025, 9, 18, 21, 15, tzinfo=UTC),
    )

    assert len(records) == 5
    replay = replay_lifecycle(store2, packet_id=packet["packet_id"])
    assert replay.event_types == ("detected", "packet_built", "classified", "eligible", "selected_for_review")


def test_manual_decisions_are_ingested_only_from_explicit_rows_and_emit_manual_lifecycle():
    store = AppendOnlyHistoryStore()
    csv_payload = """packet_id,run_id,as_of_date,environment,recorded_at,action,rationale,tags,symbol,setup_family
pkt_aapl_20250918_0123456789abcdef,run_local_20250918_fedcba9876543210,2025-09-18,local,2025-09-18T21:30:00Z,plan_trade,Operator planned entry,watch|manual,AAPL,trend_pullback
pkt_aapl_20250918_0123456789abcdef,run_local_20250918_fedcba9876543210,2025-09-18,local,2025-09-18T21:45:00Z,pass,No fill after review,expired,AAPL,trend_pullback
"""
    store2, result = ingest_manual_decisions(store, csv_payload)

    assert len(result.decision_events) == 2
    assert result.decision_events[0]["decision"]["action"] == "plan_trade"
    assert result.decision_events[0]["decision"]["tags"] == ["watch", "manual"]
    lifecycle_events = [record.payload["event_type"] for record in result.lifecycle_records]
    assert lifecycle_events == ["entered_manual", "exited_manual"]
    assert len(store.records) == 0
    assert len(store2.records) == 4


def test_outcome_analysis_computes_forward_windows_and_appends_records():
    packet = _packet()
    bars = _bars()
    store = AppendOnlyHistoryStore()
    decision_event = {
        "decision_event_id": "dec_aapl_deadbeefdeadbeef",
        "packet_id": packet["packet_id"],
    }
    analysis = calculate_outcome_analysis(
        bars=bars,
        entry_date=bars[0].session_date,
        entry_price=bars[0].close,
        invalidation_level=97.0,
        reference_high=101.0,
    )
    horizon_map = {item.bars_ahead: item for item in analysis.horizon_returns}

    assert horizon_map[1].status == "complete"
    assert round(horizon_map[1].return_pct, 4) == 0.02
    assert horizon_map[10].status == "pending"
    assert analysis.mfe_pct is not None
    assert analysis.mae_pct is not None
    assert analysis.time_to_invalidated is None
    assert analysis.time_to_new_high == 1

    store2, records = append_outcome_records(
        store,
        packet=packet,
        decision_event=decision_event,
        analysis=analysis,
        recorded_at=datetime(2025, 10, 10, 21, 0, tzinfo=UTC),
    )
    assert len(records) == 3
    assert {record["horizon"] for record in records} == {"t_plus_5", "t_plus_10", "t_plus_20"}
    assert len(store2.replay(entity_id=packet["packet_id"], record_type="outcome")) == 3
    lifecycle = replay_lifecycle(store2, packet_id=packet["packet_id"])
    assert lifecycle.current_event == "outcome_recorded"
