#!/usr/bin/env python
"""为发布产物生成 SHA-256 校验清单（SHA256SUMS.txt）。

用法：
    python scripts/release_checksums.py                 # 扫描 release/ 目录
    python scripts/release_checksums.py --dir release --out SHA256SUMS.txt
只收录安装包类文件（exe/dmg/zip/AppImage/deb），忽略中间目录与 blockmap。
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SUFFIXES = (".exe", ".dmg", ".zip", ".appimage", ".deb")


def sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="release", help="产物目录（默认 release）")
    parser.add_argument("--out", default="release/SHA256SUMS.txt", help="清单输出路径")
    parser.add_argument("--include-blockmap", action="store_true", help="一并收录 .blockmap")
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f"目录不存在：{root}")

    wanted = list(SUFFIXES) + ([".blockmap"] if args.include_blockmap else [])
    files = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in wanted)
    if not files:
        raise SystemExit(f"{root} 下没有找到安装包类文件")

    lines = []
    for path in files:
        digest = sha256(path)
        lines.append(f"{digest}  {path.name}")
        print(f"  {path.name}  {path.stat().st_size:,} B  {digest}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n清单已写入 {out}（{len(lines)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
