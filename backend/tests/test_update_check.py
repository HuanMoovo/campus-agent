"""Offline coverage for the optional update check (manifest fetch is mocked)."""
import atexit
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import httpx

_test_data = tempfile.TemporaryDirectory(prefix="campus-update-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from fastapi.testclient import TestClient

from app import main as main_module
from app.db import engine
from app.main import app, version_tuple


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)

HEADERS = {"X-Admin-Token": "test-admin-token"}
# Snapshot the real settings before any test patches app.main.get_settings, otherwise the
# helper would call the patched function and recurse into itself.
_BASE_SETTINGS = {**vars(main_module.get_settings())}


def configured_settings(manifest_url: str):
    return SimpleNamespace(**{**_BASE_SETTINGS, "update_manifest_url": manifest_url})


def test_version_tuple_parsing():
    assert version_tuple("1.1.0") == (1, 1, 0)
    assert version_tuple("v2.0") == (2, 0)
    assert version_tuple(" 1.10.3 ") == (1, 10, 3)
    for value in ("", "latest", "1.1.0-beta", "x.y", None):
        assert version_tuple(value) is None


def test_update_check_without_configuration_never_calls_the_network(monkeypatch):
    def unexpected_get(*args, **kwargs):
        raise AssertionError("unconfigured update check performed network work")

    monkeypatch.setattr(main_module, "get_settings", lambda: configured_settings(""))
    monkeypatch.setattr(main_module.httpx, "get", unexpected_get)
    with TestClient(app) as client:
        assert client.get("/api/update/check").status_code == 401
        result = client.get("/api/update/check", headers=HEADERS).json()
    assert result["configured"] is False
    assert result["update_available"] is False
    assert "不联网" in result["message"]


def test_update_check_reports_a_newer_manifest(monkeypatch):
    seen = []

    def fake_get(url, **kwargs):
        seen.append((url, kwargs))
        return httpx.Response(200, json={"version": "1.2.0", "url": "https://example.edu/mens-1.2.0.exe",
                                         "notes": "修复与改进"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(main_module, "get_settings", lambda: configured_settings("https://example.edu/mens.json"))
    monkeypatch.setattr(main_module.httpx, "get", fake_get)
    with TestClient(app) as client:
        result = client.get("/api/update/check", headers=HEADERS).json()
    assert result["update_available"] is True
    assert result["latest"] == "1.2.0"
    assert result["url"] == "https://example.edu/mens-1.2.0.exe"
    assert result["notes"] == "修复与改进"
    assert result["current"] == app.version
    assert seen and seen[0][1]["trust_env"] is False and seen[0][1]["follow_redirects"] is False


def test_update_check_rejects_non_https_or_broken_manifests(monkeypatch):
    def unexpected_get(*args, **kwargs):
        raise AssertionError("a non-HTTPS manifest URL must be rejected before any request")

    monkeypatch.setattr(main_module, "get_settings", lambda: configured_settings("http://example.edu/mens.json"))
    monkeypatch.setattr(main_module.httpx, "get", unexpected_get)
    with TestClient(app) as client:
        result = client.get("/api/update/check", headers=HEADERS).json()
    assert result["configured"] is True and result["update_available"] is False
    assert "无法读取更新清单" in result["error"]

    monkeypatch.setattr(main_module, "get_settings", lambda: configured_settings("https://example.edu/mens.json"))
    monkeypatch.setattr(main_module.httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"version": "not-a-version"}, request=httpx.Request("GET", url)))
    with TestClient(app) as client:
        result = client.get("/api/update/check", headers=HEADERS).json()
    assert result["update_available"] is False
    assert "版本号" in result["error"]

    def failing_get(url, **kwargs):
        raise httpx.ConnectTimeout("offline", request=httpx.Request("GET", url))

    monkeypatch.setattr(main_module.httpx, "get", failing_get)
    with TestClient(app) as client:
        result = client.get("/api/update/check", headers=HEADERS).json()
    assert result["update_available"] is False
    assert "无法读取更新清单" in result["error"]


def test_update_check_treats_equal_or_older_versions_as_current(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: configured_settings("https://example.edu/mens.json"))
    monkeypatch.setattr(main_module.httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"version": app.version, "url": "http://insecure.example/mens.exe"}, request=httpx.Request("GET", url)))
    with TestClient(app) as client:
        result = client.get("/api/update/check", headers=HEADERS).json()
    assert result["update_available"] is False
    assert result["message"] == "已是最新版本。"
    assert result["url"] == ""
