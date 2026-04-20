from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from swingtrader_v2.analysis.momentum import compute_momentum_features
from swingtrader_v2.analysis.moving_averages import compute_moving_averages
from swingtrader_v2.analysis.patterns import compute_pattern_features
from swingtrader_v2.analysis.relative_strength import compute_relative_strength_features
from swingtrader_v2.analysis.volume import compute_volume_features
from swingtrader_v2.analysis.volatility import compute_volatility_features
from swingtrader_v2.config.loader import load_effective_config
from swingtrader_v2.data.corporate_actions import extract_corporate_actions
from swingtrader_v2.data.freshness import assess_freshness
from swingtrader_v2.domain.enums import EnvironmentName
from swingtrader_v2.market.bars import normalize_daily_bars
from swingtrader_v2.market.calendar import NYSECalendar
from swingtrader_v2.pipelines.common import anchor_definitions_from_config
from swingtrader_v2.scanner.candidate_filters import split_candidates_and_rejections
from swingtrader_v2.scanner.detectors import ScannerInput, run_all_detectors
from swingtrader_v2.anchors.resolver import resolve_anchors


FIXTURE_ROOT = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = FIXTURE_ROOT / "golden"
SCENARIO_CATALOG_PATH = FIXTURE_ROOT / "scenario_catalog.json"
FIXED_AS_OF_DATE = date(2025, 9, 18)
FIXED_GENERATED_AT = datetime(2025, 9, 18, 21, 15, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ScenarioSnapshot:
    name: str
    definition: dict[str, Any]
    metadata: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    benchmark_rows: tuple[dict[str, Any], ...]
    bar_result: Any
    benchmark_result: Any
    freshness: Any
    moving_averages: Any
    momentum: Any
    volume: Any
    volatility: Any
    patterns: Any
    relative_strength: Any
    anchors: tuple[Any, ...]
    detector_results: tuple[Any, ...]
    candidates: tuple[Any, ...]
    rejections: tuple[Any, ...]
    corporate_actions: tuple[Any, ...]


class ScenarioLibrary:
    def __init__(self) -> None:
        self.catalog = json.loads(SCENARIO_CATALOG_PATH.read_text(encoding="utf-8"))
        self._config = load_effective_config("config", environment=EnvironmentName.LOCAL)
        self._anchor_definitions = anchor_definitions_from_config(self._config.effective)
        self._calendar = NYSECalendar()

    @property
    def as_of_date(self) -> date:
        return date.fromisoformat(self.catalog["as_of_date"])

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item["name"] for item in self.catalog["scenarios"])

    def definition(self, name: str) -> dict[str, Any]:
        for item in self.catalog["scenarios"]:
            if item["name"] == name:
                return dict(item)
        raise KeyError(name)

    def _trading_sessions(self, count: int, *, end_session: date) -> list[date]:
        sessions: list[date] = []
        cursor = end_session
        while len(sessions) < count:
            if self._calendar.is_trading_day(cursor):
                sessions.append(cursor)
            cursor -= timedelta(days=1)
        return list(reversed(sessions))

    def _trend_pullback_closes(self) -> list[float]:
        closes = [100.0 + (index * 1.0) for index in range(220)]
        closes[-8:] = [300.0, 295.0, 292.0, 289.0, 291.0, 294.0, 297.0, 301.0]
        return closes

    def _clean_base_breakout_closes(self) -> list[float]:
        closes = [200.0 - (index * 0.45) for index in range(200)]
        closes += [
            110.0,
            108.0,
            106.0,
            104.0,
            102.0,
            100.0,
            98.0,
            96.0,
            94.0,
            92.0,
            90.0,
            92.0,
            94.0,
            96.0,
            98.0,
            100.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
            116.0,
            117.0,
            118.0,
            119.0,
            120.0,
            121.0,
            122.0,
            123.0,
            124.0,
            125.0,
            126.0,
            127.0,
            128.0,
            129.0,
            130.0,
            131.0,
            132.0,
            133.0,
            134.0,
            135.0,
            136.0,
            137.0,
            138.0,
            139.0,
            140.0,
            141.0,
            142.0,
            143.0,
            144.0,
            145.0,
        ]
        return closes[:260]

    def _clean_avwap_reclaim_closes(self) -> list[float]:
        closes = [160.0 - (index * 0.25) for index in range(245)]
        closes += [99.0, 97.0, 95.0, 94.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 104.0]
        return closes

    def _conflicting_detector_closes(self) -> list[float]:
        closes = [160.0 - (index * 0.5) for index in range(180)]
        closes += [100.0, 99.5, 100.5, 99.8, 100.2, 99.7, 100.1, 99.9, 100.0, 99.8] * 5
        closes += [104.0, 105.0, 106.0, 107.0, 108.0]
        return closes

    def _series_for_profile(self, profile: str, *, length: int) -> list[float]:
        if profile == "trend_pullback":
            return self._trend_pullback_closes()[:length]
        if profile == "clean_base_breakout":
            return self._clean_base_breakout_closes()[:length]
        if profile == "clean_avwap_reclaim":
            return self._clean_avwap_reclaim_closes()[:length]
        if profile == "conflicting_detector":
            return self._conflicting_detector_closes()[:length]
        raise KeyError(profile)

    def _rows_from_closes(
        self,
        symbol: str,
        closes: list[float],
        *,
        end_session: date,
        volume: int,
        split_offset: int | None = None,
        split_ratio: float = 2.0,
    ) -> tuple[dict[str, Any], ...]:
        sessions = self._trading_sessions(len(closes), end_session=end_session)
        rows: list[dict[str, Any]] = []
        for index, (session_date, close) in enumerate(zip(sessions, closes, strict=True)):
            rows.append(
                {
                    "date": session_date.isoformat(),
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "adjusted_close": close,
                    "volume": volume + ((index % 9) * 15_000),
                    "dividend": 0.0,
                    "split_ratio": 1.0,
                }
            )
        if split_offset is not None:
            rows[-split_offset]["split_ratio"] = split_ratio
        return tuple(rows)

    def rows(self, name: str) -> tuple[dict[str, Any], ...]:
        definition = self.definition(name)
        profile = definition["profile"]
        bar_count = int(definition.get("bar_count", 260))
        stale_sessions = int(definition.get("stale_sessions", 0))
        end_session = self.as_of_date
        for _ in range(stale_sessions):
            end_session = self._calendar.previous_trading_day(end_session)
        split_offset = definition.get("split_offset")
        return self._rows_from_closes(
            definition["symbol"],
            self._series_for_profile(profile, length=bar_count),
            end_session=end_session,
            volume=int(definition.get("volume", 2_400_000)),
            split_offset=int(split_offset) if split_offset is not None else None,
        )

    def benchmark_rows(self, *, length: int = 260) -> tuple[dict[str, Any], ...]:
        closes = [100.0 + (index * 0.25) for index in range(length)]
        return self._rows_from_closes("SPY", closes, end_session=self.as_of_date, volume=3_500_000)

    def metadata_payload(self) -> dict[str, Any]:
        return {
            item["symbol"]: {
                "symbol": item["symbol"],
                "exchange": item.get("exchange", "NASDAQ"),
                "asset_type": item.get("asset_type", "common_stock"),
                "currency": "USD",
                "country": "US",
                "name": item["name"],
            }
            for item in self.catalog["scenarios"]
        }

    def bars_payload(self) -> dict[str, list[dict[str, Any]]]:
        payload = {
            item["symbol"]: list(self.rows(item["name"]))
            for item in self.catalog["scenarios"]
        }
        payload["SPY"] = list(self.benchmark_rows())
        return payload

    def snapshot(self, name: str) -> ScenarioSnapshot:
        definition = self.definition(name)
        rows = self.rows(name)
        benchmark_rows = self.benchmark_rows(length=max(260, len(rows)))
        bar_result = normalize_daily_bars(definition["symbol"], rows)
        benchmark_result = normalize_daily_bars("SPY", benchmark_rows)
        freshness = assess_freshness(
            last_bar_date=bar_result.summary.last_bar_date,
            as_of=FIXED_GENERATED_AT,
        )
        moving_averages = compute_moving_averages(bar_result.bars)
        momentum = compute_momentum_features(bar_result.bars)
        volume = compute_volume_features(bar_result.bars)
        volatility = compute_volatility_features(bar_result.bars)
        patterns = compute_pattern_features(bar_result.bars)
        relative_strength = compute_relative_strength_features(bar_result.bars, benchmark_result.bars)
        anchors = resolve_anchors(
            symbol=definition["symbol"],
            bars=bar_result.bars,
            definitions=self._anchor_definitions,
            config_fingerprint=self._config.fingerprint,
        )
        detector_results = run_all_detectors(
            ScannerInput(
                symbol=definition["symbol"],
                as_of_date=self.as_of_date,
                bars=bar_result.bars,
                moving_averages=moving_averages,
                volume=volume,
                volatility=volatility,
                patterns=patterns,
                relative_strength=relative_strength,
                anchors=anchors,
            )
        )
        candidates, rejections = split_candidates_and_rejections(
            symbol=definition["symbol"],
            detectors=detector_results,
            relative_strength=relative_strength,
            volume=volume,
        )
        return ScenarioSnapshot(
            name=name,
            definition=definition,
            metadata=self.metadata_payload()[definition["symbol"]],
            rows=rows,
            benchmark_rows=benchmark_rows,
            bar_result=bar_result,
            benchmark_result=benchmark_result,
            freshness=freshness,
            moving_averages=moving_averages,
            momentum=momentum,
            volume=volume,
            volatility=volatility,
            patterns=patterns,
            relative_strength=relative_strength,
            anchors=anchors,
            detector_results=detector_results,
            candidates=candidates,
            rejections=rejections,
            corporate_actions=extract_corporate_actions(rows),
        )

    def write_pipeline_inputs(self, target: Path) -> tuple[Path, Path]:
        target.mkdir(parents=True, exist_ok=True)
        metadata_path = target / "symbol_metadata.json"
        bars_path = target / "bars.json"
        metadata_path.write_text(json.dumps(self.metadata_payload(), indent=2, sort_keys=True), encoding="utf-8")
        bars_path.write_text(json.dumps(self.bars_payload(), indent=2, sort_keys=True), encoding="utf-8")
        return metadata_path, bars_path


@pytest.fixture
def scenario_library() -> ScenarioLibrary:
    return ScenarioLibrary()


@pytest.fixture
def freeze_pipeline_time(monkeypatch) -> Callable[[], None]:
    def _freeze() -> None:
        import swingtrader_v2.pipelines.common as common_module
        import swingtrader_v2.pipelines.run_tracking_update as tracking_pipeline

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return FIXED_GENERATED_AT.replace(tzinfo=None)
                return FIXED_GENERATED_AT.astimezone(tz)

        monkeypatch.setattr(common_module, "datetime", FrozenDateTime)
        monkeypatch.setattr(tracking_pipeline, "datetime", FrozenDateTime)

    return _freeze


@pytest.fixture
def pipeline_fixture_bundle(workspace_tmp_root: Path, scenario_library: ScenarioLibrary) -> dict[str, Any]:
    metadata_path, bars_path = scenario_library.write_pipeline_inputs(workspace_tmp_root / "inputs")
    return {
        "root": workspace_tmp_root,
        "metadata_path": metadata_path,
        "bars_path": bars_path,
        "artifact_root": workspace_tmp_root / "artifacts",
        "history_path": workspace_tmp_root / "history" / "tracking_history.json",
    }


@pytest.fixture
def workspace_tmp_root() -> Path:
    base = Path.cwd() / ".pytest_workspace"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"case_{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=False)
    return target
