"""Load config/*.yaml, with machine-specific overrides from config/local.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from jarvis.paths import CONFIG_DIR


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class Config:
    providers: dict[str, Any]
    models: dict[str, Any]
    routing: dict[str, Any]
    tools: dict[str, Any] = field(default_factory=dict)


def load_config(config_dir: Path = CONFIG_DIR) -> Config:
    local = _read_yaml(config_dir / "local.yaml")
    providers = _merge(_read_yaml(config_dir / "providers.yaml"), local.get("providers_file", {}))
    models = _merge(_read_yaml(config_dir / "models.yaml"), local.get("models_file", {}))
    routing = _merge(_read_yaml(config_dir / "routing.yaml"), local.get("routing_file", {}))
    tools = _merge(_read_yaml(config_dir / "tools.yaml"), local.get("tools_file", {}))
    return Config(
        providers=providers.get("providers", {}),
        models=models.get("models", {}),
        routing=routing,
        tools=tools,
    )
