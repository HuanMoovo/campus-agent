"""Actual sidecar lifecycle tests; require the normal backend dependencies."""
import importlib.util
import json
import os
from pathlib import Path
from queue import Queue, Empty
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler


BACKEND = Path(__file__).resolve().parents[1]
DEPENDENCIES = ("fastapi", "uvicorn", "sqlalchemy", "pydantic_settings", "httpx", "multipart")
HAS_DEPENDENCIES = all(importlib.util.find_spec(name) is not None for name in DEPENDENCIES)


@unittest.skipUnless(HAS_DEPENDENCIES, "Install backend requirements before sidecar integration tests")
class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="campus-desktop-test-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("<!doctype html><title>Desktop test</title>", encoding="utf-8")
        (self.root / "private.txt").write_text("PRIVATE FILE", encoding="utf-8")
        config = self.root / ".env"
        config.write_text("QWEN_MODEL=desktop-model-test\nADMIN_TOKEN=do-not-use-this\n", encoding="utf-8")
        self.token = secrets.token_hex(32)
        self.nonce = secrets.token_hex(24)
        self.env = {**os.environ,
                    "CAMPUS_DESKTOP_TOKEN": self.token,
                    "CAMPUS_DESKTOP_NONCE": self.nonce,
                    "CAMPUS_DATA_DIR": str(self.root / "user-data"),
                    "CAMPUS_FRONTEND_DIR": str(frontend),
                    "CAMPUS_CONFIG_FILE": str(config),
                    "DATABASE_URL": "this-value-must-be-ignored-by-desktop",
                    "ENABLE_RAG": "false", "QWEN_API_KEY": "", "DEEPSEEK_API_KEY": "",
                    "PYTHONIOENCODING": "utf-8"}
        self.env.pop("CAMPUS_DESKTOP_MODE", None)
        self.env.pop("CAMPUS_DESKTOP_PORT", None)
        self.env.pop("QWEN_MODEL", None)
        self.opener = build_opener(ProxyHandler({}))

    def start_sidecar(self):
        self.proc = subprocess.Popen([sys.executable, str(BACKEND / "desktop_entry.py"), "--desktop"],
                                     cwd=BACKEND, env=self.env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(self.cleanup_process)
        ready = Queue()
        threading.Thread(target=lambda: ready.put(self.proc.stdout.readline()), daemon=True).start()
        try:
            line = ready.get(timeout=30)
        except Empty:
            self.fail("Sidecar startup did not produce its readiness message within 30 seconds")
        if not line:
            self.fail("Sidecar exited before readiness: " + self.proc.stderr.read())
        message = json.loads(line)
        self.assertEqual(message["event"], "campus-ready")
        self.assertEqual(message["host"], "127.0.0.1")
        self.assertEqual(message["nonce"], self.nonce)
        self.assertNotIn(self.token, line)
        self.port = message["port"]
        self.assertGreater(self.port, 0)
        self.assertLessEqual(self.port, 65535)

    def cleanup_process(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=10)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            stream.close()

    def request(self, path, method="GET", token=True, headers=None, payload=None):
        merged = {"X-Campus-Desktop-Token": self.token} if token else {}
        merged.update(headers or {})
        if payload is not None:
            merged["Content-Type"] = "application/json"
        req = Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=merged,
                      data=json.dumps(payload).encode() if payload is not None else None)
        try:
            response = self.opener.open(req, timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read()

    def test_real_startup_auth_static_database_and_shutdown(self):
        self.start_sidecar()
        self.assertTrue((self.root / "user-data" / "campus.db").is_file())
        self.assertEqual(self.request("/api/health")[0], 200)
        self.assertIn(b"Desktop test", self.request("/")[1])
        for path in ("/", "/api/health", "/api/documents"):
            self.assertEqual(self.request(path, token=False)[0], 401)
            self.assertEqual(self.request(path, headers={"Host": f"evil.example:{self.port}"})[0], 401)
        self.assertEqual(self.request("/api/health", headers={"Host": "127.0.0.1:1"})[0], 401)
        for path in ("/../private.txt", "/%2e%2e/private.txt", "/.env"):
            status, body = self.request(path)
            self.assertEqual(status, 404)
            self.assertNotIn(b"PRIVATE FILE", body)
        status, body = self.request("/api/documents", method="POST", payload={"title": "Desktop document", "content": "Saved in isolated user data"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["title"], "Desktop document")
        self.assertEqual(self.request("/api/desktop/shutdown", method="POST", token=False)[0], 401)
        self.assertEqual(self.request("/api/desktop/shutdown", method="POST")[0], 200)
        self.assertEqual(self.proc.wait(timeout=15), 0)
        self.assertEqual(self.proc.stdout.read(), "")
        diagnostics = self.proc.stderr.read()
        self.assertNotIn(self.token, diagnostics)
        self.assertNotIn(self.nonce, diagnostics)

    def test_parent_pipe_loss_stops_the_backend(self):
        self.start_sidecar()
        self.proc.stdin.close()
        self.assertEqual(self.proc.wait(timeout=15), 0)

    def test_desktop_config_overrides_credentials_and_database_only_in_desktop(self):
        script = (
            "from app.config import get_settings; import json; s=get_settings(); "
            "print(json.dumps({'database':s.database_url,'data':str(s.data_dir),"
            "'model':s.qwen_model,'admin':s.admin_token,'cors':s.cors_origins}))"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND,
                                env={**self.env, "CAMPUS_DESKTOP_MODE": "1"},
                                capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        settings = json.loads(result.stdout)
        self.assertEqual(settings["database"], "sqlite:///" + (self.root / "user-data" / "campus.db").as_posix())
        self.assertEqual(settings["admin"], self.token)
        self.assertEqual(settings["model"], "desktop-model-test")
        self.assertEqual(settings["cors"], "")
        web_result = subprocess.run([sys.executable, "-c", script], cwd=BACKEND,
                                    env={**self.env, "ADMIN_TOKEN": "web-mode-token"},
                                    capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        web_settings = json.loads(web_result.stdout)
        self.assertEqual(web_settings["database"], self.env["DATABASE_URL"])
        self.assertEqual(web_settings["admin"], "web-mode-token")


if __name__ == "__main__":
    unittest.main()
