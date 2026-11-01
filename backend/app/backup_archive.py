"""Bounded ZIP validation and trusted-schema staging for application backups."""
from contextlib import closing
import hashlib
from io import BytesIO
from pathlib import Path
import re
import sqlite3
import stat
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import sqlite

from .project_recovery_backup import MAX_BUNDLE_BYTES, strict_json

MANIFEST_MAX_BYTES = 256 * 1024


def validate_zip(raw, config_files, max_bytes):
    """Read no entry until its declared bounds, names and methods are accepted."""
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [info.filename for info in entries]
            allowed = {"mens-backup.json", "campus.db", "project-recovery.json", *config_files}
            if len(names) != len(set(names)) or "mens-backup.json" not in names:
                raise ValueError("duplicate entries or missing manifest")
            total = 0
            for info in entries:
                mode = info.external_attr >> 16
                limit = (MANIFEST_MAX_BYTES if info.filename == "mens-backup.json" else
                         MAX_BUNDLE_BYTES if info.filename == "project-recovery.json" else max_bytes)
                if (info.filename not in allowed or info.orig_filename != info.filename or info.is_dir()
                        or info.external_attr & 0x10 or info.flag_bits & 1 or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or not 0 <= info.file_size <= min(limit, max_bytes)):
                    raise ValueError("unsafe or oversized ZIP entry")
                total += info.file_size
                if total > max_bytes:
                    raise ValueError("uncompressed backup exceeds budget")
            payloads = {}
            for info in entries:
                with archive.open(info) as stream:
                    payload = stream.read(info.file_size + 1)
                if len(payload) != info.file_size:
                    raise ValueError("ZIP size mismatch")
                payloads[info.filename] = payload
    except (BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValueError("invalid backup ZIP") from exc
    manifest = strict_json(payloads.pop("mens-backup.json"))
    if (not isinstance(manifest, dict) or manifest.get("app") != "Mens"
            or type(manifest.get("format")) is not int or manifest["format"] not in (1, 2)):
        raise ValueError("unsupported backup format")
    if manifest["format"] == 1 and "project-recovery.json" in payloads:
        raise ValueError("materials require backup format 2")
    files = manifest.get("files", {})
    if not isinstance(files, dict) or (manifest["format"] == 2 and set(files) != set(payloads)):
        raise ValueError("manifest does not match backup contents")
    for name, metadata in files.items():
        if name not in payloads or not isinstance(metadata, dict) or set(metadata) - {"size", "sha256"}:
            raise ValueError("invalid manifest entry")
        if manifest["format"] == 2 and set(metadata) != {"size", "sha256"}:
            raise ValueError("incomplete manifest entry")
        if "size" in metadata and (type(metadata["size"]) is not int or metadata["size"] != len(payloads[name])):
            raise ValueError("manifest size mismatch")
        if "sha256" in metadata and (not isinstance(metadata["sha256"], str)
                or re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"]) is None
                or hashlib.sha256(payloads[name]).hexdigest() != metadata["sha256"]):
            raise ValueError("manifest hash mismatch")
    return manifest, payloads


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'



def _validate_value(table, column, value, dialect):
    """SQLite affinity alone does not guarantee values the application can read."""
    if value is None:
        if column.nullable:
            return
        raise ValueError("null in a required application column")
    kind = column.type
    if isinstance(kind, JSON):
        if not isinstance(value, str):
            raise ValueError("invalid JSON storage type")
        parsed = strict_json(value.encode("utf-8", errors="strict"))
        shape = list if table == "mcp_servers" and column.name in {"args", "last_tools"} else dict
        # Existing readers consistently treat JSON null as an empty object/list.
        if parsed is not None and not isinstance(parsed, shape):
            raise ValueError("invalid application JSON shape")
    elif isinstance(kind, DateTime):
        if not isinstance(value, str):
            raise ValueError("invalid datetime storage type")
        processor = kind.dialect_impl(dialect).result_processor(dialect, None)
        if processor is not None:
            processor(value)
    elif isinstance(kind, Boolean):
        if type(value) is not int or value not in (0, 1):
            raise ValueError("invalid boolean storage value")
    elif isinstance(kind, Integer):
        if type(value) is not int:
            raise ValueError("invalid integer storage type")
    elif isinstance(kind, String):
        if not isinstance(value, str) or kind.length is not None and len(value) > kind.length:
            raise ValueError("invalid text storage value")
        value.encode("utf-8", errors="strict")
    else:
        raise ValueError("unsupported application column type")

def stage_database(upload_path, clean_path, metadata):
    """Copy bounded uploaded rows into our own schema; never transplant its SQL.

    Old backups can omit newer tables and additive conversation columns. Uploaded
    views/triggers/virtual tables and expression indexes are rejected before any
    application state changes. Only parameterized values enter the trusted DB.
    """
    uri = Path(upload_path).resolve().as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as source, closing(sqlite3.connect(clean_path)) as target:
        source.execute("PRAGMA trusted_schema=OFF")
        source.execute("PRAGMA query_only=ON")
        schema = source.execute("SELECT type,name,tbl_name,sql FROM sqlite_master").fetchall()
        tables = {name for kind, name, _, _ in schema if kind == "table"}
        if not {"conversations", "messages", "documents"} <= tables:
            raise ValueError("not a Mens application database")
        expected = metadata.tables
        if tables - set(expected) - {"sqlite_sequence"}:
            raise ValueError("unexpected application table")
        for kind, name, table, sql in schema:
            if kind not in ("table", "index"):
                raise ValueError("uploaded executable schema is not accepted")
            if sql and re.search(r"\b(VIRTUAL|GENERATED|CHECK)\b", sql, re.I):
                raise ValueError("uploaded schema expressions are not accepted")
            if kind == "index":
                # cid -2 denotes an expression; -1 is a rowid auxiliary column.
                if any(row[1] == -2 for row in source.execute("PRAGMA index_xinfo(" + _quoted(name) + ")")):
                    raise ValueError("uploaded expression index is not accepted")
        columns_by_table = {}
        additive = {"client_id", "owner_user_id", "title", "pinned"}
        for name in tables & set(expected):
            columns = source.execute("PRAGMA table_xinfo(" + _quoted(name) + ")").fetchall()
            names = {row[1] for row in columns}
            wanted = set(expected[name].columns.keys())
            optional = additive if name == "conversations" else set()
            if names - wanted or wanted - names - optional or any(row[6] != 0 for row in columns):
                raise ValueError("invalid application columns")
            columns_by_table[name] = [column.name for column in expected[name].columns if column.name in names]
        if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("corrupt application database")
        dialect = sqlite.dialect()
        for table in metadata.sorted_tables:
            target.execute(str(CreateTable(table).compile(dialect=dialect)))
            for index in table.indexes:
                target.execute(str(CreateIndex(index).compile(dialect=dialect)))
        for name, columns in columns_by_table.items():
            quoted = ",".join(_quoted(column) for column in columns)
            query = "SELECT " + quoted + " FROM " + _quoted(name)
            insert = "INSERT INTO " + _quoted(name) + " (" + quoted + ") VALUES (" + ",".join("?" for _ in columns) + ")"
            cursor = source.execute(query)
            while rows := cursor.fetchmany(256):
                for row in rows:
                    for column, value in zip(columns, row):
                        _validate_value(name, expected[name].columns[column], value, dialect)
                target.executemany(insert, rows)
        target.commit()
