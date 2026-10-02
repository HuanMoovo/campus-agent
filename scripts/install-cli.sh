#!/usr/bin/env bash
# Mens 命令行工具安装脚本（macOS / Linux）
# 用法： curl -fsSL https://raw.githubusercontent.com/HuanMoovo/campus-agent/main/scripts/install-cli.sh | bash
set -euo pipefail

ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/mens"
BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python_bin="$(command -v python3 || true)"
if [ -z "$python_bin" ]; then
  echo "未找到 python3，请先安装 Python 3.10+（macOS: brew install python@3.12；Ubuntu: sudo apt install python3-venv）" >&2
  exit 1
fi
if ! "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 版本过低，需要 3.10+（当前：$("$python_bin" -V)）" >&2
  exit 1
fi

echo "1/4 下载源码…"
curl -fsSL "https://github.com/HuanMoovo/campus-agent/archive/refs/heads/main.tar.gz" | tar xz -C "$TMP"

echo "2/4 解压到 $ROOT …"
rm -rf "$ROOT"
mkdir -p "$(dirname "$ROOT")"
mv "$TMP/campus-agent-main" "$ROOT"

echo "3/4 创建虚拟环境并安装依赖（约 1-3 分钟）…"
"$python_bin" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip --quiet
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt" --quiet

echo "4/4 生成 mens 命令…"
mkdir -p "$BIN"
cat > "$BIN/mens" <<EOF
#!/usr/bin/env bash
cd "$ROOT/backend" && exec "$ROOT/.venv/bin/python" -m app.cli "\$@"
EOF
chmod +x "$BIN/mens"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "提示：把 $BIN 加入 PATH，例如在 ~/.bashrc 或 ~/.zshrc 里加： export PATH=\"$BIN:\$PATH\"" ;;
esac

echo ""
echo "安装完成。验证："
"$BIN/mens" --version || true
echo '试试： mens ask "图书馆开放时间"'
echo "卸载： rm -rf $ROOT $BIN/mens"
