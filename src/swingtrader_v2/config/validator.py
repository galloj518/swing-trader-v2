"""Configuration validation for structural and architectural constraints."""

from __future__ import annotations

from typing import Any, Iterable

from swingtrader_v2.domain.enums import DecisionAction, MarketDataProvider, OutcomeHorizon, RuntimeMode, SetupFamily
from swingtrader_v2.domain.exceptions import ConfigValidationError
from swingtrader_v2.domain.models import EffectiveConfig, ValidationIssue, ValidationReport


def _issue(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(path=path, message=message)


def _require_keys(container: dict[str, Any], path: str, keys: Iterable[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in keys:
        if key not in container:
            issues.append(_issue(f"{path}.{key}", "Missing required key."))
    return issues


def _check_duplicates(items: list[dict[str, Any]], key: str, path: str) -> list[ValidationIssue]:
    seen: set[Any] = set()
    issues: list[ValidationIssue] = []
    for index, item in enumerate(items):
        value = item.get(key)
        if value in seen:
            issues.append(_issue(f"{path}[{index}].{key}", f"Duplicate value '{value}'."))
        seen.add(value)
    return issues


def _check_threshold_range(node: dict[str, Any], path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    minimum = node.get("min")
    maximum = node.get("max")
    if minimum is not None and maximum is not None and minimum > maximum:
        issues.append(_issue(path, f"Contradictory thresholds: min {minimum} exceeds max {maximum}."))
    return issues


def validate_effective_config(config: EffectiveConfig) -> ValidationReport:
    data = config.effective
    issues: list[ValidationIssue] = []

    issues.extend(_require_keys(data, "root", ("universe", "runtime", "feature_flags", "setup_families")))

    universe = data.get("universe", {})
    runtime = data.get("runtime", {})
    feature_flags = data.get("feature_flags", {})
    anchors = data.get("anchors", [])
    setup_families = data.get("setup_families", [])
    eligibility = data.get("thresholds", {})
    gates = data.get("gates", [])
    prioritization_components = data.get("components", [])
    tracking = data.get("tracking", {})
    artifacts = data.get("artifacts", {})

    if universe.get("timeframe") != RuntimeMode.EOD.value:
        issues.append(_issue("universe.timeframe", "v1 must remain end-of-day only."))
    if universe.get("country") != "US":
        issues.append(_issue("universe.country", "v1 supports liquid U.S. equities only."))
    if universe.get("providers", {}).get("baseline") != MarketDataProvider.YFINANCE.value:
        issues.append(_issue("universe.providers.baseline", "Baseline provider must be yfinance."))

    if runtime.get("mode") != RuntimeMode.EOD.value:
        issues.append(_issue("runtime.mode", "Runtime mode must be eod."))
    if feature_flags.get("allow_intraday") is not False:
        issues.append(_issue("feature_flags.allow_intraday", "Intraday workflows are not allowed in v1."))
    if feature_flags.get("allow_black_box_ml") is not False:
        issues.append(_issue("feature_flags.allow_black_box_ml", "Black-box ML is not allowed."))
    if feature_flags.get("allow_automated_execution") is not False:
        issues.append(_issue("feature_flags.allow_automated_execution", "Automated execution is not allowed."))
    if feature_flags.get("allow_hidden_discretionary_overrides") is not False:
        issues.append(
            _issue(
                "feature_flags.allow_hidden_discretionary_overrides",
                "Hidden discretionary overrides are not allowed."
            )
        )

    allowed_families = {family.value for family in SetupFamily}
    configured_families = [item.get("name") for item in setup_families]
    issues.extend(_check_duplicates(setup_families, "name", "setup_families"))
    if set(configured_families) != allowed_families:
        issues.append(
            _issue(
                "setup_families",
                "Supported setup families must be exactly trend_pullback, base_breakout, and avwap_reclaim."
            )
        )

    issues.extend(_check_duplicates(anchors, "name", "anchors"))
    for index, anchor in enumerate(anchors):
        if anchor.get("kind") == "avwap_proxy" and anchor.get("is_daily_proxy") is not True:
            issues.append(
                _issue(
                    f"anchors[{index}]",
                    "AVWAP in v1 must be explicitly labeled as a daily-bar proxy."
                )
            )

    if data.get("gate_ordering", {}).get("hard_eligibility_before_prioritization") is not True:
        issues.append(
            _issue(
                "gate_ordering.hard_eligibility_before_prioritization",
                "Hard eligibility must run before prioritization."
            )
        )

    for threshold_name, threshold_value in eligibility.items():
        if isinstance(threshold_value, dict):
            issues.extend(_check_threshold_range(threshold_value, f"thresholds.{threshold_name}"))

    issues.extend(_check_duplicates(gates, "name", "gates"))
    issues.extend(_check_duplicates(prioritization_components, "name", "components"))
    if data.get("hidden_composite_alpha_score") is not False:
        issues.append(_issue("hidden_composite_alpha_score", "Hidden composite alpha score must remain disabled."))
    if data.get("hard_eligibility_required") is not True:
        issues.append(_issue("hard_eligibility_required", "Prioritization must require prior eligibility."))

    total_weight = sum(float(component.get("weight", 0.0)) for component in prioritization_components)
    if prioritization_components and abs(total_weight - 1.0) > 1e-9:
        issues.append(_issue("components", f"Prioritization component weights must sum to 1.0, got {total_weight}."))

    schema_versions = artifacts.get("schema_versions", {})
    required_artifacts = (
        "packet",
        "candidate_list",
        "ranking",
        "dashboard_payload",
        "run_manifest",
        "decision_event",
        "outcome_record"
    )
    missing_artifacts = [name for name in required_artifacts if name not in schema_versions]
    if missing_artifacts:
        issues.append(
            _issue("artifacts.schema_versions", f"Missing schema versions for: {', '.join(missing_artifacts)}.")
        )

    tracking_actions = tracking.get("decision_actions", [])
    if sorted(tracking_actions) != sorted(action.value for action in DecisionAction):
        issues.append(_issue("tracking.decision_actions", "Tracking decision actions do not match supported enum values."))
    tracking_horizons = tracking.get("outcome_horizons", [])
    if sorted(tracking_horizons) != sorted(horizon.value for horizon in OutcomeHorizon):
        issues.append(_issue("tracking.outcome_horizons", "Tracking outcome horizons do not match supported enum values."))

    for family in configured_families:
        if family not in allowed_families:
            issues.append(_issue("setup_families", f"Unsupported setup family '{family}'."))

    return ValidationReport(errors=tuple(issues))


def ensure_valid_config(config: EffectiveConfig) -> EffectiveConfig:
    report = validate_effective_config(config)
    if not report.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in report.errors)
        raise ConfigValidationError(details)
    return config
