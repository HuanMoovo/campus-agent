"""Real session-cookie ownership checks and migration of existing conversations."""
import atexit
import os
from pathlib import Path
import tempfile
from uuid import uuid4

_test_data = tempfile.TemporaryDirectory(prefix="mens-conversation-auth-")
_test_dir = Path(_test_data.name)
_test_config = _test_dir / "empty.env"
_test_config.write_text("", encoding="utf-8")
os.environ["CAMPUS_CONFIG_FILE"] = str(_test_config)
os.environ["CAMPUS_DATA_DIR"] = str(_test_dir)
os.environ["DATABASE_URL"] = "sqlite:///" + (_test_dir / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["AUTH_REQUIRED"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["WEB_SEARCH_ENABLED"] = "false"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app import auth, db as db_module, main
from app.models import Conversation


def _cleanup_test_database():
    db_module.engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)


def test_real_login_cookies_enforce_conversation_ownership(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'users.db').as_posix()}",
                           connect_args={"check_same_thread": False})
    db_module.Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", sessions)
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "desktop_enabled", lambda: False)
    # The test exercises authentication and persistence, not a real model provider.
    monkeypatch.setattr(main, "run_agent", lambda *args, **kwargs: {
        "answer": "测试回答", "sources": [], "tool_calls": [], "mode": "demo"})
    original_setting = auth.setting
    monkeypatch.setattr(auth, "setting", lambda name, default: True if name == "auth_required" else
                        False if name == "cookie_secure" else original_setting(name, default))
    auth._attempts.clear()
    with sessions() as db:
        auth.create_user(db, "alice", "alice-password-1")
        auth.create_user(db, "bob", "bob-password-123")
        legacy = str(uuid4())
        db.add(Conversation(id=legacy, client_id="alice-browser"))
        db.commit()
    try:
        alice, bob = TestClient(main.app), TestClient(main.app)
        for client, username, password in ((alice, "alice", "alice-password-1"),
                                            (bob, "bob", "bob-password-123")):
            response = client.post("/api/auth/login", json={"username": username, "password": password})
            assert response.status_code == 200
            assert auth.COOKIE_NAME in client.cookies
        created = alice.post("/api/chat", json={"message": "查询我的课表", "client_id": "alice-browser"})
        assert created.status_code == 200
        cid = created.json()["conversation_id"]
        history = alice.get(f"/api/conversations/{cid}", params={"client_id": "alice-browser"})
        assert history.status_code == 200
        message_id = history.json()["messages"][-1]["id"]
        assert cid not in {row["id"] for row in bob.get("/api/conversations", params={"client_id": "alice-browser"}).json()}
        assert cid not in {row["conversation_id"] for row in bob.get("/api/conversations/search", params={"client_id": "alice-browser", "q": "课表"}).json()}
        assert bob.get(f"/api/conversations/{cid}", params={"client_id": "alice-browser"}).status_code == 404
        assert bob.get(f"/api/conversations/{cid}/export", params={"client_id": "alice-browser"}).status_code == 404
        assert bob.post(f"/api/conversations/{cid}/messages/{message_id}/feedback", params={"client_id": "alice-browser"}, json={"value": "up"}).status_code == 404
        for endpoint in ("/api/chat", "/api/chat/stream"):
            attempt = bob.post(endpoint, json={"message": "查询我的课表", "conversation_id": cid,
                                                "client_id": "alice-browser", "regenerate": True})
            assert attempt.status_code == 404
        assert bob.delete(f"/api/conversations/{cid}", params={"client_id": "alice-browser"}).status_code == 404
        assert bob.post("/api/conversations/batch-delete", json={"ids": [cid], "client_id": "alice-browser"}).json()["deleted"] == 0
        assert alice.get(f"/api/conversations/{legacy}", params={"client_id": "alice-browser"}).status_code == 404
        assert alice.post("/api/chat", json={"message": "课程", "conversation_id": legacy,
                                              "client_id": "alice-browser"}).status_code == 404
        with sessions() as db:
            assert db.scalar(select(Conversation).where(Conversation.id == legacy)).owner_user_id is None
    finally:
        auth._attempts.clear()
        engine.dispose()


def test_owner_column_migration_preserves_legacy_data_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, client_id VARCHAR(64) NOT NULL DEFAULT '')")
        connection.exec_driver_sql("INSERT INTO conversations (id, client_id) VALUES ('old-1', 'browser-1')")
    try:
        db_module.ensure_conversation_columns(engine)
        db_module.ensure_conversation_columns(engine)
        assert "owner_user_id" in {column["name"] for column in inspect(engine).get_columns("conversations")}
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT client_id, owner_user_id FROM conversations WHERE id = 'old-1'").one() == ("browser-1", None)
        assert "ix_conversations_owner_user_id" in {index["name"] for index in inspect(engine).get_indexes("conversations")}
    finally:
        engine.dispose()
