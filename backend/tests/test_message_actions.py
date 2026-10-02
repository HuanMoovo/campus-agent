"""Offline coverage for message actions：重新生成替换末尾问答对、有帮助/没帮助反馈。"""
import atexit
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

_test_data = tempfile.TemporaryDirectory(prefix="campus-actions-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app, persist_stream_exchange, replace_trailing_exchange
from app.models import Conversation


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


def _sse_frames(body: str):
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


def _stream_chat(client, question, **extra):
    payload = {"message": question, "model": "qwen", **extra}
    with client.stream("POST", "/api/chat/stream", json=payload) as response:
        assert response.status_code == 200
        return _sse_frames("".join(response.iter_text()))


def _seed_conversation(client_id: str) -> str:
    conversation_id = str(uuid4())
    with SessionLocal() as db:
        db.add(Conversation(id=conversation_id, client_id=client_id))
        db.commit()
    return conversation_id


def test_regenerate_replaces_trailing_exchange_stream(monkeypatch):
    state = {"n": 0}

    async def fake_stream(messages, requested, local_model=None, reasoning=None):
        state["n"] += 1
        yield "content", f"第{state['n']}次回答。"

    monkeypatch.setattr("app.main.stream_model", fake_stream)
    with TestClient(app) as client:
        events = _stream_chat(client, "一卡通如何补办？")
        conversation_id = events[0][1]["conversation_id"]
        history = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert [row["role"] for row in history] == ["user", "assistant"]
        assert history[-1]["content"] == "第1次回答。"

        events = _stream_chat(client, "一卡通如何补办？", conversation_id=conversation_id, regenerate=True)
        assert events[-1][1]["answer"] == "第2次回答。"
        history = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert [row["role"] for row in history] == ["user", "assistant"]
        assert sum(row["role"] == "user" for row in history) == 1
        assert history[-1]["content"] == "第2次回答。"

        # 对照组：不带 regenerate 时保持追加语义。
        _stream_chat(client, "一卡通如何补办？", conversation_id=conversation_id)
        history = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert len(history) == 4


def test_regenerate_replaces_trailing_exchange_nonstream():
    with TestClient(app) as client:
        first = client.post("/api/chat", json={"message": "图书馆几点开门？", "model": "qwen"}).json()
        conversation_id = first["conversation_id"]
        client.post("/api/chat", json={"message": "图书馆几点开门？", "model": "qwen", "conversation_id": conversation_id, "regenerate": True})
        history = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert [row["role"] for row in history] == ["user", "assistant"]
        assert sum(row["role"] == "user" for row in history) == 1


def test_feedback_sets_switches_and_clears():
    conversation_id = _seed_conversation("actions-test")
    persist_stream_exchange(conversation_id, "问题", "回答", None, "", streamed_from_model=True)
    with TestClient(app) as client:
        history = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assistant = history[-1]
        assert isinstance(assistant["id"], int)
        message_id = assistant["id"]
        endpoint = f"/api/conversations/{conversation_id}/messages/{message_id}/feedback"

        response = client.post(endpoint, json={"value": "up"})
        assert response.status_code == 200 and response.json() == {"ok": True, "feedback": "up"}
        assert client.get(f"/api/conversations/{conversation_id}").json()["messages"][-1]["feedback"] == "up"

        client.post(endpoint, json={"value": "down"})
        assert client.get(f"/api/conversations/{conversation_id}").json()["messages"][-1]["feedback"] == "down"

        client.post(endpoint, json={"value": None})
        assert "feedback" not in client.get(f"/api/conversations/{conversation_id}").json()["messages"][-1]

        assert client.post(f"/api/conversations/{uuid4()}/messages/{message_id}/feedback", json={"value": "up"}).status_code == 404
        user_message_id = history[0]["id"]
        assert client.post(f"/api/conversations/{conversation_id}/messages/{user_message_id}/feedback", json={"value": "up"}).status_code == 404
        assert client.post(f"/api/conversations/{conversation_id}/messages/999999/feedback", json={"value": "up"}).status_code == 404
        assert client.post(endpoint, json={"value": "maybe"}).status_code == 422


def test_replace_trailing_exchange_is_strict_about_match():
    conversation_id = _seed_conversation("actions-test")
    persist_stream_exchange(conversation_id, "问题一", "回答一", None, "", streamed_from_model=True)
    with SessionLocal() as db:
        assert replace_trailing_exchange(db, conversation_id, "另一个问题") is False
        db.commit()
        assert replace_trailing_exchange(db, conversation_id, "问题一") is True
        db.commit()
    with TestClient(app) as client:
        assert client.get(f"/api/conversations/{conversation_id}").json()["messages"] == []
