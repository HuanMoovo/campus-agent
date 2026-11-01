"""Proposal routes use synthetic projects and an isolated router, never real models."""
import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import agent, model_client, model_runtime, project_api
from app.project_files import ProjectRegistry


TOKEN = "a" * 64
GRANT = "b" * 64
BEFORE = b"\xef\xbb\xbf  original\r\n"
AFTER = "  replacement\r\n\r\n"


@pytest.fixture
def proposal_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMPUS_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAMPUS_DESKTOP_TOKEN", TOKEN)
    monkeypatch.setenv("CAMPUS_DESKTOP_PORT", "8395")
    monkeypatch.setenv("CAMPUS_PROJECT_GRANT_TOKEN", GRANT)
    registry = ProjectRegistry()
    monkeypatch.setattr(project_api, "registry", registry)
    if hasattr(project_api, "proposals"):
        monkeypatch.setattr(project_api, "proposals", type(project_api.proposals)())
    folder = tmp_path / "synthetic-proposal-project"
    folder.mkdir()
    (folder / "README.md").write_bytes(BEFORE)
    (folder / ".env").write_bytes(b"PRIVATE_PROPOSAL_SENTINEL")
    selected = ("openai_compatible", "fixture-key", "https://fixture.invalid/v1", "fixture-model")
    monkeypatch.setattr(agent, "choose_model", lambda *args: selected)
    profile = {"protocol": "responses", "request_options": {"supports_tools": False}}
    monkeypatch.setattr(agent, "provider_settings", lambda *args: profile)
    monkeypatch.setattr(model_runtime, "provider_settings", lambda *args: profile)
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: {
        "content": json.dumps({"replacement_text": AFTER, "summary": "Update the selected text."}),
        "tool_calls": [],
    })
    monkeypatch.setattr(agent.mcp_registry, "catalog", lambda *args: pytest.fail("Proposal enumerated MCP"))
    monkeypatch.setattr(agent.knowledge_index, "search", lambda *args: pytest.fail("Proposal searched knowledge"))
    monkeypatch.setattr(agent.services, "grades", lambda *args: pytest.fail("Proposal queried personal data"))
    app = FastAPI()
    app.include_router(project_api.router)
    with TestClient(app, base_url="http://127.0.0.1:8395", client=("127.0.0.1", 12345),
                    headers={"X-Campus-Desktop-Token": TOKEN}) as client:
        yield client, folder
    active = registry.status()
    if active:
        registry.close(active["id"])


def open_project(client, folder):
    result = client.post("/api/projects/open", json={"path": str(folder)},
                         headers={"X-Campus-Project-Grant": GRANT})
    assert result.status_code == 200, result.text
    return result.json()["project"]["id"]


def create(client, project_id, **changes):
    body = {"path": "README.md", "instruction": "Replace the text.", "model": "auto"}
    body.update(changes)
    return client.post(f"/api/projects/{project_id}/proposals", json=body)


def test_create_returns_reviewable_full_text_and_raw_hashes_without_writing(proposal_client):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    response = create(client, project_id)
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["project_id"] == project_id
    assert proposal["path"] == "README.md"
    assert proposal["state"] == "ready"
    assert proposal["before_text"] == "  original\r\n"
    assert proposal["after_text"] == AFTER
    assert proposal["base_sha256"] == hashlib.sha256(BEFORE).hexdigest()
    assert proposal["proposed_sha256"] == hashlib.sha256(b"\xef\xbb\xbf" + AFTER.encode()).hexdigest()
    assert proposal["bom"] is True and proposal["newline"] == "crlf"
    assert proposal["model"] == "openai_compatible" and proposal["model_name"] == "fixture-model"
    assert proposal["added_lines"] == 2 and proposal["removed_lines"] == 1
    assert proposal["diff"] and proposal["diff_lines"] and proposal["created_at"]
    assert str(folder) not in json.dumps(proposal)
    assert (folder / "README.md").read_bytes() == BEFORE
    assert sorted(item.name for item in folder.iterdir()) == [".env", "README.md"]


def test_get_reviews_saved_proposal_without_calling_model_and_reports_external_edit(proposal_client, monkeypatch):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    created = create(client, project_id)
    assert created.status_code == 200, created.text
    proposal = created.json()
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: pytest.fail("GET invoked model"))
    endpoint = f"/api/projects/{project_id}/proposals/{proposal['id']}"
    response = client.get(endpoint)
    assert response.status_code == 200 and response.json() == proposal
    (folder / "README.md").write_bytes(b"user changed the file\n")
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "conflict"
    assert response.json()["before_text"] == proposal["before_text"]
    assert response.json()["after_text"] == AFTER
    assert (folder / "README.md").read_bytes() == b"user changed the file\n"


@pytest.mark.parametrize("action", ["close", "reselect"])
def test_old_grant_cannot_retrieve_saved_proposal(proposal_client, tmp_path, action):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    created = create(client, project_id)
    assert created.status_code == 200, created.text
    proposal_id = created.json()["id"]
    if action == "close":
        assert client.delete(f"/api/projects/{project_id}").status_code == 200
    else:
        second = tmp_path / "another-synthetic-project"
        second.mkdir()
        open_project(client, second)
    response = client.get(f"/api/projects/{project_id}/proposals/{proposal_id}")
    assert response.status_code in (404, 410)
    assert "original" not in response.text and "replacement" not in response.text


def test_browser_mode_cannot_create_or_read_proposals(proposal_client, monkeypatch):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    monkeypatch.setenv("CAMPUS_DESKTOP_MODE", "0")
    assert create(client, project_id).status_code == 403
    assert client.get(f"/api/projects/{project_id}/proposals/opaque-proposal").status_code == 403


@pytest.mark.parametrize("headers", [{"X-Campus-Desktop-Token": ""}, {"Host": "foreign.example"}])
def test_proposals_reject_missing_or_foreign_desktop_identity(proposal_client, headers):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    body = {"path": "README.md", "instruction": "Replace text", "model": "auto"}
    assert client.post(f"/api/projects/{project_id}/proposals", json=body, headers=headers).status_code == 403
    assert client.get(f"/api/projects/{project_id}/proposals/opaque-proposal", headers=headers).status_code == 403


def test_renderer_cannot_grant_an_arbitrary_root_before_generating(proposal_client):
    client, folder = proposal_client
    denied = client.post("/api/projects/open", json={"path": str(folder)})
    assert denied.status_code == 403
    assert create(client, "forged-project-id").status_code in (404, 410)
    assert (folder / "README.md").read_bytes() == BEFORE


@pytest.mark.parametrize("changes", [{"model": "unknown-provider"}, {"reasoning": "ultra"},
                                      {"path": "README.md", "replacement_text": "CLIENT_INJECTION"},
                                      {"instruction": ""}])
def test_proposal_request_rejects_unregistered_options_and_client_replacement(proposal_client, changes):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    assert create(client, project_id, **changes).status_code == 422
    assert (folder / "README.md").read_bytes() == BEFORE


def test_no_configured_model_fails_explicitly_without_demo_proposal(proposal_client, monkeypatch):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    monkeypatch.setattr(agent, "choose_model", lambda *args: None)
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: pytest.fail("Called missing model"))
    result = create(client, project_id)
    assert result.status_code == 503, result.text
    assert result.headers.get("X-Project-Error") == "project_proposal_model_unavailable"
    assert "after_text" not in result.json()
    assert (folder / "README.md").read_bytes() == BEFORE


@pytest.mark.parametrize("output", [None, {"content": "UPSTREAM_PRIVATE_SENTINEL invalid json", "tool_calls": []},
                                   {"content": '{"replacement_text":"ok","summary":"ok","path":".env"}', "tool_calls": []},
                                   {"content": '{"replacement_text":42,"summary":"ok"}', "tool_calls": []}])
def test_invalid_model_output_is_safe_error_without_fabricated_proposal(proposal_client, monkeypatch, output):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: output)
    response = create(client, project_id)
    assert response.status_code == 502, response.text
    assert response.headers.get("X-Project-Error") == "project_proposal_invalid_result"
    assert "UPSTREAM_PRIVATE_SENTINEL" not in response.text
    assert "PRIVATE_PROPOSAL_SENTINEL" not in response.text and str(folder) not in response.text
    assert (folder / "README.md").read_bytes() == BEFORE


@pytest.mark.parametrize("path", ["../outside.md", ".env", "missing.md", "README.md:secret"])
def test_proposals_preserve_existing_path_allowlist_and_file_existence(proposal_client, path):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    response = create(client, project_id, path=path)
    assert response.status_code == 422, response.text
    assert "PRIVATE_PROPOSAL_SENTINEL" not in response.text and str(folder) not in response.text
    assert (folder / "README.md").read_bytes() == BEFORE


def test_unsupported_reasoning_is_rejected_before_model_call(proposal_client, monkeypatch):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    monkeypatch.setattr(model_client, "complete", lambda *args, **kwargs: pytest.fail("Called unsupported reasoning"))
    response = create(client, project_id, reasoning="high")
    assert response.status_code == 400, response.text
    assert response.headers.get("X-Project-Error") == "project_proposal_reasoning"
    assert (folder / "README.md").read_bytes() == BEFORE


def test_review_stage_exposes_no_apply_or_revert_routes(proposal_client):
    client, folder = proposal_client
    project_id = open_project(client, folder)
    response = create(client, project_id)
    assert response.status_code == 200, response.text
    proposal_id = response.json()["id"]
    for operation in ("apply", "revert"):
        result = client.post(f"/api/projects/{project_id}/proposals/{proposal_id}/{operation}", json={})
        assert result.status_code == 404
    assert (folder / "README.md").read_bytes() == BEFORE
