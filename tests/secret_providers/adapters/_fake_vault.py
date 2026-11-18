"""A loopback fake of the Vault KV v2 read endpoint (stdlib ``http.server``), shared by the Vault
harness and the Vault conformance tests. It records what each request carried so tests can prove
which address, token and proxy a read used."""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

KEY_B64 = base64.b64encode(b"v" * 40).decode()
VENDOR_TEXT = "F13-VAULT-VENDOR-TEXT-0123456789abcdef"
TOKEN = "s.F13-VAULT-TOKEN-0123456789abcdef"
PINNED = 3


def body(
    *, version: int = PINNED, value: object = KEY_B64, deletion_time: str = "", **top: object
) -> dict[str, object]:
    out: dict[str, object] = {
        "request_id": "r",
        "lease_id": "",
        "renewable": False,
        "lease_duration": 0,
        "data": {
            "data": {"key": value},
            "metadata": {
                "created_time": "2026-01-01T00:00:00.123456Z",
                "deletion_time": deletion_time,
                "destroyed": False,
                "version": version,
            },
        },
        "wrap_info": None,
        "warnings": None,
        "auth": None,
    }
    out.update(top)
    return out


class State:
    """What the server answers (``status`` and ``payload``) and what it saw."""

    def __init__(self) -> None:
        self.status = 200
        self.payload: object = body()
        self.requests: list[dict[str, object]] = []


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, *_: object) -> None:  # silence the stdlib's stderr line
        return

    def do_GET(self) -> None:
        state = self.server.state
        headers = {k.lower(): v for k, v in self.headers.items()}
        state.requests.append(
            {
                "path": urlsplit(self.path).path,
                "host": headers.get("host"),
                "token": headers.get("x-vault-token"),
                "authorization": headers.get("authorization"),
            }
        )
        if state.status == 200:
            payload = state.payload
        else:
            payload = {"errors": [VENDOR_TEXT]}
        data = json.dumps(payload).encode()
        self.send_response(state.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    state: State


class FakeVault:
    """``with FakeVault() as vault:`` serves on ``vault.url`` until the block ends."""

    def __init__(self) -> None:
        self.state = State()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.state = self.state
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeVault:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
