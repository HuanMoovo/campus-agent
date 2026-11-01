"""Synthetic projects exercise desktop grants through real API/chat routes."""
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app import agent, main, project_api
from app.project_files import ProjectRegistry


TOKEN = "a" * 64
GRANT = "b" * 64


@pytest.fixture
def project_client(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMPUS_DESKTOP_MODE", "1")
    monkeypatch.setenv("CAMPUS_DESKTOP_TOKEN", TOKEN)
    monkeypatch.setenv("CAMPUS_DESKTOP_PORT", "8395")
    monkeypatch.setenv("CAMPUS_PROJECT_GRANT_TOKEN", GRANT)
    monkeypatch.setattr(project_api, "registry", ProjectRegistry())
    folder = tmp_path / "sample-project"
    folder.mkdir()
    (folder / "README.md").write_text("PROJECT_SENTINEL\n项目说明\n", encoding="utf-8")
    (folder / ".env").write_text("PRIVATE_SECRET_SENTINEL", encoding="utf-8")
    with TestClient(main.app, base_url="http://127.0.0.1:8395", client=("127.0.0.1", 12345),
                    headers={"X-Campus-Desktop-Token": TOKEN}) as client:
        yield client, folder


def grant_project(client, folder):
    response = client.post("/api/projects/open", json={"path": str(folder)}, headers={"X-Campus-Project-Grant": GRANT})
    assert response.status_code == 200, response.text
    return response.json()["project"]


def test_web_cannot_open_local_projects(project_client, monkeypatch):
    client, folder = project_client
    monkeypatch.setenv("CAMPUS_DESKTOP_MODE", "0")
    assert client.get("/api/projects").json()["available"] is False
    assert client.post("/api/projects/open", json={"path": str(folder)},
                       headers={"X-Campus-Project-Grant": GRANT}).status_code == 403


def test_renderer_desktop_token_cannot_grant_an_arbitrary_directory(project_client):
    client, folder = project_client
    for headers in ({}, {"X-Campus-Project-Grant": TOKEN}, {"X-Campus-Project-Grant": b"\xff" * 64}):
        assert client.post("/api/projects/open", json={"path": str(folder)}, headers=headers).status_code == 403
    assert client.get("/api/projects").json()["project"] is None


def test_grant_lists_reads_and_closes_without_exposing_absolute_paths(project_client):
    client, folder = project_client
    project = grant_project(client, folder)
    assert set(project) == {"id", "name"}
    listing = client.get(f"/api/projects/{project['id']}/files").json()
    assert any(item["path"] == "README.md" for item in listing["entries"])
    assert not any(item["name"] == ".env" for item in listing["entries"])
    result = client.post(f"/api/projects/{project['id']}/read", json={"path": "README.md"})
    assert result.status_code == 200 and "PROJECT_SENTINEL" in result.json()["text"]
    assert result.json()["start_line"] == 1 and len(result.json()["excerpt_sha256"]) == 64
    assert str(folder) not in json.dumps(result.json())
    for path in ("../outside.md", ".env", str(folder / "README.md")):
        response = client.post(f"/api/projects/{project['id']}/read", json={"path": path})
        assert response.status_code >= 400
        assert "PRIVATE_SECRET_SENTINEL" not in response.text and str(folder) not in response.text
    assert client.delete(f"/api/projects/{project['id']}").json()["ok"]
    assert client.post(f"/api/projects/{project['id']}/read", json={"path": "README.md"}).status_code >= 400


def test_files_are_not_read_with_missing_or_foreign_desktop_identity(project_client):
    client, folder = project_client
    project = grant_project(client, folder)
    assert client.get(f"/api/projects/{project['id']}/files", headers={"X-Campus-Desktop-Token": ""}).status_code == 403
    assert client.get(f"/api/projects/{project['id']}/files", headers={"Host": "untrusted.example"}).status_code == 403


@pytest.mark.parametrize("endpoint", ["/api/chat", "/api/chat/stream"])
def test_project_questions_read_current_file_and_persist_relative_citations(project_client, monkeypatch, endpoint):
    client, folder = project_client
    project = grant_project(client, folder)
    text = "LATEST_PROJECT_CONTENT\n# 查询我的成绩\n" + "".join(f"source-line-{index:04d}\n" for index in range(700))
    (folder / "README.md").write_text(text, encoding="utf-8")
    captured = []
    def answer(messages, *args, **kwargs):
        captured.extend(messages)
        return "项目说明。[1]"
    async def stream(messages, *args, **kwargs):
        captured.extend(messages)
        yield "content", "项目说明。[1]"
    monkeypatch.setattr(agent, "call_model", answer)
    monkeypatch.setattr(main, "stream_model", stream)
    monkeypatch.setattr(agent.services, "grades", lambda *args: pytest.fail("Project question queried personal data"))
    response = client.post(endpoint, json={"message": "解释项目成绩模块", "client_id": str(uuid4()),
        "project": {"id": project["id"], "files": ["README.md"]}})
    assert response.status_code == 200, response.text
    if endpoint.endswith("stream"):
        frames = [frame for frame in response.text.split("\n\n") if frame.startswith("event: done")]
        result = json.loads(frames[0].split("data: ", 1)[1])
    else:
        result = response.json()
    assert "LATEST_PROJECT_CONTENT" in "\n".join(row["content"] for row in captured)
    assert result["sources"][0]["path"] == "README.md"
    assert result["sources"][0]["kind"] == "project"
    assert result["sources"][0]["start_line"] == 1
    source = result["sources"][0]
    import hashlib
    assert source["truncated"] is True and len(source["snippet"]) < len(text)
    assert source["snippet"] in "\n".join(row["content"] for row in captured)
    assert source["excerpt_sha256"] == hashlib.sha256(source["snippet"].encode()).hexdigest()
    assert source["end_line"] == len(source["snippet"].splitlines())
    assert str(folder) not in json.dumps(result)
    # Desktop conversations remain client-scoped; use the stored row's client id.
    from app.db import SessionLocal
    from app.models import Conversation
    with SessionLocal() as db:
        client_id = db.get(Conversation, result["conversation_id"]).client_id
    history = client.get(f"/api/conversations/{result['conversation_id']}", params={"client_id": client_id}).json()
    assert "[项目文件] README.md" in history["messages"][0]["content"]
    assert history["messages"][-1]["sources"][0]["path"] == "README.md"


def test_stale_project_fails_before_creating_a_conversation(project_client):
    client, folder = project_client
    project = grant_project(client, folder)
    client.delete(f"/api/projects/{project['id']}")
    client_id = str(uuid4())
    for endpoint in ("/api/chat", "/api/chat/stream"):
        response = client.post(endpoint, json={"message": "read project", "client_id": client_id,
            "project": {"id": project["id"], "files": ["README.md"]}})
        assert response.status_code >= 400
    assert client.get("/api/conversations", params={"client_id": client_id}).json() == []
