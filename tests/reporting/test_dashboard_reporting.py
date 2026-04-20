from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
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
from swingtrader_v2.domain.ids import build_run_id
from swingtrader_v2.domain.models import ArtifactRef
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.packet.assembler import PacketAssemblyInput, assemble_packet
from swingtrader_v2.reporting.contracts import validate_dashboard_payload
from swingtrader_v2.reporting.dashboard_payload import DashboardAssemblerInput, build_dashboard_bundle
from swingtrader_v2.reporting.html_renderer import render_dashboard_html
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate


NY_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


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


def _packet(symbol: str, family: SetupFamily) -> dict:
    config_fingerprint = "a" * 64
    as_of_date = date(2025, 9, 18)
    run_id = build_run_id(
        as_of_date=as_of_date,
        environment=EnvironmentName.LOCAL.value,
        universe_name="liquid_us_equities",
        config_fingerprint=config_fingerprint,
    )
    bar_result = normalize_daily_bars(symbol, _rows(260))
    bars = bar_result.bars
    benchmark = normalize_daily_bars("SPY", _rows(260, base=95.0, slope=0.25)).bars
    freshness = assess_freshness(
        last_bar_date=bars[-1].session_date,
        as_of=datetime(2025, 9, 18, 17, 0, tzinfo=NY_TZ),
    )
    anchor = resolve_anchor(
        symbol=symbol,
        bars=bars,
        definition=ManualAnchorDefinition(
            family="manual_anchor",
            name="manual_reference",
            anchor_date=bars[-30].session_date,
            anchor_value=bars[-30].close,
        ),
        config_fingerprint=config_fingerprint,
    )
    assembled = assemble_packet(
        PacketAssemblyInput(
            candidate=ScannerCandidate(
                symbol=symbol,
                family=family,
                evidence=("detected", "artifact_ready"),
                evidence_count=2,
                excess_return_63d=0.18,
                median_dollar_volume_50d=55_000_000.0,
                classification_status=DataSupportStatus.OK,
                reason_codes=(),
            ),
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
                peer_excess_returns={21: [0.03, 0.05], 63: [0.08, 0.11]},
            ),
            anchors=(anchor,),
            run_id=run_id,
            as_of_date=as_of_date,
            generated_at=datetime(2025, 9, 18, 21, 15, tzinfo=UTC),
            environment=EnvironmentName.LOCAL,
            config_fingerprint=config_fingerprint,
            artifact_lineage=(
                ArtifactRef(
                    artifact_type=ArtifactType.CANDIDATE_LIST,
                    artifact_id=f"cand_{symbol.lower()}",
                    schema_version="v1.0.0",
                ),
            ),
        )
    )
    return assembled.payload


def _artifacts():
    packet_a = _packet("AAPL", SetupFamily.TREND_PULLBACK)
    packet_a["eligibility_decision"] = {
        "status": "eligible",
        "gate_results": [
            {"rule_name": "instrument_support", "status": "passed", "message": "supported"},
            {"rule_name": "freshness", "status": "passed", "message": "fresh"},
        ],
    }
    packet_a["prioritization"] = {
        "status": "ranked",
        "method": "transparent_weighted_sum",
        "score_components": [
            {"name": "queue_order", "weight": 1.0, "value": 1.0, "reason": "rank=1"},
        ],
        "total_score": 1.0,
    }

    packet_b = _packet("MSFT", SetupFamily.BASE_BREAKOUT)
    packet_b["data_status"]["overall_status"] = "stale"
    packet_b["data_status"]["issues"].append(
        {"field": "raw_snapshot.coverage", "status": "stale", "reason": "stale_expected_session"}
    )
    packet_b["eligibility_decision"] = {
        "status": "ineligible",
        "gate_results": [
            {"rule_name": "freshness", "status": "failed", "message": "stale_expected_session"},
            {"rule_name": "setup_specific_integrity", "status": "failed", "message": "base_pivot_missing"},
        ],
    }
    packet_b["prioritization"] = {
        "status": "suppressed",
        "method": "transparent_weighted_sum",
        "score_components": [],
    }
    packet_b["outcomes"] = {"status": "tracking", "outcome_record_refs": []}

    run_manifest = {
        "artifact_type": "run_manifest",
        "schema_version": "v1.0.0",
        "run_id": packet_a["run_id"],
        "generated_at": "2025-09-18T21:15:00Z",
        "as_of_date": "2025-09-18",
        "environment": "local",
        "config_fingerprint": "a" * 64,
        "runtime_mode": "eod",
        "inputs": {
            "market_data_provider": "yfinance",
            "universe_name": "liquid_us_equities",
        },
        "artifact_outputs": [
            {"artifact_type": "packet", "artifact_id": packet_a["packet_id"], "schema_version": "v1.0.0"},
            {"artifact_type": "packet", "artifact_id": packet_b["packet_id"], "schema_version": "v1.0.0"},
            {"artifact_type": "ranking", "artifact_id": packet_a["run_id"], "schema_version": "v1.0.0"},
        ],
    }
    ranking = {
        "artifact_type": "ranking",
        "schema_version": "v1.0.0",
        "run_id": packet_a["run_id"],
        "generated_at": "2025-09-18T21:20:00Z",
        "as_of_date": "2025-09-18",
        "environment": "local",
        "config_fingerprint": "a" * 64,
        "method": "transparent_weighted_sum",
        "hidden_composite_alpha_score": False,
        "ranked_packets": [
            {
                "rank": 1,
                "packet_id": packet_a["packet_id"],
                "symbol": "AAPL",
                "setup_family": "trend_pullback",
                "score_components": [{"name": "queue_order", "weight": 1.0, "value": 1.0}],
                "total_score": 1.0,
            }
        ],
    }
    prior_dashboard = {
        "artifact_type": "dashboard_payload",
        "schema_version": "v1.0.0",
        "run_id": "run_local_20250917_deadbeefdeadbeef",
        "generated_at": "2025-09-17T21:20:00Z",
        "as_of_date": "2025-09-17",
        "environment": "local",
        "config_fingerprint": "b" * 64,
        "artifact_inputs": {
            "run_manifest": {"artifact_type": "run_manifest", "artifact_id": "prior", "schema_version": "v1.0.0"},
            "ranking": {"artifact_type": "ranking", "artifact_id": "prior", "schema_version": "v1.0.0"},
            "packets": [],
        },
        "summary": {"eligible_count": 1, "ranked_count": 1, "ineligible_count": 0},
        "rows": [
            {
                "packet_id": packet_b["packet_id"],
                "symbol": "MSFT",
                "setup_family": "base_breakout",
                "eligibility_status": "ineligible",
                "prioritization_status": "ranked",
            }
        ],
    }
    return run_manifest, ranking, (packet_a, packet_b), prior_dashboard


def test_dashboard_payload_is_schema_valid_and_artifact_only():
    run_manifest, ranking, packets, prior_dashboard = _artifacts()
    bundle = build_dashboard_bundle(
        DashboardAssemblerInput(
            run_manifest=run_manifest,
            ranking=ranking,
            packets=packets,
            prior_dashboard_payload=prior_dashboard,
        )
    )

    report = validate_dashboard_payload(bundle.artifact.payload)
    assert report.ok, report.errors
    assert bundle.artifact.payload["summary"] == {
        "eligible_count": 1,
        "ranked_count": 1,
        "ineligible_count": 1,
    }
    assert bundle.render_model.run_health.title == "Degraded Run"
    assert bundle.render_model.watchlist_changes.added == ("AAPL",)
    assert bundle.render_model.watchlist_changes.removed == ("MSFT",)
    assert bundle.render_model.gate_failures[0].symbol == "MSFT"


def test_html_renderer_makes_degraded_and_unsupported_states_visible():
    run_manifest, ranking, packets, prior_dashboard = _artifacts()
    packets = list(deepcopy(packets))
    packets[1]["data_status"]["issues"].append(
        {"field": "derived_features.avwap_proxy", "status": "unsupported", "reason": "not_applicable"}
    )
    bundle = build_dashboard_bundle(
        DashboardAssemblerInput(
            run_manifest=run_manifest,
            ranking=ranking,
            packets=tuple(packets),
            prior_dashboard_payload=prior_dashboard,
        )
    )

    html = render_dashboard_html(bundle.render_model)

    assert "Top Review Queue" in html
    assert "Gate Failure Reasons" in html
    assert "Survivorship Bias Disclosure" in html
    assert "stale_expected_session" in html
    assert "unsupported" in html
    assert "Watchlist Changes Vs Prior Session" in html
