"""Ordered hard-eligibility gates for classified packets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from swingtrader_v2.data.corporate_actions import CorporateAction
from swingtrader_v2.data.portfolio_snapshot import PortfolioSnapshot
from swingtrader_v2.domain.enums import SetupFamily
from swingtrader_v2.packet.completeness import INVALID, PARTIAL
from swingtrader_v2.packet.trade_plan import TradePlanScaffold
from swingtrader_v2.selector.classifier import ClassificationResult


ELIGIBLE = "eligible"
WARNING_ONLY = "warning_only"
INELIGIBLE = "ineligible"

PASSED = "passed"
FAILED = "failed"
WARNING = "warning"
UNSUPPORTED = "unsupported"

DEFAULT_ALLOWED_EXCHANGES = {"NYSE", "NASDAQ", "NYSE_AMERICAN"}
DEFAULT_ALLOWED_ASSET_TYPES = {"common_stock", "adr"}
DEFAULT_PRICE_MIN = 5.0
DEFAULT_PRICE_MAX = 1000.0
DEFAULT_HISTORY_MIN = 200
DEFAULT_STALENESS_MAX = 0
DEFAULT_DOLLAR_VOLUME_MIN = 25_000_000.0
DEFAULT_SPLIT_LOOKBACK_DAYS = 20
DEFAULT_DIVIDEND_LOOKBACK_DAYS = 5

GATE_SEQUENCE = (
    "instrument_support",
    "freshness",
    "data_sufficiency",
    "liquidity_tradeability",
    "corporate_action_distortion",
    "classification_coherence",
    "setup_specific_integrity",
    "portfolio_warning_gate",
)


@dataclass(frozen=True)
class GateResult:
    gate_name: str
    outcome: str
    blocking: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class EligibilityInput:
    packet: dict
    classification: ClassificationResult
    trade_plan: TradePlanScaffold
    completeness_state: str
    instrument_context: dict | None = None
    corporate_actions: tuple[CorporateAction, ...] = ()
    portfolio_snapshot: PortfolioSnapshot | None = None
    config: dict | None = None


@dataclass(frozen=True)
class EligibilityResult:
    outcome: str
    gate_results: tuple[GateResult, ...]


def _thresholds(config: dict | None) -> dict[str, float]:
    if not config:
        return {
            "price_min": DEFAULT_PRICE_MIN,
            "price_max": DEFAULT_PRICE_MAX,
            "history_min": DEFAULT_HISTORY_MIN,
            "staleness_max": DEFAULT_STALENESS_MAX,
            "dollar_volume_min": DEFAULT_DOLLAR_VOLUME_MIN,
        }
    thresholds = config.get("thresholds", {})
    return {
        "price_min": float(thresholds.get("price", {}).get("min", DEFAULT_PRICE_MIN)),
        "price_max": float(thresholds.get("price", {}).get("max", DEFAULT_PRICE_MAX)),
        "history_min": int(thresholds.get("history_days", {}).get("min", DEFAULT_HISTORY_MIN)),
        "staleness_max": int(thresholds.get("staleness_days", {}).get("max", DEFAULT_STALENESS_MAX)),
        "dollar_volume_min": float(
            thresholds.get("avg_daily_dollar_volume_20d", {}).get("min", DEFAULT_DOLLAR_VOLUME_MIN)
        ),
    }


def _as_of_date(packet: dict) -> date:
    return date.fromisoformat(packet["as_of_date"])


def _has_feature(packet: dict, name: str) -> bool:
    return any(item["name"] == name for item in packet["derived_features"]["values"])


def _feature_with_prefix(packet: dict, prefix: str) -> bool:
    return any(item["name"].startswith(prefix) for item in packet["derived_features"]["values"])


def _resolved_family(input_data: EligibilityInput) -> SetupFamily | None:
    family = input_data.classification.primary_family
    if family is not None:
        return family
    try:
        return SetupFamily(input_data.packet["setup"]["family"])
    except Exception:
        return None


def _family_requires_anchor_sufficiency(family: SetupFamily | None) -> bool:
    return family is SetupFamily.AVWAP_RECLAIM


def _is_optional_anchor_issue(field: str) -> bool:
    return field.startswith("anchor_set.") or field.startswith("derived_features.avwap_proxy.")


def _partial_due_only_optional_anchor_gaps(input_data: EligibilityInput) -> bool:
    family = _resolved_family(input_data)
    if _family_requires_anchor_sufficiency(family):
        return False

    packet = input_data.packet
    if packet["setup"]["classification_status"] != "ok":
        return False
    if packet["raw_snapshot"]["snapshot_status"] != "ok":
        return False
    if not packet["derived_features"]["values"]:
        return False
    if any(not _is_optional_anchor_issue(issue["field"]) for issue in packet["data_status"]["issues"]):
        return False
    return not packet["anchor_set"] or any(_is_optional_anchor_issue(issue["field"]) for issue in packet["data_status"]["issues"])


def _instrument_gate(input_data: EligibilityInput) -> GateResult:
    context = input_data.instrument_context
    if context is None:
        return GateResult("instrument_support", FAILED, True, ("instrument_context_missing",))

    reasons: list[str] = []
    exchange = str(context.get("exchange", "")).upper()
    if exchange not in DEFAULT_ALLOWED_EXCHANGES:
        reasons.append("unsupported_exchange")
    asset_type = str(context.get("asset_type", "")).lower()
    if asset_type not in DEFAULT_ALLOWED_ASSET_TYPES:
        reasons.append("unsupported_asset_type")
    country = str(context.get("country", "US")).upper()
    if country != "US":
        reasons.append("unsupported_country")
    return GateResult("instrument_support", PASSED if not reasons else FAILED, True, tuple(reasons))


def _freshness_gate(input_data: EligibilityInput, thresholds: dict[str, float]) -> GateResult:
    snapshot_status = input_data.packet["raw_snapshot"]["snapshot_status"]
    staleness_days = int(input_data.packet["raw_snapshot"]["coverage"]["staleness_days"])
    reasons: list[str] = []
    if snapshot_status != "ok":
        reasons.append(f"snapshot_status_{snapshot_status}")
    if staleness_days > thresholds["staleness_max"]:
        reasons.append("staleness_threshold_exceeded")
    return GateResult("freshness", PASSED if not reasons else FAILED, True, tuple(reasons))


def _data_sufficiency_gate(input_data: EligibilityInput, thresholds: dict[str, float]) -> GateResult:
    reasons: list[str] = []
    packet = input_data.packet
    family = _resolved_family(input_data)
    if input_data.completeness_state == INVALID:
        reasons.append("packet_invalid")
    bars_available = int(packet["raw_snapshot"]["coverage"]["bars_available"])
    if bars_available < thresholds["history_min"]:
        reasons.append("insufficient_completed_bars")
    if not packet["derived_features"]["values"]:
        reasons.append("derived_features_missing")
    if not packet["anchor_set"] and _family_requires_anchor_sufficiency(family):
        reasons.append("anchor_set_missing")
    if reasons:
        return GateResult("data_sufficiency", FAILED, True, tuple(reasons))
    if input_data.completeness_state == PARTIAL:
        if _partial_due_only_optional_anchor_gaps(input_data):
            return GateResult("data_sufficiency", PASSED, True, ())
        return GateResult("data_sufficiency", WARNING, True, ("packet_partial_but_structurally_usable",))
    return GateResult("data_sufficiency", PASSED, True, ())


def _liquidity_gate(input_data: EligibilityInput, thresholds: dict[str, float]) -> GateResult:
    packet = input_data.packet
    close = float(packet["raw_snapshot"]["price_bar"]["close"])
    dollar_volume = float(packet["raw_snapshot"]["liquidity"]["avg_daily_dollar_volume_20d"])
    reasons: list[str] = []
    if close < thresholds["price_min"] or close > thresholds["price_max"]:
        reasons.append("price_out_of_supported_range")
    if dollar_volume < thresholds["dollar_volume_min"]:
        reasons.append("avg_daily_dollar_volume_below_floor")
    return GateResult("liquidity_tradeability", PASSED if not reasons else FAILED, True, tuple(reasons))


def _corporate_action_gate(input_data: EligibilityInput) -> GateResult:
    as_of = _as_of_date(input_data.packet)
    splits = [
        action for action in input_data.corporate_actions
        if action.action_type == "split" and 0 <= (as_of - action.ex_date).days <= DEFAULT_SPLIT_LOOKBACK_DAYS
    ]
    if splits:
        return GateResult("corporate_action_distortion", FAILED, True, ("recent_split_distortion",))

    dividends = [
        action for action in input_data.corporate_actions
        if action.action_type == "dividend" and 0 <= (as_of - action.ex_date).days <= DEFAULT_DIVIDEND_LOOKBACK_DAYS
    ]
    if dividends:
        return GateResult("corporate_action_distortion", WARNING, True, ("recent_dividend_tagged",))
    return GateResult("corporate_action_distortion", PASSED, True, ())


def _classification_gate(input_data: EligibilityInput) -> GateResult:
    classification = input_data.classification
    packet_family = input_data.packet["setup"]["family"]
    if classification.primary_family is None:
        return GateResult("classification_coherence", FAILED, True, ("primary_family_unresolved",))
    reasons: list[str] = []
    if packet_family != classification.primary_family.value:
        reasons.append("packet_family_mismatch")
    if input_data.packet["setup"]["classification_status"] in {"missing", "unsupported"}:
        reasons.append("packet_classification_status_unsupported")
    if reasons:
        return GateResult("classification_coherence", FAILED, True, tuple(reasons))
    if "multi_family_overlap" in classification.secondary_tags:
        return GateResult("classification_coherence", WARNING, True, ("multi_family_overlap_requires_review",))
    return GateResult("classification_coherence", PASSED, True, ())


def _setup_specific_gate(input_data: EligibilityInput) -> GateResult:
    family = _resolved_family(input_data)
    trade_plan = input_data.trade_plan
    packet = input_data.packet
    reasons: list[str] = []
    if family is None:
        return GateResult("setup_specific_integrity", FAILED, True, ("primary_family_unresolved",))
    if trade_plan.trigger_level is None or trade_plan.invalidation_level is None:
        reasons.append("trade_plan_levels_incomplete")
    if family is SetupFamily.TREND_PULLBACK:
        if not _has_feature(packet, "sma50") or not _has_feature(packet, "sma200"):
            reasons.append("trend_moving_average_context_missing")
        if trade_plan.nearest_support is None:
            reasons.append("trend_support_context_missing")
    elif family is SetupFamily.BASE_BREAKOUT:
        if not _has_feature(packet, "pivot_price"):
            reasons.append("base_pivot_missing")
    elif family is SetupFamily.AVWAP_RECLAIM:
        if not any(anchor["is_daily_proxy"] for anchor in packet["anchor_set"]):
            reasons.append("active_daily_proxy_anchor_missing")
        if not _feature_with_prefix(packet, "avwap_proxy."):
            reasons.append("avwap_proxy_feature_missing")
    return GateResult("setup_specific_integrity", PASSED if not reasons else FAILED, True, tuple(reasons))


def _portfolio_gate(input_data: EligibilityInput) -> GateResult:
    snapshot = input_data.portfolio_snapshot
    if snapshot is None:
        return GateResult("portfolio_warning_gate", PASSED, False, ())
    reasons: list[str] = []
    if any(position.symbol == input_data.packet["symbol"] for position in snapshot.positions):
        reasons.append("symbol_already_held")
    if snapshot.degraded:
        reasons.append("portfolio_snapshot_degraded")
    if reasons:
        return GateResult("portfolio_warning_gate", WARNING, False, tuple(reasons))
    return GateResult("portfolio_warning_gate", PASSED, False, ())


def evaluate_eligibility(input_data: EligibilityInput) -> EligibilityResult:
    thresholds = _thresholds(input_data.config)
    gate_results = (
        _instrument_gate(input_data),
        _freshness_gate(input_data, thresholds),
        _data_sufficiency_gate(input_data, thresholds),
        _liquidity_gate(input_data, thresholds),
        _corporate_action_gate(input_data),
        _classification_gate(input_data),
        _setup_specific_gate(input_data),
        _portfolio_gate(input_data),
    )

    if any(result.outcome == FAILED and result.blocking for result in gate_results):
        outcome = INELIGIBLE
    elif any(result.outcome == WARNING for result in gate_results):
        outcome = WARNING_ONLY
    else:
        outcome = ELIGIBLE
    return EligibilityResult(outcome=outcome, gate_results=gate_results)
