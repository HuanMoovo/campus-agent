"""Offline coverage for the streamed thinking trace (采集、SSE 事件、持久化与截断)."""
import asyncio
import atexit
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import httpx
import pytest

_test_data = tempfile.TemporaryDirectory(prefix="campus-thinking-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app import agent
from app.db import engine
from app.main import app, persist_stream_exchange


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


async def _collect(generator):
    return [chunk async for chunk in generator]


def install_async_transport(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(agent.httpx, "AsyncClient", factory)


def local_provider_settings(provider):
    return {"model": "saved:latest", "base_url": "https://ignored.invalid/v1", "api_key": "unused"}


def test_ollama_stream_interleaves_thinking_and_content(monkeypatch):
    def handler(request):
        payload = "\n".join([
            json.dumps({"message": {"thinking": "先想", "content": ""}, "done": False}),
            json.dumps({"message": {"thinking": "再想"}, "done": False}),
            json.dumps({"message": {"content": "答"}}),
            json.dumps({"message": {"content": "案"}, "done": True}),
        ])
        return httpx.Response(200, content=payload.encode("utf-8"))

    monkeypatch.setattr(agent, "provider_settings", local_provider_settings)
    install_async_transport(monkeypatch, handler)
    chunks = asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "ollama", "custom:latest", "deep")))
    assert chunks == [("thinking", "先想"), ("thinking", "再想"), ("content", "答"), ("content", "案")]


def test_cloud_stream_keeps_reasoning_content_separate(monkeypatch):
    def handler(request):
        payload = "\n".join([
            "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "推理中"}}]}, ensure_ascii=False),
            "data: " + json.dumps({"choices": [{"delta": {"content": "答案"}}]}, ensure_ascii=False),
            "data: [DONE]",
        ])
        return httpx.Response(200, content=payload.encode("utf-8"))

    monkeypatch.setattr(agent, "provider_settings", lambda provider: {
        "model": "deepseek-reasoner", "base_url": "https://api.example.invalid/v1", "api_key": "test-key",
    })
    install_async_transport(monkeypatch, handler)
    chunks = asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "分析一下"}], "deepseek", None, "deep")))
    assert chunks == [("thinking", "推理中"), ("content", "答案")]


def test_streamed_thinking_emits_sse_events_and_persists(monkeypatch):
    async def fake_stream(messages, requested, local_model=None, reasoning=None):
        yield "thinking", "先思考"
        yield "content", "后回答"

    monkeypatch.setattr("app.main.stream_model", fake_stream)
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/stream",
                           json={"message": "校园一卡通补办流程是什么？", "model": "qwen", "reasoning": "deep"}) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
        events = []
        for frame in body.split("\n\n"):
            if not frame.strip():
                continue
            name, data = "message", ""
            for line in frame.splitlines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
            events.append((name, json.loads(data) if data else None))
        names = [name for name, _ in events]
        assert names == ["meta", "thinking", "delta", "done"]
        assert events[1][1]["text"] == "先思考"
        assert events[-1][1]["answer"] == "后回答"
        conversation_id = events[0][1]["conversation_id"]
        history = client.get(f"/api/conversations/{conversation_id}").json()
        assistant = history["messages"][-1]
        assert assistant["content"] == "后回答"
        assert assistant["thinking"] == "先思考"


def test_persisted_thinking_is_capped():
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Conversation, Message

    conversation_id = str(uuid4())
    with SessionLocal() as db:
        db.add(Conversation(id=conversation_id, client_id="thinking-test"))
        db.commit()
    persist_stream_exchange(conversation_id, "问题", "回答", None, "", streamed_from_model=True, thinking="想" * 20000)
    with SessionLocal() as db:
        row = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)).all()[-1]
        assert len(row.result_data["thinking"]) == 12000
