"""Optional manual portfolio snapshot normalization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    shares: float
    average_cost: float | None = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    positions: tuple[PortfolioPosition, ...]
    reason_codes: tuple[str, ...]
    degraded: bool


def _load_raw_positions(payload: str | Path | Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload, (str, Path)) and Path(payload).exists():
        return json.loads(Path(payload).read_text(encoding="utf-8"))
    if isinstance(payload, (str, Path)):
        raise ValueError("Portfolio snapshot path does not exist.")
    return [dict(item) for item in payload]


def normalize_portfolio_snapshot(payload: str | Path | Iterable[dict[str, Any]]) -> PortfolioSnapshot:
    raw_positions = _load_raw_positions(payload)
    aggregated: dict[str, dict[str, float | None]] = {}
    duplicate_symbols = False
    for row in raw_positions:
        symbol = str(row["symbol"]).upper()
        shares = float(row["shares"])
        average_cost = None if row.get("average_cost") in (None, "") else float(row["average_cost"])
        if symbol in aggregated:
            duplicate_symbols = True
            aggregated[symbol]["shares"] = float(aggregated[symbol]["shares"]) + shares
        else:
            aggregated[symbol] = {"shares": shares, "average_cost": average_cost}
    positions = tuple(
        PortfolioPosition(symbol=symbol, shares=float(values["shares"]), average_cost=values["average_cost"])
        for symbol, values in sorted(aggregated.items())
    )
    reasons = ("duplicate_symbol_aggregated",) if duplicate_symbols else ()
    return PortfolioSnapshot(positions=positions, reason_codes=reasons, degraded=duplicate_symbols)
