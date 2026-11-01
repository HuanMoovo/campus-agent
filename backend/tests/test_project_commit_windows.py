"""Real Windows commit tests operate exclusively on synthetic temporary trees."""
import ctypes
import hashlib
import os
from pathlib import Path

import pytest

from app.project_files import ProjectFileError, ProjectRegistry


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows NTFS commit layer")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "synthetic-commit-project"
    root.mkdir()
    (root / "src").mkdir()
    target = root / "src" / "note.txt"
    target.write_bytes(b"\xef\xbb\xbf  original\r\n\r\n")
    registry = ProjectRegistry()
    project_id = registry.open(str(root))["id"]
    yield registry, root, project_id, target
    registry.close(project_id)


def commit(project, replacement=b"\xef\xbb\xbf  proposed\r\n", checkpoint=lambda *args: None):
    registry, _, project_id, _ = project
    snapshot = registry.snapshot_file(project_id, "src/note.txt")
    return registry.commit_file(project_id, "src/note.txt", snapshot.identity, snapshot.sha256, replacement, checkpoint)


@pytest.fixture
def native_security_pair(tmp_path):
    from app import project_commit_windows as native
    original_path = tmp_path / "original-owned-security.txt"
    staging_path = tmp_path / "staging-owned-security.txt"
    original_path.write_bytes(b"owned security regression\r\n")
    assert native.supported(original_path)
    original = staging = None
    try:
        original = native._open(original_path)
        staging = native._open(staging_path, create=True)
        yield native, original, staging
    finally:
        for handle in (staging, original):
            if handle is not None:
                native.K.CloseHandle(handle)


def test_identical_native_security_is_preserved_without_reapplying_acl(native_security_pair, monkeypatch):
    native, original, staging = native_security_pair
    expected = native._security(original)
    assert native._security(staging) == expected
    def must_not_reapply(*args):
        pytest.fail("Already identical native security must not be reapplied")
    monkeypatch.setattr(native.A, "SetSecurityInfo", must_not_reapply)
    native._copy_security(original, staging)
    assert native._security(original) == expected
    assert native._security(staging) == expected


def test_differing_native_acl_requires_exact_post_copy_security(native_security_pair, monkeypatch):
    native, original, staging = native_security_pair
    expected = native._security(original)
    acl = bytearray(expected["dacl"])
    assert int.from_bytes(acl[4:6], "little") > 0 and acl[8] == 0
    mask = int.from_bytes(acl[12:16], "little")
    acl[12:16] = (mask ^ 1).to_bytes(4, "little")
    buffer = ctypes.create_string_buffer(bytes(acl))
    assert native.A.SetSecurityInfo(staging, 1, 4 | 0x80000000, None, None, buffer, None) == 0
    different = native._security(staging)
    assert different["dacl"] != expected["dacl"]
    assert all(different[key] == expected[key] for key in ("owner", "group", "label"))
    # A successful API return without the required security effect must fail closed.
    monkeypatch.setattr(native.A, "SetSecurityInfo", lambda *args: 0)
    with pytest.raises(ProjectFileError) as caught:
        native._copy_security(original, staging)
    assert caught.value.error_code == "project_change_unsupported"
    assert native._security(original) == expected
    assert native._security(staging) == different


def test_cow_changes_inode_and_preserves_original_alias_bytes(project, tmp_path):
    registry, root, project_id, target = project
    original = target.read_bytes()
    before = registry.snapshot_file(project_id, "src/note.txt")
    alias = tmp_path / "synthetic-outside-alias.txt"
    phases = []
    def checkpoint(phase, details):
        phases.append(phase)
        if phase == "prepared":
            os.link(target, alias)
    result = commit(project, checkpoint=checkpoint)
    assert result["state"] == "applied"
    assert target.read_bytes() == b"\xef\xbb\xbf  proposed\r\n"
    assert alias.read_bytes() == original
    after = registry.snapshot_file(project_id, "src/note.txt")
    assert after.identity != before.identity
    assert tuple(result["after_identity"]) == after.identity
    assert phases[:3] == ["planned", "prepared", "original_moved"]


def test_gap_occupant_is_never_overwritten_and_original_is_retained(project):
    registry, root, project_id, target = project
    original = target.read_bytes()
    details_seen = {}
    def checkpoint(phase, details):
        details_seen.update(details)
        if phase == "original_moved":
            target.write_bytes(b"USER_CREATED_DURING_GAP")
    result = commit(project, checkpoint=checkpoint)
    assert result["state"] == "uncertain"
    assert target.read_bytes() == b"USER_CREATED_DURING_GAP"
    assert (target.parent / details_seen["backup_name"]).read_bytes() == original


@pytest.mark.parametrize("fault", ["write", "flush", "publication"])
def test_commit_failures_leave_original_or_restore_without_writing_it(project, monkeypatch, fault):
    from app import project_commit_windows as native
    registry, _, project_id, target = project
    original = target.read_bytes()
    identity = registry.snapshot_file(project_id, "src/note.txt").identity
    if fault in ("write", "flush"):
        def fail(*args):
            raise OSError("synthetic fault")
        monkeypatch.setattr(native, "_write_all" if fault == "write" else "_flush", fail)
    else:
        real_rename = native._rename
        count = [0]
        def rename(*args):
            count[0] += 1
            if count[0] == 2:
                raise OSError("synthetic publication fault")
            return real_rename(*args)
        monkeypatch.setattr(native, "_rename", rename)
    result = commit(project)
    assert result["state"] == "failed"
    assert target.read_bytes() == original
    assert registry.snapshot_file(project_id, "src/note.txt").identity == identity


def test_existing_writer_is_busy_and_never_modified(project):
    registry, _, project_id, target = project
    original = target.read_bytes()
    snapshot = registry.snapshot_file(project_id, "src/note.txt")
    with target.open("r+b"):
        with pytest.raises(ProjectFileError) as caught:
            registry.commit_file(project_id, "src/note.txt", snapshot.identity, snapshot.sha256, b"new", lambda *args: None)
    assert caught.value.error_code == "project_change_busy"
    assert target.read_bytes() == original


@pytest.mark.parametrize("metadata", ["readonly", "ads"])
def test_unsupported_metadata_is_refused_before_original_mutation(project, metadata):
    _, _, _, target = project
    original = target.read_bytes()
    if metadata == "readonly":
        assert ctypes.windll.kernel32.SetFileAttributesW(str(target), 1)
    else:
        Path(str(target) + ":synthetic-stream").write_bytes(b"STREAM_SENTINEL")
    try:
        with pytest.raises(ProjectFileError) as caught:
            commit(project)
        assert caught.value.error_code == "project_change_unsupported"
        assert target.read_bytes() == original
    finally:
        if metadata == "readonly":
            ctypes.windll.kernel32.SetFileAttributesW(str(target), 128)


def test_stale_full_hash_or_identity_is_conflict_before_mutation(project):
    registry, _, project_id, target = project
    snapshot = registry.snapshot_file(project_id, "src/note.txt")
    target.write_bytes(b"USER_CHANGED")
    with pytest.raises(ProjectFileError) as caught:
        registry.commit_file(project_id, "src/note.txt", snapshot.identity, snapshot.sha256, b"proposed", lambda *args: None)
    assert caught.value.error_code == "project_change_conflict"
    assert target.read_bytes() == b"USER_CHANGED"


def test_rename_that_moves_then_reports_failure_never_claims_untouched(project, monkeypatch):
    from app import project_commit_windows as native
    _, _, _, target = project
    original = target.read_bytes()
    real = native._rename
    first = [True]
    def moved_then_error(*args):
        real(*args)
        if first[0]:
            first[0] = False
            raise OSError("synthetic post-rename validation fault")
    monkeypatch.setattr(native, "_rename", moved_then_error)
    result = commit(project)
    assert result["state"] in ("failed", "uncertain")
    if result["state"] == "failed":
        assert target.read_bytes() == original


def test_protected_dacl_is_preserved_on_new_inode(project):
    from app import project_commit_windows as native
    _, _, _, target = project
    handle = native.K.CreateFileW(str(target), 0xC0050000, 0, None, 3, 0x00200000, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        security = native._security(handle)
        acl = ctypes.create_string_buffer(security["dacl"])
        assert native.A.SetSecurityInfo(handle, 1, 4 | 0x80000000, None, None, acl, None) == 0
        expected = native._security(handle)
        assert expected["protected"]
    finally:
        native.K.CloseHandle(handle)
    assert commit(project)["state"] == "applied"
    handle = native._open(target)
    try:
        assert native._security(handle) == expected
    finally:
        native.K.CloseHandle(handle)


def test_existing_writable_mapping_refuses_commit(project):
    import mmap
    registry, _, project_id, target = project
    snapshot = registry.snapshot_file(project_id, "src/note.txt")
    with target.open("r+b") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_WRITE)
    try:
        with pytest.raises(ProjectFileError) as caught:
            registry.commit_file(project_id, "src/note.txt", snapshot.identity, snapshot.sha256, b"new", lambda *args: None)
        assert caught.value.error_code == "project_change_busy"
    finally:
        mapped.close()


def test_owner_group_mismatch_is_refused_before_target_move(project, monkeypatch):
    from app import project_commit_windows as native
    _, _, _, target = project
    original = target.read_bytes()
    real = native._security
    calls = [0]
    def mismatch(handle):
        calls[0] += 1
        security = real(handle)
        if calls[0] == 3:
            security["owner"] = b"different synthetic owner"
        return security
    monkeypatch.setattr(native, "_security", mismatch)
    with pytest.raises(ProjectFileError) as caught:
        commit(project)
    assert caught.value.error_code == "project_change_unsupported"
    assert target.read_bytes() == original


def test_integrity_label_mismatch_is_refused_before_target_move(project, monkeypatch):
    from app import project_commit_windows as native
    _, _, _, target = project
    original = target.read_bytes()
    assert hasattr(native, "_label")
    real = native._label
    def mismatch(handle):
        label = real(handle)
        return b"different-label" if ".campus-stage-" in native.files._win_final(handle) else label
    monkeypatch.setattr(native, "_label", mismatch)
    with pytest.raises(ProjectFileError) as caught:
        commit(project)
    assert caught.value.error_code == "project_change_unsupported"
    assert target.read_bytes() == original
