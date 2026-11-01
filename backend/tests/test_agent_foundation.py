"""Offline regressions for request boundaries and the shared Agent execution path."""
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import agent, main
from app.db import SessionLocal
from app.models import Message


ENTRY = {"function": "mcp__campus__echo", "server": "campus", "tool": "echo",
         "description": "Echo", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
         "required": ["text"], "additionalProperties": False}}


def state(question, **extra):
    return {"question": question, "history": [], "requested_model": "auto", **extra}


def events(response):
    frames = []
    for frame in response.text.split("\n\n"):
        lines = frame.splitlines()
        names = [line[6:].strip() for line in lines if line.startswith("event:")]
        data = [line[5:].strip() for line in lines if line.startswith("data:")]
        if names and data:
            frames.append((names[0], json.loads("\n".join(data))))
    return frames


@pytest.fixture(autouse=True)
def isolated_transports(monkeypatch):
    monkeypatch.setattr(agent, "completion", lambda *args, **kwargs: None)
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda db: [])
    monkeypatch.setattr(agent.knowledge_index, "search", lambda db, question: [])


@pytest.mark.parametrize("question", ["1+1是多少", "你好", "写一个Python函数", "解释光合作用"])
def test_short_new_topic_does_not_inherit_school_context(question):
    current = state(question, history=[{"role": "user", "content": "学校学费是多少"}])
    assert agent.resolve_question(current) == question
    assert not agent.needs_campus_evidence(current)


def test_real_followup_keeps_prior_topic():
    current = state("需要什么材料？", history=[{"role": "user", "content": "如何补办校园一卡通"}])
    assert "校园一卡通" in agent.resolve_question(current)


@pytest.mark.parametrize("question", ["你好", "mcp__campus__echo 是什么？", "不要调用 mcp__campus__echo"])
def test_model_cannot_grant_itself_an_external_tool(question, monkeypatch):
    monkeypatch.setattr(agent, "completion", lambda *args, **kwargs: {
        "tool_calls": [{"function": {"name": ENTRY["function"], "arguments": '{"text":"hello"}'}}]})
    assert agent.plan(state(question, mcp_entries=[ENTRY]))["intent"] == "knowledge"


def test_model_cannot_choose_unrequested_personal_data(monkeypatch):
    monkeypatch.setattr(agent, "completion", lambda *args, **kwargs: {
        "tool_calls": [{"function": {"name": "grades", "arguments": "{}"}}]})
    assert agent.plan(state("你好"))["intent"] == "knowledge"


def test_registered_tool_invalid_parameters_do_not_execute(monkeypatch):
    monkeypatch.setattr(agent, "completion", lambda *args, **kwargs: {
        "tool_calls": [{"function": {"name": ENTRY["function"], "arguments": '{"text":123}'}}]})
    assert agent.plan(state("调用 mcp__campus__echo", mcp_entries=[ENTRY]))["intent"] == "knowledge"


def test_real_langgraph_and_stream_share_mcp_state(monkeypatch):
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda db: [ENTRY])
    monkeypatch.setattr(agent, "completion", lambda *args, **kwargs: {
        "tool_calls": [{"function": {"name": ENTRY["function"], "arguments": '{"text":"hello"}'}}]})
    monkeypatch.setattr(agent.mcp_registry, "call", lambda db, name, args: {
        "ok": True, "server": "campus", "tool": "echo", "text": "echo: hello", "error": ""})
    sync = agent.run_agent(None, "调用 mcp__campus__echo", [], "auto")
    streamed = agent.prepare_stream_state(None, "调用 mcp__campus__echo", [], "auto")["direct"]
    assert sync["answer"] == streamed["answer"]
    assert "echo: hello" in sync["answer"]
    assert sync["tool_calls"][0]["name"] == ENTRY["function"]
    assert [step["phase"] for step in sync["run"]["steps"]] == ["plan", "tool", "answer"]


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_attachment_service_words_stay_evidence_and_prompts_are_bounded(endpoint, monkeypatch):
    captured = []
    def answer(messages, *args, **kwargs):
        captured.append(messages)
        return "附件讨论了成绩焦虑。"
    async def stream(messages, *args, **kwargs):
        captured.append(messages)
        yield "content", "附件讨论了成绩焦虑。"
    monkeypatch.setattr(agent, "call_model", answer)
    monkeypatch.setattr(main, "stream_model", stream)
    with TestClient(main.app) as client:
        response = client.post(endpoint, json={"message": "请总结附件", "client_id": str(uuid4()),
            "attachments": [{"name": "notes.txt", "text": "成绩焦虑。" + "长文" * 90000 + "结尾事实。"}]})
        assert response.status_code == 200
        result = events(response)[-1][1] if endpoint.endswith("stream") else response.json()
        assert result["answer"] == "附件讨论了成绩焦虑。"
        assert result["tool_calls"] == []
        assert captured[-1][-1]["content"] == "请总结附件"
        assert sum(len(row["content"]) for row in captured[-1]) <= 24000
        assert result["context"]["attachments_truncated"] == 1
        assert result["run"]["status"] == "completed"


def test_planner_gets_no_attachment_and_has_a_smaller_budget(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "completion", lambda messages, *args, **kwargs: captured.append(messages))
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda db: [ENTRY])
    history = [{"role": role, "content": "旧对话" * 3000} for _ in range(12) for role in ("user", "assistant")]
    agent.prepare_stream_state(None, "调用 mcp__campus__echo", history, attachments=[{"name": "notes", "text": "ATTACHMENT_ONLY"}])
    assert captured[-1][-1]["content"] == "调用 mcp__campus__echo"
    assert sum(len(row["content"]) for row in captured[-1]) <= 8000
    assert "ATTACHMENT_ONLY" not in str(captured[-1])


def test_partial_stream_preserves_sources_context_and_run(monkeypatch):
    monkeypatch.setattr(agent.knowledge_index, "search", lambda db, question: [
        {"title": "校园通知", "snippet": "补办材料", "text": "补办材料", "kind": "knowledge"}])
    async def interrupted(*args, **kwargs):
        yield "content", "需要带"
        raise agent.ModelStreamError("模型响应中断")
    monkeypatch.setattr(main, "stream_model", interrupted)
    owner = str(uuid4())
    with TestClient(main.app) as client:
        response = client.post("/api/chat/stream", json={"message": "校园卡补办材料？", "client_id": owner})
        frames = events(response)
        assert frames[-1][0] == "error"
        error = frames[-1][1]
        prepared = next(data for name, data in frames if name == "status" and data["phase"] == "answering")
        assert prepared["sources"][0]["title"] == "校园通知"
        assert prepared["context"]["input_chars"] <= 24000
        assert prepared["run"]["status"] == "running"
        assert error["sources"][0]["title"] == "校园通知"
        assert error["run"]["status"] == "partial"
        cid = frames[0][1]["conversation_id"]
        row = client.get(f"/api/conversations/{cid}", params={"client_id": owner}).json()["messages"][-1]
        assert row["partial"] is True
        assert row["run"]["id"] == error["run"]["id"]
        assert row["sources"] == error["sources"]
        assert row["context"]["input_chars"] <= 24000


def test_partial_history_is_explicitly_marked_in_next_prompt(monkeypatch):
    captured = []
    monkeypatch.setattr(agent, "call_model", lambda messages, *args, **kwargs: captured.append(messages) or "正常回答")
    owner = str(uuid4())
    with TestClient(main.app) as client:
        cid = client.post("/api/chat", json={"message": "你好", "client_id": owner}).json()["conversation_id"]
        with SessionLocal() as db:
            db.add_all([Message(conversation_id=cid, role="user", content="解释一下"),
                        Message(conversation_id=cid, role="assistant", content="INTERRUPTED_CONTENT", result_data={"partial": True})])
            db.commit()
        response = client.post("/api/chat", json={"message": "继续解释", "conversation_id": cid, "client_id": owner})
        assert response.status_code == 200
    item = next(row for row in captured[-1] if "INTERRUPTED_CONTENT" in row["content"])
    assert "中断" in item["content"] or "不完整" in item["content"]
