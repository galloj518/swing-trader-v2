"""Deterministic identifier construction rules."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from swingtrader_v2.domain.exceptions import DeterministicIdError


def _normalize_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise DeterministicIdError("ID token cannot be empty after normalization.")
    return normalized


def _canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(payload: dict[str, Any], length: int = 16) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()[:length]


def build_run_id(*, as_of_date: date, environment: str, universe_name: str, config_fingerprint: str) -> str:
    env = _normalize_token(environment)
    universe = _normalize_token(universe_name)
    day_token = as_of_date.strftime("%Y%m%d")
    suffix = _digest(
        {
            "as_of_date": as_of_date.isoformat(),
            "environment": env,
            "universe_name": universe,
            "config_fingerprint": config_fingerprint
        }
    )
    return f"run_{env}_{day_token}_{suffix}"


def build_packet_id(*, symbol: str, setup_family: str, as_of_date: date, run_id: str) -> str:
    ticker = _normalize_token(symbol)
    family = _normalize_token(setup_family)
    day_token = as_of_date.strftime("%Y%m%d")
    suffix = _digest(
        {
            "symbol": ticker,
            "setup_family": family,
            "as_of_date": as_of_date.isoformat(),
            "run_id": run_id
        }
    )
    return f"pkt_{ticker}_{day_token}_{suffix}"


def build_anchor_id(*, symbol: str, anchor_name: str, anchor_source: str, config_fingerprint: str) -> str:
    ticker = _normalize_token(symbol)
    suffix = _digest(
        {
            "symbol": ticker,
            "anchor_name": _normalize_token(anchor_name),
            "anchor_source": _normalize_token(anchor_source),
            "config_fingerprint": config_fingerprint
        }
    )
    return f"anc_{ticker}_{suffix}"
