"""Avoid model planning when the authorized route is already deterministic."""
from unittest.mock import Mock

import pytest

from app import agent


ENTRY = {"function": "mcp__campus__echo", "server": "campus", "tool": "echo", "description": "Echo",
         "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                         "required": ["text"], "additionalProperties": False}}


def state(question, **extra):
    return {"question": question, "history": [], "requested_model": "auto", **extra}


@pytest.mark.parametrize("question", ["你好", "请总结附件", "不要查询成绩", "成绩是什么"])
def test_zero_tool_questions_do_not_call_the_planner_model(question, monkeypatch):
    planner = Mock(return_value=None)
    monkeypatch.setattr(agent, "completion", planner)
    result = agent.plan(state(question))
    assert result["intent"] == "knowledge"
    assert result["context"]["input_chars"] <= 8000
    planner.assert_not_called()


@pytest.mark.parametrize("question,intent,arguments", [
    ("查询我的成绩", "grades", {}),
    ("查询我的课表", "schedule", {}),
    ("查教学楼A至少50座的空教室", "classrooms", {"building": "教学楼A", "min_seats": 50}),
])
def test_explicit_builtin_plans_use_current_request_arguments_without_a_model(question, intent, arguments, monkeypatch):
    planner = Mock(return_value=None)
    monkeypatch.setattr(agent, "completion", planner)
    result = agent.plan(state(question))
    assert result["intent"] == intent
    assert result["arguments"] == arguments
    planner.assert_not_called()


def test_explicit_external_tool_still_uses_bounded_argument_planning(monkeypatch):
    planner = Mock(return_value={"tool_calls": [{"function": {"name": ENTRY["function"], "arguments": '{"text":"hello"}'}}]})
    monkeypatch.setattr(agent, "completion", planner)
    result = agent.plan(state("调用 mcp__campus__echo", mcp_entries=[ENTRY], attachments=[{"name": "x", "text": "PRIVATE_ATTACHMENT"}]))
    assert result["intent"] == ENTRY["function"]
    assert result["arguments"] == {"text": "hello"}
    assert planner.call_count == 1
    messages = planner.call_args.args[0]
    assert "PRIVATE_ATTACHMENT" not in str(messages)
    assert sum(len(row["content"]) for row in messages) <= 8000


def test_ordinary_answer_uses_one_completion_instead_of_discarding_an_extra_reply(monkeypatch):
    completion = Mock(return_value={"content": "正常回答", "tool_calls": []})
    monkeypatch.setattr(agent, "completion", completion)
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda db: [])
    monkeypatch.setattr(agent.knowledge_index, "search", lambda *args: [])
    result = agent.run_agent(None, "解释二分查找", [])
    assert result["answer"] == "正常回答"
    assert completion.call_count == 1
