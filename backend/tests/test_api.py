import atexit
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

_test_data = tempfile.TemporaryDirectory(prefix="campus-api-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app.main import app
from app.db import engine


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


def test_health_and_chat_sources():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        response = client.post("/api/chat", json={"message": "校园一卡通补办流程是什么？"})
        assert response.status_code == 200
        data = response.json()
        assert data["sources"]
        assert "演示" in data["answer"]
        history = client.get(f"/api/conversations/{data['conversation_id']}").json()
        assert [row["role"] for row in history["messages"]] == ["user", "assistant"]
        assert history["messages"][-1]["sources"] == data["sources"]


def test_service_route_and_repair_validation():
    with TestClient(app) as client:
        answer = client.post("/api/chat", json={"message": "查询我的课表"}).json()
        assert answer["tool_calls"][0]["name"] == "schedule"
        assert answer["mode"] == "demo"
        assert client.get("/api/services/classrooms", params={"min_seats": 50}).json()["items"]
        assert client.post("/api/services/repairs", json={"location": "A1", "issue": "灯具无法正常点亮", "contact": "test@example.edu"}).status_code == 200
        assert client.post("/api/services/repairs", json={"location": "A", "issue": "坏了", "contact": "x"}).status_code == 422


def test_admin_document_lifecycle():
    with TestClient(app) as client:
        assert client.post("/api/documents", json={"title": "t", "content": "abc"}).status_code == 401
        headers = {"X-Admin-Token": "test-admin-token"}
        title = f"测试文档-{uuid4()}"
        created = client.post("/api/documents", headers=headers, json={"title": title, "content": "测试内容"})
        assert created.status_code == 200
        document_id = created.json()["id"]
        updated = client.put(f"/api/documents/{document_id}/upload", headers=headers, files={"file": ("update.txt", b"updated content", "text/plain")})
        assert updated.status_code == 200
        assert updated.json()["content"] == "updated content"
        assert client.delete(f"/api/documents/{document_id}", headers=headers).status_code == 200
        assert client.delete(f"/api/documents/{document_id}", headers=headers).status_code == 404


def test_blank_input_and_invalid_model_are_rejected():
    with TestClient(app) as client:
        headers = {"X-Admin-Token": "test-admin-token"}
        assert client.post("/api/chat", json={"message": "   \n\t"}).status_code == 422
        assert client.post("/api/chat", json={"message": "hello", "model": "unknown"}).status_code == 422
        assert client.post("/api/documents", headers=headers, json={"title": "  ", "content": "content"}).status_code == 422
        assert client.post("/api/services/repairs", json={"location": "  ", "issue": "     ", "contact": "  "}).status_code == 422


def test_plugin_manifest_and_patch_validation():
    with TestClient(app) as client:
        headers = {"X-Admin-Token": "test-admin-token"}
        manifest = {"name": "test_plugin", "description": "test", "url": "https://plugins.example.edu/data",
                    "parameters": {"type": "object", "properties": {"payload": {"type": "object"}}}}
        assert client.post("/api/plugins", headers=headers, json=manifest).status_code == 422
        assert client.patch("/api/plugins/unknown", headers=headers, json={"enabled": None}).status_code == 422
        assert client.patch("/api/plugins/unknown", headers=headers, json={"description": "   "}).status_code == 422


def test_index_failure_is_reported_without_duplicate_retry_signal():
    with TestClient(app) as client:
        headers = {"X-Admin-Token": "test-admin-token"}
        with patch("app.main.knowledge_index.index", side_effect=RuntimeError("index unavailable")):
            response = client.post("/api/documents", headers=headers, json={"title": "索引失败测试", "content": "已经保存的文档"})
        assert response.status_code == 200
        assert response.json()["index_status"] == "pending"
        document_id = response.json()["id"]
        assert any(doc["id"] == document_id for doc in client.get("/api/documents").json())
        assert client.delete(f"/api/documents/{document_id}", headers=headers).status_code == 200


def test_unsupported_and_empty_uploads_are_rejected():
    with TestClient(app) as client:
        headers = {"X-Admin-Token": "test-admin-token"}
        assert client.post("/api/documents/upload", headers=headers, files={"file": ("bad.exe", b"data")}).status_code == 400
        assert client.post("/api/documents/upload", headers=headers, files={"file": ("empty.txt", b"   ")}).status_code == 400


def test_chat_model_switch_is_request_scoped_and_preserves_history():
    with TestClient(app) as client:
        seen = []

        def answer(db, question, history, model, local_model=None):
            seen.append((model, local_model, history))
            return {"answer": local_model, "mode": "llm", "sources": []}

        with patch("app.main.resolve_local_model", side_effect=lambda name: name), patch("app.main.run_agent", side_effect=answer):
            first = client.post("/api/chat", json={"message": "你好", "model": "ollama", "local_model": "first:latest"})
            assert first.status_code == 200
            second = client.post("/api/chat", json={"message": "继续", "model": "ollama", "local_model": "second:latest",
                                                   "conversation_id": first.json()["conversation_id"]})
            assert second.status_code == 200
        assert [(row[0], row[1]) for row in seen] == [("ollama", "first:latest"), ("ollama", "second:latest")]
        assert seen[1][2] == [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "first:latest"}]


def test_local_model_failure_does_not_save_failed_messages():
    from app.model_runtime import LocalModelError

    with TestClient(app) as client:
        initial = client.post("/api/chat", json={"message": "你好"}).json()
        conversation_id = initial["conversation_id"]
        with patch("app.main.resolve_local_model", return_value="custom:latest"), patch("app.main.run_agent", side_effect=LocalModelError("本地模型暂不可用", 502)):
            failed = client.post("/api/chat", json={"message": "不应写入", "model": "ollama", "local_model": "custom:latest",
                                                   "conversation_id": conversation_id})
        assert failed.status_code == 502
        history = client.get(f"/api/conversations/{conversation_id}").json()
        assert len(history["messages"]) == 2
        with patch("app.main.resolve_local_model", side_effect=LocalModelError("模型尚未安装", 409)), patch("app.main.run_agent") as run:
            failed = client.post("/api/chat", json={"message": "hello", "model": "ollama", "local_model": "missing:latest"})
        assert failed.status_code == 409
        run.assert_not_called()
