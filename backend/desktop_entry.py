"""Private loopback backend owned by the Electron desktop main process."""
import argparse
import asyncio
from contextlib import redirect_stdout
import logging
import os
import socket
import sys
import threading

from app.desktop_runtime import DesktopRuntime, write_ready


async def run_desktop(runtime: DesktopRuntime, ready_stream, parent_stream):
    import uvicorn

    # A pre-bound socket avoids races between finding a free port and starting Uvicorn.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        os.environ["CAMPUS_DESKTOP_MODE"] = "1"
        os.environ["CAMPUS_DESKTOP_PORT"] = str(port)

        from app.main import app

        class ReadyServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started and not self.should_exit:
                    write_ready(ready_stream, port, runtime.nonce)

        server = ReadyServer(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="info", access_log=False,
            proxy_headers=False, server_header=False, timeout_graceful_shutdown=5,
            log_config=None, loop="asyncio", http="h11", ws="none",
        ))
        app.state.desktop_shutdown = lambda: setattr(server, "should_exit", True)
        loop = asyncio.get_running_loop()

        def watch_parent():
            try:
                # Electron leaves this pipe open for the lifetime of the desktop process.
                while parent_stream.read(1):
                    pass
            except (OSError, ValueError):
                pass
            finally:
                try:
                    loop.call_soon_threadsafe(setattr, server, "should_exit", True)
                except RuntimeError:
                    pass  # The server has already stopped and closed its loop.

        threading.Thread(target=watch_parent, name="desktop-parent-watch", daemon=True).start()
        try:
            await server.serve(sockets=[listener])
            if not server.started:
                raise RuntimeError("Desktop backend did not complete startup")
        finally:
            from app.db import engine
            engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Campus Agent desktop backend")
    parser.add_argument("--desktop", action="store_true", help="Run the private desktop backend")
    args = parser.parse_args(argv)
    if not args.desktop:
        parser.error("This entry point requires --desktop; use uvicorn app.main:app for web mode")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")
    ready_stream = sys.stdout
    # stdout is an IPC protocol. Library diagnostics and print() calls go to stderr.
    try:
        with redirect_stdout(sys.stderr):
            runtime = DesktopRuntime.from_environment()
            runtime.data_dir.mkdir(parents=True, exist_ok=True)
            asyncio.run(run_desktop(runtime, ready_stream, sys.stdin))
    except Exception as exc:
        # Never echo exception values from settings parsing: they can contain secrets.
        logging.error("Desktop backend failed to start (%s). Check installation and desktop configuration.", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    # Required by frozen Windows executables and harmless for ordinary Python runs.
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
