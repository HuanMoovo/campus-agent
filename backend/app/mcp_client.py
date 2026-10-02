"""最小可用的 MCP（Model Context Protocol）stdio 客户端。

只依赖标准库：以子进程方式启动 MCP 服务器，用按行分隔的 JSON-RPC 2.0 完成
initialize / tools/list / tools/call 三步，够用且便于审计。网络型传输（SSE、
streamable HTTP）不在本版本范围内，接口预留了替换空间。

约定：任何失败都以 McpError 抛出，消息为中文，便于直接展示给用户。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "mens", "version": "1.0"}
MAX_MESSAGE_BYTES = 1_000_000


class McpError(RuntimeError):
    """MCP 服务器不可用或返回错误。"""


class McpStdioClient:
    """一次会话：启动进程 → 握手 → 调用 → 关闭。

    用法：
        with McpStdioClient(command="npx", args=["-y", "some-mcp-server"]) as client:
            tools = client.list_tools()
    """

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None,
                 init_timeout: float = 20.0, call_timeout: float = 60.0):
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.init_timeout = init_timeout
        self.call_timeout = call_timeout
        self._process: subprocess.Popen | None = None
        self._pending: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self._next_id = 0
        self._stderr_tail: list[str] = []
        self._closed = False
        self.server_info: dict[str, Any] = {}
        self.negotiated_version = ""

    # ---------------------------------------------------------------- 生命周期
    def __enter__(self) -> "McpStdioClient":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        if not self.command.strip():
            raise McpError("MCP 服务器缺少启动命令")
        environment = os.environ.copy()
        environment.update({k: str(v) for k, v in self.env.items()})
        environment.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            self._process = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=environment,
            )
        except FileNotFoundError as exc:
            raise McpError(f"启动失败：找不到命令 {self.command}") from exc
        except OSError as exc:
            raise McpError(f"启动失败：{exc}") from exc

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        self.server_info = self._handshake()

    def close(self) -> None:
        self._closed = True
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    # ------------------------------------------------------------------ 传输层
    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.strip()
            if not line or len(line) > MAX_MESSAGE_BYTES:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue  # 服务器日志混进 stdout 时跳过
            identifier = message.get("id")
            if identifier is None:
                continue  # 通知（logging/progress）无需处理
            with self._lock:
                inbox = self._pending.get(identifier)
            if inbox is not None:
                inbox.put(message)

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_tail.append(line.rstrip()[:400])
            del self._stderr_tail[:-8]

    def _send(self, payload: dict) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise McpError("MCP 服务器未启动")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise McpError(f"写入失败：{exc}") from exc

    def _request(self, method: str, params: dict | None, timeout: float) -> dict:
        with self._lock:
            self._next_id += 1
            identifier = self._next_id
            inbox: queue.Queue = queue.Queue()
            self._pending[identifier] = inbox
        try:
            self._send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}})
            try:
                message = inbox.get(timeout=timeout)
            except queue.Empty:
                tail = ("；服务器输出：" + " | ".join(self._stderr_tail[-2:])) if self._stderr_tail else ""
                raise McpError(f"{method} 超时（{timeout:.0f} 秒）{tail}") from None
        finally:
            with self._lock:
                self._pending.pop(identifier, None)
        if "error" in message:
            error = message.get("error") or {}
            raise McpError(f"{method} 返回错误：{error.get('message') or error}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # ------------------------------------------------------------------ 协议层
    def _handshake(self) -> dict:
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        }, self.init_timeout)
        self.negotiated_version = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        self._notify("notifications/initialized")
        info = result.get("serverInfo")
        return info if isinstance(info, dict) else {}

    def list_tools(self) -> list[dict]:
        """返回 [{name, description, inputSchema}]，按名称排序。"""
        result = self._request("tools/list", {}, self.init_timeout)
        tools = result.get("tools")
        rows = []
        for tool in tools if isinstance(tools, list) else []:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            rows.append({
                "name": str(tool["name"]),
                "description": str(tool.get("description") or ""),
                "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {"type": "object", "properties": {}},
            })
        return sorted(rows, key=lambda row: row["name"])

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """返回 {text, is_error, raw}；文本来自 content 列表。"""
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}}, self.call_timeout)
        chunks = []
        for block in result.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                chunks.append(str(block["text"]))
            elif block.get("type") == "image":
                chunks.append("[图片结果]")
            elif block.get("type") == "resource" and block.get("resource"):
                chunks.append(str((block["resource"] or {}).get("text") or "[资源结果]"))
        text = "\n".join(chunks).strip()
        return {"text": text[:_result_cap()], "is_error": bool(result.get("isError")),
                "truncated": len(text) > _result_cap(), "raw": result}


def _result_cap() -> int:
    return 200_000


def describe(command: str, args: list[str] | None = None, env: dict[str, str] | None = None,
             timeout: float = 25.0) -> dict:
    """一次性的连通性检查：启动、握手、列出工具，然后立刻关闭。"""
    started = time.monotonic()
    with McpStdioClient(command=command, args=args, env=env, init_timeout=timeout) as client:
        tools = client.list_tools()
        return {
            "ok": True,
            "server": client.server_info.get("name") or command,
            "version": client.server_info.get("version") or "",
            "protocolVersion": client.negotiated_version,
            "tool_count": len(tools),
            "tools": tools,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


__all__ = ["McpStdioClient", "McpError", "describe", "PROTOCOL_VERSION"]
