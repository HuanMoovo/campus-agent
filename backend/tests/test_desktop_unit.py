"""Desktop security contract tests: only the Python standard library is needed."""
import asyncio
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from app.desktop_runtime import DesktopGuard, DesktopRuntime, request_is_authorized, write_ready


TOKEN = "a1" * 32
NONCE = "b2" * 24
PORT = 41321


def scope(host=None, token=TOKEN, peer="127.0.0.1", path="/api/health"):
    return {"type": "http", "path": path, "client": (peer, 54321), "headers": [
        (b"host", (host or f"127.0.0.1:{PORT}").encode()),
        (b"x-campus-desktop-token", token.encode()),
    ]}


class DesktopRequestTests(unittest.TestCase):
    def test_only_exact_loopback_authority_and_matching_token_are_accepted(self):
        self.assertTrue(request_is_authorized(scope(), TOKEN, PORT))
        self.assertTrue(request_is_authorized(scope(host=f"localhost:{PORT}"), TOKEN, PORT))
        for host in ("127.0.0.1", "localhost", "evil.example", f"evil.example:{PORT}",
                     f"localhost:{PORT + 1}", f"127.0.0.1.evil.example:{PORT}", f"127.0.0.1:{PORT}@evil.example"):
            with self.subTest(host=host):
                self.assertFalse(request_is_authorized(scope(host=host), TOKEN, PORT))
        for token in ("", "b1" * 32, TOKEN + " "):
            self.assertFalse(request_is_authorized(scope(token=token), TOKEN, PORT))
        self.assertFalse(request_is_authorized(scope(peer="192.168.1.2"), TOKEN, PORT))
        self.assertFalse(request_is_authorized(scope(), TOKEN, 0))

    def test_duplicate_headers_and_missing_peer_fail_closed(self):
        for header in ((b"host", f"127.0.0.1:{PORT}".encode()), (b"x-campus-desktop-token", TOKEN.encode())):
            request = scope()
            request["headers"].append(header)
            self.assertFalse(request_is_authorized(request, TOKEN, PORT))
        request = scope()
        request.pop("client")
        self.assertFalse(request_is_authorized(request, TOKEN, PORT))

    def test_static_and_api_paths_share_the_same_guard(self):
        async def check(path, token):
            messages = []
            reached = []

            async def downstream(request, receive, send):
                reached.append(request["path"])
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"hello"})

            async def send(message):
                messages.append(message)

            await DesktopGuard(downstream, TOKEN, PORT)(scope(path=path, token=token), None, send)
            return messages, reached

        for path in ("/", "/assets/main.js", "/api/health", "/api/desktop/shutdown"):
            denied, reached = asyncio.run(check(path, ""))
            self.assertEqual(denied[0]["status"], 401)
            self.assertEqual(reached, [])
            allowed, reached = asyncio.run(check(path, TOKEN))
            self.assertEqual(allowed[0]["status"], 200)
            self.assertEqual(reached, [path])
            self.assertIn(b"content-security-policy", dict(allowed[0]["headers"]))

    def test_ready_message_is_one_json_line_and_flushes(self):
        class Pipe(StringIO):
            flushed = False

            def flush(self):
                self.flushed = True

        stream = Pipe()
        write_ready(stream, PORT, NONCE)
        self.assertTrue(stream.flushed)
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(stream.getvalue()), {"event": "campus-ready", "host": "127.0.0.1", "port": PORT, "nonce": NONCE})
        self.assertNotIn(TOKEN, stream.getvalue())


class DesktopPathTests(unittest.TestCase):
    def test_paths_are_absolute_and_secret_is_never_in_repr(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            env = {"CAMPUS_DESKTOP_TOKEN": TOKEN, "CAMPUS_DESKTOP_NONCE": NONCE, "CAMPUS_DATA_DIR": str(root / "data"),
                   "CAMPUS_FRONTEND_DIR": str(root), "CAMPUS_CONFIG_FILE": str(root / ".env")}
            runtime = DesktopRuntime.from_environment(env)
            self.assertEqual(runtime.data_dir, (root / "data").resolve())
            self.assertNotIn(TOKEN, repr(runtime))
            self.assertNotIn(NONCE, repr(runtime))
            for name in ("CAMPUS_DATA_DIR", "CAMPUS_FRONTEND_DIR", "CAMPUS_CONFIG_FILE"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    DesktopRuntime.from_environment({**env, name: "relative/path"})
            for token in ("", "too-short", "q" * 64, "a" * 257):
                with self.subTest(token_length=len(token)), self.assertRaises(ValueError):
                    DesktopRuntime.from_environment({**env, "CAMPUS_DESKTOP_TOKEN": token})
            for nonce in ("", "g" * 48, "b" * 47, "b" * 49):
                with self.subTest(nonce_length=len(nonce)), self.assertRaises(ValueError):
                    DesktopRuntime.from_environment({**env, "CAMPUS_DESKTOP_NONCE": nonce})
            with self.assertRaisesRegex(ValueError, "index.html"):
                DesktopRuntime.from_environment({**env, "CAMPUS_FRONTEND_DIR": str(root / "missing")})


if __name__ == "__main__":
    unittest.main()
