"""Packet build orchestration over previously scanned state."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from swingtrader_v2.domain.enums import DataSupportStatus, EnvironmentName, MarketDataProvider, ProviderMode, SetupFamily
from swingtrader_v2.packet.assembler import PacketAssemblyInput, assemble_packet
from swingtrader_v2.packet.completeness import assess_packet_completeness
from swingtrader_v2.pipelines.common import (
    artifact_ref,
    build_run_context,
    deserialize_anchors,
    deserialize_bar_result,
    deserialize_freshness,
    deserialize_momentum,
    deserialize_moving_averages,
    deserialize_patterns,
    deserialize_relative_strength,
    deserialize_volatility,
    deserialize_volume,
    read_json,
    update_run_manifest,
    write_json,
)
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate


def run_packet_build(
    *,
    scan_state_path: str | Path,
    as_of_date: date | None = None,
    environment: EnvironmentName = EnvironmentName.LOCAL,
    config_root: str | Path = "config",
    artifact_root: str | Path = "artifacts",
) -> dict[str, Any]:
    scan_state = read_json(scan_state_path)
    context = build_run_context(
        as_of_date=as_of_date or date.fromisoformat(scan_state["as_of_date"]),
        environment=environment,
        config_root=config_root,
        artifact_root=artifact_root,
    )
    bundles = []
    packet_refs = []
    for symbol, state in sorted(scan_state["symbols"].items()):
        for candidate_payload in state["candidates"]:
            candidate = ScannerCandidate(
                symbol=candidate_payload["symbol"],
                family=SetupFamily(candidate_payload["family"]),
                evidence=tuple(candidate_payload["evidence"]),
                evidence_count=int(candidate_payload["evidence_count"]),
                excess_return_63d=candidate_payload["excess_return_63d"],
                median_dollar_volume_50d=candidate_payload["median_dollar_volume_50d"],
                classification_status=DataSupportStatus(candidate_payload["classification_status"]),
                reason_codes=tuple(candidate_payload["reason_codes"]),
            )
            assembled = assemble_packet(
                PacketAssemblyInput(
                    candidate=candidate,
                    bar_result=deserialize_bar_result(state["bar_result"]),
                    freshness=deserialize_freshness(state["freshness"]),
                    moving_averages=deserialize_moving_averages(state["features"]["moving_averages"]),
                    momentum=deserialize_momentum(state["features"]["momentum"]),
                    volume=deserialize_volume(state["features"]["volume"]),
                    volatility=deserialize_volatility(state["features"]["volatility"]),
                    patterns=deserialize_patterns(state["features"]["patterns"]),
                    relative_strength=deserialize_relative_strength(state["features"]["relative_strength"]),
                    anchors=deserialize_anchors(state["anchors"]),
                    run_id=context.run_id,
                    as_of_date=context.as_of_date,
                    generated_at=context.generated_at,
                    environment=context.environment,
                    config_fingerprint=context.config.fingerprint,
                    artifact_lineage=(artifact_ref("candidate_list", f"scan/candidate_list_{candidate.family.value}.json"),),
                    market_data_provider=MarketDataProvider.YFINANCE,
                    provider_mode=ProviderMode.BASELINE,
                )
            )
            bundle = {
                "packet": assembled.payload,
                "completeness": asdict(assess_packet_completeness(assembled.payload)),
                "trade_plan": asdict(assembled.trade_plan),
                "instrument_context": state["metadata"],
                "bar_result": state["bar_result"],
                "freshness": state["freshness"],
            }
            bundle_path = write_json(context.packets_dir / f"{assembled.payload['packet_id']}.json", assembled.payload)
            packet_refs.append(artifact_ref("packet", str(bundle_path.relative_to(context.run_root))))
            bundles.append(bundle)
    bundle_index_path = write_json(context.packets_dir / "packet_bundles.json", {"packet_bundles": bundles})
    update_run_manifest(context, packet_refs)
    return {
        "run_root": str(context.run_root),
        "packet_bundle_path": str(bundle_index_path),
        "packet_count": len(bundles),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build packets and completeness artifacts from scan state.")
    parser.add_argument("--scan-state", required=True)
    parser.add_argument("--as-of-date")
    parser.add_argument("--environment", default="local", choices=[item.value for item in EnvironmentName])
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--artifact-root", default="artifacts")
    args = parser.parse_args()
    result = run_packet_build(
        scan_state_path=args.scan_state,
        as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        environment=EnvironmentName(args.environment),
        config_root=args.config_root,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
