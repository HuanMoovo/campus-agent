"""Proposal snapshots and model boundaries use synthetic projects only."""
import hashlib
import json
import threading

import pytest

from app import agent, model_client, project_files
from app.project_files import ProjectFileError, ProjectRegistry


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "synthetic-proposal-project"
    directory.mkdir()
    registry = ProjectRegistry()
    project_id = registry.open(str(directory))["id"]
    yield registry, directory, project_id
    info = registry.status()
    if info:
        registry.close(info["id"])


@pytest.fixture
def model(monkeypatch):
    selected = ("openai_compatible", "synthetic-key", "https://invalid.example/v1", "synthetic-model")
    calls = []
    monkeypatch.setattr(agent, "choose_model", lambda *args: selected)
    monkeypatch.setattr(agent, "provider_settings", lambda *args: {
        "protocol": "responses", "request_options": {"reasoning_efforts": ["high"]}})
    def complete(chosen, messages, **kwargs):
        calls.append((chosen, messages, kwargs))
        return {"role": "assistant", "content": json.dumps({
            "replacement_text": "  after\r\n\r\n", "summary": "修改说明"}), "tool_calls": []}
    monkeypatch.setattr(model_client, "complete", complete)
    return calls


def create(store, project, **kwargs):
    registry, _, project_id = project
    return store.create(registry, project_id, "note.txt", "修改正文", **kwargs)


def test_snapshot_is_complete_raw_hashed_and_preserves_bom_whitespace(project):
    registry, directory, project_id = project
    raw = b"\xef\xbb\xbf  before\r\n\r\n"
    (directory / "note.txt").write_bytes(raw)
    snapshot = registry.snapshot_file(project_id, "note.txt")
    assert snapshot.text == "  before\r\n\r\n"
    assert snapshot.raw_bytes == raw
    assert snapshot.sha256 == hashlib.sha256(raw).hexdigest()
    assert snapshot.bom is True and snapshot.newline == "crlf"
    assert snapshot.identity and snapshot.path == "note.txt"


@pytest.mark.parametrize("raw", [b"a" * 12001, b"a" * 65537, b"\n" * 2001], ids=["char-limit", "byte-limit", "line-limit"])
def test_snapshot_rejects_oversize_instead_of_returning_excerpt(project, raw):
    registry, directory, project_id = project
    (directory / "note.txt").write_bytes(raw)
    with pytest.raises(ProjectFileError) as caught:
        registry.snapshot_file(project_id, "note.txt")
    assert caught.value.error_code == "project_proposal_too_large"


@pytest.mark.parametrize("raw", [b"", b"a\n", b"a\rb", b"a\r\nb\n"])
def test_snapshot_accepts_empty_and_all_existing_text_newline_conventions(project, raw):
    registry, directory, project_id = project
    (directory / "note.txt").write_bytes(raw)
    snapshot = registry.snapshot_file(project_id, "note.txt")
    assert snapshot.raw_bytes == raw and snapshot.text == raw.decode()


def test_proposal_is_immutable_read_only_and_uses_resolved_profile_once(project, model, monkeypatch):
    from app.project_proposals import ProjectProposalStore
    registry, directory, project_id = project
    raw = b"\xef\xbb\xbf  before\r\n\r\n"
    (directory / "note.txt").write_bytes(raw)
    chosen = []
    original = agent.choose_model
    monkeypatch.setattr(agent, "choose_model", lambda *args: chosen.append(args) or original(*args))
    monkeypatch.setattr(agent.services, "grades", lambda *args: pytest.fail("personal service called"))
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda *args: pytest.fail("MCP called"))
    store = ProjectProposalStore()
    result = create(store, project, requested="auto", reasoning="high")
    assert len(chosen) == 1
    assert result["state"] == "ready" and result["before_text"] == "  before\r\n\r\n"
    assert result["after_text"] == "  after\r\n\r\n" and result["bom"] is True
    assert result["base_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["proposed_sha256"] == hashlib.sha256(b"\xef\xbb\xbf  after\r\n\r\n").hexdigest()
    assert result["model"] == "openai_compatible" and result["model_name"] == "synthetic-model"
    assert result["added_lines"] == result["removed_lines"] == 1
    assert model[0][2] == {"reasoning": "high", "protocol": "responses", "request_options": {"reasoning_efforts": ["high"]}}
    assert str(directory) not in json.dumps(result, ensure_ascii=False)
    result["after_text"] = "caller mutation"
    result["diff_lines"].clear()
    reviewed = store.get(registry, project_id, result["id"])
    assert reviewed["after_text"] == "  after\r\n\r\n" and reviewed["diff_lines"]
    assert (directory / "note.txt").read_bytes() == raw
    assert sorted(p.name for p in directory.iterdir()) == ["note.txt"]


@pytest.mark.parametrize("content", [
    "not JSON", "```json\n{}\n```", "[]", '{"replacement_text":"x","summary":"s","path":"escape.txt"}',
    '{"replacement_text":1,"summary":"s"}', '{"replacement_text":"x","summary":1}',
    '{"replacement_text":"x","replacement_text":"y","summary":"s"}',
    '{"replacement_text":"\\ud800","summary":"s"}',
    '{"replacement_text":"\\ufeffafter","summary":"s"}',
])
def test_malformed_or_authority_claiming_model_output_is_safe_error(project, model, monkeypatch, content):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(b"before")
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {"content": content})
    with pytest.raises(ProjectFileError) as caught:
        create(ProjectProposalStore(), project)
    assert caught.value.status_code == 502
    assert content not in str(caught.value) and str(directory) not in str(caught.value)
    assert (directory / "note.txt").read_bytes() == b"before"


@pytest.mark.parametrize("replacement,code", [("before", "project_proposal_no_change"), ("x" * 12001, "project_proposal_too_large"), ("x\x00", "project_proposal_invalid_result"), ("\n" * 2001, "project_proposal_too_large")], ids=["nochange", "oversize", "binary", "line-limit"])
def test_model_replacement_nochange_oversize_and_binary_rejected(project, model, monkeypatch, replacement, code):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(b"before")
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {"content": json.dumps({"replacement_text": replacement, "summary": "s"})})
    with pytest.raises(ProjectFileError) as caught:
        create(ProjectProposalStore(), project)
    assert caught.value.error_code == code


def test_missing_configuration_never_generates_demo_proposal(project, model, monkeypatch):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(b"before")
    monkeypatch.setattr(agent, "choose_model", lambda *args: None)
    with pytest.raises(ProjectFileError) as caught:
        create(ProjectProposalStore(), project)
    assert caught.value.status_code == 503 and not model


def test_review_recomputes_full_raw_version_without_model_and_preserves_diff(project, model):
    from app.project_proposals import ProjectProposalStore
    registry, directory, project_id = project
    (directory / "note.txt").write_bytes(b"before")
    store = ProjectProposalStore()
    result = create(store, project)
    (directory / "note.txt").write_bytes(b"BEFORE")
    reviewed = store.get(registry, project_id, result["id"])
    assert reviewed["state"] == "conflict" and reviewed["diff"] == result["diff"]
    assert reviewed["before_text"] == "before" and len(model) == 1
    (directory / "note.txt").unlink()
    assert store.get(registry, project_id, result["id"])["state"] == "conflict"


@pytest.mark.parametrize("action", ["edit", "replace", "reselect"])
def test_generation_releases_root_lock_and_rejects_changed_snapshot(project, model, monkeypatch, tmp_path, action):
    from app.project_proposals import ProjectProposalStore
    registry, directory, project_id = project
    (directory / "note.txt").write_bytes(b"before")
    store = ProjectProposalStore()
    entered, release = threading.Event(), threading.Event()
    failures = []
    def complete(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"content": '{"replacement_text":"after","summary":"s"}'}
    monkeypatch.setattr(model_client, "complete", complete)
    def generate():
        try:
            create(store, project)
        except BaseException as error:
            failures.append(error)
    thread = threading.Thread(target=generate)
    thread.start()
    try:
        assert entered.wait(5)
        # If generation retained the registry lock, this status call deadlocks.
        assert registry.status()["id"] == project_id
        if action == "edit":
            (directory / "note.txt").write_bytes(b"BEFORE")
        elif action == "replace":
            replacement = directory / "replacement.txt"
            replacement.write_bytes(b"before")
            replacement.replace(directory / "note.txt")
        else:
            another = tmp_path / "another-project"
            another.mkdir()
            registry.open(str(another))
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and len(failures) == 1
    assert isinstance(failures[0], ProjectFileError)
    assert failures[0].status_code in (404, 409)


def test_capacity_and_expiry_release_memory_slots(project, model, monkeypatch):
    from app import project_proposals
    _, directory, project_id = project
    registry = project[0]
    (directory / "note.txt").write_bytes(b"before")
    now = [10.0]
    monkeypatch.setattr(project_proposals.time, "monotonic", lambda: now[0])
    store = project_proposals.ProjectProposalStore()
    results = [create(store, project) for _ in range(32)]
    with pytest.raises(ProjectFileError) as caught:
        create(store, project)
    assert caught.value.status_code == 429
    now[0] += 1801
    with pytest.raises(ProjectFileError) as expired:
        store.get(registry, project_id, results[0]["id"])
    assert expired.value.status_code in (404, 410)
    assert create(store, project)["state"] == "ready"


def test_generation_admission_is_bounded_and_failure_frees_slots(project, model, monkeypatch):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(b"before")
    store = ProjectProposalStore()
    entered = threading.Barrier(3)
    release = threading.Event()
    failures = []
    def complete(*args, **kwargs):
        entered.wait(timeout=5)
        assert release.wait(5)
        return None
    monkeypatch.setattr(model_client, "complete", complete)
    def generate():
        try:
            create(store, project)
        except ProjectFileError as exc:
            failures.append(exc.error_code)
    threads = [threading.Thread(target=generate) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        entered.wait(timeout=5)
        with pytest.raises(ProjectFileError) as caught:
            create(store, project)
        assert caught.value.status_code == 429
    finally:
        release.set()
        for thread in threads:
            thread.join(5)
    assert failures == ["project_proposal_invalid_result"] * 2
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {"content": '{"replacement_text":"after","summary":"s"}'})
    assert create(store, project)["state"] == "ready"


@pytest.mark.parametrize("content", [" " * (160 * 1024 + 1), '{"replacement_text":"after","summary":"' + "s" * 801 + '"}'], ids=["response-limit", "summary-limit"])
def test_model_response_and_summary_have_independent_limits(project, model, monkeypatch, content):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(b"before")
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {"content": content})
    with pytest.raises(ProjectFileError) as caught:
        create(ProjectProposalStore(), project)
    assert caught.value.error_code == "project_proposal_invalid_result"


def test_bom_source_rejects_model_supplied_second_bom(project, model, monkeypatch):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(b"\xef\xbb\xbfbefore")
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {"content": '{"replacement_text":"\\ufeffafter","summary":"s"}'})
    with pytest.raises(ProjectFileError) as caught:
        create(ProjectProposalStore(), project)
    assert caught.value.error_code == "project_proposal_invalid_result"


@pytest.mark.parametrize("before,after,counts,markers", [
    ("", "first", (1, 0), 1), ("last", "last\n", (1, 1), 1),
    ("old\r\n", "new\r\n", (1, 1), 0), ("a\rb\r", "a\rc\r", (1, 1), 0),
])
def test_diff_has_real_lines_and_explicit_missing_newline(project, model, monkeypatch, before, after, counts, markers):
    from app.project_proposals import ProjectProposalStore
    _, directory, _ = project
    (directory / "note.txt").write_bytes(before.encode())
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {"content": json.dumps({"replacement_text": after, "summary": "s"})})
    result = create(ProjectProposalStore(), project)
    assert (result["added_lines"], result["removed_lines"]) == counts
    assert sum(row["kind"] == "no_newline" for row in result["diff_lines"]) == markers
    assert all("\r" not in row["text"] and "\n" not in row["text"] for row in result["diff_lines"])
