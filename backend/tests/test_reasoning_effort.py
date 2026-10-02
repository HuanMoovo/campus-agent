"""Offline coverage for the 快速 / 深度 reasoning effort mapping (Ollama, Qwen, DeepSeek)."""
import asyncio
import atexit
import json
import os
from pathlib import Path
import tempfile

import httpx
import pytest
from pydantic import ValidationError

_test_data = tempfile.TemporaryDirectory(prefix="campus-reasoning-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app import agent
from app.db import engine
from app.main import app
from app.schemas import ChatRequest


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


@pytest.mark.parametrize("reasoning", [None, "fast", "deep"])
def test_reasoning_values_are_accepted(reasoning):
    assert ChatRequest(message="hello", reasoning=reasoning).reasoning == reasoning


@pytest.mark.parametrize("reasoning", ["ultra", "medium", "FAST", True, 1])
def test_unknown_reasoning_values_are_rejected(reasoning):
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", reasoning=reasoning)


def install_transport(monkeypatch, handler):
    real_client = httpx.Client

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(agent.httpx, "Client", client)


def install_async_transport(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(agent.httpx, "AsyncClient", factory)


def local_settings(provider):
    assert provider == "ollama"
    return {"model": "saved:latest", "base_url": "https://ignored.invalid/v1", "api_key": "unused"}


def cloud_settings(provider, model="qwen3-235b-a22b"):
    return {"model": model, "base_url": "https://api.example.invalid/v1", "api_key": "test-key"}


def test_ollama_deep_sets_think_true(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "好的"}})

    monkeypatch.setattr(agent, "provider_settings", local_settings)
    install_transport(monkeypatch, handler)
    assert agent.call_model([{"role": "user", "content": "你好"}], "ollama", "custom:latest", "deep") == "好的"
    assert bodies[0]["think"] is True

    assert agent.call_model([{"role": "user", "content": "你好"}], "ollama", "custom:latest") == "好的"
    assert bodies[1]["think"] is False


def test_ollama_deep_falls_back_when_thinking_is_unsupported(monkeypatch):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("think"):
            return httpx.Response(400, json={"error": 'model "custom:latest" does not support thinking'})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "普通回答"}})

    monkeypatch.setattr(agent, "provider_settings", local_settings)
    install_transport(monkeypatch, handler)
    assert agent.call_model([{"role": "user", "content": "你好"}], "ollama", "custom:latest", "deep") == "普通回答"
    assert [body["think"] for body in bodies] == [True, False]


async def _collect(generator):
    return [chunk async for chunk in generator]


def test_ollama_stream_deep_retries_without_thinking(monkeypatch):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("think"):
            return httpx.Response(400, json={"error": "does not support thinking"})
        payload = "\n".join([
            json.dumps({"message": {"content": "普"}, "done": False}),
            json.dumps({"message": {"content": "通"}, "done": True}),
        ])
        return httpx.Response(200, content=payload.encode("utf-8"))

    monkeypatch.setattr(agent, "provider_settings", local_settings)
    install_async_transport(monkeypatch, handler)
    chunks = asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "ollama", "custom:latest", "deep")))
    assert chunks == [("content", "普"), ("content", "通")]
    assert [body["think"] for body in bodies] == [True, False]


def test_qwen_stream_thinking_follows_reasoning(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        payload = "\n".join([
            "data: " + json.dumps({"choices": [{"delta": {"content": "好"}}]}),
            "data: [DONE]",
        ])
        return httpx.Response(200, content=payload.encode("utf-8"))

    monkeypatch.setattr(agent, "provider_settings", cloud_settings)
    install_async_transport(monkeypatch, handler)
    chunks = asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "qwen", None, "deep")))
    assert chunks == [("content", "好")]
    assert bodies[0]["enable_thinking"] is True

    asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "qwen")))
    assert bodies[1]["enable_thinking"] is False


def test_qwen_non_stream_always_disables_thinking(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "好"}}]})

    monkeypatch.setattr(agent, "provider_settings", cloud_settings)
    install_transport(monkeypatch, handler)
    assert agent.call_model([{"role": "user", "content": "你好"}], "qwen", None, "deep") == "好"
    assert bodies[0]["enable_thinking"] is False


def test_deepseek_deep_switches_to_reasoner(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "推理回答"}}]})

    def deepseek_settings(provider, model="deepseek-chat"):
        return {"model": model, "base_url": "https://api.example.invalid/v1", "api_key": "test-key"}

    monkeypatch.setattr(agent, "provider_settings", deepseek_settings)
    install_transport(monkeypatch, handler)
    assert agent.call_model([{"role": "user", "content": "分析一下"}], "deepseek", None, "deep") == "推理回答"
    assert bodies[0]["model"] == "deepseek-reasoner"
    assert "temperature" not in bodies[0]

    assert agent.call_model([{"role": "user", "content": "你好"}], "deepseek") == "推理回答"
    assert bodies[1]["model"] == "deepseek-chat"
    assert bodies[1]["temperature"] == 0.2


def test_chat_api_accepts_deep_and_rejects_unknown_reasoning():
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "你好", "reasoning": "deep"})
        assert response.status_code == 200
        assert response.json()["mode"] in {"demo", "llm"}
        assert client.post("/api/chat", json={"message": "你好", "reasoning": "ultra"}).status_code == 422
