"""Claude via the local Claude Code CLI (`claude -p`), using the user's Claude subscription login.

No API key and no per-call billing: calls count against the subscription's usage limits.
The CLI runs isolated: no built-in tools, no settings/hooks/MCP/slash commands, no saved
sessions, an empty working directory, and API-key variables removed from its environment
so it can never silently fall back to API billing.

The CLI has no native tool-calling channel for Jarvis's tools, so tools use "JSON action
mode": the model answers with a schema-validated JSON action that the core then validates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

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

# (argv, stdin) -> (returncode, stdout, stderr)
Runner = Callable[[list[str], str], tuple[int, str, str]]

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def render_transcript(messages: list[Message]) -> str:
    """Neutral history -> one prompt. A single user message is sent as-is."""
    turns = [m for m in messages if m.role != "system"]
    if len(turns) == 1 and turns[0].role == "user":
        return turns[0].text_content()
    lines = ["<conversation>"]
    for m in turns:
        for part in m.parts:
            if isinstance(part, TextPart):
                lines.append(f"[{m.role}]: {part.text}")
            elif isinstance(part, ToolCall):
                lines.append(f"[assistant tool call {part.id}]: {part.name} {json.dumps(part.arguments, ensure_ascii=False)}")
            elif isinstance(part, ToolResult):
                status = "error" if part.is_error else "result"
                lines.append(f"[tool {status} {part.tool_call_id}]: {part.content}")
    lines.append("</conversation>")
    lines.append("Respond to the last message in the conversation.")
    return "\n".join(lines)


def action_schema(tool_names: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["reply", "tool_call"]},
            "text": {"type": "string"},
            "tool": {"type": "string", "enum": tool_names},
            "arguments": {"type": "object"},
        },
        "required": ["kind"],
        "additionalProperties": False,
    }


def _tools_prompt(req: LLMRequest) -> str:
    lines = [
        "",
        "## Tools",
        'Answer with a JSON action. To reply to the user: {"kind": "reply", "text": "..."}.',
        'To use a tool: {"kind": "tool_call", "tool": "<name>", "arguments": {...}}. One tool per answer.',
        "Available tools:",
    ]
    for t in req.tools:
        lines.append(f"- {t.name}: {t.description} Parameters (JSON Schema): {json.dumps(t.parameters, ensure_ascii=False)}")
    return "\n".join(lines)


def _default_runner(timeout: int) -> Runner:
    def run(argv: list[str], stdin: str) -> tuple[int, str, str]:
        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
        workdir = Path(tempfile.gettempdir()) / "jarvis-claude-code"
        workdir.mkdir(exist_ok=True)
        try:
            r = subprocess.run(
                argv, input=stdin, capture_output=True, text=True, encoding="utf-8",
                timeout=timeout, env=env, cwd=workdir,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"claude CLI timed out after {timeout}s", retryable=True, kind="timeout") from e
        return r.returncode, r.stdout, r.stderr

    return run


class ClaudeCodeProvider:
    name = "claude_code"

    def __init__(self, models: dict[str, Any], executable: str | None = None,
                 runner: Runner | None = None, timeout: int = 300):
        self._models = models
        self._exe = executable or shutil.which("claude")
        self._run = runner or _default_runner(timeout)

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities.from_config(self._models.get(model), self.name)

    def _require_exe(self) -> str:
        if not self._exe:
            raise ProviderError("Claude Code CLI ('claude') not found on PATH", kind="config")
        return self._exe

    def _call(self, req: LLMRequest, schema: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
        exe = self._require_exe()
        system = req.system + (_tools_prompt(req) if req.tools else "")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(system or "You are a helpful assistant.")
            system_file = f.name
        argv = [
            exe, "-p", "--output-format", "json",
            "--tools", "", "--setting-sources", "", "--strict-mcp-config",
            "--disable-slash-commands", "--no-session-persistence",
            "--model", req.model, "--effort", req.reasoning,
            "--system-prompt-file", system_file,
        ]
        if schema is not None:
            argv += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
        start = time.monotonic()
        try:
            code, out, err = self._run(argv, render_transcript(req.messages))
        finally:
            Path(system_file).unlink(missing_ok=True)
        latency_ms = int((time.monotonic() - start) * 1000)
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise ProviderError(f"claude CLI gave no JSON (exit {code}): {err.strip()[:200]}", kind="error") from e
        if data.get("is_error") or code != 0:
            raise self._error(data)
        return data, latency_ms

    @staticmethod
    def _error(data: dict[str, Any]) -> ProviderError:
        status = data.get("api_error_status")
        detail = str(data.get("result") or data.get("subtype") or "unknown error")[:300]
        if status == 429:
            return ProviderError(f"usage limit or rate limit: {detail}", retryable=True, kind="rate_limit")
        if status in (401, 403):
            return ProviderError(f"not logged in to Claude: {detail}", kind="auth")
        if status == 400:
            return ProviderError(f"bad request: {detail}", kind="bad_request")
        if isinstance(status, int) and status >= 500:
            return ProviderError(f"API error {status}", retryable=True, kind="server")
        return ProviderError(detail, kind="error")

    def _response(self, data: dict[str, Any], req: LLMRequest, latency_ms: int,
                  text: str, calls: list[ToolCall]) -> LLMResponse:
        u = data.get("usage") or {}
        usage = Usage(
            # The CLI caches the prompt: count fresh, cache-written and cache-read input alike.
            input_tokens=(u.get("input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0)
            + (u.get("cache_read_input_tokens", 0) or 0),
            output_tokens=u.get("output_tokens", 0) or 0,
            cached_tokens=u.get("cache_read_input_tokens", 0) or 0,
        )
        stop = "tool_use" if calls else _STOP_REASONS.get(data.get("stop_reason") or "", "error")
        return LLMResponse(
            text=text,
            tool_calls=calls,
            stop_reason=stop,
            usage=usage,
            provider=self.name,
            model=req.model,
            latency_ms=latency_ms,
            cost_usd=None,  # subscription: not billed per call
            adapter_state={"notional_usd": data.get("total_cost_usd")},
        )

    # ---- interface ----

    def generate(self, req: LLMRequest) -> LLMResponse:
        if not req.tools:
            # A reply schema keeps only the user-facing text; the CLI's plain "result" can
            # carry stray notes the model writes before its answer.
            data, latency = self._call(req, REPLY_SCHEMA)
            out = data.get("structured_output")
            if not isinstance(out, dict) or not isinstance(out.get("text"), str):
                raise ProviderError("model returned no valid JSON reply", kind="bad_output")
            return self._response(data, req, latency, out["text"], [])

        data, latency = self._call(req, action_schema([t.name for t in req.tools]))
        action = data.get("structured_output")
        if not isinstance(action, dict) or action.get("kind") not in ("reply", "tool_call"):
            raise ProviderError("model returned no valid JSON action", kind="bad_output")
        if action["kind"] == "reply":
            return self._response(data, req, latency, action.get("text", ""), [])
        call = ToolCall(f"call_{uuid.uuid4().hex[:8]}", action.get("tool", ""), action.get("arguments") or {})
        return self._response(data, req, latency, action.get("text", ""), [call])

    def stream(self, req: LLMRequest) -> Iterator[LLMEvent]:
        resp = self.generate(req)
        yield LLMEvent("text_delta", text=resp.text)
        yield LLMEvent("done", response=resp)

    def structured(self, req: LLMRequest, schema: dict[str, Any]) -> StructuredResult:
        data, latency = self._call(req, schema)
        out = data.get("structured_output")
        resp = self._response(data, req, latency, data.get("result") or "", [])
        return StructuredResult(out if isinstance(out, dict) else None, isinstance(out, dict), resp)

    def count_tokens(self, req: LLMRequest) -> TokenCount:
        return TokenCount(estimate_tokens(req), exact=False)

    def health(self) -> ProviderHealth:
        if not self._exe:
            return ProviderHealth(False, "Claude Code CLI ('claude') not found on PATH")
        code, out, _ = self._run([self._exe, "auth", "status"], "")
        try:
            status = json.loads(out)
        except json.JSONDecodeError:
            return ProviderHealth(False, f"could not read 'claude auth status' (exit {code})")
        if not status.get("loggedIn"):
            return ProviderHealth(False, "not logged in: run 'claude' and sign in")
        if status.get("authMethod") != "claude.ai":
            return ProviderHealth(False, f"logged in via {status.get('authMethod')}, not a Claude subscription")
        return ProviderHealth(True, f"Claude subscription login ({status.get('subscriptionType', 'unknown')})")
