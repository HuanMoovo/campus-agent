"""MCP stdio 客户端测试：握手、列工具、调用、错误与超时均走真实子进程。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mcp_client import McpError, McpStdioClient, describe  # noqa: E402

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py")


def client(**kwargs) -> McpStdioClient:
    return McpStdioClient(command=sys.executable, args=["-u", FIXTURE], **kwargs)


class McpClientTest(unittest.TestCase):
    def test_handshake_exposes_server_info(self):
        with client() as connection:
            self.assertEqual(connection.server_info.get("name"), "fake-campus-mcp")
            self.assertEqual(connection.negotiated_version, "2024-11-05")

    def test_list_tools_is_sorted_and_complete(self):
        with client() as connection:
            tools = connection.list_tools()
        self.assertEqual([tool["name"] for tool in tools], ["boom", "echo", "slow"])
        echo = next(tool for tool in tools if tool["name"] == "echo")
        self.assertEqual(echo["description"], "回显输入文本")
        self.assertEqual(echo["inputSchema"]["properties"]["text"]["type"], "string")

    def test_call_tool_returns_text(self):
        with client() as connection:
            result = connection.call_tool("echo", {"text": "校园卡"})
        self.assertFalse(result["is_error"])
        self.assertEqual(result["text"], "echo: 校园卡")

    def test_tool_error_flag_is_preserved(self):
        with client() as connection:
            result = connection.call_tool("boom")
        self.assertTrue(result["is_error"])
        self.assertIn("内部错误", result["text"])

    def test_unknown_tool_raises_chinese_error(self):
        with client() as connection:
            with self.assertRaises(McpError) as caught:
                connection.call_tool("nope")
        self.assertIn("未知工具", str(caught.exception))

    def test_slow_call_times_out(self):
        with client(call_timeout=1.0) as connection:
            with self.assertRaises(McpError) as caught:
                connection.call_tool("slow", {"seconds": 5})
        self.assertIn("超时", str(caught.exception))

    def test_missing_command_reports_start_failure(self):
        with self.assertRaises(McpError) as caught:
            McpStdioClient(command="definitely-not-a-real-binary-xyz", args=[]).start()
        self.assertIn("启动失败", str(caught.exception))

    def test_describe_reports_tool_count(self):
        summary = describe(sys.executable, ["-u", FIXTURE])
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["server"], "fake-campus-mcp")
        self.assertEqual(summary["tool_count"], 3)
        self.assertGreaterEqual(summary["elapsed_ms"], 0)

    def test_blank_command_is_rejected(self):
        with self.assertRaises(McpError):
            McpStdioClient(command="   ").start()


if __name__ == "__main__":
    unittest.main()
