"""Candidate and rejection artifact writers for scanner outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

from swingtrader_v2.domain.enums import ArtifactType, DataSupportStatus, EnvironmentName, SetupFamily
from swingtrader_v2.domain.ids import build_packet_id
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate, ScannerRejection


def _candidate_id(symbol: str, family: SetupFamily, run_id: str) -> str:
    payload = json.dumps({"symbol": symbol, "family": family.value, "run_id": run_id}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"cand_{symbol.lower()}_{digest}"


@dataclass(frozen=True)
class CandidateListArtifact:
    payload: dict


@dataclass(frozen=True)
class RejectionArtifact:
    payload: dict


def write_candidate_list(
    *,
    family: SetupFamily,
    candidates: tuple[ScannerCandidate, ...],
    run_id: str,
    as_of_date: date,
    generated_at: datetime,
    environment: EnvironmentName,
    config_fingerprint: str,
) -> CandidateListArtifact:
    ordered = tuple(candidate for candidate in candidates if candidate.family is family)
    payload = {
        "artifact_type": ArtifactType.CANDIDATE_LIST.value,
        "schema_version": "v1.0.0",
        "run_id": run_id,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": as_of_date.isoformat(),
        "environment": environment.value,
        "config_fingerprint": config_fingerprint,
        "setup_family": family.value,
        "candidates": [
            {
                "candidate_id": _candidate_id(candidate.symbol, candidate.family, run_id),
                "symbol": candidate.symbol,
                "classification_status": candidate.classification_status.value,
                "packet_id": build_packet_id(
                    symbol=candidate.symbol,
                    setup_family=candidate.family.value,
                    as_of_date=as_of_date,
                    run_id=run_id,
                ),
            }
            for candidate in ordered
        ],
    }
    return CandidateListArtifact(payload=payload)


def write_rejections(
    *,
    rejections: tuple[ScannerRejection, ...],
    run_id: str,
    as_of_date: date,
    generated_at: datetime,
    environment: EnvironmentName,
    config_fingerprint: str,
) -> RejectionArtifact:
    payload = {
        "artifact_type": "scanner_rejections",
        "schema_version": "v1.0.0",
        "run_id": run_id,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": as_of_date.isoformat(),
        "environment": environment.value,
        "config_fingerprint": config_fingerprint,
        "rejections": [
            {
                "symbol": rejection.symbol,
                "setup_family": rejection.family.value,
                "classification_status": rejection.classification_status.value,
                "reason_codes": list(rejection.reason_codes),
            }
            for rejection in sorted(rejections, key=lambda item: (item.family.value, item.symbol))
        ],
    }
    return RejectionArtifact(payload=payload)
