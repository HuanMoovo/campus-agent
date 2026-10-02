"""CLI 测试：子命令解析、MCP 管理与一次离线问答（不依赖任何外部服务）。"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CAMPUS_DATA_DIR"] = tempfile.mkdtemp(prefix="mens-cli-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cli, mcp_registry  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Conversation, Message  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py")


def run(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(argv)
    return code, buffer.getvalue()


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(engine)

    def setUp(self):
        with SessionLocal() as db:
            for row in mcp_registry.list_servers(db):
                mcp_registry.delete_server(db, row["id"])

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as caught:
            cli.main(["--version"])
        self.assertEqual(caught.exception.code, 0)

    def test_missing_question_is_a_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            cli.main(["ask"])
        self.assertEqual(caught.exception.code, 2)

    def test_mcp_add_list_test_tools_remove_roundtrip(self):
        code, _ = run(["mcp", "add", "campus", "--command", sys.executable, "--args", "-u", FIXTURE])
        self.assertEqual(code, 0)

        code, listing = run(["mcp", "list", "--json"])
        rows = json.loads(listing)
        self.assertEqual([row["name"] for row in rows], ["campus"])
        self.assertEqual(rows[0]["tool_count"], 0)

        code, tested = run(["mcp", "test", "campus"])
        self.assertEqual(code, 0)
        self.assertIn("连接成功", tested)
        self.assertIn("echo", tested)

        code, tools = run(["mcp", "tools", "--json"])
        entries = json.loads(tools)
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(entry["function"].startswith("mcp__campus__") for entry in entries))

        code, _ = run(["mcp", "remove", "campus"])
        self.assertEqual(code, 0)
        self.assertEqual(run(["mcp", "list", "--json"])[1].strip(), "[]")

    def test_mcp_test_reports_failure_for_bad_command(self):
        run(["mcp", "add", "broken", "--command", "definitely-not-a-real-binary-xyz"])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = cli.main(["mcp", "test", "broken"])
        self.assertEqual(code, 1)
        self.assertIn("启动失败", buffer.getvalue())

    def test_unknown_server_is_reported(self):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = cli.main(["mcp", "test", "ghost"])
        self.assertEqual(code, 2)
        self.assertIn("未找到", buffer.getvalue())

    def test_ask_without_model_still_answers_and_persists(self):
        with SessionLocal() as db:
            before = db.scalar(select(func.count()).select_from(Message))
        code, output = run(["ask", "图书馆开放时间", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertTrue(payload["answer"])
        self.assertIn(payload["mode"], {"demo", "llm", "service", "mcp"})
        with SessionLocal() as db:
            after = db.scalar(select(func.count()).select_from(Message))
            conversations = db.scalar(select(func.count()).select_from(Conversation))
        self.assertEqual(after - before, 2)  # 提问与回答各一条
        self.assertGreaterEqual(conversations, 1)

    def test_env_entries_need_equals_sign(self):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = cli.main(["mcp", "add", "campus", "--command", "x", "--env", "BAD"])
        self.assertEqual(code, 2)
        self.assertIn("KEY=VALUE", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
