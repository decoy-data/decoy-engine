"""AWS Secrets Manager adapter for the ``secret-provider/v1`` contract (``boto3``, optional).

Pattern sources: the Secrets Manager ``GetSecretValue`` API (a pinned ``VersionId`` returns the
version and its ``SecretString`` in ONE response), the boto3 default credential chain, and the
way Terraform's ``aws_secretsmanager_secret_version`` data source and External Secrets Operator
read a pinned version through the vendor SDK. ``boto3`` is imported lazily and is never a base
dependency (``pip install decoy-engine[cloud]``).

Contract notes:
  * ``describe`` makes no provider call; ``resolve`` is the single round trip, and the returned
    ``VersionId`` must equal the pinned one. Stage labels (``AWSCURRENT``) are refused by the
    reference grammar: a rotation is a deliberate config change.
  * V1 reads one field of a JSON ``SecretString`` (the console's key/value form). A binary
    secret, plain text, a non-object, a duplicate key, a missing or empty field is
    ``secret_material_invalid``.
  * The provider is IMMUTABLE. Construction copies the frozen credentials, the configured endpoint
    (if any) and the CA bundle into one ``AwsContext`` and keeps no session or profile name. The
    read builds a fresh client from that context with the SDK's own endpoint configuration
    switched off, so later changes to environment variables, config files or the credential
    source cannot change the read or the cache key.
  * Every SDK failure is mapped to a fixed registered reason by exception TYPE (and, for a
    ``ClientError``, a fixed error-code string); vendor text, ARNs, names and request ids never
    leave this module. Every mapped error is raised after its ``except`` block has closed.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from typing import Any, Literal

from decoy_engine._canonical import strict_json_loads
from decoy_engine.secret_providers._buffer import SecretBuffer
from decoy_engine.secret_providers._errors import (
    SecretAccessDenied,
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
)

# The placeholder region only used to ask the SDK whether an endpoint is configured.
_PROBE_REGION = "us-east-1"
_SERVICE = "secretsmanager"

_NOT_CONFIGURED = (
    "AWS credentials were not found or the AWS client settings are unsafe; "
    "see docs/security/secret-providers.md."
)

_VERSION_CODES = frozenset(
    {"ResourceNotFoundException", "InvalidParameterException", "InvalidRequestException"}
)
_DENIED_CODES = frozenset(
    {
        "AccessDeniedException",
        "DecryptionFailure",
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
    }
)


def _boto3() -> Any:
    missing = False
    try:
        import boto3
    except ImportError:
        missing = True
    if missing:
        raise SecretProviderUnavailable
    return boto3


@dataclass(frozen=True, repr=False)
class AwsContext(ResolveContext):
    """Everything one Secrets Manager read is authenticated and routed with. Never rendered."""

    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    endpoint_url: str | None = None
    verify: bool | str = True


def _configured_endpoint(session: Any, config_type: Any) -> str | None:
    """The endpoint the standard AWS configuration points Secrets Manager at, or ``None``.

    botocore 1.43 does not expose configured endpoints through ``get_config_variable``, so two
    throwaway clients in a placeholder region are compared: a plain one and one that ignores
    configured endpoints. A difference is a configured endpoint (global, service-specific or
    profile) and is the one to honor; equality means the public endpoint, which the read client
    then derives from the reference's real region.
    """
    plain = session.client(_SERVICE, region_name=_PROBE_REGION)
    try:
        ignoring = session.client(
            _SERVICE,
            region_name=_PROBE_REGION,
            config=config_type(ignore_configured_endpoint_urls=True),
        )
        try:
            configured: str = plain.meta.endpoint_url
            public: str = ignoring.meta.endpoint_url
        finally:
            ignoring.close()
    finally:
        plain.close()
    return configured if configured != public else None


def _verify_of(session: Any) -> bool | str:
    """The CA bundle the standard chain selects (``AWS_CA_BUNDLE`` or the profile), else ``True``."""
    botocore_session = getattr(session, "_session", None)
    getter = getattr(botocore_session, "get_config_variable", None)
    bundle = getter("ca_bundle") if callable(getter) else None
    return bundle if isinstance(bundle, str) and bundle else True


def _context_of(session: Any, endpoint_url: str | None) -> AwsContext:
    from botocore.config import Config

    credentials = session.get_credentials()
    if credentials is None:
        raise SecretProviderConfigError(_NOT_CONFIGURED)
    frozen = credentials.get_frozen_credentials()
    if endpoint_url is None:
        endpoint_url = _configured_endpoint(session, Config)
    return AwsContext(
        scheme="aws-sm",
        access_key_id=str(frozen.access_key or ""),
        secret_access_key=str(frozen.secret_key or ""),
        session_token=str(frozen.token or ""),
        endpoint_url=endpoint_url,
        verify=_verify_of(session),
    )


def _read_client(context: AwsContext, region: str) -> Any:
    """A client built only from the frozen context: explicit credentials, endpoint and CA bundle,
    and the SDK's configured-endpoint lookup switched off."""
    boto3 = _boto3()
    from botocore.config import Config

    session = boto3.session.Session(
        aws_access_key_id=context.access_key_id,
        aws_secret_access_key=context.secret_access_key,
        aws_session_token=context.session_token or None,
        region_name=region,
    )
    return session.client(
        _SERVICE,
        region_name=region,
        endpoint_url=context.endpoint_url,
        verify=context.verify,
        config=Config(ignore_configured_endpoint_urls=True),
    )


class AwsSecretsManagerProvider:
    api_version: Literal["secret-provider/v1"] = API_VERSION
    scheme = "aws-sm"

    __slots__ = ("_context",)
    _context: AwsContext

    def __init__(self, session: Any, *, endpoint_url: str | None = None) -> None:
        """``session`` is a ``boto3.session.Session``. ``endpoint_url`` (explicit, so above any
        configured endpoint) is for private endpoints and local test servers."""
        object.__setattr__(self, "_context", _context_of(session, endpoint_url))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AwsSecretsManagerProvider is immutable; build a new provider")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("AwsSecretsManagerProvider is immutable; build a new provider")

    def __repr__(self) -> str:
        return "AwsSecretsManagerProvider(<redacted>)"

    __str__ = __repr__

    def __reduce_ex__(self, *_: object) -> Any:
        raise TypeError("secret providers cannot be pickled")

    def resolve_context(self) -> AwsContext:
        return self._context

    def describe(self, ref: SecretRef) -> SecretDescriptor:
        # No provider call. The label is part of the derived key (HKDF info), so it must be
        # stable for one version id: `v` plus the 36-character UUID.
        return SecretDescriptor(scheme=self.scheme, key_version=f"v{ref.version}", renewable=False)

    def resolve(self, ref: SecretRef, context: ResolveContext) -> ResolvedSecret:
        if not isinstance(context, AwsContext):
            raise SecretProviderUnavailable
        region, _, name = ref.locator.partition("/")
        failure: BaseException | None = None
        resolved: ResolvedSecret | None = None
        response: Any = None
        client: Any = None
        try:
            client = _read_client(context, region)
            response = client.get_secret_value(SecretId=name, VersionId=ref.version)
        except Exception as exc:
            failure = _map_sdk_error(exc)
        finally:
            _close(client)
        if failure is None:
            resolved, failure = _to_resolved(ref, response)
        # A traceback keeps this frame: the response holds the secret text.
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
    ref: SecretRef, response: Any
) -> tuple[ResolvedSecret | None, BaseException | None]:
    """The resolved secret, or the fixed failure. Returns instead of raising so the caller raises
    outside every handler and with no frame holding the payload."""
    version_ok = False
    text: Any = None
    with contextlib.suppress(Exception):
        version_ok = response.get("VersionId") == ref.version
        text = response.get("SecretString")
    if not version_ok:
        return None, SecretVersionUnavailable()
    value: Any = None
    with contextlib.suppress(Exception):
        payload = strict_json_loads(text)
        value = payload.get(ref.field or "") if isinstance(payload, dict) else None
        del payload
    del text
    if not isinstance(value, str) or not value:
        return None, SecretMaterialInvalid()
    resolved = ResolvedSecret(SecretBuffer(value.encode("utf-8")), key_version=f"v{ref.version}")
    del value
    return resolved, None


def _close(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        with contextlib.suppress(Exception):
            close()


def _error_code(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    error = response.get("Error") if isinstance(response, dict) else None
    code = error.get("Code") if isinstance(error, dict) else None
    return code if type(code) is str else None


def _map_sdk_error(exc: BaseException) -> BaseException:
    """Map a vendor exception to a fixed safe type by CLASS and fixed code string only; its text,
    ARN, secret name and request id are never read."""
    from botocore import exceptions as botocore_errors

    if isinstance(exc, botocore_errors.ClientError):
        code = _error_code(exc)
        if code in _VERSION_CODES:
            return SecretVersionUnavailable()
        if code in _DENIED_CODES:
            return SecretAccessDenied()
    return SecretProviderUnavailable()


def _non_interactive() -> bool:
    stdin = sys.stdin
    return stdin is None or not stdin.isatty()


def _refuse_unattended_mfa(botocore_session: Any) -> None:
    # An assume-role profile with `mfa_serial` makes botocore prompt on stdin: an unattended job
    # is refused instead of hanging.
    if botocore_session.get_scoped_config().get("mfa_serial") and _non_interactive():
        raise SecretProviderConfigError(_NOT_CONFIGURED)


def aws_provider_from_env(*, endpoint_url: str | None = None) -> AwsSecretsManagerProvider:
    """Build a provider from the standard AWS credential chain.

    The chain is boto3's own: environment, shared config and credentials files, a named profile,
    web identity, container and instance metadata. Any failure while building it (a missing
    profile, an unreadable config file, no credential, an STS error) is one fixed
    ``SecretProviderConfigError``; the vendor text and exception are not kept.
    """
    boto3 = _boto3()
    provider: AwsSecretsManagerProvider | None = None
    try:
        import botocore.session

        botocore_session = botocore.session.Session()
        session = boto3.session.Session(botocore_session=botocore_session)
        _refuse_unattended_mfa(botocore_session)
        provider = AwsSecretsManagerProvider(session, endpoint_url=endpoint_url)
    except Exception:
        provider = None
    if provider is None:
        raise SecretProviderConfigError(_NOT_CONFIGURED)
    return provider
