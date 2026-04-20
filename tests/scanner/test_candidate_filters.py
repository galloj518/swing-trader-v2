from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swingtrader_v2.analysis.relative_strength import RelativeStrengthFeatureSet, RelativeStrengthMetric
from swingtrader_v2.analysis.volume import VolumeFeatureSet, VolumeMetric
from swingtrader_v2.domain.enums import DataSupportStatus, EnvironmentName, SetupFamily
from swingtrader_v2.scanner.candidate_filters import (
    ScannerCandidate,
    order_candidates,
    split_candidates_and_rejections,
)
from swingtrader_v2.scanner.candidate_writer import write_candidate_list, write_rejections
from swingtrader_v2.scanner.detectors import DetectorResult


UTC = ZoneInfo("UTC")


def _relative_strength(value: float) -> RelativeStrengthFeatureSet:
    return RelativeStrengthFeatureSet(
        status=DataSupportStatus.OK,
        metrics=(
            RelativeStrengthMetric("excess_return_vs_spy_63d", value, DataSupportStatus.OK),
        ),
    )


def _volume(value: float) -> VolumeFeatureSet:
    return VolumeFeatureSet(
        status=DataSupportStatus.OK,
        metrics=(
            VolumeMetric("median_dollar_volume_50d", value, DataSupportStatus.OK),
        ),
    )


def test_candidate_ordering_matches_required_tie_breaks():
    candidates = (
        ScannerCandidate("MSFT", SetupFamily.TREND_PULLBACK, ("a", "b"), 2, 0.12, 90_000_000.0, DataSupportStatus.OK, ()),
        ScannerCandidate("AAPL", SetupFamily.TREND_PULLBACK, ("a", "b"), 2, 0.12, 100_000_000.0, DataSupportStatus.OK, ()),
        ScannerCandidate("NVDA", SetupFamily.BASE_BREAKOUT, ("a",), 1, 0.20, 120_000_000.0, DataSupportStatus.OK, ()),
    )
    ordered = order_candidates(candidates)
    assert [item.symbol for item in ordered] == ["NVDA", "AAPL", "MSFT"]


def test_split_candidates_and_rejections_stays_explicit():
    detectors = (
        DetectorResult(SetupFamily.TREND_PULLBACK, True, ("e1", "e2"), (), DataSupportStatus.OK),
        DetectorResult(SetupFamily.AVWAP_RECLAIM, False, (), ("active_anchor_missing",), DataSupportStatus.LOW_CONFIDENCE),
    )
    candidates, rejections = split_candidates_and_rejections(
        symbol="AAPL",
        detectors=detectors,
        relative_strength=_relative_strength(0.15),
        volume=_volume(150_000_000.0),
    )
    assert len(candidates) == 1
    assert len(rejections) == 1
    assert rejections[0].reason_codes == ("active_anchor_missing",)


def test_candidate_writer_emits_schema_shaped_payload_and_rejections():
    candidates = (
        ScannerCandidate("AAPL", SetupFamily.TREND_PULLBACK, ("e1", "e2"), 2, 0.12, 100_000_000.0, DataSupportStatus.OK, ()),
    )
    artifact = write_candidate_list(
        family=SetupFamily.TREND_PULLBACK,
        candidates=candidates,
        run_id="run_local_20250420_0123456789abcdef",
        as_of_date=date(2025, 4, 20),
        generated_at=datetime(2025, 4, 20, 20, 0, tzinfo=UTC),
        environment=EnvironmentName.LOCAL,
        config_fingerprint="a" * 64,
    )
    assert artifact.payload["artifact_type"] == "candidate_list"
    assert artifact.payload["setup_family"] == "trend_pullback"
    assert artifact.payload["candidates"][0]["symbol"] == "AAPL"
    assert artifact.payload["candidates"][0]["classification_status"] == "ok"

    rejection_artifact = write_rejections(
        rejections=(
            split_candidates_and_rejections(
                symbol="AAPL",
                detectors=(DetectorResult(SetupFamily.BASE_BREAKOUT, False, (), ("pivot_proximity_absent",), DataSupportStatus.LOW_CONFIDENCE),),
                relative_strength=_relative_strength(0.12),
                volume=_volume(90_000_000.0),
            )[1][0],
        ),
        run_id="run_local_20250420_0123456789abcdef",
        as_of_date=date(2025, 4, 20),
        generated_at=datetime(2025, 4, 20, 20, 0, tzinfo=UTC),
        environment=EnvironmentName.LOCAL,
        config_fingerprint="b" * 64,
    )
    assert rejection_artifact.payload["artifact_type"] == "scanner_rejections"
    assert rejection_artifact.payload["rejections"][0]["reason_codes"] == ["pivot_proximity_absent"]
