from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from swingtrader_v2.config.loader import fingerprint_config, load_effective_config
from swingtrader_v2.config.validator import ensure_valid_config, validate_effective_config
from swingtrader_v2.domain.enums import EnvironmentName, SetupFamily
from swingtrader_v2.domain.ids import build_anchor_id, build_packet_id, build_run_id
from swingtrader_v2.domain.models import EffectiveConfig


ROOT = Path(__file__).resolve().parents[2]


def _load_schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _build_valid_packet() -> dict:
    config_fingerprint = "a" * 64
    run_id = build_run_id(
        as_of_date=date(2026, 4, 20),
        environment=EnvironmentName.LOCAL.value,
        universe_name="liquid_us_equities",
        config_fingerprint=config_fingerprint
    )
    packet_id = build_packet_id(
        symbol="AAPL",
        setup_family=SetupFamily.TREND_PULLBACK.value,
        as_of_date=date(2026, 4, 20),
        run_id=run_id
    )
    anchor_id = build_anchor_id(
        symbol="AAPL",
        anchor_name="daily_proxy_avwap",
        anchor_source="daily_bars",
        config_fingerprint=config_fingerprint
    )
    return {
        "artifact_type": "packet",
        "schema_version": "v1.0.0",
        "packet_id": packet_id,
        "run_id": run_id,
        "generated_at": "2026-04-20T20:00:00Z",
        "as_of_date": "2026-04-20",
        "environment": "local",
        "config_fingerprint": config_fingerprint,
        "symbol": "AAPL",
        "setup": {
            "family": "trend_pullback",
            "classification_status": "ok",
            "scanner_label": "placeholder"
        },
        "data_status": {
            "overall_status": "ok",
            "issues": [
                {
                    "field": "fundamentals.float_shares",
                    "status": "unsupported",
                    "reason": "Not in scope for v1 core dependency."
                }
            ]
        },
        "provenance": {
            "market_data_provider": "yfinance",
            "provider_mode": "baseline",
            "artifact_lineage": []
        },
        "raw_snapshot": {
            "snapshot_status": "stale",
            "price_bar": {
                "open": 175.1,
                "high": 178.0,
                "low": 174.5,
                "close": 177.8,
                "volume": 50200000
            },
            "liquidity": {
                "avg_daily_volume_20d": 43000000.0,
                "avg_daily_dollar_volume_20d": 7600000000.0
            },
            "coverage": {
                "bars_available": 252,
                "last_bar_date": "2026-04-20",
                "staleness_days": 0
            }
        },
        "derived_features": {
            "feature_status": "low_confidence",
            "values": [
                {
                    "name": "distance_from_20d_ema_pct",
                    "status": "low_confidence",
                    "value": 1.8,
                    "units": "pct"
                }
            ]
        },
        "anchor_set": [
            {
                "anchor_id": anchor_id,
                "name": "daily_proxy_avwap",
                "status": "ok",
                "value": 171.2,
                "source": "daily_bars",
                "is_daily_proxy": True
            }
        ],
        "eligibility_decision": {
            "status": "indeterminate",
            "gate_results": [
                {
                    "rule_name": "eod_freshness",
                    "status": "unsupported",
                    "message": "Demonstrates explicit unsupported handling."
                }
            ]
        },
        "prioritization": {
            "status": "not_applicable",
            "method": "transparent_weighted_sum",
            "score_components": []
        },
        "operator_review": {
            "status": "not_reviewed",
            "packet_summary": "Placeholder artifact summary."
        },
        "outcomes": {
            "status": "not_started",
            "outcome_record_refs": []
        }
    }


def test_all_phase_one_schemas_are_valid_json_schema_documents():
    for schema_name in (
        "packet.schema.json",
        "candidate_list.schema.json",
        "ranking.schema.json",
        "dashboard_payload.schema.json",
        "run_manifest.schema.json",
        "decision_event.schema.json",
        "outcome_record.schema.json"
    ):
        schema = _load_schema(schema_name)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert "properties" in schema
        assert "required" in schema


def test_packet_schema_accepts_required_top_level_sections_and_statuses():
    schema = _load_schema("packet.schema.json")
    packet = _build_valid_packet()
    required = set(schema["required"])
    assert required.issubset(packet.keys())

    top_level_sections = {
        "raw_snapshot",
        "derived_features",
        "eligibility_decision",
        "prioritization",
        "outcomes"
    }
    assert top_level_sections.issubset(required)
    assert schema["properties"]["data_status"]["properties"]["overall_status"]["$ref"] == "#/$defs/dataSupportStatus"
    assert set(schema["$defs"]["dataSupportStatus"]["enum"]) == {
        "ok",
        "missing",
        "unsupported",
        "stale",
        "low_confidence"
    }
    assert packet["raw_snapshot"]["snapshot_status"] == "stale"
    assert packet["derived_features"]["feature_status"] == "low_confidence"
    assert packet["data_status"]["issues"][0]["status"] == "unsupported"


def test_packet_schema_rejects_missing_section():
    schema = _load_schema("packet.schema.json")
    packet = _build_valid_packet()
    del packet["derived_features"]
    required = set(schema["required"])
    assert "derived_features" in required
    assert not required.issubset(packet.keys())


def test_effective_config_loads_and_fingerprint_is_deterministic():
    first = load_effective_config(ROOT / "config", environment=EnvironmentName.GITHUB_ACTIONS)
    second = load_effective_config(ROOT / "config", environment=EnvironmentName.GITHUB_ACTIONS)

    assert first.environment is EnvironmentName.GITHUB_ACTIONS
    assert first.effective["environment"]["name"] == "github_actions"
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint == fingerprint_config(first.effective)


def test_config_validator_accepts_repo_defaults():
    config = load_effective_config(ROOT / "config", environment=EnvironmentName.GITHUB_ACTIONS)
    report = validate_effective_config(config)
    assert report.ok, report.errors
    ensure_valid_config(config)


def test_config_validator_detects_duplicates_and_contradictory_thresholds():
    config = load_effective_config(ROOT / "config")
    mutated = deepcopy(config.effective)
    mutated["anchors"].append(deepcopy(mutated["anchors"][0]))
    mutated["thresholds"]["price"]["min"] = 50.0
    mutated["thresholds"]["price"]["max"] = 10.0

    report = validate_effective_config(
        EffectiveConfig(
            environment=config.environment,
            documents=config.documents,
            effective=mutated,
            fingerprint=fingerprint_config(mutated)
        )
    )

    messages = [f"{issue.path}: {issue.message}" for issue in report.errors]
    assert any("Duplicate value" in message for message in messages)
    assert any("Contradictory thresholds" in message for message in messages)


def test_ids_are_deterministic_for_same_inputs():
    kwargs = {
        "as_of_date": date(2026, 4, 20),
        "environment": "local",
        "universe_name": "liquid_us_equities",
        "config_fingerprint": "b" * 64
    }
    run_id_1 = build_run_id(**kwargs)
    run_id_2 = build_run_id(**kwargs)
    assert run_id_1 == run_id_2

    packet_id_1 = build_packet_id(
        symbol="MSFT",
        setup_family="base_breakout",
        as_of_date=date(2026, 4, 20),
        run_id=run_id_1
    )
    packet_id_2 = build_packet_id(
        symbol="MSFT",
        setup_family="base_breakout",
        as_of_date=date(2026, 4, 20),
        run_id=run_id_1
    )
    assert packet_id_1 == packet_id_2

    anchor_id_1 = build_anchor_id(
        symbol="MSFT",
        anchor_name="base_high",
        anchor_source="daily_bars",
        config_fingerprint="b" * 64
    )
    anchor_id_2 = build_anchor_id(
        symbol="MSFT",
        anchor_name="base_high",
        anchor_source="daily_bars",
        config_fingerprint="b" * 64
    )
    assert anchor_id_1 == anchor_id_2
