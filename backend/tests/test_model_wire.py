"""Native model HTTP and public provider selection boundaries."""
import asyncio
from contextlib import contextmanager
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app import agent, model_client, model_runtime as runtime
from app.model_protocol import normalize_request_options
from app.schemas import ChatRequest, ModelProviderUpdate


@pytest.fixture
def config(monkeypatch, tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, qwen_api_key="", deepseek_api_key="",
        qwen_base_url="https://qwen.example/v1", qwen_model="qwen", deepseek_base_url="https://deepseek.example/v1", deepseek_model="deepseek")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_encrypt", lambda text: "test:" + text[::-1])
    monkeypatch.setattr(runtime, "_decrypt", lambda text: text[5:][::-1])


@pytest.mark.parametrize("provider", ["openai_responses", "anthropic", "gemini", "zhipu", "moonshot",
    "doubao", "siliconflow", "hunyuan", "qianfan", "minimax", "stepfun"])
def test_new_providers_round_trip_config_and_are_selectable(config, provider):
    ChatRequest(message="hello", model=provider)
    saved = runtime.update_provider(provider, {"api_key": "synthetic", "model": "my-model"})
    row = saved["providers"][provider]
    assert row["configured"] and row["api_key_set"]
    assert "synthetic" not in json.dumps(saved)
    assert agent.choose_model(provider)[0] == provider
    assert any(entry["id"] == provider for entry in saved["catalog"])


def test_custom_gateway_protocol_round_trip_and_local_protocol_is_fixed(config):
    result = runtime.update_provider("openai_compatible", {"protocol": "anthropic", "base_url": "https://gateway.example/custom/v1"})
    assert result["providers"]["openai_compatible"]["protocol"] == "anthropic"
    with pytest.raises(ValueError):
        runtime.update_provider("ollama", {"model": "test", "protocol": "responses"})


@pytest.mark.parametrize("value", [None, "auto", "ollama", True, [], {}])
def test_invalid_cloud_protocol_is_rejected(config, value):
    with pytest.raises(ValueError):
        runtime.update_provider("qwen", {"protocol": value})
    with pytest.raises(ValidationError):
        ModelProviderUpdate(protocol=value)


@pytest.mark.parametrize("value", [True, "1024", 63, 65537, None, 100.5])
def test_output_limit_is_strict_and_bounded(value):
    with pytest.raises(ValueError):
        normalize_request_options({"max_output_tokens": value})
    with pytest.raises(ValidationError):
        ModelProviderUpdate(request_options={"max_output_tokens": value})


def test_output_limit_can_be_saved_without_changing_other_options(config):
    runtime.update_provider("qwen", {"request_options": {"send_temperature": False}})
    result = runtime.update_provider("qwen", {"request_options": {"max_output_tokens": 4096}})
    assert result["providers"]["qwen"]["request_options"]["max_output_tokens"] == 4096
    assert result["providers"]["qwen"]["request_options"]["send_temperature"] is False


def fixture_payload(protocol):
    if protocol == "responses":
        return {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "answer"}]}]}
    if protocol == "anthropic":
        return {"role": "assistant", "content": [{"type": "text", "text": "answer"}], "stop_reason": "end_turn"}
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": "answer"}]}, "finishReason": "STOP"}]}


def native_stream_text(protocol, *, failed=False):
    def frame(value):
        return "data: " + json.dumps(value) + "\n\n"
    if protocol == "responses":
        return frame({"type": "response.output_text.delta", "delta": "answer"}) + frame({
            "type": "response.incomplete" if failed else "response.completed",
            "response": {"status": "incomplete"} if failed else fixture_payload(protocol)})
    if protocol == "anthropic":
        return (frame({"type": "message_start", "message": {"type": "message", "role": "assistant", "content": []}})
                + frame({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                + frame({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "answer"}})
                + frame({"type": "content_block_stop", "index": 0})
                + frame({"type": "message_delta", "delta": {"stop_reason": "max_tokens" if failed else "end_turn"}})
                + frame({"type": "message_stop"}))
    payload = fixture_payload(protocol)
    payload["candidates"][0]["finishReason"] = "MAX_TOKENS" if failed else "STOP"
    return frame(payload)


@pytest.mark.parametrize("protocol,provider", [("responses", "openai_responses"), ("anthropic", "anthropic"), ("gemini", "gemini")])
@pytest.mark.parametrize("failed", [False, True])
def test_native_stream_production_and_diagnostics_observe_same_end_status(monkeypatch, protocol, provider, failed):
    real = httpx.AsyncClient
    text = native_stream_text(protocol, failed=failed)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, text=text)), **kw))
    selected = (provider, "synthetic-key", "https://native.invalid/v1", "my-model")
    chunks = []
    async def collect():
        async for item in model_client.stream(selected, [{"role": "user", "content": "hello"}], protocol=protocol):
            chunks.append(item)
    if failed:
        with pytest.raises(model_client.ModelStreamError):
            asyncio.run(collect())
    else:
        asyncio.run(collect())
    assert chunks == [("content", "answer")]
    @contextmanager
    def response_stream(*args, **kwargs):
        yield httpx.Response(200, text=text)
    monkeypatch.setattr(httpx, "stream", response_stream)
    result = model_client.probe_provider(provider, {"api_key": selected[1], "base_url": selected[2],
        "model": selected[3], "protocol": protocol}, "streaming")
    assert result["ok"] is (not failed)
    assert result["capabilities"]["streaming"] == ("not_verified" if failed else "verified")


@pytest.mark.parametrize("protocol,provider", [("responses", "openai_responses"), ("anthropic", "anthropic"), ("gemini", "gemini")])
def test_native_tool_probe_is_converted_without_tool_execution(monkeypatch, protocol, provider):
    function = "mens_connection_probe"
    if protocol == "responses":
        payload = {"status": "completed", "output": [{"type": "function_call", "call_id": "probe", "name": function, "arguments": "{}"}]}
    elif protocol == "anthropic":
        payload = {"role": "assistant", "stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "probe", "name": function, "input": {}}]}
    else:
        payload = {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [{"functionCall": {"name": function, "args": {}}}]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(200, json=payload))
    result = model_client.probe_provider(provider, {"api_key": "synthetic", "base_url": "https://native.invalid/v1",
        "model": "test", "protocol": protocol}, "tools")
    assert result["ok"] and result["capabilities"]["tools"] == "verified"


def test_spark_error_code_cannot_be_accepted_as_successful_content(monkeypatch):
    real = httpx.Client
    payload = {"code": 10013, "message": "private-provider-message", "choices": [{"message": {"content": "not an answer"}}]}
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=payload)), **kw))
    assert model_client.complete(("spark", "synthetic", "https://native.invalid/v1", "test"),
        [{"role": "user", "content": "hello"}]) is None
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(200, json=payload))
    result = model_client.probe_provider("spark", {"api_key": "synthetic", "base_url": "https://native.invalid/v1", "model": "test"})
    assert result["ok"] is False
    assert "private-provider-message" not in json.dumps(result)


def test_public_catalog_and_desktop_preference_allowlist_stay_consistent():
    from pathlib import Path
    import re
    from app.provider_catalog import CLOUD_PROVIDER_IDS, public_catalog
    policy = (Path(__file__).resolve().parents[2] / "desktop/lib/policy.cjs").read_text(encoding="utf-8")
    model_set = re.search(r"const MODELS = new Set\(\[(.*?)\]\)", policy, re.S).group(1)
    actual = set(re.findall(r"'([a-z0-9_]+)'", model_set))
    expected = (set(CLOUD_PROVIDER_IDS) - {"qwen"}) | {"auto", "qwen3", "ollama"}
    assert actual == expected
    assert len(public_catalog()) == len(CLOUD_PROVIDER_IDS)


@pytest.mark.parametrize("protocol,provider,path,auth", [
    ("responses", "openai_responses", "/v1/responses", "authorization"),
    ("anthropic", "anthropic", "/v1/messages", "x-api-key"),
    ("gemini", "gemini", "/v1beta/models/my-model:generateContent", "x-goog-api-key")])
def test_native_sync_nonstream_fallback_and_probe_share_wire(monkeypatch, protocol, provider, path, auth):
    requests = []
    real, real_async = httpx.Client, httpx.AsyncClient
    def respond(req):
        requests.append(req)
        return httpx.Response(200, json=fixture_payload(protocol))
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_async(transport=httpx.MockTransport(respond), **kw))
    selected = (provider, "synthetic-secret", "https://native.invalid/" + ("v1beta" if protocol == "gemini" else "v1"), "my-model")
    options = {"max_output_tokens": 4096, "send_temperature": False, "supports_streaming": False}
    message = model_client.complete(selected, [{"role": "user", "content": "hello"}], protocol=protocol, request_options=options)
    assert message["content"] == "answer"
    async def collect():
        return [item async for item in model_client.stream(selected, [{"role": "user", "content": "hello"}], protocol=protocol, request_options=options)]
    assert asyncio.run(collect()) == [("content", "answer")]
    def post(url, **kwargs):
        request = httpx.Request("POST", url, headers=kwargs["headers"], json=kwargs["json"])
        return respond(request)
    monkeypatch.setattr(httpx, "post", post)
    result = model_client.probe_provider(provider, {"api_key": selected[1], "base_url": selected[2], "model": selected[3], "protocol": protocol, "request_options": options})
    assert result["ok"] and result["protocol"] == protocol
    for request in requests:
        assert request.url.path == path
        assert request.headers[auth] == ("Bearer " if auth == "authorization" else "") + "synthetic-secret"
        assert "synthetic-secret" not in str(request.url)
        body = json.loads(request.content)
        assert "temperature" not in body
    assert requests[0].headers.get("anthropic-version") == ("2023-06-01" if protocol == "anthropic" else None)
