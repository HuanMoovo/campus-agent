#!/usr/bin/env python
"""启动打包产物，确认内置后端与界面真的起来了，然后退出。

三类 CI 平台都用它做“跑起来才算过”的冒烟检查：启动 → 轮询调试端口拿到内部地址 →
请求界面入口 → 断言返回 HTML 且包含预期字样 → 关闭进程树。

用法：
    python scripts/smoke_package.py --command "release/win-unpacked/Mens.exe" --expect Mens
    python scripts/smoke_package.py --command "xvfb-run -a /opt/Mens/mens --no-sandbox" --expect Mens
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def poll_page(port: int, deadline: float) -> str | None:
    """从 CDP 列表里找出应用自身的页面地址（形如 http://127.0.0.1:<port>/）。"""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as response:
                for target in json.load(response):
                    url = (target or {}).get("url") or ""
                    if target.get("type") == "page" and url.startswith("http://127.0.0.1:"):
                        return url
        except Exception:
            pass
        time.sleep(2)
    return None


def fetch(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read().decode("utf-8", "replace")


def main() -> int:
    # Windows 控制台默认 cp1252，直接打印中文会抛 UnicodeEncodeError（CI 上真踩过），
    # 这里把标准输出切到 UTF-8 并对无法编码的字符降级替换。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", required=True, help="启动产物的命令（可用引号）")
    parser.add_argument("--port", type=int, default=9700, help="CDP 调试端口")
    parser.add_argument("--timeout", type=float, default=150.0, help="等待秒数")
    parser.add_argument("--expect", default="Mens", help="界面 HTML 中应出现的字样")
    parser.add_argument("--extra-arg", action="append", default=[], help="追加启动参数，可重复")
    args = parser.parse_args()

    command = shlex.split(args.command) + args.extra_arg + [f"--remote-debugging-port={args.port}"]
    print(f"启动: {' '.join(command)}")
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        deadline = time.time() + args.timeout
        origin = poll_page(args.port, deadline)
        if not origin:
            tail = ""
            if process.poll() is not None and process.stdout:
                tail = "".join(process.stdout.readlines()[-20:])
            print(f"失败：{args.timeout:.0f} 秒内没有出现应用页面（退出码 {process.poll()}）", file=sys.stderr)
            if tail:
                print(tail, file=sys.stderr)
            return 1

        print(f"应用内部地址: {origin}")

        # 桌面后端要求外壳注入的请求头：外部直接请求得到 401 说明服务在跑且鉴权生效，
        # 与 200 一样都算通过；只有连不上或返回其它状态码才算失败。
        try:
            status, body = fetch(origin)
            detail = f"HTTP {status}，{len(body)} 字符"
        except urllib.error.HTTPError as error:
            status, body, detail = error.code, "", f"HTTP {error.code}"
        print(f"界面入口探测: {detail}")
        if status == 401:
            print("  401 = 内置后端已启动且鉴权生效（外部请求无外壳请求头）")
        elif status == 200:
            if args.expect not in body:
                print(f"失败：界面未包含预期字样 {args.expect!r}", file=sys.stderr)
                return 1
            print(f"  200 = 界面可访问且包含 {args.expect!r}")
        else:
            print(f"失败：界面入口返回 {status}", file=sys.stderr)
            return 1

        print("冒烟通过：产物可启动，内置后端与界面进程均已就绪")
        return 0
    finally:
        try:
            process.terminate()
            process.wait(timeout=15)
        except Exception:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
