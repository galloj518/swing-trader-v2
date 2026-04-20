"""Domain enumerations for artifact contracts and configuration."""

from __future__ import annotations

from enum import StrEnum


class ArtifactType(StrEnum):
    PACKET = "packet"
    CANDIDATE_LIST = "candidate_list"
    RANKING = "ranking"
    DASHBOARD_PAYLOAD = "dashboard_payload"
    RUN_MANIFEST = "run_manifest"
    DECISION_EVENT = "decision_event"
    OUTCOME_RECORD = "outcome_record"


class EnvironmentName(StrEnum):
    LOCAL = "local"
    GITHUB_ACTIONS = "github_actions"


class RuntimeMode(StrEnum):
    EOD = "eod"


class SetupFamily(StrEnum):
    TREND_PULLBACK = "trend_pullback"
    BASE_BREAKOUT = "base_breakout"
    AVWAP_RECLAIM = "avwap_reclaim"


class DataSupportStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
    LOW_CONFIDENCE = "low_confidence"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INDETERMINATE = "indeterminate"


class GateResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"


class PrioritizationStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    RANKED = "ranked"
    SUPPRESSED = "suppressed"


class PrioritizationMethod(StrEnum):
    TRANSPARENT_WEIGHTED_SUM = "transparent_weighted_sum"


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    REVIEWED = "reviewed"


class OutcomeStatus(StrEnum):
    NOT_STARTED = "not_started"
    TRACKING = "tracking"
    COMPLETE = "complete"
    UNSUPPORTED = "unsupported"
    PENDING = "pending"


class DecisionAction(StrEnum):
    WATCH = "watch"
    PASS = "pass"
    PLAN_TRADE = "plan_trade"
    INVALIDATED = "invalidated"


class OutcomeHorizon(StrEnum):
    T_PLUS_5 = "t_plus_5"
    T_PLUS_10 = "t_plus_10"
    T_PLUS_20 = "t_plus_20"


class MarketDataProvider(StrEnum):
    YFINANCE = "yfinance"
    SCHWAB = "schwab"


class ProviderMode(StrEnum):
    BASELINE = "baseline"
    OPTIONAL = "optional"
