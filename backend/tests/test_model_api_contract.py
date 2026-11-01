"""Compatibility API integration, using synthetic saved configuration only."""
import asyncio
import json

import httpx
from fastapi.testclient import TestClient
import pytest

from app import agent, main


@pytest.fixture
def client(monkeypatch):
    main.app.dependency_overrides[main.require_admin] = lambda: None
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(main.require_admin, None)


def test_optional_probe_body_and_legacy_no_body_use_saved_config(client, monkeypatch):
    calls = []
    def probe(provider, capability="chat"):
        calls.append((provider, capability))
        return {"ok": True, "capability": capability}
    monkeypatch.setattr(main, "test_provider", probe)
    assert client.post("/api/models/test/qwen").json()["capability"] == "chat"
    assert client.post("/api/models/test/qwen", json={"capability": "streaming"}).json()["capability"] == "streaming"
    assert client.post("/api/models/test/qwen", json={"capability": "tools"}).json()["capability"] == "tools"
    assert calls == [("qwen", "chat"), ("qwen", "streaming"), ("qwen", "tools")]


@pytest.mark.parametrize("body", [{"capability": "unknown"}, {"capability": None},
                                    {"capability": "chat", "api_key": "draft-key"}])
def test_probe_rejects_bad_capabilities_and_draft_credentials(client, monkeypatch, body):
    monkeypatch.setattr(main, "test_provider", lambda *args: pytest.fail("Invalid probe reached provider"))
    assert client.post("/api/models/test/qwen", json=body).status_code == 422


def test_agent_threads_saved_request_options_to_both_transports(monkeypatch):
    real_client, real_async = httpx.Client, httpx.AsyncClient
    bodies = []
    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
    monkeypatch.setattr(agent.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kw: real_async(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(agent, "provider_settings", lambda name: {
        "api_key": "synthetic", "base_url": "https://model.invalid/v1", "model": "test-model",
        "request_options": {"token_parameter": "max_completion_tokens", "send_temperature": False,
                            "supports_streaming": False, "supports_tools": False}})
    messages = [{"role": "user", "content": "hello"}]
    assert agent.completion(messages, "openai_compatible", tools=[{"type": "function"}]) is None
    assert bodies == []
    assert agent.call_model(messages, "openai_compatible") == "answer"
    async def collect():
        return [chunk async for chunk in agent.stream_model(messages, "openai_compatible")]
    assert asyncio.run(collect()) == [("content", "answer")]
    assert len(bodies) == 2
    for body in bodies:
        assert body["max_completion_tokens"] == 900
        assert "max_tokens" not in body and "temperature" not in body
        assert not body.get("stream")
