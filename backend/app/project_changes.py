"""Durable bounded recovery records; project writes occur only in explicit commit.

The SQLite journal contains selected original bytes and physical identities, but
never absolute project paths. Reads classify interrupted operations, never replay
their filesystem actions.
"""
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import ntpath
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from .project_files import ProjectFileError, text_newline


_MESSAGES = {"unsupported": "当前项目不支持受控修改。", "conflict": "项目修改版本或操作已变化，请重新确认。",
             "busy": "该文件有未确定的修改，请先查看恢复记录。", "journal_unavailable": "恢复记录暂时不可用，请查询操作结果。",
             "limit": "待恢复修改已达上限，请先保留或撤销已有修改。", "invalid": "项目修改请求无效，请重新确认。",
             "not_found": "修改恢复记录不存在。", "failed": "修改未完成，请查看恢复记录。"}


def _error(code, status=409):
    return ProjectFileError("project_change_" + code, _MESSAGES[code], status)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _safe_journal(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (sqlite3.Error, ValueError, KeyError, TypeError, UnicodeError):
            raise _error("journal_unavailable", 503) from None
    return run


class ProjectChangeStore:
    def __init__(self, data_dir=None):
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self._lock = threading.RLock()
        self._plans = {}

    def _db(self):
        try:
            if self._data_dir is None:
                from .config import get_settings
                directory = get_settings().data_dir
            else:
                directory = self._data_dir
            directory.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(directory / "project-changes.sqlite3", timeout=0.3, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("CREATE TABLE IF NOT EXISTS recoveries (id TEXT PRIMARY KEY, root_key TEXT NOT NULL, proposal_id TEXT NOT NULL, state TEXT NOT NULL, path TEXT NOT NULL, original BLOB NOT NULL, before_identity TEXT NOT NULL, after_identity TEXT, before_hash TEXT NOT NULL, after_hash TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL, latest_operation TEXT NOT NULL, UNIQUE(root_key,proposal_id))")
            connection.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, root_key TEXT NOT NULL, subject_id TEXT NOT NULL, action TEXT NOT NULL, digest TEXT NOT NULL, recovery_id TEXT NOT NULL, path TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL)")
            return connection
        except (sqlite3.Error, OSError):
            if "connection" in locals():
                connection.close()
            raise _error("journal_unavailable", 503) from None

    @staticmethod
    def _root(registry, project_id):
        return _json(list(registry.physical_identity(project_id)))

    @staticmethod
    def _lookup(db, root, recovery_id):
        row = db.execute("SELECT * FROM recoveries WHERE id=? AND root_key=?", (recovery_id, root)).fetchone()
        if row is None:
            raise _error("not_found", 404)
        return dict(row)

    @staticmethod
    def _original_bytes(record):
        from .project_commit_windows import _valid_raw
        try:
            raw = bytes(record["original"])
            if hashlib.sha256(raw).hexdigest() != record["before_hash"]:
                raise ValueError("journal fingerprint mismatch")
            _valid_raw(raw)
            return raw
        except (ValueError, TypeError, ProjectFileError):
            raise _error("journal_unavailable", 503) from None

    @staticmethod
    def _snapshot(registry, project_id, path):
        try:
            return registry.snapshot_file(project_id, path)
        except ProjectFileError:
            return None

    def _blocked(self, db, root, path):
        unresolved = db.execute("SELECT path FROM operations WHERE root_key=? AND state IN ('pending','uncertain')", (root,)).fetchall()
        if any(ntpath.normcase(row[0]) == ntpath.normcase(path) for row in unresolved):
            raise _error("busy")

    @_safe_journal
    def prepare(self, registry, proposals, project_id, subject_id, action):
        with registry.grant_transaction(), self._lock:
            if action not in ("apply", "revert", "keep") or not isinstance(subject_id, str):
                raise _error("invalid", 422)
            if not registry.changes_supported(project_id):
                raise _error("unsupported", 422)
            root = self._root(registry, project_id)
            db = self._db()
            try:
                if action == "apply":
                    proposal, original_identity = proposals.material(registry, project_id, subject_id)
                    if proposal["state"] != "ready":
                        raise _error("conflict")
                    snapshot = registry.snapshot_file(project_id, proposal["path"])
                    raw = (b"\xef\xbb\xbf" if proposal["bom"] else b"") + proposal["after_text"].encode("utf-8")
                    plan = {"proposal_id": subject_id, "path": proposal["path"], "summary": proposal["summary"],
                            "added_lines": proposal["added_lines"], "removed_lines": proposal["removed_lines"],
                            "expected_sha256": proposal["base_sha256"], "target_sha256": proposal["proposed_sha256"],
                            "expected_identity": snapshot.identity, "original": snapshot.raw_bytes, "replacement": raw}
                    if snapshot.sha256 != proposal["base_sha256"] or snapshot.identity != original_identity:
                        raise _error("conflict")
                    if db.execute("SELECT 1 FROM operations WHERE root_key=? AND subject_id=? AND action='apply'", (root, subject_id)).fetchone():
                        raise _error("conflict")
                else:
                    recovery = self._lookup(db, root, subject_id)
                    if recovery["state"] != "applied":
                        raise _error("busy" if recovery["state"] in ("pending", "uncertain") else "conflict")
                    snapshot = self._snapshot(registry, project_id, recovery["path"])
                    expected = json.loads(recovery["after_identity"]) if recovery["after_identity"] else None
                    if action == "revert" and (snapshot is None or list(snapshot.identity) != expected or snapshot.sha256 != recovery["after_hash"]):
                        raise _error("conflict")
                    plan = {"proposal_id": recovery["proposal_id"], "path": recovery["path"], "summary": recovery["summary"],
                            "added_lines": 0, "removed_lines": 0, "expected_sha256": recovery["after_hash"],
                            "target_sha256": recovery["before_hash"] if action == "revert" else recovery["after_hash"],
                            "expected_identity": expected, "replacement": self._original_bytes(recovery),
                            "original": snapshot.raw_bytes if snapshot else b"", "previous_operation": recovery["latest_operation"]}
                self._blocked(db, root, plan["path"])
            except sqlite3.Error:
                raise _error("journal_unavailable", 503) from None
            finally:
                db.close()
            public = {key: plan[key] for key in ("proposal_id", "path", "summary", "added_lines", "removed_lines", "expected_sha256", "target_sha256")}
            public.update(project_id=project_id, subject_id=subject_id, action=action)
            digest_input = {**public, "root": root, "expected_identity": plan["expected_identity"]}
            digest = hashlib.sha256(_json(digest_input).encode()).hexdigest()
            public["digest"] = digest
            now = time.monotonic()
            self._plans = {key: value for key, value in self._plans.items() if value["expires"] > now}
            if len(self._plans) >= 128 and digest not in self._plans:
                raise _error("limit", 429)
            self._plans[digest] = {**plan, **public, "root": root, "expires": now + 1800}
            return deepcopy(public)

    @staticmethod
    def _receipt(operation, project_id, can_revert=False):
        value = json.loads(operation["data"])
        value = {key: value[key] for key in ("operation_id", "subject_id", "proposal_id", "recovery_id", "action", "state", "path", "summary", "created_at", "digest")}
        details = json.loads(operation["data"])
        if details.get("error_code"):
            value["error_code"] = details["error_code"]
        value.update(project_id=project_id, can_revert=can_revert)
        return value

    def _can_revert(self, registry, project_id, recovery):
        if recovery["state"] != "applied" or not recovery["after_identity"]:
            return False
        snapshot = self._snapshot(registry, project_id, recovery["path"])
        return bool(snapshot and snapshot.sha256 == recovery["after_hash"] and list(snapshot.identity) == json.loads(recovery["after_identity"]))

    def _update(self, db, operation, state, error_code=None, details=None):
        data = json.loads(operation["data"])
        data["state"] = state
        if error_code:
            data["error_code"] = error_code
        elif state not in ("pending", "uncertain", "failed", "conflict"):
            data.pop("error_code", None)
        if details:
            data.update(details)
        data["state"] = state
        db.execute("UPDATE operations SET state=?,data=? WHERE id=?", (state, _json(data), operation["id"]))
        operation.update(state=state, data=_json(data))
        return data

    def _finish(self, db, operation, state, error_code=None, details=None):
        data = self._update(db, operation, state, error_code, details)
        recovery_id = operation["recovery_id"]
        action = operation["action"]
        if action == "apply":
            db.execute("UPDATE recoveries SET state=?,after_identity=COALESCE(?,after_identity) WHERE id=?",
                       (state, _json(data["after_identity"]) if data.get("after_identity") else None, recovery_id))
        elif state in ("reverted", "kept", "pending", "uncertain"):
            db.execute("UPDATE recoveries SET state=?,latest_operation=? WHERE id=?", (state, operation["id"], recovery_id))
        else:
            db.execute("UPDATE recoveries SET state='applied',latest_operation=? WHERE id=?", (data["previous_operation"], recovery_id))

    def _reconcile(self, db, registry, project_id, operation):
        if operation["state"] not in ("pending", "uncertain"):
            return operation
        data = json.loads(operation["data"])
        current = self._snapshot(registry, project_id, operation["path"])
        if operation["action"] == "keep":
            state = "failed"
        elif self._artifacts_present(registry, project_id, operation["path"], data):
            state = "uncertain"
        elif current and data.get("after_identity") and list(current.identity) == list(data["after_identity"]) and current.sha256 == data["target_sha256"]:
            state = "applied" if operation["action"] == "apply" else "reverted"
        elif current and list(current.identity) == list(data["expected_identity"]) and current.sha256 == data["expected_sha256"]:
            state = "failed"
        else:
            state = "uncertain"
        own_transaction = not db.in_transaction
        try:
            if own_transaction:
                db.execute("BEGIN IMMEDIATE")
            self._finish(db, operation, state, (data.get("error_code") or "project_change_failed") if state in ("failed", "uncertain") else None)
            if own_transaction:
                db.execute("COMMIT")
        except Exception:
            if own_transaction and db.in_transaction:
                db.execute("ROLLBACK")
            raise
        return operation

    @staticmethod
    def _artifacts_present(registry, project_id, path, details):
        directory = path.rpartition("/")[0]
        return any(registry.internal_artifact_present(project_id, (directory + "/" if directory else "") + details[key])
                   for key in ("stage_name", "backup_name") if details.get(key))

    @_safe_journal
    def commit(self, registry, proposals, project_id, subject_id, action, digest, operation_id):
        with registry.grant_transaction(), self._lock:
            root = self._root(registry, project_id)
            if not re.fullmatch(r"[a-fA-F0-9]{64}", digest or "") or action not in ("apply", "revert", "keep"):
                raise _error("invalid", 422)
            db = self._db()
            try:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
                if prior:
                    prior = dict(prior)
                    if (prior["root_key"], prior["subject_id"], prior["action"], prior["digest"]) != (root, subject_id, action, digest):
                        raise _error("conflict")
                    self._reconcile(db, registry, project_id, prior)
                    db.execute("COMMIT")
                    record = db.execute("SELECT * FROM recoveries WHERE id=? AND root_key=?", (prior["recovery_id"], root)).fetchone()
                    return self._receipt(prior, project_id, self._can_revert(registry, project_id, dict(record)) if record else False)
                plan = self._plans.get(digest)
                if (plan is None or plan["expires"] <= time.monotonic()
                        or (plan["root"], plan["project_id"], plan["subject_id"], plan["action"]) != (root, project_id, subject_id, action)):
                    raise _error("invalid")
                if action != "keep" and hashlib.sha256(plan["replacement"]).hexdigest() != plan["target_sha256"]:
                    raise _error("journal_unavailable", 503)
                if not registry.changes_supported(project_id):
                    raise _error("unsupported", 422)
                self._blocked(db, root, plan["path"])
                if action == "apply":
                    if db.execute("SELECT 1 FROM operations WHERE root_key=? AND subject_id=? AND action='apply'", (root, subject_id)).fetchone():
                        raise _error("conflict")
                    count = db.execute("SELECT count(*) FROM recoveries WHERE state IN ('pending','applied','uncertain')").fetchone()[0]
                    if count >= 32:
                        raise _error("limit", 429)
                    recovery_id = secrets.token_urlsafe(24)
                else:
                    record = self._lookup(db, root, subject_id)
                    if record["state"] != "applied":
                        raise _error("conflict")
                    recovery_id = subject_id
                created = datetime.now(timezone.utc).isoformat()
                data = {key: plan[key] for key in ("project_id", "subject_id", "proposal_id", "action", "digest", "path", "summary", "expected_sha256", "target_sha256", "expected_identity")}
                data.update(operation_id=operation_id, recovery_id=recovery_id, state="pending", created_at=created, phase="journaled")
                if action != "apply":
                    data["previous_operation"] = plan["previous_operation"]
                operation = {"id": operation_id, "root_key": root, "subject_id": subject_id, "action": action,
                             "digest": digest, "recovery_id": recovery_id, "path": plan["path"], "state": "pending", "data": _json(data)}
                db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?)", tuple(operation[key] for key in ("id", "root_key", "subject_id", "action", "digest", "recovery_id", "path", "state", "data")))
                if action == "apply":
                    db.execute("INSERT INTO recoveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (recovery_id, root, subject_id, "pending", plan["path"], plan["original"], _json(plan["expected_identity"]), None, plan["expected_sha256"], plan["target_sha256"], plan["summary"], created, operation_id))
                else:
                    db.execute("UPDATE recoveries SET state='pending',latest_operation=? WHERE id=?", (operation_id, recovery_id))
                if action == "keep":
                    self._finish(db, operation, "kept")
                db.execute("COMMIT")
                if action != "keep":
                    def checkpoint(phase, details):
                        db.execute("BEGIN IMMEDIATE")
                        self._update(db, operation, "pending", details={"phase": phase, **details})
                        if details.get("after_identity") and action == "apply":
                            db.execute("UPDATE recoveries SET after_identity=? WHERE id=?", (_json(details["after_identity"]), recovery_id))
                        db.execute("COMMIT")
                    try:
                        outcome = registry.commit_file(project_id, plan["path"], plan["expected_identity"], plan["expected_sha256"], plan["replacement"], checkpoint)
                        state = outcome["state"]
                        if state == "applied" and action == "revert":
                            state = "reverted"
                        error_code = outcome.get("error_code")
                    except ProjectFileError as exc:
                        state = "conflict" if exc.error_code == "project_change_conflict" else "failed"
                        error_code = exc.error_code if exc.error_code.startswith("project_change_") else "project_change_failed"
                        outcome = {}
                    combined = {**json.loads(operation["data"]), **outcome}
                    if self._artifacts_present(registry, project_id, plan["path"], combined):
                        state, error_code = "uncertain", "project_change_failed"
                    db.execute("BEGIN IMMEDIATE")
                    self._finish(db, operation, state, error_code, outcome)
                    db.execute("COMMIT")
                record = self._lookup(db, root, recovery_id)
                # Bound resolved original-byte snapshots; keep operation IDs as
                # small durable replay tombstones instead of repeating writes.
                db.execute("DELETE FROM recoveries WHERE id IN (SELECT id FROM recoveries WHERE state IN ('reverted','kept','failed','conflict') ORDER BY created_at DESC LIMIT -1 OFFSET 32)")
                return self._receipt(operation, project_id, self._can_revert(registry, project_id, record))
            except sqlite3.Error:
                raise _error("journal_unavailable", 503) from None
            finally:
                db.close()

    @_safe_journal
    def operations(self, registry, project_id, operation_id):
        with registry.grant_transaction(), self._lock:
            root = self._root(registry, project_id)
            db = self._db()
            try:
                row = db.execute("SELECT * FROM operations WHERE id=? AND root_key=?", (operation_id, root)).fetchone()
                if row is None:
                    raise _error("not_found", 404)
                operation = dict(row)
                self._reconcile(db, registry, project_id, operation)
                recovery = db.execute("SELECT * FROM recoveries WHERE id=?", (operation["recovery_id"],)).fetchone()
                return self._receipt(operation, project_id, self._can_revert(registry, project_id, dict(recovery)) if recovery else False)
            except sqlite3.Error:
                raise _error("journal_unavailable", 503) from None
            finally:
                db.close()

    @_safe_journal
    def list_changes(self, registry, project_id):
        with registry.grant_transaction(), self._lock:
            root = self._root(registry, project_id)
            db = self._db()
            try:
                rows = db.execute("SELECT o.* FROM recoveries r JOIN operations o ON o.id=r.latest_operation WHERE r.root_key=? ORDER BY r.created_at DESC LIMIT 64", (root,)).fetchall()
                result = []
                for row in rows:
                    operation = self._reconcile(db, registry, project_id, dict(row))
                    recovery = self._lookup(db, root, operation["recovery_id"])
                    result.append(self._receipt(operation, project_id, self._can_revert(registry, project_id, recovery)))
                return {"available": registry.changes_supported(project_id), "records": result}
            except sqlite3.Error:
                raise _error("journal_unavailable", 503) from None
            finally:
                db.close()

    @_safe_journal
    def original(self, registry, project_id, recovery_id):
        with registry.grant_transaction(), self._lock:
            root = self._root(registry, project_id)
            db = self._db()
            try:
                record = self._lookup(db, root, recovery_id)
                raw = self._original_bytes(record)
                text = raw.decode("utf-8-sig", errors="strict")
                return {"text": text, "bom": raw.startswith(b"\xef\xbb\xbf"), "newline": text_newline(text)}
            except sqlite3.Error:
                raise _error("journal_unavailable", 503) from None
            finally:
                db.close()
