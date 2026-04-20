"""Configuration loading and deterministic fingerprinting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from swingtrader_v2.domain.enums import EnvironmentName
from swingtrader_v2.domain.exceptions import ConfigLoadError
from swingtrader_v2.domain.models import EffectiveConfig

CONFIG_FILES = (
    "universe",
    "features",
    "setups",
    "anchors",
    "eligibility",
    "prioritization",
    "artifacts",
    "tracking"
)


def _parse_yaml_like(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
    try:
        loaded = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigLoadError(
            f"Unable to parse {path}. Phase 1 expects JSON-compatible YAML documents."
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigLoadError(f"Configuration file {path} must contain a top-level object.")
    return loaded


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def canonicalize_config(config: dict[str, Any]) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint_config(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize_config(config).encode("utf-8")).hexdigest()


def load_config_documents(config_root: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(config_root)
    documents: dict[str, dict[str, Any]] = {}
    missing = [name for name in CONFIG_FILES if not (root / f"{name}.yaml").exists()]
    if missing:
        raise ConfigLoadError(f"Missing required config files: {', '.join(sorted(missing))}")
    for name in CONFIG_FILES:
        documents[name] = _parse_yaml_like(root / f"{name}.yaml")
    return documents


def load_effective_config(
    config_root: str | Path,
    *,
    environment: EnvironmentName = EnvironmentName.LOCAL
) -> EffectiveConfig:
    root = Path(config_root)
    documents = load_config_documents(root)
    effective: dict[str, Any] = {}
    for name in CONFIG_FILES:
        effective = _deep_merge(effective, documents[name])

    overlay_path = root / "environments" / f"{environment.value}.yaml"
    if overlay_path.exists():
        effective = _deep_merge(effective, _parse_yaml_like(overlay_path))

    env_block = effective.setdefault("environment", {})
    env_block.setdefault("name", environment.value)

    return EffectiveConfig(
        environment=environment,
        documents=documents,
        effective=effective,
        fingerprint=fingerprint_config(effective)
    )
