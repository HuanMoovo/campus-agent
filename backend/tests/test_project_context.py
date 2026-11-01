"""Explicit project evidence always stays separate from personal-service intent."""
import pytest

from app import agent


SOURCE = {"title": "src/grades.py:L1-L2", "path": "src/grades.py", "kind": "project",
          "snippet": "# 查询我的成绩\nAPI_VALUE = 42", "text": "# 查询我的成绩\nAPI_VALUE = 42",
          "start_line": 1, "end_line": 2, "truncated": False, "excerpt_sha256": "a" * 64}


@pytest.mark.parametrize("streaming", [False, True])
def test_project_question_does_not_query_personal_services_or_mcp(monkeypatch, streaming):
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda *args: pytest.fail("Project context must not enumerate MCP"))
    monkeypatch.setattr(agent.knowledge_index, "search", lambda *args: pytest.fail("Project context must not read campus knowledge"))
    monkeypatch.setattr(agent.services, "grades", lambda *args: pytest.fail("Project context must not query grades"))
    captured = []
    def answer(messages, *args, **kwargs):
        captured.extend(messages)
        return "项目中的 API_VALUE 为 42。[1]"
    monkeypatch.setattr(agent, "call_model", answer)
    if streaming:
        result = agent.prepare_stream_state(None, "解释这个成绩模块", [], project_sources=[dict(SOURCE)])
        assert "direct" not in result
        captured.extend(result["messages"])
    else:
        result = agent.run_agent(None, "解释这个成绩模块", [], project_sources=[dict(SOURCE)])
        assert result["tool_calls"] == []
    text = "\n".join(item["content"] for item in captured)
    assert "src/grades.py:L1-L2" in text and "API_VALUE = 42" in text
    assert "数据" in text
    assert result["sources"][0]["kind"] == "project"
    assert result["sources"][0]["path"] == "src/grades.py"


def test_offline_project_answer_is_labeled_as_file_excerpt(monkeypatch):
    monkeypatch.setattr(agent, "call_model", lambda *args: None)
    result = agent.run_agent(None, "解释文件", [], project_sources=[dict(SOURCE)])
    assert "项目文件" in result["answer"]
    assert "API_VALUE" in result["answer"]
    assert result["mode"] == "demo"


def test_project_prompt_marks_upstream_or_file_truncation(monkeypatch):
    state = {"question": "解释文件", "sources": [{**SOURCE, "text": "line\n" * 6000}], "history": []}
    messages = agent.knowledge_messages(state)
    assert state["context"]["trimmed"] is True
    assert "截断" in "\n".join(row["content"] for row in messages)


def test_final_prompt_project_excerpt_has_matching_contiguous_lines_and_fingerprint():
    import hashlib
    from app.agent_context import build_prompt
    text = "".join(f"line-{index:04d}\n" for index in range(1, 701))
    source = {**SOURCE, "title": "app.py:L1-L700", "path": "app.py", "text": text, "snippet": text,
              "end_line": 700, "truncated": False, "excerpt_sha256": hashlib.sha256(text.encode()).hexdigest()}
    prompt = build_prompt("Read project", "explain", [], [source])
    sent = prompt.sources[0]
    assert sent["truncated"] is True
    assert text.startswith(sent["text"]) and len(sent["text"]) < len(text)
    assert sent["snippet"] == sent["text"]
    assert sent["excerpt_sha256"] == hashlib.sha256(sent["text"].encode()).hexdigest()
    assert sent["end_line"] == len(sent["text"].splitlines())
    assert sent["title"] == f"app.py:L1-L{sent['end_line']}"
    assert sent["text"] in prompt.messages[0]["content"]
    assert "line-0700" not in prompt.messages[0]["content"]
    assert source["text"] == text and source["truncated"] is False


def test_file_read_truncation_is_disclosed_even_if_prompt_budget_does_not_trim_it():
    from app.agent_context import build_prompt
    source = {**SOURCE, "truncated": True}
    result = build_prompt("Read project", "explain", [], [source])
    assert result.report["trimmed"] is True
    assert result.sources[0]["truncated"] is True
    assert "截断" in result.messages[0]["content"]
