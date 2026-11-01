"""Bounded sidebar projections; authorization remains with the route's scope."""
from datetime import timezone

from sqlalchemy import LargeBinary, cast, func, select
from sqlalchemy.orm import Session

from .models import Conversation, Message


# Python str.strip's whitespace set, including Unicode spaces and line breaks.
# SQL's default TRIM only removes ordinary spaces, changing legacy title rules.
_WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def list_conversation_page(db: Session, scope, limit: int) -> list[dict]:
    """Filter owners and page metadata before retrieving bounded title prefixes.

    Latest activity follows the last message by ID, even if its timestamp is
    older. Empty conversations disappear in the aggregate join. The second
    query returns at most one 40-character title prefix per untitled page row;
    answer content and result_data never leave the database.
    """
    summaries = (select(Message.conversation_id.label("conversation_id"),
                        func.count(Message.id).label("message_count"),
                        func.max(Message.id).label("last_id"))
                 .join(Conversation, Conversation.id == Message.conversation_id)
                 .where(scope).group_by(Message.conversation_id).subquery())
    activity = func.coalesce(Message.created_at, Conversation.created_at)
    page = db.execute(
        select(Conversation.id, Conversation.title, Conversation.pinned,
               summaries.c.message_count, activity.label("updated_at"))
        .join(summaries, summaries.c.conversation_id == Conversation.id)
        .join(Message, Message.id == summaries.c.last_id)
        .order_by(Conversation.pinned.desc(), activity.desc().nulls_last(), Conversation.id.asc())
        .limit(limit)
    ).all()
    missing_titles = [row.id for row in page if not row.title]
    titles = {}
    if missing_titles:
        sqlite = db.get_bind().dialect.name == "sqlite"
        trim = func.trim if sqlite else func.btrim
        stripped = trim(Message.content, _WHITESPACE)
        first_user_ids = (select(func.min(Message.id))
                          .where(Message.conversation_id.in_(missing_titles), Message.role == "user",
                                 stripped != "")
                          .group_by(Message.conversation_id))
        # SQLite text SUBSTR stops at embedded NUL. A bounded UTF-8 byte prefix
        # preserves those legacy strings; 160 bytes contain at least 40 code
        # points, with a possibly incomplete trailing character discarded.
        prefix = func.substr(cast(stripped, LargeBinary), 1, 160) if sqlite else func.substr(stripped, 1, 40)
        for identifier, value in db.execute(select(Message.conversation_id, prefix)
                                            .where(Message.id.in_(first_user_ids))):
            text = value.decode("utf-8", errors="ignore")[:40] if sqlite else value
            titles[identifier] = text.splitlines()[0]
    return [{"id": row.id, "title": row.title or titles.get(row.id, "新对话"),
             "message_count": row.message_count,
             "updated_at": ((row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)).isoformat()
                            if row.updated_at is not None else ""),
             "pinned": bool(row.pinned)} for row in page]
