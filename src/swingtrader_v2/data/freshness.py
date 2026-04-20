"""Session-aware freshness assessment for normalized end-of-day data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from swingtrader_v2.domain.enums import DataSupportStatus
from swingtrader_v2.market.calendar import NYSECalendar


MISSING_LAST_BAR = "missing_last_bar"
FUTURE_BAR_DATE = "future_bar_date"
STALE_EXPECTED_SESSION = "stale_expected_session"


@dataclass(frozen=True)
class FreshnessReport:
    status: DataSupportStatus
    expected_session: date
    last_bar_date: date | None
    stale_sessions: int
    degraded: bool
    reason_codes: tuple[str, ...]


def assess_freshness(
    *,
    last_bar_date: date | None,
    as_of: datetime,
    calendar: NYSECalendar | None = None,
    max_stale_sessions: int = 0,
) -> FreshnessReport:
    calendar = calendar or NYSECalendar()
    expected = calendar.last_completed_session(as_of)

    if last_bar_date is None:
        return FreshnessReport(
            status=DataSupportStatus.MISSING,
            expected_session=expected,
            last_bar_date=None,
            stale_sessions=0,
            degraded=True,
            reason_codes=(MISSING_LAST_BAR,),
        )

    if last_bar_date > expected:
        return FreshnessReport(
            status=DataSupportStatus.LOW_CONFIDENCE,
            expected_session=expected,
            last_bar_date=last_bar_date,
            stale_sessions=0,
            degraded=True,
            reason_codes=(FUTURE_BAR_DATE,),
        )

    stale_sessions = calendar.sessions_between(last_bar_date, expected)
    if stale_sessions > max_stale_sessions:
        return FreshnessReport(
            status=DataSupportStatus.STALE,
            expected_session=expected,
            last_bar_date=last_bar_date,
            stale_sessions=stale_sessions,
            degraded=True,
            reason_codes=(STALE_EXPECTED_SESSION,),
        )

    return FreshnessReport(
        status=DataSupportStatus.OK,
        expected_session=expected,
        last_bar_date=last_bar_date,
        stale_sessions=stale_sessions,
        degraded=False,
        reason_codes=(),
    )
