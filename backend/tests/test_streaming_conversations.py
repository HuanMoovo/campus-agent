"""Offline coverage for streamed chat, stop-safe persistence and conversation management."""
import asyncio
import atexit
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

_test_data = tempfile.TemporaryDirectory(prefix="campus-stream-test-")
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


def parse_events(body: str):
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
    return events


def stream_chat(client, payload):
    with client.stream("POST", "/api/chat/stream", json=payload) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return parse_events("".join(response.iter_text()))


def test_streamed_chat_emits_sse_events_and_persists_history():
    client_id = f"test-{uuid4()}"
    with TestClient(app) as client:
        events = stream_chat(client, {"message": "校园一卡通补办流程是什么？", "client_id": client_id})
        names = [name for name, _ in events]
        assert names[0] == "meta"
        assert names[-1] == "done"
        assert names.count("delta") >= 1
        conversation_id = events[0][1]["conversation_id"]
        done = events[-1][1]
        assert done["conversation_id"] == conversation_id
        assert done["answer"] and done["sources"] and done["mode"] == "demo"
        streamed = "".join(data["text"] for name, data in events if name == "delta")
        assert done["answer"] == streamed
        history = client.get(f"/api/conversations/{conversation_id}").json()
        assert [row["role"] for row in history["messages"]] == ["user", "assistant"]
        assert history["messages"][-1]["content"] == done["answer"]


def test_streamed_service_answers_get_one_delta_and_tool_record():
    with TestClient(app) as client:
        events = stream_chat(client, {"message": "查询我的课表"})
        assert [name for name, _ in events] == ["meta", "delta", "done"]
        done = events[-1][1]
        assert done["tool_calls"][0]["name"] == "schedule"
        assert done["mode"] == "demo"
        assert "演示数据" in done["answer"]


def test_unknown_conversation_is_rejected_before_streaming():
    with TestClient(app) as client:
        response = client.post("/api/chat/stream", json={"message": "你好", "conversation_id": "missing-conversation"})
        assert response.status_code == 404


def test_conversation_listing_and_deletion_are_client_scoped():
    first_client, second_client = f"test-{uuid4()}", f"test-{uuid4()}"
    with TestClient(app) as client:
        first = client.post("/api/chat", json={"message": "查询我的课表", "client_id": first_client}).json()
        second = client.post("/api/chat", json={"message": "查询我的学分", "client_id": first_client}).json()
        other = client.post("/api/chat", json={"message": "查询我的成绩", "client_id": second_client}).json()
        listed = client.get("/api/conversations", params={"client_id": first_client}).json()
        ids = [row["id"] for row in listed]
        assert set(ids) == {first["conversation_id"], second["conversation_id"]}
        assert ids[0] == second["conversation_id"]
        assert all(row["message_count"] == 2 for row in listed)
        titles = {row["id"]: row["title"] for row in listed}
        assert titles[first["conversation_id"]] == "查询我的课表"
        assert all(row["updated_at"].endswith("+00:00") for row in listed)
        other_list = client.get("/api/conversations", params={"client_id": second_client}).json()
        assert [row["id"] for row in other_list] == [other["conversation_id"]]
        assert client.delete(f"/api/conversations/{first['conversation_id']}", params={"client_id": second_client}).status_code == 404
        assert client.delete(f"/api/conversations/{first['conversation_id']}", params={"client_id": first_client}).status_code == 200
        remaining = [row["id"] for row in client.get("/api/conversations", params={"client_id": first_client}).json()]
        assert remaining == [second["conversation_id"]]
        assert client.get(f"/api/conversations/{first['conversation_id']}").status_code == 404
        cleared = client.delete("/api/conversations", params={"client_id": first_client}).json()
        assert cleared["deleted"] == 1
        assert client.get("/api/conversations", params={"client_id": first_client}).json() == []
        assert client.get(f"/api/conversations/{other['conversation_id']}").status_code == 200


def test_legacy_conversations_are_claimed_by_their_next_message():
    client_id = f"test-{uuid4()}"
    with TestClient(app) as client:
        legacy = client.post("/api/chat", json={"message": "查询我的课表"}).json()
        assert client.get("/api/conversations", params={"client_id": client_id}).json() == []
        reply = client.post("/api/chat", json={"message": "查询我的学分", "conversation_id": legacy["conversation_id"], "client_id": client_id})
        assert reply.status_code == 200
        listed = [row["id"] for row in client.get("/api/conversations", params={"client_id": client_id}).json()]
        assert listed == [legacy["conversation_id"]]


@pytest.mark.parametrize("client_id", ["../config", "a" * 65, "bad id", "换行\n"])
def test_invalid_client_ids_are_rejected(client_id):
    with pytest.raises(ValidationError):
        ChatRequest(message="hello", client_id=client_id)


def test_client_id_column_is_added_to_pre_existing_databases(monkeypatch, tmp_path):
    from sqlalchemy import create_engine, inspect
    from app import db as db_module

    legacy = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with legacy.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO conversations (id) VALUES ('legacy-1')")
    monkeypatch.setattr(db_module, "engine", legacy)
    db_module.ensure_conversation_client_id()
    db_module.ensure_conversation_client_id()
    assert "client_id" in {column["name"] for column in inspect(legacy).get_columns("conversations")}
    with legacy.begin() as connection:
        assert connection.exec_driver_sql("SELECT client_id FROM conversations").scalar() == ""


async def _collect(generator):
    return [chunk async for chunk in generator]


def install_async_transport(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(agent.httpx, "AsyncClient", factory)


def local_provider_settings(provider):
    assert provider == "ollama"
    return {"model": "saved:latest", "base_url": "https://ignored.invalid/v1", "api_key": "unused"}


def test_stream_model_yields_local_deltas(monkeypatch):
    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["stream"] is True and body["think"] is False
        assert body["model"] == "organization/custom:Q4_K_M"
        payload = "\n".join([
            json.dumps({"message": {"content": "你"}, "done": False}),
            json.dumps({"message": {"content": "好"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ])
        return httpx.Response(200, content=payload.encode("utf-8"))

    monkeypatch.setattr(agent, "provider_settings", local_provider_settings)
    install_async_transport(monkeypatch, handler)
    chunks = asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "ollama", "organization/custom:Q4_K_M")))
    assert chunks == [("content", "你"), ("content", "好")]


def test_stream_model_reports_local_failure_instead_of_falling_back(monkeypatch):
    monkeypatch.setattr(agent, "provider_settings", local_provider_settings)
    install_async_transport(monkeypatch, lambda request: httpx.Response(500, json={"error": "out of memory"}))
    with pytest.raises(agent.LocalModelError) as error:
        asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "hello"}], "ollama", "custom:latest")))
    assert error.value.status_code == 502


def test_stream_model_parses_cloud_sse(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://qwen.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content)["stream"] is True
        payload = "\n".join([
            'data: {"choices": [{"delta": {"content": "嗨"}}]}',
            "",
            'data: {"choices": [{"delta": {"content": "！"}}]}',
            "",
            "data: [DONE]",
            "",
        ])
        return httpx.Response(200, content=payload.encode("utf-8"))

    monkeypatch.setattr(agent, "provider_settings", lambda provider: {
        "model": "qwen3-test", "base_url": "https://qwen.example/v1", "api_key": "test-key",
    } if provider == "qwen" else {
        "model": "deepseek-test", "base_url": "https://deepseek.example/v1", "api_key": "",
    })
    install_async_transport(monkeypatch, handler)
    chunks = asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "qwen")))
    assert chunks == [("content", "嗨"), ("content", "！")]


def test_stream_model_without_provider_yields_nothing(monkeypatch):
    monkeypatch.setattr(agent, "provider_settings", lambda provider: {
        "model": "qwen3-test", "base_url": "https://qwen.example/v1", "api_key": "",
    })
    assert asyncio.run(_collect(agent.stream_model([{"role": "user", "content": "你好"}], "auto"))) == []


def test_interrupted_model_stream_is_persisted_as_partial_llm_answer():
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.main import persist_stream_exchange
    from app.models import Conversation, Message

    conversation_id = str(uuid4())
    with SessionLocal() as db:
        db.add(Conversation(id=conversation_id, client_id="persist-test"))
        db.commit()
    persist_stream_exchange(conversation_id, "问题", "半截回答", None, "", streamed_from_model=True)
    with SessionLocal() as db:
        rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)).all()
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[-1].content == "半截回答"
        assert rows[-1].result_data["partial"] is True
        assert rows[-1].result_data["mode"] == "llm"
