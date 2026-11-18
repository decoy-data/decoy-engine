"""AWS Secrets Manager adapter (F13 row 83, E1): real SDK request shapes under moto, stubbed
clients for failure paths, and the construction-time freezing of endpoint, credentials and CA
bundle. Hermetic: no ambient AWS configuration reaches a test."""

from __future__ import annotations

import base64
import copy
import dataclasses
import json
import logging
import os
import pickle
import traceback
import types

import pytest

boto3 = pytest.importorskip("boto3")
botocore_exceptions = pytest.importorskip("botocore.exceptions")
moto = pytest.importorskip("moto")

from decoy_engine import run_mask_pipeline_chunked  # noqa: E402
from decoy_engine.keyprovider import MaskSecretError  # noqa: E402
from decoy_engine.secret_providers import (  # noqa: E402
    MASK_ROOT_V1,
    REQUIREMENTS,
    SecretCachePolicy,
    SecretProviderConfigError,
    aws,
    parse_ref,
)
from decoy_engine.secret_providers._errors import error_for, failure_of  # noqa: E402
from tests._declared_schema import chunked_entry_kwargs  # noqa: E402
from tests.secret_providers._helpers import ENGINE_VERSION, keyed_config, one_chunk  # noqa: E402

SENTINEL = "F13-AWS-SENTINEL-0123456789abcdef"
KEY_BYTES = b"k" * 40
KEY_B64 = base64.b64encode(KEY_BYTES).decode()
REQ = (REQUIREMENTS[MASK_ROOT_V1],)
UUID = "0123abcd-0123-4abc-8abc-0123456789ab"
REGION = "us-east-1"


def ref_of(version: str = UUID, region: str = REGION) -> object:
    return parse_ref(f"aws-sm://{region}/team/app?version={version}&field=key&encoding=base64")


@pytest.fixture(autouse=True)
def hermetic_aws(tmp_path, monkeypatch):
    """No ambient AWS state: empty config files, no metadata service, fixed fake credentials."""
    for name in [n for n in os.environ if n.startswith("AWS_")]:
        monkeypatch.delenv(name)
    config = tmp_path / "aws-config"
    credentials = tmp_path / "aws-credentials"
    config.write_text("")
    credentials.write_text("")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFAKEFAKEFAKEFAKE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret-key-" + SENTINEL)
    return types.SimpleNamespace(config=config, credentials=credentials)


class StubClient:
    def __init__(self, result=None, raises=None):
        self.calls, self.closed = [], 0
        self._result, self._raises = result, raises

    def get_secret_value(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._result

    def close(self):
        self.closed += 1


def stubbed(monkeypatch, client):
    monkeypatch.setattr(aws, "_read_client", lambda context, region: client)


def response(*, version=UUID, secret_string=None, **extra):
    body = {"VersionId": version, "SecretString": json.dumps({"key": KEY_B64})}
    if secret_string is not None:
        body["SecretString"] = secret_string
    body.update(extra)
    return body


def provider():
    return aws.aws_provider_from_env()


def resolve(client, monkeypatch, ref=None):
    stubbed(monkeypatch, client)
    prov = provider()
    return prov.resolve(ref or ref_of(), prov.resolve_context())


def render(exc: BaseException) -> str:
    return "".join(traceback.TracebackException.from_exception(exc, capture_locals=True).format())


def refused(client, monkeypatch, ref=None) -> MaskSecretError:
    with pytest.raises(MaskSecretError) as info:
        resolve(client, monkeypatch, ref)
    assert info.value.__cause__ is None and info.value.__context__ is None
    return info.value


def client_error(code, message=SENTINEL):
    return botocore_exceptions.ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"RequestId": SENTINEL, "HTTPStatusCode": 400},
        },
        "GetSecretValue",
    )


# -- AT-2: real SDK shapes under moto, same output as the same key from env ------------------


def _output(cfg, registry):
    kw = chunked_entry_kwargs(run_mask_pipeline_chunked, cfg, "t")
    chunks = run_mask_pipeline_chunked(
        cfg, [one_chunk()], table="t", engine_version=ENGINE_VERSION, **kw
    )
    return [c.to_pydict() for c in chunks]


def test_aws_ref_masks_exactly_like_the_same_bytes_from_env(tmp_path, registry, monkeypatch):
    with moto.mock_aws():
        client = boto3.client("secretsmanager", region_name=REGION)
        created = client.create_secret(Name="team/app", SecretString=json.dumps({"key": KEY_B64}))
        version = created["VersionId"]
        registry.register(provider())
        ref = f"aws-sm://{REGION}/team/app?version={version}&field=key&encoding=base64"
        via_aws = _output(keyed_config(tmp_path, mask_secret_ref=ref), registry)
    monkeypatch.setenv("F13_AWS_KEY", KEY_B64)
    same = f"env:F13_AWS_KEY?encoding=base64&key_version=v{version}"
    via_env = _output(keyed_config(tmp_path, mask_secret_ref=same), registry)
    plain = _output(
        keyed_config(tmp_path, mask_secret_ref="env:F13_AWS_KEY?encoding=base64"), registry
    )
    assert via_aws == via_env
    assert plain != via_aws  # the key version label is part of the derived key


def test_describe_makes_no_call_and_labels_with_the_version_id(monkeypatch):
    client = StubClient(response())
    stubbed(monkeypatch, client)
    descriptor = provider().describe(ref_of())
    assert descriptor.key_version == f"v{UUID}" and descriptor.renewable is False
    assert client.calls == []


def test_one_round_trip_for_the_pinned_version(monkeypatch):
    client = StubClient(response())
    stubbed(monkeypatch, client)
    prov = provider()
    with prov.preflight(ref_of(), REQ, SecretCachePolicy()) as prepared:
        assert len(prepared.mask_key()) == 32
        assert prepared.key_version == f"v{UUID}"
    assert client.calls == [{"SecretId": "team/app", "VersionId": UUID}]
    assert client.closed == 1


# -- AT-3: the response version must be the pinned one ---------------------------------------


@pytest.mark.parametrize("version", ["ffffffff-ffff-4fff-8fff-ffffffffffff", None, ""])
def test_a_response_for_another_version_is_refused(monkeypatch, version):
    body = response()
    if version is None:
        del body["VersionId"]
    else:
        body["VersionId"] = version
    assert refused(StubClient(body), monkeypatch).code == "secret_version_unavailable"


# -- AT-4: material shapes ---------------------------------------------------------------------

MATERIAL_CASES = {
    "binary": {"VersionId": UUID, "SecretBinary": SENTINEL.encode()},
    "plain_text": response(secret_string=SENTINEL),
    "json_array": response(secret_string=json.dumps([SENTINEL])),
    "duplicate_key": response(
        secret_string='{"key": "' + SENTINEL + '", "key": "' + SENTINEL + '2"}'
    ),
    "missing_field": response(secret_string=json.dumps({"other": SENTINEL})),
    "empty_field": response(secret_string=json.dumps({"key": ""})),
    "non_string_field": response(secret_string=json.dumps({"key": 7})),
}


@pytest.mark.parametrize("case", sorted(MATERIAL_CASES))
def test_bad_material_is_refused_without_leaking(monkeypatch, case):
    error = refused(StubClient(MATERIAL_CASES[case]), monkeypatch)
    assert error.code == "secret_material_invalid"
    text = str(error) + repr(error) + render(error)
    assert SENTINEL not in text


def test_the_whole_secret_string_is_never_used_as_the_key(monkeypatch):
    # A JSON object without the named field must not fall back to the raw string.
    body = response(secret_string=json.dumps({"other": KEY_B64}))
    assert refused(StubClient(body), monkeypatch).code == "secret_material_invalid"


# -- AT-5: error map ---------------------------------------------------------------------------

MAP = [
    (client_error("ResourceNotFoundException"), "secret_version_unavailable"),
    (client_error("InvalidParameterException"), "secret_version_unavailable"),
    (client_error("InvalidRequestException"), "secret_version_unavailable"),
    (client_error("AccessDeniedException"), "secret_access_denied"),
    (client_error("DecryptionFailure"), "secret_access_denied"),
    (client_error("UnrecognizedClientException"), "secret_access_denied"),
    (client_error("InvalidSignatureException"), "secret_access_denied"),
    (client_error("ExpiredTokenException"), "secret_access_denied"),
    (client_error("ThrottlingException"), "secret_provider_unavailable"),
    (client_error("InternalServiceError"), "secret_provider_unavailable"),
    (botocore_exceptions.NoCredentialsError(), "secret_provider_unavailable"),
    (
        botocore_exceptions.EndpointConnectionError(endpoint_url=SENTINEL),
        "secret_provider_unavailable",
    ),
    (
        botocore_exceptions.ConnectTimeoutError(endpoint_url=SENTINEL),
        "secret_provider_unavailable",
    ),
    (
        botocore_exceptions.ReadTimeoutError(endpoint_url=SENTINEL),
        "secret_provider_unavailable",
    ),
    (botocore_exceptions.BotoCoreError(), "secret_provider_unavailable"),
    (RuntimeError(SENTINEL), "secret_provider_unavailable"),
]


@pytest.mark.parametrize(
    "exc,code", MAP, ids=[type(e).__name__ + str(i) for i, (e, _) in enumerate(MAP)]
)
def test_every_error_maps_to_its_code_and_leaks_nothing(monkeypatch, caplog, exc, code):
    client = StubClient(raises=exc)
    with caplog.at_level(logging.DEBUG):
        error = refused(client, monkeypatch)
    assert error.code == code
    text = str(error) + repr(error) + render(error) + caplog.text
    assert SENTINEL not in text
    assert client.closed == 1


def test_a_client_error_with_a_hostile_code_is_unavailable(monkeypatch):
    exc = client_error("AccessDeniedException")
    exc.response["Error"]["Code"] = type("Code", (str,), {"__eq__": lambda *_: True})("x")
    assert refused(StubClient(raises=exc), monkeypatch).code == "secret_provider_unavailable"


def test_missing_boto3_raises_unavailable_with_no_chain(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "boto3", None)
    with pytest.raises(MaskSecretError) as info:
        aws._boto3()
    assert info.value.code == "secret_provider_unavailable"
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert info.value.__suppress_context__ is False


# -- AT-6: immutability, no rendering, frozen endpoint / credentials / CA bundle ---------------


def test_provider_and_context_render_no_credential():
    prov = provider()
    context = prov.resolve_context()
    for obj in (prov, context):
        text = repr(obj) + str(obj)
        assert "AKIAFAKE" not in text and SENTINEL not in text
        with pytest.raises(TypeError):
            pickle.dumps(obj)
        with pytest.raises(TypeError):
            copy.copy(obj)
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.verify = False  # type: ignore[misc]
    with pytest.raises(AttributeError):
        prov._context = context  # type: ignore[misc]


def test_construction_probes_with_two_clients_and_closes_both(monkeypatch):
    real = boto3.session.Session.client
    made = []

    def spy(self, service, **kwargs):
        client = real(self, service, **kwargs)
        config = kwargs.get("config")
        record = {
            "region": kwargs.get("region_name"),
            "ignoring": getattr(config, "ignore_configured_endpoint_urls", None),
            "closed": 0,
        }
        real_close = client.close

        def close():
            record["closed"] += 1
            real_close()

        client.close = close
        made.append(record)
        return client

    monkeypatch.setattr(boto3.session.Session, "client", spy)
    provider()
    assert [(m["region"], m["ignoring"], m["closed"]) for m in made] == [
        ("us-east-1", None, 1),
        ("us-east-1", True, 1),
    ]


def _client_endpoint(context, region):
    return aws._read_client(context, region).meta.endpoint_url


def test_configured_global_endpoint_is_frozen_and_honored(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://global.example.test")
    context = provider().resolve_context()
    assert context.endpoint_url == "https://global.example.test"
    assert _client_endpoint(context, "eu-west-1") == "https://global.example.test"


def test_configured_service_endpoint_is_frozen_and_honored(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL_SECRETS_MANAGER", "https://sm.example.test")
    context = provider().resolve_context()
    assert context.endpoint_url == "https://sm.example.test"


def test_configured_profile_endpoint_is_frozen_and_honored(hermetic_aws, monkeypatch):
    hermetic_aws.config.write_text("[profile p]\nendpoint_url = https://profile.example.test\n")
    monkeypatch.setenv("AWS_PROFILE", "p")
    context = provider().resolve_context()
    assert context.endpoint_url == "https://profile.example.test"


def test_no_configured_endpoint_freezes_none_and_uses_the_ref_region():
    context = provider().resolve_context()
    assert context.endpoint_url is None
    assert (
        _client_endpoint(context, "eu-west-1") == "https://secretsmanager.eu-west-1.amazonaws.com"
    )
    assert (
        _client_endpoint(context, "us-east-1") == "https://secretsmanager.us-east-1.amazonaws.com"
    )


def test_endpoint_set_after_construction_changes_nothing(monkeypatch):
    context = provider().resolve_context()
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://late.example.test")
    monkeypatch.setenv("AWS_ENDPOINT_URL_SECRETS_MANAGER", "https://late-sm.example.test")
    assert _client_endpoint(context, REGION) == "https://secretsmanager.us-east-1.amazonaws.com"


def test_an_explicit_endpoint_wins_over_the_configured_one(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://global.example.test")
    context = aws.aws_provider_from_env(
        endpoint_url="https://explicit.example.test"
    ).resolve_context()
    assert context.endpoint_url == "https://explicit.example.test"


def _spy_session_client(monkeypatch):
    seen = {}
    real = boto3.session.Session.client

    def spy(self, service, **kwargs):
        seen.update(kwargs)
        seen["key"] = self.get_credentials().access_key
        return real(self, service, **kwargs)

    monkeypatch.setattr(boto3.session.Session, "client", spy)
    return seen


def test_ca_bundle_is_resolved_once_and_passed_explicitly(tmp_path, monkeypatch):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("")
    monkeypatch.setenv("AWS_CA_BUNDLE", str(bundle))
    context = provider().resolve_context()
    assert context.verify == str(bundle)
    monkeypatch.setenv("AWS_CA_BUNDLE", str(tmp_path / "other.pem"))
    seen = _spy_session_client(monkeypatch)
    try:
        aws._read_client(context, REGION)
    except Exception:
        pass
    assert seen["verify"] == str(bundle)


def test_default_verify_is_true_and_passed_explicitly(monkeypatch):
    context = provider().resolve_context()
    assert context.verify is True
    seen = _spy_session_client(monkeypatch)
    aws._read_client(context, REGION)
    assert seen["verify"] is True


def test_credentials_are_frozen_at_construction(monkeypatch):
    context = provider().resolve_context()
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIALATERLATERLATER00")
    seen = _spy_session_client(monkeypatch)
    aws._read_client(context, REGION)
    assert seen["key"] == "AKIAFAKEFAKEFAKEFAKE"


def test_read_client_ignores_configured_endpoints_by_construction(monkeypatch):
    context = provider().resolve_context()
    seen = _spy_session_client(monkeypatch)
    aws._read_client(context, REGION)
    assert seen["config"].ignore_configured_endpoint_urls is True


# -- AT-7: coded config error --------------------------------------------------------------------


def test_config_error_is_coded_exported_and_round_trips():
    error = SecretProviderConfigError("fixed text")
    assert str(error) == "fixed text" and error.message == "fixed text"
    assert error.code == "secret_provider_unconfigured"
    assert repr(error) == "SecretProviderConfigError(code='secret_provider_unconfigured')"
    from decoy_engine.secret_providers import SecretProviderError

    assert isinstance(error, SecretProviderError)
    rebuilt = error_for(failure_of(error))
    assert type(rebuilt) is SecretProviderConfigError
    assert rebuilt.code == "secret_provider_unconfigured"
    assert str(rebuilt) == "The secret provider's client settings are missing or unsafe."


def test_vault_config_error_is_a_subclass_with_unchanged_text():
    pytest.importorskip("hvac")
    from decoy_engine.secret_providers.vault import VaultClientConfigError, client_from_env

    assert issubclass(VaultClientConfigError, SecretProviderConfigError)
    with pytest.raises(VaultClientConfigError) as info:
        client_from_env({})
    assert str(info.value) == "VAULT_ADDR is required to build a Vault client."
    assert failure_of(info.value)[0] == "secret_provider_unconfigured"


def test_no_credential_is_a_config_error(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY")
    with pytest.raises(SecretProviderConfigError) as info:
        aws.aws_provider_from_env()
    assert info.value.code == "secret_provider_unconfigured"
    assert info.value.__cause__ is None and info.value.__context__ is None


# -- AT-14 (engine half): the factory leaks nothing ----------------------------------------------


def _config_failure(monkeypatch, hermetic_aws, kind):
    import botocore.session

    if kind == "profile":
        monkeypatch.setenv("AWS_PROFILE", SENTINEL)
    elif kind == "credential_retrieval":

        def boom(self):
            raise botocore_exceptions.CredentialRetrievalError(provider="p", error_msg=SENTINEL)

        monkeypatch.setattr(botocore.session.Session, "get_credentials", boom)
    elif kind == "assume_role":

        def boom(self):
            raise client_error("AccessDenied", SENTINEL)

        monkeypatch.setattr(botocore.session.Session, "get_credentials", boom)
    elif kind == "unreadable_config":
        import configparser

        # configparser.read swallows an unreadable file itself, so the failure is injected where
        # botocore parses; the factory must still map an OSError to the fixed error.
        def deny(*_a, **_k):
            raise PermissionError(SENTINEL)

        monkeypatch.setattr(configparser.RawConfigParser, "read", deny)
        hermetic_aws.config.write_text("[default]\nregion = us-east-1\n")
    elif kind == "mfa_unattended":
        hermetic_aws.config.write_text(f"[default]\nmfa_serial = arn:aws:iam::1:mfa/{SENTINEL}\n")
        monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: False))
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    ["profile", "credential_retrieval", "assume_role", "unreadable_config", "mfa_unattended"],
)
def test_factory_failures_are_one_fixed_error_with_no_chain(monkeypatch, hermetic_aws, kind):
    _config_failure(monkeypatch, hermetic_aws, kind)
    with pytest.raises(SecretProviderConfigError) as info:
        aws.aws_provider_from_env()
    error = info.value
    assert error.code == "secret_provider_unconfigured"
    assert error.__cause__ is None and error.__context__ is None
    assert SENTINEL not in str(error) + repr(error) + render(error)


def test_admission_through_preflight_maps_a_failed_read(monkeypatch):
    stubbed(monkeypatch, StubClient(raises=client_error("AccessDeniedException")))
    with pytest.raises(MaskSecretError) as info:
        provider().preflight(ref_of(), REQ, SecretCachePolicy())
    assert info.value.code == "secret_access_denied"
    assert SENTINEL not in str(info.value) + render(info.value)
