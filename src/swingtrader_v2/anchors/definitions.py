"""Config-driven anchor definitions for v1 anchor families."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


SUPPORTED_ANCHOR_FAMILIES = (
    "swing_pivot_high",
    "swing_pivot_low",
    "gap_up_day",
    "gap_down_day",
    "breakout_pivot_day",
    "breakdown_pivot_day",
    "manual_anchor",
)


@dataclass(frozen=True)
class AnchorDefinition:
    family: str
    name: str
    window: int = 5
    minimum_gap_pct: float = 0.02
    breakout_lookback: int = 20
    stale_after_bars: int = 60
    enabled: bool = True
    metadata: dict[str, str | float | int | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ManualAnchorDefinition(AnchorDefinition):
    anchor_date: date | None = None
    anchor_value: float | None = None
    notes: tuple[str, ...] = ()


def validate_anchor_definition(definition: AnchorDefinition) -> AnchorDefinition:
    if definition.family not in SUPPORTED_ANCHOR_FAMILIES:
        raise ValueError(f"Unsupported anchor family: {definition.family}")
    return definition
