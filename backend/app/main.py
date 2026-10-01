from contextlib import asynccontextmanager
import secrets
import logging
from io import BytesIO
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .agent import run_agent
from . import campus_data
from .config import get_settings
from .desktop_runtime import desktop_enabled, install_desktop_routes
from .db import Base, SessionLocal, engine, get_db
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
    with SessionLocal() as db:
        seed_demo_documents(db)
    yield


app = FastAPI(title="Mens API", version="1.0.0", lifespan=lifespan)
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
    if body.conversation_id:
        conversation = db.get(Conversation, body.conversation_id)
        if conversation is None:
            raise HTTPException(404, "对话不存在")
    else:
        conversation = Conversation(id=str(uuid4()))
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
    if suffix not in {"txt", "md", "pdf"}:
        raise HTTPException(400, "仅支持 TXT、Markdown 和 PDF")
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(413, "文件超过 5 MB")
    try:
        if suffix == "pdf":
            from pypdf import PdfReader
            content = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(raw)).pages)
        else:
            content = raw.decode("utf-8-sig")
    except Exception as exc:
        raise HTTPException(400, "文件无法解析") from exc
    if not content.strip():
        raise HTTPException(400, "文档没有可提取的文本")
    if len(content) > 500_000:
        raise HTTPException(413, "文档文本超过 50 万字符，请拆分上传")
    return filename[:255], content


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


install_desktop_routes(app)
