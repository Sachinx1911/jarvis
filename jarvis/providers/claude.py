"""Claude adapter (Stage A). The only module allowed to import the Anthropic SDK.

Phase 0 scope: generate() for plain chat plus tool-call translation.
stream() and structured() arrive in Phase 1 with the contract tests.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import anthropic

from jarvis.providers.base import (
    LLMEvent,
    LLMRequest,
    LLMResponse,
    Message,
    ModelCapabilities,
    ProviderError,
    ProviderHealth,
    StopReason,
    StructuredResult,
    TextPart,
    TokenCount,
    ToolCall,
    ToolResult,
    Usage,
    estimate_tokens,
)

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class ClaudeProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, models: dict[str, Any], client: Any = None):
        self._models = models
        if client is not None:
            self._client = client
        elif api_key:
            self._client = anthropic.Anthropic(api_key=api_key, max_retries=2)
        else:
            self._client = None

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities.from_config(self._models.get(model))

    # ---- translation: neutral -> Claude ----

    def _to_claude_message(self, msg: Message, model: str) -> dict[str, Any]:
        state = msg.adapter_state or {}
        # Replay our own assistant turns unchanged (thinking blocks are bound to the
        # model and conversation; editing them can be rejected by the API).
        if state.get("provider") == self.name and state.get("model") == model and "content" in state:
            return {"role": msg.role, "content": state["content"]}

        blocks: list[dict[str, Any]] = []
        for part in msg.parts:
            if isinstance(part, TextPart):
                blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, ToolCall):
                blocks.append({"type": "tool_use", "id": part.id, "name": part.name, "input": part.arguments})
            elif isinstance(part, ToolResult):
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": part.tool_call_id,
                    "content": part.content,
                    "is_error": part.is_error,
                })
        role = "user" if msg.role == "tool" else msg.role
        return {"role": role, "content": blocks}

    def build_params(self, req: LLMRequest) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_output,
            "messages": [self._to_claude_message(m, req.model) for m in req.messages if m.role != "system"],
            "output_config": {"effort": req.reasoning},
        }
        if req.system:
            params["system"] = req.system
        if req.tools:
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in req.tools
            ]
        return params

    # ---- translation: Claude -> neutral ----

    def _cost(self, model: str, usage: Usage) -> float | None:
        price = (self._models.get(model) or {}).get("price_usd_per_mtok")
        if not price:
            return None
        cache_price = price.get("cache_read", price["input"])
        return (
            usage.input_tokens * price["input"]
            + usage.cached_tokens * cache_price
            + usage.output_tokens * price["output"]
        ) / 1_000_000

    def parse_response(self, raw: Any, model: str, latency_ms: int) -> LLMResponse:
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in raw.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
        u = raw.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cached_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        return LLMResponse(
            text="".join(texts),
            tool_calls=calls,
            stop_reason=_STOP_REASONS.get(raw.stop_reason or "", "error"),
            usage=usage,
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
            cost_usd=self._cost(model, usage),
            adapter_state={
                "provider": self.name,
                "model": model,
                "content": [b.model_dump(exclude_none=True) for b in raw.content],
            },
        )

    # ---- interface ----

    def _require_client(self) -> Any:
        if self._client is None:
            raise ProviderError("No Anthropic API key. Run: jarvis secret set anthropic_api_key", kind="auth")
        return self._client

    def generate(self, req: LLMRequest) -> LLMResponse:
        client = self._require_client()
        start = time.monotonic()
        try:
            raw = client.messages.create(**self.build_params(req))
        except anthropic.AuthenticationError as e:
            raise ProviderError(f"authentication failed ({e.status_code})", kind="auth") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("rate limited", retryable=True, kind="rate_limit") from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"bad request: {e.message}", kind="bad_request") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"API error {e.status_code}", retryable=e.status_code >= 500, kind="server") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("cannot reach the Anthropic API", retryable=True, kind="connection") from e
        latency_ms = int((time.monotonic() - start) * 1000)
        return self.parse_response(raw, req.model, latency_ms)

    def stream(self, req: LLMRequest) -> Iterator[LLMEvent]:
        raise NotImplementedError("Claude streaming arrives in Phase 1")

    def structured(self, req: LLMRequest, schema: dict[str, Any]) -> StructuredResult:
        raise NotImplementedError("Claude structured output arrives in Phase 1")

    def count_tokens(self, req: LLMRequest) -> TokenCount:
        return TokenCount(estimate_tokens(req), exact=False)

    def health(self) -> ProviderHealth:
        if self._client is None:
            return ProviderHealth(False, "no API key in the secret store")
        return ProviderHealth(True, "API key present (not verified against the API)")
