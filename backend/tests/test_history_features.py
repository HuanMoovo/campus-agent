"""Offline coverage for history management：重命名 / 置顶 / 批量删除 / 全文检索 / 列迁移。"""
import atexit
import os
from pathlib import Path
import tempfile
from uuid import uuid4

_test_data = tempfile.TemporaryDirectory(prefix="campus-history-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.db import Base, SessionLocal, engine, ensure_conversation_columns
from app.main import app, persist_stream_exchange
from app.models import Conversation

# 直接建表，便于在 TestClient 生命周期之外先落种子数据。
Base.metadata.create_all(bind=engine)


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


def _seed(client_id: str, question: str, answer: str) -> str:
    conversation_id = str(uuid4())
    with SessionLocal() as db:
        db.add(Conversation(id=conversation_id, client_id=client_id))
        db.commit()
    persist_stream_exchange(conversation_id, question, answer, None, "", streamed_from_model=True)
    return conversation_id


def test_rename_and_pin_roundtrip():
    conversation_id = _seed("hist-user", "图书馆几点开门？", "八点。")
    with TestClient(app) as client:
        listed = client.get("/api/conversations?client_id=hist-user").json()
        assert listed[0]["title"] == "图书馆几点开门？" and listed[0]["pinned"] is False

        response = client.patch(f"/api/conversations/{conversation_id}?client_id=hist-user", json={"title": "  我的图书馆问题  "})
        assert response.status_code == 200 and response.json()["title"] == "我的图书馆问题"
        assert client.get("/api/conversations?client_id=hist-user").json()[0]["title"] == "我的图书馆问题"

        assert client.patch(f"/api/conversations/{conversation_id}?client_id=hist-user", json={"pinned": True}).status_code == 200
        assert client.get("/api/conversations?client_id=hist-user").json()[0]["pinned"] is True

        # 空字符串恢复默认标题
        assert client.patch(f"/api/conversations/{conversation_id}?client_id=hist-user", json={"title": ""}).json()["title"] is None
        assert client.get("/api/conversations?client_id=hist-user").json()[0]["title"] == "图书馆几点开门？"

        # 错误 client / 缺字段 / 超长标题
        assert client.patch(f"/api/conversations/{conversation_id}?client_id=someone-else", json={"title": "x"}).status_code == 404
        assert client.patch(f"/api/conversations/{conversation_id}?client_id=hist-user", json={}).status_code == 422
        assert client.patch(f"/api/conversations/{conversation_id}?client_id=hist-user", json={"title": "长" * 121}).status_code == 422


def test_pinned_sorts_first():
    older = _seed("pin-user", "旧问题", "旧回答")
    newer = _seed("pin-user", "新问题", "新回答")
    with TestClient(app) as client:
        listed = client.get("/api/conversations?client_id=pin-user").json()
        assert [item["id"] for item in listed][0] == newer
        client.patch(f"/api/conversations/{older}?client_id=pin-user", json={"pinned": True})
        listed = client.get("/api/conversations?client_id=pin-user").json()
        assert [item["id"] for item in listed][:2] == [older, newer]


def test_batch_delete_only_own():
    first = _seed("batch-a", "问题一", "回答一")
    second = _seed("batch-a", "问题二", "回答二")
    foreign = _seed("batch-b", "别人的问题", "别人的回答")
    with TestClient(app) as client:
        response = client.post("/api/conversations/batch-delete", json={"ids": [first, second, foreign, "missing"], "client_id": "batch-a"})
        assert response.status_code == 200 and response.json() == {"deleted": 2}
        assert client.get("/api/conversations?client_id=batch-a").json() == []
        assert len(client.get("/api/conversations?client_id=batch-b").json()) == 1
        assert client.post("/api/conversations/batch-delete", json={"ids": [], "client_id": "batch-a"}).status_code == 422


def test_search_matches_chinese_and_escapes_like_wildcards():
    target = _seed("search-user", "补办一卡通需要什么材料？", "需要学生证和照片。")
    _seed("search-user", "课表在哪里看？", "在教务系统里查看 Python 课表。")
    discount = _seed("search-user", "学费折扣说明", "在 9 月前缴费可享 50% 优惠。")
    _seed("search-other", "补办一卡通", "别人的回答。")
    with TestClient(app) as client:
        found = client.get("/api/conversations/search", params={"client_id": "search-user", "q": "一卡通"}).json()
        assert [item["conversation_id"] for item in found] == [target]
        assert "一卡通" in found[0]["snippet"]

        found = client.get("/api/conversations/search", params={"client_id": "search-user", "q": "python"}).json()
        assert found and found[0]["matches"] >= 1  # 大小写不敏感（ASCII）

        found = client.get("/api/conversations/search", params={"client_id": "search-user", "q": "%"}).json()
        assert [item["conversation_id"] for item in found] == [discount]  # 通配符按字面义转义

        assert client.get("/api/conversations/search", params={"client_id": "search-user", "q": ""}).status_code == 422


def test_ensure_columns_adds_to_legacy_table():
    legacy = create_engine("sqlite:///" + (Path(_test_data.name) / "legacy.db").as_posix())
    with legacy.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, created_at DATETIME)")
    ensure_conversation_columns(legacy)
    columns = {column["name"] for column in inspect(legacy).get_columns("conversations")}
    assert {"client_id", "title", "pinned"} <= columns
    ensure_conversation_columns(legacy)  # 幂等：重复调用不报错
    legacy.dispose()
