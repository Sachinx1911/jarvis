"""Local adapter (Stage B) contract tests, offline: a fake llama-server on 127.0.0.1.

The same contract as the Claude adapters: neutral messages, tools, tool calls and tool
results, stop reasons, usage, structured output, errors, health. Plus the local-only rules:
localhost endpoints only, thinking off, never approved in routing.yaml. No real model runs.
"""

import ast
import dataclasses
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jarvis.config import load_config
from jarvis.providers import make_provider
from jarvis.providers.base import LLMRequest, Message, ProviderError, ReasoningProvider, ToolCall, ToolResult, ToolSpec
from jarvis.providers.local import LocalProvider, check_endpoint
from jarvis.routing.policy import RoutingError, decide

MODELS = {
    "test-local-9b": {
        "provider": "local", "context_window": 16384, "max_output": 2048, "tool_calling": "single",
        "structured_output": "json_schema", "streaming": True, "source": "measured",
        "sampling": {"temperature": 0.7, "top_k": 20, "seed": 42},
    },
    "test-local-thinker": {"provider": "local", "thinking": True, "source": "measured"},
    "claude-opus-5-5": {"provider": "anthropic", "tool_calling": "parallel", "structured_output": "json_schema"},
}
TOOL = ToolSpec("read_file", "Read a file.", {"type": "object", "properties": {"path": {"type": "string"}},
                                              "required": ["path"]})


class FakeServer:
    """Scripted replies: dict (JSON 200), (status, dict), or {"sse": [events]}."""

    def __init__(self):
        self.replies: list = []
        self.requests: list[tuple[str, str, dict | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.requests.append((self.command, self.path, body))
                item = outer.replies.pop(0) if outer.replies else {"error": "no scripted reply"}
                status, payload = item if isinstance(item, tuple) else (200, item)
                if isinstance(payload, dict) and "sse" in payload:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for event in payload["sse"]:
                        self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = _reply
            do_POST = _reply

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def body(self, i: int = -1) -> dict:
        return self.requests[i][2] or {}


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


def _provider(server) -> LocalProvider:
    return LocalProvider(MODELS, server.url, timeout=10)


def _completion(content="", tool_calls=None, finish="stop", reasoning=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 100}},
            "timings": {"prompt_n": 20, "prompt_ms": 50.0, "predicted_n": 8, "predicted_ms": 400.0,
                        "predicted_per_second": 20.0, "cache_n": 100}}


# ---- localhost only ----

@pytest.mark.parametrize("url", [
    "https://api.openai.com", "http://api.openai.com:8080", "http://10.0.0.5:8080", "http://0.0.0.0:8080",
    "http://localhost.evil.com:8080", "http://127.0.0.1@evil.com:8080", "http://user:pw@127.0.0.1:8080",
    "https://127.0.0.1:8080", "http://127.0.0.1:8080/v1", "ftp://localhost", "",
])
def test_refuses_non_localhost_endpoints(url):
    with pytest.raises(ProviderError) as e:
        LocalProvider(MODELS, url)
    assert e.value.kind == "config"


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://localhost:8080", "http://[::1]:8080",
                                 "http://127.0.0.2:9000/"])
def test_accepts_loopback_endpoints(url):
    assert check_endpoint(url)[1] in (8080, 9000)


def test_registry_builds_local_from_config_and_refuses_remote(monkeypatch):
    config = load_config()
    provider = make_provider("local", config)
    assert isinstance(provider, ReasoningProvider) and provider.name == "local"
    assert provider.endpoint.startswith("http://127.0.0.1")
    bad = dataclasses.replace(config, providers={**config.providers, "local": {"endpoint": "http://example.com:8080"}})
    with pytest.raises(ProviderError):
        make_provider("local", bad)


def test_only_the_registry_imports_the_local_adapter():
    package = Path(__file__).resolve().parent.parent / "jarvis"
    importers = []
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(n == "jarvis.providers.local" for n in names):
                importers.append(str(path.relative_to(package)))
    assert sorted(set(importers)) == ["providers/__init__.py"]


def test_local_is_not_approved_for_live_routing():
    config = load_config()
    assert "local" not in config.routing.get("approved_providers", [])
    for route, spec in config.routing.get("routes", {}).items():
        assert all(c["provider"] != "local" for c in spec.get("candidates", [])), route
    with pytest.raises(RoutingError):
        decide(config, "main_chat", "local")


# ---- translation, text and stop reasons ----

def test_text_reply_usage_and_request_shape(server):
    server.replies.append(_completion("Good evening, sir."))
    req = LLMRequest("main_chat", "test-local-9b", [Message.text("user", "hello")], system="sys", max_output=16000)
    resp = _provider(server).generate(req)
    assert (resp.text, resp.stop_reason, resp.provider, resp.cost_usd) == ("Good evening, sir.", "end", "local", 0.0)
    assert (resp.usage.input_tokens, resp.usage.output_tokens, resp.usage.cached_tokens) == (120, 8, 100)
    assert resp.adapter_state["timings"]["predicted_per_second"] == 20.0
    method, path, body = server.requests[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello"}]
    assert body["max_tokens"] == 2048                      # capped by the measured profile
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["temperature"] == 0.7 and body["seed"] == 42 and body["stream"] is False
    assert "tools" not in body and "response_format" not in body


def test_thinking_kept_out_of_reply(server):
    server.replies.append(_completion("<think>step one</think>\nNamaskar, sir.", reasoning="more"))
    resp = _provider(server).generate(LLMRequest("r", "test-local-9b", [Message.text("user", "x")]))
    assert resp.text == "Namaskar, sir."
    assert "step one" in resp.adapter_state["thinking"] and "more" in resp.adapter_state["thinking"]


def test_thinking_model_does_not_force_switch(server):
    server.replies.append(_completion("ok"))
    _provider(server).generate(LLMRequest("r", "test-local-thinker", [Message.text("user", "x")]))
    assert "chat_template_kwargs" not in server.body()


@pytest.mark.parametrize("finish,stop", [("length", "max_tokens"), ("content_filter", "refusal"),
                                         ("weird", "error"), ("stop", "end")])
def test_stop_reasons_map_to_neutral(server, finish, stop):
    server.replies.append(_completion("x", finish=finish))
    assert _provider(server).generate(LLMRequest("r", "test-local-9b", [Message.text("user", "x")])).stop_reason == stop


# ---- tools ----

def test_tool_calls_round_trip(server):
    server.replies.append(_completion("", tool_calls=[
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}],
        finish="tool_calls"))
    provider = _provider(server)
    resp = provider.generate(LLMRequest("r", "test-local-9b", [Message.text("user", "read a.txt")], tools=[TOOL]))
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls == [ToolCall("c1", "read_file", {"path": "a.txt"})]
    sent = server.body()["tools"][0]
    assert sent == {"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                                     "parameters": TOOL.parameters}}

    server.replies.append(_completion("Done, sir."))
    history = [Message.text("user", "read a.txt"), resp.to_message(),
               Message("tool", [ToolResult("c1", "file text"), ToolResult("c2", "boom", is_error=True)])]
    provider.generate(LLMRequest("r", "test-local-9b", history, tools=[TOOL]))
    msgs = server.body()["messages"]
    assert msgs[1] == {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]}
    assert msgs[2] == {"role": "tool", "tool_call_id": "c1", "content": "file text"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "c2", "content": "Error: boom"}


@pytest.mark.parametrize("args", ['{"path": ', '["a"]'])
def test_bad_tool_arguments_are_bad_output(server, args):
    server.replies.append(_completion("", tool_calls=[
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": args}}], finish="tool_calls"))
    with pytest.raises(ProviderError) as e:
        _provider(server).generate(LLMRequest("r", "test-local-9b", [Message.text("user", "x")], tools=[TOOL]))
    assert e.value.kind == "bad_output"


# ---- structured output ----

SCHEMA = {"type": "object", "properties": {"action": {"type": "string", "enum": ["ADD", "NOOP"]}},
          "required": ["action"], "additionalProperties": False}


def test_structured_uses_json_schema_and_no_tools(server):
    server.replies.append(_completion('{"action": "ADD"}'))
    req = LLMRequest("memory_extractor", "test-local-9b", [Message.text("user", "x")], tools=[TOOL],
                     response_schema=SCHEMA)
    res = _provider(server).structured(req, SCHEMA)
    assert res.valid and res.data == {"action": "ADD"}
    body = server.body()
    assert body["response_format"] == {"type": "json_schema",
                                       "json_schema": {"name": "response", "schema": SCHEMA, "strict": True}}
    assert "tools" not in body


@pytest.mark.parametrize("content", ["not json", '["a"]'])
def test_structured_invalid_json(server, content):
    server.replies.append(_completion(content))
    res = _provider(server).structured(LLMRequest("r", "test-local-9b", [Message.text("user", "x")]), SCHEMA)
    assert not res.valid and res.data is None


# ---- streaming ----

def test_stream_text_and_tool_deltas(server):
    server.replies.append({"sse": [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "Good "}}]},
        {"choices": [{"index": 0, "delta": {"content": "evening."}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "c9", "function": {"name": "read_file", "arguments": '{"pa'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'th": "b"}'}}]},
                      "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 5}, "timings": {"predicted_per_second": 21.5}},
    ]})
    events = list(_provider(server).stream(LLMRequest("r", "test-local-9b", [Message.text("user", "x")], tools=[TOOL])))
    assert [e.text for e in events if e.type == "text_delta"] == ["Good ", "evening."]
    done = events[-1].response
    assert done.text == "Good evening." and done.stop_reason == "tool_use"
    assert done.tool_calls == [ToolCall("c9", "read_file", {"path": "b"})]
    assert done.usage.input_tokens == 30 and done.adapter_state["ttft_ms"] >= 0
    assert server.body()["stream"] is True and server.body()["stream_options"] == {"include_usage": True}


# ---- errors, health, tokens, capabilities ----

@pytest.mark.parametrize("status,kind,retryable", [(400, "bad_request", False), (401, "auth", False),
                                                    (503, "server", True), (500, "server", True)])
def test_http_errors_map_to_provider_errors(server, status, kind, retryable):
    server.replies.append((status, {"error": {"message": "nope"}}))
    with pytest.raises(ProviderError) as e:
        _provider(server).generate(LLMRequest("r", "test-local-9b", [Message.text("user", "x")]))
    assert (e.value.kind, e.value.retryable) == (kind, retryable)


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_server_down_is_retryable_connection_error():
    provider = LocalProvider(MODELS, f"http://127.0.0.1:{_closed_port()}", timeout=2)
    with pytest.raises(ProviderError) as e:
        provider.generate(LLMRequest("r", "test-local-9b", [Message.text("user", "x")]))
    assert e.value.kind == "connection" and e.value.retryable
    assert not provider.health().ok
    count = provider.count_tokens(LLMRequest("r", "test-local-9b", [Message.text("user", "hello there")]))
    assert not count.exact and count.input_tokens >= 1


def test_health_and_exact_token_count(server):
    server.replies += [{"status": "ok"}, {"prompt": "<|im_start|>user\nhello<|im_end|>"}, {"tokens": [1, 2, 3, 4, 5]}]
    provider = _provider(server)
    assert provider.health().ok
    count = provider.count_tokens(LLMRequest("r", "test-local-9b", [Message.text("user", "hello")]))
    assert count.exact and count.input_tokens == 5
    assert [r[1] for r in server.requests] == ["/health", "/apply-template", "/tokenize"]


def test_capabilities_only_from_local_profiles(server):
    provider = _provider(server)
    caps = provider.capabilities("test-local-9b")
    assert caps.source == "measured" and caps.has("tools") and caps.has("structured_output")
    assert provider.capabilities("claude-opus-5-5").source == "unknown"  # another provider's model
    assert provider.capabilities("nope").source == "unknown"


# ---- eval-only override (jarvis.evals.local_run) ----

def test_eval_override_is_in_memory_only():
    from jarvis.config import CONFIG_DIR
    from jarvis.evals.local_run import local_eval_config

    config = load_config()
    config = dataclasses.replace(config, models={**config.models, "test-local-9b": MODELS["test-local-9b"]})
    before = (CONFIG_DIR / "routing.yaml").read_text(encoding="utf-8")
    ev = local_eval_config(config, "test-local-9b")
    assert ev.routing["approved_providers"] == ["local"]
    for spec in ev.routing["routes"].values():
        assert [(c["provider"], c["model"]) for c in spec["candidates"]] == [("local", "test-local-9b")]
    d = decide(ev, "memory_extractor", "local")
    assert (d.provider, d.model, d.effort) == ("local", "test-local-9b", "low")
    assert "local" not in config.routing["approved_providers"]          # the original is untouched
    assert (CONFIG_DIR / "routing.yaml").read_text(encoding="utf-8") == before
    with pytest.raises(SystemExit):
        local_eval_config(config, "claude-opus-5-5")
