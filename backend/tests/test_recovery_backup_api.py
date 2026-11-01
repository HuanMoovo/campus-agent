"""Offline backup integrity, portability and publication tests."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import warnings
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from test_docx_and_backup import HEADERS, app, main_module, use_temp_data_dir, zip_bytes
from app import project_recovery_backup as recovery

RAW = b"\xef\xbb\xbf  original\r\n\r\n"


def material(**updates):
    return {"root_key": [12, 34], "path": "src/main.py", "summary": "Selected original",
            "created_at": "2026-10-31T08:00:00+00:00", "sha256": hashlib.sha256(RAW).hexdigest(),
            "original_base64": base64.b64encode(RAW).decode("ascii"), **updates}


def make_backup(payloads, version=2, metadata=None):
    files = {name: {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in payloads.items()}
    manifest = {"app": "Mens", "format": version, "files": files if metadata is None else metadata}
    return zip_bytes([("mens-backup.json", json.dumps(manifest)), *payloads.items()])


def upload(client, raw):
    return client.post("/api/backup/import", headers=HEADERS,
                       files={"file": ("synthetic.zip", raw, "application/zip")})


def test_opt_in_export_and_import_reexports_exact_originals(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    source = recovery.ProjectRecoveryArchive(tmp_path)
    source.insert([material()])
    with TestClient(app) as client:
        plain = client.get("/api/backup/export", headers=HEADERS)
        with ZipFile(BytesIO(plain.content)) as archive:
            assert "project-recovery.json" not in archive.namelist()
            assert json.loads(archive.read("mens-backup.json"))["format"] == 1
        included = client.get("/api/backup/export?include_project_recoveries=true", headers=HEADERS)
        assert included.status_code == 200
        with ZipFile(BytesIO(included.content)) as archive:
            manifest = json.loads(archive.read("mens-backup.json"))
            assert manifest["format"] == 2
            assert json.loads(archive.read("project-recovery.json")) == {"materials": [material()]}
        destination = tmp_path / "imported"
        use_temp_data_dir(monkeypatch, destination)
        imported = upload(client, included.content)
        assert imported.status_code == 200, imported.text
        assert imported.json()["project_recoveries"] == {"imported": 1, "duplicates": 0}
        assert upload(client, included.content).json()["project_recoveries"] == {"imported": 0, "duplicates": 1}
        assert recovery.export_materials(destination) == [material()]
        assert not (destination / "project-changes.sqlite3").exists()


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("metadata", [
    {"workspace.json": {"size": 2, "sha256": "0" * 64}},
    {"workspace.json": {"size": 3, "sha256": hashlib.sha256(b"{}").hexdigest()}},
    {"missing.json": {"size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}},
])
def test_declared_manifest_integrity_fails_before_config_mutation(monkeypatch, tmp_path, version, metadata):
    use_temp_data_dir(monkeypatch, tmp_path)
    target = tmp_path / "workspace.json"
    target.write_bytes(b"old")
    with TestClient(app) as client:
        result = upload(client, make_backup({"workspace.json": b"{}"}, version, metadata))
        assert result.status_code == 400
    assert target.read_bytes() == b"old"


def test_format_two_requires_exact_manifest_but_legacy_unlisted_configs_work(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        assert upload(client, make_backup({"workspace.json": b"{}"}, 2, {})).status_code == 400
        assert upload(client, make_backup({"workspace.json": b"{}"}, 1, {})).status_code == 200


def test_duplicate_zip_entries_and_oversized_expansion_rejected(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate = zip_bytes([("mens-backup.json", '{"app":"Mens","format":1}'),
                                   ("workspace.json", "first"), ("workspace.json", "second")])
        assert upload(client, duplicate).status_code == 400
        # Small compressed upload, uncompressed contents beyond configured budget.
        monkeypatch.setattr(main_module, "BACKUP_MAX_BYTES", 2048)
        from zipfile import ZIP_DEFLATED
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("mens-backup.json", '{"app":"Mens","format":1}')
            archive.writestr("workspace.json", b"x" * 2049)
        assert upload(client, stream.getvalue()).status_code == 400
    assert not (tmp_path / "workspace.json").exists()


def test_invalid_material_fails_before_any_config_or_application_change(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    target = tmp_path / "workspace.json"
    target.write_bytes(b"old")
    data = json.dumps({"materials": [material(sha256="0" * 64)]}).encode()
    with TestClient(app) as client:
        exported = client.get("/api/backup/export", headers=HEADERS)
        with ZipFile(BytesIO(exported.content)) as archive:
            database = archive.read("campus.db")
        before_database = Path(main_module.sqlite_database_path()).read_bytes()
        result = upload(client, make_backup({"campus.db": database, "workspace.json": b"new", "project-recovery.json": data}))
        assert result.status_code == 400
        assert Path(main_module.sqlite_database_path()).read_bytes() == before_database
    assert target.read_bytes() == b"old"
    assert not (tmp_path / recovery.ARCHIVE_FILE).exists()


@pytest.mark.parametrize("malformation", ["trigger", "view", "wrong_columns", "virtual", "expression"])
def test_uploaded_schema_rejected_before_app_mutation(monkeypatch, tmp_path, malformation):
    use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        exported = client.get("/api/backup/export", headers=HEADERS)
        with ZipFile(BytesIO(exported.content)) as archive:
            database = archive.read("campus.db")
        malicious = tmp_path / "synthetic-schema.db"
        malicious.write_bytes(database)
        with sqlite3.connect(malicious) as db:
            if malformation == "trigger":
                db.execute("CREATE TRIGGER uploaded_trigger AFTER INSERT ON documents BEGIN DELETE FROM conversations; END")
            elif malformation == "view":
                db.execute("CREATE VIEW uploaded_view AS SELECT * FROM conversations")
            elif malformation == "wrong_columns":
                db.execute("DROP TABLE documents")
                db.execute("CREATE TABLE documents (id TEXT)")
            elif malformation == "virtual":
                db.execute("CREATE VIRTUAL TABLE uploaded_virtual USING fts5(content)")
            else:
                db.execute("CREATE INDEX uploaded_expression ON documents(lower(title))")
        before = Path(main_module.sqlite_database_path()).read_bytes()
        result = upload(client, make_backup({"campus.db": malicious.read_bytes(), "workspace.json": b"new"}, version=1))
        assert result.status_code == 400, result.text
        assert Path(main_module.sqlite_database_path()).read_bytes() == before
    assert not (tmp_path / "workspace.json").exists()


def test_concurrent_exports_use_isolated_snapshots_and_leave_no_temporary_files(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: client.get("/api/backup/export", headers=HEADERS), range(8)))
        assert all(row.status_code == 200 for row in responses)
        for row in responses:
            with ZipFile(BytesIO(row.content)) as archive:
                assert json.loads(archive.read("mens-backup.json"))["files"]["campus.db"]["size"] > 0
    assert not list(tmp_path.glob(".mens-*"))


def test_archive_quota_rejected_before_database_or_config_publication(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(recovery, "MAX_MATERIALS", 1)
    store = recovery.ProjectRecoveryArchive(tmp_path)
    store.insert([material()])
    target = tmp_path / "workspace.json"
    target.write_bytes(b"old")
    with TestClient(app) as client:
        exported = client.get("/api/backup/export", headers=HEADERS)
        with ZipFile(BytesIO(exported.content)) as archive:
            database = archive.read("campus.db")
        before = Path(main_module.sqlite_database_path()).read_bytes()
        more = json.dumps({"materials": [material(path="other.py")]}).encode()
        result = upload(client, make_backup({"campus.db": database, "workspace.json": b"new", "project-recovery.json": more}))
        assert result.status_code == 400
        assert Path(main_module.sqlite_database_path()).read_bytes() == before
    assert target.read_bytes() == b"old"
    assert recovery.export_materials(tmp_path) == [material()]


def test_combined_material_export_limit_leaves_ordinary_export_usable(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    recovery.ProjectRecoveryArchive(tmp_path).insert([material(), material(path="other.py")])
    monkeypatch.setattr(recovery, "MAX_MATERIALS", 1)
    with TestClient(app) as client:
        assert client.get("/api/backup/export?include_project_recoveries=true", headers=HEADERS).status_code == 400
        assert client.get("/api/backup/export", headers=HEADERS).status_code == 200


def test_backup_rejects_oversized_manifest_and_unsupported_compression(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    from app import backup_archive
    monkeypatch.setattr(backup_archive, "MANIFEST_MAX_BYTES", 32)
    with TestClient(app) as client:
        oversized = zip_bytes([("mens-backup.json", json.dumps({"app": "Mens", "format": 1, "padding": "x" * 64}))])
        assert upload(client, oversized).status_code == 400
        from zipfile import ZIP_BZIP2
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_BZIP2) as archive:
            archive.writestr("mens-backup.json", '{"app":"Mens","format":1}')
        assert upload(client, stream.getvalue()).status_code == 400
    assert not (tmp_path / "workspace.json").exists()


def test_total_uncompressed_budget_rejected_before_publication(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module, "BACKUP_MAX_BYTES", 2048)
    from zipfile import ZIP_DEFLATED
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("mens-backup.json", '{"app":"Mens","format":1}')
        archive.writestr("workspace.json", b"x" * 1100)
        archive.writestr("model-providers.json", b"y" * 1100)
    with TestClient(app) as client:
        assert upload(client, stream.getvalue()).status_code == 400
    assert not (tmp_path / "workspace.json").exists()
    assert not (tmp_path / "model-providers.json").exists()


def test_configuration_runtime_failure_is_reported_and_temporary_paths_cleaned(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    original_replace = main_module.os.replace
    def fail_workspace(source, destination):
        if Path(destination).name == "workspace.json":
            raise OSError("synthetic publication failure")
        return original_replace(source, destination)
    monkeypatch.setattr(main_module.os, "replace", fail_workspace)
    with TestClient(app) as client:
        result = upload(client, make_backup({"workspace.json": b"{}", "web-search.json": b"{}"}))
        assert result.status_code == 200
        assert result.json() == {"restored": ["web-search.json"], "failed": ["workspace.json"], "restart_required": False}
    assert not list(tmp_path.glob(".mens-*"))


def test_legacy_database_with_additive_columns_missing_is_migrated_using_trusted_schema(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    with TestClient(app) as client:
        exported = client.get("/api/backup/export", headers=HEADERS)
        with ZipFile(BytesIO(exported.content)) as archive:
            database = archive.read("campus.db")
        legacy = tmp_path / "synthetic-legacy.db"
        legacy.write_bytes(database)
        with sqlite3.connect(legacy) as db:
            db.execute("DROP INDEX IF EXISTS ix_conversations_client_id")
            db.execute("DROP INDEX IF EXISTS ix_conversations_owner_user_id")
            for column in ("client_id", "owner_user_id", "title", "pinned"):
                db.execute("ALTER TABLE conversations DROP COLUMN " + column)
        imported = upload(client, make_backup({"campus.db": legacy.read_bytes()}, version=1))
        assert imported.status_code == 200, imported.text
        assert imported.json()["restored"] == ["campus.db"]
        with sqlite3.connect(main_module.sqlite_database_path()) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(conversations)")}
        assert {"client_id", "owner_user_id", "title", "pinned"} <= columns


def test_optional_export_checks_serialized_bundle_size(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    recovery.ProjectRecoveryArchive(tmp_path).insert([material()])
    monkeypatch.setattr(main_module, "MAX_BUNDLE_BYTES", 16, raising=False)
    with TestClient(app) as client:
        assert client.get("/api/backup/export?include_project_recoveries=true", headers=HEADERS).status_code == 400
        assert client.get("/api/backup/export", headers=HEADERS).status_code == 200


def test_zip_directory_attribute_rejected_even_without_trailing_slash(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    from zipfile import ZipInfo
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        info = ZipInfo("mens-backup.json")
        info.create_system = 0
        info.external_attr = 0x10
        archive.writestr(info, '{"app":"Mens","format":1}')
    with TestClient(app) as client:
        assert upload(client, stream.getvalue()).status_code == 400


@pytest.mark.parametrize("field,value", [
    ("date", "not-a-date"), ("json", "{broken"), ("json", "[1]"),
    ("text", sqlite3.Binary(b"binary text")), ("boolean", "not-a-boolean"),
])
def test_invalid_database_row_values_cannot_replace_readable_application_state(monkeypatch, tmp_path, field, value):
    use_temp_data_dir(monkeypatch, tmp_path)
    target = tmp_path / "workspace.json"
    target.write_bytes(b"old")
    with TestClient(app) as client:
        exported = client.get("/api/backup/export", headers=HEADERS)
        with ZipFile(BytesIO(exported.content)) as archive:
            database = archive.read("campus.db")
        malformed = tmp_path / "synthetic-row.db"
        malformed.write_bytes(database)
        with sqlite3.connect(malformed) as db:
            db.execute("INSERT INTO conversations (id,client_id,pinned,created_at) VALUES ('synthetic-cid','synthetic',0,'2026-10-31 08:00:00')")
            db.execute("INSERT INTO messages (conversation_id,role,content,result_data,created_at) VALUES ('synthetic-cid','assistant','text','{}','2026-10-31 08:00:00')")
            if field == "date":
                db.execute("UPDATE documents SET created_at=?", (value,))
            elif field == "json":
                db.execute("UPDATE messages SET result_data=? WHERE conversation_id='synthetic-cid'", (value,))
            elif field == "text":
                db.execute("UPDATE documents SET title=?", (value,))
            else:
                db.execute("UPDATE conversations SET pinned=? WHERE id='synthetic-cid'", (value,))
        before = Path(main_module.sqlite_database_path()).read_bytes()
        materials = json.dumps({"materials": [material()]}).encode()
        result = upload(client, make_backup({"campus.db": malformed.read_bytes(), "workspace.json": b"new", "project-recovery.json": materials}))
        if result.status_code != 400:
            # Keep each parameter independent even while demonstrating the red case.
            rollback = tmp_path / "synthetic-before.db"
            rollback.write_bytes(database)
            from contextlib import closing
            with closing(sqlite3.connect(rollback)) as source, closing(sqlite3.connect(main_module.sqlite_database_path())) as live:
                source.backup(live)
        assert result.status_code == 400, result.text
        assert Path(main_module.sqlite_database_path()).read_bytes() == before
        assert target.read_bytes() == b"old"
        assert not (tmp_path / recovery.ARCHIVE_FILE).exists()


def test_configuration_staging_failure_reports_that_file_and_restores_other_configs(monkeypatch, tmp_path):
    use_temp_data_dir(monkeypatch, tmp_path)
    original_write = Path.write_bytes
    def fail_workspace_stage(path, data):
        if path.name == "workspace.json" and path.parent.name.startswith(".mens-restore-"):
            raise OSError("synthetic staging failure")
        return original_write(path, data)
    monkeypatch.setattr(Path, "write_bytes", fail_workspace_stage)
    with TestClient(app) as client:
        result = upload(client, make_backup({"workspace.json": b"{}", "web-search.json": b"{}"}))
        assert result.status_code == 200
        assert result.json() == {"restored": ["web-search.json"], "failed": ["workspace.json"], "restart_required": False}
    assert (tmp_path / "web-search.json").read_bytes() == b"{}"
    assert not (tmp_path / "workspace.json").exists()
    assert not list(tmp_path.glob(".mens-*"))
