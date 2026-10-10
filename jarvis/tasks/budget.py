"""Per-task budget across all agents (PLAN.md 9.4, 16): model calls, tokens and notional cost.

Subscription calls are not billed per call, so cost is tracked as "notional" USD: what the
same calls would cost at API prices. Thread-safe: researchers run in parallel.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from jarvis.core.loop import BudgetExceeded
from jarvis.db import notional_usd
from jarvis.providers.base import LLMResponse


@dataclass(frozen=True)
class Budget:
    max_model_calls: int = 60
    max_tokens: int = 1_500_000
    max_notional_usd: float = 3.0
    max_steps_per_agent: int = 8

    @classmethod
    def from_config(cls, cfg: dict | None, override: dict | None = None) -> "Budget":
        merged = {**(cfg or {}), **(override or {})}
        known = {k: merged[k] for k in cls.__dataclass_fields__ if k in merged}
        return cls(**known)


class BudgetTracker:
    def __init__(self, budget: Budget, spent_calls: int = 0, spent_tokens: int = 0, spent_usd: float = 0.0):
        self.budget = budget
        self.calls = spent_calls
        self.tokens = spent_tokens
        self.usd = spent_usd
        self._lock = threading.Lock()

    def charge(self, resp: LLMResponse) -> None:
        with self._lock:
            self.calls += 1
            self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
            self.usd += notional_usd(resp) or 0.0
            over = self._over()
        if over:
            raise BudgetExceeded(over)

    def _over(self) -> str | None:
        b = self.budget
        if self.calls > b.max_model_calls:
            return f"model call limit reached ({b.max_model_calls})"
        if self.tokens > b.max_tokens:
            return f"token limit reached ({b.max_tokens})"
        if self.usd > b.max_notional_usd:
            return f"cost limit reached (${b.max_notional_usd:.2f} notional)"
        return None

    def summary(self) -> str:
        return (f"{self.calls}/{self.budget.max_model_calls} calls, {self.tokens:,} tokens, "
                f"${self.usd:.2f} of ${self.budget.max_notional_usd:.2f} (notional)")
