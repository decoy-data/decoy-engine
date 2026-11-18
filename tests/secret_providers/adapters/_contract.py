"""Shared adapter contract kit (F13 shared rules SR-1 to SR-5, plan 2026-11-18, slice E3).

An adapter joins by adding a harness class to ``harness_classes()``: it builds the provider
against a hermetic backend, serves a sentinel secret, injects each failure class (keyed by the
registered code it must produce), lists the sentinel strings and declares the facts it freezes at
build. The ``check_*`` functions are the parametrized rules; ``test_contract.py`` runs them for
every harness and ``tests/sentry/defects/test_secret_adapter_kit.py`` fails a provider module
that has no harness.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import logging
import pickle
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar, Protocol

import pytest

from decoy_engine.secret_providers import SecretRef
from decoy_engine.secret_providers._errors import SecretProviderError
from decoy_engine.secret_providers._types import context_key_parts

# The SDK loggers SR-2 puts at DEBUG; "" is the root logger.
SDK_LOGGERS = ("", "urllib3", "requests", "hvac", "botocore", "boto3", "google", "azure", "msal")
MINIMUM_FROZEN = frozenset({"endpoint", "credentials", "ca_bundle"})


@dataclasses.dataclass(frozen=True)
class Observed:
    """What the backend saw on the last read: the facts SR-3 says are frozen at build."""

    endpoint: object
    credential: object
    ca_bundle: object


class ProviderHarness(Protocol):
    """One adapter's hermetic backend. Built per test by ``make_harness``."""

    key: ClassVar[str]
    failure_codes: ClassVar[frozenset[str]]
    frozen: ClassVar[frozenset[str]]
    sentinels: tuple[str, ...]
    provider: Any
    ref: SecretRef
    expected: Observed

    def serve(self) -> None:
        """Answer the next reads with the sentinel secret."""

    def inject(self, code: str) -> None:
        """Make the next reads fail so the provider must answer with ``code``."""

    def mismatch_version(self) -> None:
        """Answer the next reads with a version other than the pinned one."""

    def drift(self) -> None:
        """Change every environment variable and file the SDK could read after build."""

    def observed(self) -> Observed: ...

    def reads(self) -> int:
        """Provider reads made so far."""

    def close(self) -> None: ...


HarnessFactory = Callable[..., ProviderHarness]


def harness_classes() -> dict[str, HarnessFactory]:
    from tests.secret_providers.adapters import _harness_aws, _harness_vault

    return {
        _harness_vault.VaultHarness.key: _harness_vault.VaultHarness,
        _harness_aws.AwsHarness.key: _harness_aws.AwsHarness,
    }


@contextlib.contextmanager
def make_harness(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, proxies: bool = False
) -> Iterator[ProviderHarness]:
    harness = harness_classes()[key](tmp_path, monkeypatch, proxies=proxies)
    try:
        yield harness
    finally:
        harness.close()


def read(h: ProviderHarness) -> bytes:
    """One provider read, as the engine makes it (the frozen context goes back in)."""
    with h.provider.resolve(h.ref, h.provider.resolve_context()) as resolved:
        return bytes(resolved.buffer.view())


def refused(h: ProviderHarness) -> SecretProviderError:
    with pytest.raises(SecretProviderError) as info:
        read(h)
    return info.value


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.text: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = repr(record.msg) + repr(record.args)
        self.text.append(message + repr(record.__dict__))


@contextlib.contextmanager
def debug_capture() -> Iterator[_Capture]:
    """Every SDK logger at DEBUG and propagating, one handler on the root that renders the
    message and the whole ``record.__dict__`` (so ``extra=`` payloads show)."""
    handler = _Capture()
    saved = []
    for name in SDK_LOGGERS:
        log = logging.getLogger(name)
        saved.append((log, log.level, log.propagate, log.disabled))
        log.setLevel(logging.DEBUG)
        log.propagate = True
        log.disabled = False
    logging.getLogger().addHandler(handler)
    try:
        yield handler
    finally:
        logging.getLogger().removeHandler(handler)
        for log, level, propagate, disabled in saved:
            log.setLevel(level)
            log.propagate = propagate
            log.disabled = disabled


def _surfaces(exc: BaseException) -> str:
    rendered = traceback.TracebackException.from_exception(exc, capture_locals=True)
    return "".join(
        [str(exc), repr(exc), "".join(traceback.format_exception(exc)), "".join(rendered.format())]
    )


def assert_clean(h: ProviderHarness, text: str) -> None:
    for sentinel in h.sentinels:
        assert sentinel not in text, "a sentinel reached an output surface"


# -- SR-1: value-free errors --------------------------------------------------------------------


def check_sr1_failures_are_value_free(h: ProviderHarness) -> None:
    assert h.failure_codes, "a harness injects at least one failure"
    for code in sorted(h.failure_codes):
        h.inject(code)
        with debug_capture() as logs:
            exc = refused(h)
        assert exc.code == code
        assert exc.__cause__ is None and exc.__context__ is None
        assert_clean(h, _surfaces(exc))
        assert_clean(h, "".join(logs.text))
        h.serve()
    assert read(h)  # positive control: serving again works after every injected failure


# -- SR-2: SDK DEBUG logging --------------------------------------------------------------------


def check_sr2_debug_logging_shows_no_secret(h: ProviderHarness) -> None:
    h.serve()
    with debug_capture() as logs:
        assert read(h)
    assert logs.text, "positive control: the SDK logs at DEBUG"
    assert_clean(h, "".join(logs.text))
    h.inject("secret_access_denied")
    with debug_capture() as logs:
        refused(h)
    assert_clean(h, "".join(logs.text))


# -- SR-3: frozen at build ----------------------------------------------------------------------


def check_sr3_values_are_frozen_at_build(h: ProviderHarness) -> None:
    assert h.frozen >= MINIMUM_FROZEN
    h.serve()
    first = read(h)
    before = h.observed()
    assert before == h.expected, (before, h.expected)  # the backend saw what the build resolved
    h.drift()
    second = read(h)
    assert second == first
    assert h.observed() == before


def check_sr3_context_has_flat_values(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_harness(key, tmp_path, monkeypatch, proxies=True) as h:
        # The parts feed a salted HMAC (the cache key), so they may hold the frozen values.
        assert context_key_parts(h.provider.resolve_context(), key)


# -- SR-4: never rendered -----------------------------------------------------------------------


def check_sr4_never_rendered(h: ProviderHarness) -> None:
    context = h.provider.resolve_context()
    surfaces = "".join(
        [repr(h.provider), str(h.provider), repr(context), str(context), f"{context}"]
    )
    assert_clean(h, surfaces)
    for blocked in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            blocked(h.provider)
    with pytest.raises(TypeError):
        pickle.dumps(context)
    with pytest.raises(AttributeError):
        h.provider.anything = 1
    with pytest.raises(AttributeError):
        del h.provider._context
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.scheme = "other"


# -- SR-5: pinned version -----------------------------------------------------------------------


def check_sr5_pinned_version(h: ProviderHarness) -> None:
    h.serve()
    before = h.reads()
    descriptor = h.provider.describe(h.ref)
    assert h.reads() == before, "describe makes no call"
    assert descriptor.key_version == f"v{h.ref.version}" and descriptor.renewable is False
    h.mismatch_version()
    assert refused(h).code == "secret_version_unavailable"
    h.serve()
    with h.provider.resolve(h.ref, h.provider.resolve_context()) as resolved:
        assert resolved.key_version == descriptor.key_version
