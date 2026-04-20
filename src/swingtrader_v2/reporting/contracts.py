"""Reporting-layer contracts and schema validation helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from swingtrader_v2.domain.models import ValidationIssue, ValidationReport


ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_SCHEMA_PATH = ROOT / "schemas" / "dashboard_payload.schema.json"


@dataclass(frozen=True)
class DashboardArtifact:
    payload: dict[str, Any]


@dataclass(frozen=True)
class BannerMessage:
    level: str
    title: str
    body: str


@dataclass(frozen=True)
class QueueRow:
    queue_position: int | None
    family_rank: int | None
    symbol: str
    setup_family: str
    priority_label: str
    eligibility_label: str
    prioritization_label: str
    packet_summary: str
    sort_key_explanations: tuple[str, ...]
    degraded_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FamilyTable:
    family: str
    rows: tuple[QueueRow, ...]


@dataclass(frozen=True)
class PacketSummaryCard:
    symbol: str
    packet_id: str
    setup_family: str
    summary: str
    data_status: str
    missing_or_unsupported: tuple[str, ...]


@dataclass(frozen=True)
class GateFailureGroup:
    symbol: str
    packet_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WatchlistChanges:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]


@dataclass(frozen=True)
class OutcomeSummary:
    status_counts: dict[str, int]


@dataclass(frozen=True)
class DashboardRenderModel:
    title: str
    run_health: BannerMessage
    universe_count: int
    candidate_count: int
    eligible_counts_by_family: dict[str, int]
    top_review_queue: tuple[QueueRow, ...]
    family_tables: tuple[FamilyTable, ...]
    packet_summaries: tuple[PacketSummaryCard, ...]
    gate_failures: tuple[GateFailureGroup, ...]
    watchlist_changes: WatchlistChanges
    outcome_summary: OutcomeSummary
    survivorship_bias_disclosure: str


@dataclass(frozen=True)
class DashboardBundle:
    artifact: DashboardArtifact
    render_model: DashboardRenderModel


def _issue(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(path=path, message=message)


def _load_schema() -> dict[str, Any]:
    return json.loads(DASHBOARD_SCHEMA_PATH.read_text(encoding="utf-8"))


def _resolve_ref(schema: dict[str, Any], reference: str) -> dict[str, Any]:
    node: Any = schema
    for part in reference.removeprefix("#/").split("/"):
        node = node[part]
    return node


def _matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    return True


def _valid_format(value: str, format_name: str) -> bool:
    try:
        if format_name == "date":
            date.fromisoformat(value)
            return True
        if format_name == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
    except ValueError:
        return False
    return True


def _validate_node(*, value: Any, spec: dict[str, Any], schema: dict[str, Any], path: str, errors: list[ValidationIssue]) -> None:
    if "$ref" in spec:
        _validate_node(value=value, spec=_resolve_ref(schema, spec["$ref"]), schema=schema, path=path, errors=errors)
        return

    expected_type = spec.get("type")
    if isinstance(expected_type, list):
        if not any(_matches_type(value, item) for item in expected_type):
            errors.append(_issue(path, f"Expected one of types {expected_type}."))
            return
    elif isinstance(expected_type, str) and not _matches_type(value, expected_type):
        errors.append(_issue(path, f"Expected type '{expected_type}'."))
        return

    if "const" in spec and value != spec["const"]:
        errors.append(_issue(path, f"Expected constant value {spec['const']!r}."))
    if "enum" in spec and value not in spec["enum"]:
        errors.append(_issue(path, f"Expected one of {spec['enum']!r}."))
    if isinstance(value, str):
        if "minLength" in spec and len(value) < spec["minLength"]:
            errors.append(_issue(path, f"String shorter than {spec['minLength']}."))
        if "pattern" in spec and re.match(spec["pattern"], value) is None:
            errors.append(_issue(path, f"String does not match pattern {spec['pattern']!r}."))
        if "format" in spec and not _valid_format(value, spec["format"]):
            errors.append(_issue(path, f"String does not satisfy format {spec['format']!r}."))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(_issue(path, f"Value below minimum {spec['minimum']}."))

    if isinstance(value, dict):
        required = spec.get("required", [])
        for key in required:
            if key not in value:
                errors.append(_issue(f"{path}.{key}", "Missing required field."))
        properties = spec.get("properties", {})
        if spec.get("additionalProperties") is False:
            for extra in sorted(key for key in value if key not in properties):
                errors.append(_issue(f"{path}.{extra}", "Unexpected field."))
        for key, child_spec in properties.items():
            if key in value:
                _validate_node(value=value[key], spec=child_spec, schema=schema, path=f"{path}.{key}", errors=errors)
        return

    if isinstance(value, list) and "items" in spec:
        for index, item in enumerate(value):
            _validate_node(value=item, spec=spec["items"], schema=schema, path=f"{path}[{index}]", errors=errors)


def validate_dashboard_payload(payload: dict[str, Any]) -> ValidationReport:
    schema = _load_schema()
    errors: list[ValidationIssue] = []
    _validate_node(value=payload, spec=schema, schema=schema, path="dashboard_payload", errors=errors)
    return ValidationReport(errors=tuple(errors))
