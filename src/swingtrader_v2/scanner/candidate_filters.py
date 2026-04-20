"""Scanner-stage rejection taxonomy and deterministic candidate ordering."""

from __future__ import annotations

from dataclasses import dataclass

from swingtrader_v2.analysis.relative_strength import RelativeStrengthFeatureSet
from swingtrader_v2.analysis.volume import VolumeFeatureSet
from swingtrader_v2.domain.enums import DataSupportStatus, SetupFamily
from swingtrader_v2.scanner.detectors import DetectorResult


def _metric_value(items, name: str):
    for item in items:
        if item.name == name:
            return item.value
    return None


@dataclass(frozen=True)
class ScannerCandidate:
    symbol: str
    family: SetupFamily
    evidence: tuple[str, ...]
    evidence_count: int
    excess_return_63d: float | None
    median_dollar_volume_50d: float | None
    classification_status: DataSupportStatus
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ScannerRejection:
    symbol: str
    family: SetupFamily
    reason_codes: tuple[str, ...]
    classification_status: DataSupportStatus


def build_scanner_candidate(
    *,
    symbol: str,
    detector: DetectorResult,
    relative_strength: RelativeStrengthFeatureSet,
    volume: VolumeFeatureSet,
) -> ScannerCandidate:
    return ScannerCandidate(
        symbol=symbol,
        family=detector.family,
        evidence=detector.evidence,
        evidence_count=len(detector.evidence),
        excess_return_63d=_metric_value(relative_strength.metrics, "excess_return_vs_spy_63d"),
        median_dollar_volume_50d=_metric_value(volume.metrics, "median_dollar_volume_50d"),
        classification_status=detector.data_status,
        reason_codes=(),
    )


def build_scanner_rejection(*, symbol: str, detector: DetectorResult) -> ScannerRejection:
    return ScannerRejection(
        symbol=symbol,
        family=detector.family,
        reason_codes=detector.rejection_reasons,
        classification_status=detector.data_status,
    )


def split_candidates_and_rejections(
    *,
    symbol: str,
    detectors: tuple[DetectorResult, ...],
    relative_strength: RelativeStrengthFeatureSet,
    volume: VolumeFeatureSet,
) -> tuple[tuple[ScannerCandidate, ...], tuple[ScannerRejection, ...]]:
    candidates: list[ScannerCandidate] = []
    rejections: list[ScannerRejection] = []
    for detector in detectors:
        if detector.detected:
            candidates.append(
                build_scanner_candidate(
                    symbol=symbol,
                    detector=detector,
                    relative_strength=relative_strength,
                    volume=volume,
                )
            )
        else:
            rejections.append(build_scanner_rejection(symbol=symbol, detector=detector))
    return order_candidates(tuple(candidates)), tuple(sorted(rejections, key=lambda item: (item.family.value, item.symbol)))


def order_candidates(candidates: tuple[ScannerCandidate, ...]) -> tuple[ScannerCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.family.value,
                -item.evidence_count,
                -(item.excess_return_63d if item.excess_return_63d is not None else float("-inf")),
                -(item.median_dollar_volume_50d if item.median_dollar_volume_50d is not None else float("-inf")),
                item.symbol,
            ),
        )
    )
