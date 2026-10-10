"""Settings for the proactive features: config/proactive.yaml + `proactive_file:` in config/local.yaml.

Kept apart from jarvis/config.py so this phase does not change the shared Config type.
Provider routes for this module live in config/proactive.yaml and are added to the
routing table in memory only; config/routing.yaml is never written.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from jarvis.config import Config, _merge, _read_yaml
from jarvis.paths import CONFIG_DIR
from jarvis.routing.policy import RouteDecision, decide

DEFAULT_TZ = "Asia/Kolkata"

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class ProactiveSettings:
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tz_name(self) -> str:
        return str(self.raw.get("timezone") or DEFAULT_TZ)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name) or {}
        return value if isinstance(value, dict) else {}

    def clock(self) -> Clock:
        tz = self.tz
        return lambda: datetime.now(tz)

    # ---- quiet hours ----

    def in_quiet_hours(self, now: datetime) -> bool:
        q = self.section("quiet_hours")
        if not q.get("start") or not q.get("end"):
            return False
        start, end = _hhmm(q["start"]), _hhmm(q["end"])
        t = now.astimezone(self.tz).time()
        if start <= end:
            return start <= t < end
        return t >= start or t < end  # window crosses midnight

    # ---- telegram ----

    @property
    def telegram_user_id(self) -> int | None:
        value = self.section("telegram").get("allowed_user_id")
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @property
    def telegram_secret(self) -> str:
        return str(self.section("telegram").get("secret") or "telegram_bot_token")


def _hhmm(text: str) -> time:
    h, _, m = str(text).partition(":")
    return time(int(h), int(m or 0))


def load_settings(config_dir: Path = CONFIG_DIR) -> ProactiveSettings:
    local = _read_yaml(config_dir / "local.yaml")
    return ProactiveSettings(_merge(_read_yaml(config_dir / "proactive.yaml"), local.get("proactive_file", {})))


def with_routes(config: Config, settings: ProactiveSettings) -> Config:
    """The shared Config plus this module's routes (in memory only)."""
    extra = settings.raw.get("routes") or {}
    if not extra:
        return config
    routing = dict(config.routing)
    routing["routes"] = {**extra, **(config.routing.get("routes") or {})}  # shared routes win on a clash
    return dataclasses.replace(config, routing=routing)


def decide_route(config: Config, settings: ProactiveSettings, route: str,
                 provider_override: str | None = None) -> RouteDecision:
    """RoutingError goes to the caller. The local cloud override (Telegram /cloud) applies."""
    from jarvis.proactive.cloud import apply_cloud_override

    return decide(apply_cloud_override(with_routes(config, settings)), route, provider_override)
