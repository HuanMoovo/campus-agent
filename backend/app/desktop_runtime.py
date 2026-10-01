"""Desktop process contract and request isolation (stdlib-only until mounting)."""
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from typing import Mapping


@dataclass(frozen=True)
class DesktopRuntime:
    token: str = field(repr=False)
    nonce: str = field(repr=False)
    data_dir: Path
    frontend_dir: Path
    config_file: Path

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None):
        env = os.environ if environ is None else environ
        token = env.get("CAMPUS_DESKTOP_TOKEN", "")
        if re.fullmatch(r"[0-9a-fA-F]{32,256}", token) is None:
            raise ValueError("CAMPUS_DESKTOP_TOKEN must be 32-256 hexadecimal characters")
        nonce = env.get("CAMPUS_DESKTOP_NONCE", "")
        if re.fullmatch(r"[0-9a-fA-F]{48}", nonce) is None:
            raise ValueError("CAMPUS_DESKTOP_NONCE must be 48 hexadecimal characters")
        paths = {}
        for name in ("CAMPUS_DATA_DIR", "CAMPUS_FRONTEND_DIR", "CAMPUS_CONFIG_FILE"):
            value = env.get(name, "")
            path = Path(value)
            if not value or not path.is_absolute():
                raise ValueError(f"{name} must be an absolute path")
            paths[name] = path.resolve()
        frontend_dir = paths["CAMPUS_FRONTEND_DIR"]
        if not (frontend_dir / "index.html").is_file():
            raise ValueError("Frontend build is missing index.html; build the frontend first")
        return cls(token, nonce, paths["CAMPUS_DATA_DIR"], frontend_dir, paths["CAMPUS_CONFIG_FILE"])


def desktop_enabled() -> bool:
    return os.environ.get("CAMPUS_DESKTOP_MODE") == "1"


def request_is_authorized(scope: dict, token: str, port: int) -> bool:
    """Reject duplicate headers, foreign peers, DNS rebinding and missing secrets."""
    if not 0 < port <= 65535:
        return False
    try:
        if not ipaddress.ip_address(scope["client"][0]).is_loopback:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    headers: dict[bytes, list[bytes]] = {}
    for name, value in scope.get("headers", []):
        headers.setdefault(name.lower(), []).append(value)
    hosts = headers.get(b"host", [])
    tokens = headers.get(b"x-campus-desktop-token", [])
    allowed_hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()}
    return (
        len(hosts) == 1 and hosts[0].lower() in allowed_hosts
        and len(tokens) == 1
        and secrets.compare_digest(tokens[0], token.encode("ascii"))
    )


class DesktopGuard:
    def __init__(self, app, token: str, port: int):
        self.app = app
        self.token = token
        self.port = port

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if not request_is_authorized(scope, self.token, self.port):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                body = b'{"detail":"Desktop request denied"}'
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store")
                ]})
                await send({"type": "http.response.body", "body": body})
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
                ]
            await send(message)

        await self.app(scope, receive, secure_send)


def install_desktop_routes(app):
    """Called after API registration, so StaticFiles cannot shadow API routes."""
    if not desktop_enabled():
        return
    from fastapi import HTTPException
    from starlette.staticfiles import StaticFiles

    runtime = DesktopRuntime.from_environment()
    port = int(os.environ.get("CAMPUS_DESKTOP_PORT", "0"))
    if not 0 < port <= 65535:
        raise ValueError("Desktop entry must bind a port before loading the application")
    app.add_middleware(DesktopGuard, token=runtime.token, port=port)

    @app.post("/api/desktop/shutdown", include_in_schema=False)
    async def shutdown_desktop():
        shutdown = getattr(app.state, "desktop_shutdown", None)
        if shutdown is None:
            raise HTTPException(503, "Desktop shutdown is unavailable")
        shutdown()
        return {"status": "stopping"}

    app.mount("/", StaticFiles(directory=runtime.frontend_dir, html=True, follow_symlink=False), name="desktop-ui")


def write_ready(stream, port: int, nonce: str):
    stream.write(json.dumps({"event": "campus-ready", "host": "127.0.0.1", "port": port, "nonce": nonce}) + "\n")
    stream.flush()
