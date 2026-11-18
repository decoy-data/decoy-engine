"""`aws-sm://` reference grammar, and the raw-control-character tightening both pinned remote
schemes share (F13 row 83, E1, acceptance AT-1)."""

from __future__ import annotations

import pytest

from decoy_engine.keyprovider import MaskSecretError
from decoy_engine.secret_providers import parse_ref

UUID = "0123abcd-0123-4abc-8abc-0123456789ab"
GOOD = f"aws-sm://us-east-1/team/app?version={UUID}&field=key&encoding=base64"
VAULT = "vault://kv/team/app?version=3&field=key&encoding=base64"


def _aws(*, region="us-east-1", name="team/app", version=UUID, field="key", enc="base64"):
    return f"aws-sm://{region}/{name}?version={version}&field={field}&encoding={enc}"


def test_aws_ref_round_trips_its_parts():
    ref = parse_ref(GOOD)
    assert (ref.scheme, ref.locator, ref.version, ref.field, ref.encoding) == (
        "aws-sm",
        "us-east-1/team/app",
        UUID,
        "key",
        "base64",
    )
    assert parse_ref(_aws(region="us-gov-west-1", name="a+b=c.d@e-f_g")).locator == (
        "us-gov-west-1/a+b=c.d@e-f_g"
    )


def test_aws_name_is_percent_decoded_once():
    assert parse_ref(_aws(name="a%2Fb")).locator == "us-east-1/a/b"


@pytest.mark.parametrize(
    "bad",
    [
        _aws(version="AWSCURRENT"),
        _aws(version="AWSPREVIOUS"),
        _aws(version=UUID.upper()),
        _aws(version=UUID[:-1]),
        _aws(version=UUID + "0"),
        _aws(version=UUID + "%0A"),
        _aws(version="3"),
        _aws(region="us-east-1.evil.example"),
        _aws(region="USEAST1"),
        _aws(region="us-east"),
        _aws(region="us-east-123"),
        _aws(name="a//b"),
        _aws(name="a/../b"),
        _aws(name="./a"),
        _aws(name="a/"),
        _aws(name="a%5Cb"),
        _aws(name="a%20b"),
        _aws(name="a%3Ab"),
        _aws(name="arn:aws:secretsmanager:us-east-1:123456789012:secret:x"),
        _aws(name="a" * 513),
        f"aws-sm://us-east-1/a?version={UUID}&encoding=raw",
        f"aws-sm://us-east-1/a?version={UUID}&field=f",
        "aws-sm://us-east-1/a?field=f&encoding=raw",
        f"aws-sm://us-east-1/a?version={UUID}&version={UUID}&field=f&encoding=raw",
        f"aws-sm://us-east-1/a?version={UUID}&field=f&encoding=raw&extra=1",
        f"aws-sm://user:pw@us-east-1/a?version={UUID}&field=f&encoding=raw",
        f"aws-sm://us-east-1:443/a?version={UUID}&field=f&encoding=raw",
        f"aws-sm://us-east-1/a?version={UUID}&field=f&encoding=raw#frag",
        f"aws-sm://us-east-1/a?version={UUID}&field=f&encoding=utf16",
        f"aws-sm://us-east-1/a?version={UUID}&field=%ZZ&encoding=raw",
        f"aws-sm://us-east-1/a?version={UUID}&field=%ff&encoding=raw",
        f"aws-sm://us-east-1?version={UUID}&field=f&encoding=raw",
        f"aws-sm:///a?version={UUID}&field=f&encoding=raw",
    ],
)
def test_aws_ref_grammar_rejects_unsafe_refs(bad):
    with pytest.raises(MaskSecretError) as info:
        parse_ref(bad)
    assert info.value.code == "bad_secret_ref"


@pytest.mark.parametrize("char", ["\n", "\t", "\r", "\x7f", "\x1f"])
@pytest.mark.parametrize("part", ["region", "name", "version", "field", "encoding"])
def test_aws_ref_refuses_a_control_character_in_every_part(part, char):
    parts = {"region": "us-east-1", "name": "team/app", "version": UUID, "field": "key"}
    parts["enc"] = "base64"
    key = "enc" if part == "encoding" else part
    parts[key] = parts[key] + char if part != "region" else "us-east-1" + char
    with pytest.raises(MaskSecretError) as info:
        parse_ref(_aws(**parts))
    assert info.value.code == "bad_secret_ref"


@pytest.mark.parametrize("char", ["\n", "\t", "\r", "\x7f"])
@pytest.mark.parametrize(
    "bad",
    [
        "vault://kv{c}/a?version=1&field=f&encoding=raw",
        "vault://kv/a{c}b?version=1&field=f&encoding=raw",
        "vault://kv/a?version=1{c}&field=f&encoding=raw",
        "vault://kv/a?version=1&field=f{c}&encoding=raw",
        "vault://kv/a?version=1&field=f&encoding=raw{c}",
    ],
)
def test_vault_ref_refuses_raw_control_characters_urlsplit_would_drop(bad, char):
    # urlsplit strips \t \n \r before anyone sees them, so `kv/a\nb` parsed as `kv/ab`.
    with pytest.raises(MaskSecretError) as info:
        parse_ref(bad.format(c=char))
    assert info.value.code == "bad_secret_ref"


def test_vault_ref_still_parses_after_the_shared_grammar_change():
    ref = parse_ref(VAULT)
    assert (ref.scheme, ref.locator, ref.version, ref.field) == ("vault", "kv/team/app", "3", "key")


def test_aws_refs_never_repeat_the_reference():
    ref = parse_ref(GOOD)
    assert "team" not in repr(ref) + str(ref)
    with pytest.raises(MaskSecretError) as info:
        parse_ref(_aws(name="F13NAMEMARKER", version="AWSCURRENT"))
    assert "F13NAMEMARKER" not in str(info.value) + repr(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None
