from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from math import isclose
from zoneinfo import ZoneInfo

from swingtrader_v2.analysis.momentum import compute_momentum_features
from swingtrader_v2.analysis.moving_averages import compute_moving_averages
from swingtrader_v2.analysis.patterns import compute_pattern_features
from swingtrader_v2.analysis.relative_strength import compute_relative_strength_features
from swingtrader_v2.analysis.volume import compute_volume_features
from swingtrader_v2.analysis.volatility import compute_volatility_features
from swingtrader_v2.anchors.definitions import ManualAnchorDefinition
from swingtrader_v2.anchors.resolver import resolve_anchor
from swingtrader_v2.data.freshness import assess_freshness
from swingtrader_v2.domain.enums import ArtifactType, DataSupportStatus, EnvironmentName, SetupFamily
from swingtrader_v2.domain.ids import build_packet_id, build_run_id
from swingtrader_v2.domain.models import ArtifactRef
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.packet.assembler import AssembledPacket, PacketAssemblyInput, assemble_packet
from swingtrader_v2.packet.completeness import COMPLETE, INVALID, PARTIAL, assess_packet_completeness
from swingtrader_v2.packet.validator import validate_packet
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate


NY_TZ = ZoneInfo("America/New_York")


def _rows(count: int, *, start: date = date(2025, 1, 2), base: float = 100.0, slope: float = 0.45) -> list[dict]:
    rows: list[dict] = []
    for index in range(count):
        close = base + (index * slope) + (((index % 8) - 4) * 0.35)
        rows.append(
            {
                "date": (start.fromordinal(start.toordinal() + index)).isoformat(),
                "open": close - 0.6,
                "high": close + 1.1,
                "low": close - 1.0,
                "close": close,
                "adjusted_close": close,
                "volume": 1_600_000 + ((index % 9) * 120_000),
                "dividend": 0.0,
                "split_ratio": 1.0,
            }
        )
    return rows
def _assembled_packet(family: SetupFamily = SetupFamily.TREND_PULLBACK) -> AssembledPacket:
    config_fingerprint = "a" * 64
    run_id = build_run_id(
        as_of_date=date(2025, 9, 18),
        environment=EnvironmentName.LOCAL.value,
        universe_name="liquid_us_equities",
        config_fingerprint=config_fingerprint,
    )
    bar_result = normalize_daily_bars("AAPL", _rows(260))
    bars = bar_result.bars
    benchmark = normalize_daily_bars("SPY", _rows(260, base=95.0, slope=0.25)).bars
    freshness = assess_freshness(
        last_bar_date=bars[-1].session_date,
        as_of=datetime(2025, 9, 18, 17, 0, tzinfo=NY_TZ),
    )
    anchor = resolve_anchor(
        symbol="AAPL",
        bars=bars,
        definition=ManualAnchorDefinition(
            family="manual_anchor",
            name="manual_reference",
            anchor_date=bars[-30].session_date,
            anchor_value=bars[-30].close,
        ),
        config_fingerprint=config_fingerprint,
    )
    candidate = ScannerCandidate(
        symbol="AAPL",
        family=family,
        evidence=("trend_intact", "support_proximity_present"),
        evidence_count=2,
        excess_return_63d=0.18,
        median_dollar_volume_50d=55_000_000.0,
        classification_status=DataSupportStatus.OK,
        reason_codes=(),
    )
    return assemble_packet(
        PacketAssemblyInput(
            candidate=candidate,
            bar_result=bar_result,
            freshness=freshness,
            moving_averages=compute_moving_averages(bars),
            momentum=compute_momentum_features(bars),
            volume=compute_volume_features(bars),
            volatility=compute_volatility_features(bars),
            patterns=compute_pattern_features(bars),
            relative_strength=compute_relative_strength_features(
                bars,
                benchmark,
                peer_excess_returns={21: [0.03, 0.05, 0.09], 63: [0.08, 0.11, 0.14]},
            ),
            anchors=(anchor,),
            run_id=run_id,
            as_of_date=date(2025, 9, 18),
            generated_at=datetime(2025, 9, 18, 21, 15, tzinfo=ZoneInfo("UTC")),
            environment=EnvironmentName.LOCAL,
            config_fingerprint=config_fingerprint,
            artifact_lineage=(
                ArtifactRef(
                    artifact_type=ArtifactType.CANDIDATE_LIST,
                    artifact_id="cand_aapl_trend_pullback",
                    schema_version="v1.0.0",
                ),
            ),
        )
    )


def test_candidate_assembles_into_schema_valid_packet():
    assembled = _assembled_packet()
    packet = assembled.payload

    assert validate_packet(packet).ok
    assert packet["packet_id"] == build_packet_id(
        symbol="AAPL",
        setup_family=SetupFamily.TREND_PULLBACK.value,
        as_of_date=date(2025, 9, 18),
        run_id=packet["run_id"],
    )
    assert packet["eligibility_decision"]["status"] == "indeterminate"
    assert packet["prioritization"]["status"] == "not_applicable"
    assert packet["data_status"]["overall_status"] == "ok"
    assert packet["derived_features"]["values"]
    assert packet["anchor_set"]
    assert assembled.trade_plan.actionability_state == "ready"
    assert assess_packet_completeness(packet).state == COMPLETE


def test_validator_rejects_non_deterministic_packet_id():
    packet = deepcopy(_assembled_packet().payload)
    packet["packet_id"] = "pkt_aapl_20250918_deadbeefdeadbeef"
    report = validate_packet(packet)
    assert report.ok is False
    assert any(issue.path == "packet_id" for issue in report.errors)


def test_completeness_marks_low_confidence_packet_partial():
    packet = deepcopy(_assembled_packet().payload)
    packet["data_status"]["overall_status"] = "low_confidence"
    packet["data_status"]["issues"].append(
        {
            "field": "anchor_set.breakout_proxy",
            "status": "low_confidence",
            "reason": "anchor_not_found",
        }
    )
    report = assess_packet_completeness(packet)
    assert report.state == PARTIAL
    assert "status:low_confidence" in report.reason_codes


def test_completeness_marks_schema_break_invalid():
    packet = deepcopy(_assembled_packet().payload)
    del packet["raw_snapshot"]
    report = assess_packet_completeness(packet)
    assert report.state == INVALID
    assert any(code.startswith("packet.raw_snapshot") for code in report.reason_codes)


def test_avwap_reclaim_trade_plan_uses_avwap_trigger():
    assembled = _assembled_packet(SetupFamily.AVWAP_RECLAIM)
    anchor = assembled.payload["anchor_set"][0]
    avwap_current = next(
        item["value"]
        for item in assembled.payload["derived_features"]["values"]
        if item["name"] == "avwap_proxy.manual_reference.current"
    )
    assert anchor["is_daily_proxy"] is True
    assert isclose(assembled.trade_plan.trigger_level, avwap_current, rel_tol=1e-9)
