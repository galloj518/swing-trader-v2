"""Typed contract models for Phase 1 foundation artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from swingtrader_v2.domain.enums import (
    ArtifactType,
    DataSupportStatus,
    EligibilityStatus,
    EnvironmentName,
    GateResultStatus,
    OutcomeStatus,
    PrioritizationMethod,
    PrioritizationStatus,
    ProviderMode,
    ReviewStatus,
    RuntimeMode,
    SetupFamily
)


@dataclass(frozen=True)
class ArtifactRef:
    artifact_type: ArtifactType
    artifact_id: str
    schema_version: str


@dataclass(frozen=True)
class DataIssue:
    field: str
    status: DataSupportStatus
    reason: str


@dataclass(frozen=True)
class NamedValue:
    name: str
    status: DataSupportStatus
    value: float | int | str | bool
    units: str | None = None


@dataclass(frozen=True)
class RuleEvaluation:
    rule_name: str
    status: GateResultStatus
    message: str | None = None


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    weight: float
    value: float
    reason: str | None = None


@dataclass(frozen=True)
class PacketMetadata:
    artifact_type: ArtifactType
    schema_version: str
    packet_id: str
    run_id: str
    generated_at: str
    as_of_date: str
    environment: EnvironmentName
    config_fingerprint: str
    symbol: str
    setup_family: SetupFamily


@dataclass(frozen=True)
class PacketContract:
    metadata: PacketMetadata
    data_issues: tuple[DataIssue, ...] = ()
    derived_features: tuple[NamedValue, ...] = ()
    gate_results: tuple[RuleEvaluation, ...] = ()
    score_components: tuple[ScoreComponent, ...] = ()


@dataclass(frozen=True)
class RunManifestContract:
    artifact_type: ArtifactType
    schema_version: str
    run_id: str
    generated_at: str
    as_of_date: str
    environment: EnvironmentName
    config_fingerprint: str
    runtime_mode: RuntimeMode
    inputs: dict[str, Any]
    artifact_outputs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True)
class EffectiveConfig:
    environment: EnvironmentName
    documents: dict[str, dict[str, Any]]
    effective: dict[str, Any]
    fingerprint: str


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PacketState:
    eligibility_status: EligibilityStatus
    prioritization_status: PrioritizationStatus
    prioritization_method: PrioritizationMethod
    review_status: ReviewStatus
    outcome_status: OutcomeStatus
    provider_mode: ProviderMode
