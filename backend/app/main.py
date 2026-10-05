from contextlib import asynccontextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import logging
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .agent import prepare_stream_state, run_agent, stream_model
from . import auth, campus_data, mcp_registry, web_search
from .config import get_settings
from .desktop_runtime import desktop_enabled, install_desktop_routes
from .db import Base, SessionLocal, engine, ensure_conversation_columns, get_db
from .models import Conversation, Document, Message, Plugin, User
from .model_runtime import configuration as model_configuration, update_provider, test_provider, local_models, start_download, get_download, cancel_download, resolve_local_model, LocalModelError
from .plugins import GITHUB_HOSTS, fetch_github_manifest, fetch_manifest_json, invoke_plugin, validate_plugin_url
from .rag import knowledge_index
from .schemas import AuthLogin, AuthRegister, ChatRequest, ChatResponse, ConversationBatchDelete, ConversationUpdate, DocumentCreate, DocumentUpdate, FeedbackRequest, ImportUrlRequest, McpServerCreate, McpServerUpdate, PasswordChange, PasswordReset, PluginCreate, PluginUpdate, RepairCreate, SettingsUpdate, ModelProviderUpdate, LocalModelPull, Source, UserCreate, UserUpdate, WebSearchConfigUpdate
from .seed import seed_demo_documents
from . import services

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_conversation_columns()
    with SessionLocal() as db:
        seed_demo_documents(db)
        auth.ensure_bootstrap_admin(db)
    yield


app = FastAPI(title="Mens API", version="1.2.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def require_admin(x_admin_token: str | None = Header(default=None), x_campus_desktop_token: str | None = Header(default=None),
                  request: Request = None):
    configured = get_settings().admin_token
    supplied = x_campus_desktop_token if desktop_enabled() else x_admin_token
    if configured and supplied and secrets.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        return
    # 网站部署下，已登录且角色为管理员的使用者同样可以执行管理操作
    if auth.setting("auth_required", False) and not desktop_enabled() and request is not None:
        token = request.cookies.get(auth.COOKIE_NAME, "")
        if token:
            with SessionLocal() as db:
                user = auth.resolve_session(db, token)
            if user is not None and user.role == "admin":
                return
    if not configured:
        raise HTTPException(503, "尚未配置 ADMIN_TOKEN")
    raise HTTPException(401, "管理员令牌无效")


PUBLIC_API_PATHS = {"/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/auth/register", "/api/health"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """网站部署：除公开接口外，/api/* 一律要求登录 Cookie；桌面版自动豁免。"""
    settings = get_settings()
    path = request.url.path
    if (not auth.setting("auth_required", False)) or desktop_enabled() or request.method == "OPTIONS":
        return await call_next(request)
    if not path.startswith("/api/") or path in PUBLIC_API_PATHS or path.startswith("/api/desktop"):
        return await call_next(request)
    token = request.cookies.get(auth.COOKIE_NAME, "")
    if token:
        with SessionLocal() as db:
            user = auth.resolve_session(db, token)
        if user is not None:
            request.state.user = user
            return await call_next(request)
    return JSONResponse({"detail": "请先登录"}, status_code=401)


@app.post("/api/auth/login")
def auth_login(body: AuthLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{body.username.strip().lower()}|{request.client.host if request.client else 'unknown'}"
    if auth.rate_limited(key):
        raise HTTPException(429, "尝试过于频繁，请五分钟后再试")
    user = auth.authenticate(db, body.username, body.password)
    if user is None:
        auth.record_attempt(key)
        raise HTTPException(401, "用户名或口令不正确")
    auth.clear_attempts(key)
    token = auth.start_session(db, user)
    response.set_cookie(auth.COOKIE_NAME, token, max_age=max(1, auth.setting("session_days", 14)) * 86400,
                        httponly=True, samesite="lax", secure=bool(auth.setting("cookie_secure", False)), path="/")
    return {"user": auth.public_user(user)}


@app.post("/api/auth/register")
def auth_register(body: AuthRegister, request: Request, response: Response, db: Session = Depends(get_db)):
    """自助注册：由 ALLOW_REGISTRATION 控制；设置 REGISTER_CODE 后必须带对注册码。"""
    if not auth.setting("allow_registration", False):
        raise HTTPException(403, "本站未开放自助注册，请联系管理员开通账号")
    key = f"register|{request.client.host if request.client else 'unknown'}"
    if auth.rate_limited(key):
        raise HTTPException(429, "注册过于频繁，请稍后再试")
    expected = str(auth.setting("register_code", "") or "")
    if expected and not secrets.compare_digest(body.code.strip().encode("utf-8"), expected.encode("utf-8")):
        auth.record_attempt(key)
        raise HTTPException(403, "注册码不正确")
    try:
        user = auth.create_user(db, body.username, body.password, role="user")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    token = auth.start_session(db, user)
    response.set_cookie(auth.COOKIE_NAME, token, max_age=max(1, auth.setting("session_days", 14)) * 86400,
                        httponly=True, samesite="lax", secure=bool(auth.setting("cookie_secure", False)), path="/")
    return {"user": auth.public_user(user)}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.end_session(db, request.cookies.get(auth.COOKIE_NAME, ""))
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user = auth.resolve_session(db, request.cookies.get(auth.COOKIE_NAME, ""))
    if user is None:
        raise HTTPException(401, "未登录")
    return {"user": auth.public_user(user)}


def _session_user(request: Request, db: Session):
    return auth.resolve_session(db, request.cookies.get(auth.COOKIE_NAME, ""))


@app.post("/api/auth/password")
def auth_change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db)):
    """自助改密：需提供当前口令。"""
    user = _session_user(request, db)
    if user is None:
        raise HTTPException(401, "未登录")
    try:
        auth.change_own_password(db, user, body.current, body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@app.get("/api/auth/users", dependencies=[Depends(require_admin)])
def auth_list_users(db: Session = Depends(get_db)):
    users = auth.list_users(db)
    return {"users": users, "admin_count": auth.count_admins(db), "total": len(users)}


@app.post("/api/auth/users", dependencies=[Depends(require_admin)])
def auth_create_user(body: UserCreate, db: Session = Depends(get_db)):
    try:
        user = auth.create_user(db, body.username, body.password, role=body.role)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"user": auth.public_user(user)}


@app.patch("/api/auth/users/{user_id}", dependencies=[Depends(require_admin)])
def auth_update_user(user_id: str, body: UserUpdate, request: Request, db: Session = Depends(get_db)):
    actor = _session_user(request, db)
    actor_id = actor.id if actor else ""
    try:
        if body.role is not None:
            auth.set_role(db, user_id, body.role, actor_id)
        if body.disabled is not None:
            auth.set_disabled(db, user_id, body.disabled, actor_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    user = db.get(User, user_id)
    return {"user": auth.public_user(user) if user else None}


@app.delete("/api/auth/users/{user_id}", dependencies=[Depends(require_admin)])
def auth_delete_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    actor = _session_user(request, db)
    try:
        auth.delete_user(db, user_id, actor.id if actor else "")
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"deleted": user_id}


@app.post("/api/auth/users/{user_id}/password", dependencies=[Depends(require_admin)])
def auth_reset_password(user_id: str, body: PasswordReset, db: Session = Depends(get_db)):
    """管理员重置口令：改完立即踢掉该用户的全部会话。"""
    try:
        user = auth.reset_password(db, user_id, body.password)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"user": auth.public_user(user)}


@app.post("/api/auth/users/{user_id}/revoke", dependencies=[Depends(require_admin)])
def auth_revoke_sessions(user_id: str, db: Session = Depends(get_db)):
    if db.get(User, user_id) is None:
        raise HTTPException(404, "用户不存在")
    return {"revoked": auth.revoke_sessions(db, user_id)}


def document_json(doc: Document) -> dict:
    return {"id": doc.id, "title": doc.title, "content": doc.content, "created_at": doc.created_at, "updated_at": doc.updated_at}


def indexed_document_json(doc: Document) -> dict:
    result = document_json(doc)
    try:
        knowledge_index.index(doc)
        result["index_status"] = "indexed" if get_settings().enable_rag else "keyword"
    except Exception:
        # The SQL write has succeeded; report recoverable indexing failure honestly.
        # Retrieval checks SQL versions so stale vectors cannot appear as current data.
        result["index_status"] = "pending"
        logger.warning("Document saved but vector indexing failed: %s", doc.id)
        result["warning"] = "文档已保存，向量索引暂不可用；恢复后请重建索引。"
    return result


def plugin_json(plugin: Plugin) -> dict:
    return {"id": plugin.id, "name": plugin.name, "description": plugin.description, "url": plugin.url, "parameters": plugin.parameters, "enabled": plugin.enabled}


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def iso_utc(value) -> str:
    if value is None:
        return ""
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


THINKING_LIMIT = 12000


def persist_stream_exchange(conversation_id: str, question: str, text: str, final: dict | None, error: str,
                            streamed_from_model: bool = False, thinking: str = "") -> None:
    """Best-effort persistence for streamed answers; stopped or failed streams must not crash cleanup."""
    try:
        with SessionLocal() as db:
            rows = [Message(conversation_id=conversation_id, role="user", content=question)]
            if text.strip():
                data = {"sources": (final or {}).get("sources", []), "tool_calls": (final or {}).get("tool_calls", [])}
                data["mode"] = final.get("mode", "demo") if final is not None else ("llm" if streamed_from_model else "demo")
                if thinking.strip():
                    data["thinking"] = thinking[:THINKING_LIMIT]
                if final and final.get("web"):
                    data["web"] = final["web"]
                if final is None or error:
                    data["partial"] = True
                rows.append(Message(conversation_id=conversation_id, role="assistant", content=text, result_data=data))
            db.add_all(rows)
            db.commit()
    except Exception:
        logger.warning("Failed to persist streamed exchange for conversation %s", conversation_id, exc_info=True)


def replace_trailing_exchange(db, conversation_id: str, question: str) -> bool:
    """重新生成：删除末尾与之匹配的「问答对」，避免同题在历史里重复出现。"""
    tail = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(2)).all()
    if len(tail) == 2 and tail[0].role == "assistant" and tail[1].role == "user" and tail[1].content == question:
        for row in tail:
            db.delete(row)
        return True
    return False


def attachments_augmented(question: str, attachments) -> str:
    """把随提问附带的文件内容拼进发给模型的提问；落库仍是原始提问文本。"""
    if not attachments:
        return question
    blocks = "\n\n".join(f"文件：{item.name}\n```\n{item.text}\n```" for item in attachments)
    return f"{question}\n\n---\n以下是用户随提问附上的文件内容：\n\n{blocks}"


def public_sources(rows) -> list[dict]:
    """Normalize agent source rows for responses and storage (drops fetched page text)."""
    return [Source(**row).model_dump() for row in (rows or [])]


@app.get("/api/health")
def health():
    settings = get_settings()
    providers = model_configuration()["providers"]
    return {"status": "ok", "rag_enabled": settings.enable_rag, "rag_degraded": knowledge_index.last_error,
            "models": {key: row["configured"] for key, row in providers.items()},
            "auth_required": bool(auth.setting("auth_required", False)) and not desktop_enabled(),
            "allow_registration": bool(auth.setting("allow_registration", False)) and not desktop_enabled(),
            "register_code_required": bool(str(auth.setting("register_code", "") or "")) and not desktop_enabled(),
            "demo_services": not any(campus_data.configured(kind) for kind in campus_data.KINDS)}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    if body.model not in (None, "auto", "qwen", "deepseek", "ollama"):
        raise HTTPException(422, "不支持的模型")
    model = body.model or _selected_model
    try:
        local_model = resolve_local_model(body.local_model) if model == "ollama" else None
    except LocalModelError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    client_id = (body.client_id or "").strip()
    if body.conversation_id:
        conversation = db.get(Conversation, body.conversation_id)
        if conversation is None:
            raise HTTPException(404, "对话不存在")
        if client_id and not conversation.client_id:
            conversation.client_id = client_id
    else:
        conversation = Conversation(id=str(uuid4()), client_id=client_id)
        db.add(conversation)
        db.flush()
    if body.regenerate and body.conversation_id:
        replace_trailing_exchange(db, conversation.id, body.message.strip())
    past = db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id.desc()).limit(8)).all()
    history = [{"role": item.role, "content": item.content} for item in reversed(past)]
    try:
        result = run_agent(db, attachments_augmented(body.message.strip(), body.attachments), history, model, local_model=local_model, use_web=body.web, reasoning=body.reasoning)
    except LocalModelError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    response_data = {"sources": public_sources(result.get("sources", [])), "tool_calls": result.get("tool_calls", []),
                     "mode": result.get("mode", "demo"), "web": result.get("web", {})}
    db.add_all([Message(conversation_id=conversation.id, role="user", content=body.message.strip()), Message(conversation_id=conversation.id, role="assistant", content=result["answer"], result_data=response_data)])
    db.commit()
    return ChatResponse(conversation_id=conversation.id, answer=result["answer"], sources=response_data["sources"], tool_calls=result.get("tool_calls", []), mode=result.get("mode", "demo"), web=result.get("web", {}))


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest):
    """Server-sent events: `meta`, repeated `delta`, then `done` (or `error`).

    Stopping the client disconnects the request; whatever was generated is still
    persisted so history stays honest about what happened.
    """
    if body.model not in (None, "auto", "qwen", "deepseek", "ollama"):
        raise HTTPException(422, "不支持的模型")
    model = body.model or _selected_model
    try:
        local_model = resolve_local_model(body.local_model) if model == "ollama" else None
    except LocalModelError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    question = body.message.strip()
    client_id = (body.client_id or "").strip()
    with SessionLocal() as db:
        if body.conversation_id:
            conversation = db.get(Conversation, body.conversation_id)
            if conversation is None:
                raise HTTPException(404, "对话不存在")
            if client_id and not conversation.client_id:
                conversation.client_id = client_id
            conversation_id = conversation.id
        else:
            conversation_id = str(uuid4())
            db.add(Conversation(id=conversation_id, client_id=client_id))
        if body.regenerate and body.conversation_id:
            replace_trailing_exchange(db, conversation_id, question)
        past = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(8)).all()
        history = [{"role": item.role, "content": item.content} for item in reversed(past)]
        db.commit()

    async def event_stream():
        parts: list[str] = []
        thinking_parts: list[str] = []
        final: dict | None = None
        error = ""
        streamed_from_model = False
        yield sse_event("meta", {"conversation_id": conversation_id})
        try:
            with SessionLocal() as db:
                prepared = await run_in_threadpool(prepare_stream_state, db, attachments_augmented(question, body.attachments), history, model, local_model, body.web, body.reasoning)
                if "direct" in prepared:
                    final = dict(prepared["direct"])
                    parts.append(final["answer"])
                    yield sse_event("delta", {"text": final["answer"]})
                else:
                    streamed_from_model = True
                    try:
                        async for kind, chunk in stream_model(prepared["messages"], prepared["requested_model"], prepared.get("local_model"), prepared.get("reasoning")):
                            if kind == "thinking":
                                thinking_parts.append(chunk)
                                yield sse_event("thinking", {"text": chunk})
                            else:
                                parts.append(chunk)
                                yield sse_event("delta", {"text": chunk})
                    except LocalModelError as exc:
                        error = str(exc)
                    if not error:
                        text = "".join(parts)
                        if text.strip():
                            final = {"answer": text, "sources": public_sources(prepared["sources"]), "tool_calls": [],
                                     "mode": "llm", "web": prepared.get("web", {})}
                        else:
                            fallback = prepared["fallback"]
                            final = {**fallback, "sources": public_sources(prepared["sources"]), "tool_calls": [],
                                     "web": prepared.get("web", {})}
                            parts.append(fallback["answer"])
                            yield sse_event("delta", {"text": fallback["answer"]})
        except Exception:
            logger.exception("Streamed chat failed for conversation %s", conversation_id)
            error = error or "生成回答时发生错误，请稍后重试。"
        finally:
            persist_stream_exchange(conversation_id, question, "".join(parts), final, error, streamed_from_model, "".join(thinking_parts))
        if error:
            yield sse_event("error", {"message": error, "partial": "".join(parts), "conversation_id": conversation_id})
        else:
            yield sse_event("done", {**(final or {"answer": "", "sources": [], "tool_calls": [], "mode": "demo"}),
                                     "conversation_id": conversation_id})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/conversations")
def list_conversations(db: Session = Depends(get_db), client_id: str = Query(default="", max_length=64),
                       limit: int = Query(default=50, ge=1, le=200)):
    conversations = db.scalars(select(Conversation).where(Conversation.client_id == client_id)).all()
    items = []
    for conversation in conversations:
        rows = db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)).all()
        if not rows:
            continue
        first_user = next((row for row in rows if row.role == "user" and row.content.strip()), None)
        items.append({
            "id": conversation.id,
            "title": conversation.title or (first_user.content.strip().splitlines()[0][:40] if first_user else "新对话"),
            "message_count": len(rows),
            "updated_at": iso_utc(rows[-1].created_at or conversation.created_at),
            "pinned": bool(conversation.pinned),
        })
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    items.sort(key=lambda item: item["pinned"], reverse=True)
    return items[:limit]


@app.get("/api/conversations/search")
def search_conversations(db: Session = Depends(get_db), client_id: str = Query(default="", max_length=64),
                         q: str = Query(min_length=1, max_length=100), limit: int = Query(default=20, ge=1, le=50)):
    """全文检索历史对话（提问与回答都参与匹配）；中文短词可用、% 与 _ 按字面义转义。"""
    query = q.strip()
    if not query:
        return []
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    owned = select(Conversation.id).where(Conversation.client_id == client_id)
    rows = db.scalars(select(Message).where(Message.conversation_id.in_(owned), Message.content.like(pattern, escape="\\"))
                      .order_by(Message.id.desc()).limit(500)).all()
    results: list[dict] = []
    seen: dict[str, dict] = {}
    for row in rows:
        entry = seen.get(row.conversation_id)
        index = row.content.lower().find(query.lower())
        if index < 0:
            index = 0
        snippet = row.content[max(0, index - 30): index + len(query) + 60].replace("\n", " ").strip()
        if entry is None:
            if len(results) >= limit:
                continue
            entry = {"conversation_id": row.conversation_id, "snippet": snippet, "matches": 0}
            seen[row.conversation_id] = entry
            results.append(entry)
        entry["matches"] += 1
    for item in results:
        conversation = db.get(Conversation, item["conversation_id"])
        first = db.scalars(select(Message).where(Message.conversation_id == item["conversation_id"], Message.role == "user")
                           .order_by(Message.id).limit(1)).first()
        item["title"] = (conversation.title if conversation and conversation.title
                         else (first.content.strip().splitlines()[0][:40] if first else "新对话"))
    return results


@app.patch("/api/conversations/{conversation_id}")
def update_conversation(conversation_id: str, body: ConversationUpdate, db: Session = Depends(get_db),
                        client_id: str = Query(default="", max_length=64)):
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.client_id != client_id:
        raise HTTPException(404, "对话不存在")
    if body.title is not None:
        title = body.title.strip()
        conversation.title = title[:120] if title else None
    if body.pinned is not None:
        conversation.pinned = body.pinned
    db.commit()
    return {"id": conversation.id, "title": conversation.title, "pinned": bool(conversation.pinned)}


@app.post("/api/conversations/batch-delete")
def batch_delete_conversations(body: ConversationBatchDelete, db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(body.ids))
    owned = list(db.scalars(select(Conversation.id).where(Conversation.id.in_(ids), Conversation.client_id == body.client_id)).all())
    if owned:
        db.execute(delete(Message).where(Message.conversation_id.in_(owned)))
        db.execute(delete(Conversation).where(Conversation.id.in_(owned)))
        db.commit()
    return {"deleted": len(owned)}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), client_id: str = Query(default="", max_length=64)):
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.client_id != client_id:
        raise HTTPException(404, "对话不存在")
    db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    db.delete(conversation)
    db.commit()
    return {"deleted": True}


@app.delete("/api/conversations")
def clear_conversations(db: Session = Depends(get_db), client_id: str = Query(default="", max_length=64)):
    ids = list(db.scalars(select(Conversation.id).where(Conversation.client_id == client_id)).all())
    if ids:
        db.execute(delete(Message).where(Message.conversation_id.in_(ids)))
        db.execute(delete(Conversation).where(Conversation.id.in_(ids)))
        db.commit()
    return {"deleted": len(ids)}


@app.get("/api/conversations/{conversation_id}")
def conversation_history(conversation_id: str, db: Session = Depends(get_db)):
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(404, "对话不存在")
    rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)).all()
    return {"id": conversation_id, "messages": [{"role": row.role, "content": row.content, "created_at": row.created_at, **(row.result_data or {}), "id": row.id} for row in rows]}


@app.post("/api/conversations/{conversation_id}/messages/{message_id}/feedback")
def message_feedback(conversation_id: str, message_id: int, body: FeedbackRequest, db: Session = Depends(get_db)):
    """用户对某条助手回答的「有帮助 / 没帮助」反馈；value 为 null 时清除。"""
    row = db.get(Message, message_id)
    if row is None or row.conversation_id != conversation_id or row.role != "assistant":
        raise HTTPException(404, "消息不存在")
    data = dict(row.result_data or {})
    if body.value is None:
        data.pop("feedback", None)
    else:
        data["feedback"] = body.value
    row.result_data = data
    db.commit()
    return {"ok": True, "feedback": body.value}


def conversation_rows(db: Session, conversation_id: str) -> list[Message]:
    return list(db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)).all())


def conversation_title(rows: list[Message]) -> str:
    """Same title rule as the history list, so exports match what the sidebar shows."""
    first_user = next((row for row in rows if row.role == "user" and row.content.strip()), None)
    return first_user.content.strip().splitlines()[0][:80] if first_user else "新对话"


def exported_message(row: Message) -> dict:
    data = row.result_data if isinstance(row.result_data, dict) else {}
    return {"role": row.role, "content": row.content, "created_at": iso_utc(row.created_at),
            "sources": data.get("sources", []), "tool_calls": data.get("tool_calls", []), "mode": data.get("mode", "")}


def conversation_markdown(title: str, conversation_id: str, exported_at: str, rows: list[Message]) -> str:
    lines = [f"# {title}", "",
             f"- 对话 ID：`{conversation_id}`",
             f"- 消息数：{len(rows)}",
             f"- 导出时间：{exported_at}",
             "- 导出工具：Mens 校园助手（Apache-2.0）。演示数据与降级结果在消息内标注。",
             "", "---", ""]
    for index, row in enumerate(rows, 1):
        speaker = "用户" if row.role == "user" else "助手"
        lines += [f"## {index}. {speaker} · {iso_utc(row.created_at)}", "", row.content.strip() or "（空）", ""]
        data = row.result_data if isinstance(row.result_data, dict) else {}
        if data.get("mode") == "demo":
            lines += ["> 本条回答使用演示数据或降级结果，未接入学校接口。", ""]
        calls = data.get("tool_calls") or []
        if calls:
            lines += ["**工具调用**", ""]
            for call in calls:
                name = call.get("name") or call.get("tool") or "tool"
                lines.append(f"- `{name}`")
            lines.append("")
        sources = data.get("sources") or []
        if sources:
            lines += ["**参考来源**", ""]
            for position, source in enumerate(sources, 1):
                label = source.get("title") or source.get("url") or f"来源 {position}"
                url = source.get("url") or ""
                kind = f"（{source['kind']}）" if source.get("kind") else ""
                lines.append(f"{position}. [{label}]({url}){kind}" if url else f"{position}. {label}{kind}")
                snippet = (source.get("snippet") or "").strip()
                if snippet:
                    lines.append(f"   - {snippet[:200]}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@app.get("/api/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, format: str = Query(default="md", pattern="^(md|json)$"),
                        db: Session = Depends(get_db)):
    """Export one conversation as Markdown (for reading) or JSON (for tooling)."""
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(404, "对话不存在")
    rows = conversation_rows(db, conversation_id)
    if not rows:
        raise HTTPException(404, "对话不存在")
    exported_at = iso_utc(datetime.now(timezone.utc))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if format == "json":
        payload = {"app": "Mens", "format": "mens-conversation/1", "license": "Apache-2.0",
                   "exported_at": exported_at,
                   "conversation": {"id": conversation_id, "title": conversation_title(rows), "message_count": len(rows)},
                   "messages": [exported_message(row) for row in rows]}
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        media_type, extension = "application/json", "json"
    else:
        body = conversation_markdown(conversation_title(rows), conversation_id, exported_at, rows).encode("utf-8")
        media_type, extension = "text/markdown; charset=utf-8", "md"
    filename = f"mens-conversation-{conversation_id[:8]}-{stamp}.{extension}"
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.get("/api/documents")
def list_documents(db: Session = Depends(get_db)):
    return [document_json(doc) for doc in db.scalars(select(Document).order_by(Document.updated_at.desc())).all()]


@app.post("/api/documents", dependencies=[Depends(require_admin)])
def add_document(body: DocumentCreate, db: Session = Depends(get_db)):
    doc = Document(id=str(uuid4()), **body.model_dump())
    db.add(doc)
    db.commit()
    return indexed_document_json(doc)


@app.post("/api/documents/upload", dependencies=[Depends(require_admin)])
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename, content = await parse_upload(file)
    doc = Document(id=str(uuid4()), title=filename, content=content)
    db.add(doc)
    db.commit()
    return indexed_document_json(doc)


@app.post("/api/chat/attachments/extract")
async def extract_chat_attachment(file: UploadFile = File(...)):
    """解析随提问上传的文件（TXT/Markdown/PDF/Word，≤5 MB）为纯文本，供前端随消息正文发送。"""
    filename, content = await parse_upload(file)
    return {"name": filename, "text": content.strip()[:200_000]}


@app.post("/api/documents/import-url", dependencies=[Depends(require_admin)])
def import_document_url(body: ImportUrlRequest, db: Session = Depends(get_db)):
    """Import one public web page as a knowledge-base document.

    The fetch follows the same rules as web search (HTTPS only, address pinned to the validated
    public IP with SNI preserved, no redirects, size cap) and the page text is stored locally, so
    the imported material is searchable offline afterwards.
    """
    try:
        title, text = web_search.fetch_document_text(body.url)
    except web_search.WebSearchError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    text = text.strip()
    if len(text) < 20:
        raise HTTPException(400, "网页没有可提取的正文文本")
    label = (title or urlsplit(body.url).netloc or body.url)[:180]
    content = f"来源：{body.url}\n导入时间：{iso_utc(datetime.now(timezone.utc))}\n\n{text}"
    doc = Document(id=str(uuid4()), title=f"[网页] {label}"[:255], content=content)
    db.add(doc)
    db.commit()
    return indexed_document_json(doc)


async def parse_upload(file: UploadFile) -> tuple[str, str]:
    filename = file.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"txt", "md", "pdf", "docx"}:
        raise HTTPException(400, "仅支持 TXT、Markdown、PDF 和 Word (.docx 新版格式)")
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(413, "文件超过 5 MB")
    try:
        if suffix == "pdf":
            from pypdf import PdfReader
            content = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages)
        elif suffix == "docx":
            content = docx_text(raw)
        else:
            content = raw.decode("utf-8-sig")
    except Exception as exc:
        raise HTTPException(400, "文件无法解析；旧版 .doc 请先另存为 .docx") from exc
    if not content.strip():
        raise HTTPException(400, "文档没有可提取的文本")
    if len(content) > 500_000:
        raise HTTPException(413, "文档文本超过 50 万字符，请拆分上传")
    return filename[:255], content


def docx_text(raw: bytes) -> str:
    """Extract paragraph text from a .docx (OOXML) archive with the standard library only."""
    from xml.etree import ElementTree

    try:
        with ZipFile(BytesIO(raw)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 30_000_000:
                raise ValueError("Word document body is too large")
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (BadZipFile, ElementTree.ParseError, KeyError, OSError, ValueError) as exc:
        raise ValueError("Word document cannot be read") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines = []
    for paragraph in root.iter(f"{namespace}p"):
        line = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


@app.put("/api/documents/{document_id}/upload", dependencies=[Depends(require_admin)])
async def replace_document_file(document_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    doc.title, doc.content = await parse_upload(file)
    db.commit()
    return indexed_document_json(doc)


@app.put("/api/documents/{document_id}", dependencies=[Depends(require_admin)])
def update_document(document_id: str, body: DocumentUpdate, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    doc.title, doc.content = body.title, body.content
    db.commit()
    return indexed_document_json(doc)


@app.delete("/api/documents/{document_id}", dependencies=[Depends(require_admin)])
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    db.delete(doc)
    db.commit()
    try:
        knowledge_index.remove(document_id)
    except Exception:
        return {"deleted": True, "warning": "文档已删除；向量清理待重试，已失效的分段不会参与问答。"}
    return {"deleted": True}


@app.post("/api/documents/reindex", dependencies=[Depends(require_admin)])
def reindex(db: Session = Depends(get_db)):
    try:
        return {"indexed": knowledge_index.rebuild(db), "mode": "vector" if get_settings().enable_rag else "keyword"}
    except Exception as exc:
        raise HTTPException(503, "向量重建失败，请检查 BGE-M3、Chroma 依赖与模型文件。") from exc


@app.get("/api/mcp/servers")
def mcp_servers(db: Session = Depends(get_db)):
    """已登记的 MCP 服务器（环境变量只回键名与掩码）。"""
    return {"servers": mcp_registry.list_servers(db)}


@app.post("/api/mcp/servers", dependencies=[Depends(require_admin)])
def mcp_create_server(body: McpServerCreate, db: Session = Depends(get_db)):
    try:
        row = mcp_registry.create_server(db, body.name, body.command, body.args, body.env, body.enabled)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"server": mcp_registry.public_row(row)}


@app.put("/api/mcp/servers/{server_id}", dependencies=[Depends(require_admin)])
def mcp_update_server(server_id: str, body: McpServerUpdate, db: Session = Depends(get_db)):
    try:
        row = mcp_registry.update_server(db, server_id, name=body.name, command=body.command,
                                         args=body.args, env=body.env, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"server": mcp_registry.public_row(row)}


@app.delete("/api/mcp/servers/{server_id}", dependencies=[Depends(require_admin)])
def mcp_delete_server(server_id: str, db: Session = Depends(get_db)):
    try:
        mcp_registry.delete_server(db, server_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": server_id}


@app.post("/api/mcp/servers/{server_id}/test", dependencies=[Depends(require_admin)])
def mcp_test_server(server_id: str, db: Session = Depends(get_db)):
    """真实启动一次服务器：握手、列工具，并把结果缓存下来供界面展示。"""
    try:
        return mcp_registry.check_server(db, server_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/mcp/tools")
def mcp_tools(db: Session = Depends(get_db)):
    return {"tools": mcp_registry.catalog(db)}


@app.get("/api/services/grades")
def get_grades():
    return services.grades()


@app.get("/api/services/schedule")
def get_schedule():
    return services.schedule()


@app.get("/api/services/credits")
def get_credits():
    return services.credits()


@app.get("/api/services/classrooms")
def get_classrooms(building: str | None = None, min_seats: int = Query(default=0, ge=0, le=1000)):
    return services.classrooms(building, min_seats)


@app.post("/api/services/repairs")
def add_repair(body: RepairCreate, db: Session = Depends(get_db)):
    return services.submit_repair(db, body)


@app.get("/api/services/repairs", dependencies=[Depends(require_admin)])
def list_local_repairs(db: Session = Depends(get_db), limit: int = Query(default=50, ge=1, le=200)):
    """Repair history contains contact details, so it stays behind admin authorization."""
    return services.list_repairs(db, limit)


@app.get("/api/campus-sources")
def get_campus_sources():
    return campus_data.list_sources()


@app.put("/api/campus-sources/{kind}", dependencies=[Depends(require_admin)])
def put_campus_source(kind: str, body: dict):
    return campus_data.configure_source(kind, body)


@app.delete("/api/campus-sources/{kind}", dependencies=[Depends(require_admin)])
def delete_campus_source(kind: str):
    campus_data.remove_source(kind)
    return {"deleted": True}


@app.get("/api/campus-data/{kind}")
def get_campus_data(kind: str):
    if kind == "repairs":
        raise HTTPException(405, "报修请使用服务提交入口")
    return campus_data.fetch_source(kind)


@app.get("/api/plugins")
def list_plugins(db: Session = Depends(get_db)):
    return [plugin_json(plugin) for plugin in db.scalars(select(Plugin).order_by(Plugin.name)).all()]


@app.post("/api/plugins", dependencies=[Depends(require_admin)])
def add_plugin(body: PluginCreate, db: Session = Depends(get_db)):
    validate_plugin_url(str(body.url))
    if db.scalar(select(Plugin).where(Plugin.name == body.name)):
        raise HTTPException(409, "插件名称已存在")
    plugin = Plugin(id=str(uuid4()), **{**body.model_dump(), "url": str(body.url)})
    db.add(plugin)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "插件名称已存在") from exc
    return plugin_json(plugin)


@app.post("/api/plugins/install", dependencies=[Depends(require_admin)])
def install_plugin(body: dict, db: Session = Depends(get_db)):
    from pydantic import ValidationError

    source = body.get("source")
    if not isinstance(source, str) or not source.strip():
        raise HTTPException(422, "缺少插件清单地址")
    source = source.strip()
    if (urlsplit(source).hostname or "").lower() in GITHUB_HOSTS:
        manifest = fetch_github_manifest(source)
    else:
        manifest = fetch_manifest_json(source, use_url_whitelist=True)
    try:
        manifest = PluginCreate.model_validate(manifest)
    except ValidationError as exc:
        raise HTTPException(422, "插件清单格式无效") from exc
    return add_plugin(manifest, db)


@app.patch("/api/plugins/{plugin_id}", dependencies=[Depends(require_admin)])
def update_plugin(plugin_id: str, body: PluginUpdate, db: Session = Depends(get_db)):
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise HTTPException(404, "插件不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(plugin, key, value)
    db.commit()
    return plugin_json(plugin)


@app.delete("/api/plugins/{plugin_id}", dependencies=[Depends(require_admin)])
def delete_plugin(plugin_id: str, db: Session = Depends(get_db)):
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise HTTPException(404, "插件不存在")
    db.delete(plugin)
    db.commit()
    return {"deleted": True}


@app.post("/api/plugins/{name}/invoke", dependencies=[Depends(require_admin)])
def call_plugin(name: str, parameters: dict, db: Session = Depends(get_db)):
    return invoke_plugin(db, name, parameters)


_selected_model = "auto"


@app.get("/api/settings")
def get_ui_settings():
    settings = get_settings()
    providers = model_configuration()["providers"]
    return {"model": _selected_model, "qwen_available": providers["qwen"]["configured"], "deepseek_available": providers["deepseek"]["configured"], "rag_enabled": settings.enable_rag}


@app.put("/api/settings", dependencies=[Depends(require_admin)])
def update_ui_settings(body: SettingsUpdate):
    global _selected_model
    _selected_model = body.model
    return get_ui_settings()


@app.get("/api/web/status")
def web_status():
    """Whether live web search is available for chat; safe for any client to read."""
    return web_search.status()


@app.put("/api/web/config", dependencies=[Depends(require_admin)])
def update_web_config(body: WebSearchConfigUpdate):
    try:
        return web_search.update_config(body.model_dump(exclude_unset=True))
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/models/config")
def get_model_config():
    return model_configuration()


@app.put("/api/models/config/{provider}", dependencies=[Depends(require_admin)])
def put_model_config(provider: str, body: ModelProviderUpdate):
    try:
        return update_provider(provider, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/models/test/{provider}", dependencies=[Depends(require_admin)])
def test_model_config(provider: str):
    if provider not in ("qwen", "deepseek", "ollama"):
        raise HTTPException(404, "未知模型提供商")
    return test_provider(provider)


@app.get("/api/models/local")
def get_local_models():
    return local_models()


@app.post("/api/models/local/pull", status_code=202, dependencies=[Depends(require_admin)])
def pull_local_model(body: LocalModelPull):
    result = start_download(body.model, body.source)
    return {**result, "job_id": result["id"]}


@app.get("/api/models/local/jobs/{job_id}")
def get_local_model_job(job_id: str):
    result = get_download(job_id)
    if result is None:
        raise HTTPException(404, "下载任务不存在")
    return result


@app.post("/api/models/local/jobs/{job_id}/cancel", dependencies=[Depends(require_admin)])
def cancel_local_model_job(job_id: str):
    result = cancel_download(job_id)
    if result is None:
        raise HTTPException(404, "下载任务不存在")
    return result


BACKUP_FORMAT = 1
BACKUP_CONFIG_FILES = ("workspace.json", "model-providers.json", "campus-sources.json", "web-search.json", ".env")
BACKUP_MAX_BYTES = 200_000_000


def version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"(\d+(?:\.\d+){0,3})", (value or "").strip().lstrip("vV"))
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


@app.get("/api/update/check", dependencies=[Depends(require_admin)])
def check_update():
    """Optional update check; only runs when an administrator configured an HTTPS manifest."""
    current = app.version
    url = (get_settings().update_manifest_url or "").strip()
    if not url:
        return {"configured": False, "current": current, "update_available": False,
                "message": "未配置更新清单地址（.env 中的 UPDATE_MANIFEST_URL），不联网检查。"}
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("update manifest must be a plain HTTPS URL")
        response = httpx.get(url, timeout=10, follow_redirects=False, trust_env=False, headers={"Accept": "application/json"})
        response.raise_for_status()
        if len(response.content) > 64_000:
            raise ValueError("update manifest is too large")
        manifest = response.json()
    except (httpx.HTTPError, ValueError):
        return {"configured": True, "current": current, "update_available": False,
                "error": "无法读取更新清单，请检查地址与网络后重试。"}
    latest = manifest.get("version") if isinstance(manifest, dict) else None
    latest_tuple, current_tuple = version_tuple(str(latest or "")), version_tuple(current)
    if latest_tuple is None or current_tuple is None:
        return {"configured": True, "current": current, "update_available": False,
                "error": "更新清单缺少有效的版本号。"}
    available = latest_tuple > current_tuple
    download = manifest.get("url") if isinstance(manifest.get("url"), str) else ""
    notes = manifest.get("notes") if isinstance(manifest.get("notes"), str) else ""
    return {"configured": True, "current": current, "latest": str(latest), "update_available": available,
            "url": download if download.startswith("https://") else "", "notes": notes[:500],
            "message": f"发现新版本 {latest}。" if available else "已是最新版本。"}


def sqlite_database_path() -> Path | None:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        return None
    return Path(url.removeprefix("sqlite:///"))


@app.get("/api/backup/export", dependencies=[Depends(require_admin)])
def export_backup():
    """Zip of knowledge base, conversations and configuration; SQLite is snapshotted through VACUUM INTO."""
    data_dir = Path(get_settings().data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    database = "server-managed"
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        database_path = sqlite_database_path()
        if database_path is not None and database_path.is_file():
            database = "sqlite"
            snapshot = data_dir / ".mens-backup-snapshot.db"
            snapshot.unlink(missing_ok=True)
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql("VACUUM INTO ?", (str(snapshot),))
                payload = snapshot.read_bytes()
            finally:
                snapshot.unlink(missing_ok=True)
            archive.writestr("campus.db", payload)
            files["campus.db"] = {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name in BACKUP_CONFIG_FILES:
            path = data_dir / name
            if path.is_file():
                payload = path.read_bytes()
                archive.writestr(name, payload)
                files[name] = {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        manifest = {"app": "Mens", "format": BACKUP_FORMAT, "created_at": iso_utc(datetime.now(timezone.utc)),
                    "database": database, "files": files}
        archive.writestr("mens-backup.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    buffer.seek(0)
    filename = f"mens-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(buffer, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                      "Cache-Control": "no-store"})


@app.post("/api/backup/import", dependencies=[Depends(require_admin)])
async def import_backup(file: UploadFile = File(...)):
    """Restore a Mens backup; the live SQLite database is replaced through the backup API, never by file swap."""
    raw = await file.read(BACKUP_MAX_BYTES + 1)
    if len(raw) > BACKUP_MAX_BYTES:
        raise HTTPException(413, "备份文件超过 200 MB")
    try:
        archive = ZipFile(BytesIO(raw))
    except BadZipFile as exc:
        raise HTTPException(400, "不是有效的备份文件（zip）") from exc
    with archive:
        names = archive.namelist()
        if "mens-backup.json" not in names:
            raise HTTPException(400, "缺少备份清单 mens-backup.json")
        allowed = {"mens-backup.json", "campus.db", *BACKUP_CONFIG_FILES}
        if any(name not in allowed or "/" in name or "\\" in name for name in names):
            raise HTTPException(400, "备份文件包含不允许的路径")
        try:
            manifest = json.loads(archive.read("mens-backup.json"))
            payloads = {name: archive.read(name) for name in names if name != "mens-backup.json"}
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(400, "备份内容无法读取") from exc
    if not isinstance(manifest, dict) or manifest.get("app") != "Mens" or manifest.get("format") != BACKUP_FORMAT:
        raise HTTPException(400, "备份格式不受支持")
    data_dir = Path(get_settings().data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    failed: list[str] = []
    if "campus.db" in payloads:
        database_path = sqlite_database_path()
        if database_path is None:
            raise HTTPException(400, "该部署使用服务器数据库，不能导入 SQLite 备份")
        staging = data_dir / ".mens-restore-staging.db"
        staging.write_bytes(payloads["campus.db"])
        try:
            # Validate the uploaded database before the live file is touched at all.
            with closing(sqlite3.connect(staging)) as source:
                tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"conversations", "messages", "documents"} <= tables:
                    raise HTTPException(400, "备份中的数据库不是 Mens 数据")
                with closing(sqlite3.connect(database_path)) as target:
                    source.backup(target)
        except sqlite3.DatabaseError as exc:
            raise HTTPException(400, "备份中的数据库无法读取") from exc
        finally:
            staging.unlink(missing_ok=True)
        ensure_conversation_columns()
        restored.append("campus.db")
    for name in BACKUP_CONFIG_FILES:
        if name in payloads:
            temporary = data_dir / f".{name.lstrip('.')}.import"
            try:
                temporary.write_bytes(payloads[name])
                os.replace(temporary, data_dir / name)
                restored.append(name)
            except OSError:
                failed.append(name)
                temporary.unlink(missing_ok=True)
                logger.warning("Could not restore backup file %s", name)
    logger.info("Backup imported: %s", ", ".join(restored) or "nothing")
    return {"restored": restored, "failed": failed,
            "restart_required": any(name in payloads for name in (".env", "workspace.json"))}


install_desktop_routes(app)

# 网站部署：把前端构建产物交给后端托管（桌面版走外壳自己的静态目录）。
# 必须在所有 /api 路由注册之后挂载，避免遮挡接口。
WEB_FRONTEND_DIR = os.environ.get("WEB_FRONTEND_DIR", "")
if WEB_FRONTEND_DIR and Path(WEB_FRONTEND_DIR).is_dir():
    from starlette.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=WEB_FRONTEND_DIR, html=True, follow_symlink=False), name="web-ui")
