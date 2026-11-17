"""One NER model resolution for every route (SCAN-ML-MD A-13).

Route cells replace the resolver's default answer with a value no constant or literal holds, so a
route that reads the constant, hard-codes a model or keeps its own copy of the logic resolves
something else and fails. Each route cell also records that it was entered, so a route that stops
running cannot pass.
"""

from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.config import PostScanConfig, PreScanConfig
from decoy_engine.detection import ner
from decoy_engine.execution._strategies import _ner_config, _text_mask
from decoy_engine.execution.out_of_core import _mask_group_c
from decoy_engine.plan import _checks, compile_plan
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.verification.postmask import _model_findings

SENTINEL = "en_core_web_md"
NAMED = "xx_named_model"
ROUTED = "xx_from_the_resolver"
_REAL_RESOLVE = ner.resolve_ner_model


@pytest.fixture(autouse=True)
def _sentinel_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ner, "DEFAULT_NER_MODEL", SENTINEL)


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """The resolver answers ROUTED for an unset model; every call is recorded."""
    calls: list[str | None] = []

    def _resolve(value: str | None) -> str:
        calls.append(value)
        return ROUTED if not value else _REAL_RESOLVE(value)

    monkeypatch.setattr(ner, "resolve_ner_model", _resolve)
    monkeypatch.setattr(_model_findings, "resolve_ner_model", _resolve)
    return calls


class _EnteredError(Exception):
    """Raised by a recorder to stop a route once it has resolved its model."""


def _seed(ner_value: object) -> ColumnSeed:
    return ColumnSeed(
        namespace=None,
        strategy="text_mask",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="bijective",
        deterministic=False,
        provider_config=(("ner", ner_value),),
        ner_model_version=None,
    )


def test_resolver_default_and_named() -> None:
    assert ner.resolve_ner_model(None) == SENTINEL
    assert ner.resolve_ner_model("") == SENTINEL
    assert ner.resolve_ner_model(NAMED) == NAMED
    assert ner.is_default_ner_model(SENTINEL)
    assert not ner.is_default_ner_model(NAMED)


@pytest.mark.parametrize("bad", ["../x", "en_core_web_sm\n", "A", "a b"])
def test_resolver_refuses_a_bad_name(bad: str) -> None:
    with pytest.raises(ner.NerModelNameError):
        ner.resolve_ner_model(bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, (None, None)),
        (False, (None, None)),
        ({}, (None, None)),
        (True, (SENTINEL, None)),
        ({"model": None}, (SENTINEL, None)),
        ({"model": ""}, (SENTINEL, None)),
        ({"model": NAMED, "entities": ["location"]}, (NAMED, ["location"])),
        ({"entities": []}, (SENTINEL, None)),
        ({"entities": "location"}, (SENTINEL, None)),
    ],
)
def test_column_semantics(value: object, expected: tuple[str | None, list[str] | None]) -> None:
    assert ner.resolve_column_ner(value) == expected
    assert _ner_config.resolve_ner_config({"ner": value}) == expected


def test_strategy_config_delegates() -> None:
    assert _ner_config.resolve_ner_config({"ner": True}) == (SENTINEL, None)
    assert _ner_config.resolve_ner_config({}) == (None, None)


def _record_enforce(monkeypatch: pytest.MonkeyPatch, module: object) -> list[str | None]:
    seen: list[str | None] = []

    def _enforce(*, ner_model: str | None, **_: object) -> None:
        seen.append(ner_model)
        raise _EnteredError

    monkeypatch.setattr(module, "enforce_ner_model_version", _enforce)
    return seen


@pytest.mark.parametrize(("ner_value", "expected"), [(True, ROUTED), ({"model": NAMED}, NAMED)])
def test_text_mask_resident(
    routed: list[str | None], monkeypatch: pytest.MonkeyPatch, ner_value: object, expected: str
) -> None:
    seen = _record_enforce(monkeypatch, _text_mask)
    df = pd.DataFrame({"c": ["x"]})
    with pytest.raises(_EnteredError):
        _text_mask.TextMaskHandler().run(df, "c", _seed(ner_value), object())  # type: ignore[arg-type]
    assert seen == [expected]
    assert routed, "the route never called the resolver"


@pytest.mark.parametrize(("ner_value", "expected"), [(True, ROUTED), ({"model": NAMED}, NAMED)])
def test_out_of_core_group_c(
    routed: list[str | None], monkeypatch: pytest.MonkeyPatch, ner_value: object, expected: str
) -> None:
    seen = _record_enforce(monkeypatch, _mask_group_c)
    with pytest.raises(_EnteredError):
        _mask_group_c._text_mask_ner({"ner": ner_value}, _seed(ner_value), "c")
    assert seen == [expected]
    assert routed, "the route never called the resolver"


@pytest.mark.parametrize(("ner_value", "expected"), [(True, ROUTED), ({"model": NAMED}, NAMED)])
def test_plan_check(
    routed: list[str | None], monkeypatch: pytest.MonkeyPatch, ner_value: object, expected: str
) -> None:
    seen: list[str] = []

    def _ensure(model: str, *_: object, **__: object) -> None:
        seen.append(model)

    monkeypatch.setattr(ner, "ensure_ner_available", _ensure)
    config = {
        "tables": [
            {
                "name": "t",
                "columns": [
                    {
                        "name": "c",
                        "strategy": "text_mask",
                        "provider_config": {"ner": ner_value},
                    }
                ],
            }
        ]
    }
    _checks.check_text_mask_ner_available(config)
    assert seen == [expected]
    assert routed, "the route never called the resolver"


@pytest.mark.parametrize(("ner_value", "expected"), [(True, ROUTED), ({"model": NAMED}, NAMED)])
def test_seed_envelope(
    routed: list[str | None], monkeypatch: pytest.MonkeyPatch, ner_value: object, expected: str
) -> None:
    from decoy_engine.execution._chunked_profile import first_chunk_profile
    from decoy_engine.plan import _compile as compile_mod

    seen: list[str] = []

    def _version(model: str = SENTINEL) -> str:
        seen.append(model)
        return "9.9.9"

    monkeypatch.setattr(ner, "installed_model_version", _version)
    monkeypatch.setattr(compile_mod, "check_text_mask_ner_available", lambda config: None)
    cfg = {
        "global_settings": {"seed": 1},
        "tables": [
            {
                "name": "t",
                "columns": [
                    {"name": "c", "strategy": "text_mask", "provider_config": {"ner": ner_value}}
                ],
            }
        ],
    }
    profile = first_chunk_profile(
        pa.Table.from_pandas(pd.DataFrame({"c": ["hello"]}), preserve_index=False),
        table="t",
        engine_version="x",
    )
    plan = compile_plan(cfg, profile, decoy_engine_version="x", no_profile=True)
    column = dict(plan.seed_envelope.per_table[0][1].per_column)["c"]
    assert column.ner_model_version == "9.9.9"
    assert seen == [expected]
    assert routed, "the route never called the resolver"


@pytest.mark.parametrize(("block_model", "expected"), [(None, ROUTED), (NAMED, NAMED)])
def test_post_scan_findings(
    routed: list[str | None],
    monkeypatch: pytest.MonkeyPatch,
    block_model: str | None,
    expected: str,
) -> None:
    seen: list[str] = []

    def _load(sources: object, *, ner_model: str, **_: object) -> str:
        seen.append(ner_model)
        return "loaded"

    monkeypatch.setattr(_model_findings, "load_detectors", _load)
    monkeypatch.setattr(_model_findings, "post_scan_integrity_requested", lambda config: True)
    block: dict[str, object] = {"detectors": ["regex", "ner"]}
    if block_model is not None:
        block["ner_model"] = block_model
    assert _model_findings.post_scan_detectors({"post_scan": block}) == "loaded"
    assert seen == [expected]
    assert routed, "the route never called the resolver"


@pytest.mark.parametrize(
    ("config_cls", "extra"), [(PreScanConfig, {}), (PostScanConfig, {"integrity": True})]
)
def test_config_omits_only_the_default(config_cls: type, extra: dict[str, bool]) -> None:
    base = {"detectors": ["regex", "ner"], **extra}
    default = config_cls(**base, ner_model=SENTINEL).model_dump(mode="json")
    named = config_cls(**base, ner_model=NAMED).model_dump(mode="json")
    assert "ner_model" not in default
    assert named["ner_model"] == NAMED
