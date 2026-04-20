"""Dashboard payload assembly from existing artifacts only."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from swingtrader_v2.domain.enums import ArtifactType
from swingtrader_v2.reporting.contracts import (
    BannerMessage,
    DashboardArtifact,
    DashboardBundle,
    DashboardRenderModel,
    FamilyTable,
    GateFailureGroup,
    OutcomeSummary,
    PacketSummaryCard,
    QueueRow,
    WatchlistChanges,
    validate_dashboard_payload,
)


DASHBOARD_SCHEMA_VERSION = "v1.0.0"
SURVIVORSHIP_BIAS_DISCLOSURE = (
    "Dashboard counts and tables reflect only artifacts captured for the run. "
    "They do not represent delisted names, missing historical constituents, or any symbols omitted upstream."
)


@dataclass(frozen=True)
class DashboardAssemblerInput:
    run_manifest: dict[str, Any]
    ranking: dict[str, Any]
    packets: tuple[dict[str, Any], ...]
    prior_dashboard_payload: dict[str, Any] | None = None


def _artifact_ref(artifact_type: str, artifact_id: str, schema_version: str) -> dict[str, str]:
    return {
        "artifact_type": artifact_type,
        "artifact_id": artifact_id,
        "schema_version": schema_version,
    }


def _packet_map(packets: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {packet["packet_id"]: packet for packet in packets}


def _universe_count(run_manifest: dict[str, Any]) -> int:
    artifact_outputs = run_manifest.get("artifact_outputs", [])
    return sum(1 for item in artifact_outputs if item.get("artifact_type") == "packet")


def _gate_failure_reasons(packet: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    for gate in packet["eligibility_decision"].get("gate_results", []):
        if gate["status"] in {"failed", "unsupported"}:
            message = gate.get("message") or gate["status"]
            reasons.append(f"{gate['rule_name']}: {message}")
    return tuple(reasons)


def _degraded_reasons(packet: dict[str, Any]) -> tuple[str, ...]:
    reasons = [
        f"{issue['field']} ({issue['status']}): {issue['reason']}"
        for issue in packet["data_status"]["issues"]
        if issue["status"] in {"missing", "unsupported", "stale", "low_confidence"}
    ]
    if packet["data_status"]["overall_status"] != "ok" and not reasons:
        reasons.append(f"overall_status={packet['data_status']['overall_status']}")
    return tuple(reasons)


def _queue_row(
    packet: dict[str, Any],
    ranked_entry: dict[str, Any] | None,
    *,
    queue_position: int | None,
    family_rank: int | None,
) -> QueueRow:
    reasons = _degraded_reasons(packet)
    score_components = ranked_entry.get("score_components", []) if ranked_entry else []
    explanations = tuple(
        component.get("reason", f"{component['name']}={component['value']}")
        for component in score_components
    )
    priority_label = ranked_entry.get("priority_band", "UNRANKED") if ranked_entry else "UNRANKED"
    if priority_label == "UNRANKED" and packet["prioritization"]["status"] == "suppressed":
        priority_label = "SUPPRESSED"
    return QueueRow(
        queue_position=queue_position,
        family_rank=family_rank,
        symbol=packet["symbol"],
        setup_family=packet["setup"]["family"],
        priority_label=priority_label,
        eligibility_label=packet["eligibility_decision"]["status"].upper(),
        prioritization_label=packet["prioritization"]["status"].upper(),
        packet_summary=packet["operator_review"]["packet_summary"],
        sort_key_explanations=explanations or ("score_components_not_available_in_ranking_artifact",),
        degraded_reasons=reasons or ("none",),
    )


def _watchlist_changes(
    ranking: dict[str, Any],
    prior_dashboard_payload: dict[str, Any] | None,
) -> WatchlistChanges:
    current = {item["symbol"] for item in ranking.get("ranked_packets", [])}
    previous = set()
    if prior_dashboard_payload:
        previous = {
            row["symbol"]
            for row in prior_dashboard_payload.get("rows", [])
            if row.get("prioritization_status") == "ranked"
        }
    added = tuple(sorted(current - previous))
    removed = tuple(sorted(previous - current))
    unchanged = tuple(sorted(current & previous))
    return WatchlistChanges(added=added, removed=removed, unchanged=unchanged)


def _run_health(packets: tuple[dict[str, Any], ...]) -> BannerMessage:
    degraded_packets = [packet for packet in packets if packet["data_status"]["overall_status"] != "ok"]
    if degraded_packets:
        reasons = sorted(
            {
                issue["status"]
                for packet in degraded_packets
                for issue in packet["data_status"]["issues"]
            }
        )
        return BannerMessage(
            level="warning",
            title="Degraded Run",
            body="Explicit degraded states are present: " + (", ".join(reasons) if reasons else "status_only"),
        )
    return BannerMessage(level="ok", title="Healthy Run", body="All packet artifacts report explicit OK data status.")


def build_dashboard_bundle(input_data: DashboardAssemblerInput) -> DashboardBundle:
    packet_lookup = _packet_map(input_data.packets)
    ranked_packets = input_data.ranking.get("ranked_packets", [])
    ranking_by_packet = {item["packet_id"]: item for item in ranked_packets}
    ranking_positions = {item["packet_id"]: item["rank"] for item in ranked_packets}
    family_ranks: dict[str, dict[str, int]] = defaultdict(dict)
    family_counts: Counter[str] = Counter()
    for item in ranked_packets:
        family = item["setup_family"]
        family_counts[family] += 1
        family_ranks[family][item["packet_id"]] = family_counts[family]

    rows = []
    for packet in sorted(input_data.packets, key=lambda item: (item["setup"]["family"], item["symbol"])):
        row = {
            "packet_id": packet["packet_id"],
            "symbol": packet["symbol"],
            "setup_family": packet["setup"]["family"],
            "eligibility_status": packet["eligibility_decision"]["status"],
            "prioritization_status": packet["prioritization"]["status"],
        }
        rows.append(row)

    artifact = DashboardArtifact(
        payload={
            "artifact_type": ArtifactType.DASHBOARD_PAYLOAD.value,
            "schema_version": DASHBOARD_SCHEMA_VERSION,
            "run_id": input_data.run_manifest["run_id"],
            "generated_at": input_data.ranking["generated_at"],
            "as_of_date": input_data.run_manifest["as_of_date"],
            "environment": input_data.run_manifest["environment"],
            "config_fingerprint": input_data.run_manifest["config_fingerprint"],
            "artifact_inputs": {
                "run_manifest": _artifact_ref("run_manifest", input_data.run_manifest["run_id"], input_data.run_manifest["schema_version"]),
                "ranking": _artifact_ref("ranking", input_data.ranking["run_id"], input_data.ranking["schema_version"]),
                "packets": [
                    _artifact_ref("packet", packet["packet_id"], packet["schema_version"])
                    for packet in sorted(input_data.packets, key=lambda item: item["packet_id"])
                ],
            },
            "summary": {
                "eligible_count": sum(1 for packet in input_data.packets if packet["eligibility_decision"]["status"] == "eligible"),
                "ranked_count": len(ranked_packets),
                "ineligible_count": sum(1 for packet in input_data.packets if packet["eligibility_decision"]["status"] == "ineligible"),
            },
            "rows": rows,
        }
    )
    report = validate_dashboard_payload(artifact.payload)
    if not report.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in report.errors)
        raise ValueError(f"Dashboard payload schema validation failed: {details}")

    eligible_counts = Counter(
        packet["setup"]["family"]
        for packet in input_data.packets
        if packet["eligibility_decision"]["status"] == "eligible"
    )
    queue_rows = tuple(
        _queue_row(
            packet_lookup[item["packet_id"]],
            item,
            queue_position=ranking_positions.get(item["packet_id"]),
            family_rank=family_ranks[item["setup_family"]].get(item["packet_id"]),
        )
        for item in ranked_packets
        if item["packet_id"] in packet_lookup
    )
    families: dict[str, list[QueueRow]] = defaultdict(list)
    for row in queue_rows:
        families[row.setup_family].append(row)

    packet_summaries = tuple(
        PacketSummaryCard(
            symbol=packet["symbol"],
            packet_id=packet["packet_id"],
            setup_family=packet["setup"]["family"],
            summary=packet["operator_review"]["packet_summary"],
            data_status=packet["data_status"]["overall_status"],
            missing_or_unsupported=_degraded_reasons(packet) or ("none",),
        )
        for packet in sorted(input_data.packets, key=lambda item: (item["setup"]["family"], item["symbol"]))
    )
    gate_failures = tuple(
        GateFailureGroup(symbol=packet["symbol"], packet_id=packet["packet_id"], reasons=reasons)
        for packet in sorted(input_data.packets, key=lambda item: item["symbol"])
        if (reasons := _gate_failure_reasons(packet))
    )
    outcome_summary = OutcomeSummary(
        status_counts=dict(
            sorted(Counter(packet["outcomes"]["status"] for packet in input_data.packets).items())
        )
    )
    render_model = DashboardRenderModel(
        title=f"SwingTrader v2 Dashboard - {input_data.run_manifest['as_of_date']}",
        run_health=_run_health(input_data.packets),
        universe_count=_universe_count(input_data.run_manifest),
        candidate_count=len(input_data.packets),
        eligible_counts_by_family=dict(sorted(eligible_counts.items())),
        top_review_queue=queue_rows[:5],
        family_tables=tuple(
            FamilyTable(family=family, rows=tuple(rows))
            for family, rows in sorted(families.items())
        ),
        packet_summaries=packet_summaries,
        gate_failures=gate_failures,
        watchlist_changes=_watchlist_changes(input_data.ranking, input_data.prior_dashboard_payload),
        outcome_summary=outcome_summary,
        survivorship_bias_disclosure=SURVIVORSHIP_BIAS_DISCLOSURE,
    )
    return DashboardBundle(artifact=artifact, render_model=render_model)
