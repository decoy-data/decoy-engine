"""Vault adapter conformance (F13 slice E3): frozen at build (SR-3), value-free failures (SR-1),
DEBUG logging (SR-2) and the ``~/.vault-token`` rule. Runs against the loopback fake server."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from decoy_engine.secret_providers import SecretProviderConfigError, parse_ref
from decoy_engine.secret_providers.vault import (
    VaultClientConfigError,
    VaultKV2Provider,
    client_from_env,
)
from tests.secret_providers.adapters import _contract as kit
from tests.secret_providers.adapters._fake_vault import (
    KEY_B64,
    PINNED,
    TOKEN,
    VENDOR_TEXT,
    FakeVault,
    body,
)
from tests.secret_providers.adapters._harness_vault import hermetic
from tests.sentry.fa.rules import toml_reader

hvac = pytest.importorskip("hvac")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    with kit.make_harness("vault", tmp_path, monkeypatch) as harness:
        yield harness


def last(vault):
    return vault.server.state.requests[-1]


# -- AT-E3-3: frozen at build -------------------------------------------------------------------


def test_environment_and_files_set_after_build_change_nothing(vault) -> None:
    vault.serve()
    kit.read(vault)
    vault.drift()
    kit.read(vault)
    seen = last(vault)
    assert seen["host"] == vault.expected.endpoint
    assert seen["token"] == TOKEN
    assert seen["authorization"] is None  # ~/.netrc was not read
    assert vault.observed().ca_bundle is True  # REQUESTS_CA_BUNDLE was not read at send time
    assert len(vault.server.state.requests) == 2


def test_an_empty_token_sends_no_header_and_reads_no_variable_or_file(
    tmp_path, monkeypatch
) -> None:
    hermetic(monkeypatch, tmp_path / "home")
    (tmp_path / "home" / ".vault-token").write_text("s.from-file")
    monkeypatch.setenv("VAULT_TOKEN", "s.from-env")
    opened: list[str] = []
    real_open = builtins.open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    with FakeVault() as server:
        provider = VaultKV2Provider(hvac.Client(url=server.url, token=""))
        monkeypatch.setattr(builtins, "open", spy)
        ref = parse_ref(f"vault://kv/team/app?version={PINNED}&field=key&encoding=base64")
        with provider.resolve(ref, provider.resolve_context()):
            pass
    assert server.state.requests[-1]["token"] is None
    assert not [path for path in opened if path.endswith(".vault-token")]


def test_a_client_with_no_address_is_refused_at_build() -> None:
    client = SimpleNamespace(url="", token="t", adapter=None)
    with pytest.raises(SecretProviderConfigError) as info:
        VaultKV2Provider(client)
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_a_ca_bundle_set_before_build_is_frozen_as_a_path(tmp_path, monkeypatch) -> None:
    hermetic(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "ca-at-build.pem"))
    with FakeVault() as server:
        provider = VaultKV2Provider(hvac.Client(url=server.url, token=TOKEN))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "ca-later.pem"))
        seen: list[object] = []
        from requests.adapters import HTTPAdapter

        real = HTTPAdapter.send

        def send(adapter, request, **kwargs):
            seen.append(kwargs.get("verify"))
            return real(adapter, request, **kwargs)

        monkeypatch.setattr(HTTPAdapter, "send", send)
        ref = parse_ref(f"vault://kv/team/app?version={PINNED}&field=key&encoding=base64")
        with provider.resolve(ref, provider.resolve_context()):
            pass
    assert seen == [str(tmp_path / "ca-at-build.pem")]


# -- AT-E3-4: proxies ---------------------------------------------------------------------------

BEHIND_PROXY = "http://vault.internal.test:8200"


def _read_through(provider) -> None:
    ref = parse_ref(f"vault://kv/team/app?version={PINNED}&field=key&encoding=base64")
    with provider.resolve(ref, provider.resolve_context()):
        pass


def test_a_proxy_in_the_environment_at_build_is_used_by_the_read(tmp_path, monkeypatch) -> None:
    hermetic(monkeypatch, tmp_path / "home")
    with FakeVault() as proxy:
        monkeypatch.setenv("HTTP_PROXY", proxy.url)
        provider = VaultKV2Provider(hvac.Client(url=BEHIND_PROXY, token=TOKEN))
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # changed after build: ignored
        _read_through(provider)
    seen = proxy.state.requests[-1]
    assert seen["host"] == "vault.internal.test:8200" and seen["token"] == TOKEN


def test_a_client_built_with_proxies_uses_those_not_the_environment(tmp_path, monkeypatch) -> None:
    hermetic(monkeypatch, tmp_path / "home")
    with FakeVault() as environment, FakeVault() as explicit:
        monkeypatch.setenv("HTTP_PROXY", environment.url)
        client = hvac.Client(url=BEHIND_PROXY, token=TOKEN, proxies={"http": explicit.url})
        _read_through(VaultKV2Provider(client))
    assert explicit.state.requests and not environment.state.requests


# -- AT-E3-5: value-free failures ---------------------------------------------------------------


def _without_field() -> dict:
    payload = body()
    payload["data"]["data"] = {"other": KEY_B64}
    return payload


def _destroyed() -> dict:
    payload = body()
    payload["data"]["metadata"]["destroyed"] = True
    return payload


CASES = {
    "lease": (body(lease_id="database/creds/x/abc"), "secret_lease_unsupported"),
    "destroyed": (_destroyed(), "secret_version_unavailable"),
    "version_mismatch": (body(version=PINNED + 1), "secret_version_unavailable"),
    "missing_field": (_without_field(), "secret_provider_unavailable"),
    "empty_field": (body(value=""), "secret_material_invalid"),
    "bad_timestamp": (body(deletion_time="not-a-time"), "secret_provider_unavailable"),
    "no_data": ({"request_id": KEY_B64}, "secret_provider_unavailable"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_bad_payload_gives_its_code_and_leaks_nothing(vault, case) -> None:
    payload, code = CASES[case]
    vault.server.state.payload = payload
    exc = kit.refused(vault)
    assert exc.code == code
    assert exc.__cause__ is None and exc.__context__ is None
    kit.assert_clean(vault, kit._surfaces(exc))


# -- AT-E3-6: DEBUG logging ---------------------------------------------------------------------


def test_debug_logging_shows_no_secret_or_token_on_success_and_on_403(vault) -> None:
    kit.check_sr2_debug_logging_shows_no_secret(vault)
    vault.inject("secret_access_denied")
    with kit.debug_capture() as logs:
        kit.refused(vault)
    text = "".join(logs.text)
    assert VENDOR_TEXT not in text and TOKEN not in text and KEY_B64 not in text


# -- AT-E3-8: ~/.vault-token --------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    hermetic(monkeypatch, tmp_path / "home")
    return tmp_path / "home"


ENV = {"VAULT_ADDR": "https://v.example:8200"}


def test_the_token_file_is_read_once_and_stripped(home, monkeypatch) -> None:
    (home / ".vault-token").write_text("  s.filetoken \n")
    calls = []
    real = hvac.utils.get_token_from_env
    monkeypatch.setattr(hvac.utils, "get_token_from_env", lambda: calls.append(1) or real())
    client = client_from_env(ENV)
    assert client.token == "s.filetoken"
    assert calls == [1]


def test_an_empty_token_file_is_an_empty_token(home) -> None:
    (home / ".vault-token").write_text("\n")
    assert client_from_env(ENV).token == ""


def test_a_missing_token_file_is_an_empty_token(home) -> None:
    assert client_from_env(ENV).token == ""


def test_vault_token_wins_and_the_file_is_not_read(home, monkeypatch) -> None:
    (home / ".vault-token").write_text("s.filetoken")
    calls = []
    monkeypatch.setattr(hvac.utils, "get_token_from_env", lambda: calls.append(1))
    assert client_from_env({**ENV, "VAULT_TOKEN": "s.envtoken"}).token == "s.envtoken"
    assert calls == []


def test_the_token_file_is_not_opened_at_resolve(home, monkeypatch) -> None:
    (home / ".vault-token").write_text(TOKEN)
    calls = []
    real = hvac.utils.get_token_from_env
    monkeypatch.setattr(hvac.utils, "get_token_from_env", lambda: calls.append(1) or real())
    with FakeVault() as server:
        provider = VaultKV2Provider(client_from_env({"VAULT_ADDR": server.url}))
        built = len(calls)
        _read_through(provider)
        _read_through(provider)
    assert built == 1 and len(calls) == 1
    assert server.state.requests[-1]["token"] == TOKEN


def test_an_unreadable_token_file_is_a_fixed_refusal(home, monkeypatch) -> None:
    (home / ".vault-token").write_text(TOKEN)
    real_open = builtins.open

    def denied(file, *args, **kwargs):
        if str(file).endswith(".vault-token"):
            raise PermissionError(f"{file}: {TOKEN}")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", denied)
    _assert_fixed_refusal()


def test_a_token_file_that_is_not_utf8_is_a_fixed_refusal(home) -> None:
    (home / ".vault-token").write_bytes(b"\xff\xfe\x80s.token")
    _assert_fixed_refusal()


def _assert_fixed_refusal() -> None:
    with pytest.raises(VaultClientConfigError) as info:
        client_from_env(ENV)
    exc = info.value
    assert exc.__cause__ is None and exc.__context__ is None
    assert TOKEN not in str(exc) + repr(exc) and "/" not in str(exc)


def _entries() -> list[dict]:
    path = Path(__file__).parents[2] / "sentry" / "file_access_modules.toml"
    entries = toml_reader.loads(path.read_text(encoding="utf-8"))["operator_environment"]
    return [e for e in entries if e["module"].endswith("secret_providers/vault.py")]


def test_both_new_reads_are_declared_and_the_file_access_sentry_passes() -> None:
    from tests.sentry.test_file_access_boundary import (
        test_operator_environment_exceptions_are_current,
    )

    declared = {(e["function"], e.get("resolved_by")) for e in _entries()}
    assert ("client_from_env", "hvac") in declared  # ~/.vault-token
    assert ("_connect", "hvac") in declared  # REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE
    test_operator_environment_exceptions_are_current()


@pytest.mark.parametrize("function", ["client_from_env", "_connect"])
def test_a_renamed_function_makes_the_file_access_sentry_red(function, monkeypatch) -> None:
    from tests.sentry import test_file_access_boundary as boundary
    from tests.sentry.fa.rules import toml_reader

    real = toml_reader.loads

    def renamed(text):
        data = real(text)
        for entry in data["operator_environment"]:
            if entry["module"].endswith("vault.py") and entry.get("resolved_by") == "hvac":
                if entry["function"] == function:
                    entry["function"] = function + "_renamed"
        return data

    monkeypatch.setattr(toml_reader, "loads", renamed)
    with pytest.raises(AssertionError):
        boundary.test_operator_environment_exceptions_are_current()
