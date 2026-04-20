"""NYSE trading-session calendar helpers for end-of-day workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


NY_TZ = ZoneInfo("America/New_York")
NYSE_CLOSE = time(hour=16, minute=0)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    current += timedelta(days=7 * (occurrence - 1))
    return current


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nyse_holidays(year: int) -> set[date]:
    easter = _easter_sunday(year)
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        easter - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


@dataclass(frozen=True)
class SessionWindow:
    session_date: date
    close_time: datetime


class NYSECalendar:
    """NYSE session-aware logic for daily-bar freshness and point-in-time EOD runs."""

    timezone = NY_TZ
    close_time = NYSE_CLOSE

    def is_trading_day(self, session_date: date) -> bool:
        return session_date.weekday() < 5 and session_date not in nyse_holidays(session_date.year)

    def previous_trading_day(self, session_date: date) -> date:
        current = session_date - timedelta(days=1)
        while not self.is_trading_day(current):
            current -= timedelta(days=1)
        return current

    def next_trading_day(self, session_date: date) -> date:
        current = session_date + timedelta(days=1)
        while not self.is_trading_day(current):
            current += timedelta(days=1)
        return current

    def last_completed_session(self, as_of: datetime) -> date:
        localized = as_of.astimezone(self.timezone)
        session_date = localized.date()
        if not self.is_trading_day(session_date):
            while not self.is_trading_day(session_date):
                session_date -= timedelta(days=1)
            return session_date
        if localized.timetz().replace(tzinfo=None) >= self.close_time:
            return session_date
        return self.previous_trading_day(session_date)

    def sessions_between(self, previous_session: date, current_session: date) -> int:
        if previous_session >= current_session:
            return 0
        count = 0
        cursor = previous_session
        while cursor < current_session:
            cursor = self.next_trading_day(cursor)
            count += 1
        return count

    def session_window(self, session_date: date) -> SessionWindow:
        close_dt = datetime.combine(session_date, self.close_time, tzinfo=self.timezone)
        return SessionWindow(session_date=session_date, close_time=close_dt)
