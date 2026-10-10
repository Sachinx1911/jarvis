"""Provider-neutral types and the ReasoningProvider interface (PLAN.md 5.3).

Nothing in this file knows about a vendor. Core code depends only on these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]
StopReason = Literal["end", "tool_use", "max_tokens", "refusal", "error", "cancelled"]
Reasoning = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


Part = TextPart | ToolCall | ToolResult


@dataclass
class Message:
    role: Role
    parts: list[Part]
    # Opaque provider data (e.g. raw blocks with thinking). Only the adapter that wrote it
    # reads it, and only for the same provider and model. Never needed to resume a task.
    adapter_state: dict[str, Any] | None = None

    @classmethod
    def text(cls, role: Role, text: str) -> "Message":
        return cls(role, [TextPart(text)])

    def text_content(self) -> str:
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # portable JSON Schema subset; risk tier never goes here


@dataclass
class LLMRequest:
    route: str
    model: str
    messages: list[Message]
    system: str = ""
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    reasoning: Reasoning = "medium"
    max_output: int = 16000
    task_id: str | None = None
    budget_usd: float | None = None
    privacy_classes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage
    provider: str
    model: str
    latency_ms: int
    cost_usd: float | None = None
    adapter_state: dict[str, Any] | None = None

    def to_message(self) -> Message:
        parts: list[Part] = []
        if self.text:
            parts.append(TextPart(self.text))
        parts.extend(self.tool_calls)
        return Message("assistant", parts, self.adapter_state)


@dataclass(frozen=True)
class LLMEvent:
    type: Literal["text_delta", "done"]
    text: str = ""
    response: LLMResponse | None = None


@dataclass(frozen=True)
class StructuredResult:
    data: dict[str, Any] | None
    valid: bool
    response: LLMResponse


@dataclass(frozen=True)
class TokenCount:
    input_tokens: int
    exact: bool


@dataclass(frozen=True)
class ProviderHealth:
    ok: bool
    detail: str


@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int = 0
    max_output: int = 0
    tool_calling: Literal["none", "single", "parallel"] = "none"
    structured_output: Literal["none", "json_mode", "json_schema", "grammar"] = "none"
    vision: bool = False
    streaming: bool = False
    prompt_caching: bool = False
    reasoning_control: bool = False
    languages_verified: tuple[str, ...] = ()
    source: Literal["documented", "measured", "unknown"] = "unknown"

    @classmethod
    def from_config(cls, entry: dict[str, Any] | None) -> "ModelCapabilities":
        if not entry:
            return cls()  # unknown counts as unsupported
        known = {k: entry[k] for k in cls.__dataclass_fields__ if k in entry}
        if "languages_verified" in known:
            known["languages_verified"] = tuple(known["languages_verified"])
        return cls(**known)

    def has(self, need: str) -> bool:
        if need == "tools":
            return self.tool_calling != "none"
        if need == "structured_output":
            return self.structured_output != "none"
        return bool(getattr(self, need, False))


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, kind: str = "error"):
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind  # auth | rate_limit | connection | bad_request | server | error


@runtime_checkable
class ReasoningProvider(Protocol):
    name: str

    def capabilities(self, model: str) -> ModelCapabilities: ...
    def generate(self, req: LLMRequest) -> LLMResponse: ...
    def stream(self, req: LLMRequest) -> Iterator[LLMEvent]: ...
    def structured(self, req: LLMRequest, schema: dict[str, Any]) -> StructuredResult: ...
    def count_tokens(self, req: LLMRequest) -> TokenCount: ...
    def health(self) -> ProviderHealth: ...


def estimate_tokens(req: LLMRequest) -> int:
    """Rough fallback: about 4 characters per token."""
    chars = len(req.system) + sum(len(m.text_content()) for m in req.messages)
    return max(1, chars // 4)
