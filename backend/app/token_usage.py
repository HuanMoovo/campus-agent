"""Scoped, content-free usage persistence and bounded UTC dashboard queries."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
from uuid import uuid4

from sqlalchemy import and_, case, func, select, tuple_

from .db import SessionLocal
from .models import TokenUsage
from .model_usage import track_usage


logger = logging.getLogger(__name__)
TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
                "cache_creation_input_tokens", "reasoning_tokens")
COUNT_FIELDS = ("requests", "reported_requests", "partial_requests", "unreported_requests")
MODEL_LIMIT = 100


@dataclass(frozen=True)
class UsageIdentity:
    owner_user_id: str | None
    client_id: str
    desktop: bool = False

    def scope(self):
        if self.owner_user_id is not None:
            return TokenUsage.owner_user_id == self.owner_user_id
        if self.desktop:
            return TokenUsage.owner_user_id.is_(None)
        return and_(TokenUsage.owner_user_id.is_(None), TokenUsage.client_id == self.client_id)


def _count(value):
    # SQLite accepts arbitrary sized ints until bind time; PostgreSQL INTEGER
    # does not. Invalid upstream counts remain unknown across both databases.
    return value if type(value) is int and 0 <= value <= 2**31 - 1 else None


class UsageCollector:
    def __init__(self, identity, operation, session_factory):
        self.identity = identity
        self.operation = operation
        self.session_factory = session_factory
        self._events = []
        self._lock = threading.Lock()

    def record(self, event):
        if not isinstance(event, dict):
            return
        values = {name: _count(event.get(name)) for name in TOKEN_FIELDS}
        # Whitelist only bounded model metadata; no input/output, credentials,
        # endpoint, headers or provider error payload can enter this table.
        values.update({name: str(event.get(name, ""))[:limit] for name, limit in
                       (("provider", 64), ("model", 128), ("protocol", 32))})
        values.update(id=str(uuid4()), created_at=datetime.now(timezone.utc),
                      owner_user_id=self.identity.owner_user_id,
                      client_id="" if self.identity.desktop else self.identity.client_id,
                      operation=self.operation[:32],
                      status=event.get("status") if event.get("status") in {"completed", "failed", "cancelled"} else "failed")
        with self._lock:
            self._events.append(values)

    def flush(self):
        with self._lock:
            events, self._events = self._events, []
        if not events:
            return
        try:
            with self.session_factory() as db:
                db.add_all(TokenUsage(**event) for event in events)
                db.commit()
        except Exception:
            # Usage diagnostics must never replace an otherwise valid answer.
            # Do not log exception text: database URLs may include credentials.
            logger.warning("Token usage could not be saved")


@contextmanager
def capture_usage(identity: UsageIdentity, operation: str, *, session_factory=None):
    collector = UsageCollector(identity, operation, session_factory or SessionLocal)
    try:
        with track_usage(collector.record):
            yield collector
    finally:
        collector.flush()


def _empty():
    return {**{name: 0 for name in COUNT_FIELDS}, **{name: None for name in TOKEN_FIELDS}}


def _measures():
    complete = and_(TokenUsage.status == "completed",
                    *(getattr(TokenUsage, name).is_not(None) for name in TOKEN_FIELDS[:3]))
    any_report = ~and_(*(getattr(TokenUsage, name).is_(None) for name in TOKEN_FIELDS))
    return [func.count().label("requests"),
            func.sum(case((complete, 1), else_=0)).label("reported_requests"),
            func.sum(case((and_(~complete, any_report), 1), else_=0)).label("partial_requests"),
            func.sum(case((~any_report, 1), else_=0)).label("unreported_requests"),
            *(func.sum(getattr(TokenUsage, name)).label(name) for name in TOKEN_FIELDS)]


def _values(row):
    return {name: int(row[name] or 0) for name in COUNT_FIELDS} | {
        name: int(row[name]) if row[name] is not None else None for name in TOKEN_FIELDS}


def usage_summary(db, identity: UsageIdentity, days: int, *, now=None):
    if days not in (7, 30):
        raise ValueError("Usage period must be 7 or 30 days")
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    today = now.date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)
    where = and_(identity.scope(), TokenUsage.created_at >= start, TokenUsage.created_at <= now)
    totals = _values(db.execute(select(*_measures()).where(where)).mappings().one())
    utc_created = (func.timezone("UTC", TokenUsage.created_at)
                   if db.get_bind().dialect.name == "postgresql" else TokenUsage.created_at)
    day = func.date(utc_created)
    by_day = {str(row["date"]): _values(row) for row in db.execute(
        select(day.label("date"), *_measures()).where(where).group_by(day)).mappings()}
    daily = [{"date": (first + timedelta(days=i)).isoformat(),
              **by_day.get((first + timedelta(days=i)).isoformat(), _empty())} for i in range(days)]
    grouped = select(TokenUsage.provider, TokenUsage.model, *_measures()).where(where).group_by(TokenUsage.provider, TokenUsage.model)
    # One total row, at most 30 day rows and 100 displayed model rows. A grouped
    # remainder retains each field's nullability without hydrating all events.
    grouped = grouped.order_by(func.coalesce(func.sum(TokenUsage.total_tokens), -1).desc(),
        func.count().desc(), TokenUsage.provider.asc(), TokenUsage.model.asc()).limit(MODEL_LIMIT)
    models = [{"provider": row["provider"], "model": row["model"], **_values(row)}
              for row in db.execute(grouped).mappings()]
    if sum(row["requests"] for row in models) < totals["requests"]:
        remainder = db.execute(select(*_measures()).where(where, ~tuple_(TokenUsage.provider, TokenUsage.model).in_(
            [(row["provider"], row["model"]) for row in models]))).mappings().one()
        models.append({"provider": "other", "model": "", **_values(remainder)})
    return {"days": days, "timezone": "UTC", "start_date": first.isoformat(), "end_date": today.isoformat(),
            "totals": totals, "daily": daily, "models": models}
