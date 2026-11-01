"""Desktop authorization still scopes copy-only imported materials."""
import base64
import hashlib
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import project_api
from app.project_changes import ProjectChangeStore
from app.project_files import ProjectRegistry
from app.project_recovery_backup import ProjectRecoveryArchive

TOKEN, GRANT, WRITE = "a" * 64, "b" * 64, "c" * 64


def test_archive_routes_scope_current_physical_root_and_never_offer_write(monkeypatch, tmp_path):
    for name, value in {"CAMPUS_DESKTOP_MODE": "1", "CAMPUS_DESKTOP_TOKEN": TOKEN,
                        "CAMPUS_DESKTOP_PORT": "8395", "CAMPUS_PROJECT_GRANT_TOKEN": GRANT,
                        "CAMPUS_PROJECT_WRITE_TOKEN": WRITE}.items():
        monkeypatch.setenv(name, value)
    registry = ProjectRegistry()
    store = ProjectRecoveryArchive(tmp_path / "archive")
    changes = ProjectChangeStore(tmp_path / "live-journal")
    monkeypatch.setattr(project_api, "registry", registry)
    monkeypatch.setattr(project_api, "changes", changes)
    # Fails until the archive reader is integrated; normal originals still use changes.
    monkeypatch.setattr(project_api, "archives", store, raising=False)
    folder = tmp_path / "synthetic-selected-project"
    folder.mkdir()
    target = folder / "README.md"
    target.write_bytes(b"current project text\n")
    other = tmp_path / "synthetic-other-project"
    other.mkdir()
    app = FastAPI()
    app.include_router(project_api.router)
    with TestClient(app, base_url="http://127.0.0.1:8395", client=("127.0.0.1", 12345),
                    headers={"X-Campus-Desktop-Token": TOKEN}) as client:
        opened = client.post("/api/projects/open", json={"path": str(folder)},
                             headers={"X-Campus-Project-Grant": GRANT})
        assert opened.status_code == 200
        project_id = opened.json()["project"]["id"]
        raw = b"\xef\xbb\xbforiginal\r\n"
        store.insert([{"root_key": list(registry.physical_identity(project_id)), "path": "README.md",
                       "summary": "Imported original", "created_at": "2026-10-31T08:00:00Z",
                       "sha256": hashlib.sha256(raw).hexdigest(), "original_base64": base64.b64encode(raw).decode()}])
        listed = client.get(f"/api/projects/{project_id}/changes")
        assert listed.status_code == 200
        assert listed.json()["records"] == []
        entries = listed.json().get("archives", [])
        assert len(entries) == 1
        archive_id = entries[0]["archive_id"]
        assert set(entries[0]) == {"archive_id", "path", "summary", "created_at", "size_bytes"}
        monkeypatch.setattr(changes, "original", lambda *args: pytest.fail("archive ID reached live journal reader"))
        copied = client.get(f"/api/projects/{project_id}/changes/{archive_id}/original")
        assert copied.status_code == 200
        assert copied.json() == {"text": "original\r\n", "bom": True, "newline": "crlf"}
        assert client.get(f"/api/projects/{project_id}/changes/{archive_id}/original",
                          headers={"X-Campus-Desktop-Token": ""}).status_code == 403
        monkeypatch.setattr(changes, "prepare", lambda *args: pytest.fail("archive ID reached live prepare"))
        monkeypatch.setattr(changes, "commit", lambda *args: pytest.fail("archive ID reached live commit"))
        for action in ("apply", "revert", "keep"):
            body = {"subject_id": archive_id, "action": action}
            prepared = client.post(f"/api/projects/{project_id}/changes/prepare", json=body,
                                   headers={"X-Campus-Project-Write": WRITE})
            assert prepared.status_code == 422
            committed = client.post(f"/api/projects/{project_id}/changes/commit", json={
                **body, "digest": "d" * 64, "operation_id": str(uuid4())},
                headers={"X-Campus-Project-Write": WRITE})
            assert committed.status_code == 422
        assert target.read_bytes() == b"current project text\n"
        assert client.delete(f"/api/projects/{project_id}").status_code == 200
        selected_other = client.post("/api/projects/open", json={"path": str(other)},
                                     headers={"X-Campus-Project-Grant": GRANT}).json()["project"]["id"]
        assert client.get(f"/api/projects/{selected_other}/changes").json()["archives"] == []
        assert client.get(f"/api/projects/{selected_other}/changes/{archive_id}/original").status_code == 404
        assert client.get(f"/api/projects/{project_id}/changes/{archive_id}/original").status_code == 404
        assert client.delete(f"/api/projects/{selected_other}").status_code == 200
