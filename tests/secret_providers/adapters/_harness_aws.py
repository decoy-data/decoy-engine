"""AWS Secrets Manager harness for the adapter contract kit: the real boto3 client under moto for
the success path, and a stubbed client for injected failures (as ``test_aws_adapter.py`` does)."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, ClassVar

import pytest

from decoy_engine.secret_providers import aws, parse_ref
from tests.secret_providers.adapters._contract import Observed

SENTINEL = "F13-AWS-SENTINEL-0123456789abcdef"
KEY_B64 = base64.b64encode(b"a" * 40).decode()
SECRET_KEY = "fake-secret-key-" + SENTINEL
ACCESS_KEY = "AKIAFAKEFAKEFAKEFAKE"
REGION = "us-east-1"
OTHER_VERSION = "ffffffff-ffff-4fff-8fff-ffffffffffff"


class _Stub:
    def __init__(self, result: Any = None, raises: BaseException | None = None) -> None:
        self._result, self._raises = result, raises

    def get_secret_value(self, **_: Any) -> Any:
        if self._raises is not None:
            raise self._raises
        return self._result

    def close(self) -> None:
        return None


class AwsHarness:
    key: ClassVar[str] = "aws-sm"
    failure_codes: ClassVar[frozenset[str]] = frozenset(
        {
            "secret_access_denied",
            "secret_version_unavailable",
            "secret_provider_unavailable",
            "secret_material_invalid",
        }
    )
    frozen: ClassVar[frozenset[str]] = frozenset({"endpoint", "credentials", "ca_bundle"})

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, proxies: bool = False
    ) -> None:
        self._boto3 = pytest.importorskip("boto3")
        self._errors = pytest.importorskip("botocore.exceptions")
        moto = pytest.importorskip("moto")
        self._monkeypatch = monkeypatch
        self._tmp = tmp_path
        for name in [n for n in os.environ if n.startswith("AWS_")]:
            monkeypatch.delenv(name)
        for name, value in {
            "AWS_CONFIG_FILE": tmp_path / "aws-config",
            "AWS_SHARED_CREDENTIALS_FILE": tmp_path / "aws-credentials",
        }.items():
            value.write_text("")
            monkeypatch.setenv(name, str(value))
        monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS_KEY)
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
        if proxies:
            monkeypatch.setenv("HTTPS_PROXY", "http://proxy-user:proxy-pass@127.0.0.1:9")
        self._moto = moto.mock_aws()
        self._moto.start()
        client = self._boto3.client("secretsmanager", region_name=REGION)
        created = client.create_secret(Name="team/app", SecretString=json.dumps({"key": KEY_B64}))
        self._version = created["VersionId"]
        # moto replaced the credential variables with its own while it started.
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS_KEY)
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
        self.sentinels = (
            SENTINEL,
            KEY_B64,
            base64.b64encode(KEY_B64.encode()).decode(),
            SECRET_KEY,
            "proxy-pass",
        )
        self.ref = parse_ref(
            f"aws-sm://{REGION}/team/app?version={self._version}&field=key&encoding=base64"
        )
        self._reads = 0
        self._seen: list[Observed] = []
        self._real_read_client = aws._read_client
        self.provider = aws.aws_provider_from_env()
        self.expected = Observed(
            endpoint=f"https://secretsmanager.{REGION}.amazonaws.com",
            credential=ACCESS_KEY,
            ca_bundle=True,
        )
        self.serve()

    def _recording_client(self, context: Any, region: str) -> Any:
        client = self._real_read_client(context, region)
        signer = getattr(client, "_request_signer", None)
        http = getattr(getattr(client, "_endpoint", None), "http_session", None)
        self._seen.append(
            Observed(
                endpoint=client.meta.endpoint_url,
                credential=getattr(getattr(signer, "_credentials", None), "access_key", None),
                ca_bundle=getattr(http, "_verify", None),
            )
        )
        return client

    def _use(self, client_factory: Any) -> None:
        def counted(context: Any, region: str) -> Any:
            self._reads += 1
            return client_factory(context, region)

        self._monkeypatch.setattr(aws, "_read_client", counted)

    def _stubbed(self, stub: _Stub) -> None:
        self._use(lambda context, region: stub)

    def _good_body(self, **extra: Any) -> dict[str, Any]:
        out = {"VersionId": self._version, "SecretString": json.dumps({"key": KEY_B64})}
        out.update(extra)
        return out

    def serve(self) -> None:
        self._use(self._recording_client)

    def inject(self, code: str) -> None:
        client_error = self._errors.ClientError(
            {
                "Error": {"Code": "AccessDeniedException", "Message": SENTINEL},
                "ResponseMetadata": {"RequestId": SENTINEL, "HTTPStatusCode": 400},
            },
            "GetSecretValue",
        )
        if code == "secret_access_denied":
            self._stubbed(_Stub(raises=client_error))
        elif code == "secret_version_unavailable":
            self._stubbed(_Stub(self._good_body(VersionId=OTHER_VERSION)))
        elif code == "secret_provider_unavailable":
            self._stubbed(_Stub(raises=RuntimeError(SENTINEL)))
        elif code == "secret_material_invalid":
            self._stubbed(_Stub(self._good_body(SecretString=SENTINEL)))
        else:
            raise AssertionError(code)

    def mismatch_version(self) -> None:
        self._stubbed(_Stub(self._good_body(VersionId=OTHER_VERSION)))

    def drift(self) -> None:
        env = self._monkeypatch.setenv
        env("AWS_ACCESS_KEY_ID", "AKIADRIFTEDDRIFTEDXX")
        env("AWS_SECRET_ACCESS_KEY", "drifted")
        env("AWS_CA_BUNDLE", str(self._tmp / "other-ca.pem"))
        env("AWS_ENDPOINT_URL", "https://drifted.invalid")
        env("AWS_ENDPOINT_URL_SECRETS_MANAGER", "https://drifted.invalid")

    def observed(self) -> Observed:
        return self._seen[-1]

    def reads(self) -> int:
        return self._reads

    def close(self) -> None:
        self._moto.stop()
