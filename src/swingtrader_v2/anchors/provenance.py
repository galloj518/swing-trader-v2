"""Explicit provenance records for resolved anchors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AnchorProvenance:
    source_family: str
    source_name: str
    source_date: date | None
    source_bar_index: int | None
    notes: tuple[str, ...] = ()
