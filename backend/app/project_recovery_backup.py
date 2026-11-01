"""Portable copy-only original materials, separate from executable recovery state.

Only this store owns backup_ identifiers. It never calls a project filesystem
reader, a journal reconciler, or any project write method.
"""
import base64
import binascii
from contextlib import closing, contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .project_files import MAX_EDIT_BYTES, ProjectFileError, _parts, text_newline
from .project_commit_windows import _valid_raw

MAX_MATERIALS = 256
MAX_ORIGINAL_BYTES = 16 * 1024 * 1024
MAX_BUNDLE_BYTES = 25 * 1024 * 1024
ARCHIVE_FILE = "project-recovery-archive.sqlite3"
_FIELDS = {"root_key", "path", "summary", "created_at", "sha256", "original_base64"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def strict_json(raw):
    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("invalid JSON number")))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid JSON") from exc


def _root_key(root):
    if (not isinstance(root, (list, tuple)) or len(root) != 2
            or any(type(part) is not int or not 0 <= part < 2 ** 64 for part in root)):
        raise ValueError("invalid physical root identity")
    return list(root)


def _material(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("invalid material fields")
    root = _root_key(value["root_key"])
    try:
        _parts(value["path"])
        value["path"].encode("utf-8", errors="strict")
    except ProjectFileError as exc:
        raise ValueError("invalid material path") from exc
    summary, created, encoded, sha = (value[key] for key in ("summary", "created_at", "original_base64", "sha256"))
    if (not isinstance(summary, str) or not 1 <= len(summary) <= 800
            or any(ord(c) < 32 and c not in "\r\n\t" or ord(c) == 127 for c in summary)):
        raise ValueError("invalid summary")
    summary.encode("utf-8", errors="strict")
    if not isinstance(created, str) or not 1 <= len(created) <= 64:
        raise ValueError("invalid creation date")
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("creation date must include timezone")
    except ValueError as exc:
        raise ValueError("invalid creation date") from exc
    if not isinstance(sha, str) or re.fullmatch(r"[a-f0-9]{64}", sha) is None:
        raise ValueError("invalid original hash")
    if not isinstance(encoded, str) or len(encoded) > ((MAX_EDIT_BYTES + 2) // 3) * 4:
        raise ValueError("oversized original")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode("ascii") != encoded:
            raise ValueError("noncanonical base64")
        _valid_raw(raw)
    except (binascii.Error, UnicodeError, ProjectFileError) as exc:
        raise ValueError("invalid original bytes") from exc
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("original hash mismatch")
    return {**value, "root_key": root}, raw


def validate_bundle(raw):
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("material bundle exceeds 25 MiB")
    value = strict_json(raw)
    if not isinstance(value, dict) or set(value) != {"materials"} or not isinstance(value["materials"], list):
        raise ValueError("invalid material bundle")
    return _validate_rows(value["materials"])


def _validate_rows(rows):
    if len(rows) > MAX_MATERIALS:
        raise ValueError("too many originals")
    result, total = [], 0
    for value in rows:
        row, raw = _material(value)
        total += len(raw)
        if total > MAX_ORIGINAL_BYTES:
            raise ValueError("original bytes exceed 16 MiB")
        result.append(row)
    return result


def _archive_id(row):
    return "backup_" + hashlib.sha256(canonical([row["root_key"], row["path"], row["sha256"]]).encode("utf-8")).hexdigest()


def _readonly(path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def _from_record(row):
    raw = bytes(row["original"])
    return {"root_key": strict_json(row["root_key"].encode("utf-8")), "path": row["path"],
            "summary": row["summary"], "created_at": row["created_at"], "sha256": row["sha256"],
            "original_base64": base64.b64encode(raw).decode("ascii")}


def export_materials(data_dir):
    """Snapshot each independent store read-only; never reconcile live operations."""
    result = {}
    for name, query in (
        ("project-changes.sqlite3", "SELECT root_key,path,summary,created_at,before_hash AS sha256,original FROM recoveries"),
        (ARCHIVE_FILE, "SELECT root_key,path,summary,created_at,sha256,original FROM materials"),
    ):
        path = Path(data_dir) / name
        if not path.is_file():
            continue
        with closing(_readonly(path)) as db:
            rows = db.execute(query + " LIMIT ?", (MAX_MATERIALS + 1,)).fetchall()
            if len(rows) > MAX_MATERIALS:
                raise ValueError("too many originals to export")
            for record in rows:
                row, _ = _material(_from_record(record))
                result.setdefault(_archive_id(row), row)
    return _validate_rows(list(result.values()))


class ProjectRecoveryArchive:
    def __init__(self, data_dir=None):
        self._data_dir = Path(data_dir) if data_dir is not None else None

    def _path(self):
        if self._data_dir is not None:
            return self._data_dir / ARCHIVE_FILE
        from .config import get_settings
        return Path(get_settings().data_dir) / ARCHIVE_FILE

    @contextmanager
    def publication(self, rows):
        """Validate/dedup/reserve quota before the caller publishes app restoration."""
        rows = _validate_rows(rows)
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS materials (archive_id TEXT PRIMARY KEY, root_key TEXT NOT NULL, path TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL, sha256 TEXT NOT NULL, original BLOB NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            try:
                count, total = db.execute("SELECT COUNT(*),COALESCE(SUM(length(original)),0) FROM materials").fetchone()
                imported = duplicates = 0
                for row in rows:
                    archive_id = _archive_id(row)
                    if db.execute("SELECT 1 FROM materials WHERE archive_id=?", (archive_id,)).fetchone():
                        duplicates += 1
                        continue
                    raw = base64.b64decode(row["original_base64"], validate=True)
                    count += 1
                    total += len(raw)
                    if count > MAX_MATERIALS or total > MAX_ORIGINAL_BYTES:
                        raise ValueError("retained original quota exceeded; no materials imported")
                    db.execute("INSERT INTO materials VALUES (?,?,?,?,?,?,?)", (
                        archive_id, canonical(row["root_key"]), row["path"], row["summary"], row["created_at"], row["sha256"], raw))
                    imported += 1
                yield {"imported": imported, "duplicates": duplicates}
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def insert(self, rows):
        with self.publication(rows) as counts:
            return counts

    def list_archives(self, registry, project_id):
        with registry.grant_transaction():
            root = canonical(_root_key(registry.physical_identity(project_id)))
            path = self._path()
            if not path.is_file():
                return []
            try:
                with closing(_readonly(path)) as db:
                    rows = db.execute("SELECT archive_id,path,summary,created_at,length(original) AS size_bytes FROM materials WHERE root_key=? ORDER BY created_at DESC,archive_id LIMIT ?", (root, MAX_MATERIALS)).fetchall()
                    return [dict(row) for row in rows]
            except (sqlite3.Error, OSError):
                raise ProjectFileError("project_archive_unavailable", "备份原文暂时不可用。", 503) from None

    def original(self, registry, project_id, archive_id):
        with registry.grant_transaction():
            root = canonical(_root_key(registry.physical_identity(project_id)))
            path = self._path()
            if path.is_file():
                try:
                    with closing(_readonly(path)) as db:
                        row = db.execute("SELECT * FROM materials WHERE archive_id=? AND root_key=?", (archive_id, root)).fetchone()
                        if row is not None:
                            value, raw = _material(_from_record(row))
                            if _archive_id(value) != archive_id:
                                raise ValueError("archive identity mismatch")
                            text = raw.decode("utf-8-sig")
                            return {"text": text, "bom": raw.startswith(b"\xef\xbb\xbf"), "newline": text_newline(text)}
                except (sqlite3.Error, OSError, ValueError, TypeError):
                    raise ProjectFileError("project_archive_unavailable", "备份原文暂时不可用。", 503) from None
            raise ProjectFileError("project_archive_not_found", "备份原文不存在。", 404)
