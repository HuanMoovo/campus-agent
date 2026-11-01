"""History pagination preserves summaries without materializing answer payloads."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import main
from app.db import Base
from app.models import Conversation, Message


@pytest.fixture
def history_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main.auth, "setting", lambda *_args: False)
    with Session(engine) as db:
        yield db, engine
    engine.dispose()


def listing(db, client="mine", limit=50):
    return main.list_conversations(Request({"type": "http"}), db, client, limit)


def test_page_uses_two_queries_without_answer_or_result_payloads(history_db, monkeypatch):
    db, engine = history_db
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(80):
        db.add(Conversation(id=f"c{i:03}", client_id="mine", created_at=when))
        for j in range(6):
            db.add(Message(conversation_id=f"c{i:03}", role="user" if j % 2 == 0 else "assistant",
                           content=f"Question {i}" if j == 0 else "x" * 8192,
                           result_data={"thinking": "y" * 8192}, created_at=when + timedelta(seconds=i)))
    db.commit()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cur, sql, _p, _ctx, _many: statements.append(sql))
    projections = []
    execute = db.execute
    def record_projection(*args, **kwargs):
        frozen = execute(*args, **kwargs).freeze()
        projections.extend(frozen().all())
        return frozen()
    monkeypatch.setattr(db, "execute", record_projection)
    result = listing(db, limit=5)
    assert [item["id"] for item in result] == ["c079", "c078", "c077", "c076", "c075"]
    assert len(statements) <= 2, "A page must not issue one message query per conversation"
    assert all("result_data" not in sql.lower() for sql in statements)
    assert len(projections) <= 10, "Only page metadata and one title prefix per page row may be returned"
    payload = sum(len(value.encode("utf-8") if isinstance(value, str) else value)
                  for row in projections for value in row if isinstance(value, (str, bytes)))
    assert payload < 1000, "A sidebar page must not fetch complete question/answer bodies"
    assert not db.identity_map, "Sidebar projection must not hydrate conversations or messages"


def test_page_preserves_title_latest_id_pin_empty_and_profile_scope(history_db):
    db, _ = history_db
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    specs = [
        ("a-pinned", "mine", None, True, None),
        ("b-custom", "mine", None, False, "Explicit title"),
        ("c-unicode", "mine", None, False, None),
        ("d-assistant", "mine", None, False, None),
        ("empty", "mine", None, True, None),
        ("foreign", "other", None, True, None),
        ("owned", "mine", "user-one", True, None),
        ("legacy", "", None, False, None),
    ]
    for identifier, client, owner, pinned, title in specs:
        db.add(Conversation(id=identifier, client_id=client, owner_user_id=owner, pinned=pinned,
                            title=title, created_at=when))
    for identifier, content, role, offset in [
        ("a-pinned", "Pinned", "user", -10),
        ("b-custom", "Ignored", "user", 100),
        ("b-custom", "Last id controls activity", "assistant", 30),
        ("c-unicode", "\u2003\u3000\t\x1c", "user", 0),
        ("c-unicode", "\u2003First line\u2028Second line", "user", 20),
        ("d-assistant", "Answer only", "assistant", 10),
        ("foreign", "private", "user", 1000),
        ("owned", "private", "user", 1000),
        ("legacy", "legacy", "user", 0),
    ]:
        db.add(Message(conversation_id=identifier, content=content, role=role,
                       created_at=when + timedelta(seconds=offset)))
    db.commit()
    assert listing(db, limit=4) == [
        {"id": "a-pinned", "title": "Pinned", "message_count": 1,
         "updated_at": "2025-12-31T23:59:50+00:00", "pinned": True},
        {"id": "b-custom", "title": "Explicit title", "message_count": 2,
         "updated_at": "2026-01-01T00:00:30+00:00", "pinned": False},
        {"id": "c-unicode", "title": "First line", "message_count": 2,
         "updated_at": "2026-01-01T00:00:20+00:00", "pinned": False},
        {"id": "d-assistant", "title": "新对话", "message_count": 1,
         "updated_at": "2026-01-01T00:00:10+00:00", "pinned": False},
    ]
    assert [item["id"] for item in listing(db, client="")] == ["legacy"]


def test_authenticated_scope_filters_before_limit(history_db, monkeypatch):
    db, _ = history_db
    monkeypatch.setattr(main.auth, "setting", lambda *_args: True)
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for identifier, owner in [("foreign", "them"), ("owned", "me")]:
        db.add(Conversation(id=identifier, client_id="shared", owner_user_id=owner,
                            pinned=identifier == "foreign", created_at=when))
        db.add(Message(conversation_id=identifier, role="user", content=identifier, created_at=when))
    db.commit()
    request = Request({"type": "http"})
    from types import SimpleNamespace
    request.state.user = SimpleNamespace(id="me")
    result = main.list_conversations(request, db, "shared", 1)
    assert [item["id"] for item in result] == ["owned"]


def test_equal_activity_pages_use_stable_id_order(history_db):
    db, _ = history_db
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for identifier in ["c", "b", "a"]:
        db.add(Conversation(id=identifier, client_id="mine", created_at=when))
        db.add(Message(conversation_id=identifier, role="user", content=identifier, created_at=when))
    db.commit()
    assert [item["id"] for item in listing(db, limit=2)] == ["a", "b"]


@pytest.mark.parametrize("content,title", [
    ("\u3000" + "长" * 50 + "\nsecond", "长" * 40),
    (" \t\n\v\f\r\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000", "新对话"),
    ("\u200bzero width is text", "\u200bzero width is text"),
    ("Start\x85later", "Start"),
    ("\x00Start\nLater", "\x00Start"),
])
def test_title_prefix_preserves_python_unicode_strip_and_splitlines(history_db, content, title):
    db, _ = history_db
    db.add(Conversation(id="title", client_id="mine"))
    db.add(Message(conversation_id="title", role="user", content=content))
    db.commit()
    assert listing(db)[0]["title"] == title


def test_legacy_null_last_timestamp_uses_conversation_timestamp():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE conversations (id TEXT PRIMARY KEY, client_id TEXT, owner_user_id TEXT, title TEXT, pinned BOOLEAN, created_at DATETIME)")
        connection.exec_driver_sql("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO conversations VALUES ('legacy', '', NULL, NULL, 0, '2026-01-01 00:00:00')")
        connection.exec_driver_sql("INSERT INTO messages VALUES (1, 'legacy', 'user', 'Legacy title', NULL)")
    from app.history_queries import list_conversation_page
    with Session(engine) as db:
        assert list_conversation_page(db, Conversation.client_id == "", 1)[0]["updated_at"] == "2026-01-01T00:00:00+00:00"
    engine.dispose()
