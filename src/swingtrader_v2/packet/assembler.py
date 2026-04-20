"""Canonical packet assembly for scanner-routed candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from swingtrader_v2.analysis.momentum import MomentumFeatureSet
from swingtrader_v2.analysis.moving_averages import MovingAverageFeatureSet
from swingtrader_v2.analysis.patterns import PatternFeatureSet
from swingtrader_v2.analysis.relative_strength import RelativeStrengthFeatureSet
from swingtrader_v2.analysis.volatility import VolatilityFeatureSet
from swingtrader_v2.analysis.volume import VolumeFeatureSet
from swingtrader_v2.anchors.resolver import ResolvedAnchor
from swingtrader_v2.data.freshness import FreshnessReport
from swingtrader_v2.domain.enums import (
    ArtifactType,
    DataSupportStatus,
    EligibilityStatus,
    EnvironmentName,
    MarketDataProvider,
    OutcomeStatus,
    PrioritizationMethod,
    PrioritizationStatus,
    ProviderMode,
    ReviewStatus,
)
from swingtrader_v2.domain.ids import build_packet_id
from swingtrader_v2.domain.models import ArtifactRef
from swingtrader_v2.market.bars import BarNormalizationResult
from swingtrader_v2.packet.trade_plan import TradePlanScaffold, build_trade_plan_scaffold
from swingtrader_v2.packet.validator import ensure_valid_packet
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate


PACKET_SCHEMA_VERSION = "v1.0.0"


@dataclass(frozen=True)
class PacketAssemblyInput:
    candidate: ScannerCandidate
    bar_result: BarNormalizationResult
    freshness: FreshnessReport
    moving_averages: MovingAverageFeatureSet
    momentum: MomentumFeatureSet
    volume: VolumeFeatureSet
    volatility: VolatilityFeatureSet
    patterns: PatternFeatureSet
    relative_strength: RelativeStrengthFeatureSet
    anchors: tuple[ResolvedAnchor, ...]
    run_id: str
    as_of_date: date
    generated_at: datetime
    environment: EnvironmentName
    config_fingerprint: str
    artifact_lineage: tuple[ArtifactRef | dict, ...] = ()
    market_data_provider: MarketDataProvider = MarketDataProvider.YFINANCE
    provider_mode: ProviderMode = ProviderMode.BASELINE


@dataclass(frozen=True)
class AssembledPacket:
    payload: dict
    trade_plan: TradePlanScaffold


def _status_rank(status: DataSupportStatus) -> int:
    return {
        DataSupportStatus.OK: 0,
        DataSupportStatus.LOW_CONFIDENCE: 1,
        DataSupportStatus.STALE: 2,
        DataSupportStatus.UNSUPPORTED: 3,
        DataSupportStatus.MISSING: 4,
    }[status]


def _combine_statuses(statuses: list[DataSupportStatus]) -> DataSupportStatus:
    return max(statuses, key=_status_rank) if statuses else DataSupportStatus.OK


def _artifact_ref_to_payload(reference: ArtifactRef | dict) -> dict:
    if isinstance(reference, ArtifactRef):
        return {
            "artifact_type": reference.artifact_type.value,
            "artifact_id": reference.artifact_id,
            "schema_version": reference.schema_version,
        }
    return dict(reference)


def _metric_issue(field: str, status: DataSupportStatus, reason: str | None) -> dict:
    return {
        "field": field,
        "status": status.value,
        "reason": reason or "status_not_ok",
    }


def _append_named_value(
    *,
    values: list[dict],
    issues: list[dict],
    name: str,
    status: DataSupportStatus,
    value,
    units: str | None = None,
    reason: str | None = None,
) -> None:
    if value is None:
        issue_status = status if status is not DataSupportStatus.OK else DataSupportStatus.LOW_CONFIDENCE
        issues.append(_metric_issue(f"derived_features.{name}", issue_status, reason))
        return
    payload = {
        "name": name,
        "status": status.value,
        "value": value,
    }
    if units is not None:
        payload["units"] = units
    values.append(payload)


def _append_feature_sets(
    *,
    values: list[dict],
    issues: list[dict],
    moving_averages: MovingAverageFeatureSet,
    momentum: MomentumFeatureSet,
    volume: VolumeFeatureSet,
    volatility: VolatilityFeatureSet,
    patterns: PatternFeatureSet,
    relative_strength: RelativeStrengthFeatureSet,
    anchors: tuple[ResolvedAnchor, ...],
) -> DataSupportStatus:
    statuses = [
        moving_averages.status,
        momentum.status,
        volume.status,
        volatility.status,
        patterns.status,
        relative_strength.status,
    ]

    for metric in moving_averages.values:
        _append_named_value(values=values, issues=issues, name=metric.name, status=metric.status, value=metric.value, reason=metric.reason)
        _append_named_value(
            values=values,
            issues=issues,
            name=f"{metric.name}_slope",
            status=metric.status,
            value=metric.slope,
            units="ratio",
            reason=metric.reason or f"{metric.name}_slope_unavailable",
        )
        _append_named_value(
            values=values,
            issues=issues,
            name=f"{metric.name}_distance_from_close_pct",
            status=metric.status,
            value=metric.distance_from_close_pct,
            units="pct",
            reason=metric.reason or f"{metric.name}_distance_unavailable",
        )

    for collection in (momentum.metrics, volume.metrics, volatility.metrics, patterns.metrics, relative_strength.metrics):
        for metric in collection:
            units = "pct" if "pct" in metric.name or "return" in metric.name or "ratio" in metric.name or "percentile" in metric.name else None
            _append_named_value(values=values, issues=issues, name=metric.name, status=metric.status, value=metric.value, units=units, reason=metric.reason)

    for anchor in anchors:
        if anchor.avwap_proxy is None:
            continue
        proxy = anchor.avwap_proxy
        statuses.append(proxy.status)
        prefix = f"avwap_proxy.{anchor.name}"
        _append_named_value(
            values=values,
            issues=issues,
            name=f"{prefix}.current",
            status=proxy.status,
            value=proxy.current_avwap,
            reason=proxy.reason,
        )
        _append_named_value(
            values=values,
            issues=issues,
            name=f"{prefix}.distance_from_close_pct",
            status=proxy.status,
            value=proxy.distance_from_close_pct,
            units="pct",
            reason=proxy.reason or "avwap_distance_unavailable",
        )
        _append_named_value(
            values=values,
            issues=issues,
            name=f"{prefix}.short_slope",
            status=proxy.status,
            value=proxy.short_slope,
            units="ratio",
            reason=proxy.reason or "avwap_short_slope_unavailable",
        )
        _append_named_value(
            values=values,
            issues=issues,
            name=f"{prefix}.bars_since_anchor",
            status=proxy.status,
            value=proxy.bars_since_anchor,
            reason=proxy.reason or "bars_since_anchor_unavailable",
        )

    return _combine_statuses(statuses)


def _anchor_payload(anchor: ResolvedAnchor) -> dict | None:
    if anchor.value is None:
        return None
    return {
        "anchor_id": anchor.anchor_id,
        "name": anchor.name,
        "status": anchor.data_status.value,
        "value": anchor.value,
        "source": anchor.source,
        "is_daily_proxy": anchor.is_daily_proxy,
    }


def _issue_codes_to_issues(field_prefix: str, status: DataSupportStatus, codes: tuple[str, ...]) -> list[dict]:
    return [_metric_issue(f"{field_prefix}.{code}", status, code) for code in codes]


def _latest_bar_payload(bar_result: BarNormalizationResult) -> dict:
    if not bar_result.bars:
        raise ValueError("Cannot assemble packet raw snapshot without at least one normalized bar.")
    last_bar = bar_result.bars[-1]
    return {
        "open": last_bar.open,
        "high": last_bar.high,
        "low": last_bar.low,
        "close": last_bar.close,
        "volume": last_bar.volume,
    }


def _liquidity_payload(bar_result: BarNormalizationResult) -> dict:
    trailing = bar_result.bars[-20:] if len(bar_result.bars) >= 20 else bar_result.bars
    if not trailing:
        raise ValueError("Cannot assemble packet liquidity without normalized bars.")
    avg_volume = sum(bar.volume for bar in trailing) / len(trailing)
    avg_dollar_volume = sum(bar.dollar_volume for bar in trailing) / len(trailing)
    return {
        "avg_daily_volume_20d": float(avg_volume),
        "avg_daily_dollar_volume_20d": float(avg_dollar_volume),
    }


def assemble_packet(payload: PacketAssemblyInput) -> AssembledPacket:
    candidate = payload.candidate
    last_bar = payload.bar_result.bars[-1] if payload.bar_result.bars else None
    close = last_bar.close if last_bar else None
    trade_plan = build_trade_plan_scaffold(
        candidate=candidate,
        close=close,
        moving_averages=payload.moving_averages,
        patterns=payload.patterns,
        anchors=payload.anchors,
    )

    issues: list[dict] = []
    issues.extend(_issue_codes_to_issues("raw_snapshot", payload.bar_result.status, payload.bar_result.reason_codes))
    issues.extend(_issue_codes_to_issues("raw_snapshot.coverage", payload.freshness.status, payload.freshness.reason_codes))

    feature_values: list[dict] = []
    feature_status = _append_feature_sets(
        values=feature_values,
        issues=issues,
        moving_averages=payload.moving_averages,
        momentum=payload.momentum,
        volume=payload.volume,
        volatility=payload.volatility,
        patterns=payload.patterns,
        relative_strength=payload.relative_strength,
        anchors=payload.anchors,
    )

    anchor_payloads: list[dict] = []
    for anchor in payload.anchors:
        built = _anchor_payload(anchor)
        if built is not None:
            anchor_payloads.append(built)
        elif anchor.data_status is not DataSupportStatus.OK:
            issues.append(_metric_issue(f"anchor_set.{anchor.name}", anchor.data_status, anchor.reason))

    snapshot_status = _combine_statuses([payload.bar_result.status, payload.freshness.status])
    overall_status = _combine_statuses(
        [
            snapshot_status,
            feature_status,
            candidate.classification_status,
            *[anchor.data_status for anchor in payload.anchors],
        ]
    )
    generated_at = payload.generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    packet_id = build_packet_id(
        symbol=candidate.symbol,
        setup_family=candidate.family.value,
        as_of_date=payload.as_of_date,
        run_id=payload.run_id,
    )
    packet = {
        "artifact_type": ArtifactType.PACKET.value,
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_id": packet_id,
        "run_id": payload.run_id,
        "generated_at": generated_at,
        "as_of_date": payload.as_of_date.isoformat(),
        "environment": payload.environment.value,
        "config_fingerprint": payload.config_fingerprint,
        "symbol": candidate.symbol,
        "setup": {
            "family": candidate.family.value,
            "classification_status": candidate.classification_status.value,
            "scanner_label": f"detected:{candidate.family.value}",
            "scanner_notes": list(candidate.evidence),
        },
        "data_status": {
            "overall_status": overall_status.value,
            "issues": sorted(issues, key=lambda item: (item["field"], item["status"], item["reason"])),
        },
        "provenance": {
            "market_data_provider": payload.market_data_provider.value,
            "provider_mode": payload.provider_mode.value,
            "artifact_lineage": [_artifact_ref_to_payload(reference) for reference in payload.artifact_lineage],
        },
        "raw_snapshot": {
            "snapshot_status": snapshot_status.value,
            "price_bar": _latest_bar_payload(payload.bar_result),
            "liquidity": _liquidity_payload(payload.bar_result),
            "coverage": {
                "bars_available": payload.bar_result.summary.completed_bars,
                "last_bar_date": payload.freshness.last_bar_date.isoformat() if payload.freshness.last_bar_date else payload.as_of_date.isoformat(),
                "staleness_days": payload.freshness.stale_sessions,
            },
        },
        "derived_features": {
            "feature_status": feature_status.value,
            "values": sorted(feature_values, key=lambda item: item["name"]),
        },
        "anchor_set": sorted(anchor_payloads, key=lambda item: (item["name"], item["anchor_id"])),
        "eligibility_decision": {
            "status": EligibilityStatus.INDETERMINATE.value,
            "gate_results": [],
        },
        "prioritization": {
            "status": PrioritizationStatus.NOT_APPLICABLE.value,
            "method": PrioritizationMethod.TRANSPARENT_WEIGHTED_SUM.value,
            "score_components": [],
        },
        "operator_review": {
            "status": ReviewStatus.NOT_REVIEWED.value,
            "packet_summary": trade_plan.to_summary(),
        },
        "outcomes": {
            "status": OutcomeStatus.NOT_STARTED.value,
            "outcome_record_refs": [],
        },
    }
    ensure_valid_packet(packet)
    return AssembledPacket(payload=packet, trade_plan=trade_plan)
