"""测试夹具：MCP 服务器，用别名暴露同名工具。

命名冲突是 MCP 的常态（多个服务器都叫 `search`），本夹具固定提供 `search`
与带空格的名称，用于验证前缀隔离与名称规范化。
"""
from __future__ import annotations

import json
import sys

TOOLS = [
    {"name": "search", "description": "在校园网内搜索", "inputSchema": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "资料.读取", "description": "带非 ASCII 字符的工具名", "inputSchema": {"type": "object", "properties": {}}},
]


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        identifier = message.get("id")
        method = message.get("method")
        if identifier is None:
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": identifier, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "alias-mcp", "version": "0.2.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": identifier, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = message.get("params") or {}
            send({"jsonrpc": "2.0", "id": identifier, "result": {
                "content": [{"type": "text", "text": f"命中 {params.get('name')}"}]}})
        else:
            send({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "不支持"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
