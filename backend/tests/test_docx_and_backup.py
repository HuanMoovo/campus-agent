"""Offline coverage for Word (.docx) uploads and the backup export/import endpoints."""
import atexit
import json
import os
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

_test_data = tempfile.TemporaryDirectory(prefix="campus-docx-backup-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app import main as main_module
from app.db import engine
from app.main import app


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)

HEADERS = {"X-Admin-Token": "test-admin-token"}


def use_temp_data_dir(monkeypatch, tmp_path):
    """Keep restored config files out of the real backend data directory."""
    settings = SimpleNamespace(**{**vars(main_module.get_settings()), "data_dir": Path(tmp_path)})
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    return Path(tmp_path)


def make_docx(paragraphs):
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>' for text in paragraphs)
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>'
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def zip_bytes(entries):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_docx_upload_extracts_paragraph_text():
    with TestClient(app) as client:
        raw = make_docx(["补办校园一卡通需要：", "1. 学生证", "2. 书面申请", ""])
        created = client.post("/api/documents/upload", headers=HEADERS, files={
            "file": ("policy.docx", raw, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        assert created.status_code == 200
        payload = created.json()
        assert payload["content"] == "补办校园一卡通需要：\n1. 学生证\n2. 书面申请"
        assert payload["title"] == "policy.docx"
        assert client.delete(f"/api/documents/{payload['id']}", headers=HEADERS).status_code == 200


def test_legacy_doc_and_unreadable_docx_are_rejected():
    with TestClient(app) as client:
        legacy = client.post("/api/documents/upload", headers=HEADERS,
                             files={"file": ("old.doc", b"\xd0\xcf\x11\xe0legacy-binary", "application/msword")})
        assert legacy.status_code == 400
        broken = client.post("/api/documents/upload", headers=HEADERS,
                             files={"file": ("broken.docx", b"definitely not a zip", "application/zip")})
        assert broken.status_code == 400
        empty = client.post("/api/documents/upload", headers=HEADERS,
                            files={"file": ("empty.docx", make_docx([""]), "application/zip")})
        assert empty.status_code == 400
        assert "没有可提取的文本" in empty.json()["detail"]


def test_backup_export_requires_admin_and_carries_a_manifest(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/backup/export").status_code == 401
        response = client.get("/api/backup/export", headers=HEADERS)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("mens-backup.json"))
            database = archive.read("campus.db")
        assert {"mens-backup.json", "campus.db"} <= names
        assert manifest["app"] == "Mens" and manifest["format"] == 1
        assert manifest["database"] == "sqlite"
        assert manifest["files"]["campus.db"]["size"] == len(database) > 0


def test_backup_round_trip_restores_deleted_conversations(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    client_id = f"backup-{uuid4()}"
    with TestClient(app) as client:
        created = client.post("/api/chat", json={"message": "查询我的课表", "client_id": client_id}).json()
        exported = client.get("/api/backup/export", headers=HEADERS)
        assert exported.status_code == 200
        assert client.delete(f"/api/conversations/{created['conversation_id']}",
                             params={"client_id": client_id}).status_code == 200
        assert client.get(f"/api/conversations/{created['conversation_id']}").status_code == 404
        restored = client.post("/api/backup/import", headers=HEADERS,
                               files={"file": ("mens-backup.zip", exported.content, "application/zip")})
        assert restored.status_code == 200
        body = restored.json()
        assert "campus.db" in body["restored"] and body["failed"] == []
        history = client.get(f"/api/conversations/{created['conversation_id']}")
        assert history.status_code == 200
        assert [row["role"] for row in history.json()["messages"]] == ["user", "assistant"]


def test_backup_import_restores_configuration_files(monkeypatch, tmp_path):
    data_dir = use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        exported = client.get("/api/backup/export", headers=HEADERS)
        assert exported.status_code == 200
        (data_dir / "model-providers.json").write_text('{"qwen": {"api_key_ref": "stored"}}', encoding="utf-8")
        with ZipFile(BytesIO(exported.content)) as archive:
            entries = [(name, archive.read(name)) for name in archive.namelist()]
        enriched = zip_bytes([*entries, ("model-providers.json", b'{"qwen": {"model": "restored"}}'),
                              ("workspace.json", b'{"appearance": "dark"}')])
        restored = client.post("/api/backup/import", headers=HEADERS,
                               files={"file": ("mens-backup.zip", enriched, "application/zip")})
        assert restored.status_code == 200
        body = restored.json()
        assert set(body["restored"]) >= {"campus.db", "model-providers.json", "workspace.json"}
        assert body["restart_required"] is True
        assert (data_dir / "model-providers.json").read_text(encoding="utf-8") == '{"qwen": {"model": "restored"}}'
        assert (data_dir / "workspace.json").read_text(encoding="utf-8") == '{"appearance": "dark"}'


def test_backup_import_rejects_foreign_or_unsafe_archives(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    manifest = json.dumps({"app": "Mens", "format": 1})
    with TestClient(app) as client:
        survivor = client.post("/api/chat", json={"message": "查询我的学分", "client_id": "import-guard"}).json()
        assert client.post("/api/backup/import", headers=HEADERS,
                           files={"file": ("x.zip", b"not a zip", "application/zip")}).status_code == 400
        assert client.post("/api/backup/import", headers=HEADERS, files={
            "file": ("x.zip", zip_bytes([("mens-backup.json", json.dumps({"app": "Mens", "format": 99}))]), "application/zip")}).status_code == 400
        assert client.post("/api/backup/import", headers=HEADERS, files={
            "file": ("x.zip", zip_bytes([("mens-backup.json", manifest), ("../evil.txt", "x")]), "application/zip")}).status_code == 400
        assert client.post("/api/backup/import", headers=HEADERS, files={
            "file": ("x.zip", zip_bytes([("notes.txt", "x")]), "application/zip")}).status_code == 400
        assert client.post("/api/backup/import", headers=HEADERS, files={
            "file": ("x.zip", zip_bytes([("mens-backup.json", manifest), ("campus.db", b"not a database")]), "application/zip")}).status_code == 400
        # A rejected import must leave the live database untouched.
        assert client.get(f"/api/conversations/{survivor['conversation_id']}").status_code == 200
        listed = client.get("/api/conversations", params={"client_id": "import-guard"}).json()
        assert [row["id"] for row in listed] == [survivor["conversation_id"]]
