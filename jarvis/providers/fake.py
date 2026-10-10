"""Deterministic test double. Offline; the whole test suite runs against it."""

from __future__ import annotations

import json
import re
from collections import deque
from typing import Any, Iterator

from jarvis.providers.base import (
    LLMEvent,
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ProviderHealth,
    StructuredResult,
    TokenCount,
    Usage,
    estimate_tokens,
)

GREETING = re.compile(
    r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|namaskar|namaste|नमस्कार|नमस्ते)\b",
    re.IGNORECASE,
)


class FakeProvider:
    name = "fake"

    def __init__(self, script: list[str] | None = None, models: dict[str, Any] | None = None):
        self._script = deque(script or [])
        self._models = models or {}
        self.requests: list[LLMRequest] = []

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities.from_config(self._models.get(model))

    def _reply(self, req: LLMRequest) -> str:
        if self._script:
            return self._script.popleft()
        last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
        text = last_user.text_content() if last_user else ""
        if GREETING.match(text):
            return "Good evening, sir."
        return f"[fake] {text}"

    def generate(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        text = self._reply(req)
        return LLMResponse(
            text=text,
            tool_calls=[],
            stop_reason="end",
            usage=Usage(input_tokens=estimate_tokens(req), output_tokens=max(1, len(text) // 4)),
            provider=self.name,
            model=req.model,
            latency_ms=0,
            cost_usd=0.0,
        )

    def stream(self, req: LLMRequest) -> Iterator[LLMEvent]:
        resp = self.generate(req)
        for word in resp.text.split(" "):
            yield LLMEvent("text_delta", text=word + " ")
        yield LLMEvent("done", response=resp)

    def structured(self, req: LLMRequest, schema: dict[str, Any]) -> StructuredResult:
        resp = self.generate(req)
        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return StructuredResult(None, False, resp)
        return StructuredResult(data, isinstance(data, dict), resp)

    def count_tokens(self, req: LLMRequest) -> TokenCount:
        return TokenCount(estimate_tokens(req), exact=False)

    def health(self) -> ProviderHealth:
        return ProviderHealth(True, "fake provider is always available")
