"""Phase-oriented orchestration for daily EOD scan artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from swingtrader_v2.analysis.momentum import compute_momentum_features
from swingtrader_v2.analysis.moving_averages import compute_moving_averages
from swingtrader_v2.analysis.patterns import compute_pattern_features
from swingtrader_v2.analysis.relative_strength import compute_relative_strength_features
from swingtrader_v2.analysis.volume import compute_volume_features
from swingtrader_v2.analysis.volatility import compute_volatility_features
from swingtrader_v2.anchors.resolver import resolve_anchors
from swingtrader_v2.data.freshness import assess_freshness
from swingtrader_v2.data.sources import ProviderBarsPayload, YFinanceDailyBarSource
from swingtrader_v2.data.symbol_master import build_symbol_master_snapshot
from swingtrader_v2.domain.enums import EnvironmentName, SetupFamily
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.market.benchmarks import prepare_spy_benchmark
from swingtrader_v2.market.universe_builder import build_universe_snapshot
from swingtrader_v2.pipelines.common import (
    anchor_definitions_from_config,
    artifact_ref,
    build_run_context,
    load_provider_rows,
    load_symbol_metadata,
    serialize_anchors,
    serialize_bar_result,
    serialize_feature_set,
    serialize_freshness,
    update_run_manifest,
    write_json,
)
from swingtrader_v2.scanner.candidate_filters import split_candidates_and_rejections
from swingtrader_v2.scanner.candidate_writer import write_candidate_list, write_rejections
from swingtrader_v2.scanner.detectors import ScannerInput, run_all_detectors


class StaticDailyBarSource:
    def __init__(self, rows_by_symbol: dict[str, list[dict[str, Any]]]) -> None:
        self._rows_by_symbol = rows_by_symbol

    def fetch_daily_bars(self, symbols: list[str], *, start, end):
        return {
            symbol: ProviderBarsPayload(
                symbol=symbol,
                provider=YFinanceDailyBarSource.provider,
                provider_mode=YFinanceDailyBarSource.provider_mode,
                rows=tuple(self._rows_by_symbol[symbol]),
                degraded=False,
                reason_codes=(),
            )
            for symbol in symbols
        }


def run_daily_scan(
    *,
    symbol_metadata_path: str | Path,
    bars_input_path: str | Path | None = None,
    as_of_date: date | None = None,
    environment: EnvironmentName = EnvironmentName.LOCAL,
    config_root: str | Path = "config",
    artifact_root: str | Path = "artifacts",
) -> dict[str, Any]:
    context = build_run_context(
        as_of_date=as_of_date,
        environment=environment,
        config_root=config_root,
        artifact_root=artifact_root,
    )
    metadata_by_symbol = load_symbol_metadata(symbol_metadata_path)
    symbols = sorted(metadata_by_symbol)
    start = context.as_of_date - timedelta(days=450)
    end = context.as_of_date + timedelta(days=1)

    if bars_input_path:
        rows_by_symbol = load_provider_rows(bars_input_path)
        provider = StaticDailyBarSource(rows_by_symbol)
    else:
        provider = YFinanceDailyBarSource()
        rows_by_symbol = {
            symbol: list(payload.rows)
            for symbol, payload in provider.fetch_daily_bars(symbols, start=start, end=end).items()
        }
    if "SPY" not in rows_by_symbol:
        spy_rows = YFinanceDailyBarSource().fetch_daily_bars(["SPY"], start=start, end=end)["SPY"]
        rows_by_symbol["SPY"] = list(spy_rows.rows)

    benchmark = prepare_spy_benchmark(provider=StaticDailyBarSource(rows_by_symbol), start=start, end=end, as_of=context.generated_at)

    bars_by_symbol = {}
    freshness_by_symbol = {}
    for symbol in symbols:
        normalized = normalize_daily_bars(symbol, rows_by_symbol[symbol])
        freshness = assess_freshness(last_bar_date=normalized.summary.last_bar_date, as_of=context.generated_at)
        bars_by_symbol[symbol] = normalized
        freshness_by_symbol[symbol] = freshness

    symbol_master = build_symbol_master_snapshot(
        metadata_by_symbol=metadata_by_symbol,
        bars_by_symbol=bars_by_symbol,
        freshness_by_symbol=freshness_by_symbol,
    )
    universe = build_universe_snapshot(symbol_master, as_of_date=context.as_of_date)
    anchor_definitions = anchor_definitions_from_config(context.config.effective)

    symbol_states: dict[str, Any] = {}
    candidates_by_family: dict[SetupFamily, list[Any]] = {family: [] for family in SetupFamily}
    rejections: list[Any] = []

    decisions = {item.symbol: item for item in (*universe.included, *universe.excluded)}
    for symbol in symbols:
        normalized = bars_by_symbol[symbol]
        moving_averages = compute_moving_averages(normalized.bars)
        momentum = compute_momentum_features(normalized.bars)
        volume = compute_volume_features(normalized.bars)
        volatility = compute_volatility_features(normalized.bars)
        patterns = compute_pattern_features(normalized.bars)
        relative_strength = compute_relative_strength_features(normalized.bars, benchmark.bars.bars)
        anchors = resolve_anchors(
            symbol=symbol,
            bars=normalized.bars,
            definitions=anchor_definitions,
            config_fingerprint=context.config.fingerprint,
        )
        detectors = run_all_detectors(
            ScannerInput(
                symbol=symbol,
                as_of_date=context.as_of_date,
                bars=normalized.bars,
                moving_averages=moving_averages,
                volume=volume,
                volatility=volatility,
                patterns=patterns,
                relative_strength=relative_strength,
                anchors=anchors,
            )
        )
        candidates, candidate_rejections = split_candidates_and_rejections(
            symbol=symbol,
            detectors=detectors,
            relative_strength=relative_strength,
            volume=volume,
        )
        for candidate in candidates:
            candidates_by_family[candidate.family].append(candidate)
        rejections.extend(candidate_rejections)
        symbol_states[symbol] = {
            "metadata": metadata_by_symbol[symbol],
            "provider_rows": rows_by_symbol[symbol],
            "bar_result": serialize_bar_result(normalized),
            "freshness": serialize_freshness(freshness_by_symbol[symbol]),
            "universe_decision": {
                "included": decisions[symbol].included,
                "reason_codes": list(decisions[symbol].reason_codes),
            },
            "features": {
                "moving_averages": serialize_feature_set(moving_averages),
                "momentum": serialize_feature_set(momentum),
                "volume": serialize_feature_set(volume),
                "volatility": serialize_feature_set(volatility),
                "patterns": serialize_feature_set(patterns),
                "relative_strength": serialize_feature_set(relative_strength),
            },
            "anchors": serialize_anchors(anchors),
            "candidates": [
                {
                    "symbol": candidate.symbol,
                    "family": candidate.family.value,
                    "evidence": list(candidate.evidence),
                    "evidence_count": candidate.evidence_count,
                    "excess_return_63d": candidate.excess_return_63d,
                    "median_dollar_volume_50d": candidate.median_dollar_volume_50d,
                    "classification_status": candidate.classification_status.value,
                    "reason_codes": list(candidate.reason_codes),
                }
                for candidate in candidates
            ],
            "rejections": [
                {
                    "symbol": rejection.symbol,
                    "family": rejection.family.value,
                    "reason_codes": list(rejection.reason_codes),
                    "classification_status": rejection.classification_status.value,
                }
                for rejection in candidate_rejections
            ],
        }

    candidate_paths = []
    for family in SetupFamily:
        artifact = write_candidate_list(
            family=family,
            candidates=tuple(candidates_by_family[family]),
            run_id=context.run_id,
            as_of_date=context.as_of_date,
            generated_at=context.generated_at,
            environment=context.environment,
            config_fingerprint=context.config.fingerprint,
        )
        path = write_json(context.scan_dir / f"candidate_list_{family.value}.json", artifact.payload)
        candidate_paths.append(path)
    rejection_artifact = write_rejections(
        rejections=tuple(rejections),
        run_id=context.run_id,
        as_of_date=context.as_of_date,
        generated_at=context.generated_at,
        environment=context.environment,
        config_fingerprint=context.config.fingerprint,
    )
    rejection_path = write_json(context.scan_dir / "scanner_rejections.json", rejection_artifact.payload)
    scan_state_path = write_json(
        context.scan_dir / "scan_state.json",
        {
            "run_id": context.run_id,
            "generated_at": context.generated_at.isoformat().replace("+00:00", "Z"),
            "as_of_date": context.as_of_date.isoformat(),
            "environment": context.environment.value,
            "config_fingerprint": context.config.fingerprint,
            "benchmark": {
                "bar_result": serialize_bar_result(benchmark.bars),
                "freshness": serialize_freshness(benchmark.freshness),
            },
            "universe": {
                "included": [{"symbol": item.symbol, "reason_codes": list(item.reason_codes)} for item in universe.included],
                "excluded": [{"symbol": item.symbol, "reason_codes": list(item.reason_codes)} for item in universe.excluded],
                "degraded": universe.degraded,
            },
            "symbols": symbol_states,
        },
    )
    update_run_manifest(
        context,
        [artifact_ref("candidate_list", str(path.relative_to(context.run_root))) for path in candidate_paths],
    )
    return {
        "run_root": str(context.run_root),
        "scan_state_path": str(scan_state_path),
        "rejection_artifact_path": str(rejection_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run daily EOD scan orchestration.")
    parser.add_argument("--symbol-metadata", required=True)
    parser.add_argument("--bars-input")
    parser.add_argument("--as-of-date")
    parser.add_argument("--environment", default="local", choices=[item.value for item in EnvironmentName])
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--artifact-root", default="artifacts")
    args = parser.parse_args()
    result = run_daily_scan(
        symbol_metadata_path=args.symbol_metadata,
        bars_input_path=args.bars_input,
        as_of_date=date.fromisoformat(args.as_of_date) if args.as_of_date else None,
        environment=EnvironmentName(args.environment),
        config_root=args.config_root,
        artifact_root=args.artifact_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
