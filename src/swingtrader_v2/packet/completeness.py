"""Packet completeness assessment.

Completeness is intentionally distinct from eligibility. A packet can be
partially complete and still be ineligible later, or fully complete and later
rejected by eligibility gates.
"""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.packet.validator import validate_packet


COMPLETE = "complete"
PARTIAL = "partial"
INVALID = "invalid"


@dataclass(frozen=True)
class PacketCompletenessReport:
    state: str
    reason_codes: tuple[str, ...]


def assess_packet_completeness(packet: dict) -> PacketCompletenessReport:
    validation = validate_packet(packet)
    if not validation.ok:
        return PacketCompletenessReport(
            state=INVALID,
            reason_codes=tuple(dict.fromkeys(["schema_or_internal_validation_failed", *(issue.path for issue in validation.errors)])),
        )

    reason_codes: list[str] = []
    status_values = (
        packet["setup"]["classification_status"],
        packet["data_status"]["overall_status"],
        packet["raw_snapshot"]["snapshot_status"],
        packet["derived_features"]["feature_status"],
    )
    if any(value != "ok" for value in status_values):
        reason_codes.extend(f"status:{value}" for value in status_values if value != "ok")

    for issue in packet["data_status"]["issues"]:
        reason_codes.append(f"{issue['field']}:{issue['status']}")

    if not packet["derived_features"]["values"]:
        reason_codes.append("derived_features:empty")
    if not packet["anchor_set"]:
        reason_codes.append("anchor_set:empty")

    if reason_codes:
        return PacketCompletenessReport(state=PARTIAL, reason_codes=tuple(dict.fromkeys(reason_codes)))
    return PacketCompletenessReport(state=COMPLETE, reason_codes=())
