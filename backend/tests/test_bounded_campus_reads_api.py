"""Offline parity and current-message authority for bounded campus tasks."""
import json
import asyncio
import threading
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app import agent, main
from app.agent_tasks import ReadTaskControl


def terminal(response, endpoint):
    if not endpoint.endswith("stream"):
        return response.json()
    frames = []
    for frame in response.text.split("\n\n"):
        lines = frame.splitlines()
        names = [line[6:].strip() for line in lines if line.startswith("event:")]
        data = [line[5:].strip() for line in lines if line.startswith("data:")]
        if names and data:
            frames.append((names[0], json.loads("\n".join(data))))
    assert frames[-1][0] == "done", frames
    return frames[-1][1]


@pytest.fixture
def reads(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "completion", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda db: [])
    monkeypatch.setattr(agent.knowledge_index, "search", lambda *args: [])
    values = {
        "schedule": {"demo": False, "items": [{"weekday": "周一", "time": "08:00", "course": "数学", "room": "A101"}]},
        "grades": {"demo": True, "items": [{"course": "数学", "score": 88, "credits": 4}]},
        "credits": {"demo": False, "earned": 4, "required": 160},
        "classrooms": {"demo": True, "items": []},
    }
    for name in values:
        def read(_name=name, **kwargs):
            calls.append(_name)
            return values[_name]
        monkeypatch.setattr(agent.services, name, read)
    return calls


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_three_ordered_reads_share_results_diagnostics_and_history(endpoint, reads):
    owner = str(uuid4())
    with TestClient(main.app) as client:
        response = client.post(endpoint, json={"message": "查询我的课表和成绩，并统计学分", "client_id": owner})
        assert response.status_code == 200, response.text
        result = terminal(response, endpoint)
        assert reads == ["schedule", "grades", "credits"]
        assert [row["name"] for row in result["tool_calls"]] == reads
        assert result["run"]["task"] == {"kind": "campus_reads", "limit_steps": 3, "planned_steps": 3,
            "attempted_steps": 3, "completed_steps": 3, "limit_ms": 20000, "stop_reason": "completed", "truncated_results": 0}
        assert result["run"]["status"] == "completed"
        assert "演示" in result["answer"] and "学校接口" in result["answer"]
        stored = client.get(f"/api/conversations/{result['conversation_id']}", params={"client_id": owner}).json()["messages"][-1]
        assert stored["run"] == result["run"]
        assert stored["content"] == result["answer"]


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_four_distinct_reads_are_rejected_without_any_service_call(endpoint, reads):
    with TestClient(main.app) as client:
        result = terminal(client.post(endpoint, json={"message": "查询成绩、课表、学分和空教室"}), endpoint)
    assert reads == []
    assert result["run"]["task"]["stop_reason"] == "step_limit"
    assert result["run"]["task"]["attempted_steps"] == 0
    assert result["run"]["status"] == "partial"


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_failed_read_keeps_other_results_without_secret_errors_or_retries(endpoint, reads, monkeypatch):
    def fail():
        reads.append("grades")
        raise HTTPException(502, "private-school-token-secret")
    monkeypatch.setattr(agent.services, "grades", fail)
    with TestClient(main.app) as client:
        result = terminal(client.post(endpoint, json={"message": "查询课表、成绩和学分"}), endpoint)
    assert reads == ["schedule", "grades", "credits"]
    assert "private-school-token-secret" not in json.dumps(result)
    assert result["run"]["status"] == "partial"
    assert result["run"]["task"]["completed_steps"] == 2
    assert result["run"]["task"]["stop_reason"] == "tool_error"


@pytest.mark.parametrize("question", ["不要查询成绩和课表", "解释成绩和课表接口的数据格式", "继续"])
def test_history_and_negative_or_document_requests_do_not_authorize_reads(question, reads):
    state = {"question": question, "history": [{"role": "user", "content": "查询我的成绩和课表"}], "requested_model": "auto"}
    assert agent.plan(state)["intent"] == "knowledge"
    assert reads == []


@pytest.mark.parametrize("disconnect_stage", ["during_read", "after_prepare"])
def test_actual_asgi_disconnect_stops_second_read_and_keeps_completed_history(reads, monkeypatch, disconnect_stage):
    started, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    class ObservedControl(ReadTaskControl):
        def cancel(self):
            super().cancel(); cancelled.set()
    monkeypatch.setattr(main, "ReadTaskControl", ObservedControl, raising=False)
    def first_read():
        reads.append("grades")
        if disconnect_stage == "during_read":
            started.set()
            assert release.wait(5), "synthetic read was not released"
        return {"demo": False, "items": [{"course": "数学", "score": 88}]}
    monkeypatch.setattr(agent.services, "grades", first_read)
    if disconnect_stage == "after_prepare":
        original_worker = main._prepare_read_stream_worker
        def held_worker(*args, **kwargs):
            result = original_worker(*args, **kwargs)
            started.set()
            assert release.wait(5)
            return result
        monkeypatch.setattr(main, "_prepare_read_stream_worker", held_worker)
    owner = str(uuid4())
    async def scenario():
        disconnected = asyncio.Event()
        body = json.dumps({"message": "查询成绩和课表", "client_id": owner}).encode()
        delivered = False
        sent = []
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            sent.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
                 "method": "POST", "scheme": "http", "path": "/api/chat/stream", "raw_path": b"/api/chat/stream",
                 "root_path": "", "query_string": b"", "http_version": "1.1", "server": ("testserver", 80),
                 "client": ("127.0.0.1", 12345), "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")]}
        request = asyncio.create_task(main.app(scope, receive, send))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            disconnected.set()
            observed = await asyncio.to_thread(cancelled.wait, 1)
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(request, return_exceptions=True), 5)
        frames = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body").decode()
        meta = next(frame for frame in frames.split("\n\n") if frame.startswith("event: meta"))
        conversation_id = json.loads(meta.split("data: ", 1)[1])["conversation_id"]
        return observed, conversation_id
    with TestClient(main.app) as client:
        observed, conversation_id = asyncio.run(scenario())
        assert observed, "disconnect did not reach the running task control"
        expected_reads = ["grades"] if disconnect_stage == "during_read" else ["grades", "schedule"]
        assert reads == expected_reads
        history = client.get(f"/api/conversations/{conversation_id}", params={"client_id": owner}).json()["messages"]
        assert len(history) == 2
        answer = history[-1]
        assert answer["partial"] is True
        assert answer["run"]["task"]["stop_reason"] == "cancelled"
        assert answer["run"]["task"]["completed_steps"] == len(expected_reads)
        assert answer["mode"] == "service"
        assert "88" in answer["content"]


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
@pytest.mark.parametrize("read_succeeds", [True, False])
def test_deadline_stops_future_reads_and_keeps_honest_outcome(endpoint, reads, monkeypatch, read_succeeds):
    from app import agent_tasks
    now = [0.0]
    class ClockControl(ReadTaskControl):
        def __init__(self):
            super().__init__(clock=lambda: now[0])
    monkeypatch.setattr(agent_tasks, "ReadTaskControl", ClockControl)
    monkeypatch.setattr(main, "ReadTaskControl", ClockControl)
    def slow_first():
        reads.append("grades"); now[0] = 21.0
        if not read_succeeds:
            raise HTTPException(502, "private-deadline-error")
        return {"demo": False, "items": [{"course": "数学", "score": 88}]}
    monkeypatch.setattr(agent.services, "grades", slow_first)
    with TestClient(main.app) as client:
        result = terminal(client.post(endpoint, json={"message": "查询成绩和课表"}), endpoint)
    assert reads == ["grades"]
    assert result["run"]["task"]["stop_reason"] == "deadline"
    assert result["run"]["status"] == ("partial" if read_succeeds else "failed")
    if read_succeeds:
        assert "88" in result["answer"]
    assert "private-deadline-error" not in json.dumps(result)
