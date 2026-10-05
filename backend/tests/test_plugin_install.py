"""GitHub custom plugin install, manifest fetching and egress policy."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main, plugins
from app.db import Base, get_db
from app.models import Plugin
from app.plugins import BAIKE_SEARCH_URL, LEGACY_BAIKE_API_URL


MANIFEST = {
    "name": "demo_search",
    "description": "演示插件：调用公开数据接口",
    "url": "https://api.example.com/search",
    "parameters": {"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["query"], "additionalProperties": False},
}

BAIKE_SCHEMA = {"type": "object", "properties": {"bk_key": {"type": "string", "minLength": 1, "maxLength": 200}}, "required": ["bk_key"], "additionalProperties": False}


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
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(admin_token="plugin-test"))
    monkeypatch.setattr(main, "desktop_enabled", lambda: False)
    monkeypatch.setattr(plugins, "get_settings", lambda: SimpleNamespace(allowed_plugin_hosts=set()))
    client = TestClient(main.app)
    try:
        yield client, {"X-Admin-Token": "plugin-test"}, sessions
    finally:
        client.close()
        if previous is None:
            main.app.dependency_overrides.pop(get_db, None)
        else:
            main.app.dependency_overrides[get_db] = previous
        engine.dispose()


@pytest.fixture
def public_dns(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(plugins.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize("source,expected", [
    ("https://github.com/HuanMoovo/mens-plugin-demo", ("HuanMoovo", "mens-plugin-demo", "HEAD")),
    ("https://www.github.com/owner/repo/", ("owner", "repo", "HEAD")),
    ("https://github.com/owner/repo.git", ("owner", "repo", "HEAD")),
    ("https://github.com/owner/repo?tab=readme-ov-file", ("owner", "repo", "HEAD")),
    ("https://github.com/owner/repo/tree/main", ("owner", "repo", "main")),
    ("https://github.com/owner/repo/tree/release/1.x", ("owner", "repo", "release/1.x")),
    ("https://github.com/owner/repo/blob/main/plugin.json", ("owner", "repo", "main")),
    ("https://github.com/owner/repo/raw/v1/plugin.json", ("owner", "repo", "v1")),
])
def test_github_source_parsing_accepts_repo_links(source, expected):
    assert plugins.parse_github_source(source) == expected


@pytest.mark.parametrize("source", [
    "http://github.com/owner/repo",
    "https://gitlab.com/owner/repo",
    "https://github.com/only-owner",
    "https://github.com/owner/repo/tree",
    "https://github.com/owner/repo/settings",
    "https://github.com/owner/repo/blob/main/readme.md",
    "https://github.com/ow ner/repo",
    "https://user:pass@github.com/owner/repo",
    "https://github.com/owner/repo:8080/x",
    "https://github.com/owner/repo/tree/..",
])
def test_github_source_parsing_rejects_invalid_links(source):
    with pytest.raises(HTTPException) as excinfo:
        plugins.parse_github_source(source)
    assert excinfo.value.status_code == 400


def test_github_manifest_candidates_prefer_jsdelivr_then_raw():
    assert plugins.github_manifest_urls("owner", "repo", "main") == [
        "https://cdn.jsdelivr.net/gh/owner/repo@main/plugin.json",
        "https://fastly.jsdelivr.net/gh/owner/repo@main/plugin.json",
        "https://raw.githubusercontent.com/owner/repo/main/plugin.json",
    ]


def test_github_manifest_falls_back_across_cdns(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        if "cdn.jsdelivr.net" in url:
            raise HTTPException(502, "插件请求失败或响应不是有效 JSON")
        return dict(MANIFEST)

    monkeypatch.setattr(plugins, "fetch_manifest_json", fake_fetch)
    assert plugins.fetch_github_manifest("https://github.com/owner/repo") == MANIFEST
    assert calls == [
        "https://cdn.jsdelivr.net/gh/owner/repo@HEAD/plugin.json",
        "https://fastly.jsdelivr.net/gh/owner/repo@HEAD/plugin.json",
    ]


def test_github_manifest_missing_returns_friendly_404(monkeypatch):
    def fake_fetch(url):
        raise HTTPException(404, "未找到插件清单")

    monkeypatch.setattr(plugins, "fetch_manifest_json", fake_fetch)
    with pytest.raises(HTTPException) as excinfo:
        plugins.fetch_github_manifest("https://github.com/owner/repo")
    assert excinfo.value.status_code == 404
    assert "plugin.json" in excinfo.value.detail


def test_github_manifest_unreachable_returns_502(monkeypatch):
    def fake_fetch(url):
        raise HTTPException(502, "插件请求失败或响应不是有效 JSON")

    monkeypatch.setattr(plugins, "fetch_manifest_json", fake_fetch)
    with pytest.raises(HTTPException) as excinfo:
        plugins.fetch_github_manifest("https://github.com/owner/repo")
    assert excinfo.value.status_code == 502


def test_github_manifest_must_be_json_object(monkeypatch):
    monkeypatch.setattr(plugins, "fetch_manifest_json", lambda url: ["not", "an", "object"])
    with pytest.raises(HTTPException) as excinfo:
        plugins.fetch_github_manifest("https://github.com/owner/repo")
    assert excinfo.value.status_code == 422


def test_install_endpoint_installs_from_github_manifest(plugin_client, public_dns, monkeypatch):
    client, headers, _ = plugin_client
    monkeypatch.setattr(main, "fetch_github_manifest", lambda source: dict(MANIFEST))
    response = client.post("/api/plugins/install", headers=headers, json={"source": "https://github.com/owner/repo"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "demo_search"
    assert body["enabled"] is True
    assert [row["name"] for row in client.get("/api/plugins").json()] == ["demo_search"]
    assert client.post("/api/plugins/install", headers=headers, json={"source": "https://github.com/owner/repo"}).status_code == 409


def test_install_endpoint_accepts_direct_manifest_url(plugin_client, public_dns, monkeypatch):
    client, headers, _ = plugin_client
    calls = {}

    def fake_fetch(url, *, use_url_whitelist=False):
        calls["url"] = url
        calls["use_url_whitelist"] = use_url_whitelist
        return dict(MANIFEST)

    monkeypatch.setattr(main, "fetch_manifest_json", fake_fetch)
    response = client.post("/api/plugins/install", headers=headers, json={"source": "https://plugins.example.edu/plugin.json"})
    assert response.status_code == 200
    assert calls == {"url": "https://plugins.example.edu/plugin.json", "use_url_whitelist": True}


def test_install_endpoint_requires_admin(plugin_client):
    client, _, _ = plugin_client
    payload = {"source": "https://github.com/owner/repo"}
    assert client.post("/api/plugins/install", json=payload).status_code == 401
    assert client.post("/api/plugins/install", headers={"X-Admin-Token": "wrong"}, json=payload).status_code == 401


def test_install_endpoint_rejects_invalid_source(plugin_client):
    client, headers, _ = plugin_client
    assert client.post("/api/plugins/install", headers=headers, json={}).status_code == 422
    assert client.post("/api/plugins/install", headers=headers, json={"source": 42}).status_code == 422
    assert client.post("/api/plugins/install", headers=headers, json={"source": "   "}).status_code == 422
    assert client.post("/api/plugins/install", headers=headers, json={"source": "http://github.com/owner/repo"}).status_code == 400


def test_install_endpoint_rejects_invalid_manifest(plugin_client, monkeypatch):
    client, headers, _ = plugin_client
    monkeypatch.setattr(main, "fetch_github_manifest", lambda source: {"name": "BAD NAME", "description": "x", "url": "https://a.example/x"})
    assert client.post("/api/plugins/install", headers=headers, json={"source": "https://github.com/owner/repo"}).status_code == 422


def test_install_endpoint_surfaces_manifest_errors(plugin_client, monkeypatch):
    client, headers, _ = plugin_client

    def fake(source):
        raise HTTPException(404, "仓库根目录未找到 plugin.json（请确认文件存在且仓库公开）")

    monkeypatch.setattr(main, "fetch_github_manifest", fake)
    response = client.post("/api/plugins/install", headers=headers, json={"source": "https://github.com/owner/repo"})
    assert response.status_code == 404
    assert "plugin.json" in response.json()["detail"]


def test_recommended_plugin_catalog_endpoints_are_removed(plugin_client):
    client, headers, _ = plugin_client
    # GET 路径仍命中 /api/plugins/{plugin_id} 的 PATCH/DELETE 模式 → 405；安装端点整体移除 → 404。
    assert client.get("/api/plugins/catalog").status_code == 405
    assert client.post("/api/plugins/catalog/install", headers=headers, json={"id": "baidu_baike"}).status_code == 404


def test_plugin_url_gate_blocks_private_hosts_and_applies_optional_whitelist(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        address = "127.0.0.1" if host == "localhost" else "93.184.216.34"
        return [(2, 1, 6, "", (address, port))]

    monkeypatch.setattr(plugins.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(plugins, "get_settings", lambda: SimpleNamespace(allowed_plugin_hosts=set()))
    assert plugins.validate_plugin_url("https://api.example.com/data") == ("api.example.com", ["93.184.216.34"])
    with pytest.raises(HTTPException) as excinfo:
        plugins.validate_plugin_url("https://localhost/data")
    assert excinfo.value.status_code == 400
    monkeypatch.setattr(plugins, "get_settings", lambda: SimpleNamespace(allowed_plugin_hosts={"other.example.com"}))
    with pytest.raises(HTTPException) as excinfo:
        plugins.validate_plugin_url("https://api.example.com/data")
    assert excinfo.value.status_code == 400
    assert "白名单" in excinfo.value.detail
    for bad in ("http://api.example.com/x", "https://api.example.com/x#frag", "https://user@api.example.com/x"):
        with pytest.raises(HTTPException) as excinfo:
            plugins.validate_plugin_url(bad)
        assert excinfo.value.status_code == 400


def _install_baike(sessions, url=BAIKE_SEARCH_URL):
    with sessions() as db:
        db.add(Plugin(id="baike-row", name="baidu_baike_search", description="百度百科词条查询", url=url, parameters=BAIKE_SCHEMA, enabled=True))
        db.commit()


@pytest.mark.parametrize("legacy", [False, True])
def test_baidu_url_has_fixed_origin_and_one_encoded_query(plugin_client, monkeypatch, legacy):
    client, headers, sessions = plugin_client
    _install_baike(sessions, LEGACY_BAIKE_API_URL if legacy else BAIKE_SEARCH_URL)
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
    client, headers, sessions = plugin_client
    _install_baike(sessions)
    fetch = Mock()
    monkeypatch.setattr(plugins, "fetch_plugin_json", fetch)
    response = client.post("/api/plugins/baidu_baike_search/invoke",
                           headers={**headers, "Content-Type": "application/json"}, content=json.dumps(parameters))
    assert response.status_code == 400
    fetch.assert_not_called()


def test_tampered_baike_manifest_is_not_treated_as_browser_command(plugin_client, monkeypatch):
    client, headers, sessions = plugin_client
    _install_baike(sessions, BAIKE_SEARCH_URL + "?redirect=https://evil.example")
    fetch = Mock(return_value={"ok": True})
    monkeypatch.setattr(plugins, "fetch_plugin_json", fetch)
    response = client.post("/api/plugins/baidu_baike_search/invoke", headers=headers, json={"bk_key": "大学"})
    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True}
    assert fetch.call_count == 1


def test_fetch_retries_second_address_when_first_is_reset(monkeypatch):
    monkeypatch.setattr(plugins, "_resolve_public_ips", lambda host: ["203.0.113.7", "93.184.216.34"])
    attempts = []

    def fake_stream(url, host, address, parameters, max_bytes):
        attempts.append(address)
        if address == "203.0.113.7":
            raise plugins._TransportFailure("connection reset")
        return 200, {"ok": True}

    monkeypatch.setattr(plugins, "_stream_from_address", fake_stream)
    assert plugins.fetch_manifest_json("https://api.example.com/plugin.json") == {"ok": True}
    assert attempts == ["203.0.113.7", "93.184.216.34"]


def test_fetch_reports_failure_when_every_address_is_reset(monkeypatch):
    monkeypatch.setattr(plugins, "_resolve_public_ips", lambda host: ["203.0.113.7", "203.0.113.8"])

    def fake_stream(url, host, address, parameters, max_bytes):
        raise plugins._TransportFailure("connection reset")

    monkeypatch.setattr(plugins, "_stream_from_address", fake_stream)
    with pytest.raises(HTTPException) as excinfo:
        plugins.fetch_manifest_json("https://api.example.com/plugin.json")
    assert excinfo.value.status_code == 502


def test_disabled_plugin_blocks_invoke_and_delete_removes_it(plugin_client, monkeypatch):
    client, headers, sessions = plugin_client
    with sessions() as db:
        db.add(Plugin(id="p1", name="demo_plugin", description="demo", url="https://api.example.com/x",
                      parameters={"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 100}}, "required": ["query"], "additionalProperties": False},
                      enabled=True))
        db.commit()
    fetch = Mock(return_value={"items": []})
    monkeypatch.setattr(plugins, "fetch_plugin_json", fetch)
    assert client.post("/api/plugins/demo_plugin/invoke", headers=headers, json={"query": "x"}).status_code == 200
    fetch.assert_called_once_with("https://api.example.com/x", {"query": "x"})
    assert client.patch("/api/plugins/p1", headers=headers, json={"enabled": False}).status_code == 200
    assert client.post("/api/plugins/demo_plugin/invoke", headers=headers, json={"query": "x"}).status_code == 404
    assert client.delete("/api/plugins/p1", headers=headers).status_code == 200
    assert client.post("/api/plugins/demo_plugin/invoke", headers=headers, json={"query": "x"}).status_code == 404
