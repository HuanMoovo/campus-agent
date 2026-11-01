"""Desktop-only project routes; native picker grants and renderer reads differ."""
import os
import re
import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .desktop_runtime import desktop_enabled, request_is_authorized
from .project_files import MAX_CONTEXT_CHARS, MAX_FILES, ProjectFileError, ProjectRegistry
from .project_proposals import ProjectProposalStore
from .project_changes import ProjectChangeStore
from .project_recovery_backup import ProjectRecoveryArchive
from .provider_catalog import ModelPreference
from .schemas import ProjectSelection, RequestModel
from .token_usage import UsageIdentity, capture_usage


router = APIRouter(prefix="/api/projects", tags=["projects"])
registry = ProjectRegistry()
proposals = ProjectProposalStore()
changes = ProjectChangeStore()
archives = ProjectRecoveryArchive()


class ProjectOpenRequest(RequestModel):
    path: str = Field(min_length=1, max_length=4096)


class ProjectReadRequest(RequestModel):
    path: str = Field(min_length=1, max_length=2048)


class ProjectProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    path: str = Field(min_length=1, max_length=2048)
    instruction: str = Field(min_length=1, max_length=4000)
    model: ModelPreference = "auto"
    local_model: str | None = Field(default=None, min_length=1, max_length=128,
                                    pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
    reasoning: Literal["auto", "fast", "deep", "low", "medium", "high", "xhigh", "max"] | None = None

    @field_validator("instruction")
    @classmethod
    def nonempty_instruction(cls, value):
        if not value.strip():
            raise ValueError("请填写修改要求。")
        return value.strip()

    @model_validator(mode="after")
    def local_requires_ollama(self):
        if self.local_model is not None and self.model != "ollama":
            raise ValueError("指定本地模型时，model 必须为 ollama")
        return self


class ProjectChangePrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    action: Literal["apply", "revert", "keep"]


class ProjectChangeCommitRequest(ProjectChangePrepareRequest):
    digest: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    operation_id: str = Field(pattern=r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$")


def _available():
    return (desktop_enabled()
            and re.fullmatch(r"[a-fA-F0-9]{64}", os.environ.get("CAMPUS_PROJECT_GRANT_TOKEN", "")) is not None
            and re.fullmatch(r"[a-fA-F0-9]{32,256}", os.environ.get("CAMPUS_DESKTOP_TOKEN", "")) is not None)


def _require_desktop(request):
    try:
        port = int(os.environ.get("CAMPUS_DESKTOP_PORT", "0"))
    except ValueError:
        port = 0
    if not _available() or not request_is_authorized(request.scope, os.environ.get("CAMPUS_DESKTOP_TOKEN", ""), port):
        raise HTTPException(403, "请在桌面端通过目录选择器打开项目。")


def _result(operation, *args):
    try:
        return operation(*args)
    except ProjectFileError as exc:
        raise HTTPException(exc.status_code, exc.message, headers={"X-Project-Error": exc.error_code}) from None


def _changes_available():
    info = registry.status()
    return bool(info and re.fullmatch(r"[a-fA-F0-9]{64}", os.environ.get("CAMPUS_PROJECT_WRITE_TOKEN", ""))
                and _result(registry.changes_supported, info["id"]))


def _require_write(request):
    _require_desktop(request)
    secret = os.environ.get("CAMPUS_PROJECT_WRITE_TOKEN", "")
    headers = request.headers.getlist("X-Campus-Project-Write")
    if (re.fullmatch(r"[a-fA-F0-9]{64}", secret) is None or len(headers) != 1
            or not secrets.compare_digest(headers[0].encode("utf-8"), secret.encode("ascii"))):
        raise HTTPException(403, "修改操作必须通过桌面端逐次确认。")


def _status():
    return {"available": True, "project": registry.status(), "changes_available": _changes_available(),
            "limits": {"max_files": MAX_FILES, "max_context_chars": MAX_CONTEXT_CHARS}}


@router.get("")
def project_status(request: Request):
    if not _available():
        return {"available": False, "project": None, "changes_available": False,
                "limits": {"max_files": MAX_FILES, "max_context_chars": MAX_CONTEXT_CHARS}}
    _require_desktop(request)
    return _status()


@router.post("/open")
def open_project(body: ProjectOpenRequest, request: Request):
    _require_desktop(request)
    grants = request.headers.getlist("X-Campus-Project-Grant")
    secret = os.environ["CAMPUS_PROJECT_GRANT_TOKEN"]
    if len(grants) != 1 or not secrets.compare_digest(grants[0].encode("utf-8"), secret.encode("ascii")):
        raise HTTPException(403, "项目目录必须由桌面选择器授权。")
    with registry.grant_transaction():
        info = _result(registry.open, body.path)
        proposals.retain_project(info["id"])
    return _status()


@router.get("/{project_id}/files")
def list_project_files(project_id: str, request: Request, path: str = Query(default="", max_length=2048)):
    _require_desktop(request)
    return _result(registry.list_files, project_id, path)


@router.post("/{project_id}/read")
def read_project_file(project_id: str, body: ProjectReadRequest, request: Request):
    _require_desktop(request)
    return _result(registry.read_file, project_id, body.path)


@router.post("/{project_id}/proposals")
def create_project_proposal(project_id: str, body: ProjectProposalRequest, request: Request):
    _require_desktop(request)
    with capture_usage(UsageIdentity(None, "", desktop=True), "project_proposal"):
        return _result(proposals.create, registry, project_id, body.path, body.instruction,
                       body.model, body.local_model, body.reasoning)


@router.get("/{project_id}/proposals/{proposal_id}")
def review_project_proposal(project_id: str, proposal_id: str, request: Request):
    _require_desktop(request)
    return _result(proposals.get, registry, project_id, proposal_id)


def _reject_archive_write(subject_id):
    if subject_id.startswith("backup_"):
        raise HTTPException(422, "备份原文仅供复制，不能执行项目修改。",
                            headers={"X-Project-Error": "project_archive_read_only"})


@router.post("/{project_id}/changes/prepare")
def prepare_project_change(project_id: str, body: ProjectChangePrepareRequest, request: Request):
    _require_write(request)
    _reject_archive_write(body.subject_id)
    return _result(changes.prepare, registry, proposals, project_id, body.subject_id, body.action)


@router.post("/{project_id}/changes/commit")
def commit_project_change(project_id: str, body: ProjectChangeCommitRequest, request: Request):
    _require_write(request)
    _reject_archive_write(body.subject_id)
    return _result(changes.commit, registry, proposals, project_id, body.subject_id, body.action, body.digest, body.operation_id)


@router.get("/{project_id}/changes/operations/{operation_id}")
def project_change_operation(project_id: str, operation_id: str, request: Request):
    _require_desktop(request)
    return _result(changes.operations, registry, project_id, operation_id)


@router.get("/{project_id}/changes")
def project_changes(project_id: str, request: Request):
    _require_desktop(request)
    with registry.grant_transaction():
        result = _result(changes.list_changes, registry, project_id)
        result["archives"] = _result(archives.list_archives, registry, project_id)
        return result


@router.get("/{project_id}/changes/{recovery_id}/original")
def project_change_original(project_id: str, recovery_id: str, request: Request):
    _require_desktop(request)
    reader = archives.original if recovery_id.startswith("backup_") else changes.original
    return _result(reader, registry, project_id, recovery_id)


@router.delete("/{project_id}")
def close_project(project_id: str, request: Request):
    _require_desktop(request)
    with registry.grant_transaction():
        _result(registry.close, project_id)
        proposals.retain_project(None)
    return {"ok": True}


def resolve_project_sources(request: Request, selection: ProjectSelection | None):
    """Read current server-owned files once, before creating any conversation."""
    if selection is None:
        return []
    _require_desktop(request)
    rows = _result(registry.sources, selection.id, selection.files)
    for row in rows:
        row["title"] = f"{row['path']}:L{row['start_line']}-L{row['end_line']}"
    return rows


def project_question_label(question, selection: ProjectSelection | None):
    if selection is None:
        return question
    return question + "\n\n[项目文件] " + "、".join(selection.files)
