"""Deterministic route -> provider/model decision (PLAN.md section 16).

Only approved providers are used, there is no silent fallback, and capabilities are
never assumed. The fake provider is a local test double and is always allowed.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import Config
from jarvis.providers.base import ModelCapabilities

FAKE_MODEL = "fake-1"


class RoutingError(Exception):
    pass


@dataclass(frozen=True)
class RouteDecision:
    route: str
    provider: str
    model: str
    effort: str
    reason: str


def decide(config: Config, route: str, provider_override: str | None = None) -> RouteDecision:
    if provider_override == "fake":
        return RouteDecision(route, "fake", FAKE_MODEL, "medium", "override: fake provider")

    routes = config.routing.get("routes", {})
    if route not in routes:
        raise RoutingError(f"unknown route: {route}")
    spec = routes[route]
    approved = set(config.routing.get("approved_providers", []))
    cloud_allowed = bool(config.routing.get("cloud_allowed", False))
    needs = spec.get("needs", [])

    skipped: list[str] = []
    for cand in spec.get("candidates", []):
        provider, model = cand["provider"], cand["model"]
        label = f"{provider}/{model}"
        if provider_override and provider != provider_override:
            skipped.append(f"{label}: not the requested provider")
            continue
        if provider not in approved:
            skipped.append(f"{label}: provider not approved")
            continue
        kind = config.providers.get(provider, {}).get("kind")
        if kind == "cloud" and not cloud_allowed:
            skipped.append(f"{label}: cloud not allowed")
            continue
        caps = ModelCapabilities.from_config(config.models.get(model), provider)
        missing = [n for n in needs if not caps.has(n)]
        if missing:
            skipped.append(f"{label}: missing {', '.join(missing)}")
            continue
        reason = "first eligible candidate"
        if skipped:
            reason += " (skipped: " + "; ".join(skipped) + ")"
        return RouteDecision(route, provider, model, cand.get("effort", "medium"), reason)

    raise RoutingError(f"no eligible candidate for route {route}: " + ("; ".join(skipped) or "none listed"))
