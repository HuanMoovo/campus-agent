"""Conversation export and knowledge-base URL import.

The export endpoints mirror what the interface already shows (same title rule, same source
rows); the import endpoint must honour the web-search egress rules, so one test drives the
real fetch path with a private address to prove it is refused.
"""
import atexit
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

_test_data = tempfile.TemporaryDirectory(prefix="campus-export-test-")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix())
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("ENABLE_RAG", "false")

from fastapi.testclient import TestClient

from app.main import app
from app import web_search
from app.db import engine


def _cleanup():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup)

ADMIN = {"X-Admin-Token": "test-admin-token"}


def _seeded_conversation(client) -> str:
    response = client.post("/api/chat", json={"message": "校园一卡通补办流程是什么？"})
    assert response.status_code == 200
    return response.json()["conversation_id"]


def test_conversation_export_markdown_and_json():
    with TestClient(app) as client:
        conversation_id = _seeded_conversation(client)

        markdown = client.get(f"/api/conversations/{conversation_id}/export")
        assert markdown.status_code == 200
        assert markdown.headers["content-type"].startswith("text/markdown")
        disposition = markdown.headers["content-disposition"]
        assert "mens-conversation-" in disposition and disposition.endswith('.md"')
        assert "no-store" in markdown.headers["cache-control"]
        text = markdown.text
        assert text.startswith("# ")
        assert "## 1. 用户" in text and "## 2. 助手" in text
        assert "**参考来源**" in text                     # the demo answer cites knowledge-base passages
        assert "一卡通" in text

        payload = client.get(f"/api/conversations/{conversation_id}/export", params={"format": "json"})
        assert payload.status_code == 200
        assert payload.headers["content-disposition"].endswith('.json"')
        data = json.loads(payload.text)
        assert data["format"] == "mens-conversation/1"
        assert data["license"] == "Apache-2.0"
        assert [row["role"] for row in data["messages"]] == ["user", "assistant"]
        assert data["messages"][0]["content"].strip()
        assert data["messages"][1]["sources"] == client.get(f"/api/conversations/{conversation_id}").json()["messages"][1]["sources"]
        assert data["conversation"]["message_count"] == 2


def test_conversation_export_rejects_unknown_conversation_and_format():
    with TestClient(app) as client:
        assert client.get("/api/conversations/does-not-exist/export").status_code == 404
        conversation_id = _seeded_conversation(client)
        assert client.get(f"/api/conversations/{conversation_id}/export", params={"format": "pdf"}).status_code == 422


def test_import_url_requires_admin_https_and_a_usable_url():
    with TestClient(app) as client:
        before = len(client.get("/api/documents").json())
        assert client.post("/api/documents/import-url", json={"url": "https://example.edu/page"}).status_code == 401
        assert client.post("/api/documents/import-url", headers=ADMIN, json={"url": "http://example.edu/page"}).status_code == 422
        assert client.post("/api/documents/import-url", headers=ADMIN, json={"url": "example.edu"}).status_code == 422
        assert len(client.get("/api/documents").json()) == before


def test_import_url_stores_the_page_text_as_a_document():
    with TestClient(app) as client:
        with patch.object(web_search, "fetch_document_text", return_value=(
                "转专业申请指南", "转专业 学生须在大二第一学期提出申请，并经所在学院与接收学院同意。")):
            created = client.post("/api/documents/import-url", headers=ADMIN,
                                  json={"url": "https://example.edu/transfer"})
        assert created.status_code == 200
        document = created.json()
        assert document["title"] == "[网页] 转专业申请指南"
        stored = next(row for row in client.get("/api/documents").json() if row["id"] == document["id"])
        assert stored["content"].startswith("来源：https://example.edu/transfer")
        assert "转专业" in stored["content"]
        assert "导入时间：" in stored["content"]


def test_import_url_refuses_a_page_that_resolves_to_a_private_address():
    """Drive the real fetch path, so the egress rules are exercised rather than assumed."""
    def private_dns(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("10.255.255.7", port))]

    with TestClient(app) as client:
        before = len(client.get("/api/documents").json())
        with patch("socket.getaddrinfo", private_dns):
            response = client.post("/api/documents/import-url", headers=ADMIN,
                                   json={"url": "https://intranet.example.edu/notice"})
        assert 400 <= response.status_code < 500
        assert len(client.get("/api/documents").json()) == before


def test_import_url_rejects_pages_without_readable_text():
    with TestClient(app) as client:
        with patch.object(web_search, "fetch_document_text", return_value=("空页面", "  ")):
            response = client.post("/api/documents/import-url", headers=ADMIN,
                                   json={"url": "https://example.edu/empty"})
        assert response.status_code == 400
        assert "正文" in response.text
