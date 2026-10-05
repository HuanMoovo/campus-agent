"""Offline coverage for chat attachments：模型提示注入、落库文本、解析端点与校验。"""
import atexit
import json
import os
from pathlib import Path
import tempfile

_test_data = tempfile.TemporaryDirectory(prefix="campus-attach-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app.db import engine
from app.main import app, attachments_augmented
from app.schemas import ChatAttachment


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


def test_attachments_augmented_builds_fenced_blocks():
    assert attachments_augmented("问题", None) == "问题"
    assert attachments_augmented("问题", []) == "问题"
    result = attachments_augmented("看附件", [
        ChatAttachment(name="a.txt", text="内容一"),
        ChatAttachment(name="b.md", text="内容二"),
    ])
    assert result.startswith("看附件\n\n---\n以下是用户随提问附上的文件内容：")
    assert "文件：a.txt\n```\n内容一\n```" in result
    assert "文件：b.md\n```\n内容二\n```" in result


def test_stream_injects_attachment_content_but_persists_plain_question(monkeypatch):
    captured = {}

    async def fake_stream(messages, requested, local_model=None, reasoning=None):
        captured["messages"] = messages
        yield "content", "已阅读附件。"

    monkeypatch.setattr("app.main.stream_model", fake_stream)
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/stream", json={
            "message": "根据附件回答\n\n[附件] note.txt",
            "model": "qwen",
            "attachments": [{"name": "note.txt", "text": "校园卡补办在行政楼 101。"}],
        }) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
        assert "已阅读附件" in body
        joined = "\n".join(message["content"] for message in captured["messages"])
        assert "以下是用户随提问附上" in joined and "行政楼 101" in joined

        conversation_id = json.loads(body.split("event: meta\ndata: ")[1].split("\n")[0])["conversation_id"]
        history = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
        assert history[0]["content"] == "根据附件回答\n\n[附件] note.txt"
        assert "行政楼 101" not in history[0]["content"]


def test_nonstream_injects_attachment_content(monkeypatch):
    captured = {}

    def fake_run_agent(db, question, history, model, local_model=None, use_web=False, reasoning=None):
        captured["question"] = question
        return {"answer": "好的。", "sources": [], "tool_calls": [], "mode": "demo"}

    monkeypatch.setattr("app.main.run_agent", fake_run_agent)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={
            "message": "总结一下附件",
            "model": "qwen",
            "attachments": [{"name": "t.md", "text": "第二条内容"}],
        })
        assert response.status_code == 200
    assert "文件：t.md" in captured["question"] and "第二条内容" in captured["question"]


def test_attachment_validation_and_extract_endpoint():
    with TestClient(app) as client:
        too_many = {"message": "hi", "model": "qwen", "attachments": [{"name": f"{i}.txt", "text": "x"} for i in range(4)]}
        assert client.post("/api/chat", json=too_many).status_code == 422
        assert client.post("/api/chat", json={"message": "hi", "model": "qwen", "attachments": [{"name": "a.txt", "text": ""}]}).status_code == 422
        long_text = "长" * 200_001
        assert client.post("/api/chat", json={"message": "hi", "model": "qwen", "attachments": [{"name": "a.txt", "text": long_text}]}).status_code == 422

        ok = client.post("/api/chat/attachments/extract", files={"file": ("通知.txt", "补办开始时间是周一。".encode("utf-8"), "text/plain")})
        assert ok.status_code == 200
        assert ok.json()["name"] == "通知.txt" and "补办开始时间" in ok.json()["text"]

        bad = client.post("/api/chat/attachments/extract", files={"file": ("图.png", b"\x89PNG", "image/png")})
        assert bad.status_code == 400

        empty = client.post("/api/chat/attachments/extract", files={"file": ("空.md", b"   ", "text/markdown")})
        assert empty.status_code == 400
