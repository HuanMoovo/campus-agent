"""Optional bundled plugins and Baike browser hand-off contract."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main, plugins
from app.db import Base, get_db
from app.models import Plugin
from app.plugin_catalog import BAIKE_SEARCH_URL, LEGACY_BAIKE_API_URL


@pytest.fixture
def plugin_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)

    def isolated_db():
        with sessions() as db:
            yield db

    previous = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = isolated_db
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(admin_token="catalog-test"))
    monkeypatch.setattr(main, "desktop_enabled", lambda: False)
    client = TestClient(main.app)
    try:
        yield client, {"X-Admin-Token": "catalog-test"}, sessions
    finally:
        client.close()
        if previous is None:
            main.app.dependency_overrides.pop(get_db, None)
        else:
            main.app.dependency_overrides[get_db] = previous
        engine.dispose()


def test_catalog_is_optional_and_contains_baidu_instead_of_wikipedia(plugin_client):
    client, headers, _ = plugin_client
    rows = client.get("/api/plugins/catalog").json()
    assert [row["id"] for row in rows] == ["openalex", "crossref", "baidu_baike"]
    assert all(not row["installed"] and not row["enabled"] for row in rows)
    assert client.get("/api/plugins").json() == []
    assert client.post("/api/plugins/catalog/install", json={"id": "baidu_baike"}).status_code == 401
    assert client.post("/api/plugins/catalog/install", headers=headers, json={"id": "wikipedia"}).status_code == 404


@pytest.mark.parametrize("plugin_id,parameters", [
    ("openalex", {"search": "machine learning"}),
    ("crossref", {"query": "machine learning"}),
    ("baidu_baike", {"bk_key": "人工智能"}),
])
def test_catalog_install_invoke_disable_and_uninstall(plugin_client, monkeypatch, plugin_id, parameters):
    client, headers, _ = plugin_client
    fetch = Mock(return_value={"items": [{"title": "test"}]})
    monkeypatch.setattr(plugins, "fetch_plugin_json", fetch)
    response = client.post("/api/plugins/catalog/install", headers=headers, json={"id": plugin_id})
    assert response.status_code == 200
    installed = response.json()
    assert installed["enabled"] is True
    assert client.post("/api/plugins/catalog/install", headers=headers, json={"id": plugin_id}).status_code == 409
    catalog_row = next(row for row in client.get("/api/plugins/catalog").json() if row["id"] == plugin_id)
    assert catalog_row["installed"] and catalog_row["enabled"]
    invoke_url = f"/api/plugins/{installed['name']}/invoke"
    assert client.post(invoke_url, json=parameters).status_code == 401
    result = client.post(invoke_url, headers=headers, json=parameters)
    assert result.status_code == 200
    if plugin_id == "baidu_baike":
        fetch.assert_not_called()
        assert result.json()["result"]["external"] is True
    else:
        fetch.assert_called_once_with(installed["url"], parameters)
    plugin_url = f"/api/plugins/{installed['id']}"
    assert client.patch(plugin_url, headers=headers, json={"enabled": False}).status_code == 200
    assert client.post(invoke_url, headers=headers, json=parameters).status_code == 404
    assert client.patch(plugin_url, headers=headers, json={"enabled": True}).status_code == 200
    assert client.delete(plugin_url, headers=headers).status_code == 200
    assert client.post(invoke_url, headers=headers, json=parameters).status_code == 404
    assert all(not row["installed"] for row in client.get("/api/plugins/catalog").json())


@pytest.mark.parametrize("legacy", [False, True])
def test_baidu_url_has_fixed_origin_and_one_encoded_query(plugin_client, monkeypatch, legacy):
    client, headers, sessions = plugin_client
    installed = client.post("/api/plugins/catalog/install", headers=headers, json={"id": "baidu_baike"}).json()
    if legacy:
        with sessions() as db:
            db.get(Plugin, installed["id"]).url = LEGACY_BAIKE_API_URL
            db.commit()
    fetch = Mock(side_effect=AssertionError("Baidu must open in the user's browser"))
    monkeypatch.setattr(plugins, "fetch_plugin_json", fetch)
    query = "人工智能 & next=https://evil.example/#登录"
    response = client.post("/api/plugins/baidu_baike_search/invoke", headers=headers, json={"bk_key": f"  {query}  "})
    assert response.status_code == 200
    result = response.json()["result"]
    parts = urlsplit(result["url"])
    assert parts.scheme == "https"
    assert parts.netloc == "baike.baidu.com"
    assert parts.path == "/search/word"
    assert not parts.fragment
    assert parse_qs(parts.query) == {"word": [query]}
    assert result["external"] is True
    fetch.assert_not_called()


@pytest.mark.parametrize("parameters", [
    {}, {"bk_key": ""}, {"bk_key": "   "}, {"bk_key": 123},
    {"bk_key": "x" * 201}, {"bk_key": "词条\n跳转"}, {"bk_key": "\ud800"},
    {"bk_key": "词条", "url": "https://evil.example"},
])
def test_baidu_rejects_invalid_query_before_any_network_call(plugin_client, monkeypatch, parameters):
    client, headers, _ = plugin_client
    client.post("/api/plugins/catalog/install", headers=headers, json={"id": "baidu_baike"})
    fetch = Mock()
    monkeypatch.setattr(plugins, "fetch_plugin_json", fetch)
    response = client.post("/api/plugins/baidu_baike_search/invoke",
                           headers={**headers, "Content-Type": "application/json"}, content=json.dumps(parameters))
    assert response.status_code == 400
    fetch.assert_not_called()


def test_arbitrary_baike_manifest_is_not_treated_as_browser_command(plugin_client, monkeypatch):
    client, headers, sessions = plugin_client
    installed = client.post("/api/plugins/catalog/install", headers=headers, json={"id": "baidu_baike"}).json()
    with sessions() as db:
        db.get(Plugin, installed["id"]).url = BAIKE_SEARCH_URL + "?redirect=https://evil.example"
        db.commit()
    # This URL is not eligible for the special browser hand-off, and normal
    # public-data egress validation rejects Baike because it is not an API host.
    monkeypatch.setattr(plugins, "get_settings", lambda: SimpleNamespace(allowed_plugin_hosts=set()))
    response = client.post("/api/plugins/baidu_baike_search/invoke", headers=headers, json={"bk_key": "大学"})
    assert response.status_code == 400
