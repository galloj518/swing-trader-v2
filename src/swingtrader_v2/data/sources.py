"""Provider contracts and baseline yfinance adapter for daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Protocol

from swingtrader_v2.domain.enums import MarketDataProvider, ProviderMode
from swingtrader_v2.domain.exceptions import SwingTraderError


class ProviderError(SwingTraderError):
    """Raised when a provider cannot satisfy a request."""


@dataclass(frozen=True)
class ProviderBarsPayload:
    symbol: str
    provider: MarketDataProvider
    provider_mode: ProviderMode
    rows: tuple[dict[str, Any], ...]
    degraded: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ProviderSymbolRecord:
    symbol: str
    exchange: str
    asset_type: str
    currency: str
    name: str | None = None


class DailyBarProvider(Protocol):
    provider: MarketDataProvider
    provider_mode: ProviderMode

    def fetch_daily_bars(self, symbols: list[str], *, start: date, end: date) -> dict[str, ProviderBarsPayload]:
        """Return normalized provider rows for each symbol."""


class YFinanceDailyBarSource:
    provider = MarketDataProvider.YFINANCE
    provider_mode = ProviderMode.BASELINE

    def __init__(self, download_fn: Callable[..., Any] | None = None) -> None:
        self._download_fn = download_fn

    def _resolve_download(self) -> Callable[..., Any]:
        if self._download_fn is not None:
            return self._download_fn
        try:
            import yfinance as yf  # type: ignore
        except ImportError as exc:
            raise ProviderError("yfinance is not installed for live provider use.") from exc
        return yf.download

    def fetch_daily_bars(self, symbols: list[str], *, start: date, end: date) -> dict[str, ProviderBarsPayload]:
        download = self._resolve_download()
        frame = download(
            tickers=" ".join(symbols),
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            actions=True,
            progress=False,
            group_by="ticker",
        )
        payloads: dict[str, ProviderBarsPayload] = {}
        for symbol in symbols:
            symbol_frame = frame[symbol] if hasattr(frame, "columns") and symbol in getattr(frame, "columns", []) else frame
            rows: list[dict[str, Any]] = []
            for index, row in symbol_frame.iterrows():
                rows.append(
                    {
                        "date": index.date().isoformat(),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "adjusted_close": float(row.get("Adj Close", row["Close"])),
                        "volume": int(row["Volume"]),
                        "dividend": float(row.get("Dividends", 0.0)),
                        "split_ratio": row.get("Stock Splits", 1.0),
                    }
                )
            payloads[symbol] = ProviderBarsPayload(
                symbol=symbol,
                provider=self.provider,
                provider_mode=self.provider_mode,
                rows=tuple(rows),
                degraded=False,
                reason_codes=(),
            )
        return payloads


class SchwabDailyBarSourceStub:
    provider = MarketDataProvider.SCHWAB
    provider_mode = ProviderMode.OPTIONAL

    def fetch_daily_bars(self, symbols: list[str], *, start: date, end: date) -> dict[str, ProviderBarsPayload]:
        raise ProviderError("Schwab support is planned later and is intentionally a stub in v1.")
