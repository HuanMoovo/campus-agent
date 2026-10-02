"""测试夹具：一个最小的 MCP stdio 服务器。

按行读取 JSON-RPC 2.0，支持 initialize / tools/list / tools/call。
用于验证客户端的握手、列工具、调用、错误与超时路径，不依赖任何外部服务。
"""
from __future__ import annotations

import json
import sys
import time

TOOLS = [
    {"name": "echo", "description": "回显输入文本", "inputSchema": {
        "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "boom", "description": "总是返回错误结果", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "slow", "description": "三秒后才返回", "inputSchema": {"type": "object", "properties": {}}},
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
        method = message.get("method")
        identifier = message.get("id")
        if identifier is None:
            continue

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": identifier, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "fake-campus-mcp", "version": "0.1.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": identifier, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "echo":
                send({"jsonrpc": "2.0", "id": identifier, "result": {
                    "content": [{"type": "text", "text": f"echo: {arguments.get('text', '')}"}]}})
            elif name == "boom":
                send({"jsonrpc": "2.0", "id": identifier, "result": {
                    "content": [{"type": "text", "text": "内部错误：示例失败"}], "isError": True}})
            elif name == "slow":
                time.sleep(float(arguments.get("seconds") or 3))
                send({"jsonrpc": "2.0", "id": identifier, "result": {
                    "content": [{"type": "text", "text": "慢工具完成"}]}})
            else:
                send({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": f"未知工具：{name}"}})
        else:
            send({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": f"未知方法：{method}"}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
