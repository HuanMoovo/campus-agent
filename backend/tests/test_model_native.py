"""Native cloud contracts: wire formats, refusal and honest stream completion."""
import importlib
import json

import pytest

from app.model_protocol import ProtocolError


def adapter(name):
    # This assertion makes the initial red describe the missing implementation.
    assert importlib.util.find_spec(f"app.model_{name}"), f"Missing native {name} adapter"
    return importlib.import_module(f"app.model_{name}")


HISTORY = [{"role": "system", "content": "Be concise."},
           {"role": "user", "content": "Hello"},
           {"role": "assistant", "content": "Hi"},
           {"role": "user", "content": "Find courses"}]
TOOLS = [{"type": "function", "function": {"name": "find_courses", "description": "Find courses",
          "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"]}}}]


def sse(payload):
    return "data: " + json.dumps(payload)


def anthropic_payload(content=None, stop="end_turn"):
    return {"type": "message", "role": "assistant", "content": content if content is not None else
            [{"type": "text", "text": "Hello"}], "stop_reason": stop}


def gemini_payload(parts=None, stop="STOP"):
    return {"candidates": [{"content": {"role": "model", "parts": parts if parts is not None else
            [{"text": "Hello"}]}, "finishReason": stop}]}


def test_anthropic_moves_system_and_converts_tool_schema():
    body = adapter("anthropic").build_body("claude-custom", HISTORY, tools=TOOLS, max_tokens=321,
               request_options={"send_temperature": False, "token_parameter": "max_completion_tokens"})
    assert body == {"model": "claude-custom", "system": "Be concise.", "max_tokens": 321,
                    "messages": HISTORY[1:], "tools": [{"name": "find_courses", "description": "Find courses",
                    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                                     "required": ["query"]}}], "tool_choice": {"type": "auto"}}


def test_gemini_uses_native_contents_and_function_declarations():
    body = adapter("gemini").build_body("models/custom", HISTORY, tools=TOOLS, max_tokens=321)
    assert body == {"systemInstruction": {"parts": [{"text": "Be concise."}]},
                    "contents": [{"role": "user", "parts": [{"text": "Hello"}]},
                                 {"role": "model", "parts": [{"text": "Hi"}]},
                                 {"role": "user", "parts": [{"text": "Find courses"}]}],
                    "generationConfig": {"maxOutputTokens": 321, "temperature": 0.2},
                    "tools": [{"functionDeclarations": [{"name": "find_courses", "description": "Find courses",
                    "parametersJsonSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                                   "required": ["query"]}}]}],
                    "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}}}


@pytest.mark.parametrize("function", [
    {"name": "classrooms", "description": "Find available classrooms", "parameters": {
        "type": "object", "properties": {"building": {"type": "string", "maxLength": 120},
        "min_seats": {"type": "integer", "minimum": 0, "maximum": 1000}},
        "additionalProperties": False}},
    {"name": "probe", "description": "Check function planning", "parameters": {
        "type": "object", "properties": {}, "additionalProperties": False}},
])
def test_gemini_preserves_closed_json_schema_and_constraints_for_planning_and_probe(function):
    body = adapter("gemini").build_body("gemini-custom", HISTORY,
            tools=[{"type": "function", "function": function}])
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration == {"name": function["name"], "description": function["description"],
                           "parametersJsonSchema": function["parameters"]}
    assert "parameters" not in declaration
    assert declaration["parametersJsonSchema"]["additionalProperties"] is False


@pytest.mark.parametrize("name", ["anthropic", "gemini"])
def test_native_options_do_not_invent_thinking_settings(name):
    body = adapter(name).build_body("private-model", HISTORY, stream=True, reasoning="deep",
          tools=TOOLS, request_options={"supports_tools": False, "send_temperature": False})
    assert "tools" not in body
    assert "thinking" not in body
    assert "thinkingConfig" not in body.get("generationConfig", {})
    assert "temperature" not in body
    assert "temperature" not in body.get("generationConfig", {})
    if name == "anthropic":
        assert body["stream"] is True


@pytest.mark.parametrize("name", ["anthropic", "gemini"])
@pytest.mark.parametrize("messages", [None, {}, [], [None], [{"role": "tool", "content": "x"}],
    [{"role": "user", "content": ["x"]}], [{"role": "user", "content": None}],
    [{"role": "system", "content": "only system"}],
    [{"role": "assistant", "content": "x", "tool_calls": []}]])
def test_native_builders_reject_history_they_cannot_preserve(name, messages):
    with pytest.raises(ValueError):
        adapter(name).build_body("model", messages)


@pytest.mark.parametrize("name", ["anthropic", "gemini"])
@pytest.mark.parametrize("tools", ["bad", [None], [{"type": "image"}],
    [{"type": "function", "function": {"name": "", "parameters": {}}}],
    [{"type": "function", "function": {"name": "find", "parameters": "bad"}}]])
def test_native_builders_reject_malformed_tool_definitions(name, tools):
    with pytest.raises(ValueError):
        adapter(name).build_body("model", HISTORY, tools=tools)


@pytest.mark.parametrize("name,payload", [("anthropic", anthropic_payload()), ("gemini", gemini_payload())])
def test_native_completions_map_text(name, payload):
    assert adapter(name).parse_completion(payload) == {"role": "assistant", "content": "Hello"}


def test_native_completions_map_tool_calls_to_canonical_json():
    anth = adapter("anthropic").parse_completion(anthropic_payload([
        {"type": "thinking", "thinking": "private reasoning", "signature": "s"},
        {"type": "tool_use", "id": "call_1", "name": "find_courses", "input": {"query": "数学"}}], "tool_use"))
    gem = adapter("gemini").parse_completion(gemini_payload([
        {"text": "private reasoning", "thought": True},
        {"functionCall": {"id": "call_1", "name": "find_courses", "args": {"query": "数学"}}}]))
    for result in (anth, gem):
        assert result["role"] == "assistant" and result["content"] is None
        call = result["tool_calls"][0]
        assert call["id"] == "call_1" and call["type"] == "function"
        assert call["function"]["name"] == "find_courses"
        assert json.loads(call["function"]["arguments"]) == {"query": "数学"}


def test_gemini_assigns_distinct_ids_to_calls_without_native_ids():
    calls = adapter("gemini").parse_completion(gemini_payload([
        {"functionCall": {"name": "a", "args": {}}},
        {"functionCall": {"name": "b"}}]))["tool_calls"]
    assert all(isinstance(call["id"], str) and call["id"] for call in calls)
    assert calls[0]["id"] != calls[1]["id"]


@pytest.mark.parametrize("stop", [None, "max_tokens", "refusal", "pause_turn", "stop_sequence", "unknown"])
def test_anthropic_does_not_accept_incomplete_or_refused_answers(stop):
    with pytest.raises(ProtocolError):
        adapter("anthropic").parse_completion(anthropic_payload(stop=stop))


@pytest.mark.parametrize("stop", [None, "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", "MALFORMED_FUNCTION_CALL"])
def test_gemini_does_not_accept_incomplete_or_blocked_answers(stop):
    with pytest.raises(ProtocolError):
        adapter("gemini").parse_completion(gemini_payload(stop=stop))


@pytest.mark.parametrize("name,payload", [
    ("anthropic", {}), ("anthropic", anthropic_payload([])),
    ("anthropic", anthropic_payload([{"type": "text", "text": 1}])),
    ("anthropic", anthropic_payload([{"type": "image"}])),
    ("anthropic", anthropic_payload([{"type": "tool_use", "name": "a", "id": "x", "input": "{}"}], "tool_use")),
    ("anthropic", anthropic_payload([{"type": "tool_use", "name": "a", "input": {}}], "tool_use")),
    ("anthropic", anthropic_payload(stop="tool_use")),
    ("gemini", {}), ("gemini", gemini_payload([])),
    ("gemini", gemini_payload([{"text": 1}])),
    ("gemini", gemini_payload([{"inlineData": {}}])),
    ("gemini", gemini_payload([{"functionCall": {"name": "a", "args": "{}"}}])),
    ("gemini", gemini_payload([{"text": "x", "functionCall": {"name": "a"}}])),
    ("gemini", {"promptFeedback": {"blockReason": "SAFETY"}}),
])
def test_native_malformed_responses_are_rejected(name, payload):
    with pytest.raises(ProtocolError):
        adapter(name).parse_completion(payload)


@pytest.mark.parametrize("name", ["anthropic", "gemini"])
def test_native_upstream_errors_are_sanitized(name):
    with pytest.raises(ProtocolError) as caught:
        adapter(name).parse_completion({"error": {"message": "private credential detail"}})
    assert "private" not in str(caught.value)


def start_anthropic(parser):
    assert list(parser.feed(sse({"type": "message_start", "message":
        {"type": "message", "role": "assistant", "content": [], "stop_reason": None}}))) == []


def test_anthropic_streams_text_thinking_and_waits_for_message_stop():
    parser = adapter("anthropic").StreamParser()
    start_anthropic(parser)
    assert list(parser.feed(sse({"type": "content_block_start", "index": 0,
                "content_block": {"type": "thinking", "thinking": ""}}))) == []
    assert list(parser.feed(sse({"type": "content_block_delta", "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "Plan"}}))) == [("thinking", "Plan")]
    list(parser.feed(sse({"type": "content_block_delta", "index": 0,
                "delta": {"type": "signature_delta", "signature": "opaque"}})))
    list(parser.feed(sse({"type": "content_block_stop", "index": 0})))
    assert list(parser.feed(sse({"type": "content_block_start", "index": 1,
                "content_block": {"type": "text", "text": "Hello"}}))) == [("content", "Hello")]
    assert list(parser.feed(sse({"type": "content_block_delta", "index": 1,
                "delta": {"type": "text_delta", "text": "!"}}))) == [("content", "!")]
    list(parser.feed(sse({"type": "content_block_stop", "index": 1})))
    list(parser.feed(sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"}})))
    assert not parser.done
    with pytest.raises(ProtocolError, match="incomplete_response"):
        parser.finish()
    list(parser.feed(sse({"type": "message_stop"})))
    assert parser.done
    parser.finish()


@pytest.mark.parametrize("event", [{"type": "message_stop"},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "x"}},
    {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
    {"type": "error", "error": {"type": "overloaded_error", "message": "private"}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "name": "x", "input": {}}}])
def test_anthropic_invalid_stream_events_fail(event):
    parser = adapter("anthropic").StreamParser()
    start_anthropic(parser)
    with pytest.raises(ProtocolError):
        list(parser.feed(sse(event)))
    assert not parser.done


def test_gemini_stream_emits_thought_and_text_then_validates_stop():
    parser = adapter("gemini").StreamParser()
    assert list(parser.feed(sse(gemini_payload([{"text": "Plan", "thought": True}], None)))) == [("thinking", "Plan")]
    assert list(parser.feed(sse(gemini_payload([{"text": "Hello"}], None)))) == [("content", "Hello")]
    assert not parser.done
    list(parser.feed(sse(gemini_payload([{"text": "!"}]))))
    assert parser.done
    parser.finish()


@pytest.mark.parametrize("stop", ["MAX_TOKENS", "SAFETY"])
def test_gemini_stream_retains_last_text_before_abnormal_finish(stop):
    parser = adapter("gemini").StreamParser()
    chunks = parser.feed(sse(gemini_payload([{"text": "partial"}], stop)))
    assert next(chunks) == ("content", "partial")
    with pytest.raises(ProtocolError):
        next(chunks)
    assert not parser.done


@pytest.mark.parametrize("name", ["anthropic", "gemini"])
@pytest.mark.parametrize("line", ["data: [DONE]", "data: []", "data: {bad", "data: null",
    sse({"error": {"message": "private"}})])
def test_native_streams_reject_malformed_data_and_never_treat_done_sentinel_as_success(name, line):
    parser = adapter(name).StreamParser()
    with pytest.raises(ProtocolError):
        list(parser.feed(line))
    assert not parser.done
    with pytest.raises(ProtocolError):
        parser.finish()


@pytest.mark.parametrize("name", ["anthropic", "gemini"])
def test_native_empty_stream_and_sse_metadata_are_not_success(name):
    parser = adapter(name).StreamParser()
    for line in ("", "event: message_start", ": ping"):
        assert list(parser.feed(line)) == []
    with pytest.raises(ProtocolError, match="incomplete_response"):
        parser.finish()


@pytest.mark.parametrize("payload", [{"promptFeedback": {"blockReason": "SAFETY"}},
    gemini_payload([{"functionCall": {"name": "f", "args": {}}}]),
    gemini_payload([{"text": None}]), {"candidates": []},
    {"candidates": [{"finishReason": "STOP"}]}])
def test_gemini_stream_rejects_blocked_empty_malformed_or_unexpected_tool_output(payload):
    with pytest.raises(ProtocolError):
        list(adapter("gemini").StreamParser().feed(sse(payload)))
