"""DUP-DEST E1: two declared tables cannot write to one destination."""

from __future__ import annotations

import os
import re
from typing import Any

import pytest
from pydantic import ValidationError

from decoy_engine import reasons
from decoy_engine.config import (
    FileTarget,
    GCSTarget,
    PipelineConfig,
    PipelineConfigError,
    S3Target,
    duplicate_target_groups,
    parse_pipeline_config,
)
from decoy_engine.config import _targets as targets_mod
from decoy_engine.profiling._starter_config import _refuse_shared_destinations

CODE = "target_shared_destination"
CANARY = "CANARYVALUE"


def _file(path: str) -> dict[str, Any]:
    return {"type": "file", "format": "csv", "path": path}


def _s3(bucket: str = "b", key: str = "k", **extra: Any) -> dict[str, Any]:
    return {"type": "s3", "format": "csv", "bucket": bucket, "key": key, **extra}


def _gcs(bucket: str = "b", obj: str = "o") -> dict[str, Any]:
    return {"type": "gcs", "format": "csv", "bucket": bucket, "object": obj}


def _table(name: str, kind: str = "generate") -> dict[str, Any]:
    if kind == "mask":
        return {"name": name, "columns": [{"name": "email", "strategy": "hash"}]}
    col = {"name": "id", "type": "sequence", "start": 1, "step": 1}
    return {"name": name, "row_count": 3, "generate_columns": [col]}


def _config(targets: dict[str, Any], names: list[str] | None = None) -> dict[str, Any]:
    names = names if names is not None else [n for n in targets if n.isalpha()]
    return {
        "version": 2,
        "global_settings": {"seed": 1},
        "sources": {},
        "tables": [_table(n) for n in names],
        "targets": targets,
    }


def _refusal(raw: dict[str, Any]) -> ValidationError:
    with pytest.raises(ValidationError) as err:
        PipelineConfig.model_validate(raw)
    return err.value


def _locs(exc: ValidationError) -> list[tuple[Any, ...]]:
    return [e["loc"] for e in exc.errors() if e["type"] == CODE]


def test_e1_two_file_targets_one_path_are_refused() -> None:
    exc = _refusal(_config({"a": _file("out.csv"), "b": _file("out.csv")}))
    assert _locs(exc) == [("targets", "a", "path"), ("targets", "b", "path")]


@pytest.mark.parametrize("second", ["out/./a.csv", "out//a.csv"])
def test_e2_equivalent_spellings_are_one_destination(second: str) -> None:
    exc = _refusal(_config({"a": _file("out/a.csv"), "b": _file(second)}))
    assert _locs(exc) == [("targets", "a", "path"), ("targets", "b", "path")]


def test_e3_s3_same_address_is_refused_whatever_the_routing() -> None:
    a = _s3(region="us-east-1", credentials_ref="one")
    b = _s3(region="eu-west-1", credentials_ref="two")
    exc = _refusal(_config({"a": a, "b": b}))
    assert _locs(exc) == [("targets", "a", "key"), ("targets", "b", "key")]
    for other in (_s3(bucket="other"), _s3(key="other")):
        PipelineConfig.model_validate(_config({"a": _s3(), "b": other}))


def test_e4_gcs_same_address_is_refused() -> None:
    exc = _refusal(_config({"a": _gcs(), "b": _gcs()}))
    assert _locs(exc) == [("targets", "a", "object"), ("targets", "b", "object")]
    for other in (_gcs(bucket="other"), _gcs(obj="other")):
        PipelineConfig.model_validate(_config({"a": _gcs(), "b": other}))


def test_e5_a_file_and_an_s3_key_with_one_name_are_distinct() -> None:
    PipelineConfig.model_validate(_config({"a": _file("a.csv"), "b": _s3(key="a.csv")}))


def test_e6_every_table_of_a_group_is_reported_in_config_order() -> None:
    three = _config({"a": _file("x"), "b": _file("x"), "c": _file("x")})
    assert _locs(_refusal(three)) == [("targets", n, "path") for n in "abc"]
    pairs = _config({"a": _file("x"), "b": _file("y"), "c": _file("x"), "d": _file("y")})
    assert _locs(_refusal(pairs)) == [("targets", n, "path") for n in "abcd"]


def test_e7_mask_and_generate_tables_share_the_rule() -> None:
    raw = _config({"a": _file("x"), "b": _file("x")})
    raw["tables"][0] = _table("a", "mask")
    raw["sources"] = {"a": {"type": "file", "format": "csv", "has_header": True, "path": "in.csv"}}
    assert _locs(_refusal(raw)) == [("targets", "a", "path"), ("targets", "b", "path")]


def test_e8_the_refusal_carries_no_destination_value() -> None:
    clash = {
        "a": _file(f"/{CANARY}/p.csv"),
        "b": _file(f"/{CANARY}/p.csv"),
        "c": _s3(bucket=f"{CANARY}b", key=f"{CANARY}k", endpoint_url=f"http://u:{CANARY}@h/"),
        "d": _s3(bucket=f"{CANARY}b", key=f"{CANARY}k", endpoint_url=f"http://u:{CANARY}@h/"),
        "e": _gcs(f"{CANARY}g", f"{CANARY}o"),
        "f": _gcs(f"{CANARY}g", f"{CANARY}o"),
    }
    raw = _config(clash)
    exc = _refusal(raw)
    assert CANARY not in str(exc)
    for e in exc.errors():
        assert CANARY not in repr((e["msg"], e.get("input"), e.get("ctx")))
    assert exc.__cause__ is None and exc.__context__ is None
    with pytest.raises(PipelineConfigError) as perr:
        parse_pipeline_config(raw)
    assert CANARY not in str(perr.value)
    assert {p.code for p in perr.value.problems} == {CODE}
    assert perr.value.__cause__ is None and perr.value.__context__ is None
    with pytest.raises(ValueError) as starter:
        _refuse_shared_destinations(clash, list(clash))
    assert CANARY not in str(starter.value)
    assert reasons.find("config", CODE) is not None


def test_e9_distinct_targets_validate() -> None:
    cfg = PipelineConfig.model_validate(_config({"a": _file("a.csv"), "b": _file("b.csv")}))
    assert list(cfg.targets) == ["a", "b"]


def test_e10_an_unknown_type_is_a_discriminator_refusal_and_the_fallback_is_value_free() -> None:
    raw = _config({"a": {"type": CANARY, "format": "csv", "path": "x"}, "b": _file("x")})
    exc = _refusal(raw)
    assert CODE not in {e["type"] for e in exc.errors()}
    with pytest.raises(TypeError, match="unsupported target type") as err:
        targets_mod._target_identity(CANARY)  # type: ignore[arg-type]
    assert CANARY not in str(err.value)


def test_e11_the_code_is_a_registered_unreleased_configuration_repair() -> None:
    spec = reasons.find("config", CODE)
    assert spec is not None
    assert spec.owner == "PipelineValidationError"
    assert spec.since == reasons.UNRELEASED
    assert spec.kind is reasons.Kind.FAILURE
    assert [r.retry for r in spec.rules] == [reasons.RetryClass.CONFIGURATION_REPAIR]
    assert not re.search(r"[{}%]", spec.summary)


def test_e12_a_parent_segment_keeps_its_text(tmp_path: Any) -> None:
    PipelineConfig.model_validate(_config({"a": _file("link/../x.csv"), "b": _file("x.csv")}))
    link = tmp_path / "link"
    (tmp_path / "real" / "sub").mkdir(parents=True)
    os.symlink(tmp_path / "real" / "sub", link)
    assert os.path.realpath(link / ".." / "x.csv") != os.path.realpath(tmp_path / "x.csv")
    assert os.path.normpath("link/../x.csv") == "x.csv"  # what normpath would have merged
    assert targets_mod._target_identity(FileTarget(**_file("link/../x.csv"))) != (
        targets_mod._target_identity(FileTarget(**_file("x.csv")))
    )


def test_e12b_the_same_parent_segment_text_twice_is_still_refused() -> None:
    exc = _refusal(_config({"a": _file("../x.csv"), "b": _file("../x.csv")}))
    assert _locs(exc) == [("targets", "a", "path"), ("targets", "b", "path")]


def test_e13_only_targets_naming_a_declared_table_take_part() -> None:
    PipelineConfig.model_validate(
        _config({"a": _file("x"), "u1": _file("y"), "u2": _file("y")}, names=["a"])
    )
    PipelineConfig.model_validate(_config({"a": _file("x"), "unused": _file("x")}, names=["a"]))


def test_e14_s3_endpoint_is_part_of_the_address() -> None:
    other = _s3(endpoint_url="http://minio:9000")
    PipelineConfig.model_validate(_config({"a": _s3(), "b": other}))
    same = _s3(endpoint_url="HTTP://MINIO:9000/")
    exc = _refusal(_config({"a": other, "b": same}))
    assert _locs(exc) == [("targets", "a", "key"), ("targets", "b", "key")]


def test_groups_come_back_as_table_names_in_mapping_order() -> None:
    models = {
        "z": FileTarget(**_file("x")),
        "a": S3Target(**_s3()),
        "m": FileTarget(**_file("./x")),
        "q": GCSTarget(**_gcs()),
    }
    assert duplicate_target_groups(models, ["z", "a", "m", "q"]) == [["z", "m"]]
    assert duplicate_target_groups(models, ["z", "a", "q"]) == []


def test_e14b_an_endpoint_path_keeps_its_case() -> None:
    upper = _s3(endpoint_url="https://gateway/TenantA")
    lower = _s3(endpoint_url="https://gateway/tenanta")
    PipelineConfig.model_validate(_config({"a": upper, "b": lower}))
    users = (_s3(endpoint_url="http://Ann@h/"), _s3(endpoint_url="http://ann@h/"))
    PipelineConfig.model_validate(_config({"a": users[0], "b": users[1]}))
    same = _s3(endpoint_url="HTTPS://GATEWAY/TenantA/")
    exc = _refusal(_config({"a": upper, "b": same}))
    assert _locs(exc) == [("targets", "a", "key"), ("targets", "b", "key")]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://h/T?t=/", "https://h/T?t="),
        ("https://h/T#t/", "https://h/T#t"),
        ("https://h/T//", "https://h/T/"),
    ],
)
def test_e14c_only_one_path_slash_is_dropped(first: str, second: str) -> None:
    a, b = _s3(endpoint_url=first), _s3(endpoint_url=second)
    PipelineConfig.model_validate(_config({"a": a, "b": b}))
