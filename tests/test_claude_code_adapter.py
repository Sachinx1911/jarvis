"""Claude Code CLI adapter, tested offline with a stand-in runner (no CLI process)."""

import json

import pytest

from jarvis.config import load_config
from jarvis.providers.base import LLMRequest, Message, ProviderError, ToolCall, ToolResult, ToolSpec
from jarvis.providers.claude_code import ClaudeCodeProvider, render_transcript


class StubRunner:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, argv, stdin):
        self.calls.append((argv, stdin))
        out = self.outputs.pop(0)
        return out.get("_rc", 0), json.dumps({k: v for k, v in out.items() if k != "_rc"}), ""


def _ok(**extra):
    return {"type": "result", "is_error": False, "result": "note\n\nGood evening, sir.", "stop_reason": "end_turn",
            "structured_output": {"text": "Good evening, sir."},
            "usage": {"input_tokens": 50, "output_tokens": 6, "cache_read_input_tokens": 10},
            "total_cost_usd": 0.002, **extra}


def _provider(*outputs):
    runner = StubRunner(*outputs)
    return ClaudeCodeProvider(load_config().models, executable="claude", runner=runner), runner


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_plain_reply_is_isolated_and_unbilled():
    provider, runner = _provider(_ok())
    resp = provider.generate(LLMRequest("main_chat", "claude-opus-5-5", [Message.text("user", "Hello")], system="sys"))
    assert resp.text == "Good evening, sir."
    assert resp.stop_reason == "end"
    assert resp.cost_usd is None and resp.adapter_state == {"notional_usd": 0.002}
    assert resp.usage.cached_tokens == 10
    argv, stdin = runner.calls[0]
    assert stdin == "Hello"
    assert _flag(argv, "--tools") == "" and _flag(argv, "--setting-sources") == ""
    for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in argv
    assert _flag(argv, "--model") == "claude-opus-5-5" and _flag(argv, "--effort") == "medium"
    assert json.loads(_flag(argv, "--json-schema"))["required"] == ["text"]


def test_plain_reply_without_json_raises():
    provider, _ = _provider(_ok(structured_output=None))
    with pytest.raises(ProviderError) as e:
        provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "x")]))
    assert e.value.kind == "bad_output"


def test_history_is_rendered_as_transcript():
    text = render_transcript([
        Message.text("user", "नमस्कार"),
        Message.text("assistant", "Good evening, sir."),
        Message("assistant", [ToolCall("c1", "memory_search", {"q": "college"})]),
        Message("tool", [ToolResult("c1", "no results")]),
        Message.text("user", "ok"),
    ])
    assert text.startswith("<conversation>")
    assert "[user]: नमस्कार" in text
    assert '[assistant tool call c1]: memory_search {"q": "college"}' in text
    assert "[tool result c1]: no results" in text
    assert text.rstrip().endswith("Respond to the last message in the conversation.")


def test_tool_call_via_json_action_mode():
    action = {"kind": "tool_call", "tool": "memory_search", "arguments": {"q": "college"}}
    provider, runner = _provider(_ok(structured_output=action))
    tool = ToolSpec("memory_search", "Search memory.", {"type": "object", "properties": {"q": {"type": "string"}}})
    resp = provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "find it")], tools=[tool]))
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls[0].name == "memory_search" and resp.tool_calls[0].arguments == {"q": "college"}
    schema = json.loads(_flag(runner.calls[0][0], "--json-schema"))
    assert schema["properties"]["tool"]["enum"] == ["memory_search"]


def test_reply_via_json_action_mode():
    provider, _ = _provider(_ok(structured_output={"kind": "reply", "text": "Done, sir."}))
    tool = ToolSpec("t", "d", {"type": "object"})
    resp = provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "x")], tools=[tool]))
    assert (resp.text, resp.tool_calls, resp.stop_reason) == ("Done, sir.", [], "end")


def test_invalid_action_raises():
    provider, _ = _provider(_ok(structured_output={"kind": "dance"}))
    with pytest.raises(ProviderError) as e:
        provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "x")],
                                     tools=[ToolSpec("t", "d", {"type": "object"})]))
    assert e.value.kind == "bad_output"


def test_structured_output():
    provider, _ = _provider(_ok(structured_output={"answer": "4"}))
    res = provider.structured(LLMRequest("r", "claude-haiku-5-5", [Message.text("user", "2+2")]), {"type": "object"})
    assert res.valid and res.data == {"answer": "4"}


@pytest.mark.parametrize("status,kind,retryable", [(429, "rate_limit", True), (401, "auth", False),
                                                   (400, "bad_request", False), (529, "server", True)])
def test_errors_map_to_neutral(status, kind, retryable):
    provider, _ = _provider({"_rc": 1, "type": "result", "is_error": True, "api_error_status": status, "result": "boom"})
    with pytest.raises(ProviderError) as e:
        provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "x")]))
    assert (e.value.kind, e.value.retryable) == (kind, retryable)


def test_missing_cli():
    provider = ClaudeCodeProvider({}, executable=None, runner=StubRunner())
    provider._exe = None
    assert not provider.health().ok
    with pytest.raises(ProviderError):
        provider.generate(LLMRequest("r", "m", [Message.text("user", "x")]))


@pytest.mark.parametrize("status,ok", [
    ({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}, True),
    ({"loggedIn": True, "authMethod": "api_key"}, False),
    ({"loggedIn": False}, False),
])
def test_health_requires_subscription_login(status, ok):
    provider, _ = _provider(status)
    assert provider.health().ok is ok


def test_capabilities_use_via_profile():
    caps = ClaudeCodeProvider(load_config().models, executable="claude", runner=StubRunner()).capabilities("claude-opus-5-5")
    assert caps.tool_calling == "single" and not caps.prompt_caching and caps.structured_output == "json_schema"
