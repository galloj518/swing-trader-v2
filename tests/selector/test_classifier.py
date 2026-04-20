from __future__ import annotations

from swingtrader_v2.domain.enums import DataSupportStatus, SetupFamily
from swingtrader_v2.scanner.candidate_filters import ScannerCandidate
from swingtrader_v2.selector.classifier import classify_candidates


def test_classifier_promotes_stronger_overlap_candidate_and_records_demotions():
    candidates = (
        ScannerCandidate("AAPL", SetupFamily.TREND_PULLBACK, ("a", "b"), 2, 0.12, 90_000_000.0, DataSupportStatus.OK, ()),
        ScannerCandidate("AAPL", SetupFamily.AVWAP_RECLAIM, ("a", "b", "c", "d"), 4, 0.10, 80_000_000.0, DataSupportStatus.OK, ()),
    )

    result = classify_candidates(candidates)

    assert result.primary_family is SetupFamily.AVWAP_RECLAIM
    assert "multi_family_overlap" in result.secondary_tags
    assert "promoted_avwap_reclaim" in result.secondary_tags
    assert any(item.family is SetupFamily.TREND_PULLBACK and item.decision == "secondary" for item in result.resolutions)
    assert any("stronger_evidence" in reason for reason in result.disqualification_reasons)


def test_classifier_uses_priority_order_when_evidence_ties():
    candidates = (
        ScannerCandidate("AAPL", SetupFamily.TREND_PULLBACK, ("a", "b", "c"), 3, 0.11, 70_000_000.0, DataSupportStatus.OK, ()),
        ScannerCandidate("AAPL", SetupFamily.BASE_BREAKOUT, ("a", "b", "c"), 3, 0.15, 100_000_000.0, DataSupportStatus.OK, ()),
    )

    result = classify_candidates(candidates)

    assert result.primary_family is SetupFamily.TREND_PULLBACK
    assert any(item.family is SetupFamily.BASE_BREAKOUT and "demoted_by_family_priority_order" in item.reason_codes for item in result.resolutions)
