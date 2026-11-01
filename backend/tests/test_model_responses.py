"""Responses wire contracts, exercised without configuration or network access."""
import importlib
import json

import pytest

from app.model_protocol import ProtocolError


def adapter():
    return importlib.import_module("app.model_responses")


def message(text="answer", **extra):
    return {"type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}], **extra}


def response(*output, **extra):
    return {"id": "resp_test", "object": "response", "status": "completed",
            "error": None, "incomplete_details": None, "output": list(output), **extra}


def event(kind, **fields):
    return "data: " + json.dumps({"type": kind, **fields})


def test_native_request_preserves_history_model_and_uses_private_token_limit():
    history = [{"role": "system", "content": "rules"}, {"role": "user", "content": "hello"},
               {"role": "assistant", "content": "previous"}]
    assert adapter().build_body("deployment-a", history, stream=True, max_tokens=123,
        request_options={"send_temperature": False, "token_parameter": "max_completion_tokens"}) == {
        "model": "deployment-a", "input": history, "stream": True,
        "store": False, "max_output_tokens": 123}


def test_request_flattens_functions_without_changing_optional_schema_fields():
    schema = {"type": "object", "properties": {"term": {"type": "string"}}}
    tools = [{"type": "function", "function": {"name": "search", "description": "Search", "parameters": schema}}]
    body = adapter().build_body("m", [{"role": "user", "content": "hi"}], tools=tools, reasoning="deep")
    assert body["tools"] == [{"type": "function", "name": "search", "description": "Search",
                              "parameters": schema, "strict": False}]
    assert body["tool_choice"] == "auto"
    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert body["temperature"] == 0.2
    assert "strict" not in tools[0]["function"]
    assert "tools" not in adapter().build_body("m", [], tools=tools, request_options={"supports_tools": False})


@pytest.mark.parametrize("history", [[{"role": "tool", "content": "ok", "tool_call_id": "x"}],
    [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
    [{"role": "assistant", "content": None, "tool_calls": []}],
    [{"role": "assistant", "content": "hi", "tool_calls": [{"id": "x"}]}], [None], "hi"])
def test_unsupported_history_is_rejected_instead_of_silently_discarded(history):
    with pytest.raises(ValueError):
        adapter().build_body("m", history)


def test_completion_combines_text_items_and_normalizes_function_call_ids():
    payload = response({"type": "reasoning", "summary": []}, message("one"),
        {"type": "function_call", "id": "fc_item", "call_id": "call_1", "status": "completed",
         "name": "search", "arguments": '{"term":"x"}'}, message("two"))
    assert adapter().parse_completion(payload) == {"role": "assistant", "content": "onetwo",
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "search", "arguments": '{"term":"x"}'}}]}


def test_tool_only_completion_has_none_content():
    assert adapter().parse_completion(response({"type": "function_call", "call_id": "call_1",
        "name": "search", "arguments": "{}"}))["content"] is None


@pytest.mark.parametrize("payload,code", [
    ({}, "invalid_response"), (response(), "invalid_response"),
    (response(message("partial"), status="incomplete"), "incomplete_response"),
    (response(message(), status="failed", error={"message": "secret quota_exceeded"}), "quota_exceeded"),
    (response(message(), status="in_progress"), "incomplete_response"),
    (response(message(), incomplete_details={"reason": "max_output_tokens"}), "incomplete_response"),
    (response(message(status="incomplete")), "incomplete_response"),
    (response({"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "private"}]}), "invalid_response"),
    (response(message(42)), "invalid_response"),
    (response({"type": "function_call", "call_id": "x", "name": "search", "arguments": "{"}), "invalid_response"),
    (response({"type": "function_call", "call_id": "x", "name": "search", "arguments": "[]"}), "invalid_response"),
    (response({"type": "function_call", "name": "search", "arguments": "{}"}), "invalid_response"),
    (response({"type": "web_search_call", "status": "completed"}), "invalid_response"),
])
def test_non_success_or_malformed_completion_is_rejected_safely(payload, code):
    with pytest.raises(ProtocolError) as caught:
        adapter().parse_completion(payload)
    assert caught.value.error_code == code
    assert "secret" not in str(caught.value)


def test_stream_requires_completed_response_and_keeps_thinking_separate():
    parser = adapter().StreamParser()
    assert list(parser.feed(": ping")) == []
    assert list(parser.feed("event: response.output_text.delta")) == []
    assert list(parser.feed(event("response.reasoning_summary_text.delta", delta="summary"))) == [("thinking", "summary")]
    assert list(parser.feed(event("response.output_text.delta", delta="answer"))) == [("content", "answer")]
    assert not parser.done
    assert list(parser.feed(event("response.completed", response=response(message())))) == []
    assert parser.done
    parser.finish()


@pytest.mark.parametrize("terminal", [None, "data: [DONE]", event("response.output_text.done", text="answer")])
def test_eof_done_marker_or_text_done_cannot_prove_success(terminal):
    parser = adapter().StreamParser()
    list(parser.feed(event("response.output_text.delta", delta="partial")))
    if terminal:
        list(parser.feed(terminal))
    assert not parser.done
    with pytest.raises(ProtocolError, match="incomplete_response"):
        parser.finish()


@pytest.mark.parametrize("terminal,code", [
    (event("response.incomplete", response=response(message("partial"), status="incomplete")), "incomplete_response"),
    (event("response.failed", response=response(status="failed", error={"code": "quota_exceeded", "message": "secret"})), "quota_exceeded"),
    (event("error", code="server_error", message="secret"), "upstream_error"),
    (event("response.completed", response=response(message(), status="incomplete")), "incomplete_response"),
    (event("response.refusal.delta", delta="private"), "invalid_response"),
    (event("response.completed", response=response({"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "private"}]})), "invalid_response"),
])
def test_partial_content_survives_non_success_terminal_without_done(terminal, code):
    parser = adapter().StreamParser()
    assert list(parser.feed(event("response.output_text.delta", delta="partial"))) == [("content", "partial")]
    with pytest.raises(ProtocolError) as caught:
        list(parser.feed(terminal))
    assert caught.value.error_code == code
    assert not parser.done
    with pytest.raises(ProtocolError):
        parser.finish()


def test_tool_events_cannot_make_text_stream_successful():
    parser = adapter().StreamParser()
    assert list(parser.feed(event("response.function_call_arguments.delta", delta="{}"))) == []
    with pytest.raises(ProtocolError):
        list(parser.feed(event("response.completed", response=response({"type": "function_call", "call_id": "x",
            "name": "search", "arguments": "{}"}))))
    assert not parser.done


@pytest.mark.parametrize("line", ["data: not-json", "data: []", event("response.output_text.delta", delta=1), "data: {}"])
def test_malformed_stream_events_are_rejected(line):
    parser = adapter().StreamParser()
    with pytest.raises(ProtocolError):
        list(parser.feed(line))


@pytest.mark.parametrize("arguments", ['{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}'])
def test_function_arguments_must_be_portable_json(arguments):
    with pytest.raises(ProtocolError):
        adapter().parse_completion(response({"type": "function_call", "call_id": "x",
            "name": "search", "arguments": arguments}))


def test_stream_failure_cannot_be_overridden_by_a_later_success_marker():
    parser = adapter().StreamParser()
    with pytest.raises(ProtocolError):
        list(parser.feed(event("response.incomplete", response=response(status="incomplete"))))
    with pytest.raises(ProtocolError, match="incomplete_response"):
        list(parser.feed(event("response.completed", response=response(message()))))
    assert not parser.done


def test_completed_response_can_supply_text_when_no_deltas_arrived():
    parser = adapter().StreamParser()
    assert list(parser.feed(event("response.completed", response=response(message("final"))))) == [("content", "final")]
    parser.finish()


def test_completed_response_cannot_hide_lost_text_deltas():
    parser = adapter().StreamParser()
    assert list(parser.feed(event("response.output_text.delta", delta="ans"))) == [("content", "ans")]
    with pytest.raises(ProtocolError, match="incomplete_response"):
        list(parser.feed(event("response.completed", response=response(message("answer")))))
    assert not parser.done
