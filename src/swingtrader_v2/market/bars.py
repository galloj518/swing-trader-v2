"""Normalized daily-bar contracts and utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Iterable

from swingtrader_v2.data.corporate_actions import extract_corporate_actions, parse_split_ratio
from swingtrader_v2.domain.enums import DataSupportStatus


MISSING_BARS = "missing_bars"
DUPLICATE_SESSION_BAR = "duplicate_session_bar"
INVALID_BAR_ORDER = "invalid_bar_order"


@dataclass(frozen=True)
class NormalizedBar:
    symbol: str
    session_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int
    dividend: float
    split_ratio: float
    adjustment_factor: float

    @property
    def dollar_volume(self) -> float:
        return self.close * self.volume


@dataclass(frozen=True)
class BarSummary:
    symbol: str
    completed_bars: int
    first_bar_date: date | None
    last_bar_date: date | None
    median_50d_volume: float
    median_50d_dollar_volume: float


@dataclass(frozen=True)
class BarNormalizationResult:
    symbol: str
    status: DataSupportStatus
    bars: tuple[NormalizedBar, ...]
    summary: BarSummary
    reason_codes: tuple[str, ...]
    degraded: bool
    duplicate_count: int


def _to_date(raw: Any) -> date:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    return date.fromisoformat(str(raw))


def _to_float(raw: Any, *, default: float = 0.0) -> float:
    if raw in (None, ""):
        return default
    return float(raw)


def _to_int(raw: Any, *, default: int = 0) -> int:
    if raw in (None, ""):
        return default
    return int(raw)


def _build_bar(symbol: str, row: dict[str, Any]) -> NormalizedBar:
    close = _to_float(row["close"])
    adjusted_close = _to_float(row.get("adjusted_close"), default=close)
    split_ratio = parse_split_ratio(row.get("split_ratio"))
    adjustment_factor = adjusted_close / close if close else 1.0
    return NormalizedBar(
        symbol=symbol,
        session_date=_to_date(row["date"]),
        open=_to_float(row["open"]),
        high=_to_float(row["high"]),
        low=_to_float(row["low"]),
        close=close,
        adjusted_close=adjusted_close,
        volume=_to_int(row["volume"]),
        dividend=_to_float(row.get("dividend")),
        split_ratio=split_ratio,
        adjustment_factor=adjustment_factor,
    )


def _summarize(symbol: str, bars: tuple[NormalizedBar, ...]) -> BarSummary:
    trailing = bars[-50:] if len(bars) >= 50 else bars
    volumes = [bar.volume for bar in trailing]
    dollar_volumes = [bar.dollar_volume for bar in trailing]
    return BarSummary(
        symbol=symbol,
        completed_bars=len(bars),
        first_bar_date=bars[0].session_date if bars else None,
        last_bar_date=bars[-1].session_date if bars else None,
        median_50d_volume=median(volumes) if volumes else 0.0,
        median_50d_dollar_volume=median(dollar_volumes) if dollar_volumes else 0.0,
    )


def normalize_daily_bars(symbol: str, rows: Iterable[dict[str, Any]]) -> BarNormalizationResult:
    indexed: dict[date, dict[str, Any]] = {}
    duplicate_count = 0
    for row in rows:
        session_date = _to_date(row["date"])
        if session_date in indexed:
            duplicate_count += 1
        indexed[session_date] = dict(row)

    bars = tuple(sorted((_build_bar(symbol, row) for row in indexed.values()), key=lambda item: item.session_date))
    reason_codes: list[str] = []
    if duplicate_count:
        reason_codes.append(DUPLICATE_SESSION_BAR)
    if not bars:
        reason_codes.append(MISSING_BARS)
        return BarNormalizationResult(
            symbol=symbol,
            status=DataSupportStatus.MISSING,
            bars=(),
            summary=_summarize(symbol, ()),
            reason_codes=tuple(reason_codes),
            degraded=True,
            duplicate_count=duplicate_count,
        )

    if list(bars) != sorted(bars, key=lambda item: item.session_date):
        reason_codes.append(INVALID_BAR_ORDER)

    extract_corporate_actions(
        {
            "date": bar.session_date,
            "dividend": bar.dividend,
            "split_ratio": bar.split_ratio,
        }
        for bar in bars
    )
    status = DataSupportStatus.OK if not reason_codes else DataSupportStatus.LOW_CONFIDENCE
    return BarNormalizationResult(
        symbol=symbol,
        status=status,
        bars=bars,
        summary=_summarize(symbol, bars),
        reason_codes=tuple(reason_codes),
        degraded=bool(reason_codes),
        duplicate_count=duplicate_count,
    )
