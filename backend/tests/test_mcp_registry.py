"""MCP 注册表与接口测试：CRUD、掩码、工具编目、真实调用与鉴权。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_TEST_DIR = tempfile.mkdtemp(prefix="mens-mcp-")
os.environ["CAMPUS_DATA_DIR"] = _TEST_DIR
os.environ["ADMIN_TOKEN"] = "test-admin-token"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import mcp_registry, main  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py")
ALIAS = str(Path(__file__).resolve().parent / "fixtures" / "fake_mcp_alias.py")
ADMIN = {"X-Admin-Token": "test-admin-token"}


def fake_args() -> list[str]:
    return ["-u", FIXTURE]


class McpRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        with SessionLocal() as db:
            for row in mcp_registry.list_servers(db):
                mcp_registry.delete_server(db, row["id"])

    def test_function_name_is_sanitized_and_bounded(self):
        name = mcp_registry.function_name("my server", "资料.读取")
        self.assertTrue(name.startswith("mcp__"))
        self.assertRegex(name, r"^[A-Za-z0-9_-]{1,64}$")
        long_name = mcp_registry.function_name("s" * 40, "t" * 60)
        self.assertLessEqual(len(long_name), 64)
        self.assertNotEqual(long_name, mcp_registry.function_name("s" * 40, "t" * 59))

    def test_create_list_and_mask_env(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args(),
                                             {"API_KEY": "secret-value"}, True)
            listed = mcp_registry.list_servers(db)
        self.assertEqual(len(listed), 1)
        public = listed[0]
        self.assertEqual(public["name"], "campus")
        self.assertEqual(public["env_keys"], ["API_KEY"])
        self.assertEqual(public["env_masked"]["API_KEY"], mcp_registry.MASK)
        self.assertNotIn("secret-value", str(public))
        self.assertEqual(row.id, public["id"])

    def test_duplicate_name_and_validation(self):
        with SessionLocal() as db:
            mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            with self.assertRaises(ValueError):
                mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            with self.assertRaises(ValueError):
                mcp_registry.create_server(db, "bad name", sys.executable, fake_args())
            with self.assertRaises(ValueError):
                mcp_registry.create_server(db, "ok", "   ", fake_args())

    def test_check_server_caches_tools_and_catalog_exposes_them(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            result = mcp_registry.check_server(db, row.id)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["tool_count"], 3)
            entries = mcp_registry.catalog(db)
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry["function"].startswith("mcp__campus__") for entry in entries))
        self.assertEqual({entry["tool"] for entry in entries}, {"boom", "echo", "slow"})

    def test_call_routes_to_the_right_tool(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            mcp_registry.check_server(db, row.id)
            entry = next(item for item in mcp_registry.catalog(db) if item["tool"] == "echo")
            outcome = mcp_registry.call(db, entry["function"], {"text": "你好"})
        self.assertTrue(outcome["ok"], outcome)
        self.assertEqual(outcome["server"], "campus")
        self.assertEqual(outcome["tool"], "echo")
        self.assertEqual(outcome["text"], "echo: 你好")

    def test_call_reports_error_result(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            mcp_registry.check_server(db, row.id)
            entry = next(item for item in mcp_registry.catalog(db) if item["tool"] == "boom")
            outcome = mcp_registry.call(db, entry["function"], {})
        self.assertFalse(outcome["ok"])
        self.assertIn("内部错误", outcome["text"])

    def test_disabled_server_is_not_called(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            mcp_registry.check_server(db, row.id)
            entry = next(item for item in mcp_registry.catalog(db) if item["tool"] == "echo")
            mcp_registry.update_server(db, row.id, enabled=False)
            self.assertEqual(mcp_registry.catalog(db), [])
            outcome = mcp_registry.call(db, entry["function"], {"text": "x"})
        self.assertFalse(outcome["ok"])
        self.assertIn("未启用", outcome["error"])

    def test_default_arguments_and_enabled_flag_survive_update(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args(),
                                             {"TOKEN": "abc"})
            updated = mcp_registry.update_server(db, row.id, command=sys.executable,
                                                 env={"TOKEN": mcp_registry.MASK, "NEW": "x"})
            self.assertEqual(updated.env["TOKEN"], "abc")
            self.assertEqual(updated.env["NEW"], "x")
            self.assertEqual(updated.args, fake_args())

    def test_two_servers_expose_isolated_function_names(self):
        with SessionLocal() as db:
            row = mcp_registry.create_server(db, "campus", sys.executable, fake_args())
            alias = mcp_registry.create_server(db, "alias", sys.executable, ["-u", ALIAS])
            mcp_registry.check_server(db, row.id)
            mcp_registry.check_server(db, alias.id)
            entries = mcp_registry.catalog(db)
        functions = [entry["function"] for entry in entries]
        self.assertEqual(len(functions), len(set(functions)))
        self.assertIn("mcp__campus__echo", functions)
        self.assertIn("mcp__alias__search", functions)


class McpApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)
        cls.client = TestClient(main.app)

    def setUp(self):
        with SessionLocal() as db:
            for row in mcp_registry.list_servers(db):
                mcp_registry.delete_server(db, row["id"])

    def test_read_requires_no_admin_but_mutations_do(self):
        self.assertEqual(self.client.get("/api/mcp/servers").status_code, 200)
        body = {"name": "campus", "command": sys.executable, "args": fake_args()}
        self.assertEqual(self.client.post("/api/mcp/servers", json=body).status_code, 401)
        created = self.client.post("/api/mcp/servers", json=body, headers=ADMIN)
        self.assertEqual(created.status_code, 200, created.text)

    def test_full_lifecycle_over_http(self):
        created = self.client.post("/api/mcp/servers", headers=ADMIN, json={
            "name": "campus", "command": sys.executable, "args": fake_args(),
            "env": {"API_KEY": "top-secret"}, "enabled": True}).json()["server"]
        self.assertEqual(created["env_keys"], ["API_KEY"])
        self.assertNotIn("top-secret", str(created))

        tested = self.client.post(f"/api/mcp/servers/{created['id']}/test", headers=ADMIN).json()
        self.assertTrue(tested["ok"], tested)
        self.assertEqual(tested["tool_count"], 3)

        tools = self.client.get("/api/mcp/tools").json()["tools"]
        self.assertEqual(len(tools), 3)

        updated = self.client.put(f"/api/mcp/servers/{created['id']}", headers=ADMIN,
                                  json={"enabled": False}).json()["server"]
        self.assertFalse(updated["enabled"])
        self.assertEqual(self.client.get("/api/mcp/tools").json()["tools"], [])

        self.assertEqual(self.client.delete(f"/api/mcp/servers/{created['id']}", headers=ADMIN).status_code, 200)
        self.assertEqual(self.client.get("/api/mcp/servers").json()["servers"], [])

    def test_validation_errors_are_422_with_message(self):
        response = self.client.post("/api/mcp/servers", headers=ADMIN,
                                    json={"name": "bad name", "command": "x"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("名称", response.json()["detail"])
        self.assertEqual(self.client.post("/api/mcp/servers/nope/test", headers=ADMIN).status_code, 404)


if __name__ == "__main__":
    unittest.main()
