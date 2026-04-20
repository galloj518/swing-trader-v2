"""Independent setup-family detectors for scanner-stage routing only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from swingtrader_v2.analysis.moving_averages import MovingAverageFeatureSet
from swingtrader_v2.analysis.patterns import PatternFeatureSet
from swingtrader_v2.analysis.relative_strength import RelativeStrengthFeatureSet
from swingtrader_v2.analysis.volatility import VolatilityFeatureSet
from swingtrader_v2.analysis.volume import VolumeFeatureSet
from swingtrader_v2.anchors.resolver import ResolvedAnchor
from swingtrader_v2.domain.enums import DataSupportStatus, SetupFamily
from swingtrader_v2.market.bars import NormalizedBar


def _metric_value(items, name: str):
    for item in items:
        if item.name == name:
            return item.value, item.status
    return None, DataSupportStatus.MISSING


def _find_active_anchor(anchors: tuple[ResolvedAnchor, ...]) -> ResolvedAnchor | None:
    active = [anchor for anchor in anchors if anchor.status == "active" and anchor.avwap_proxy is not None]
    return active[0] if active else None


@dataclass(frozen=True)
class ScannerInput:
    symbol: str
    as_of_date: date
    bars: tuple[NormalizedBar, ...]
    moving_averages: MovingAverageFeatureSet
    volume: VolumeFeatureSet
    volatility: VolatilityFeatureSet
    patterns: PatternFeatureSet
    relative_strength: RelativeStrengthFeatureSet
    anchors: tuple[ResolvedAnchor, ...]


@dataclass(frozen=True)
class DetectorResult:
    family: SetupFamily
    detected: bool
    evidence: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    data_status: DataSupportStatus


def detect_trend_pullback(payload: ScannerInput) -> DetectorResult:
    reasons: list[str] = []
    evidence: list[str] = []
    sma50, sma50_status = _metric_value(payload.moving_averages.values, "sma50")
    sma200, sma200_status = _metric_value(payload.moving_averages.values, "sma200")
    ema21, ema21_status = _metric_value(payload.moving_averages.values, "ema21")
    excess63, excess63_status = _metric_value(payload.relative_strength.metrics, "excess_return_vs_spy_63d")
    pullback_depth, pullback_status = _metric_value(payload.patterns.metrics, "pullback_depth_pct")
    support_touches, support_status = _metric_value(payload.patterns.metrics, "support_touches")
    if not payload.bars:
        reasons.append("missing_bars")
    else:
        close = payload.bars[-1].close
        if sma50 is None or sma50_status is not DataSupportStatus.OK:
            reasons.append("sma50_unavailable")
        elif close > sma50:
            evidence.append("close_above_sma50")
        else:
            reasons.append("close_not_above_sma50")
        if sma50 is None or sma200 is None or sma50_status is not DataSupportStatus.OK or sma200_status is not DataSupportStatus.OK:
            reasons.append("long_trend_mas_unavailable")
        elif sma50 > sma200:
            evidence.append("sma50_above_sma200")
        else:
            reasons.append("sma50_not_above_sma200")
        if ema21 is None or ema21_status is not DataSupportStatus.OK or sma50 is None:
            reasons.append("ema21_unavailable")
        elif ema21 >= sma50:
            evidence.append("ema21_at_or_above_sma50")
        else:
            reasons.append("ema21_below_sma50")
        if excess63 is None or excess63_status is not DataSupportStatus.OK:
            reasons.append("relative_strength_63d_unavailable")
        elif excess63 > 0:
            evidence.append("positive_63d_excess_return_vs_spy")
        else:
            reasons.append("nonpositive_63d_excess_return_vs_spy")
        if pullback_depth is None or pullback_status is DataSupportStatus.MISSING:
            reasons.append("pullback_depth_unavailable")
        elif 0.02 <= pullback_depth <= 0.12:
            evidence.append("pullback_in_band")
        else:
            reasons.append("pullback_out_of_band")
        if support_touches is None or support_status is DataSupportStatus.MISSING:
            reasons.append("support_proximity_unavailable")
        elif support_touches >= 2:
            evidence.append("support_proximity_present")
        else:
            reasons.append("support_proximity_absent")
    status = DataSupportStatus.OK if not reasons else DataSupportStatus.LOW_CONFIDENCE if evidence else DataSupportStatus.LOW_CONFIDENCE
    return DetectorResult(SetupFamily.TREND_PULLBACK, not reasons, tuple(evidence), tuple(reasons), status)


def detect_base_breakout(payload: ScannerInput) -> DetectorResult:
    reasons: list[str] = []
    evidence: list[str] = []
    base_length, base_length_status = _metric_value(payload.patterns.metrics, "base_length_bars")
    base_depth, base_depth_status = _metric_value(payload.patterns.metrics, "base_depth_pct")
    pivot_price, pivot_status = _metric_value(payload.patterns.metrics, "pivot_price")
    contraction_ratio, contraction_status = _metric_value(payload.volatility.metrics, "atr_contraction_ratio")
    if not payload.bars:
        reasons.append("missing_bars")
    else:
        close = payload.bars[-1].close
        if base_length is None or base_length_status is not DataSupportStatus.OK:
            reasons.append("base_length_unavailable")
        elif base_length >= 20:
            evidence.append("base_length_threshold_met")
        else:
            reasons.append("base_length_below_threshold")
        if base_depth is None or base_depth_status is DataSupportStatus.MISSING:
            reasons.append("base_depth_unavailable")
        elif 0.05 <= base_depth <= 0.35:
            evidence.append("base_depth_in_band")
        else:
            reasons.append("base_depth_out_of_band")
        if contraction_ratio is None or contraction_status is not DataSupportStatus.OK:
            reasons.append("contraction_ratio_unavailable")
        elif contraction_ratio <= 0.9:
            evidence.append("contraction_behavior_present")
        else:
            reasons.append("contraction_behavior_absent")
        if pivot_price is None or pivot_status is not DataSupportStatus.OK:
            reasons.append("pivot_price_unavailable")
        else:
            distance = abs(close - pivot_price) / pivot_price if pivot_price else None
            if distance is not None and distance <= 0.03:
                evidence.append("pivot_proximity_present")
            else:
                reasons.append("pivot_proximity_absent")
    status = DataSupportStatus.OK if not reasons else DataSupportStatus.LOW_CONFIDENCE
    return DetectorResult(SetupFamily.BASE_BREAKOUT, not reasons, tuple(evidence), tuple(reasons), status)


def detect_avwap_reclaim(payload: ScannerInput) -> DetectorResult:
    reasons: list[str] = []
    evidence: list[str] = []
    sma50, sma50_status = _metric_value(payload.moving_averages.values, "sma50")
    active_anchor = _find_active_anchor(payload.anchors)
    if not payload.bars:
        reasons.append("missing_bars")
    elif active_anchor is None:
        reasons.append("active_anchor_missing")
    else:
        close = payload.bars[-1].close
        avwap = active_anchor.avwap_proxy
        if avwap is None or avwap.current_avwap is None or avwap.status is not DataSupportStatus.OK:
            reasons.append("avwap_proxy_unavailable")
        elif close > avwap.current_avwap:
            evidence.append("close_above_avwap_proxy")
        else:
            reasons.append("close_not_above_avwap_proxy")
        if avwap is None or avwap.distance_from_close_pct is None:
            reasons.append("avwap_distance_unavailable")
        elif 0 <= avwap.distance_from_close_pct <= 0.05:
            evidence.append("distance_to_avwap_in_band")
        else:
            reasons.append("distance_to_avwap_out_of_band")
        if avwap is not None and avwap.short_slope is not None and avwap.short_slope >= 0:
            evidence.append("avwap_proxy_holding_or_rising")
        else:
            reasons.append("avwap_proxy_not_holding")
        if sma50 is None or sma50_status is not DataSupportStatus.OK:
            reasons.append("sma50_unavailable")
        elif close > sma50:
            evidence.append("close_above_sma50")
        else:
            reasons.append("close_not_above_sma50")
    status = DataSupportStatus.OK if not reasons else DataSupportStatus.LOW_CONFIDENCE
    return DetectorResult(SetupFamily.AVWAP_RECLAIM, not reasons, tuple(evidence), tuple(reasons), status)


def run_all_detectors(payload: ScannerInput) -> tuple[DetectorResult, ...]:
    results = (
        detect_trend_pullback(payload),
        detect_base_breakout(payload),
        detect_avwap_reclaim(payload),
    )
    return tuple(sorted(results, key=lambda item: item.family.value))
