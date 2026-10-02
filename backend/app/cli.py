"""Mens 命令行客户端。

与桌面端共用同一套后端代码与数据目录（默认 %APPDATA%\\CampusAgent，可用
CAMPUS_DATA_DIR 覆盖），因此命令行里问过的问题、登记过的 MCP 服务器都会出现在
界面里，反之亦然。

用法：
    python -m app.cli ask "图书馆开放时间"
    python -m app.cli chat
    python -m app.cli mcp add campus --command npx --args -y some-server
    python -m app.cli mcp list|test|tools|remove
    python -m app.cli serve --port 8000
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

from sqlalchemy import select

from . import agent as agent_module
from . import mcp_registry
from .db import Base, SessionLocal, engine
from .models import Conversation, Message

VERSION = "1.2.1"
MODELS = ("auto", "qwen", "deepseek", "ollama")


def prepare() -> None:
    Base.metadata.create_all(engine)


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload.get("answer", ""))


def _record(db, conversation: Conversation, question: str, answer: str, extra: dict) -> None:
    db.add_all([
        Message(conversation_id=conversation.id, role="user", content=question),
        Message(conversation_id=conversation.id, role="assistant", content=answer, result_data=extra),
    ])
    db.commit()


def _answer(question: str, model: str, use_web: bool, local_model: str | None,
            conversation: Conversation | None) -> dict:
    with SessionLocal() as db:
        history = []
        if conversation is not None:
            rows = db.scalars(select(Message).where(Message.conversation_id == conversation.id)
                              .order_by(Message.id.desc()).limit(8)).all()
            history = [{"role": row.role, "content": row.content} for row in reversed(rows)]
        result = agent_module.run_agent(db, question, history, model, local_model=local_model, use_web=use_web)
        if conversation is not None:
            extra = {"sources": result.get("sources", []), "tool_calls": result.get("tool_calls", []),
                     "mode": result.get("mode", "demo"), "web": result.get("web", {})}
            _record(db, conversation, question, result["answer"], extra)
    return {"answer": result["answer"], "mode": result.get("mode", "demo"),
            "sources": result.get("sources", []), "tool_calls": result.get("tool_calls", [])}


def cmd_ask(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip()
    if not question:
        print("请提供问题文本", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        conversation = Conversation(id=str(uuid.uuid4()), client_id="cli")
        db.add(conversation)
        db.commit()
    payload = _answer(question, args.model, args.web, args.local_model, conversation)
    _print(payload, args.json)
    if args.json:
        return 0
    if payload["sources"] and args.show_sources:
        print("\n参考来源：")
        for index, source in enumerate(payload["sources"], start=1):
            suffix = f"（{source['url']}）" if source.get("url") else ""
            print(f"  [{index}] {source['title']}{suffix}")
    if payload["tool_calls"] and args.show_sources:
        print("\n工具调用：")
        for call in payload["tool_calls"]:
            print(f"  · {call.get('name')} {json.dumps(call.get('arguments') or {}, ensure_ascii=False)}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        conversation = Conversation(id=str(uuid.uuid4()), client_id="cli")
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id
    print(f"Mens 命令行对话（模型：{args.model}）。输入 /quit 退出，/new 开启新对话。")
    while True:
        try:
            question = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            continue
        if question in ("/quit", "/exit"):
            return 0
        if question == "/new":
            with SessionLocal() as db:
                conversation = Conversation(id=str(uuid.uuid4()), client_id="cli")
                db.add(conversation)
                db.commit()
                conversation_id = conversation.id
            print("已开启新对话。")
            continue
        with SessionLocal() as db:
            conversation = db.get(Conversation, conversation_id)
        payload = _answer(question, args.model, args.web, args.local_model, conversation)
        print(f"\n助手 > {payload['answer']}\n")


def cmd_mcp(args: argparse.Namespace) -> int:
    prepare()
    with SessionLocal() as db:
        if args.mcp_action == "list":
            rows = mcp_registry.list_servers(db)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
                return 0
            if not rows:
                print("尚未登记 MCP 服务器。用 mcp add 添加，例如：")
                print("  python -m app.cli mcp add campus --command npx --args -y some-mcp-server")
                return 0
            for row in rows:
                state = "启用" if row["enabled"] else "停用"
                print(f"[{state}] {row['name']}  {row['command']} {' '.join(row['args'])}")
                print(f"        工具 {row['tool_count']} 个｜环境变量 {', '.join(row['env_keys']) or '无'}"
                      f"｜上次检查 {row['last_checked_at'] or '未检查'}"
                      + (f"｜错误：{row['last_error']}" if row["last_error"] else ""))
            return 0

        if args.mcp_action == "add":
            env = {}
            for item in args.env or []:
                if "=" not in item:
                    print(f"环境变量需形如 KEY=VALUE：{item}", file=sys.stderr)
                    return 2
                key, value = item.split("=", 1)
                env[key.strip()] = value
            try:
                row = mcp_registry.create_server(db, args.name, args.command, args.args or [], env,
                                                 enabled=not args.disabled)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            print(f"已登记 {row.name}（{row.command} {' '.join(row.args or [])}）。用 mcp test {row.name} 检查连通性。")
            return 0

        row = next((item for item in mcp_registry.list_servers(db) if item["name"] == args.name), None)
        if row is None and args.mcp_action != "tools":
            print(f"未找到 MCP 服务器：{args.name}", file=sys.stderr)
            return 2

        if args.mcp_action == "remove":
            mcp_registry.delete_server(db, row["id"])
            print(f"已删除 {row['name']}。")
            return 0

        if args.mcp_action == "test":
            result = mcp_registry.check_server(db, row["id"])
            if not result["ok"]:
                print(f"连接失败：{result['error']}", file=sys.stderr)
                return 1
            print(f"连接成功：{result['server']} {result['version']}（协议 {result['protocolVersion']}，"
                  f"{result['tool_count']} 个工具，{result['elapsed_ms']} ms）")
            for tool in result["tools"]:
                print(f"  · {tool['name']}：{tool['description']}")
            return 0

        if args.mcp_action == "tools":
            entries = mcp_registry.catalog(db, enabled_only=not args.all)
            if args.json:
                print(json.dumps(entries, ensure_ascii=False, indent=2))
                return 0
            if not entries:
                print("没有可用的 MCP 工具（先 mcp test 拉取工具清单，或检查服务器是否启用）。")
                return 0
            for entry in entries:
                print(f"  {entry['function']}  <-  {entry['server']} / {entry['tool']}")
            return 0
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    prepare()
    import uvicorn
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mens", description="Mens 校园助手命令行")
    parser.add_argument("--version", action="version", version=f"Mens {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="提问一次并打印回答")
    ask.add_argument("question", nargs="+", help="问题文本")
    ask.add_argument("--model", choices=MODELS, default="auto")
    ask.add_argument("--local-model", default=None, help="本地模型名称（model 为 ollama 时使用）")
    ask.add_argument("--web", action="store_true", help="允许联网检索")
    ask.add_argument("--json", action="store_true", help="输出 JSON（便于脚本处理）")
    ask.add_argument("--show-sources", action="store_true", help="附带来源与工具调用")
    ask.set_defaults(func=cmd_ask)

    chat = sub.add_parser("chat", help="进入交互式对话")
    chat.add_argument("--model", choices=MODELS, default="auto")
    chat.add_argument("--local-model", default=None)
    chat.add_argument("--web", action="store_true")
    chat.set_defaults(func=cmd_chat)

    mcp = sub.add_parser("mcp", help="管理 MCP 服务器")
    mcp.add_argument("mcp_action", choices=["list", "add", "remove", "test", "tools"])
    mcp.add_argument("name", nargs="?", default="", help="服务器名称（list/tools 不需要）")
    mcp.add_argument("--command", default="", help="启动命令，如 npx、python")
    mcp.add_argument("--args", nargs=argparse.REMAINDER, default=[], help="命令参数（放在最后，可含连字符开头的参数）")
    mcp.add_argument("--env", nargs="*", default=[], help="环境变量 KEY=VALUE，可多个")
    mcp.add_argument("--disabled", action="store_true", help="登记后先停用")
    mcp.add_argument("--all", action="store_true", help="tools 时包含已停用服务器")
    mcp.add_argument("--json", action="store_true")
    mcp.set_defaults(func=cmd_mcp)

    serve = sub.add_parser("serve", help="启动本地后端（默认 127.0.0.1:8000）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    prepare()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
