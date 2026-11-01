"""Copy-only backup materials use synthetic bytes and physical identities."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import sqlite3

import pytest

from app import project_recovery_backup as recovery
from app.project_files import ProjectFileError

RAW = b"\xef\xbb\xbf  original\r\n\r\n"


def material(raw=RAW, **updates):
    value = {"root_key": [12, 34], "path": "src/main.py", "summary": "Selected original",
             "created_at": "2026-10-31T08:00:00+00:00", "sha256": hashlib.sha256(raw).hexdigest(),
             "original_base64": base64.b64encode(raw).decode("ascii")}
    return {**value, **updates}


def bundle(rows):
    return json.dumps({"materials": rows}, ensure_ascii=False).encode("utf-8")


class Registry:
    root = (12, 34)

    @contextmanager
    def grant_transaction(self):
        yield

    def physical_identity(self, project_id):
        if project_id != "selected":
            raise ProjectFileError("project_not_open", "Not selected", 404)
        return self.root


def test_archive_roundtrip_dedup_and_physical_root_scope(tmp_path):
    store = recovery.ProjectRecoveryArchive(tmp_path)
    rows = recovery.validate_bundle(bundle([material(), material()]))
    assert store.insert(rows) == {"imported": 1, "duplicates": 1}
    assert store.insert(rows) == {"imported": 0, "duplicates": 2}
    registry = Registry()
    listed = store.list_archives(registry, "selected")
    assert len(listed) == 1
    entry = listed[0]
    assert set(entry) == {"archive_id", "path", "summary", "created_at", "size_bytes"}
    assert entry["archive_id"].startswith("backup_") and entry["size_bytes"] == len(RAW)
    assert store.original(registry, "selected", entry["archive_id"]) == {
        "text": "  original\r\n\r\n", "bom": True, "newline": "crlf"}
    registry.root = (12, 35)
    assert store.list_archives(registry, "selected") == []
    with pytest.raises(ProjectFileError) as error:
        store.original(registry, "selected", entry["archive_id"])
    assert error.value.status_code == 404
    assert recovery.export_materials(tmp_path) == rows[:1]
    assert not (tmp_path / "project-changes.sqlite3").exists()


@pytest.mark.parametrize("updates", [
    {"root_key": [True, 1]}, {"root_key": "[12,34]"}, {"root_key": [-1, 34]},
    {"root_key": [12, 34, 56]}, {"root_key": [12, 2 ** 64]}, {"path": "../secret.py"}, {"path": "C:/file.py"},
    {"path": ".env"}, {"path": "a\\b.py"}, {"sha256": "a" * 64},
    {"original_base64": "YQ==\n"}, {"operation_id": "forged"},
    {"summary": "x" * 801}, {"created_at": "tomorrow"},
])
def test_material_rejects_invalid_or_executable_fields(updates):
    with pytest.raises(ValueError):
        recovery.validate_bundle(bundle([material(**updates)]))


@pytest.mark.parametrize("raw", [b"a\0b", b"\xff", b"x" * 12001, b"x\n" * 2001, b"\x7f"])
def test_original_validation_preserves_edit_text_limits(raw):
    with pytest.raises(ValueError):
        recovery.validate_bundle(bundle([material(raw)]))


def test_bundle_rejects_duplicate_json_keys_and_excess_records():
    with pytest.raises(ValueError):
        recovery.validate_bundle(b'{"materials":[],"materials":[]}')
    with pytest.raises(ValueError):
        recovery.validate_bundle(bundle([material()] * 257))


def test_quota_failure_is_atomic_and_dedup_counts_before_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "MAX_MATERIALS", 2)
    store = recovery.ProjectRecoveryArchive(tmp_path)
    first = recovery.validate_bundle(bundle([material()]))
    assert store.insert(first)["imported"] == 1
    other = recovery.validate_bundle(bundle([material(path="b.py"), material(path="c.py")]))
    with pytest.raises(ValueError):
        store.insert(other)
    assert len(store.list_archives(Registry(), "selected")) == 1
    assert store.insert(first) == {"imported": 0, "duplicates": 1}
    monkeypatch.setattr(recovery, "MAX_ORIGINAL_BYTES", len(RAW))
    with pytest.raises(ValueError):
        store.insert(other[:1])
    assert len(store.list_archives(Registry(), "selected")) == 1


def test_concurrent_insert_deduplicates_inside_transaction(tmp_path):
    rows = recovery.validate_bundle(bundle([material()]))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: recovery.ProjectRecoveryArchive(tmp_path).insert(rows), range(4)))
    assert sum(row["imported"] for row in results) == 1
    assert sum(row["duplicates"] for row in results) == 3


def test_export_reads_live_originals_without_reconciling_or_replacing_journal(tmp_path):
    journal = tmp_path / "project-changes.sqlite3"
    with sqlite3.connect(journal) as db:
        db.execute("CREATE TABLE recoveries (root_key TEXT,path TEXT,summary TEXT,created_at TEXT,before_hash TEXT,original BLOB)")
        row = material()
        db.execute("INSERT INTO recoveries VALUES (?,?,?,?,?,?)", (
            "[12, 34]", row["path"], row["summary"], row["created_at"], row["sha256"], RAW))
    before = journal.read_bytes()
    assert recovery.export_materials(tmp_path) == [material()]
    assert journal.read_bytes() == before
    store = recovery.ProjectRecoveryArchive(tmp_path)
    store.insert(recovery.validate_bundle(bundle([material()])))
    assert recovery.export_materials(tmp_path) == [material()]
    assert journal.read_bytes() == before


def test_multiline_summary_roundtrips_and_surrogates_are_rejected(tmp_path):
    row = material(summary="First line\nSecond\tline")
    validated = recovery.validate_bundle(bundle([row]))
    recovery.ProjectRecoveryArchive(tmp_path).insert(validated)
    assert recovery.export_materials(tmp_path) == [row]
    for updates in ({"summary": "bad\ud800"}, {"path": "bad\ud800.py"}):
        raw = json.dumps({"materials": [material(**updates)]}, ensure_ascii=True).encode()
        with pytest.raises(ValueError):
            recovery.validate_bundle(raw)
