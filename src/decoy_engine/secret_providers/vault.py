"""HashiCorp Vault KV v2 adapter for the ``secret-provider/v1`` contract (optional extra).

Pattern sources: the Vault KV v2 read API (``GET /:mount/data/:path?version=N`` returns data and
version metadata in ONE response) and the ``hvac`` client's ``read_secret_version``. The adapter
takes a caller-built, already-authenticated client: authentication, namespace selection and
authorization (F45) belong to the caller. ``hvac`` is imported lazily and is never a base
dependency (``pip install decoy-engine[hashicorp-vault]``).

Contract notes:
  * ``describe`` makes no provider call; ``resolve`` is the single round trip (data + metadata
    together), and the returned version must equal the pinned version.
  * Static KV v2 values only. A response carrying a lease id, a renewable flag, a lease duration,
    wrap info or auth data is a dynamic/leased secret and fails ``secret_lease_unsupported``.
  * The provider is IMMUTABLE. Construction copies the client's address, namespace, token and TLS
    settings into one frozen ``VaultContext`` and keeps no reference to the client. The engine
    derives the cache key from that context and hands the same object to ``resolve``, which reads
    through a transport built from it, so a shared client re-pointed mid-load (another tenant, a
    renewed token) can neither change the read nor have its secret cached under this key. To
    change tenant or token, build a new provider.
  * Frozen at build (F13 shared rules, SR-3): address, token (even an empty one), namespace, CA
    bundle path, client certificate and proxies are resolved once. The read runs on a
    ``requests.Session`` with ``trust_env`` off, so ``REQUESTS_CA_BUNDLE``, proxy variables,
    ``~/.netrc`` and ``VAULT_TOKEN`` set after build change nothing. Build the provider per run.
  * Every SDK/transport failure is mapped to a fixed registered reason by exception TYPE; vendor
    text, paths and response bodies never leave this module. Every mapped error is raised after
    its ``except`` block has closed, with the payload deleted from the frame first.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from decoy_engine._opaque import OpaqueBox
from decoy_engine.internal.env_flags import env_flag
from decoy_engine.secret_providers._buffer import SecretBuffer
from decoy_engine.secret_providers._errors import (
    SecretAccessDenied,
    SecretExpired,
    SecretLeaseUnsupported,
    SecretMaterialInvalid,
    SecretProviderConfigError,
    SecretProviderUnavailable,
    SecretVersionUnavailable,
)
from decoy_engine.secret_providers._types import (
    API_VERSION,
    PreparedSecret,
    ResolveContext,
    ResolvedSecret,
    SecretCachePolicy,
    SecretDescriptor,
    SecretRef,
    SystemClock,
)

_SKIP_VERIFY_ENV = "VAULT_SKIP_VERIFY"


class VaultClientConfigError(SecretProviderConfigError):
    """The Vault client could not be built safely from the environment (fixed, value-free text)."""


def _hvac() -> Any:
    missing = False
    try:
        import hvac
    except ImportError:
        missing = True
    if missing:
        raise SecretProviderUnavailable
    return hvac


def _requests() -> Any:
    missing = False
    try:
        import requests
    except ImportError:
        missing = True
    if missing:
        raise SecretProviderUnavailable
    return requests


def _no_token() -> str:
    return ""


def _home_token_file() -> tuple[Callable[[], str], bool]:
    """``(reader, failed)`` for ``~/.vault-token``, the file ``vault login`` writes.

    hvac opens it (a library read, declared in ``file_access_modules.toml``). hvac checks the
    process ``VAULT_TOKEN`` first, so a process token is never taken for the file's: when the
    process has one this reads nothing. A missing or empty file is an empty token. The text is
    held by the returned closure, not by a frame local, so a traceback cannot render it.
    """
    if len(os.environ.get("VAULT_TOKEN", "")) > 0:
        return _no_token, False
    hvac = _hvac()
    text = ""
    failed = False
    try:
        text = str(hvac.utils.get_token_from_env() or "").strip()
    except Exception:
        failed = True

    def read() -> str:
        return text

    return (_no_token if failed else read), failed


def client_from_env(
    environ: Mapping[str, str] | None = None, *, insecure_skip_tls_verify: bool = False
) -> Any:
    """Build an ``hvac.Client`` from the standard Vault environment variables.

    Honors ``VAULT_ADDR``, ``VAULT_TOKEN``, ``VAULT_NAMESPACE``, ``VAULT_CACERT``,
    ``VAULT_CLIENT_CERT`` and ``VAULT_CLIENT_KEY``. With ``VAULT_TOKEN`` unset, the token is read
    once from ``~/.vault-token`` as the last step and passed explicitly; an empty or missing file
    is an empty token (no token header, the Vault Agent proxy pattern) and an unreadable one is
    ``VaultClientConfigError``. ``VAULT_SKIP_VERIFY`` set truthy is REJECTED,
    never warned about: disabling TLS verification is an in-code decision
    (``insecure_skip_tls_verify=True``), not an environment toggle that can silently enable a
    man-in-the-middle on a privacy product.
    """
    # The mapping holds VAULT_TOKEN (and, for os.environ, every secret in the process): a refusal's
    # traceback keeps this frame, so it holds only a box (`_opaque`) and the token is read only
    # inside the client call expression.
    box = OpaqueBox(os.environ if environ is None else environ)
    del environ
    if env_flag(_SKIP_VERIFY_ENV, str(box.open()[0].get(_SKIP_VERIFY_ENV, ""))):
        raise VaultClientConfigError(
            "VAULT_SKIP_VERIFY is not honored: disabling TLS verification requires an explicit "
            "in-code override (insecure_skip_tls_verify=True)."
        )
    addr = box.open()[0].get("VAULT_ADDR")
    if not addr:
        raise VaultClientConfigError("VAULT_ADDR is required to build a Vault client.")
    verify: bool | str = (
        False if insecure_skip_tls_verify else (box.open()[0].get("VAULT_CACERT") or True)
    )
    cert_file, key_file = map(box.open()[0].get, ("VAULT_CLIENT_CERT", "VAULT_CLIENT_KEY"))
    if bool(cert_file) != bool(key_file):
        raise VaultClientConfigError("VAULT_CLIENT_CERT and VAULT_CLIENT_KEY must be set together.")
    # Last step, after every other setting is validated. The file token stays inside a closure.
    file_token = _no_token
    file_failed = False
    if not box.open()[0].get("VAULT_TOKEN"):
        file_token, file_failed = _home_token_file()
    if file_failed:
        raise VaultClientConfigError("The Vault token file ~/.vault-token could not be read.")
    return _hvac().Client(
        url=addr,
        token=box.open()[0].get("VAULT_TOKEN") or file_token(),
        namespace=box.open()[0].get("VAULT_NAMESPACE") or None,
        verify=verify,
        cert=(cert_file, key_file) if cert_file and key_file else None,
    )


def _parse_rfc3339(text: str) -> tuple[bool, float | None]:
    """``(ok, seconds)``. Vault timestamps are RFC 3339 with nanoseconds; an empty string means
    'not set'. A bad value is ``ok=False``, returned rather than raised so no handler is open."""
    if not text:
        return True, None
    trimmed = text.rstrip("Z")
    head, _, frac = trimmed.partition(".")
    seconds: float | None = None
    try:
        moment = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        seconds = moment.timestamp() + (float("0." + frac) if frac else 0.0)
    except ValueError:
        seconds = None
    return seconds is not None, seconds


@dataclass(frozen=True, repr=False)
class VaultContext(ResolveContext):
    """Everything one KV v2 read is routed and authenticated with. Never rendered."""

    address: str = ""
    namespace: str = ""
    token: str = ""
    verify: bool | str = True
    cert: tuple[str, ...] | None = None
    # Sorted flat (scheme, url, scheme, url, ...): context_key_parts takes flat values only, and a
    # proxy URL can hold a credential, so the context is never rendered.
    proxies: tuple[str, ...] = ()


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _resolved_verify(verify: bool | str) -> bool | str:
    """``verify=True`` the way ``requests`` resolves it at send time, but once, at build."""
    if verify is not True:
        return verify
    for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        bundle = os.environ.get(name)
        if bundle:
            return bundle
    return True


def _flat_proxies(mapping: Mapping[object, object]) -> tuple[str, ...]:
    return tuple(
        part for pair in sorted((str(k), str(v)) for k, v in mapping.items()) for part in pair
    )


def _context_of(client: Any) -> VaultContext:
    """Copy an ``hvac.Client``'s routing and TLS settings (``Adapter.__init__`` in hvac 2.4 keeps
    namespace on the adapter and ``verify``/``cert``/``proxies`` in ``adapter._kwargs``).

    The proxies are the client's own when the caller set them, else the process environment's for
    this address, so turning ``trust_env`` off at read time breaks no proxied user."""
    adapter = getattr(client, "adapter", None)
    tls = getattr(adapter, "_kwargs", None)
    tls = tls if isinstance(tls, Mapping) else {}
    verify = tls.get("verify", True)
    cert = tls.get("cert")
    if not isinstance(verify, (bool, str)) or verify == "":
        verify = True
    if cert is not None:
        cert = tuple(str(part) for part in (cert if isinstance(cert, (tuple, list)) else (cert,)))
    address = _text(getattr(client, "url", None))
    if not address:
        raise SecretProviderConfigError("The Vault client has no address.")
    caller_proxies = tls.get("proxies")
    proxies = (
        caller_proxies
        if isinstance(caller_proxies, Mapping)
        else _requests().utils.get_environ_proxies(address)
    )
    return VaultContext(
        scheme="vault",
        address=address,
        namespace=_text(getattr(adapter, "namespace", None)),
        token=_text(getattr(client, "token", None)),
        verify=_resolved_verify(verify),
        cert=cert or None,
        proxies=_flat_proxies(proxies),
    )


def _connect(context: VaultContext) -> Any:
    """An hvac client built only from the frozen context, on a session that reads no environment:
    explicit address, token (an empty one sends no token header), verify, cert and proxies."""
    cert: str | tuple[str, ...] | None = context.cert
    if cert is not None and len(cert) not in (1, 2):
        raise SecretProviderUnavailable  # never silently drop client-certificate authentication
    if not context.address:
        raise SecretProviderUnavailable  # hvac would fall back to VAULT_ADDR
    cert_arg: str | tuple[str, ...] = (
        cert[0] if cert is not None and len(cert) == 1 else (cert or ())
    )
    proxies = dict(zip(context.proxies[::2], context.proxies[1::2], strict=True))
    session = _requests().Session()
    session.trust_env = False
    session.verify = context.verify
    session.cert = cert_arg or None
    session.proxies = proxies
    return _hvac().Client(
        url=context.address,
        token=context.token,
        namespace=context.namespace or None,
        verify=context.verify,
        cert=cert_arg,
        proxies=proxies,
        session=session,
    )


class VaultKV2Provider:
    api_version: Literal["secret-provider/v1"] = API_VERSION
    scheme = "vault"

    __slots__ = ("_clock", "_context")
    _clock: Any
    _context: VaultContext

    def __init__(self, client: Any, *, clock: Any | None = None) -> None:
        object.__setattr__(self, "_context", _context_of(client))
        object.__setattr__(self, "_clock", clock or SystemClock())

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("VaultKV2Provider is immutable; build a new provider")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("VaultKV2Provider is immutable; build a new provider")

    def __repr__(self) -> str:
        return "VaultKV2Provider(<redacted>)"

    __str__ = __repr__

    def __reduce_ex__(self, *_: object) -> Any:
        raise TypeError("secret providers cannot be pickled")

    def resolve_context(self) -> VaultContext:
        return self._context

    def describe(self, ref: SecretRef) -> SecretDescriptor:
        # No provider call: the pinned version is part of the reference.
        return SecretDescriptor(scheme=self.scheme, key_version=f"v{ref.version}", renewable=False)

    def resolve(self, ref: SecretRef, context: ResolveContext) -> ResolvedSecret:
        if not isinstance(context, VaultContext):
            raise SecretProviderUnavailable
        mount, _, path = ref.locator.partition("/")
        failure: BaseException | None = None
        resolved: ResolvedSecret | None = None
        response: Any = None
        client = _connect(context)
        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=path, version=int(ref.version or 0), mount_point=mount
            )
        except Exception as exc:
            failure = _map_sdk_error(exc)
        finally:
            _close(client)
        if failure is None:
            resolved, failure = _to_resolved(self._clock, ref, response)
        # A traceback keeps this frame: the response holds every field of the secret.
        del response
        if failure is None and resolved is not None:
            return resolved
        raise failure if failure is not None else SecretProviderUnavailable()

    def preflight(
        self, ref: SecretRef, requirements: tuple[Any, ...], cache_policy: SecretCachePolicy
    ) -> PreparedSecret:
        from decoy_engine.secret_providers._preflight import prepare_secret

        return prepare_secret(
            provider=self, ref=ref, requirements=requirements, cache_policy=cache_policy
        )


def _to_resolved(
    clock: Any, ref: SecretRef, response: Any
) -> tuple[ResolvedSecret | None, BaseException | None]:
    """The resolved secret, or the fixed failure. Returns instead of raising so the caller raises
    outside every handler, with no frame holding the payload."""
    failure: BaseException | None = None
    resolved: ResolvedSecret | None = None
    try:
        resolved, failure = _read_payload(clock, ref, response)
    except (KeyError, TypeError, ValueError, AttributeError):
        failure = SecretProviderUnavailable()
    return resolved, failure


def _read_payload(
    clock: Any, ref: SecretRef, response: Any
) -> tuple[ResolvedSecret | None, BaseException | None]:
    if (
        response.get("lease_id")
        or response.get("renewable")
        or response.get("lease_duration")
        or response.get("wrap_info")
        or response.get("auth")
    ):
        return None, SecretLeaseUnsupported()
    outer = response["data"]
    meta, data = outer["metadata"], outer["data"]
    del outer
    if meta.get("destroyed"):
        return None, SecretVersionUnavailable()
    if int(meta["version"]) != int(ref.version or 0):
        return None, SecretVersionUnavailable()
    expiry_ok, expires_at = _parse_rfc3339(str(meta.get("deletion_time") or ""))
    if not expiry_ok:
        return None, SecretProviderUnavailable()
    if expires_at is not None and expires_at <= clock.wall():
        return None, SecretExpired()
    created_ok, created_at = _parse_rfc3339(str(meta.get("created_time") or ""))
    if not created_ok:
        return None, SecretProviderUnavailable()
    value = data[ref.field or ""]
    del data
    if not isinstance(value, str) or not value:
        return None, SecretMaterialInvalid()
    resolved = ResolvedSecret(
        SecretBuffer(value.encode("utf-8")),
        key_version=f"v{ref.version}",
        expires_at=expires_at,
        created_at=created_at,
    )
    del value
    return resolved, None


def _close(client: Any) -> None:
    close = getattr(getattr(client, "adapter", None), "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _map_sdk_error(exc: BaseException) -> BaseException:
    """Map a vendor exception to a fixed safe type by CLASS only; its text is never read."""
    hvac = _hvac()
    errors = hvac.exceptions
    if isinstance(exc, (errors.Forbidden, errors.Unauthorized)):
        return SecretAccessDenied()
    if isinstance(exc, errors.InvalidPath):
        return SecretVersionUnavailable()
    return SecretProviderUnavailable()
