"""Only synthetic temporary projects are opened by these filesystem tests."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app.project_files import ProjectFileError, ProjectRegistry
from app import project_files


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "synthetic-project"
    root.mkdir()
    registry = ProjectRegistry()
    info = registry.open(str(root))
    yield registry, root, info["id"]
    current = registry.status()
    if current:
        registry.close(current["id"])


def rejected(call):
    with pytest.raises(ProjectFileError) as caught:
        call()
    assert caught.value.error_code
    assert caught.value.status_code in (404, 409, 422)
    return caught.value


def test_open_reselect_close_revokes_ids(project, tmp_path):
    registry, root, old_id = project
    assert registry.status() == {"id": old_id, "name": "synthetic-project"}
    (root / "one.py").write_text("one", encoding="utf-8")
    second = tmp_path / "another"
    second.mkdir()
    current = registry.open(str(second))
    assert current["id"] != old_id
    rejected(lambda: registry.read_file(old_id, "one.py"))
    rejected(lambda: registry.close(old_id))
    assert registry.status() == current
    registry.close(current["id"])
    assert registry.status() is None
    rejected(lambda: registry.list_files(current["id"]))


@pytest.mark.parametrize("path", ["../outside.py", "/x.py", "C:/x.py", "a\\x.py", "a/../x.py", "./x.py", "a//x.py", "x.py:secret", "x.py ", "x.py.", "CON.txt", "a\x00.py", "a\n.py", "~1.py"])
def test_relative_path_bypasses_rejected(project, path):
    registry, _, project_id = project
    rejected(lambda: registry.read_file(project_id, path))


@pytest.mark.parametrize("name", [".env", ".ENV.local", "credentials.json", "secrets.yaml", "api-keys.json", "model_config.json", "id_rsa", "private.pem", "cert.p12", "program.exe", "photo.png"])
def test_sensitive_and_non_text_files_not_listed_or_read(project, name):
    registry, root, project_id = project
    (root / name).write_text("synthetic secret", encoding="utf-8")
    assert registry.list_files(project_id)["entries"] == []
    rejected(lambda: registry.read_file(project_id, name))


@pytest.mark.parametrize("name", [".git", ".SSH", ".aws", ".codex", ".agents", "node_modules", ".venv", "venv", "dist", "build"])
def test_sensitive_directories_not_listed_or_traversed(project, name):
    registry, root, project_id = project
    directory = root / name
    directory.mkdir()
    (directory / "x.py").write_text("synthetic", encoding="utf-8")
    assert registry.list_files(project_id)["entries"] == []
    rejected(lambda: registry.list_files(project_id, name))
    rejected(lambda: registry.read_file(project_id, f"{name}/x.py"))


def test_listing_is_one_level_and_read_preserves_text_and_hash(project):
    registry, root, project_id = project
    (root / "src").mkdir()
    (root / "src" / "app.py").write_bytes(b"\xef\xbb\xbfhello\r\nworld\n")
    listing = registry.list_files(project_id)
    assert listing == {"project": registry.status(), "path": "", "entries": [{"name": "src", "path": "src", "kind": "directory"}], "truncated": False}
    assert registry.list_files(project_id, "src")["entries"] == [{"name": "app.py", "path": "src/app.py", "kind": "file", "size_bytes": 16, "readable": True}]
    excerpt = registry.read_file(project_id, "src/app.py")
    assert excerpt == {"path": "src/app.py", "text": "hello\r\nworld\n", "start_line": 1, "end_line": 2, "size_bytes": 16, "truncated": False, "excerpt_sha256": hashlib.sha256(b"hello\r\nworld\n").hexdigest()}


@pytest.mark.parametrize("data", [b"valid\x00binary", b"\xff\xfe\x00\x00", b"\x01\x02\x03", b"\xff"])
def test_binary_and_invalid_utf8_rejected(project, data):
    registry, root, project_id = project
    (root / "x.py").write_bytes(data)
    rejected(lambda: registry.read_file(project_id, "x.py"))


def test_truncation_counts_lines_and_hashes_actual_excerpt(project):
    registry, root, project_id = project
    (root / "long.py").write_bytes(("α\n" * 150000).encode())
    excerpt = registry.read_file(project_id, "long.py")
    assert excerpt["text"] == "α\n" * 6000
    assert excerpt["end_line"] == 6000
    assert excerpt["truncated"] is True
    assert excerpt["size_bytes"] == 450000
    assert excerpt["excerpt_sha256"] == hashlib.sha256(excerpt["text"].encode()).hexdigest()


def test_utf8_partial_tail_at_byte_limit_is_not_invalid_encoding(project):
    registry, root, project_id = project
    (root / "long.txt").write_bytes(("€" * 100000).encode())
    excerpt = registry.read_file(project_id, "long.txt")
    assert excerpt["text"] == "€" * 12000
    assert excerpt["truncated"] is True


def test_empty_excerpt_has_no_fabricated_line(project):
    registry, root, project_id = project
    (root / "empty.py").write_bytes(b"")
    excerpt = registry.read_file(project_id, "empty.py")
    assert (excerpt["start_line"], excerpt["end_line"], excerpt["text"]) == (1, 0, "")


@pytest.mark.parametrize("text,end_line", [("a\rb\r", 2), ("a\rb", 2), ("a\r\nb\nc", 3)])
def test_line_ranges_include_cr_and_mixed_newlines(project, text, end_line):
    registry, root, project_id = project
    (root / "lines.txt").write_bytes(text.encode())
    excerpt = registry.read_file(project_id, "lines.txt")
    assert excerpt["text"] == text
    assert excerpt["end_line"] == end_line


def test_sources_limit_is_shared_and_metadata_describes_exact_text(project):
    registry, root, project_id = project
    for i in range(5):
        (root / f"{i}.py").write_bytes(b"a\n" * 7000)
    sources = registry.sources(project_id, ["0.py", "1.py", "2.py", "3.py"])
    assert sum(len(source["text"]) for source in sources) <= 16000
    assert [len(source["text"]) for source in sources] == [4000, 4000, 4000, 4000]
    for source in sources:
        assert source["kind"] == "project"
        assert source["title"] == source["path"]
        assert source["snippet"] == source["text"]
        assert source["truncated"] is True
        assert source["end_line"] == len(source["text"]) // 2
        assert source["excerpt_sha256"] == hashlib.sha256(source["text"].encode()).hexdigest()
    rejected(lambda: registry.sources(project_id, [f"{i}.py" for i in range(5)]))
    rejected(lambda: registry.sources(project_id, ["0.py", "0.py"]))
    rejected(lambda: registry.sources(project_id, ["0.py", "1.py", "missing.py"]))


def test_empty_files_preview_consistently_but_cannot_be_question_context(project):
    registry, root, project_id = project
    (root / "empty.py").write_bytes(b"")
    rejected(lambda: registry.sources(project_id, ["empty.py"]))


def test_listing_has_bounded_output_and_reports_omission(project):
    registry, root, project_id = project
    for i in range(350):
        (root / f"f{i:04}.py").write_bytes(b"")
    listing = registry.list_files(project_id)
    assert len(listing["entries"]) == 300
    assert listing["truncated"] is True
    assert [entry["name"] for entry in listing["entries"]] == sorted(entry["name"] for entry in listing["entries"])


def test_hardlinks_rejected_even_when_target_inside_project(project):
    registry, root, project_id = project
    (root / "a.py").write_text("synthetic", encoding="utf-8")
    os.link(root / "a.py", root / "b.py")
    rejected(lambda: registry.read_file(project_id, "a.py"))
    rejected(lambda: registry.read_file(project_id, "b.py"))
    assert registry.list_files(project_id)["entries"] == []


def test_symlink_file_and_directory_rejected(project, tmp_path):
    registry, root, project_id = project
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_bytes(b"outside")
    links = []
    try:
        try:
            os.symlink(outside / "x.py", root / "link.py")
            links.append(root / "link.py")
            os.symlink(outside, root / "link", target_is_directory=True)
            links.append(root / "link")
        except OSError as error:
            if os.name == "nt" and error.winerror == 1314:
                pytest.skip("Windows account has no symlink privilege")
            raise
        rejected(lambda: registry.read_file(project_id, "link.py"))
        rejected(lambda: registry.read_file(project_id, "link/x.py"))
        assert registry.list_files(project_id)["entries"] == []
    finally:
        for link in reversed(links):
            assert link.parent == root and link.is_symlink()
            if link.is_dir() and os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows case aliases")
def test_sources_reject_case_aliases_of_same_file(project):
    registry, root, project_id = project
    (root / "a.py").write_bytes(b"synthetic")
    rejected(lambda: registry.sources(project_id, ["a.py", "A.PY"]))


@pytest.mark.skipif(os.name != "nt", reason="real Windows junction")
def test_real_junction_inside_or_outside_project_rejected(project, tmp_path):
    registry, root, project_id = project
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_text("never read me", encoding="utf-8")
    (root / "target").mkdir()
    (root / "target" / "x.py").write_text("also rejected via junction", encoding="utf-8")
    for name, target in [("escape", outside), ("alias", root / "target")]:
        link = root / name
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        try:
            rejected(lambda: registry.read_file(project_id, f"{name}/x.py"))
            rejected(lambda: registry.list_files(project_id, name))
            assert name not in [entry["name"] for entry in registry.list_files(project_id)["entries"]]
            other = ProjectRegistry()
            rejected(lambda: other.open(str(link)))
        finally:
            # rmdir removes only the checked junction itself, never its target.
            assert link.parent == root and link.lstat().st_file_attributes & 0x400
            os.rmdir(link)
    assert (outside / "x.py").read_text() == "never read me"


@pytest.mark.skipif(os.name != "nt", reason="Windows roots")
@pytest.mark.parametrize("path", ["C:\\", "C:", "\\\\server\\share\\project", "\\\\?\\C:\\project", "\\\\.\\C:\\project"])
def test_windows_non_local_or_drive_roots_rejected(path):
    rejected(lambda: ProjectRegistry().open(path))


def test_errors_do_not_disclose_absolute_paths(project):
    registry, root, project_id = project
    error = rejected(lambda: registry.read_file(project_id, "missing.py"))
    assert str(root) not in str(error)
    assert "missing.py" not in str(error)


@pytest.mark.skipif(os.name != "nt", reason="real Windows handles")
def test_opened_handle_redirected_outside_root_is_rejected_before_read(project, tmp_path, monkeypatch):
    registry, root, project_id = project
    (root / "safe.py").write_bytes(b"safe")
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"outside must never be read")
    real_open = project_files._win_open

    def redirected(path, *, directory):
        # A real outside handle models a junction change between path validation
        # and opening. Its final path, rather than the requested string, matters.
        return real_open(outside if not directory else path, directory=directory)

    def must_not_read(*args):
        pytest.fail("content read before handle boundary validation")

    monkeypatch.setattr(project_files, "_win_open", redirected)
    monkeypatch.setattr(project_files.os, "read", must_not_read)
    rejected(lambda: registry.read_file(project_id, "safe.py"))


@pytest.mark.skipif(os.name != "nt", reason="real Windows junction race")
def test_junction_swap_during_open_cannot_read_outside(project, tmp_path, monkeypatch):
    registry, root, project_id = project
    source = root / "src"
    source.mkdir()
    (source / "x.py").write_bytes(b"inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_bytes(b"outside")
    real_open = project_files._win_open
    swapped = False

    def swap_then_open(path, *, directory):
        nonlocal swapped
        if Path(path) == source and not swapped:
            os.rename(source, root / "original")
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(source), str(outside)], capture_output=True)
            assert result.returncode == 0
            swapped = True
        return real_open(path, directory=directory)

    monkeypatch.setattr(project_files, "_win_open", swap_then_open)
    try:
        rejected(lambda: registry.read_file(project_id, "src/x.py"))
        assert swapped
    finally:
        if swapped:
            assert source.parent == root and source.lstat().st_file_attributes & 0x400
            os.rmdir(source)
    assert (outside / "x.py").read_bytes() == b"outside"


@pytest.mark.skipif(os.name != "nt", reason="real Windows sharing semantics")
def test_open_directory_is_pinned_against_rename_before_file_open(project, monkeypatch):
    registry, root, project_id = project
    source = root / "src"
    source.mkdir()
    (source / "x.py").write_bytes(b"inside")
    real_open = project_files._win_open
    attempted = False

    def try_rename_then_open(path, *, directory):
        nonlocal attempted
        if not directory:
            with pytest.raises(PermissionError):
                os.rename(source, root / "replaced")
            attempted = True
        return real_open(path, directory=directory)

    monkeypatch.setattr(project_files, "_win_open", try_rename_then_open)
    assert registry.read_file(project_id, "src/x.py")["text"] == "inside"
    assert attempted


def test_read_bytes_are_bounded_not_just_returned_text(project, monkeypatch):
    registry, root, project_id = project
    (root / "large.py").write_bytes(b"a" * 400000)
    real_read = os.read
    read_bytes = 0

    def count_read(fd, size):
        nonlocal read_bytes
        data = real_read(fd, size)
        read_bytes += len(data)
        return data

    monkeypatch.setattr(project_files.os, "read", count_read)
    assert len(registry.read_file(project_id, "large.py")["text"]) == 12000
    assert read_bytes == 262145


def test_scanning_stops_on_many_excluded_entries(project, monkeypatch):
    registry, root, project_id = project
    (root / "hidden.exe").write_bytes(b"")
    real_scandir = os.scandir
    consumed = 0

    class HugeDirectory:
        def __init__(self, directory):
            with real_scandir(directory) as scan:
                self.entry = next(scan)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal consumed
            consumed += 1
            if consumed > 1201:
                pytest.fail("unbounded directory enumeration")
            return self.entry

    monkeypatch.setattr(project_files.os, "scandir", HugeDirectory)
    listing = registry.list_files(project_id)
    assert consumed == 1201
    assert listing["entries"] == []
    assert listing["truncated"] is True


def test_close_serializes_with_active_sources_and_revokes_future_reads(project, monkeypatch):
    registry, root, project_id = project
    (root / "x.py").write_bytes(b"inside")
    reading = threading.Event()
    release = threading.Event()
    closing = threading.Event()
    closed = threading.Event()
    results = []
    failures = []
    real_read = os.read

    def held_read(fd, size):
        reading.set()
        assert release.wait(5)
        return real_read(fd, size)

    def read_source():
        try:
            results.extend(registry.sources(project_id, ["x.py"]))
        except BaseException as error:
            failures.append(error)

    def close_project():
        closing.set()
        registry.close(project_id)
        closed.set()

    monkeypatch.setattr(project_files.os, "read", held_read)
    reader = threading.Thread(target=read_source)
    closer = threading.Thread(target=close_project)
    reader.start()
    try:
        assert reading.wait(5)
        closer.start()
        assert closing.wait(5)
        assert not closed.wait(0.05)
    finally:
        release.set()
        reader.join(5)
        if closer.ident is not None:
            closer.join(5)
    assert not failures
    assert closed.is_set()
    assert results[0]["text"] == "inside"
    rejected(lambda: registry.read_file(project_id, "x.py"))


@pytest.fixture
def synthetic_posix(monkeypatch):
    """Exercise the POSIX branch on Windows without changing process os.name."""
    live = {}
    calls = []
    closed = []
    next_fd = 100
    fail_at = set()
    invalid_at = set()
    directory_info = lambda fd: SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_dev=9, st_ino=fd, st_nlink=2)

    class SyntheticPath(PurePosixPath):
        # Allow the former lstat/stat preflight so the test fails specifically
        # when production tries the unsafe full-path open, rather than because
        # the synthetic path has no filesystem methods.
        def lstat(self):
            return directory_info(1)

        def stat(self):
            return directory_info(1)

    def opened(path, flags, *, dir_fd=None):
        nonlocal next_fd
        path = str(path)
        assert flags & 0x10000 and flags & 0x20000, "directory and no-follow flags must apply at every hop"
        if dir_fd is None:
            assert path == "/", "root acquisition must not open an absolute path through mutable ancestors"
            resolved = "/"
        else:
            assert dir_fd in live, "parent descriptor closed before opening its child"
            assert "/" not in path and path not in (".", ".."), "only one component may be resolved per open"
            resolved = live[dir_fd].rstrip("/") + "/" + path
        calls.append((path, dir_fd))
        if resolved in fail_at:
            raise OSError("synthetic symlink swap")
        fd = next_fd
        next_fd += 1
        live[fd] = resolved
        return fd

    def fstat(fd):
        info = directory_info(fd)
        if live[fd] in invalid_at:
            info.st_mode = stat.S_IFREG | 0o600
        return info

    def close(fd):
        assert fd in live, "descriptor closed twice"
        closed.append(live.pop(fd))

    fake_os = SimpleNamespace(name="posix", O_RDONLY=0, O_DIRECTORY=0x10000,
                              O_NOFOLLOW=0x20000, open=opened, fstat=fstat, close=close)
    monkeypatch.setattr(project_files, "os", fake_os)
    monkeypatch.setattr(project_files, "Path", SyntheticPath)
    return SimpleNamespace(live=live, calls=calls, closed=closed, fail_at=fail_at, invalid_at=invalid_at)


def test_posix_root_is_opened_one_component_at_a_time(synthetic_posix):
    registry = ProjectRegistry()
    info = registry.open("/workspace/project")
    try:
        assert info["name"] == "project"
        assert synthetic_posix.calls == [("/", None), ("workspace", 100), ("project", 101)]
        assert list(synthetic_posix.live.values()) == ["/workspace/project"]
        assert set(synthetic_posix.closed) == {"/", "/workspace"}
    finally:
        current = registry.status()
        if current:
            registry.close(current["id"])
    assert synthetic_posix.live == {}


@pytest.mark.parametrize("failure", ["open", "not_directory"])
def test_posix_failed_root_acquisition_closes_every_descriptor(synthetic_posix, failure):
    if failure == "open":
        synthetic_posix.fail_at.add("/workspace/project")
    else:
        synthetic_posix.invalid_at.add("/workspace/project")
    registry = ProjectRegistry()
    rejected(lambda: registry.open("/workspace/project"))
    assert registry.status() is None
    assert synthetic_posix.live == {}


def test_posix_sensitive_ancestor_is_rejected_before_any_open(synthetic_posix):
    registry = ProjectRegistry()
    rejected(lambda: registry.open("/workspace/.ssh/project"))
    assert synthetic_posix.calls == []
    assert synthetic_posix.live == {}


def test_posix_failed_reselection_preserves_old_authorization_without_leaks(synthetic_posix):
    registry = ProjectRegistry()
    current = registry.open("/workspace/project")
    try:
        synthetic_posix.fail_at.add("/workspace/other")
        rejected(lambda: registry.open("/workspace/other"))
        assert registry.status() == current
        assert list(synthetic_posix.live.values()) == ["/workspace/project"]
    finally:
        registry.close(current["id"])
    assert synthetic_posix.live == {}


@pytest.mark.skipif(os.name == "nt", reason="requires native POSIX dir_fd and O_NOFOLLOW")
def test_posix_ancestor_swapped_to_symlink_during_root_acquisition(tmp_path, monkeypatch):
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir()
    (ancestor / "project").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "project").mkdir()
    (outside / "project" / "x.py").write_bytes(b"outside must not be authorized")
    real_open = os.open
    swapped = False

    def swap_then_open(path, flags, *, dir_fd=None, **kwargs):
        nonlocal swapped
        if not swapped and (str(path) == "ancestor" or str(path) == str(ancestor / "project")):
            ancestor.rename(tmp_path / "original")
            ancestor.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_open(path, flags, dir_fd=dir_fd, **kwargs)

    registry = ProjectRegistry()
    monkeypatch.setattr(project_files.os, "open", swap_then_open)
    try:
        rejected(lambda: registry.open(str(ancestor / "project")))
        assert swapped
        assert registry.status() is None
    finally:
        current = registry.status()
        if current:
            registry.close(current["id"])
        if swapped:
            assert ancestor.parent == tmp_path and ancestor.is_symlink()
            ancestor.unlink()
