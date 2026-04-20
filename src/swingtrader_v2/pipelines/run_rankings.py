"""Selector orchestration for classification, eligibility, and review ordering."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from swingtrader_v2.data.corporate_actions import extract_corporate_actions
from swingtrader_v2.domain.enums import DataSupportStatus, EnvironmentName, PrioritizationMethod, PrioritizationStatus, SetupFamily
from swingtrader_v2.pipelines.common import artifact_ref, build_run_context, read_json, update_run_manifest, write_json
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate
from swingtrader_v2.selector.classifier import classify_candidates
from swingtrader_v2.selector.eligibility import WARNING_ONLY, EligibilityInput, evaluate_eligibility
from swingtrader_v2.selector.prioritizer import PrioritizationInput, prioritize_candidates


def _candidate_from_bundle(bundle: dict[str, Any]) -> ScannerCandidate:
    packet = bundle["packet"]
    feature_lookup = {item["name"]: item["value"] for item in packet["derived_features"]["values"]}
    scanner_notes = tuple(packet["setup"].get("scanner_notes", ()))
    return ScannerCandidate(
        symbol=packet["symbol"],
        family=SetupFamily(packet["setup"]["family"]),
        evidence=scanner_notes,
        evidence_count=len(scanner_notes),
        excess_return_63d=feature_lookup.get("excess_return_vs_spy_63d"),
        median_dollar_volume_50d=feature_lookup.get(
            "median_dollar_volume_50d",
            packet["raw_snapshot"]["liquidity"]["avg_daily_dollar_volume_20d"],
        ),
        classification_status=DataSupportStatus(packet["setup"]["classification_status"]),
        reason_codes=(),
    )


def _gate_results_payload(eligibility_result) -> list[dict[str, str]]:
    rows = []
    for gate in eligibility_result.gate_results:
        status = "passed"
        if gate.outcome == "failed":
            status = "failed"
        elif gate.outcome == "warning":
            status = "unsupported"
        rows.append(
            {
                "rule_name": gate.gate_name,
                "status": status,
                "message": ", ".join(gate.reason_codes) if gate.reason_codes else gate.outcome,
            }
        )
    return rows


def run_rankings(
    *,
    packet_bundle_path: str | Path,
    as_of_date: date | None = None,
    environment: EnvironmentName = EnvironmentName.LOCAL,
    config_root: str | Path = "config",
    artifact_root: str | Path = "artifacts",
) -> dict[str, Any]:
    packet_bundles = read_json(packet_bundle_path)["packet_bundles"]
    context = build_run_context(
        as_of_date=as_of_date or date.fromisoformat(packet_bundles[0]["packet"]["as_of_date"]),
        environment=environment,
        config_root=config_root,
        artifact_root=artifact_root,
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for bundle in packet_bundles:
        grouped.setdefault(bundle["packet"]["symbol"], []).append(bundle)

    selector_inputs: list[PrioritizationInput] = []
    selector_state: list[dict[str, Any]] = []
    updated_packets: list[dict[str, Any]] = []
    for symbol, bundles in sorted(grouped.items()):
        candidates = tuple(_candidate_from_bundle(bundle) for bundle in bundles)
        classification = classify_candidates(candidates, config=context.config.documents["setups"])
        for bundle in bundles:
            packet = bundle["packet"]
            eligibility = evaluate_eligibility(
                EligibilityInput(
                    packet=packet,
                    classification=classification,
                    trade_plan=SimpleNamespace(**bundle["trade_plan"]),
                    completeness_state=bundle["completeness"]["state"],
                    instrument_context=bundle["instrument_context"],
                    corporate_actions=extract_corporate_actions(
                        {
                            "date": item["session_date"],
                            "dividend": item["dividend"],
                            "split_ratio": item["split_ratio"],
                        }
                        for item in bundle["bar_result"]["bars"]
                    ),
                    config=context.config.documents["eligibility"],
                )
            )
            packet["eligibility_decision"] = {
                "status": "eligible" if eligibility.outcome in {"eligible", WARNING_ONLY} else "ineligible",
                "gate_results": _gate_results_payload(eligibility),
            }
            selector_inputs.append(
                PrioritizationInput(
                    packet=packet,
                    classification=classification,
                    eligibility=eligibility,
                    trade_plan=SimpleNamespace(**bundle["trade_plan"]),
                )
            )
            selector_state.append(
                {
                    "packet_id": packet["packet_id"],
                    "symbol": symbol,
                    "classification": {
                        "primary_family": classification.primary_family.value if classification.primary_family else None,
                        "secondary_tags": list(classification.secondary_tags),
                        "disqualification_reasons": list(classification.disqualification_reasons),
                    },
                    "eligibility_outcome": eligibility.outcome,
                }
            )
            updated_packets.append(packet)

    prioritization = prioritize_candidates(tuple(selector_inputs), config=context.config.documents["setups"])
    ranking_payload = {
        "artifact_type": "ranking",
        "schema_version": "v1.0.0",
        "run_id": context.run_id,
        "generated_at": context.generated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": context.as_of_date.isoformat(),
        "environment": context.environment.value,
        "config_fingerprint": context.config.fingerprint,
        "method": "transparent_weighted_sum",
        "hidden_composite_alpha_score": False,
        "ranked_packets": [],
    }
    for position, ranked in enumerate(prioritization.ranked, start=1):
        packet = next(item for item in updated_packets if item["symbol"] == ranked.symbol and item["setup"]["family"] == ranked.primary_family.value)
        score_value = 1.0 / position
        packet["prioritization"] = {
            "status": PrioritizationStatus.RANKED.value,
            "method": PrioritizationMethod.TRANSPARENT_WEIGHTED_SUM.value,
            "score_components": [{"name": "review_queue_inverse", "weight": 1.0, "value": score_value, "reason": ranked.priority_band}],
            "total_score": score_value,
        }
        ranking_payload["ranked_packets"].append(
            {
                "rank": position,
                "packet_id": packet["packet_id"],
                "symbol": packet["symbol"],
                "setup_family": packet["setup"]["family"],
                "score_components": [{"name": "review_queue_inverse", "weight": 1.0, "value": score_value}],
                "total_score": score_value,
            }
        )
        selector_row = next(item for item in selector_state if item["packet_id"] == packet["packet_id"])
        selector_row["review_queue_position"] = ranked.review_queue_position
        selector_row["family_rank"] = ranked.family_rank
        selector_row["priority_band"] = ranked.priority_band
        selector_row["sort_key_explanations"] = list(ranked.sort_key_explanations)

    for suppressed in prioritization.suppressed:
        packet = next(item for item in updated_packets if item["symbol"] == suppressed.symbol)
        packet["prioritization"] = {
            "status": PrioritizationStatus.SUPPRESSED.value,
            "method": PrioritizationMethod.TRANSPARENT_WEIGHTED_SUM.value,
            "score_components": [],
        }
        selector_row = next(item for item in selector_state if item["packet_id"] == packet["packet_id"])
        selector_row["suppressed_reason"] = suppressed.reason

    ranking_path = write_json(context.rankings_dir / "ranking.json", ranking_payload)
    selector_state_path = write_json(context.rankings_dir / "selector_state.json", {"selector_state": selector_state})
    for packet in updated_packets:
        write_json(context.packets_dir / f"{packet['packet_id']}.json", packet)
    update_run_manifest(
        context,
        [artifact_ref("ranking", str(ranking_path.relative_to(context.run_root)))],
    )
    return {
        "run_root": str(context.run_root),
        "ranking_path": str(ranking_path),
        "selector_state_path": str(selector_state_path),
        "ranked_count": len(ranking_payload["ranked_packets"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run selector orchestration and emit ranking artifacts.")
    parser.add_argument("--packet-bundles", required=True)
    parser.add_argument("--as-of-date")
    parser.add_argument("--environment", default="local", choices=[item.value for item in EnvironmentName])
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--artifact-root", default="artifacts")
    args = parser.parse_args()
    result = run_rankings(
        packet_bundle_path=args.packet_bundles,
        as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        environment=EnvironmentName(args.environment),
        config_root=args.config_root,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
