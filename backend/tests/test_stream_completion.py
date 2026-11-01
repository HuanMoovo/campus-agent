"""Offline regressions for model stream completion and partial-answer persistence."""
import atexit
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import httpx
import pytest

_test_data = tempfile.TemporaryDirectory(prefix="campus-stream-completion-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import agent, main
from app.db import engine, SessionLocal
from app.models import Message


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


class ModelBytes(httpx.AsyncByteStream):
    def __init__(self, payload, disconnect=False):
        self.payload = payload.encode("utf-8")
        self.disconnect = disconnect

    async def __aiter__(self):
        yield self.payload
        if self.disconnect:
            raise httpx.ReadError("private upstream diagnostics")


def cloud_frame(delta=None, **choice):
    return "data: " + json.dumps({"choices": [{"delta": delta or {}, **choice}]}) + "\n\n"


def ollama_frame(message=None, **fields):
    return json.dumps({"message": message or {}, **fields}) + "\n"


def install_model(monkeypatch, provider, payload, *, disconnect=False, status_code=200):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(agent, "choose_model", lambda *args: (
        provider, "test-key", "https://model.example.invalid/v1", "test-model",
    ))
    monkeypatch.setattr(main, "resolve_local_model", lambda model: "test-model")
    monkeypatch.setattr(main, "prepare_stream_state", lambda *args: {
        "messages": [{"role": "user", "content": "question"}],
        "requested_model": provider, "sources": [],
        "fallback": {"answer": "offline fallback", "mode": "demo"},
    })
    transport = httpx.MockTransport(lambda request: httpx.Response(
        status_code, stream=ModelBytes(payload, disconnect),
    ))
    monkeypatch.setattr(agent.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=transport, **kwargs,
    ))


def request_stream(client, provider):
    response = client.post("/api/chat/stream", json={
        "message": "question", "model": provider, "client_id": str(uuid4()),
    })
    assert response.status_code == 200
    events = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        event = next(line[6:].strip() for line in lines if line.startswith("event:"))
        data = next(line[5:].strip() for line in lines if line.startswith("data:"))
        events.append((event, json.loads(data)))
    return events


@pytest.mark.parametrize("provider", ["openai_compatible", "ollama"])
@pytest.mark.parametrize("failure", ["disconnect", "eof", "error_frame", "length", "malformed_json"])
def test_incomplete_model_answer_emits_error_and_persists_partial(monkeypatch, provider, failure):
    payload = (ollama_frame({"content": "partial answer"}, done=False) if provider == "ollama"
               else cloud_frame({"content": "partial answer"}))
    if failure == "error_frame":
        payload += ('{"error":"private upstream diagnostics"}\n' if provider == "ollama"
                    else 'data: {"error":{"message":"private upstream diagnostics"}}\n\n')
    elif failure == "length":
        payload += ('{"done":true,"done_reason":"length"}\n' if provider == "ollama"
                    else cloud_frame(finish_reason="length"))
    elif failure == "malformed_json":
        payload += 'broken-json\n' if provider == "ollama" else 'data: broken-json\n\ndata: [DONE]\n\n'
    install_model(monkeypatch, provider, payload, disconnect=failure == "disconnect")

    with TestClient(main.app) as client:
        events = request_stream(client, provider)
    assert [name for name, _ in events] == ["meta", "status", "status", "delta", "error"]
    assert events[-1][1]["partial"] == "partial answer"
    assert events[-1][1]["message"]
    assert "private upstream diagnostics" not in events[-1][1]["message"]
    with SessionLocal() as db:
        rows = db.scalars(select(Message).where(
            Message.conversation_id == events[0][1]["conversation_id"],
        ).order_by(Message.id)).all()
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[-1].content == "partial answer"
        assert rows[-1].result_data["partial"] is True
        assert rows[-1].result_data["mode"] == "llm"


@pytest.mark.parametrize("failure", ["disconnect", "eof", "error_frame"])
def test_cloud_failure_after_thinking_does_not_become_successful_fallback(monkeypatch, failure):
    payload = cloud_frame({"reasoning_content": "unfinished thinking"})
    if failure == "error_frame":
        payload += 'data: {"error":{"message":"private upstream diagnostics"}}\n\n'
    install_model(monkeypatch, "openai_compatible", payload, disconnect=failure == "disconnect")
    with TestClient(main.app) as client:
        events = request_stream(client, "openai_compatible")
    assert [name for name, _ in events] == ["meta", "status", "status", "thinking", "error"]
    assert events[-1][1]["partial"] == ""
    assert events[-1][1]["message"]


@pytest.mark.parametrize("failure", ["http_status", "disconnect", "eof", "error_frame"])
def test_cloud_failure_before_any_output_preserves_offline_fallback(monkeypatch, failure):
    payload = 'data: {"error":{"message":"upstream unavailable"}}\n\n' if failure == "error_frame" else ""
    install_model(monkeypatch, "openai_compatible", payload,
                  disconnect=failure == "disconnect", status_code=503 if failure == "http_status" else 200)
    with TestClient(main.app) as client:
        events = request_stream(client, "openai_compatible")
    assert [name for name, _ in events] == ["meta", "status", "status", "delta", "done"]
    assert events[-1][1]["answer"] == "offline fallback"
    assert events[-1][1]["mode"] == "demo"


@pytest.mark.parametrize("ending", ["done", "finish_reason", "finish_and_usage", "finish_disconnect", "ollama_done", "ollama_done_only"])
def test_explicit_completion_preserves_success(monkeypatch, ending):
    provider = "ollama" if ending.startswith("ollama") else "openai_compatible"
    if provider == "ollama":
        payload = ollama_frame({"content": "complete answer"}, done=ending == "ollama_done")
        if ending == "ollama_done_only":
            payload += '{"done":true}\n'
    else:
        payload = cloud_frame({"content": "complete answer"})
        if ending == "done":
            payload += "data: [DONE]\n\n"
        else:
            payload += cloud_frame(finish_reason="stop")
            if ending == "finish_and_usage":
                payload += 'data: {"choices":[],"usage":{"total_tokens":5}}\n\n'
    install_model(monkeypatch, provider, payload, disconnect=ending == "finish_disconnect")
    with TestClient(main.app) as client:
        events = request_stream(client, provider)
    assert [name for name, _ in events] == ["meta", "status", "status", "delta", "done"]
    assert events[-1][1]["answer"] == "complete answer"
    assert events[-1][1]["mode"] == "llm"
