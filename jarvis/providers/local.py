"""Local adapter (Stage B): an OpenAI-compatible client for a local inference server.

Built for llama.cpp `llama-server` (GGUF models, Metal). It speaks the server's
`/v1/chat/completions` API with the standard library only (no vendor SDK).

Rules (PLAN.md 5.4):
- Localhost only. The endpoint must be http://localhost, 127.0.0.1 or [::1]. Anything
  else is refused when the provider is built, so this adapter can never quietly turn
  into a cloud provider. Redirects are never followed (http.client does not follow them).
- Capabilities come from config/models.yaml profiles measured on this Mac, not model cards.
- Thinking ("reasoning") is switched off per model through the chat template
  (`chat_template_kwargs`), and any thinking text the server returns is kept out of the
  reply and stored only in adapter_state.
- Structured output uses `response_format: json_schema`, which llama-server turns into a
  grammar (constrained decoding). The core still validates every result itself.
- Tools use the server's native tool calling (`--jinja` chat templates).

Only the provider registry (jarvis.providers.make_provider) imports this module.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import time
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from jarvis.providers.base import (
    LLMEvent,
    LLMRequest,
    LLMResponse,
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

DEFAULT_ENDPOINT = "http://127.0.0.1:8080"
_STOP_REASONS: dict[str, StopReason] = {
    "stop": "end",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}
_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# (method, path, JSON body or None, stream) -> (HTTP status, body chunks; lines when streaming)
Transport = Callable[[str, str, dict[str, Any] | None, bool], tuple[int, Iterator[bytes]]]


def check_endpoint(url: str) -> tuple[str, int]:
    """(host, port) of a loopback http endpoint, or ProviderError. Hostnames other than
    'localhost' are refused, even if they resolve to a loopback address."""
    parts = urlsplit(url)
    if parts.scheme != "http":
        raise ProviderError(f"local provider needs an http://localhost endpoint, got {url!r}", kind="config")
    if parts.username or parts.password:
        raise ProviderError("local provider endpoint must not carry credentials", kind="config")
    host = parts.hostname or ""
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if not loopback:
        raise ProviderError(f"local provider refuses non-localhost endpoint {host!r}", kind="config")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ProviderError("local provider endpoint must be scheme://host:port only", kind="config")
    return host, parts.port or 80


def _http_transport(host: str, port: int, timeout: float) -> Transport:
    def send(method: str, path: str, body: dict[str, Any] | None, stream: bool) -> tuple[int, Iterator[bytes]]:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        try:
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
        except (ConnectionError, socket.timeout, OSError) as e:
            conn.close()
            kind = "timeout" if isinstance(e, socket.timeout) else "connection"
            raise ProviderError(f"local model server not reachable at {host}:{port} ({e})",
                                retryable=True, kind=kind) from e

        def chunks() -> Iterator[bytes]:
            try:
                if stream:
                    while True:
                        line = resp.readline()
                        if not line:
                            break
                        yield line
                else:
                    yield resp.read()
            except (socket.timeout, OSError) as e:
                raise ProviderError(f"local model server stopped answering ({e})", retryable=True,
                                    kind="timeout") from e
            finally:
                conn.close()

        return resp.status, chunks()

    return send


def _error_for(status: int, body: bytes) -> ProviderError:
    try:
        detail = json.loads(body.decode("utf-8", "replace")).get("error", {})
        detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    except (ValueError, AttributeError):
        detail = body.decode("utf-8", "replace")
    detail = (detail or "").strip()[:300]
    if status in (401, 403):
        return ProviderError(f"local server refused the request ({status}): {detail}", kind="auth")
    if status == 400:
        return ProviderError(f"bad request: {detail}", kind="bad_request")
    if status == 503:
        return ProviderError(f"local model still loading or busy: {detail}", retryable=True, kind="server")
    if status >= 500:
        return ProviderError(f"local server error {status}: {detail}", retryable=True, kind="server")
    return ProviderError(f"local server answered {status}: {detail}", kind="error")


class LocalProvider:
    name = "local"

    def __init__(self, models: dict[str, Any], endpoint: str = DEFAULT_ENDPOINT,
                 transport: Transport | None = None, timeout: float = 600):
        host, port = check_endpoint(endpoint)  # refuses anything but localhost, always
        self._models = models
        self.endpoint = endpoint
        self._send = transport or _http_transport(host, port, timeout)

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities.from_config(self._models.get(model), self.name)

    def _profile(self, model: str) -> dict[str, Any]:
        entry = self._models.get(model) or {}
        return entry if entry.get("provider") == self.name else {}

    # ---- translation: neutral -> OpenAI-compatible ----

    @staticmethod
    def _to_messages(req: LLMRequest) -> list[dict[str, Any]]:
        system = [req.system] if req.system else []
        system += [m.text_content() for m in req.messages if m.role == "system"]
        out: list[dict[str, Any]] = []
        if any(system):
            out.append({"role": "system", "content": "\n\n".join(s for s in system if s)})
        for m in req.messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                for p in m.parts:
                    if isinstance(p, ToolResult):
                        content = f"Error: {p.content}" if p.is_error else p.content
                        out.append({"role": "tool", "tool_call_id": p.tool_call_id, "content": content})
                continue
            text = "".join(p.text for p in m.parts if isinstance(p, TextPart))
            calls = [p for p in m.parts if isinstance(p, ToolCall)]
            msg: dict[str, Any] = {"role": m.role, "content": text}
            if calls and m.role == "assistant":
                msg["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                    for c in calls
                ]
            out.append(msg)
        return out

    def build_params(self, req: LLMRequest, schema: dict[str, Any] | None = None,
                     stream: bool = False) -> dict[str, Any]:
        profile = self._profile(req.model)
        caps = self.capabilities(req.model)
        max_tokens = req.max_output
        if caps.max_output:
            max_tokens = min(max_tokens, caps.max_output)
        params: dict[str, Any] = {
            "model": profile.get("server_model", req.model),
            "messages": self._to_messages(req),
            "max_tokens": max_tokens,
            "stream": stream,
        }
        params.update(profile.get("sampling") or {})
        if not profile.get("thinking", False):
            # Qwen3.5 thinks by default; its template reads enable_thinking. Templates without
            # the switch ignore the extra variable.
            params["chat_template_kwargs"] = {"enable_thinking": False}
        if req.tools and schema is None:
            params["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in req.tools
            ]
        if schema is not None:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": schema, "strict": True},
            }
        if stream:
            params["stream_options"] = {"include_usage": True}
        return params

    # ---- translation: OpenAI-compatible -> neutral ----

    @staticmethod
    def _split_thinking(content: str, reasoning: str) -> tuple[str, str]:
        thoughts = [reasoning] if reasoning else []
        thoughts += [t[len("<think>"):-len("</think>")].strip() for t in re.findall(r"<think>.*?</think>", content, re.DOTALL)]
        return _THINK.sub("", content).strip(), "\n".join(t for t in thoughts if t)

    @staticmethod
    def _tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
        calls = []
        for i, c in enumerate(raw or []):
            fn = c.get("function") or {}
            args_text = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_text) if isinstance(args_text, str) else args_text
            except json.JSONDecodeError as e:
                raise ProviderError(f"model gave tool arguments that are not JSON: {args_text[:120]!r}",
                                    kind="bad_output") from e
            if not isinstance(args, dict):
                raise ProviderError("model gave tool arguments that are not a JSON object", kind="bad_output")
            calls.append(ToolCall(c.get("id") or f"call_{i}", fn.get("name") or "", args))
        return calls

    def _response(self, req: LLMRequest, content: str, reasoning: str, raw_calls: list[dict[str, Any]] | None,
                  finish: str | None, usage: dict[str, Any], timings: dict[str, Any], latency_ms: int,
                  ttft_ms: int | None = None) -> LLMResponse:
        text, thoughts = self._split_thinking(content or "", reasoning or "")
        calls = self._tool_calls(raw_calls)
        stop: StopReason = "tool_use" if calls else _STOP_REASONS.get(finish or "", "error")
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or timings.get("cache_n") or 0
        state: dict[str, Any] = {"provider": self.name, "model": req.model}
        if timings:
            state["timings"] = {k: timings[k] for k in ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms",
                                                         "predicted_per_second", "cache_n") if k in timings}
        if ttft_ms is not None:
            state["ttft_ms"] = ttft_ms
        if thoughts:
            state["thinking"] = thoughts  # never shown, never sent back
        return LLMResponse(
            text=text,
            tool_calls=calls,
            stop_reason=stop,
            usage=Usage(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), int(cached)),
            provider=self.name,
            model=req.model,
            latency_ms=latency_ms,
            cost_usd=0.0,  # no money spent; time and resources are in adapter_state
            adapter_state=state,
        )

    def _post(self, path: str, body: dict[str, Any] | None, method: str = "POST") -> dict[str, Any]:
        status, chunks = self._send(method, path, body, False)
        raw = b"".join(chunks)
        if status != 200:
            raise _error_for(status, raw)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise ProviderError("local server gave a response that is not JSON", kind="bad_output") from e
        if not isinstance(data, dict):
            raise ProviderError("local server gave an unexpected response", kind="bad_output")
        return data

    def _complete(self, req: LLMRequest, schema: dict[str, Any] | None) -> LLMResponse:
        start = time.monotonic()
        data = self._post("/v1/chat/completions", self.build_params(req, schema))
        latency_ms = int((time.monotonic() - start) * 1000)
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("local server returned no choices", kind="bad_output")
        msg = choices[0].get("message") or {}
        return self._response(req, msg.get("content") or "", msg.get("reasoning_content") or "",
                              msg.get("tool_calls"), choices[0].get("finish_reason"),
                              data.get("usage") or {}, data.get("timings") or {}, latency_ms)

    # ---- interface ----

    def generate(self, req: LLMRequest) -> LLMResponse:
        return self._complete(req, None)

    def stream(self, req: LLMRequest) -> Iterator[LLMEvent]:
        start = time.monotonic()
        status, chunks = self._send("POST", "/v1/chat/completions", self.build_params(req, stream=True), True)
        if status != 200:
            raise _error_for(status, b"".join(chunks))
        content, reasoning, finish = [], [], None
        calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}
        ttft_ms: int | None = None
        in_think = False
        for line in chunks:
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                break
            try:
                event = json.loads(payload.decode("utf-8"))
            except ValueError:
                continue
            usage = event.get("usage") or usage
            timings = event.get("timings") or timings
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                finish = choice.get("finish_reason") or finish
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": "", "function": {"name": "", "arguments": ""}})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["function"]["name"] += fn.get("name") or ""
                    slot["function"]["arguments"] += fn.get("arguments") or ""
                piece = delta.get("content") or ""
                if not piece:
                    continue
                if ttft_ms is None:
                    ttft_ms = int((time.monotonic() - start) * 1000)
                content.append(piece)
                # Hide inline <think> blocks from the live text, too.
                if "<think>" in piece:
                    in_think = True
                if not in_think:
                    yield LLMEvent("text_delta", text=piece)
                if "</think>" in piece:
                    in_think = False
        latency_ms = int((time.monotonic() - start) * 1000)
        raw_calls = [calls[i] for i in sorted(calls)]
        resp = self._response(req, "".join(content), "".join(reasoning), raw_calls, finish, usage, timings,
                              latency_ms, ttft_ms)
        yield LLMEvent("done", response=resp)

    def structured(self, req: LLMRequest, schema: dict[str, Any]) -> StructuredResult:
        resp = self._complete(req, schema)
        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return StructuredResult(None, False, resp)
        return StructuredResult(data if isinstance(data, dict) else None, isinstance(data, dict), resp)

    def count_tokens(self, req: LLMRequest) -> TokenCount:
        """Exact when the server is up: render the chat template, then tokenize it."""
        try:
            rendered = self._post("/apply-template", {"messages": self._to_messages(req)}).get("prompt")
            if isinstance(rendered, str):
                tokens = self._post("/tokenize", {"content": rendered}).get("tokens")
                if isinstance(tokens, list):
                    return TokenCount(len(tokens), exact=True)
        except ProviderError:
            pass
        return TokenCount(estimate_tokens(req), exact=False)

    def health(self) -> ProviderHealth:
        try:
            data = self._post("/health", None, method="GET")
        except ProviderError as e:
            return ProviderHealth(False, str(e))
        if data.get("status") != "ok":
            return ProviderHealth(False, f"local server status: {data.get('status')}")
        return ProviderHealth(True, f"local model server up at {self.endpoint}")
