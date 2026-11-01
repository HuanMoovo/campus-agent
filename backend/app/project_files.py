"""Revocable, bounded read-only access to an explicitly selected local project.

Windows handles are opened without delete sharing, inspected for reparse points,
and checked using GetFinalPathNameByHandleW before any content is read. Directory
handles stay open throughout traversal. POSIX uses dir_fd + O_NOFOLLOW instead.
No file contents or absolute project paths are persisted by this module.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import ntpath
import os
from pathlib import Path
import re
import secrets
import stat
import threading


MAX_FILES = 4
MAX_CONTEXT_CHARS = 16000
MAX_FILE_CHARS = 12000
MAX_FILE_BYTES = 256 * 1024
MAX_ENTRIES = 300
MAX_SCAN_ENTRIES = 1200
MAX_EDIT_BYTES = 64 * 1024
MAX_EDIT_CHARS = 12000
MAX_EDIT_LINES = 2000

_BLOCKED_DIRS = frozenset({
    ".git", ".ssh", ".aws", ".codex", ".agents", "node_modules", ".venv",
    "venv", "dist", "build", "__pycache__", ".idea", ".vscode", ".gnupg",
    ".azure", ".kube", ".npm", ".pypirc", ".config",
})
_EXTENSIONS = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json",
    ".md", ".mdx", ".txt", ".rst", ".html", ".htm", ".css", ".scss",
    ".sass", ".less", ".vue", ".svelte", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".xml", ".sql", ".sh", ".bash", ".ps1", ".bat", ".cmd",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".java", ".kt", ".kts",
    ".go", ".rs", ".rb", ".php", ".swift", ".dart", ".r", ".lua",
    ".gd", ".gdshader", ".tscn", ".tres", ".tex", ".csv", ".tsv",
})
_TEXT_NAMES = frozenset({"readme", "license", "makefile", "dockerfile", ".gitignore", ".gitattributes", ".editorconfig"})
_SENSITIVE = re.compile(r"(?:credential|secret|password|passwd|private|api[-_]?key|access[-_]?token|auth[-_]?token|model[-_]?(?:config|settings|keys)|provider[-_]?(?:config|settings|keys))", re.I)
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(?:\.|$)", re.I)


class ProjectFileError(Exception):
    def __init__(self, error_code, message, status_code=422):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ProjectSnapshot:
    """Internal complete snapshot; never serialize raw bytes or identity to clients."""
    path: str
    text: str = field(repr=False)
    raw_bytes: bytes = field(repr=False)
    sha256: str
    identity: tuple
    bom: bool
    newline: str


def text_newline(text):
    endings = set(re.findall(r"\r\n|\r|\n", text))
    if len(endings) > 1:
        return "mixed"
    return {"\r\n": "crlf", "\n": "lf", "\r": "cr"}.get(next(iter(endings), ""), "none")


def text_line_count(text):
    return len(re.findall(r"\r\n|\r|\n", text)) + bool(text and not text.endswith(("\r", "\n")))


def _denied():
    return ProjectFileError("project_path_denied", "该项目路径或文件不可访问。")


def _safe_component(name):
    return bool(name) and name not in {".", ".."} and not (
        name[-1] in " ." or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(c in name for c in '\\/:<>"|?*~') or _RESERVED.match(name)
    )


def _sensitive(name):
    lower = name.casefold()
    return lower.startswith(".env") or lower.startswith("id_") or bool(_SENSITIVE.search(name))


def _allowed_file(name):
    return (_safe_component(name) and not _sensitive(name)
            and (Path(name).suffix.casefold() in _EXTENSIONS or name.casefold() in _TEXT_NAMES))


def _parts(path, *, directory=False):
    if not isinstance(path, str) or len(path) > 2048:
        raise _denied()
    if directory and path == "":
        return []
    parts = path.split("/")
    if len(parts) > 64 or any(not _safe_component(part) or _sensitive(part) or part.casefold() in _BLOCKED_DIRS for part in parts):
        raise _denied()
    if not directory and not _allowed_file(parts[-1]):
        raise _denied()
    return parts


def _regular(info, *, directory):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise _denied()
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise _denied()
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _denied()


def _posix_open_root(canonical):
    """Acquire a root capability without resolving mutable ancestor paths.

    O_NOFOLLOW only protects the final component of a single open. Starting at
    '/' and resolving one component per parent descriptor applies that protection
    to every ancestor, even if a directory is renamed during acquisition.
    """
    handles = []
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        handles.append(os.open("/", flags))
        info = os.fstat(handles[-1])
        _regular(info, directory=True)
        for component in canonical.parts[1:]:
            handles.append(os.open(component, flags, dir_fd=handles[-1]))
            info = os.fstat(handles[-1])
            _regular(info, directory=True)
        # Only the selected directory descriptor becomes the active capability.
        return handles.pop(), info.st_dev
    finally:
        for handle in reversed(handles):
            os.close(handle)


if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class _HandleInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    _kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_HandleInfo)]
    _kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel.GetFileType.argtypes = [wintypes.HANDLE]
    _kernel.GetFileType.restype = wintypes.DWORD
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel.GetDriveTypeW.restype = wintypes.UINT

    def _win_open(path, *, directory):
        # OPEN_EXISTING; OPEN_REPARSE_POINT applies to the final component.
        # Excluding FILE_SHARE_DELETE pins directories against junction swaps.
        # READ_ATTRIBUTES alone is exempt from sharing checks and does not pin
        # a directory: GENERIC_READ is necessary for this protection.
        handle = _kernel.CreateFileW(str(path), 0x80000000,
                                     3 if directory else 1, None, 3,
                                     0x00200000 | (0x02000000 if directory else 0), None)
        if handle == ctypes.c_void_p(-1).value:
            raise _denied()
        return handle

    def _win_final(handle):
        # FILE_NAME_NORMALIZED | VOLUME_NAME_DOS, documented by Microsoft.
        size = _kernel.GetFinalPathNameByHandleW(handle, None, 0, 0)
        if not size or size > 32768:
            raise _denied()
        buffer = ctypes.create_unicode_buffer(size + 1)
        used = _kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not used or used >= len(buffer):
            raise _denied()
        path = buffer.value
        if not path.startswith("\\\\?\\") or path.startswith("\\\\?\\UNC\\"):
            raise _denied()
        return path[4:]

    def _win_check(handle, expected, *, directory, volume=None):
        info = _HandleInfo()
        if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(info)) or _kernel.GetFileType(handle) != 1:
            raise _denied()
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise _denied()
        if not directory and info.links != 1:
            raise _denied()
        final = _win_final(handle)
        # Exact normalized path also rejects in-root aliases and 8.3 shortcuts.
        if ntpath.normcase(final) != ntpath.normcase(str(expected)):
            raise _denied()
        if volume is not None and info.volume != volume:
            raise _denied()
        return info


def _excerpt(path, text, size, truncated):
    # Count CRLF as one boundary, and support LF and legacy CR line endings.
    lines = text.replace("\r\n", "\n").replace("\r", "\n")
    end_line = lines.count("\n") + (1 if lines and not lines.endswith("\n") else 0)
    return {"path": path, "text": text, "start_line": 1, "end_line": end_line,
            "size_bytes": size, "truncated": truncated,
            "excerpt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


class ProjectRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._root = None

    def __del__(self):
        # The service normally closes explicitly; release a forgotten capability.
        root = getattr(self, "_root", None)
        if root is not None:
            try:
                self._dispose(root)
            except (OSError, AttributeError):
                pass

    @staticmethod
    def _dispose(root):
        if os.name == "nt":
            _kernel.CloseHandle(root["handle"])
        else:
            os.close(root["handle"])

    def _active(self, project_id):
        if self._root is None or not isinstance(project_id, str) or project_id != self._root["info"]["id"]:
            raise ProjectFileError("project_not_found", "项目授权已失效，请重新选择目录。", 404)
        return self._root

    def open(self, path):
        with self._lock:
            if not isinstance(path, str) or not path or len(path) > 2048:
                raise _denied()
            if os.name == "nt":
                drive, tail = ntpath.splitdrive(path)
                if not re.fullmatch("[A-Za-z]:", drive) or not tail.startswith(("\\", "/")):
                    raise _denied()
                raw_parts = re.split(r"[\\/]", tail[1:])
                if not raw_parts or any(not _safe_component(p) or p.casefold() in _BLOCKED_DIRS or _sensitive(p) for p in raw_parts):
                    raise _denied()
                canonical = Path(ntpath.normpath(path))
                if _kernel.GetDriveTypeW(drive + "\\") not in (2, 3, 6):
                    raise _denied()
            else:
                canonical = Path(path)
                if not canonical.is_absolute() or canonical.anchor != "/" or canonical == Path(canonical.anchor):
                    raise _denied()
                if any(not _safe_component(p) or p.casefold() in _BLOCKED_DIRS or _sensitive(p) for p in canonical.parts[1:]):
                    raise _denied()
            handle = None
            try:
                if os.name == "nt":
                    # Windows also verifies the opened handle's final path below;
                    # these attribute checks reject existing junction ancestors.
                    for ancestor in reversed((canonical, *canonical.parents)):
                        _regular(ancestor.lstat(), directory=True)
                    handle = _win_open(canonical, directory=True)
                    info = _win_check(handle, canonical, directory=True)
                    volume = info.volume
                else:
                    handle, volume = _posix_open_root(canonical)
                new_root = {"path": canonical, "handle": handle, "volume": volume,
                            "info": {"id": secrets.token_urlsafe(24), "name": canonical.name}}
            except (OSError, ValueError):
                if handle is not None:
                    self._dispose({"handle": handle})
                raise _denied() from None
            except ProjectFileError:
                if handle is not None:
                    self._dispose({"handle": handle})
                raise
            old_root, self._root = self._root, new_root
            if old_root is not None:
                self._dispose(old_root)
            return dict(new_root["info"])

    def status(self):
        with self._lock:
            return dict(self._root["info"]) if self._root else None

    def close(self, project_id):
        with self._lock:
            root = self._active(project_id)
            self._root = None
            self._dispose(root)

    @contextmanager
    def _opened(self, root, parts, *, directory):
        handles = []
        fd = None
        try:
            if os.name == "nt":
                _win_check(root["handle"], root["path"], directory=True, volume=root["volume"])
                path = root["path"]
                for index, part in enumerate(parts):
                    path = path / part
                    is_directory = directory or index < len(parts) - 1
                    handle = _win_open(path, directory=is_directory)
                    handles.append(handle)
                    _win_check(handle, path, directory=is_directory, volume=root["volume"])
                if directory:
                    yield path
                else:
                    # msvcrt transfers ownership; this descriptor is the already
                    # checked handle, not a second path-based file opening.
                    fd = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
                    handles.pop()
                    _regular(os.fstat(fd), directory=False)
                    yield fd
            else:
                parent = root["handle"]
                for index, part in enumerate(parts):
                    is_directory = directory or index < len(parts) - 1
                    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                    if is_directory:
                        flags |= os.O_DIRECTORY
                    handle = os.open(part, flags, dir_fd=parent)
                    handles.append(handle)
                    info = os.fstat(handle)
                    _regular(info, directory=is_directory)
                    if info.st_dev != root["volume"]:
                        raise _denied()
                    parent = handle
                yield parent
        except (OSError, ValueError):
            raise _denied() from None
        finally:
            if fd is not None:
                os.close(fd)
            for handle in reversed(handles):
                if os.name == "nt":
                    _kernel.CloseHandle(handle)
                else:
                    os.close(handle)

    def list_files(self, project_id, path=""):
        with self._lock:
            root = self._active(project_id)
            parts = _parts(path, directory=True)
            entries = []
            truncated = False
            with self._opened(root, parts, directory=True) as directory:
                with os.scandir(directory) as scan:
                    for count, entry in enumerate(scan):
                        if count >= MAX_SCAN_ENTRIES or len(entries) >= MAX_ENTRIES:
                            truncated = True
                            break
                        name = entry.name
                        if not _safe_component(name) or _sensitive(name) or name.casefold() in _BLOCKED_DIRS:
                            continue
                        try:
                            # Windows DirEntry's cached stat omits link count and
                            # volume identity; request complete lstat metadata.
                            info = os.stat(entry.path, follow_symlinks=False) if os.name == "nt" else entry.stat(follow_symlinks=False)
                            is_dir = stat.S_ISDIR(info.st_mode)
                            _regular(info, directory=is_dir)
                            if info.st_dev != root["volume"] and os.name != "nt":
                                continue
                            if not is_dir and not _allowed_file(name):
                                continue
                            record = {"name": name, "path": "/".join(parts + [name]), "kind": "directory" if is_dir else "file"}
                            if not is_dir:
                                record.update(size_bytes=info.st_size, readable=True)
                            entries.append(record)
                        except (OSError, ProjectFileError):
                            continue
            entries.sort(key=lambda entry: (entry["kind"] != "directory", entry["name"].casefold(), entry["name"]))
            return {"project": dict(root["info"]), "path": path, "entries": entries, "truncated": truncated}

    def _read(self, root, path):
        parts = _parts(path)
        with self._opened(root, parts, directory=False) as fd:
            info = os.fstat(fd)
            data = bytearray()
            while len(data) < MAX_FILE_BYTES + 1:
                chunk = os.read(fd, MAX_FILE_BYTES + 1 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            byte_truncated = len(data) > MAX_FILE_BYTES
            data = bytes(data[:MAX_FILE_BYTES])
            try:
                # An incomplete UTF-8 tail may be caused by our byte boundary;
                # invalid bytes anywhere else remain a hard error.
                import codecs
                decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
                text = decoder.decode(data, final=not byte_truncated)
            except UnicodeDecodeError:
                raise ProjectFileError("project_not_text", "仅支持有效的 UTF-8 文本文件。") from None
            if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in text):
                raise ProjectFileError("project_not_text", "仅支持有效的 UTF-8 文本文件。")
            char_truncated = len(text) > MAX_FILE_CHARS
            return _excerpt(path, text[:MAX_FILE_CHARS], info.st_size, byte_truncated or char_truncated)

    def read_file(self, project_id, path):
        with self._lock:
            return self._read(self._active(project_id), path)

    @contextmanager
    def grant_transaction(self):
        """Serialize brief grant transitions and dependent memory-only cleanup."""
        with self._lock:
            yield

    def snapshot_file(self, project_id, path):
        with self._snapshot_guard(project_id, path) as snapshot:
            return snapshot

    def physical_identity(self, project_id):
        with self._lock:
            root = self._active(project_id)
            if os.name == "nt":
                info = _win_check(root["handle"], root["path"], directory=True, volume=root["volume"])
                return (info.volume, (info.index_high << 32) | info.index_low)
            info = os.fstat(root["handle"])
            return (info.st_dev, info.st_ino)

    def changes_supported(self, project_id):
        from .project_commit_windows import supported
        with self._lock:
            return supported(self._active(project_id)["path"])

    def commit_file(self, project_id, path, expected_identity, expected_sha256, replacement, checkpoint):
        from .project_commit_windows import commit_file, error
        with self._lock:
            root = self._active(project_id)
            if os.name != "nt":
                raise error("unsupported")
            parts = _parts(path)
            with self._opened(root, parts[:-1], directory=True) as parent:
                return commit_file(parent, parent / parts[-1], root["volume"], expected_identity,
                                   expected_sha256, replacement, checkpoint)

    def internal_artifact_present(self, project_id, path):
        """Conservative existence check for journal-owned names; never follows/read/writes them."""
        with self._lock:
            root = self._active(project_id)
            parts = _parts(path, directory=True)
            if not parts or re.fullmatch(r"\.campus-(?:stage|backup)-[a-f0-9]{32}\.tmp", parts[-1]) is None:
                return True
            if os.name != "nt":
                return True
            try:
                with self._opened(root, parts[:-1], directory=True) as parent:
                    _kernel.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
                    _kernel.GetFileAttributesW.restype = wintypes.DWORD
                    ctypes.set_last_error(0)
                    attributes = _kernel.GetFileAttributesW(str(parent / parts[-1]))
                    return attributes != 0xFFFFFFFF or ctypes.get_last_error() not in (2, 3)
            except ProjectFileError:
                return True

    @contextmanager
    def unchanged_snapshot(self, project_id, expected):
        """Pin a matching read-only file through a short proposal admission."""
        with self._snapshot_guard(project_id, expected.path) as current:
            if current.identity != expected.identity or current.sha256 != expected.sha256:
                raise ProjectFileError("project_proposal_conflict", "文件在生成期间发生变化，请重新生成提案。", 409)
            yield

    @contextmanager
    def _snapshot_guard(self, project_id, path):
        """Read one complete small file under the existing read capability.

        Proposal callers get raw-byte identity rather than the preview's bounded,
        BOM-stripped excerpt fingerprint. This operation never opens for writing.
        """
        with self._lock:
            root = self._active(project_id)
            parts = _parts(path)
            with self._opened(root, parts, directory=False) as fd:
                before = os.fstat(fd)
                data = bytearray()
                while len(data) <= MAX_EDIT_BYTES:
                    chunk = os.read(fd, MAX_EDIT_BYTES + 1 - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                if len(data) > MAX_EDIT_BYTES or before.st_size > MAX_EDIT_BYTES:
                    raise ProjectFileError("project_proposal_too_large", "修改提案仅支持不超过 12000 字符和 64 KiB 的完整文本文件。")
                raw = bytes(data)
                try:
                    text = raw.decode("utf-8-sig", errors="strict")
                except UnicodeDecodeError:
                    raise ProjectFileError("project_not_text", "仅支持有效的 UTF-8 文本文件。") from None
                if any(ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127 for char in text):
                    raise ProjectFileError("project_not_text", "仅支持有效的 UTF-8 文本文件。")
                if len(text) > MAX_EDIT_CHARS or text_line_count(text) > MAX_EDIT_LINES:
                    raise ProjectFileError("project_proposal_too_large", "修改提案仅支持不超过 12000 字符和 64 KiB 的完整文本文件。")
                after = os.fstat(fd)
                if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                        or len(raw) != after.st_size):
                    raise ProjectFileError("project_proposal_conflict", "文件在生成期间发生变化，请重新生成提案。", 409)
                yield ProjectSnapshot(path, text, raw, hashlib.sha256(raw).hexdigest(),
                                      (after.st_dev, after.st_ino), raw.startswith(b"\xef\xbb\xbf"), text_newline(text))

    def sources(self, project_id, files):
        with self._lock:
            root = self._active(project_id)
            if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES or any(not isinstance(path, str) for path in files):
                raise ProjectFileError("project_file_limit", "请选择 1 至 4 个不同的项目文件。")
            identities = [ntpath.normcase(path) if os.name == "nt" else path for path in files]
            if len(set(identities)) != len(files):
                raise ProjectFileError("project_file_limit", "请选择 1 至 4 个不同的项目文件。")
            # Validate every selected file, even when earlier files exhaust the
            # context budget, so an invalid selection never silently succeeds.
            excerpts = [self._read(root, path) for path in files]
            if any(not excerpt["text"].strip() for excerpt in excerpts):
                raise ProjectFileError("project_empty_file", "所选文件没有可用于问答的文本内容。")
            sources = []
            remaining = MAX_CONTEXT_CHARS
            for index, excerpt in enumerate(excerpts):
                # Reserve a fair share for every selected file; shorter earlier
                # excerpts release their unused allowance to later selections.
                allowance = remaining // (len(excerpts) - index)
                text = excerpt["text"][:allowance]
                bounded = _excerpt(excerpt["path"], text, excerpt["size_bytes"], excerpt["truncated"] or len(text) < len(excerpt["text"]))
                sources.append({"title": bounded["path"], "kind": "project", "snippet": text,
                                **{key: value for key, value in bounded.items() if key != "size_bytes"}})
                remaining -= len(text)
            return sources
