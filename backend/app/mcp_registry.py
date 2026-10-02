"""MCP 服务器注册表：持久化、连通性检查、工具编目与调用。

工具暴露给模型时统一改名成 `mcp__<服务器>__<工具>`（函数名只允许字母数字下划线和
横线，长度上限 64），原始名称保留在编目里，调用时再换回去。
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mcp_client
from .models import McpServer

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
PREFIX = "mcp__"
MAX_FUNCTION_NAME = 64
MASK = "••••••"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", part)


def function_name(server: str, tool: str) -> str:
    """把服务器与工具名拼成合法的函数名，过长时截断并附加短哈希。"""
    base = f"{PREFIX}{_sanitize(server)}__{_sanitize(tool)}"
    if len(base) <= MAX_FUNCTION_NAME:
        return base
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:6]
    return base[:MAX_FUNCTION_NAME - 7] + "_" + digest


def public_row(row: McpServer, tools: list[dict] | None = None) -> dict:
    """环境变量只回键名与掩码，令牌类内容不经过接口回显。"""
    return {
        "id": row.id,
        "name": row.name,
        "command": row.command,
        "args": list(row.args or []),
        "env_keys": sorted((row.env or {}).keys()),
        "env_masked": {key: MASK for key in sorted((row.env or {}).keys())},
        "enabled": bool(row.enabled),
        "tools": tools if tools is not None else list(row.last_tools or []),
        "tool_count": len(tools if tools is not None else (row.last_tools or [])),
        "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
        "last_error": row.last_error or "",
    }


def list_servers(db: Session) -> list[dict]:
    rows = db.scalars(select(McpServer).order_by(McpServer.name)).all()
    return [public_row(row) for row in rows]


def get_server(db: Session, server_id: str) -> McpServer | None:
    return db.get(McpServer, server_id)


def validate(name: str, command: str, args: list, env: dict) -> None:
    if not NAME_PATTERN.match((name or "").strip()):
        raise ValueError("名称只能包含字母、数字、下划线和横线（1-40 位），且以字母或数字开头")
    if not (command or "").strip():
        raise ValueError("启动命令不能为空")
    if len(command) > 300:
        raise ValueError("启动命令过长（上限 300 字符）")
    if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
        raise ValueError("参数必须是字符串列表")
    if len(args) > 30:
        raise ValueError("参数个数过多（上限 30）")
    if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        raise ValueError("环境变量必须是字符串到字符串的映射")
    if len(env) > 30:
        raise ValueError("环境变量数量过多（上限 30）")


def create_server(db: Session, name: str, command: str, args: list | None = None,
                  env: dict | None = None, enabled: bool = True) -> McpServer:
    name = (name or "").strip()
    validate(name, command, list(args or []), dict(env or {}))
    if db.scalar(select(McpServer).where(McpServer.name == name)) is not None:
        raise ValueError(f"服务器名称已存在：{name}")
    row = McpServer(id=str(uuid.uuid4()), name=name, command=command.strip(),
                    args=list(args or []), env=dict(env or {}), enabled=bool(enabled))
    db.add(row)
    db.commit()
    return row


def update_server(db: Session, server_id: str, *, name: str | None = None, command: str | None = None,
                  args: list | None = None, env: dict | None = None, enabled: bool | None = None) -> McpServer:
    row = db.get(McpServer, server_id)
    if row is None:
        raise LookupError("服务器不存在")
    merged_name = (name or row.name).strip()
    merged_command = (command or row.command).strip()
    merged_args = list(row.args or []) if args is None else list(args)
    merged_env = dict(row.env or {})
    if env is not None:
        # 掩码占位符表示“保持原值”，避免编辑界面回显令牌
        merged_env.update({key: value for key, value in env.items() if value != MASK})
    validate(merged_name, merged_command, merged_args, merged_env)
    if merged_name != row.name and db.scalar(select(McpServer).where(McpServer.name == merged_name)) is not None:
        raise ValueError(f"服务器名称已存在：{merged_name}")
    row.name, row.command, row.args, row.env = merged_name, merged_command, merged_args, merged_env
    if enabled is not None:
        row.enabled = bool(enabled)
    db.commit()
    return row


def delete_server(db: Session, server_id: str) -> None:
    row = db.get(McpServer, server_id)
    if row is None:
        raise LookupError("服务器不存在")
    db.delete(row)
    db.commit()


def check_server(db: Session, server_id: str, timeout: float = 25.0) -> dict:
    """真实启动一次服务器：握手、列工具，并把结果缓存到行上供界面直接展示。"""
    row = db.get(McpServer, server_id)
    if row is None:
        raise LookupError("服务器不存在")
    try:
        summary = mcp_client.describe(row.command, list(row.args or []), dict(row.env or {}), timeout=timeout)
    except mcp_client.McpError as exc:
        row.last_error = str(exc)
        row.last_checked_at = _now()
        db.commit()
        return {"ok": False, "error": str(exc), "tools": []}
    row.last_tools = summary["tools"]
    row.last_error = ""
    row.last_checked_at = _now()
    db.commit()
    return {"ok": True, "server": summary["server"], "version": summary["version"],
            "protocolVersion": summary["protocolVersion"], "tool_count": summary["tool_count"],
            "tools": summary["tools"], "elapsed_ms": summary["elapsed_ms"]}


def catalog(db: Session, enabled_only: bool = True) -> list[dict]:
    """可暴露给模型的工具清单（含调用所需的服务器身份）。"""
    if db is None:  # 无数据库上下文（例如纯规划测试）时视为没有外部工具
        return []
    statement = select(McpServer).order_by(McpServer.name)
    if enabled_only:
        statement = statement.where(McpServer.enabled.is_(True))
    entries = []
    for row in db.scalars(statement).all():
        for tool in list(row.last_tools or []):
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            entries.append({
                "server_id": row.id,
                "server": row.name,
                "tool": str(tool["name"]),
                "function": function_name(row.name, str(tool["name"])),
                "description": (str(tool.get("description") or "").strip() or f"{row.name} 的 {tool['name']} 工具"),
                "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {"type": "object", "properties": {}},
            })
    return entries


def openai_tools(entries: list[dict]) -> list[dict]:
    """转成 OpenAI 风格的 function 定义，供模型选择。"""
    return [{"type": "function", "function": {
        "name": entry["function"], "description": entry["description"], "parameters": entry["inputSchema"],
    }} for entry in entries]


def call(db: Session, function: str, arguments: dict | None = None) -> dict:
    """按函数名调用远程工具，返回 {ok, server, tool, text, error}。"""
    entry = next((item for item in catalog(db, enabled_only=False) if item["function"] == function), None)
    if entry is None:
        return {"ok": False, "error": f"未找到 MCP 工具：{function}", "server": "", "tool": "", "text": ""}
    row = db.get(McpServer, entry["server_id"])
    if row is None or not row.enabled:
        return {"ok": False, "error": f"MCP 服务器未启用：{entry['server']}", "server": entry["server"],
                "tool": entry["tool"], "text": ""}
    try:
        with mcp_client.McpStdioClient(row.command, list(row.args or []), dict(row.env or {})) as connection:
            result = connection.call_tool(entry["tool"], arguments or {})
    except mcp_client.McpError as exc:
        return {"ok": False, "error": str(exc), "server": entry["server"], "tool": entry["tool"], "text": ""}
    return {"ok": not result["is_error"], "error": "" if not result["is_error"] else "工具返回错误",
            "server": entry["server"], "tool": entry["tool"], "text": result["text"]}


__all__ = ["list_servers", "get_server", "create_server", "update_server", "delete_server",
           "check_server", "catalog", "openai_tools", "call", "public_row", "function_name",
           "MASK", "PREFIX"]
