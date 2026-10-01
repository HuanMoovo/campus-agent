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
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .agent import prepare_stream_state, run_agent, stream_model
from . import campus_data
from .config import get_settings
from .desktop_runtime import desktop_enabled, install_desktop_routes
from .db import Base, SessionLocal, engine, ensure_conversation_client_id, get_db
from .models import Conversation, Document, Message, Plugin
from .model_runtime import configuration as model_configuration, update_provider, test_provider, local_models, start_download, get_download, cancel_download, resolve_local_model, LocalModelError
from .plugins import fetch_plugin_json, invoke_plugin, validate_plugin_url
from .plugin_catalog import catalog_list, install_curated_plugin
from .rag import knowledge_index
from .schemas import ChatRequest, ChatResponse, DocumentCreate, DocumentUpdate, PluginCreate, PluginUpdate, RepairCreate, SettingsUpdate, ModelProviderUpdate, LocalModelPull
from .seed import seed_demo_documents
from . import services

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_conversation_client_id()
    with SessionLocal() as db:
        seed_demo_documents(db)
    yield


app = FastAPI(title="Mens API", version="1.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def require_admin(x_admin_token: str | None = Header(default=None), x_campus_desktop_token: str | None = Header(default=None)):
    configured = get_settings().admin_token
    if not configured:
        raise HTTPException(503, "尚未配置 ADMIN_TOKEN")
    supplied = x_campus_desktop_token if desktop_enabled() else x_admin_token
    if not supplied or not secrets.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(401, "管理员令牌无效")


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


def persist_stream_exchange(conversation_id: str, question: str, text: str, final: dict | None, error: str,
                            streamed_from_model: bool = False) -> None:
    """Best-effort persistence for streamed answers; stopped or failed streams must not crash cleanup."""
    try:
        with SessionLocal() as db:
            rows = [Message(conversation_id=conversation_id, role="user", content=question)]
            if text.strip():
                data = {"sources": (final or {}).get("sources", []), "tool_calls": (final or {}).get("tool_calls", [])}
                data["mode"] = final.get("mode", "demo") if final is not None else ("llm" if streamed_from_model else "demo")
                if final is None or error:
                    data["partial"] = True
                rows.append(Message(conversation_id=conversation_id, role="assistant", content=text, result_data=data))
            db.add_all(rows)
            db.commit()
    except Exception:
        logger.warning("Failed to persist streamed exchange for conversation %s", conversation_id, exc_info=True)


@app.get("/api/health")
def health():
    settings = get_settings()
    providers = model_configuration()["providers"]
    return {"status": "ok", "rag_enabled": settings.enable_rag, "rag_degraded": knowledge_index.last_error,
            "models": {key: row["configured"] for key, row in providers.items()},
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
    past = db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id.desc()).limit(8)).all()
    history = [{"role": item.role, "content": item.content} for item in reversed(past)]
    try:
        result = run_agent(db, body.message.strip(), history, model, local_model=local_model)
    except LocalModelError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    response_data = {"sources": result.get("sources", []), "tool_calls": result.get("tool_calls", []), "mode": result.get("mode", "demo")}
    db.add_all([Message(conversation_id=conversation.id, role="user", content=body.message.strip()), Message(conversation_id=conversation.id, role="assistant", content=result["answer"], result_data=response_data)])
    db.commit()
    return ChatResponse(conversation_id=conversation.id, answer=result["answer"], sources=result.get("sources", []), tool_calls=result.get("tool_calls", []), mode=result.get("mode", "demo"))


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
        past = db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.desc()).limit(8)).all()
        history = [{"role": item.role, "content": item.content} for item in reversed(past)]
        db.commit()

    async def event_stream():
        parts: list[str] = []
        final: dict | None = None
        error = ""
        streamed_from_model = False
        yield sse_event("meta", {"conversation_id": conversation_id})
        try:
            with SessionLocal() as db:
                prepared = await run_in_threadpool(prepare_stream_state, db, question, history, model, local_model)
                if "direct" in prepared:
                    final = dict(prepared["direct"])
                    parts.append(final["answer"])
                    yield sse_event("delta", {"text": final["answer"]})
                else:
                    streamed_from_model = True
                    try:
                        async for chunk in stream_model(prepared["messages"], prepared["requested_model"], prepared.get("local_model")):
                            parts.append(chunk)
                            yield sse_event("delta", {"text": chunk})
                    except LocalModelError as exc:
                        error = str(exc)
                    if not error:
                        text = "".join(parts)
                        if text.strip():
                            final = {"answer": text, "sources": prepared["sources"], "tool_calls": [], "mode": "llm"}
                        else:
                            fallback = prepared["fallback"]
                            final = {**fallback, "sources": prepared["sources"], "tool_calls": []}
                            parts.append(fallback["answer"])
                            yield sse_event("delta", {"text": fallback["answer"]})
        except Exception:
            logger.exception("Streamed chat failed for conversation %s", conversation_id)
            error = error or "生成回答时发生错误，请稍后重试。"
        finally:
            persist_stream_exchange(conversation_id, question, "".join(parts), final, error, streamed_from_model)
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
            "title": first_user.content.strip().splitlines()[0][:40] if first_user else "新对话",
            "message_count": len(rows),
            "updated_at": iso_utc(rows[-1].created_at or conversation.created_at),
        })
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return items[:limit]


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
    return {"id": conversation_id, "messages": [{"role": row.role, "content": row.content, "created_at": row.created_at, **(row.result_data or {})} for row in rows]}


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


@app.get("/api/plugins/catalog")
def list_plugin_catalog(db: Session = Depends(get_db)):
    return catalog_list(db)


@app.post("/api/plugins/catalog/install", dependencies=[Depends(require_admin)])
def install_catalog_plugin(body: dict, db: Session = Depends(get_db)):
    plugin_id = body.get("id")
    if not isinstance(plugin_id, str):
        raise HTTPException(422, "缺少插件编号")
    return plugin_json(install_curated_plugin(db, plugin_id))


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
    if not isinstance(source, str):
        raise HTTPException(422, "缺少插件清单地址")
    try:
        manifest = PluginCreate.model_validate(fetch_plugin_json(source, max_bytes=100_000))
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
BACKUP_CONFIG_FILES = ("workspace.json", "model-providers.json", "campus-sources.json", ".env")
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
        ensure_conversation_client_id()
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
