"""Desktop change grants and durable recovery use synthetic NTFS projects only."""
import hashlib
import json
import os
import sqlite3
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import agent, model_client, project_api
from app.project_files import ProjectFileError, ProjectRegistry
from app.project_proposals import ProjectProposalStore


TOKEN = "a" * 64
GRANT = "b" * 64
WRITE = "c" * 64
BEFORE = b"\xef\xbb\xbf  original\r\n\r\n"
AFTER = b"\xef\xbb\xbf  replacement\r\n\r\n"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Production editing is Windows NTFS only")


@pytest.fixture
def change_client(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("CAMPUS_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAMPUS_DESKTOP_TOKEN", TOKEN)
    monkeypatch.setenv("CAMPUS_DESKTOP_PORT", "8395")
    monkeypatch.setenv("CAMPUS_PROJECT_GRANT_TOKEN", GRANT)
    monkeypatch.setenv("CAMPUS_PROJECT_WRITE_TOKEN", WRITE)
    fixture_root = tmp_path_factory.mktemp("change-api")
    data_dir = fixture_root / "isolated-change-data"
    data_dir.mkdir()
    monkeypatch.setenv("CAMPUS_DATA_DIR", str(data_dir))
    registry = ProjectRegistry()
    monkeypatch.setattr(project_api, "registry", registry)
    monkeypatch.setattr(project_api, "proposals", ProjectProposalStore())
    if hasattr(project_api, "changes"):
        monkeypatch.setattr(project_api, "changes", type(project_api.changes)(data_dir=data_dir))
    project = fixture_root / "synthetic-change-project"
    project.mkdir()
    (project / "README.md").write_bytes(BEFORE)
    selected = ("openai_compatible", "fixture-key", "https://fixture.invalid/v1", "fixture-model")
    monkeypatch.setattr(agent, "choose_model", lambda *args: selected)
    monkeypatch.setattr(agent, "provider_settings", lambda *args: {"protocol": "responses", "request_options": {}})
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": json.dumps({"replacement_text": AFTER[3:].decode(), "summary": "Update selected text."}),
        "tool_calls": [],
    })
    app = FastAPI()
    app.include_router(project_api.router)
    with TestClient(app, base_url="http://127.0.0.1:8395", client=("127.0.0.1", 12345),
                    headers={"X-Campus-Desktop-Token": TOKEN}) as client:
        opened = client.post("/api/projects/open", json={"path": str(project)},
                             headers={"X-Campus-Project-Grant": GRANT})
        assert opened.status_code == 200, opened.text
        project_id = opened.json()["project"]["id"]
        yield client, project, project_id, data_dir
    active = registry.status()
    if active:
        registry.close(active["id"])


def proposal(client, project_id):
    result = client.post(f"/api/projects/{project_id}/proposals", json={
        "path": "README.md", "instruction": "Update the selected text.", "model": "auto"})
    assert result.status_code == 200, result.text
    return result.json()


def prepare(client, project_id, subject_id, action="apply", **kwargs):
    return client.post(f"/api/projects/{project_id}/changes/prepare",
                       json={"subject_id": subject_id, "action": action},
                       headers=kwargs.pop("headers", {"X-Campus-Project-Write": WRITE}), **kwargs)


def commit(client, project_id, subject_id, digest, action="apply", operation_id=None, **kwargs):
    return client.post(f"/api/projects/{project_id}/changes/commit", json={
        "subject_id": subject_id, "action": action, "digest": digest,
        "operation_id": operation_id or str(uuid4())},
        headers=kwargs.pop("headers", {"X-Campus-Project-Write": WRITE}), **kwargs)


def applied(client, project_id):
    draft = proposal(client, project_id)
    planned = prepare(client, project_id, draft["id"])
    assert planned.status_code == 200, planned.text
    operation_id = str(uuid4())
    result = commit(client, project_id, draft["id"], planned.json()["digest"], operation_id=operation_id)
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "applied", result.text
    return draft, planned.json(), result.json()


@pytest.mark.parametrize("headers", [{}, {"X-Campus-Project-Write": TOKEN},
                                      {"X-Campus-Project-Write": GRANT},
                                      [("X-Campus-Project-Write", WRITE), ("X-Campus-Project-Write", WRITE)]],
                         ids=["missing", "renderer-token", "root-grant", "duplicate"])
def test_write_routes_require_private_single_write_grant(change_client, headers):
    client, folder, project_id, _ = change_client
    draft = proposal(client, project_id)
    assert prepare(client, project_id, draft["id"], headers=headers).status_code == 403
    result = commit(client, project_id, draft["id"], "d" * 64, headers=headers)
    assert result.status_code == 403
    assert (folder / "README.md").read_bytes() == BEFORE


@pytest.mark.parametrize("headers", [{"X-Campus-Desktop-Token": "", "X-Campus-Project-Write": WRITE},
                                      {"Host": "foreign.example", "X-Campus-Project-Write": WRITE}])
def test_write_secret_does_not_replace_desktop_identity(change_client, headers):
    client, folder, project_id, _ = change_client
    draft = proposal(client, project_id)
    assert prepare(client, project_id, draft["id"], headers=headers).status_code == 403
    assert commit(client, project_id, draft["id"], "d" * 64, headers=headers).status_code == 403
    assert (folder / "README.md").read_bytes() == BEFORE


def test_prepare_is_reviewable_and_never_mutates_project(change_client):
    client, folder, project_id, data_dir = change_client
    draft = proposal(client, project_id)
    result = prepare(client, project_id, draft["id"])
    assert result.status_code == 200, result.text
    plan = result.json()
    assert plan["project_id"] == project_id and plan["subject_id"] == draft["id"]
    assert plan["proposal_id"] == draft["id"] and plan["action"] == "apply"
    assert plan["path"] == "README.md" and plan["summary"] == draft["summary"]
    assert plan["expected_sha256"] == hashlib.sha256(BEFORE).hexdigest()
    assert plan["target_sha256"] == hashlib.sha256(AFTER).hexdigest()
    assert len(plan["digest"]) == 64 and int(plan["digest"], 16) >= 0
    assert (folder / "README.md").read_bytes() == BEFORE
    assert sorted(item.name for item in folder.iterdir()) == ["README.md"]
    assert str(folder) not in json.dumps(plan)


def test_apply_is_durable_and_operation_retry_does_not_rewrite(change_client, monkeypatch):
    client, folder, project_id, data_dir = change_client
    before_identity = (folder / "README.md").stat().st_ino
    draft, plan, receipt = applied(client, project_id)
    target = folder / "README.md"
    assert target.read_bytes() == AFTER and target.stat().st_ino != before_identity
    applied_identity = target.stat().st_ino
    assert receipt["action"] == "apply" and receipt["can_revert"] is True
    assert receipt["subject_id"] == draft["id"] and receipt["proposal_id"] == draft["id"]
    assert receipt["recovery_id"] and receipt["digest"] == plan["digest"]
    assert str(folder) not in json.dumps(receipt)
    monkeypatch.setattr(project_api.registry, "commit_file", lambda *args, **kwargs: pytest.fail("Idempotent retry wrote again"))
    retried = commit(client, project_id, draft["id"], plan["digest"], operation_id=receipt["operation_id"])
    assert retried.status_code == 200 and retried.json() == receipt
    assert target.stat().st_ino == applied_identity
    queried = client.get(f"/api/projects/{project_id}/changes/operations/{receipt['operation_id']}")
    assert queried.status_code == 200 and queried.json() == receipt
    listed = client.get(f"/api/projects/{project_id}/changes")
    assert listed.status_code == 200 and listed.json()["available"] is True
    assert any(row["recovery_id"] == receipt["recovery_id"] for row in listed.json()["records"])
    journal = data_dir / "project-changes.sqlite3"
    assert journal.is_file()
    assert str(folder).encode() not in journal.read_bytes()


def test_same_operation_cannot_change_binding_and_proposal_cannot_apply_twice(change_client):
    client, folder, project_id, _ = change_client
    draft, plan, receipt = applied(client, project_id)
    for subject, digest, operation in ((draft["id"], "e" * 64, receipt["operation_id"]),
                                       (draft["id"], plan["digest"], str(uuid4()))):
        result = commit(client, project_id, subject, digest, operation_id=operation)
        assert result.status_code == 409, result.text
        assert result.headers.get("X-Project-Error") == "project_change_conflict"
    assert (folder / "README.md").read_bytes() == AFTER


def test_reselect_same_physical_root_retains_original_after_proposal_expiry_and_restart(change_client, monkeypatch):
    client, folder, project_id, data_dir = change_client
    _, _, receipt = applied(client, project_id)
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    monkeypatch.setattr(project_api, "changes", type(project_api.changes)(data_dir=data_dir))
    reopened = client.post("/api/projects/open", json={"path": str(folder)}, headers={"X-Campus-Project-Grant": GRANT})
    assert reopened.status_code == 200, reopened.text
    current_id = reopened.json()["project"]["id"]
    assert current_id != project_id
    assert client.get(f"/api/projects/{project_id}/changes").status_code in (404, 410)
    listed = client.get(f"/api/projects/{current_id}/changes")
    assert listed.status_code == 200, listed.text
    saved = next(row for row in listed.json()["records"] if row["recovery_id"] == receipt["recovery_id"])
    assert saved["project_id"] == current_id and saved["can_revert"] is True
    original = client.get(f"/api/projects/{current_id}/changes/{receipt['recovery_id']}/original")
    assert original.status_code == 200, original.text
    assert original.json() == {"text": "  original\r\n\r\n", "bom": True, "newline": "crlf"}
    undo_plan = prepare(client, current_id, receipt["recovery_id"], "revert")
    assert undo_plan.status_code == 200, undo_plan.text
    undone = commit(client, current_id, receipt["recovery_id"], undo_plan.json()["digest"], "revert")
    assert undone.status_code == 200 and undone.json()["state"] == "reverted", undone.text
    assert (folder / "README.md").read_bytes() == BEFORE


def test_revert_conflict_preserves_later_user_edit_and_original_remains_copyable(change_client):
    client, folder, project_id, _ = change_client
    _, _, receipt = applied(client, project_id)
    planned = prepare(client, project_id, receipt["recovery_id"], "revert")
    assert planned.status_code == 200, planned.text
    target = folder / "README.md"
    target.write_bytes(b"USER_EDITED_AFTER_APPLY\n")
    result = commit(client, project_id, receipt["recovery_id"], planned.json()["digest"], "revert")
    assert result.status_code == 200 and result.json()["state"] == "conflict", result.text
    assert result.json()["can_revert"] is False
    assert target.read_bytes() == b"USER_EDITED_AFTER_APPLY\n"
    listed = client.get(f"/api/projects/{project_id}/changes").json()["records"]
    master = next(row for row in listed if row["recovery_id"] == receipt["recovery_id"] and row["action"] == "apply")
    assert master["state"] == "applied" and master["can_revert"] is False
    original = client.get(f"/api/projects/{project_id}/changes/{receipt['recovery_id']}/original")
    assert original.status_code == 200 and original.json()["text"] == "  original\r\n\r\n"


def test_keep_ends_recovery_without_touching_current_user_bytes(change_client, monkeypatch):
    client, folder, project_id, _ = change_client
    _, _, receipt = applied(client, project_id)
    target = folder / "README.md"
    target.write_bytes(b"USER_WANTS_TO_KEEP_THIS\n")
    expected_identity = target.stat().st_ino
    monkeypatch.setattr(project_api.registry, "commit_file", lambda *args, **kwargs: pytest.fail("Keep wrote project"))
    planned = prepare(client, project_id, receipt["recovery_id"], "keep")
    assert planned.status_code == 200, planned.text
    result = commit(client, project_id, receipt["recovery_id"], planned.json()["digest"], "keep")
    assert result.status_code == 200 and result.json()["state"] == "kept", result.text
    assert result.json()["can_revert"] is False
    assert target.read_bytes() == b"USER_WANTS_TO_KEEP_THIS\n" and target.stat().st_ino == expected_identity
    repeated = commit(client, project_id, receipt["recovery_id"], planned.json()["digest"], "keep")
    assert repeated.status_code == 409


def test_other_physical_root_cannot_read_original_or_operation(change_client, tmp_path):
    client, _, project_id, _ = change_client
    _, _, receipt = applied(client, project_id)
    other = tmp_path / "different-physical-root"
    other.mkdir()
    opened = client.post("/api/projects/open", json={"path": str(other)}, headers={"X-Campus-Project-Grant": GRANT})
    assert opened.status_code == 200, opened.text
    other_id = opened.json()["project"]["id"]
    for suffix in (f"changes/{receipt['recovery_id']}/original", f"changes/operations/{receipt['operation_id']}"):
        result = client.get(f"/api/projects/{other_id}/{suffix}")
        assert result.status_code == 404
        assert "original" not in result.text and "replacement" not in result.text
    assert client.get(f"/api/projects/{other_id}/changes").json()["records"] == []


@pytest.mark.parametrize("body", [{"subject_id": "x", "action": "delete"},
                                    {"subject_id": "x", "action": "apply", "replacement_text": "INJECTION"}])
def test_change_requests_do_not_accept_paths_actions_or_free_replacement(change_client, body):
    client, folder, project_id, _ = change_client
    result = client.post(f"/api/projects/{project_id}/changes/prepare", json=body,
                         headers={"X-Campus-Project-Write": WRITE})
    assert result.status_code == 422
    assert (folder / "README.md").read_bytes() == BEFORE


def test_editing_availability_requires_private_write_secret(change_client, monkeypatch):
    client, _, _, _ = change_client
    assert client.get("/api/projects").json()["changes_available"] is True
    monkeypatch.delenv("CAMPUS_PROJECT_WRITE_TOKEN")
    assert client.get("/api/projects").json()["changes_available"] is False


def test_recovery_tracks_physical_root_after_directory_rename(change_client, tmp_path):
    client, folder, project_id, _ = change_client
    _, _, receipt = applied(client, project_id)
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    moved = tmp_path / "same-physical-root-different-name"
    folder.rename(moved)
    opened = client.post("/api/projects/open", json={"path": str(moved)}, headers={"X-Campus-Project-Grant": GRANT})
    assert opened.status_code == 200, opened.text
    current_id = opened.json()["project"]["id"]
    original = client.get(f"/api/projects/{current_id}/changes/{receipt['recovery_id']}/original")
    assert original.status_code == 200, original.text
    assert original.json()["text"] == "  original\r\n\r\n"
    listed = client.get(f"/api/projects/{current_id}/changes").json()["records"]
    assert any(row["recovery_id"] == receipt["recovery_id"] for row in listed)


def test_keep_releases_one_of_32_unresolved_recovery_slots(change_client, monkeypatch):
    client, folder, project_id, _ = change_client
    records = []
    for index in range(32):
        monkeypatch.setattr(project_api, "proposals", ProjectProposalStore())
        monkeypatch.setattr(model_client, "complete", lambda *args, value=index, **kwargs: {
            "content": json.dumps({"replacement_text": f"version-{value}\n", "summary": f"Change {value}"})})
        _, _, receipt = applied(client, project_id)
        records.append(receipt)
    assert (folder / "README.md").read_bytes() == b"\xef\xbb\xbfversion-31\n"
    monkeypatch.setattr(project_api, "proposals", ProjectProposalStore())
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": '{"replacement_text":"after-capacity-release\\n","summary":"New bounded change"}'})
    draft = proposal(client, project_id)
    planned = prepare(client, project_id, draft["id"])
    if planned.status_code == 200:
        denied = commit(client, project_id, draft["id"], planned.json()["digest"])
    else:
        denied = planned
    assert denied.status_code == 429, denied.text
    assert denied.headers.get("X-Project-Error") == "project_change_limit"
    assert (folder / "README.md").read_bytes() == b"\xef\xbb\xbfversion-31\n"
    keep_plan = prepare(client, project_id, records[0]["recovery_id"], "keep")
    assert keep_plan.status_code == 200, keep_plan.text
    kept = commit(client, project_id, records[0]["recovery_id"], keep_plan.json()["digest"], "keep")
    assert kept.status_code == 200 and kept.json()["state"] == "kept", kept.text
    retry_plan = prepare(client, project_id, draft["id"])
    assert retry_plan.status_code == 200, retry_plan.text
    accepted = commit(client, project_id, draft["id"], retry_plan.json()["digest"])
    assert accepted.status_code == 200 and accepted.json()["state"] == "applied", accepted.text
    assert (folder / "README.md").read_bytes() == b"\xef\xbb\xbfafter-capacity-release\n"


@pytest.mark.parametrize("publication,expected_state", [(False, "failed"), (True, "applied")], ids=["before-mutation", "after-publication"])
def test_interrupted_pending_operation_is_classified_on_restart_without_replaying_write(change_client, monkeypatch, publication, expected_state):
    client, folder, project_id, data_dir = change_client
    draft = proposal(client, project_id)
    plan = prepare(client, project_id, draft["id"])
    assert plan.status_code == 200, plan.text
    operation_id = str(uuid4())
    real_commit = project_api.registry.commit_file
    def interrupted(*args, **kwargs):
        if publication:
            result = real_commit(*args, **kwargs)
            assert result["state"] == "applied"
        raise SystemExit("synthetic process interruption")
    monkeypatch.setattr(project_api.registry, "commit_file", interrupted)
    with pytest.raises(SystemExit):
        project_api.changes.commit(project_api.registry, project_api.proposals, project_id,
                                   draft["id"], "apply", plan.json()["digest"], operation_id)
    monkeypatch.setattr(project_api, "changes", type(project_api.changes)(data_dir=data_dir))
    monkeypatch.setattr(project_api.registry, "commit_file", lambda *args, **kwargs: pytest.fail("Pending query replayed project write"))
    result = client.get(f"/api/projects/{project_id}/changes/operations/{operation_id}")
    assert result.status_code == 200 and result.json()["state"] == expected_state, result.text
    retried = commit(client, project_id, draft["id"], plan.json()["digest"], operation_id=operation_id)
    assert retried.status_code == 200 and retried.json()["state"] == expected_state, retried.text
    assert (folder / "README.md").read_bytes() == (AFTER if publication else BEFORE)
    original = client.get(f"/api/projects/{project_id}/changes/{result.json()['recovery_id']}/original")
    assert original.status_code == 200 and original.json()["text"] == "  original\r\n\r\n"


def test_gap_collision_has_durable_uncertain_receipt_without_overwriting_occupant(change_client, monkeypatch):
    from app import project_commit_windows as native
    client, folder, project_id, _ = change_client
    target = folder / "README.md"
    draft = proposal(client, project_id)
    plan = prepare(client, project_id, draft["id"])
    assert plan.status_code == 200, plan.text
    real_rename = native._rename
    def rename_then_occupy(handle, destination):
        result = real_rename(handle, destination)
        if destination.name.startswith(".campus-backup-"):
            target.write_bytes(b"USER_OCCUPIED_DURING_RENAME_GAP\n")
        return result
    monkeypatch.setattr(native, "_rename", rename_then_occupy)
    result = commit(client, project_id, draft["id"], plan.json()["digest"])
    assert result.status_code == 200 and result.json()["state"] == "uncertain", result.text
    assert result.json()["can_revert"] is False
    assert target.read_bytes() == b"USER_OCCUPIED_DURING_RENAME_GAP\n"
    original = client.get(f"/api/projects/{project_id}/changes/{result.json()['recovery_id']}/original")
    assert original.status_code == 200 and original.json()["text"] == "  original\r\n\r\n"
    assert any(item.name.startswith(".campus-backup-") and item.read_bytes() == BEFORE for item in folder.iterdir())


def test_locked_journal_refuses_commit_before_any_project_mutation(change_client):
    client, folder, project_id, data_dir = change_client
    draft = proposal(client, project_id)
    plan = prepare(client, project_id, draft["id"])
    assert plan.status_code == 200, plan.text
    listed = client.get(f"/api/projects/{project_id}/changes")
    assert listed.status_code == 200, listed.text
    journal = data_dir / "project-changes.sqlite3"
    with sqlite3.connect(journal) as held:
        held.execute("BEGIN EXCLUSIVE")
        try:
            result = commit(client, project_id, draft["id"], plan.json()["digest"])
        finally:
            held.rollback()
    assert result.status_code == 503, result.text
    assert result.headers.get("X-Project-Error") == "project_change_journal_unavailable"
    assert (folder / "README.md").read_bytes() == BEFORE
    assert sorted(item.name for item in folder.iterdir()) == ["README.md"]


def test_backup_cleanup_failure_remains_uncertain_and_blocks_new_actions(change_client, monkeypatch):
    from app import project_commit_windows as native
    client, folder, project_id, _ = change_client
    draft = proposal(client, project_id)
    plan = prepare(client, project_id, draft["id"])
    assert plan.status_code == 200, plan.text
    monkeypatch.setattr(native, "_delete", lambda *args: False)
    result = commit(client, project_id, draft["id"], plan.json()["digest"])
    assert result.status_code == 200 and result.json()["state"] == "uncertain", result.text
    receipt = result.json()
    assert receipt["can_revert"] is False
    assert (folder / "README.md").read_bytes() == AFTER
    assert any(path.name.startswith(".campus-backup-") and path.read_bytes() == BEFORE for path in folder.iterdir())
    queried = client.get(f"/api/projects/{project_id}/changes/operations/{receipt['operation_id']}")
    assert queried.status_code == 200 and queried.json()["state"] == "uncertain", queried.text
    assert queried.json()["can_revert"] is False
    listed = client.get(f"/api/projects/{project_id}/changes").json()["records"]
    assert next(row for row in listed if row["recovery_id"] == receipt["recovery_id"])["state"] == "uncertain"
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": '{"replacement_text":"next-proposal-after-orphan\\n","summary":"A new proposal"}'})
    next_draft = proposal(client, project_id)
    for action, subject in (("apply", next_draft["id"]), ("revert", receipt["recovery_id"]), ("keep", receipt["recovery_id"])):
        denied = prepare(client, project_id, subject, action)
        assert denied.status_code == 409, denied.text
        assert denied.headers.get("X-Project-Error") == "project_change_busy"
    original = client.get(f"/api/projects/{project_id}/changes/{receipt['recovery_id']}/original")
    assert original.status_code == 200 and original.json()["text"] == "  original\r\n\r\n"


def test_old_apply_plan_cannot_replay_after_resolved_original_is_evicted(change_client, monkeypatch):
    client, folder, project_id, data_dir = change_client
    first = None
    for index in range(33):
        monkeypatch.setattr(project_api, "proposals", ProjectProposalStore())
        monkeypatch.setattr(model_client, "complete", lambda *args, value=index, **kwargs: {
            "content": json.dumps({"replacement_text": f"resolved-version-{value}\n", "summary": f"Keep {value}"})})
        draft, plan, receipt = applied(client, project_id)
        if first is None:
            first = draft, plan, receipt
        keep_plan = prepare(client, project_id, receipt["recovery_id"], "keep")
        assert keep_plan.status_code == 200, keep_plan.text
        kept = commit(client, project_id, receipt["recovery_id"], keep_plan.json()["digest"], "keep")
        assert kept.status_code == 200 and kept.json()["state"] == "kept", kept.text
    first_draft, first_plan, first_receipt = first
    with sqlite3.connect(data_dir / "project-changes.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM recoveries WHERE id=?", (first_receipt["recovery_id"],)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM operations WHERE id=?", (first_receipt["operation_id"],)).fetchone()[0] == 1
    current = (folder / "README.md").read_bytes()
    calls = []
    def no_second_mutation(*args, **kwargs):
        calls.append(args)
        return {"state": "failed", "error_code": "project_change_failed"}
    monkeypatch.setattr(project_api.registry, "commit_file", no_second_mutation)
    replayed = commit(client, project_id, first_draft["id"], first_plan["digest"])
    assert replayed.status_code == 409, replayed.text
    assert replayed.headers.get("X-Project-Error") == "project_change_conflict"
    assert calls == []
    assert (folder / "README.md").read_bytes() == current


def test_corrupt_original_snapshot_is_safe_journal_error(change_client):
    client, folder, project_id, data_dir = change_client
    _, _, receipt = applied(client, project_id)
    with sqlite3.connect(data_dir / "project-changes.sqlite3") as db:
        db.execute("UPDATE recoveries SET original=? WHERE id=?", (b"CORRUPTED_PRIVATE_SNAPSHOT\xff", receipt["recovery_id"]))
    result = client.get(f"/api/projects/{project_id}/changes/{receipt['recovery_id']}/original")
    assert result.status_code == 503, result.text
    assert result.headers.get("X-Project-Error") == "project_change_journal_unavailable"
    assert "CORRUPTED_PRIVATE_SNAPSHOT" not in result.text and str(data_dir) not in result.text
    assert "  original" not in result.text and str(folder) not in result.text
    assert (folder / "README.md").read_bytes() == AFTER


def test_corrupt_valid_utf8_original_cannot_be_used_for_revert(change_client):
    client, folder, project_id, data_dir = change_client
    _, _, receipt = applied(client, project_id)
    with sqlite3.connect(data_dir / "project-changes.sqlite3") as db:
        db.execute("UPDATE recoveries SET original=? WHERE id=?", (b"CORRUPTED_BUT_VALID_UTF8\n", receipt["recovery_id"]))
    result = prepare(client, project_id, receipt["recovery_id"], "revert")
    assert result.status_code == 503, result.text
    assert result.headers.get("X-Project-Error") == "project_change_journal_unavailable"
    assert "CORRUPTED_BUT_VALID_UTF8" not in result.text
    assert (folder / "README.md").read_bytes() == AFTER


def test_pending_classification_rolls_back_both_rows_when_recovery_update_fails(change_client, monkeypatch):
    client, folder, project_id, data_dir = change_client
    draft = proposal(client, project_id)
    plan = prepare(client, project_id, draft["id"])
    assert plan.status_code == 200, plan.text
    operation_id = str(uuid4())
    def interrupted(*args, **kwargs):
        raise SystemExit("synthetic interruption before mutation")
    monkeypatch.setattr(project_api.registry, "commit_file", interrupted)
    with pytest.raises(SystemExit):
        project_api.changes.commit(project_api.registry, project_api.proposals, project_id,
                                   draft["id"], "apply", plan.json()["digest"], operation_id)
    journal = data_dir / "project-changes.sqlite3"
    with sqlite3.connect(journal) as db:
        assert db.execute("SELECT state FROM operations WHERE id=?", (operation_id,)).fetchone()[0] == "pending"
        db.execute("CREATE TRIGGER synthetic_recovery_update_failure BEFORE UPDATE OF state ON recoveries "
                   "BEGIN SELECT RAISE(FAIL, 'synthetic recovery update failure'); END")
    queried = client.get(f"/api/projects/{project_id}/changes/operations/{operation_id}")
    assert queried.status_code == 503, queried.text
    assert queried.headers.get("X-Project-Error") == "project_change_journal_unavailable"
    with sqlite3.connect(journal) as db:
        row = db.execute("SELECT state,data,recovery_id FROM operations WHERE id=?", (operation_id,)).fetchone()
        assert row[0] == "pending"
        assert json.loads(row[1])["state"] == "pending"
        assert db.execute("SELECT state FROM recoveries WHERE id=?", (row[2],)).fetchone()[0] == "pending"
    assert (folder / "README.md").read_bytes() == BEFORE


def test_prepare_rejects_same_bytes_replaced_with_new_identity_after_proposal_review(change_client, monkeypatch):
    client, folder, project_id, _ = change_client
    target = folder / "README.md"
    draft = proposal(client, project_id)
    before_identity = target.stat().st_ino
    real_get = project_api.proposals.get
    def get_then_replace(*args, **kwargs):
        reviewed = real_get(*args, **kwargs)
        replacement = folder / "synthetic-replacement.txt"
        replacement.write_bytes(BEFORE)
        replacement.replace(target)
        return reviewed
    monkeypatch.setattr(project_api.proposals, "get", get_then_replace)
    result = prepare(client, project_id, draft["id"])
    assert target.stat().st_ino != before_identity
    assert result.status_code == 409, result.text
    assert result.headers.get("X-Project-Error") == "project_change_conflict"
    assert target.read_bytes() == BEFORE


def test_interrupted_keep_rolls_back_without_hidden_pending_blocker(change_client, monkeypatch):
    client, folder, project_id, data_dir = change_client
    _, _, receipt = applied(client, project_id)
    planned = prepare(client, project_id, receipt["recovery_id"], "keep")
    assert planned.status_code == 200, planned.text
    operation_id = str(uuid4())
    real_finish = project_api.changes._finish
    def interrupted_keep(db, operation, *args, **kwargs):
        if operation["action"] == "keep":
            raise SystemExit("synthetic interruption before keep finish")
        return real_finish(db, operation, *args, **kwargs)
    monkeypatch.setattr(project_api.changes, "_finish", interrupted_keep)
    with pytest.raises(SystemExit):
        project_api.changes.commit(project_api.registry, project_api.proposals, project_id,
                                   receipt["recovery_id"], "keep", planned.json()["digest"], operation_id)
    monkeypatch.setattr(project_api, "changes", type(project_api.changes)(data_dir=data_dir))
    listed = client.get(f"/api/projects/{project_id}/changes")
    assert listed.status_code == 200, listed.text
    assert all(row["state"] != "pending" for row in listed.json()["records"])
    undo_plan = prepare(client, project_id, receipt["recovery_id"], "revert")
    assert undo_plan.status_code == 200, undo_plan.text
    with sqlite3.connect(data_dir / "project-changes.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM operations WHERE id=?", (operation_id,)).fetchone()[0] == 0
    assert (folder / "README.md").read_bytes() == AFTER


def test_successful_reconciliation_clears_previous_uncertain_error(change_client):
    client, folder, project_id, data_dir = change_client
    _, _, receipt = applied(client, project_id)
    with sqlite3.connect(data_dir / "project-changes.sqlite3") as db:
        raw = db.execute("SELECT data FROM operations WHERE id=?", (receipt["operation_id"],)).fetchone()[0]
        value = json.loads(raw)
        value.update(state="uncertain", error_code="project_change_failed")
        db.execute("UPDATE operations SET state='uncertain',data=? WHERE id=?", (json.dumps(value), receipt["operation_id"]))
        db.execute("UPDATE recoveries SET state='uncertain' WHERE id=?", (receipt["recovery_id"],))
    queried = client.get(f"/api/projects/{project_id}/changes/operations/{receipt['operation_id']}")
    assert queried.status_code == 200 and queried.json()["state"] == "applied", queried.text
    assert "error_code" not in queried.json()
    assert queried.json()["can_revert"] is True
    assert (folder / "README.md").read_bytes() == AFTER


@pytest.mark.parametrize("metadata", ["{}", "not valid JSON"], ids=["missing-fields", "invalid-json"])
def test_corrupt_operation_metadata_is_safe_journal_error(change_client, metadata):
    _, folder, project_id, data_dir = change_client
    client = change_client[0]
    _, _, receipt = applied(client, project_id)
    with sqlite3.connect(data_dir / "project-changes.sqlite3") as db:
        db.execute("UPDATE operations SET data=? WHERE id=?", (metadata, receipt["operation_id"]))
    with pytest.raises(ProjectFileError) as caught:
        project_api.changes.operations(project_api.registry, project_id, receipt["operation_id"])
    assert caught.value.error_code == "project_change_journal_unavailable"
    assert caught.value.status_code == 503
    assert metadata not in str(caught.value) and str(data_dir) not in str(caught.value)
    assert (folder / "README.md").read_bytes() == AFTER


def test_windows_case_alias_cannot_bypass_uncertain_path_block(change_client, monkeypatch):
    from app import project_commit_windows as native
    client, folder, project_id, _ = change_client
    draft = proposal(client, project_id)
    plan = prepare(client, project_id, draft["id"])
    real_delete = native._delete
    monkeypatch.setattr(native, "_delete", lambda *args: False)
    result = commit(client, project_id, draft["id"], plan.json()["digest"])
    assert result.status_code == 200 and result.json()["state"] == "uncertain", result.text
    monkeypatch.setattr(native, "_delete", real_delete)
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": '{"replacement_text":"alias-change\\n","summary":"Case alias"}'})
    alias = client.post(f"/api/projects/{project_id}/proposals", json={
        "path": "readme.MD", "instruction": "Change the same file.", "model": "auto"})
    assert alias.status_code == 200, alias.text
    denied = prepare(client, project_id, alias.json()["id"])
    assert denied.status_code == 409, denied.text
    assert denied.headers.get("X-Project-Error") == "project_change_busy"
    assert (folder / "README.md").read_bytes() == AFTER
