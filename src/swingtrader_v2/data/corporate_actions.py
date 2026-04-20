"""Explicit split and dividend handling for normalized daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class CorporateAction:
    action_type: str
    ex_date: date
    value: float
    raw_value: str | None = None


def parse_split_ratio(raw_value: str | float | int | None) -> float:
    if raw_value in (None, "", 0, 0.0):
        return 1.0
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    text = str(raw_value).strip()
    if ":" in text:
        left, right = text.split(":", 1)
        return float(left) / float(right)
    if "/" in text:
        left, right = text.split("/", 1)
        return float(left) / float(right)
    return float(text)


def extract_corporate_actions(rows: Iterable[dict]) -> tuple[CorporateAction, ...]:
    actions: list[CorporateAction] = []
    for row in rows:
        bar_date = row["date"]
        if isinstance(bar_date, str):
            bar_date = date.fromisoformat(bar_date)
        dividend = float(row.get("dividend", 0.0) or 0.0)
        split_ratio = parse_split_ratio(row.get("split_ratio"))
        if dividend > 0.0:
            actions.append(CorporateAction("dividend", bar_date, dividend))
        if split_ratio != 1.0:
            actions.append(
                CorporateAction(
                    action_type="split",
                    ex_date=bar_date,
                    value=split_ratio,
                    raw_value=str(row.get("split_ratio")),
                )
            )
    actions.sort(key=lambda item: (item.ex_date, item.action_type))
    return tuple(actions)


def cumulative_split_factor(actions: Iterable[CorporateAction], *, through_date: date | None = None) -> float:
    factor = 1.0
    for action in actions:
        if action.action_type != "split":
            continue
        if through_date is not None and action.ex_date > through_date:
            continue
        factor *= action.value
    return factor
