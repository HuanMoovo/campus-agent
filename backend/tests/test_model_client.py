"""HTTP is simulated; all provider traffic stays offline."""
import asyncio
from contextlib import contextmanager
import json

import httpx
import pytest

from app import model_client
from app.model_protocol import ModelStreamError


SELECTED = ("openai_compatible", "private-key", "https://models.invalid/gateway/v1", "vendor/model")
CURRENT = {"api_key": SELECTED[1], "base_url": SELECTED[2], "model": SELECTED[3]}
MESSAGES = [{"role": "user", "content": "hello"}]


def install_transport(monkeypatch, handler, *, asynchronous=False):
    name = "AsyncClient" if asynchronous else "Client"
    real = getattr(httpx, name)
    def factory(**kwargs):
        assert kwargs["trust_env"] is False
        return real(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(model_client.httpx, name, factory)


def collect(**kwargs):
    async def run():
        return [item async for item in model_client.stream(SELECTED, MESSAGES, **kwargs)]
    return asyncio.run(run())


def frame(content=None, finish=None):
    return "data: " + json.dumps({"choices": [{"delta": {} if content is None else {"content": content},
                                               "finish_reason": finish}]}) + "\n\n"


def test_complete_uses_shared_compatibility_body(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    install_transport(monkeypatch, handler)
    assert model_client.complete(SELECTED, MESSAGES,
        request_options={"token_parameter": "max_completion_tokens", "send_temperature": False}) == {"content": "answer"}
    assert str(requests[0].url) == "https://models.invalid/gateway/v1/chat/completions"
    assert json.loads(requests[0].content) == {"model": "vendor/model", "messages": MESSAGES, "max_completion_tokens": 900}


def test_disabled_tools_skip_network_to_allow_deterministic_planning(monkeypatch):
    monkeypatch.setattr(model_client.httpx, "Client", lambda **kw: pytest.fail("network must not be called"))
    assert model_client.complete(SELECTED, MESSAGES, tools=[{}], request_options={"supports_tools": False}) is None


@pytest.mark.parametrize("payload", [{}, {"error": {"message": "private"}}, {"choices": [{"message": {"content": ""}}]}])
def test_cloud_invalid_completion_allows_fallback(monkeypatch, payload):
    install_transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    assert model_client.complete(SELECTED, MESSAGES) is None


@pytest.mark.parametrize("suffix", ["data: [DONE]\n\n", frame(finish="stop"),
    'data: {"choices":[],"usage":{"total_tokens":5}}\n\n' + frame(finish="stop")])
def test_normal_stream_completion_and_usage_are_accepted(monkeypatch, suffix):
    install_transport(monkeypatch, lambda req: httpx.Response(200, text=frame("answer") + suffix), asynchronous=True)
    assert collect() == [("content", "answer")]


@pytest.mark.parametrize("ending", [frame(finish="length"), frame(finish="content_filter"), frame(finish="unexpected"),
    "data: broken-json\n\ndata: [DONE]\n\n", 'data: {"error":{"message":"private-key"}}\n\ndata: [DONE]\n\n', ""])
def test_partial_stream_errors_are_safe_and_never_masked_by_done(monkeypatch, ending):
    install_transport(monkeypatch, lambda req: httpx.Response(200, text=frame("partial") + ending), asynchronous=True)
    chunks = []
    async def run():
        with pytest.raises(ModelStreamError) as error:
            async for item in model_client.stream(SELECTED, MESSAGES):
                chunks.append(item)
        assert "private-key" not in str(error.value)
    asyncio.run(run())
    assert chunks == [("content", "partial")]


def test_content_in_length_frame_is_delivered_before_failure(monkeypatch):
    install_transport(monkeypatch, lambda req: httpx.Response(200, text=frame("partial", "length")), asynchronous=True)
    async def run():
        iterator = model_client.stream(SELECTED, MESSAGES)
        assert await anext(iterator) == ("content", "partial")
        with pytest.raises(ModelStreamError):
            await anext(iterator)
    asyncio.run(run())


@pytest.mark.parametrize("text", ["", "data: broken\n\ndata: [DONE]\n\n", 'data: {"error":{"message":"private"}}\n\n'])
def test_cloud_failure_before_output_preserves_fallback(monkeypatch, text):
    install_transport(monkeypatch, lambda req: httpx.Response(200, text=text), asynchronous=True)
    assert collect() == []


def test_disabled_streaming_posts_nonstream_and_emits_visible_answer(monkeypatch):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer", "reasoning_content": "hidden"}}]})
    install_transport(monkeypatch, handler, asynchronous=True)
    assert collect(reasoning="deep", request_options={"supports_streaming": False}) == [("content", "answer")]
    assert bodies[0].get("stream", False) is False


def test_ollama_thinking_retry_and_native_done_metrics(monkeypatch):
    bodies = []
    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        if body["think"]:
            return httpx.Response(400, json={"error": "unsupported thinking"})
        return httpx.Response(200, text='{"message":{"thinking":"think","content":"answer"},"done":false}\n{"done":true,"eval_count":3}\n')
    install_transport(monkeypatch, handler, asynchronous=True)
    async def run():
        return [item async for item in model_client.stream(("ollama", "", "https://ignored.invalid/v1", "local"), MESSAGES, reasoning="deep")]
    assert asyncio.run(run()) == [("thinking", "think"), ("content", "answer")]
    assert [body["think"] for body in bodies] == [True, False]


def test_ollama_invalid_completion_raises_local_error(monkeypatch):
    from app.model_runtime import LocalModelError
    install_transport(monkeypatch, lambda req: httpx.Response(200, json={}))
    with pytest.raises(LocalModelError):
        model_client.complete(("ollama", "", "", "local"), MESSAGES)


def probe_response(monkeypatch, payload, status=200):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(model_client.httpx, "post", post)
    return calls


def test_chat_probe_uses_saved_compatibility_options_and_only_verifies_chat(monkeypatch):
    calls = probe_response(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    result = model_client.probe_provider("openai_compatible", {**CURRENT, "request_options": {
        "token_parameter": "max_completion_tokens", "send_temperature": False}})
    assert result["ok"] and result["capability"] == "chat"
    assert result["capabilities"] == {"chat": "verified", "tools": "not_tested", "streaming": "not_tested"}
    assert result["latency_ms"] >= 0 and result["protocol"] == "chat_completions"
    assert "max_completion_tokens" in calls[0][1]["json"] and "temperature" not in calls[0][1]["json"]
    assert "private-key" not in json.dumps(result)


@pytest.mark.parametrize("status,payload,code", [
    (401, {}, "authentication"), (403, {}, "authentication"), (404, {}, "not_found"),
    (429, {"error": {"code": "insufficient_quota", "message": "private-key"}}, "quota_exceeded"),
    (429, {}, "rate_limited"), (400, {"error": {"code": "unsupported_parameter"}}, "unsupported_parameter"),
    (500, {}, "upstream_error"), (302, {}, "upstream_error"), (200, {}, "invalid_response"),
    (200, {"choices": [{"message": {"content": " "}}]}, "invalid_response")])
def test_probe_classifies_errors_without_exposing_provider_body(monkeypatch, status, payload, code):
    probe_response(monkeypatch, payload, status)
    result = model_client.probe_provider("openai_compatible", CURRENT)
    assert result["ok"] is False and result["error_code"] == code
    assert result["capabilities"]["chat"] == "not_verified"
    assert "private-key" not in json.dumps(result)


@pytest.mark.parametrize("exception,code", [(httpx.ReadTimeout("private-key"), "timeout"),
                                           (httpx.ConnectError("private-key"), "connection")])
def test_probe_transport_errors_are_classified(monkeypatch, exception, code):
    def post(*args, **kwargs):
        raise exception
    monkeypatch.setattr(model_client.httpx, "post", post)
    result = model_client.probe_provider("openai_compatible", CURRENT)
    assert result["error_code"] == code and "private-key" not in json.dumps(result)


@pytest.mark.parametrize("field,code", [("api_key", "missing_key"), ("model", "missing_model")])
def test_probe_missing_configuration_never_calls_network(monkeypatch, field, code):
    monkeypatch.setattr(model_client.httpx, "post", lambda *a, **kw: pytest.fail("unexpected network"))
    assert model_client.probe_provider("openai_compatible", {**CURRENT, field: ""})["error_code"] == code


@pytest.mark.parametrize("capability,option", [("tools", "supports_tools"), ("streaming", "supports_streaming")])
def test_disabled_probe_never_calls_network(monkeypatch, capability, option):
    monkeypatch.setattr(model_client.httpx, "post", lambda *a, **kw: pytest.fail("unexpected network"))
    monkeypatch.setattr(model_client.httpx, "stream", lambda *a, **kw: pytest.fail("unexpected network"))
    result = model_client.probe_provider("openai_compatible", {**CURRENT, "request_options": {option: False}}, capability)
    assert result["error_code"] == "capability_disabled"


@pytest.mark.parametrize("message,code", [
    ({"content": "ok"}, "tool_not_observed"),
    ({"content": None, "tool_calls": [{"type": "function", "function": {"name": "mens_connection_probe", "arguments": "{}"}}]}, ""),
    ({"content": None, "tool_calls": [{"type": "function", "function": {"name": "other", "arguments": "{}"}}]}, "invalid_response"),
    ({"content": None, "tool_calls": [{"type": "function", "function": {"name": "mens_connection_probe", "arguments": "[]"}}]}, "invalid_response"),
    ({"content": None, "tool_calls": [{"type": "function", "function": {"name": "mens_connection_probe", "arguments": "{bad"}}]}, "invalid_response")])
def test_tools_probe_checks_name_and_empty_json_arguments_without_execution(monkeypatch, message, code):
    calls = probe_response(monkeypatch, {"choices": [{"message": message}]})
    result = model_client.probe_provider("openai_compatible", CURRENT, "tools")
    assert result["error_code"] == code and result["ok"] is (code == "")
    body = calls[0][1]["json"]
    assert body["tool_choice"] == "auto"
    assert body["tools"][0]["function"]["name"] == "mens_connection_probe"


@pytest.mark.parametrize("text,code", [(frame("answer") + "data: [DONE]\n\n", ""),
    (frame("answer", "length") + "data: [DONE]\n\n", "incomplete_response"),
    (frame("answer") + "data: broken\n\ndata: [DONE]\n\n", "invalid_response"),
    (frame("answer"), "incomplete_response"), ("data: [DONE]\n\n", "invalid_response")])
def test_streaming_probe_requires_visible_output_and_normal_completion(monkeypatch, text, code):
    @contextmanager
    def stream(method, url, **kwargs):
        assert method == "POST" and kwargs["json"]["stream"] is True
        yield httpx.Response(200, text=text)
    monkeypatch.setattr(model_client.httpx, "stream", stream)
    result = model_client.probe_provider("openai_compatible", CURRENT, "streaming")
    assert result["error_code"] == code and result["ok"] is (code == "")
