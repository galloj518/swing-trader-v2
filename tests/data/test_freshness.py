from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from swingtrader_v2.data.freshness import MISSING_LAST_BAR, STALE_EXPECTED_SESSION, assess_freshness
from swingtrader_v2.domain.enums import DataSupportStatus


NY_TZ = ZoneInfo("America/New_York")


def test_freshness_uses_previous_session_before_close():
    report = assess_freshness(
        last_bar_date=date(2025, 4, 17),
        as_of=datetime(2025, 4, 18, 15, 30, tzinfo=NY_TZ),
    )

    assert report.expected_session == date(2025, 4, 17)
    assert report.status is DataSupportStatus.OK
    assert report.reason_codes == ()


def test_freshness_marks_missing_explicitly():
    report = assess_freshness(
        last_bar_date=None,
        as_of=datetime(2025, 4, 18, 17, 0, tzinfo=NY_TZ),
    )

    assert report.status is DataSupportStatus.MISSING
    assert report.reason_codes == (MISSING_LAST_BAR,)
    assert report.degraded is True


def test_freshness_marks_stale_after_session_close():
    report = assess_freshness(
        last_bar_date=date(2025, 4, 16),
        as_of=datetime(2025, 4, 18, 17, 0, tzinfo=NY_TZ),
    )

    assert report.expected_session == date(2025, 4, 17)
    assert report.status is DataSupportStatus.STALE
    assert report.stale_sessions == 1
    assert report.reason_codes == (STALE_EXPECTED_SESSION,)
