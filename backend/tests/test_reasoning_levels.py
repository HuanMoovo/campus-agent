"""Reasoning effort is validated against the selected model before any chat write."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from app import agent, main, model_client, model_runtime as runtime, model_wire
from app.db import SessionLocal
from app.models import Conversation, Message
from app.schemas import ChatRequest, ModelProviderUpdate


LEVELS = ["low", "medium", "high", "xhigh", "max"]
MESSAGES = [{"role": "user", "content": "hello"}]


@pytest.fixture
def config(monkeypatch, tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path, qwen_api_key="", deepseek_api_key="",
        qwen_base_url="https://qwen.invalid/v1", qwen_model="qwen",
        deepseek_base_url="https://deepseek.invalid/v1", deepseek_model="deepseek-chat")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_encrypt", lambda value: "synthetic:" + value)
    monkeypatch.setattr(runtime, "_decrypt", lambda value: value.removeprefix("synthetic:"))


@pytest.mark.parametrize("level", [None, "fast", "deep", "auto", *LEVELS])
def test_request_accepts_canonical_and_legacy_values(level):
    assert ChatRequest(message="hello", reasoning=level).reasoning == level


@pytest.mark.parametrize("level", ["ultra", "none", "minimal", "HIGH", True, 1])
def test_request_does_not_conflate_codex_or_api_values_with_app_choices(level):
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", reasoning=level)


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("level", LEVELS)
def test_each_configured_effort_reaches_its_protocol_field(protocol, level):
    request = model_wire.build_request(("openai_compatible", "synthetic", "https://gateway.invalid/v1", "private"),
        MESSAGES, protocol=protocol, reasoning=level, request_options={"reasoning_efforts": LEVELS})
    if protocol == "responses":
        assert request.body["reasoning"] == {"effort": level}
        assert "reasoning_effort" not in request.body
    else:
        assert request.body["reasoning_effort"] == level
        assert "reasoning" not in request.body


@pytest.mark.parametrize("protocol", ["chat_completions", "responses", "anthropic", "gemini"])
@pytest.mark.parametrize("level", [None, "auto"])
def test_default_effort_never_adds_an_effort_field(protocol, level):
    request = model_wire.build_request(("openai_compatible", "synthetic", "https://gateway.invalid/v1", "private"),
        MESSAGES, protocol=protocol, reasoning=level)
    assert "reasoning" not in request.body and "reasoning_effort" not in request.body


@pytest.mark.parametrize("provider,protocol,model,base,mode,levels", [
    ("openai_responses", "responses", "gpt-6.1-sol", "https://api.openai.com/v1", "effort", LEVELS),
    ("openai_compatible", "chat_completions", "gpt-5.4", "https://api.openai.com/v1", "effort", LEVELS[:-1]),
    ("openai_responses", "responses", "gpt-5.1", "https://api.openai.com/v1", "effort", LEVELS[:3]),
    ("openai_responses", "responses", "gpt-5.4", "https://api.openai.com.evil.invalid/v1", "unknown", []),
    ("openai_responses", "responses", "private-model", "https://api.openai.com/v1", "unknown", []),
    ("openai_responses", "gemini", "gpt-6.1-sol", "https://api.openai.com/v1", "unsupported", []),
    ("qwen", "chat_completions", "qwen", "https://qwen.invalid/v1", "toggle", []),
    ("ollama", "ollama", "qwen:latest", "http://127.0.0.1:11434/v1", "toggle", []),
])
def test_capability_uses_model_protocol_and_official_address(provider, protocol, model, base, mode, levels):
    result = model_wire.reasoning_capability(provider, model, protocol, base)
    assert result["mode"] == mode
    assert result["levels"] == levels


@pytest.mark.parametrize("provider,protocol", [("qwen", "chat_completions"), ("ollama", "ollama"),
    ("openai_compatible", "responses"), ("anthropic", "anthropic"), ("gemini", "gemini")])
def test_unknown_or_toggle_models_do_not_accept_new_high_as_a_boolean(provider, protocol):
    with pytest.raises(ValueError, match="推理强度"):
        model_wire.build_request((provider, "synthetic", "https://gateway.invalid/v1", "private"),
                                 MESSAGES, protocol=protocol, reasoning="high")


@pytest.mark.parametrize("efforts", [True, "high", ["high", "high"], ["ultra"], [1], [None], ("high",)])
def test_override_requires_a_unique_list_of_application_efforts(config, efforts):
    with pytest.raises(ValueError):
        runtime.update_provider("openai_compatible", {"request_options": {"reasoning_efforts": efforts}})
    with pytest.raises(ValidationError):
        ModelProviderUpdate(request_options={"reasoning_efforts": efforts})


def test_override_round_trip_disable_and_restore_inference(config):
    saved = runtime.update_provider("openai_compatible", {"model": "private",
        "request_options": {"reasoning_efforts": ["low", "high"]}})
    assert saved["providers"]["openai_compatible"]["reasoning"] == {
        "mode": "effort", "levels": ["low", "high"], "source": "configured"}
    row = runtime.update_provider("openai_compatible", {"request_options": {"reasoning_efforts": []}})["providers"]["openai_compatible"]
    assert row["reasoning"]["mode"] == "unsupported" and row["reasoning"]["levels"] == []
    row = runtime.update_provider("openai_compatible", {"model": "gpt-6.1-sol",
        "request_options": {"reasoning_efforts": None}})["providers"]["openai_compatible"]
    assert row["request_options"]["reasoning_efforts"] is None
    assert row["reasoning"] == {"mode": "effort", "levels": LEVELS, "source": "model"}


def test_capability_is_recomputed_after_identity_changes(config):
    row = runtime.update_provider("openai_responses", {"model": "gpt-6.1-sol"})["providers"]["openai_responses"]
    assert row["reasoning"]["levels"] == LEVELS
    row = runtime.update_provider("openai_responses", {"model": "private"})["providers"]["openai_responses"]
    assert row["reasoning"]["mode"] == "unknown"
    row = runtime.update_provider("openai_responses", {"model": "gpt-6.1-sol", "protocol": "gemini"})["providers"]["openai_responses"]
    assert row["reasoning"]["mode"] == "unsupported"
    row = runtime.update_provider("openai_responses", {"protocol": "responses", "base_url": "https://gateway.invalid/v1"})["providers"]["openai_responses"]
    assert row["reasoning"]["mode"] == "unknown"


@pytest.mark.parametrize("protocol", ["anthropic", "gemini"])
def test_native_protocol_never_claims_configured_openai_effort_support(config, protocol):
    row = runtime.update_provider("openai_compatible", {"model": "private", "protocol": protocol,
        "request_options": {"reasoning_efforts": ["high"]}})["providers"]["openai_compatible"]
    assert row["reasoning"]["mode"] == "unsupported" and row["reasoning"]["levels"] == []


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
@pytest.mark.parametrize("requested", ["openai_compatible", "auto"])
def test_unsupported_effort_returns_400_without_creating_a_conversation(config, route, requested):
    runtime.update_provider("openai_compatible", {"model": "private", "api_key": "synthetic"})
    client_id = str(uuid4())
    with TestClient(main.app) as client:
        response = client.post(route, json={"message": "hello", "model": requested, "reasoning": "high", "client_id": client_id})
        assert response.status_code == 400
        assert "推理强度" in response.json()["detail"]
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Conversation).where(Conversation.client_id == client_id)) == 0


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
def test_unsupported_regeneration_does_not_delete_existing_messages(config, route):
    runtime.update_provider("openai_compatible", {"model": "private", "api_key": "synthetic"})
    conversation_id, client_id = str(uuid4()), str(uuid4())
    with TestClient(main.app) as client:
        with SessionLocal() as db:
            db.add(Conversation(id=conversation_id, client_id=client_id))
            db.add_all([Message(conversation_id=conversation_id, role="user", content="hello"),
                        Message(conversation_id=conversation_id, role="assistant", content="previous answer")])
            db.commit()
        response = client.post(route, json={"message": "hello", "model": "openai_compatible", "reasoning": "high",
            "conversation_id": conversation_id, "client_id": client_id, "regenerate": True})
        assert response.status_code == 400
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)) == 2


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("streaming", [True, False])
def test_sync_and_stream_transports_send_the_same_effort(monkeypatch, protocol, streaming):
    bodies = []
    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        if protocol == "responses":
            payload = {"status": "completed", "output": [{"type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "answer"}]}]}
            text = 'data: {"type":"response.output_text.delta","delta":"answer"}\n\n' + "data: " + json.dumps({"type": "response.completed", "response": payload}) + "\n\n"
        else:
            payload = {"choices": [{"message": {"content": "answer"}}]}
            text = 'data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=text) if body.get("stream") else httpx.Response(200, json=payload)
    real, real_async = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async(transport=httpx.MockTransport(respond), **kwargs))
    selected = ("openai_compatible", "synthetic", "https://gateway.invalid/v1", "private")
    options = {"reasoning_efforts": ["high"], "supports_streaming": streaming}
    assert model_client.complete(selected, MESSAGES, reasoning="high", protocol=protocol, request_options=options)["content"] == "answer"
    async def collect():
        return [item async for item in model_client.stream(selected, MESSAGES, reasoning="high", protocol=protocol, request_options=options)]
    assert asyncio.run(collect()) == [("content", "answer")]
    assert len(bodies) == 2
    for body in bodies:
        assert (body["reasoning"] if protocol == "responses" else body["reasoning_effort"]) == ({"effort": "high"} if protocol == "responses" else "high")


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("transport", ["complete", "stream", "nonstream_fallback"])
def test_transport_does_not_turn_an_effort_configuration_error_into_empty_output(protocol, transport):
    selected = ("openai_compatible", "synthetic-key", "https://private.invalid/v1", "private-model")
    options = {"reasoning_efforts": [], "supports_streaming": transport != "nonstream_fallback"}
    with pytest.raises(ValueError, match="推理强度") as caught:
        if transport == "complete":
            model_client.complete(selected, MESSAGES, reasoning="high", protocol=protocol, request_options=options)
        else:
            async def collect():
                return [item async for item in model_client.stream(selected, MESSAGES, reasoning="high", protocol=protocol, request_options=options)]
            asyncio.run(collect())
    assert type(caught.value).__name__ == "ReasoningConfigurationError"


@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
@pytest.mark.parametrize("change", [{"request_options": {"reasoning_efforts": []}}, {"clear_api_key": True}])
def test_configuration_change_after_preflight_never_becomes_a_successful_fallback(config, monkeypatch, route, change):
    runtime.update_provider("openai_compatible", {"model": "private-model", "api_key": "synthetic-secret",
        "request_options": {"reasoning_efforts": ["high"]}})
    original_preflight = main.validate_reasoning_request
    def change_configuration(*args):
        original_preflight(*args)
        runtime.update_provider("openai_compatible", change)
    monkeypatch.setattr(main, "validate_reasoning_request", change_configuration)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "planning response"}}]})), **kwargs))
    client_id = str(uuid4())
    with TestClient(main.app) as client:
        response = client.post(route, json={"message": "hello", "model": "openai_compatible", "reasoning": "high", "client_id": client_id})
        assert "synthetic-secret" not in response.text and "private-model" not in response.text
        with SessionLocal() as db:
            conversations = db.scalars(select(Conversation).where(Conversation.client_id == client_id)).all()
            if route == "/api/chat":
                assert response.status_code == 400
                assert "推理强度" in response.json()["detail"]
                assert conversations == []
            else:
                events = []
                for frame in response.text.strip().split("\n\n"):
                    lines = frame.splitlines()
                    events.append((next(line[7:] for line in lines if line.startswith("event: ")),
                                   json.loads(next(line[6:] for line in lines if line.startswith("data: ")))))
                assert [name for name, _ in events] == ["meta", "status", "status", "error"]
                assert "推理强度" in events[-1][1]["message"]
                assert events[-1][1]["run"]["status"] == "failed"
                rows = db.scalars(select(Message).where(Message.conversation_id == conversations[0].id)).all()
                assert [row.role for row in rows] == ["user"]
