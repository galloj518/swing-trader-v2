"""Packet validation against internal expectations and schema contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from swingtrader_v2.domain.enums import DataSupportStatus, SetupFamily
from swingtrader_v2.domain.exceptions import SchemaContractError
from swingtrader_v2.domain.ids import build_packet_id
from swingtrader_v2.domain.models import ValidationIssue, ValidationReport


ROOT = Path(__file__).resolve().parents[3]
PACKET_SCHEMA_PATH = ROOT / "schemas" / "packet.schema.json"


@dataclass(frozen=True)
class PacketValidationReport(ValidationReport):
    pass


def _issue(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(path=path, message=message)


def _load_schema() -> dict[str, Any]:
    return json.loads(PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))


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
            extras = sorted(key for key in value if key not in properties)
            for extra in extras:
                errors.append(_issue(f"{path}.{extra}", "Unexpected field."))
        for key, child_spec in properties.items():
            if key in value:
                _validate_node(value=value[key], spec=child_spec, schema=schema, path=f"{path}.{key}", errors=errors)
        return

    if isinstance(value, list) and "items" in spec:
        for index, item in enumerate(value):
            _validate_node(value=item, spec=spec["items"], schema=schema, path=f"{path}[{index}]", errors=errors)


def _validate_internal_expectations(packet: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    try:
        as_of_date = date.fromisoformat(packet["as_of_date"])
    except Exception:
        return issues

    expected_packet_id = build_packet_id(
        symbol=packet["symbol"],
        setup_family=packet["setup"]["family"],
        as_of_date=as_of_date,
        run_id=packet["run_id"],
    )
    if packet.get("packet_id") != expected_packet_id:
        issues.append(_issue("packet_id", "Packet ID is not deterministic for the provided inputs."))

    feature_names = [item["name"] for item in packet.get("derived_features", {}).get("values", [])]
    if len(feature_names) != len(set(feature_names)):
        issues.append(_issue("derived_features.values", "Duplicate feature names are not allowed."))

    anchor_ids = [item["anchor_id"] for item in packet.get("anchor_set", [])]
    if len(anchor_ids) != len(set(anchor_ids)):
        issues.append(_issue("anchor_set", "Duplicate anchor IDs are not allowed."))

    anchor_names = [item["name"] for item in packet.get("anchor_set", [])]
    if len(anchor_names) != len(set(anchor_names)):
        issues.append(_issue("anchor_set", "Duplicate anchor names are not allowed."))

    valid_statuses = {status.value for status in DataSupportStatus}
    if packet.get("data_status", {}).get("overall_status") not in valid_statuses:
        issues.append(_issue("data_status.overall_status", "Unknown data support status."))
    if packet.get("setup", {}).get("family") not in {family.value for family in SetupFamily}:
        issues.append(_issue("setup.family", "Unsupported setup family."))
    return issues


def validate_packet(packet: dict[str, Any]) -> PacketValidationReport:
    schema = _load_schema()
    errors: list[ValidationIssue] = []
    _validate_node(value=packet, spec=schema, schema=schema, path="packet", errors=errors)
    errors.extend(_validate_internal_expectations(packet))
    return PacketValidationReport(errors=tuple(errors))


def ensure_valid_packet(packet: dict[str, Any]) -> dict[str, Any]:
    report = validate_packet(packet)
    if not report.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in report.errors)
        raise SchemaContractError(details)
    return packet
