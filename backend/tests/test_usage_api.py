"""Usage is real transport metadata, scoped to the current website/local user."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import agent, auth, main, model_client, token_usage
from app.db import Base, get_db
from app.models import TokenUsage


REAL_SYNC_CLIENT, REAL_ASYNC_CLIENT = httpx.Client, httpx.AsyncClient


@pytest.fixture
def usage_app(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'api-usage.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(token_usage, "SessionLocal", factory)
    monkeypatch.setattr(main, "desktop_enabled", lambda: False)
    monkeypatch.setattr(auth, "setting", lambda _name, default=None: default)
    monkeypatch.setattr(agent, "choose_model", lambda *args: ("qwen", "fixture-key", "https://fixture.invalid/v1", "fixture-model"))
    monkeypatch.setattr(agent, "provider_settings", lambda *args: {"protocol": "chat_completions", "request_options": {}})
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda *args: [])
    monkeypatch.setattr(agent.knowledge_index, "search", lambda *args: [])
    def db_dependency():
        with factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = db_dependency
    client = TestClient(main.app)
    yield client, factory
    client.close()
    main.app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def install_transport(monkeypatch, *, reported=True, streaming=True):
    def handler(request):
        body = json.loads(request.content)
        usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
                 "prompt_tokens_details": {"cached_tokens": 3}, "completion_tokens_details": {"reasoning_tokens": 2}}
        if body.get("stream"):
            frames = 'data: ' + json.dumps({"choices": [{"delta": {"content": "fixture answer"}, "finish_reason": None}]}) + '\n\n'
            frames += 'data: ' + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}) + '\n\n'
            if reported:
                frames += 'data: ' + json.dumps({"choices": [], "usage": usage}) + '\n\n'
            return httpx.Response(200, text=frames + 'data: [DONE]\n\n', headers={"content-type": "text/event-stream"})
        response = {"choices": [{"message": {"role": "assistant", "content": "fixture answer"}, "finish_reason": "stop"}]}
        if reported:
            response["usage"] = usage
        return httpx.Response(200, json=response)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(model_client.httpx, "Client", lambda **kwargs: REAL_SYNC_CLIENT(transport=transport, **kwargs))
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=transport, **kwargs))


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_actual_transport_usage_and_unknown_are_distinct(endpoint, usage_app, monkeypatch):
    client, _factory = usage_app
    install_transport(monkeypatch)
    response = client.post(endpoint, json={"message": "Explain a Python loop", "model": "qwen", "client_id": "one"})
    assert response.status_code == 200, response.text
    summary = client.get("/api/usage", params={"client_id": "one", "days": 7}).json()
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["reported_requests"] == 1
    assert summary["totals"]["input_tokens"] == 11
    assert summary["totals"]["output_tokens"] == 7
    assert summary["totals"]["total_tokens"] == 18
    assert summary["totals"]["cached_input_tokens"] == 3
    assert summary["totals"]["reasoning_tokens"] == 2
    assert client.get("/api/usage", params={"client_id": "two"}).json()["totals"]["requests"] == 0
    # Do not turn a provider that omits metadata into a zero-token request.
    install_transport(monkeypatch, reported=False)
    assert client.post(endpoint, json={"message": "Explain a loop", "model": "qwen", "client_id": "two"}).status_code == 200
    missing = client.get("/api/usage", params={"client_id": "two"}).json()["totals"]
    assert missing["requests"] == missing["unreported_requests"] == 1
    assert missing["total_tokens"] is None and missing["input_tokens"] is None


def test_regeneration_and_deletion_do_not_erase_usage(usage_app, monkeypatch):
    client, _factory = usage_app
    install_transport(monkeypatch)
    body = {"message": "Explain a loop", "model": "qwen", "client_id": "one"}
    created = client.post("/api/chat", json=body).json()
    regenerated = client.post("/api/chat", json={**body, "conversation_id": created["conversation_id"], "regenerate": True})
    assert regenerated.status_code == 200
    assert client.delete(f"/api/conversations/{created['conversation_id']}", params={"client_id": "one"}).status_code == 200
    result = client.get("/api/usage", params={"client_id": "one"}).json()["totals"]
    assert result["requests"] == 2 and result["total_tokens"] == 36


def test_threadpool_planner_and_stream_answer_share_scope(usage_app, monkeypatch):
    client, _factory = usage_app
    install_transport(monkeypatch)
    def preparation(*args, **kwargs):
        agent.completion([{"role": "user", "content": "fixture planning"}], "qwen")
        return {"messages": [{"role": "user", "content": "fixture answer"}], "requested_model": "qwen", "sources": [],
                "fallback": {"answer": "fallback", "sources": [], "tool_calls": [], "mode": "demo"}}
    monkeypatch.setattr(main, "prepare_stream_state", preparation)
    assert client.post("/api/chat/stream", json={"message": "Explain a loop", "model": "qwen", "client_id": "one"}).status_code == 200
    totals = client.get("/api/usage", params={"client_id": "one"}).json()["totals"]
    assert totals["requests"] == 2 and totals["total_tokens"] == 36
    assert client.get("/api/usage", params={"client_id": "two"}).json()["totals"]["requests"] == 0


def test_parallel_clients_cannot_leak_or_duplicate_usage(usage_app, monkeypatch):
    client, _factory = usage_app
    install_transport(monkeypatch)
    def call(identifier):
        response = client.post("/api/chat", json={"message": "Explain a loop", "model": "qwen", "client_id": identifier})
        assert response.status_code == 200, response.text
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(call, ["one", "two"]))
    for identifier in ("one", "two"):
        result = client.get("/api/usage", params={"client_id": identifier}).json()["totals"]
        assert result["requests"] == 1 and result["total_tokens"] == 18


def test_authenticated_usage_ignores_forged_client_and_requires_login(usage_app, monkeypatch):
    client, factory = usage_app
    original_setting = auth.setting
    monkeypatch.setattr(auth, "setting", lambda name, default=None: True if name == "auth_required" else original_setting(name, default))
    with factory() as db:
        alice = auth.create_user(db, "usage-alice", "alice-password-1")
        bob = auth.create_user(db, "usage-bob", "bob-password-1")
        db.add_all(TokenUsage(id=name, created_at=datetime.now(timezone.utc), owner_user_id=owner, client_id="forged",
            provider="qwen", model="fixture", protocol="chat_completions", operation="chat", status="completed",
            input_tokens=tokens, output_tokens=1, total_tokens=tokens + 1) for name, owner, tokens in
            [("alice", alice.id, 10), ("bob", bob.id, 20), ("anonymous", None, 99)])
        db.commit()
    assert client.get("/api/usage", params={"client_id": "forged"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "usage-alice", "password": "alice-password-1"}).status_code == 200
    totals = client.get("/api/usage", params={"client_id": "forged"}).json()["totals"]
    assert totals["requests"] == 1 and totals["total_tokens"] == 11
    assert client.get("/api/usage", params={"client_id": "different-browser"}).json()["totals"] == totals


def test_desktop_usage_collects_unowned_app_calls_across_profiles(usage_app, monkeypatch):
    client, factory = usage_app
    monkeypatch.setattr(main, "desktop_enabled", lambda: True)
    install_transport(monkeypatch)
    assert client.post("/api/chat", json={"message": "Explain a loop", "model": "qwen", "client_id": "one"}).status_code == 200
    assert client.get("/api/usage", params={"client_id": "two"}).json()["totals"]["requests"] == 1
    with factory() as db:
        event = db.scalar(select(TokenUsage))
        assert event.client_id == "" and event.owner_user_id is None


def test_desktop_project_draft_records_usage_without_conversation(usage_app, monkeypatch):
    from app import project_api
    client, factory = usage_app
    monkeypatch.setattr(main, "desktop_enabled", lambda: True)
    monkeypatch.setattr(project_api, "_require_desktop", lambda request: None)
    install_transport(monkeypatch)
    def make_draft(*args):
        result = model_client.complete(("qwen", "fixture-key", "https://fixture.invalid/v1", "fixture-model"),
            [{"role": "user", "content": "synthetic draft"}])
        return {"fixture": bool(result)}
    monkeypatch.setattr(project_api.proposals, "create", make_draft)
    response = client.post("/api/projects/fixture/proposals", json={"path": "README.md", "instruction": "synthetic draft"})
    assert response.status_code == 200 and response.json() == {"fixture": True}
    result = client.get("/api/usage", params={"client_id": "one"}).json()["totals"]
    assert result["requests"] == 1 and result["total_tokens"] == 18
    with factory() as db:
        assert db.scalar(select(TokenUsage)).operation == "project_proposal"


def test_failed_model_attempt_is_recorded_without_upstream_error(usage_app, monkeypatch):
    client, factory = usage_app
    transport = httpx.MockTransport(lambda request: httpx.Response(502, json={"error": {"message": "PRIVATE-UPSTREAM-DETAIL"}}))
    monkeypatch.setattr(model_client.httpx, "Client", lambda **kwargs: REAL_SYNC_CLIENT(transport=transport, **kwargs))
    assert client.post("/api/chat", json={"message": "Explain a loop", "model": "qwen", "client_id": "one"}).status_code == 200
    result = client.get("/api/usage", params={"client_id": "one"}).json()
    assert result["totals"]["requests"] == result["totals"]["unreported_requests"] == 1
    assert result["totals"]["total_tokens"] is None
    assert "PRIVATE-UPSTREAM-DETAIL" not in json.dumps(result)
    with factory() as db:
        event = db.scalar(select(TokenUsage))
        assert event.status == "failed" and "PRIVATE-UPSTREAM-DETAIL" not in repr(event.__dict__)


@pytest.mark.parametrize("params", [{"days": 0}, {"days": 8}, {"days": 90}, {"days": "all"}, {"client_id": "x" * 65}, {"client_id": "bad/id"}])
def test_usage_query_rejects_unbounded_periods_and_invalid_profiles(params, usage_app):
    client, _factory = usage_app
    assert client.get("/api/usage", params=params).status_code == 422


def test_pure_service_answer_does_not_create_usage(usage_app):
    client, _factory = usage_app
    assert client.post("/api/chat", json={"message": "查询我的课表", "client_id": "one"}).status_code == 200
    assert client.get("/api/usage", params={"client_id": "one"}).json()["totals"]["requests"] == 0


def test_disconnect_persists_attempt_without_inventing_tokens(usage_app, monkeypatch):
    client, factory = usage_app
    real_async = httpx.AsyncClient
    class PausedModel(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial answer"},"finish_reason":null}]}\n\n'
            await asyncio.Event().wait()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=PausedModel()))
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda **kwargs: real_async(transport=transport, **kwargs))
    async def scenario():
        disconnected = asyncio.Event()
        delivered = False
        payload = json.dumps({"message": "Explain a loop", "model": "qwen", "client_id": "one"}).encode()
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if b"partial answer" in message.get("body", b""):
                disconnected.set()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
                 "method": "POST", "scheme": "http", "path": "/api/chat/stream", "raw_path": b"/api/chat/stream",
                 "root_path": "", "query_string": b"", "http_version": "1.1", "server": ("testserver", 80),
                 "client": ("127.0.0.1", 12345), "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")]}
        await asyncio.wait_for(main.app(scope, receive, send), 5)
    asyncio.run(scenario())
    totals = client.get("/api/usage", params={"client_id": "one"}).json()["totals"]
    assert totals["requests"] == totals["unreported_requests"] == 1
    assert totals["total_tokens"] is None
    with factory() as db:
        assert db.scalar(select(TokenUsage)).status == "cancelled"


def test_explicit_stream_close_flushes_transport_before_ledger(usage_app, monkeypatch):
    from starlette.requests import Request
    from app.schemas import ChatRequest
    client, factory = usage_app
    class PausedModel(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial answer"},"finish_reason":null}]}\n\n'
            await asyncio.Event().wait()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=PausedModel()))
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda **kwargs: REAL_ASYNC_CLIENT(transport=transport, **kwargs))
    async def scenario():
        response = await main.chat_stream(ChatRequest(message="Explain a loop", model="qwen", client_id="one"),
                                         Request({"type": "http"}))
        async for frame in response.body_iterator:
            if "partial answer" in frame:
                break
        await response.body_iterator.aclose()
        with factory() as db:
            event = db.scalar(select(TokenUsage))
            assert event is not None, "Closing the outer stream must settle its transport before flushing usage"
            assert event.status == "cancelled" and event.total_tokens is None
    asyncio.run(scenario())
