"""Offline coverage for optional web search: parsing, URL safety, config and chat wiring.

All outbound traffic is substituted; the only real code paths are parsing, validation
and the agent/API wiring.
"""
import atexit
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

# Match the sibling test modules: the settings cache is process-wide, so whichever
# module imports `app` first fixes the environment for the whole run.
_test_data = tempfile.TemporaryDirectory(prefix="campus-web-search-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_data.name) / "test.db").as_posix()
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["ENABLE_RAG"] = "false"
os.environ["QWEN_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

from app import web_search
from app.db import engine
from app.main import app, get_settings


def _cleanup_test_database():
    engine.dispose()
    _test_data.cleanup()


atexit.register(_cleanup_test_database)

# Snapshot the real settings once so per-test patches never recurse through get_settings.
BASE = {**vars(web_search.get_settings())}

BING_FIXTURE = """
<ol id="b_results">
<li class="b_algo" data-id iid=SERP.1><h2><a href="https://www.example.edu.cn/notice/1">关于2026年秋季学期<strong>选课</strong>的通知</a></h2>
<div class="b_caption"><p class="b_lineclamp2">教务处将于9月1日开放选课系统，请同学们按时完成选课，逾期不予补选。</p></div></li>
<li class="b_algo"><h2><a href="https://news.example.com/a?b=1&amp;c=2">校园新闻：选课指南</a></h2><p>新生选课指南与常见问题解答。</p></li>
<li class="b_algo"><h2><a href="http://insecure.example.com/x">明文站点结果</a></h2><p>该结果不是 HTTPS，应被忽略。</p></li>
</ol>
"""

PAGE_FIXTURE = """<!doctype html><html><head><title>选课通知 - 教务处</title>
<script>console.log('ignore me')</script><style>.a{color:red}</style></head>
<body><h1>选课通知</h1><p>第一段内容。</p><div>第二段内容。<span>第三段</span></div>
<script>alert(1)</script></body></html>"""


class _FakeStream:
    def __init__(self, status_code, headers, chunks):
        self.status_code = status_code
        self.headers = headers
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("GET", "https://example.com"), response=None)

    def iter_bytes(self, chunk_size=16_384):
        yield from self._chunks


def fake_client(status_code=200, headers=None, chunks=(b"<html></html>",)):
    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            return _FakeStream(status_code, headers or {"content-type": "text/html; charset=utf-8"}, list(chunks))
    return lambda **kwargs: _Client()


def public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


class WebSearchTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="campus-web-test-")
        self.addCleanup(self.temp.cleanup)
        settings = SimpleNamespace(**{**BASE, "data_dir": Path(self.temp.name),
                                      "web_search_enabled": False, "web_search_provider": "auto",
                                      "web_search_api_key": "", "web_search_max_results": 5,
                                      "web_search_fetch_pages": 0})
        patcher = patch.object(web_search, "get_settings", lambda: settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = settings

    def enable(self, **changes):
        return web_search.update_config({"enabled": True, **changes})


class ParsingTests(WebSearchTestCase):
    def test_bing_results_are_parsed_and_plain_https_only(self):
        results = web_search.parse_bing_results(BING_FIXTURE, 5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["url"], "https://www.example.edu.cn/notice/1")
        self.assertEqual(results[0]["title"], "关于2026年秋季学期 选课 的通知")
        self.assertIn("选课系统", results[0]["snippet"])
        self.assertEqual(results[1]["url"], "https://news.example.com/a?b=1&c=2")
        self.assertEqual(web_search.parse_bing_results(BING_FIXTURE, 1), results[:1])

    def test_page_text_extraction_skips_scripts_and_keeps_structure(self):
        title, text = web_search.html_to_text(PAGE_FIXTURE)
        self.assertEqual(title, "选课通知 - 教务处")
        self.assertIn("第一段内容", text)
        self.assertIn("第三段", text)
        self.assertNotIn("console.log", text)
        self.assertNotIn("color:red", text)

    def test_text_extraction_respects_the_character_limit(self):
        _, text = web_search.html_to_text("<p>" + "字" * 5000 + "</p>", limit=120)
        self.assertLessEqual(len(text), 120)


class UrlSafetyTests(WebSearchTestCase):
    def test_only_plain_public_https_urls_pass(self):
        with patch("socket.getaddrinfo", public_dns):
            self.assertEqual(web_search.validate_external_url("https://example.com/a")[0], "example.com")
        for url in ("http://example.com/", "https://example.com:8443/", "https://user:pw@example.com/",
                    "file:///C:/Windows/System32/cmd.exe", "https://" + "a" * 2200, "", None, 42):
            with self.subTest(url=url), self.assertRaises(web_search.WebSearchError):
                web_search.validate_external_url(url)

    def test_private_or_loopback_hosts_are_rejected(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "::1"):
            with self.subTest(address=address), patch("socket.getaddrinfo",
                                                      lambda *a, _ip=address, **k: [(2, 1, 6, "", (_ip, 443))]), \
                    self.assertRaises(web_search.WebSearchError):
                web_search.validate_external_url("https://internal.example/")
        with patch("socket.getaddrinfo", side_effect=__import__("socket").gaierror("nope")), \
                self.assertRaises(web_search.WebSearchError):
            web_search.validate_external_url("https://missing.example/")

    def test_redirects_and_oversized_pages_are_refused(self):
        with patch("socket.getaddrinfo", public_dns), patch.object(httpx, "Client", fake_client(302)):
            with self.assertRaises(web_search.WebSearchError) as redirect:
                web_search.fetch_bytes("https://example.com/")
        self.assertIn("跳转", str(redirect.exception))
        with patch("socket.getaddrinfo", public_dns), \
                patch.object(httpx, "Client", fake_client(200, chunks=(b"x" * 4096, b"y" * 4096))):
            with self.assertRaises(web_search.WebSearchError) as large:
                web_search.fetch_bytes("https://example.com/", max_bytes=4096)
        self.assertEqual(large.exception.status_code, 413)

    def test_read_page_requires_html(self):
        with patch("socket.getaddrinfo", public_dns), \
                patch.object(httpx, "Client", fake_client(200, headers={"content-type": "image/png"})):
            with self.assertRaises(web_search.WebSearchError) as invalid:
                web_search.read_page("https://example.com/photo")
        self.assertEqual(invalid.exception.status_code, 415)


class ConfigurationTests(WebSearchTestCase):
    def test_configuration_defaults_to_disabled_bing(self):
        status = web_search.status()
        self.assertFalse(status["enabled"])
        self.assertEqual(status["provider"], "auto")
        self.assertEqual(status["resolved_provider"], "bing")
        self.assertTrue(status["available"])
        self.assertFalse(status["api_key_set"])

    def test_api_keys_are_encrypted_on_disk_and_never_returned(self):
        self.enable(provider="tavily", api_key="tvly-secret-value")
        raw = json.loads((Path(self.temp.name) / web_search.CONFIG_FILE).read_text(encoding="utf-8"))
        self.assertNotIn("tvly-secret-value", json.dumps(raw))
        self.assertTrue(raw["api_key"].startswith("dpapi:") or raw["api_key"].startswith("plain:"))
        status = web_search.status()
        self.assertTrue(status["api_key_set"])
        self.assertEqual(status["resolved_provider"], "tavily")
        self.assertNotIn("api_key", status)
        self.assertEqual(web_search.configuration()["api_key"], "tvly-secret-value")

    def test_invalid_updates_are_rejected(self):
        for changes in ({"provider": "google"}, {"enabled": "yes"}, {"max_results": 0}, {"max_results": 9},
                        {"fetch_pages": -1}, {"fetch_pages": 4}, {"api_key": "x" * 201}, {"api_key": "bad\nkey"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                web_search.update_config(changes)

    def test_keyed_provider_without_key_is_unavailable(self):
        self.enable(provider="bocha")
        status = web_search.status()
        self.assertFalse(status["available"])
        with self.assertRaises(web_search.WebSearchError) as missing:
            web_search.search("选课")
        self.assertIn("API Key", str(missing.exception))


class SearchDispatchTests(WebSearchTestCase):
    def test_disabled_search_does_not_touch_the_network(self):
        def fail(*args, **kwargs):
            raise AssertionError("disabled search performed network work")

        with patch.object(web_search, "fetch_bytes", fail):
            with self.assertRaises(web_search.WebSearchError) as disabled:
                web_search.search("选课")
        self.assertEqual(disabled.exception.status_code, 403)

    def test_bing_search_returns_parsed_results_and_enforces_limits(self):
        self.enable(max_results=2)
        seen = {}

        def fake_fetch(url, **kwargs):
            seen["url"] = url
            return "text/html; charset=utf-8", BING_FIXTURE.encode("utf-8")

        with patch.object(web_search, "fetch_bytes", fake_fetch):
            payload = web_search.search("选课 通知")
        self.assertEqual(payload["provider"], "bing")
        self.assertEqual(len(payload["results"]), 2)
        self.assertIn("q=%E9%80%89%E8%AF%BE", seen["url"])
        with patch.object(web_search, "fetch_bytes", fake_fetch):
            self.assertEqual(len(web_search.search("选课", limit=1)["results"]), 1)
            with self.assertRaises(web_search.WebSearchError):
                web_search.search("x" * 201)

    def test_tavily_results_are_normalized(self):
        self.enable(provider="tavily", api_key="tvly-key")
        captured = {}

        def fake_post(url, payload, api_key, timeout=12):
            captured.update(url=url, payload=payload, key=api_key)
            return {"results": [{"title": "T", "url": "https://a.example/1", "content": "内容 A"},
                                {"title": "bad", "url": "http://insecure.example/"}]}

        with patch.object(web_search, "_post_json", fake_post):
            payload = web_search.search("测试")
        self.assertEqual(captured["url"], web_search.TAVILY_SEARCH_URL)
        self.assertEqual(captured["key"], "tvly-key")
        self.assertEqual(payload["results"], [{"title": "T", "url": "https://a.example/1", "snippet": "内容 A"}])

    def test_live_context_reads_top_pages_and_never_raises(self):
        self.enable(fetch_pages=1)

        def fake_fetch(url, **kwargs):
            return "text/html; charset=utf-8", BING_FIXTURE.encode("utf-8")

        with patch.object(web_search, "fetch_bytes", fake_fetch):
            context = web_search.live_context("选课")
        self.assertEqual(context["provider"], "bing")
        self.assertEqual(context["error"], "")
        self.assertTrue(context["results"][0]["text"])
        self.assertIn("选课系统", context["results"][0]["text"])
        self.assertNotIn("text", context["results"][1])

        with patch.object(web_search, "fetch_bytes", side_effect=web_search.WebSearchError("搜索服务不可用")):
            failed = web_search.live_context("选课")
        self.assertEqual(failed["results"], [])
        self.assertEqual(failed["error"], "搜索服务不可用")


class ChatWiringTests(WebSearchTestCase):
    def test_status_endpoint_reports_the_configuration(self):
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            body = client.get("/api/web/status").json()
        self.assertIn("providers", body)
        self.assertIn("resolved_provider", body)

    def test_config_endpoint_requires_admin_and_persists(self):
        from fastapi.testclient import TestClient

        token = get_settings().admin_token
        self.assertTrue(token, "the test environment must configure ADMIN_TOKEN")
        with TestClient(app) as client:
            self.assertEqual(client.put("/api/web/config", json={"enabled": True}).status_code, 401)
            self.assertEqual(client.put("/api/web/config", json={"enabled": True},
                                        headers={"X-Admin-Token": "wrong-token"}).status_code, 401)
            response = client.put("/api/web/config", json={"enabled": True, "provider": "bing", "max_results": 3},
                                  headers={"X-Admin-Token": token})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["enabled"])
            self.assertEqual(response.json()["max_results"], 3)
            self.assertEqual(client.put("/api/web/config", json={"max_results": 99},
                                        headers={"X-Admin-Token": token}).status_code, 422)

    def test_chat_request_can_attach_live_web_sources(self):
        from fastapi.testclient import TestClient

        context = {"provider": "bing", "fetched_at": "2026-10-01 20:00", "error": "",
                   "results": [{"title": "选课通知", "url": "https://www.example.edu.cn/notice/1",
                                "snippet": "9月1日开放选课", "text": "教务处将于9月1日开放选课系统。"}]}
        with patch("app.agent.web_search.live_context", return_value=context):
            with TestClient(app) as client:
                response = client.post("/api/chat", json={"message": "选课什么时候开放？", "web": True})
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                history = client.get(f"/api/conversations/{data['conversation_id']}").json()
        web_sources = [row for row in data["sources"] if row["kind"] == "web"]
        self.assertEqual(len(web_sources), 1)
        self.assertEqual(web_sources[0]["url"], "https://www.example.edu.cn/notice/1")
        self.assertEqual(data["web"]["provider"], "bing")
        self.assertNotIn("text", web_sources[0])
        self.assertIn("https://www.example.edu.cn/notice/1", data["answer"])
        self.assertEqual(history["messages"][-1]["sources"], data["sources"])

    def test_chat_without_the_flag_stays_offline(self):
        from fastapi.testclient import TestClient

        def fail(*args, **kwargs):
            raise AssertionError("chat without the web flag performed a search")

        with patch("app.agent.web_search.live_context", fail):
            with TestClient(app) as client:
                response = client.post("/api/chat", json={"message": "你好"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row for row in response.json()["sources"] if row["kind"] == "web"], [])


if __name__ == "__main__":
    unittest.main()
