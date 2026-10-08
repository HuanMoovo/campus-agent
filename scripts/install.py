"""Install this project locally; run explicitly with Python or scripts/install.cmd."""
import argparse
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def configure(full_rag=False):
    destination = ROOT / "backend" / ".env"
    if destination.exists():
        print("Keeping existing backend/.env.")
        return
    config = (ROOT / "backend" / ".env.example").read_text(encoding="utf-8-sig")
    config = config.replace("change-this-before-deployment", secrets.token_urlsafe(32))
    if full_rag:
        config = config.replace("ENABLE_RAG=false", "ENABLE_RAG=true")
    # Exclusive creation protects an existing configuration from being overwritten.
    with destination.open("x", encoding="utf-8", newline="\n") as output:
        output.write(config)
    print("Created backend/.env with a random admin token (not printed).")


def run(command, directory):
    subprocess.run(command, cwd=directory, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-rag", action="store_true")
    parser.add_argument("--configure-only", action="store_true")
    args = parser.parse_args()
    if args.configure_only:
        configure(args.full_rag)
        return
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required.")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not node or not npm:
        raise RuntimeError("Install Node.js 22 or newer with npm, then retry.")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        raise RuntimeError("Node.js 22 or newer is required.")
    backend, frontend = ROOT / "backend", ROOT / "frontend"
    python = backend / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        venv.create(backend / ".venv", with_pip=True)
    requirements = "requirements-ai.txt" if args.full_rag else "requirements.txt"
    run([str(python), "-m", "pip", "install", "-r", requirements, "--disable-pip-version-check", "--no-cache-dir"], backend)
    configure(args.full_rag)
    run([str(python), "-c", "from langgraph.graph import StateGraph; print('LangGraph import verified')"], backend)
    run([str(python), "-m", "pytest", "-q"], backend)
    run([npm, "install", "--cache", ".npm-cache"], frontend)
    run([npm, "run", "build"], frontend)
    print("Installation, backend tests, and frontend build completed.")
    print("Start with scripts\start-backend.cmd and scripts\start-frontend.cmd, then open http://localhost:5173")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Installation stopped: {error}", file=sys.stderr)
        sys.exit(1)
