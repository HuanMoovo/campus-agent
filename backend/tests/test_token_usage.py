"""Real-usage ledger isolation, nullable totals and bounded UTC summaries."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Conversation, TokenUsage
from app.token_usage import UsageIdentity, capture_usage, usage_summary
from app.schemas import ModelProviderUpdate


NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'usage.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def row(identifier, **changes):
    values = dict(id=identifier, created_at=NOW, owner_user_id=None, client_id="mine", provider="qwen",
                  model="fixture", protocol="chat_completions", operation="chat", status="completed",
                  input_tokens=10, output_tokens=5, total_tokens=15)
    values.update(changes)
    return TokenUsage(**values)


def test_nullable_fields_zero_values_partial_and_missing_reports(ledger):
    with ledger() as db:
        db.add_all([row("complete"), row("zero", input_tokens=0, output_tokens=0, total_tokens=0),
                    row("partial", input_tokens=None, output_tokens=None, total_tokens=17),
                    row("missing", input_tokens=None, output_tokens=None, total_tokens=None)])
        db.commit()
        result = usage_summary(db, UsageIdentity(None, "mine"), 7, now=NOW)
        assert result["timezone"] == "UTC"
        assert result["start_date"] == "2026-10-25" and result["end_date"] == "2026-10-31"
        assert len(result["daily"]) == 7
        assert result["totals"] == dict(requests=4, reported_requests=2, partial_requests=1, unreported_requests=1,
            input_tokens=10, output_tokens=5, total_tokens=32, cached_input_tokens=None,
            cache_creation_input_tokens=None, reasoning_tokens=None)
        assert result["daily"][0]["requests"] == 0
        assert result["daily"][0]["total_tokens"] is None
        assert result["daily"][-1]["total_tokens"] == 32
        assert result["models"][0]["provider"] == "qwen"


def test_scope_and_date_window_exclude_foreign_old_and_future_usage(ledger):
    with ledger() as db:
        db.add_all([row("mine"), row("other", client_id="other"), row("user-one", owner_user_id="one"),
                    row("user-two", owner_user_id="two", client_id="other"),
                    row("old", created_at=NOW - timedelta(days=7)),
                    row("future", created_at=NOW + timedelta(seconds=1)),
                    row("boundary", created_at=NOW.replace(hour=0) - timedelta(days=6))])
        db.commit()
        assert usage_summary(db, UsageIdentity(None, "mine"), 7, now=NOW)["totals"]["requests"] == 2
        assert usage_summary(db, UsageIdentity("one", "other"), 7, now=NOW)["totals"]["requests"] == 1
        assert usage_summary(db, UsageIdentity(None, "", desktop=True), 7, now=NOW)["totals"]["requests"] == 3


def test_capture_filters_untrusted_fields_and_does_not_cascade_with_conversations(ledger):
    # The callback transport owns one event per HTTP attempt; this collector only
    # copies its whitelisted metadata, never request content or error text.
    with capture_usage(UsageIdentity(None, "mine"), "chat", session_factory=ledger) as collector:
        collector.record(dict(provider="qwen", model="fixture", protocol="chat_completions", status="completed",
            input_tokens=10, output_tokens=0, total_tokens=10, api_key="PRIVATE", prompt="PRIVATE",
            cached_input_tokens=True, reasoning_tokens=-1, cache_creation_input_tokens=2**64))
    with ledger() as db:
        record = db.scalar(select(TokenUsage))
        assert record.input_tokens == 10 and record.output_tokens == 0
        assert record.cached_input_tokens is None and record.reasoning_tokens is None
        assert record.cache_creation_input_tokens is None
        assert "PRIVATE" not in repr(record.__dict__)
        db.add(Conversation(id="conversation", client_id="mine"))
        db.commit()
        db.execute(delete(Conversation)); db.commit()
        assert db.scalar(select(TokenUsage)) is not None


def test_collector_threaded_records_and_failure_never_change_answer(ledger):
    with capture_usage(UsageIdentity(None, "mine"), "chat", session_factory=ledger) as collector:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: collector.record(dict(provider="qwen", model="fixture", protocol="responses",
                status="completed", input_tokens=1, output_tokens=2, total_tokens=3)), range(20)))
    with ledger() as db:
        assert usage_summary(db, UsageIdentity(None, "mine"), 7)["totals"]["requests"] == 20
    def broken_session():
        raise RuntimeError("PRIVATE DATABASE URL")
    with capture_usage(UsageIdentity(None, "mine"), "chat", session_factory=broken_session) as collector:
        collector.record(dict(provider="qwen", model="fixture", protocol="responses", status="failed"))
        answer = "answer survives unavailable ledger"
    assert answer


def test_summary_limits_model_rows_without_losing_total(ledger):
    with ledger() as db:
        db.add_all(row(f"r{i}", model=f"fixture-{i:03}") for i in range(120))
        db.commit()
        result = usage_summary(db, UsageIdentity(None, "mine"), 30, now=NOW)
        assert result["totals"]["requests"] == 120
        assert len(result["models"]) <= 101
        assert sum(item["requests"] for item in result["models"]) == 120
        assert sum(item["total_tokens"] or 0 for item in result["models"]) == 1800


def test_cancelled_interim_counts_are_partial_and_other_unknown_stays_unknown(ledger):
    with ledger() as db:
        db.add_all(row(f"r{i}", model=f"fixture-{i:03}") for i in range(100))
        db.add(row("cancelled", status="cancelled", model="cancelled", input_tokens=1, output_tokens=0, total_tokens=1))
        db.add(row("missing", model="unknown", input_tokens=None, output_tokens=None, total_tokens=None))
        db.commit()
        result = usage_summary(db, UsageIdentity(None, "mine"), 7, now=NOW)
        assert result["totals"]["reported_requests"] == 100
        assert result["totals"]["partial_requests"] == 1
        assert result["totals"]["unreported_requests"] == 1
        assert result["models"][-1]["provider"] == "other"
        assert result["models"][-1]["requests"] == 2
        assert result["models"][-1]["total_tokens"] == 1
    with ledger() as db:
        db.execute(delete(TokenUsage).where(TokenUsage.id == "cancelled")); db.commit()
        result = usage_summary(db, UsageIdentity(None, "mine"), 7, now=NOW)
        assert result["models"][-1]["total_tokens"] is None


def test_pre_usage_backup_still_restores_into_additive_schema(tmp_path):
    from app.backup_archive import stage_database
    old_path, restored_path = tmp_path / "old.db", tmp_path / "restored.db"
    old = create_engine(f"sqlite:///{old_path.as_posix()}")
    Base.metadata.create_all(old, tables=[table for table in Base.metadata.sorted_tables if table.name != "token_usage"])
    old.dispose()
    stage_database(old_path, restored_path, Base.metadata)
    restored = create_engine(f"sqlite:///{restored_path.as_posix()}")
    assert "token_usage" in inspect(restored).get_table_names()
    with Session(restored) as db:
        assert db.scalar(select(TokenUsage)) is None
    restored.dispose()


@pytest.mark.parametrize("value", [None, "true", 0, 1, [], {}])
def test_stream_usage_preference_rejects_coerced_or_null_values(value):
    with pytest.raises(ValidationError):
        ModelProviderUpdate(request_options={"stream_usage": value})


@pytest.mark.parametrize("value", [True, False])
def test_stream_usage_preference_accepts_only_explicit_booleans(value):
    assert ModelProviderUpdate(request_options={"stream_usage": value}).request_options.stream_usage is value
