"""Primary setup-family classification over scanner detections."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.domain.enums import DataSupportStatus, SetupFamily
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate


DEFAULT_SETUP_PRIORITIES: dict[SetupFamily, int] = {
    SetupFamily.TREND_PULLBACK: 1,
    SetupFamily.BASE_BREAKOUT: 2,
    SetupFamily.AVWAP_RECLAIM: 3,
}


@dataclass(frozen=True)
class FamilyResolution:
    family: SetupFamily
    decision: str
    evidence_count: int
    priority_order: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ClassificationResult:
    primary_family: SetupFamily | None
    primary_candidate: ScannerCandidate | None
    secondary_tags: tuple[str, ...]
    resolutions: tuple[FamilyResolution, ...]
    disqualification_reasons: tuple[str, ...]


def _setup_priorities(config: dict | None = None) -> dict[SetupFamily, int]:
    if not config:
        return dict(DEFAULT_SETUP_PRIORITIES)
    priorities: dict[SetupFamily, int] = {}
    for item in config.get("setup_families", ()):
        try:
            family = SetupFamily(item["name"])
        except Exception:
            continue
        priorities[family] = int(item.get("priority_order", DEFAULT_SETUP_PRIORITIES[family]))
    return priorities or dict(DEFAULT_SETUP_PRIORITIES)


def _eligible_candidates(candidates: tuple[ScannerCandidate, ...], priorities: dict[SetupFamily, int]) -> tuple[ScannerCandidate, ...]:
    return tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate.family in priorities and candidate.classification_status not in {DataSupportStatus.MISSING, DataSupportStatus.UNSUPPORTED}
            ),
            key=lambda item: (
                priorities[item.family],
                -item.evidence_count,
                -(item.excess_return_63d if item.excess_return_63d is not None else float("-inf")),
                -(item.median_dollar_volume_50d if item.median_dollar_volume_50d is not None else float("-inf")),
                item.symbol,
            ),
        )
    )


def _promotion_candidate(candidates: tuple[ScannerCandidate, ...], priorities: dict[SetupFamily, int]) -> ScannerCandidate:
    return sorted(
        candidates,
        key=lambda item: (
            -item.evidence_count,
            -(item.excess_return_63d if item.excess_return_63d is not None else float("-inf")),
            priorities[item.family],
            -(item.median_dollar_volume_50d if item.median_dollar_volume_50d is not None else float("-inf")),
            item.symbol,
        ),
    )[0]


def classify_candidates(
    candidates: tuple[ScannerCandidate, ...],
    *,
    config: dict | None = None,
) -> ClassificationResult:
    priorities = _setup_priorities(config)
    eligible = _eligible_candidates(candidates, priorities)
    if not eligible:
        return ClassificationResult(
            primary_family=None,
            primary_candidate=None,
            secondary_tags=(),
            resolutions=tuple(
                FamilyResolution(
                    family=candidate.family,
                    decision="disqualified",
                    evidence_count=candidate.evidence_count,
                    priority_order=priorities.get(candidate.family, 999),
                    reason_codes=tuple(dict.fromkeys((*candidate.reason_codes, "unsupported_or_missing_scanner_status"))),
                )
                for candidate in sorted(candidates, key=lambda item: item.family.value)
            ),
            disqualification_reasons=("no_supported_detected_families",),
        )

    default_primary = eligible[0]
    promoted = _promotion_candidate(eligible, priorities)
    primary = promoted if promoted.evidence_count > default_primary.evidence_count else default_primary

    secondary_tags: list[str] = []
    disqualification_reasons: list[str] = []
    resolutions: list[FamilyResolution] = []
    overlap = len(eligible) > 1
    if overlap:
        secondary_tags.append("multi_family_overlap")
    if primary is not default_primary:
        secondary_tags.append(f"promoted_{primary.family.value}")
        disqualification_reasons.append(
            f"primary_promoted_from_{default_primary.family.value}_to_{primary.family.value}_for_stronger_evidence"
        )

    for candidate in sorted(candidates, key=lambda item: item.family.value):
        priority_order = priorities.get(candidate.family, 999)
        if candidate is primary:
            reasons = ("selected_as_primary",)
            if candidate is not default_primary:
                reasons = ("promoted_for_stronger_evidence",)
            decision = "primary"
        elif candidate in eligible:
            decision = "secondary"
            demotion_reason = (
                "demoted_for_lower_evidence"
                if candidate.evidence_count < primary.evidence_count
                else "demoted_by_family_priority_order"
            )
            reasons = tuple(dict.fromkeys((demotion_reason, *candidate.reason_codes)))
            secondary_tags.append(candidate.family.value)
            disqualification_reasons.append(f"{candidate.family.value}:{demotion_reason}")
        else:
            decision = "disqualified"
            reasons = tuple(dict.fromkeys((*candidate.reason_codes, "unsupported_or_missing_scanner_status")))
            disqualification_reasons.append(f"{candidate.family.value}:unsupported_or_missing_scanner_status")
        resolutions.append(
            FamilyResolution(
                family=candidate.family,
                decision=decision,
                evidence_count=candidate.evidence_count,
                priority_order=priority_order,
                reason_codes=reasons,
            )
        )

    return ClassificationResult(
        primary_family=primary.family,
        primary_candidate=primary,
        secondary_tags=tuple(dict.fromkeys(secondary_tags)),
        resolutions=tuple(resolutions),
        disqualification_reasons=tuple(dict.fromkeys(disqualification_reasons)),
    )
