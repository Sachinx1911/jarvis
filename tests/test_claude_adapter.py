"""Claude adapter translation, tested offline with a stand-in client (no network)."""

from types import SimpleNamespace

import pytest

from jarvis.config import load_config
from jarvis.providers.base import LLMRequest, Message, ProviderError, TextPart, ToolCall, ToolResult, ToolSpec
from jarvis.providers.claude import ClaudeProvider


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in vars(self).items() if v is not None}


class StubClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.messages = self

    def create(self, **params):
        self.calls.append(params)
        return self.response


def _response(content, stop="end_turn"):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage)


def _provider(response):
    client = StubClient(response)
    return ClaudeProvider(None, load_config().models, client=client), client


def test_text_reply_and_cost():
    provider, client = _provider(_response([
        Block(type="thinking", thinking="", signature="sig"),
        Block(type="text", text="Good evening, sir."),
    ]))
    req = LLMRequest("main_chat", "claude-opus-5-5", [Message.text("user", "hello")], system="sys")
    resp = provider.generate(req)
    assert resp.text == "Good evening, sir."
    assert resp.stop_reason == "end"
    assert resp.cost_usd == pytest.approx((1000 * 4 + 200 * 20) / 1_000_000)
    params = client.calls[0]
    assert params["system"] == "sys"
    assert params["output_config"] == {"effort": "medium"}
    assert "thinking" not in params and "temperature" not in params
    assert params["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]


def test_own_assistant_turn_replayed_unchanged():
    raw = [Block(type="thinking", thinking="", signature="sig"), Block(type="text", text="Hi")]
    provider, client = _provider(_response(raw))
    first = provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "hello")]))
    history = [Message.text("user", "hello"), first.to_message(), Message.text("user", "again")]
    provider.generate(LLMRequest("r", "claude-opus-5-5", history))
    replayed = client.calls[1]["messages"][1]
    assert replayed["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}


def test_other_model_state_not_replayed():
    provider, client = _provider(_response([Block(type="text", text="ok")]))
    old = Message("assistant", [TextPart("Hi")],
                  adapter_state={"provider": "anthropic", "model": "claude-haiku-5-5", "content": [{"type": "x"}]})
    provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "a"), old, Message.text("user", "b")]))
    assert client.calls[0]["messages"][1]["content"] == [{"type": "text", "text": "Hi"}]


def test_tool_calls_round_trip():
    provider, client = _provider(_response(
        [Block(type="tool_use", id="tu1", name="read_file", input={"path": "a.txt"})], stop="tool_use"))
    tool = ToolSpec("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
    resp = provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "read a.txt")], tools=[tool]))
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls == [ToolCall("tu1", "read_file", {"path": "a.txt"})]
    assert client.calls[0]["tools"][0]["input_schema"]["required"] == ["path"]

    result = Message("tool", [ToolResult("tu1", "file text")])
    provider.generate(LLMRequest("r", "claude-sonnet-5-5", [Message.text("user", "x"), resp.to_message(), result]))
    msgs = client.calls[1]["messages"]
    assert msgs[1]["content"] == [{"type": "tool_use", "id": "tu1", "name": "read_file", "input": {"path": "a.txt"}}]
    assert msgs[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu1", "content": "file text", "is_error": False}]}


def test_refusal_maps_to_neutral():
    provider, _ = _provider(_response([], stop="refusal"))
    assert provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "x")])).stop_reason == "refusal"


def test_no_key_raises_auth_error():
    provider = ClaudeProvider(None, {})
    assert not provider.health().ok
    with pytest.raises(ProviderError) as e:
        provider.generate(LLMRequest("r", "claude-opus-5-5", [Message.text("user", "x")]))
    assert e.value.kind == "auth"
