from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from swingtrader_v2.domain.enums import ArtifactType, EnvironmentName
from swingtrader_v2.domain.ids import build_run_id
from swingtrader_v2.domain.models import ArtifactRef
from swingtrader_v2.packet.assembler import PacketAssemblyInput, assemble_packet
from swingtrader_v2.packet.completeness import PARTIAL, assess_packet_completeness
from swingtrader_v2.packet.validator import validate_packet


UTC = ZoneInfo("UTC")


def _assemble_from_snapshot(snapshot, candidate, *, as_of_date):
    run_id = build_run_id(
        as_of_date=as_of_date,
        environment=EnvironmentName.LOCAL.value,
        universe_name="liquid_us_equities",
        config_fingerprint="a" * 64,
    )
    return assemble_packet(
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


def test_packet_assembly_is_deterministic_for_identical_fixture_inputs(scenario_library):
    snapshot = scenario_library.snapshot("clean_trend_pullback")
    candidate = snapshot.candidates[0]

    first = _assemble_from_snapshot(snapshot, candidate, as_of_date=scenario_library.as_of_date)
    second = _assemble_from_snapshot(snapshot, candidate, as_of_date=scenario_library.as_of_date)

    assert first.payload == second.payload
    assert asdict(first.trade_plan) == asdict(second.trade_plan)
    assert validate_packet(first.payload).ok


def test_packet_completeness_stays_explicit_for_stale_fixture_inputs(scenario_library):
    snapshot = scenario_library.snapshot("stale_data_symbol")
    candidate = snapshot.candidates[0]
    assembled = _assemble_from_snapshot(snapshot, candidate, as_of_date=scenario_library.as_of_date)

    report = assess_packet_completeness(assembled.payload)

    assert report.state == PARTIAL
    assert "status:stale" in report.reason_codes
    assert assembled.payload["data_status"]["overall_status"] == "stale"
