"""Vault harness for the adapter contract kit: a loopback fake KV v2 server and a real hvac
client, with the requests adapter spied so a test can see the ``verify`` value a read used."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

import pytest

from decoy_engine.secret_providers import parse_ref
from tests.secret_providers.adapters._contract import Observed
from tests.secret_providers.adapters._fake_vault import (
    KEY_B64,
    PINNED,
    TOKEN,
    VENDOR_TEXT,
    FakeVault,
    body,
)

_VAULT_ENV = ("VAULT_ADDR", "VAULT_TOKEN", "VAULT_NAMESPACE", "VAULT_CACERT", "VAULT_CAPATH")
_AMBIENT = (
    *_VAULT_ENV,
    "VAULT_CLIENT_CERT",
    "VAULT_CLIENT_KEY",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def hermetic(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """No ambient Vault or proxy state, and an empty home (no ``~/.vault-token``, no netrc)."""
    for name in _AMBIENT:
        monkeypatch.delenv(name, raising=False)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))


class VaultHarness:
    key: ClassVar[str] = "vault"
    failure_codes: ClassVar[frozenset[str]] = frozenset(
        {
            "secret_access_denied",
            "secret_version_unavailable",
            "secret_provider_unavailable",
            "secret_lease_unsupported",
            "secret_expired",
            "secret_material_invalid",
        }
    )
    frozen: ClassVar[frozenset[str]] = frozenset(
        {"endpoint", "credentials", "ca_bundle", "proxies"}
    )

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, proxies: bool = False
    ) -> None:
        # Imported here, not at module level: the kit sentry reads the class attributes of every
        # harness without the SDKs, and a skip at import would hide a missing cell.
        self._hvac = pytest.importorskip("hvac")
        self._adapters = pytest.importorskip("requests.adapters")
        from decoy_engine.secret_providers.vault import VaultKV2Provider

        self._home = tmp_path / "home"
        self._monkeypatch = monkeypatch
        hermetic(monkeypatch, self._home)
        if proxies:
            monkeypatch.setenv("HTTP_PROXY", "http://proxy-user:proxy-pass@127.0.0.1:9")
        self.server = FakeVault().__enter__()
        self.sentinels = (KEY_B64, VENDOR_TEXT, TOKEN, "proxy-pass")
        self.ref = parse_ref(f"vault://kv/team/app?version={PINNED}&field=key&encoding=base64")
        self._verify_seen: list[object] = []
        self._spy(monkeypatch)
        self.client = self._hvac.Client(url=self.server.url, token=TOKEN)
        self.provider = VaultKV2Provider(self.client)
        host = self.server.url.removeprefix("http://")
        self.expected = Observed(endpoint=host, credential=TOKEN, ca_bundle=True)

    def _spy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = self._adapters.HTTPAdapter.send
        seen = self._verify_seen

        def send(adapter: Any, request: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("verify"))
            return real(adapter, request, **kwargs)

        monkeypatch.setattr(self._adapters.HTTPAdapter, "send", send)

    def serve(self) -> None:
        self.server.state.status = 200
        self.server.state.payload = body()

    def inject(self, code: str) -> None:
        state = self.server.state
        state.status, state.payload = 200, body()
        if code == "secret_access_denied":
            state.status = 403
        elif code == "secret_version_unavailable":
            state.status = 404
        elif code == "secret_provider_unavailable":
            state.status = 500
        elif code == "secret_lease_unsupported":
            state.payload = body(lease_id="database/creds/x/abc")
        elif code == "secret_expired":
            state.payload = body(deletion_time="2020-01-01T00:00:00Z")
        elif code == "secret_material_invalid":
            state.payload = body(value="")
        else:
            raise AssertionError(code)

    def mismatch_version(self) -> None:
        self.server.state.status = 200
        self.server.state.payload = body(version=PINNED + 1)

    def drift(self) -> None:
        env = self._monkeypatch.setenv
        env("VAULT_ADDR", "http://127.0.0.1:1")
        env("VAULT_TOKEN", "s.drifted")
        env("VAULT_CACERT", str(self._home / "other-ca.pem"))
        env("VAULT_CLIENT_CERT", str(self._home / "c.pem"))
        env("VAULT_CLIENT_KEY", str(self._home / "c.key"))
        env("REQUESTS_CA_BUNDLE", str(self._home / "other-ca.pem"))
        env("HTTP_PROXY", "http://127.0.0.1:9")
        env("HTTPS_PROXY", "http://127.0.0.1:9")
        (self._home / ".vault-token").write_text("s.drifted-file")
        (self._home / ".netrc").write_text("machine 127.0.0.1 login drift password drift\n")
        os.utime(self._home / ".netrc")

    def observed(self) -> Observed:
        last = self.server.state.requests[-1]
        return Observed(
            endpoint=last["host"], credential=last["token"], ca_bundle=self._verify_seen[-1]
        )

    def reads(self) -> int:
        return len(self.server.state.requests)

    def close(self) -> None:
        self.server.close()
