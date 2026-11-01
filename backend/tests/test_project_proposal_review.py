"""Independent review regressions use temporary files and mocked generation."""
import json
import threading

import pytest

from app import agent, model_client, project_api, project_proposals
from app.project_files import ProjectFileError, ProjectRegistry
from starlette.requests import Request


@pytest.fixture
def review_project(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-review-project"
    root.mkdir()
    registry = ProjectRegistry()
    project_id = registry.open(str(root))["id"]
    monkeypatch.setattr(agent, "choose_model", lambda *args: (
        "openai_compatible", "fixture-key", "https://fixture.invalid/v1", "fixture-model"))
    monkeypatch.setattr(agent, "provider_settings", lambda *args: {})
    yield registry, root, project_id
    active = registry.status()
    if active:
        registry.close(active["id"])


def test_diff_body_resembling_file_headers_still_counts_as_changed_lines(review_project, monkeypatch):
    registry, root, project_id = review_project
    (root / "note.txt").write_bytes(b"-- old heading\n")
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": json.dumps({"replacement_text": "++ new heading\n", "summary": "Update heading."})})
    proposal = project_proposals.ProjectProposalStore().create(
        registry, project_id, "note.txt", "Update the heading.")
    assert (proposal["added_lines"], proposal["removed_lines"]) == (1, 1)
    assert [(row["kind"], row["text"], row["old_line"], row["new_line"])
            for row in proposal["diff_lines"] if row["kind"] in ("add", "remove")] == [
        ("remove", "-- old heading", 1, None), ("add", "++ new heading", None, 1)]


@pytest.mark.parametrize("action", ["close", "reselect"])
def test_revocation_during_diff_construction_cannot_publish_old_grant_proposal(
        review_project, monkeypatch, tmp_path, action):
    registry, root, project_id = review_project
    (root / "note.txt").write_bytes(b"before\n")
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": '{"replacement_text":"after\\n","summary":"Update text."}'})
    store = project_proposals.ProjectProposalStore()
    entered, release = threading.Event(), threading.Event()
    real_diff = project_proposals._diff
    successes, failures = [], []

    def held_diff(*args):
        entered.set()
        assert release.wait(5)
        return real_diff(*args)

    monkeypatch.setattr(project_proposals, "_diff", held_diff)

    def generate():
        try:
            successes.append(store.create(registry, project_id, "note.txt", "Update text."))
        except ProjectFileError as exc:
            failures.append(exc)

    thread = threading.Thread(target=generate)
    thread.start()
    try:
        assert entered.wait(5)
        if action == "close":
            registry.close(project_id)
            store.retain_project(None)
        else:
            second = tmp_path / "second-synthetic-review-project"
            second.mkdir()
            new_id = registry.open(str(second))["id"]
            store.retain_project(new_id)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert not successes, "A revoked project must not publish a ready proposal."
    assert len(failures) == 1 and failures[0].error_code == "project_not_found"


def test_finishing_old_close_cannot_clear_new_project_proposals(review_project, monkeypatch, tmp_path):
    registry, _, project_id = review_project
    store = project_proposals.ProjectProposalStore()
    monkeypatch.setattr(project_api, "registry", registry)
    monkeypatch.setattr(project_api, "proposals", store)
    monkeypatch.setenv("CAMPUS_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAMPUS_DESKTOP_TOKEN", "a" * 64)
    monkeypatch.setenv("CAMPUS_PROJECT_GRANT_TOKEN", "b" * 64)
    monkeypatch.setenv("CAMPUS_DESKTOP_PORT", "8395")
    request = Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [
        (b"host", b"127.0.0.1:8395"), (b"x-campus-desktop-token", b"a" * 64)]})
    entered, release = threading.Event(), threading.Event()
    real_close = registry.close
    failures = []

    def held_close(*args):
        real_close(*args)
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(registry, "close", held_close)

    def close_api():
        try:
            project_api.close_project(project_id, request)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=close_api)
    new_project_ready = threading.Event()
    new_project_attempted = threading.Event()
    current = []

    def reopen_and_generate():
        try:
            second = tmp_path / "new-active-synthetic-project"
            second.mkdir()
            (second / "note.txt").write_bytes(b"new before\n")
            new_project_attempted.set()
            current_id = registry.open(str(second))["id"]
            store.retain_project(current_id)
            proposal = store.create(registry, current_id, "note.txt", "Update new file.")
            current.append((current_id, proposal["id"]))
            new_project_ready.set()
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": '{"replacement_text":"new after\\n","summary":"Update new text."}'})
    reopening = threading.Thread(target=reopen_and_generate)
    thread.start()
    try:
        assert entered.wait(5)
        reopening.start()
        assert new_project_attempted.wait(5)
        # With serialized lifecycle operations, reopening waits for close. The
        # former split operations finish here and their proposal is then erased.
        new_project_ready.wait(0.2)
    finally:
        release.set()
        thread.join(5)
        if reopening.ident is not None:
            reopening.join(5)
    assert not thread.is_alive() and not reopening.is_alive() and not failures
    assert len(current) == 1
    assert store.get(registry, current[0][0], current[0][1])["state"] == "ready"
