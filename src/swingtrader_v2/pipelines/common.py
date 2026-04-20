"""Shared helpers for thin pipeline orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from swingtrader_v2.analysis.momentum import MomentumFeatureSet, MomentumMetric
from swingtrader_v2.analysis.moving_averages import MovingAverageFeatureSet, MovingAverageValue
from swingtrader_v2.analysis.patterns import PatternFeatureSet, PatternMetric
from swingtrader_v2.analysis.relative_strength import RelativeStrengthFeatureSet, RelativeStrengthMetric
from swingtrader_v2.analysis.volume import VolumeFeatureSet, VolumeMetric
from swingtrader_v2.analysis.volatility import VolatilityFeatureSet, VolatilityMetric
from swingtrader_v2.anchors.avwap import AvwapProxyResult
from swingtrader_v2.anchors.definitions import AnchorDefinition
from swingtrader_v2.anchors.provenance import AnchorProvenance
from swingtrader_v2.anchors.resolver import ResolvedAnchor
from swingtrader_v2.config.loader import load_effective_config
from swingtrader_v2.config.validator import ensure_valid_config
from swingtrader_v2.data.freshness import FreshnessReport
from swingtrader_v2.domain.enums import DataSupportStatus, EnvironmentName
from swingtrader_v2.domain.ids import build_run_id
from swingtrader_v2.market.bars import BarNormalizationResult, BarSummary, NormalizedBar


@dataclass(frozen=True)
class RunContext:
    as_of_date: date
    generated_at: datetime
    environment: EnvironmentName
    config_root: Path
    artifact_root: Path
    config: Any
    run_id: str

    @property
    def run_root(self) -> Path:
        return self.artifact_root / self.as_of_date.isoformat() / self.run_id

    @property
    def manifests_dir(self) -> Path:
        return self.run_root / "manifests"

    @property
    def scan_dir(self) -> Path:
        return self.run_root / "scan"

    @property
    def packets_dir(self) -> Path:
        return self.run_root / "packets"

    @property
    def rankings_dir(self) -> Path:
        return self.run_root / "rankings"

    @property
    def dashboard_dir(self) -> Path:
        return self.run_root / "dashboard"

    @property
    def tracking_dir(self) -> Path:
        return self.run_root / "tracking"

    @property
    def manifest_path(self) -> Path:
        return self.manifests_dir / "run_manifest.json"


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Unsupported JSON type: {type(value)!r}")


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")
    return target


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def build_run_context(
    *,
    as_of_date: date | None = None,
    generated_at: datetime | None = None,
    environment: EnvironmentName = EnvironmentName.LOCAL,
    config_root: str | Path = "config",
    artifact_root: str | Path = "artifacts",
) -> RunContext:
    config = ensure_valid_config(load_effective_config(config_root, environment=environment))
    current_date = as_of_date or datetime.now(timezone.utc).date()
    current_time = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    universe_name = config.effective.get("universe", {}).get("name", "liquid_us_equities")
    run_id = build_run_id(
        as_of_date=current_date,
        environment=environment.value,
        universe_name=universe_name,
        config_fingerprint=config.fingerprint,
    )
    context = RunContext(
        as_of_date=current_date,
        generated_at=current_time,
        environment=environment,
        config_root=Path(config_root),
        artifact_root=Path(artifact_root),
        config=config,
        run_id=run_id,
    )
    for directory in (
        context.manifests_dir,
        context.scan_dir,
        context.packets_dir,
        context.rankings_dir,
        context.dashboard_dir,
        context.tracking_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return context


def artifact_ref(artifact_type: str, artifact_id: str, schema_version: str = "v1.0.0") -> dict[str, str]:
    return {
        "artifact_type": artifact_type,
        "artifact_id": artifact_id,
        "schema_version": schema_version,
    }


def load_or_init_run_manifest(context: RunContext) -> dict[str, Any]:
    if context.manifest_path.exists():
        return read_json(context.manifest_path)
    manifest = {
        "artifact_type": "run_manifest",
        "schema_version": "v1.0.0",
        "run_id": context.run_id,
        "generated_at": context.generated_at.isoformat().replace("+00:00", "Z"),
        "as_of_date": context.as_of_date.isoformat(),
        "environment": context.environment.value,
        "config_fingerprint": context.config.fingerprint,
        "runtime_mode": "eod",
        "inputs": {
            "market_data_provider": context.config.effective.get("universe", {}).get("providers", {}).get("baseline", "yfinance"),
            "universe_name": context.config.effective.get("universe", {}).get("name", "liquid_us_equities"),
        },
        "artifact_outputs": [],
    }
    write_json(context.manifest_path, manifest)
    return manifest


def update_run_manifest(context: RunContext, artifact_outputs: list[dict[str, Any]]) -> Path:
    manifest = load_or_init_run_manifest(context)
    seen = {(item["artifact_type"], item["artifact_id"], item["schema_version"]) for item in manifest["artifact_outputs"]}
    for item in artifact_outputs:
        key = (item["artifact_type"], item["artifact_id"], item["schema_version"])
        if key not in seen:
            manifest["artifact_outputs"].append(item)
            seen.add(key)
    manifest["artifact_outputs"] = sorted(manifest["artifact_outputs"], key=lambda item: (item["artifact_type"], item["artifact_id"]))
    return write_json(context.manifest_path, manifest)


def load_symbol_metadata(path: str | Path) -> dict[str, dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        return {str(item["symbol"]).upper(): dict(item) for item in payload}
    if isinstance(payload, dict) and "symbol" in payload:
        return {str(payload["symbol"]).upper(): dict(payload)}
    return {str(symbol).upper(): dict(item) for symbol, item in payload.items()}


def load_provider_rows(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    payload = read_json(path)
    return {str(symbol).upper(): list(rows) for symbol, rows in payload.items()}


def anchor_definitions_from_config(config: dict[str, Any]) -> tuple[AnchorDefinition, ...]:
    definitions: list[AnchorDefinition] = []
    for item in config.get("anchors", []):
        name = str(item["name"])
        kind = str(item.get("kind", "")).lower()
        if kind == "swing_point":
            family = "swing_pivot_low" if "low" in name else "swing_pivot_high"
        elif kind == "range_boundary":
            family = "breakout_pivot_day" if "high" in name or "base" in name else "breakdown_pivot_day"
        elif kind == "avwap_proxy":
            family = "swing_pivot_low"
        else:
            family = "swing_pivot_low"
        definitions.append(AnchorDefinition(family=family, name=name, enabled=bool(item.get("enabled", True))))
    return tuple(definitions)


def serialize_bar_result(result: BarNormalizationResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "status": result.status.value,
        "bars": [
            {
                "symbol": bar.symbol,
                "session_date": bar.session_date.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
                "dividend": bar.dividend,
                "split_ratio": bar.split_ratio,
                "adjustment_factor": bar.adjustment_factor,
            }
            for bar in result.bars
        ],
        "summary": {
            "symbol": result.summary.symbol,
            "completed_bars": result.summary.completed_bars,
            "first_bar_date": result.summary.first_bar_date.isoformat() if result.summary.first_bar_date else None,
            "last_bar_date": result.summary.last_bar_date.isoformat() if result.summary.last_bar_date else None,
            "median_50d_volume": result.summary.median_50d_volume,
            "median_50d_dollar_volume": result.summary.median_50d_dollar_volume,
        },
        "reason_codes": list(result.reason_codes),
        "degraded": result.degraded,
        "duplicate_count": result.duplicate_count,
    }


def deserialize_bar_result(payload: dict[str, Any]) -> BarNormalizationResult:
    bars = tuple(
        NormalizedBar(
            symbol=item["symbol"],
            session_date=date.fromisoformat(item["session_date"]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            adjusted_close=float(item["adjusted_close"]),
            volume=int(item["volume"]),
            dividend=float(item["dividend"]),
            split_ratio=float(item["split_ratio"]),
            adjustment_factor=float(item["adjustment_factor"]),
        )
        for item in payload["bars"]
    )
    summary_payload = payload["summary"]
    return BarNormalizationResult(
        symbol=payload["symbol"],
        status=DataSupportStatus(payload["status"]),
        bars=bars,
        summary=BarSummary(
            symbol=summary_payload["symbol"],
            completed_bars=int(summary_payload["completed_bars"]),
            first_bar_date=date.fromisoformat(summary_payload["first_bar_date"]) if summary_payload["first_bar_date"] else None,
            last_bar_date=date.fromisoformat(summary_payload["last_bar_date"]) if summary_payload["last_bar_date"] else None,
            median_50d_volume=float(summary_payload["median_50d_volume"]),
            median_50d_dollar_volume=float(summary_payload["median_50d_dollar_volume"]),
        ),
        reason_codes=tuple(payload["reason_codes"]),
        degraded=bool(payload["degraded"]),
        duplicate_count=int(payload["duplicate_count"]),
    )


def serialize_freshness(report: FreshnessReport) -> dict[str, Any]:
    return {
        "status": report.status.value,
        "expected_session": report.expected_session.isoformat(),
        "last_bar_date": report.last_bar_date.isoformat() if report.last_bar_date else None,
        "stale_sessions": report.stale_sessions,
        "degraded": report.degraded,
        "reason_codes": list(report.reason_codes),
    }


def deserialize_freshness(payload: dict[str, Any]) -> FreshnessReport:
    return FreshnessReport(
        status=DataSupportStatus(payload["status"]),
        expected_session=date.fromisoformat(payload["expected_session"]),
        last_bar_date=date.fromisoformat(payload["last_bar_date"]) if payload["last_bar_date"] else None,
        stale_sessions=int(payload["stale_sessions"]),
        degraded=bool(payload["degraded"]),
        reason_codes=tuple(payload["reason_codes"]),
    )


def serialize_feature_set(feature_set: Any) -> dict[str, Any]:
    payload = asdict(feature_set)
    payload["status"] = feature_set.status.value
    for field in ("values", "metrics"):
        if field in payload:
            payload[field] = [{**item, "status": item["status"].value} for item in payload[field]]
    return payload


def deserialize_moving_averages(payload: dict[str, Any]) -> MovingAverageFeatureSet:
    return MovingAverageFeatureSet(
        status=DataSupportStatus(payload["status"]),
        values=tuple(
            MovingAverageValue(
                name=item["name"],
                value=item["value"],
                slope=item["slope"],
                distance_from_close_pct=item["distance_from_close_pct"],
                status=DataSupportStatus(item["status"]),
                reason=item.get("reason"),
            )
            for item in payload["values"]
        ),
    )


def deserialize_momentum(payload: dict[str, Any]) -> MomentumFeatureSet:
    return MomentumFeatureSet(
        status=DataSupportStatus(payload["status"]),
        metrics=tuple(MomentumMetric(name=item["name"], value=item["value"], status=DataSupportStatus(item["status"]), reason=item.get("reason")) for item in payload["metrics"]),
    )


def deserialize_volume(payload: dict[str, Any]) -> VolumeFeatureSet:
    return VolumeFeatureSet(
        status=DataSupportStatus(payload["status"]),
        metrics=tuple(VolumeMetric(name=item["name"], value=item["value"], status=DataSupportStatus(item["status"]), reason=item.get("reason")) for item in payload["metrics"]),
    )


def deserialize_volatility(payload: dict[str, Any]) -> VolatilityFeatureSet:
    return VolatilityFeatureSet(
        status=DataSupportStatus(payload["status"]),
        metrics=tuple(VolatilityMetric(name=item["name"], value=item["value"], status=DataSupportStatus(item["status"]), reason=item.get("reason")) for item in payload["metrics"]),
    )


def deserialize_patterns(payload: dict[str, Any]) -> PatternFeatureSet:
    return PatternFeatureSet(
        status=DataSupportStatus(payload["status"]),
        metrics=tuple(PatternMetric(name=item["name"], value=item["value"], status=DataSupportStatus(item["status"]), reason=item.get("reason")) for item in payload["metrics"]),
    )


def deserialize_relative_strength(payload: dict[str, Any]) -> RelativeStrengthFeatureSet:
    return RelativeStrengthFeatureSet(
        status=DataSupportStatus(payload["status"]),
        metrics=tuple(RelativeStrengthMetric(name=item["name"], value=item["value"], status=DataSupportStatus(item["status"]), reason=item.get("reason")) for item in payload["metrics"]),
    )


def serialize_anchors(anchors: tuple[ResolvedAnchor, ...]) -> list[dict[str, Any]]:
    serialized = []
    for anchor in anchors:
        serialized.append(
            {
                "anchor_id": anchor.anchor_id,
                "name": anchor.name,
                "family": anchor.family,
                "status": anchor.status,
                "data_status": anchor.data_status.value,
                "value": anchor.value,
                "source": anchor.source,
                "is_daily_proxy": anchor.is_daily_proxy,
                "bar_index": anchor.bar_index,
                "reason": anchor.reason,
                "provenance": {
                    "source_family": anchor.provenance.source_family,
                    "source_name": anchor.provenance.source_name,
                    "source_date": anchor.provenance.source_date.isoformat() if anchor.provenance.source_date else None,
                    "source_bar_index": anchor.provenance.source_bar_index,
                    "notes": list(anchor.provenance.notes),
                },
                "avwap_proxy": None if anchor.avwap_proxy is None else {
                    "status": anchor.avwap_proxy.status.value,
                    "current_avwap": anchor.avwap_proxy.current_avwap,
                    "distance_from_close_pct": anchor.avwap_proxy.distance_from_close_pct,
                    "short_slope": anchor.avwap_proxy.short_slope,
                    "bars_since_anchor": anchor.avwap_proxy.bars_since_anchor,
                    "is_daily_proxy": anchor.avwap_proxy.is_daily_proxy,
                    "reason": anchor.avwap_proxy.reason,
                },
            }
        )
    return serialized


def deserialize_anchors(payload: list[dict[str, Any]]) -> tuple[ResolvedAnchor, ...]:
    anchors = []
    for item in payload:
        avwap = item["avwap_proxy"]
        anchors.append(
            ResolvedAnchor(
                anchor_id=item["anchor_id"],
                name=item["name"],
                family=item["family"],
                status=item["status"],
                data_status=DataSupportStatus(item["data_status"]),
                value=item["value"],
                source=item["source"],
                is_daily_proxy=bool(item["is_daily_proxy"]),
                bar_index=item["bar_index"],
                provenance=AnchorProvenance(
                    source_family=item["provenance"]["source_family"],
                    source_name=item["provenance"]["source_name"],
                    source_date=date.fromisoformat(item["provenance"]["source_date"]) if item["provenance"]["source_date"] else None,
                    source_bar_index=item["provenance"]["source_bar_index"],
                    notes=tuple(item["provenance"]["notes"]),
                ),
                avwap_proxy=None if avwap is None else AvwapProxyResult(
                    status=DataSupportStatus(avwap["status"]),
                    current_avwap=avwap["current_avwap"],
                    distance_from_close_pct=avwap["distance_from_close_pct"],
                    short_slope=avwap["short_slope"],
                    bars_since_anchor=avwap["bars_since_anchor"],
                    is_daily_proxy=bool(avwap["is_daily_proxy"]),
                    reason=avwap.get("reason"),
                ),
                reason=item.get("reason"),
            )
        )
    return tuple(anchors)


def history_store_to_payload(store: Any) -> dict[str, Any]:
    return {
        "records": [
            {
                "sequence": record.sequence,
                "record_type": record.record_type,
                "entity_id": record.entity_id,
                "recorded_at": record.recorded_at,
                "payload": record.payload,
            }
            for record in store.records
        ]
    }


def load_history_store(path: str | Path):
    from swingtrader_v2.tracking.history_store import AppendOnlyHistoryStore, HistoryRecord

    source = Path(path)
    if not source.exists():
        return AppendOnlyHistoryStore()
    payload = read_json(source)
    return AppendOnlyHistoryStore(
        records=tuple(
            HistoryRecord(
                sequence=int(item["sequence"]),
                record_type=item["record_type"],
                entity_id=item["entity_id"],
                recorded_at=item["recorded_at"],
                payload=item["payload"],
            )
            for item in payload.get("records", [])
        )
    )
