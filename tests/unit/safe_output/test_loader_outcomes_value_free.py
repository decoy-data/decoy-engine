"""B1: every loader route's outcome is value-free, under the ambient and a strict policy.

Each route has its own expected outcome (a raised refusal, `None`, a `PinnedRead`, a report).
A case first asserts that outcome and its discriminator, so a different, earlier refusal cannot
satisfy the canary check, then asserts the canary is on no surface the caller can read.
Value slots (field values, pins, URLs, file contents) must never be shown. Name slots are
shaped so that `approve_name` refuses them; the case asserts that, then asserts a placeholder
shows instead.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import string
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decoy_engine import fileaccess
from decoy_engine.detection.name_hints.loader import NameHintLoaderError, load_name_hint_terms
from decoy_engine.generation.statistical import StatisticalSpecError, load_spec
from decoy_engine.plan import _generation
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.profiling.model_pack.loader import ModelPackLoader, ModelPackLoadError
from decoy_engine.quality import dp_provenance as prov
from decoy_engine.quality.snapshot import compute_distribution_snapshot
from decoy_engine.reasons import approve_name
from decoy_engine.transforms._codeset_loader import load_corpus, verify_corpus
from decoy_engine.transforms.code_set import CodeSetConfig
from decoy_engine.transforms.joint_mask import validate_joint_mask_config
from tests.fileaccess.support import RootRelative

_CANARIES = st.text(alphabet=string.ascii_letters + string.digits, min_size=6, max_size=18).map(
    lambda s: "CANARY" + s
)


@contextlib.contextmanager
def _world(strict: bool) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "root"
        root.mkdir()
        if not strict:
            yield root
            return
        policy = RootRelative(root)
        try:
            with fileaccess.scope(policy):
                yield root
        finally:
            policy.close()


def _surfaces(outcome: object) -> list[str]:
    """Every string a caller can read from an outcome."""
    if isinstance(outcome, BaseException):
        out = [str(outcome), repr(outcome), *(str(a) for a in outcome.args)]
        out += [v for v in vars(outcome).values() if isinstance(v, str)]
        assert outcome.__cause__ is None
        assert outcome.__context__ is None
        return out
    if dataclasses.is_dataclass(outcome) and not isinstance(outcome, type):
        return [repr(v) for v in vars(outcome).values()] + [repr(outcome)]
    return [repr(outcome)]


def _caught(call: Callable[[], object]) -> object:
    try:
        return call()
    except Exception as exc:
        return exc


def _hints(root: Path, body: str, manifest: str = "files:\n  - bad.yaml\n") -> Path:
    folder = root / "hints"
    folder.mkdir()
    (folder / "manifest.yaml").write_text(manifest, encoding="utf-8")
    (folder / "bad.yaml").write_text(body, encoding="utf-8")
    return folder


def _tz_corpus(root: Path, canary: str) -> Path:
    import datetime

    path = root / "tz.parquet"
    stamp = pa.array([datetime.datetime(2024, 1, 1)], pa.timestamp("us", tz=canary))
    pq.write_table(pa.table({"code": pa.array(["A1"], pa.string()), "ts": stamp}), path)
    return path


def _snapshot() -> dict[str, Any]:
    snap = compute_distribution_snapshot(pd.DataFrame({"a": ["x", "y", "z"]}))
    return json.loads(json.dumps(snap))


_STAT_COL = {"name": "a", "type": "statistical", "snapshot_file": "s.json"}


# case: (id, run(root, canary) -> outcome, check(outcome, canary) -> None)
Case = tuple[str, Callable[[Path, str], object], Callable[[object, str, bool], None]]


def _refused(
    kind: type[BaseException],
    *fragments: str,
    denied_when_strict: bool = False,
    read_error_when_strict: bool = False,
) -> Callable[[object, str, bool], None]:
    def check(outcome: object, canary: str, strict: bool) -> None:
        if strict and read_error_when_strict:
            # The strict YAML adapter already replaces a parse failure with its fixed read error.
            assert isinstance(outcome, fileaccess.FileAccessReadError), outcome
            return
        if strict and denied_when_strict:
            # A strict policy refuses the locator itself: the route's own denial passes.
            assert isinstance(outcome, fileaccess.FileAccessDenied), outcome
            return
        assert isinstance(outcome, kind), outcome
        text = str(outcome)
        for fragment in fragments:
            assert fragment in text, (fragment, text)

    return check


def _coded(
    kind: type[BaseException], code: str, *fragments: str, denied_when_strict: bool = False
) -> Callable[[object, str, bool], None]:
    def check(outcome: object, canary: str, strict: bool) -> None:
        _refused(kind, *fragments, denied_when_strict=denied_when_strict)(outcome, canary, strict)
        if not (strict and denied_when_strict):
            assert getattr(outcome, "code", None) == code

    return check


def _name_hint_value(root: Path, c: str) -> object:
    return _caught(lambda: load_name_hint_terms(_hints(root, f"x: !!int {c}\n")))


def _name_hint_pattern(root: Path, c: str) -> object:
    body = "detectors:\n  - detector_id: foo\n    patterns: [{" + c + ": v}]\n"
    return _caught(lambda: load_name_hint_terms(_hints(root, body)))


def _name_hint_directory(root: Path, c: str) -> object:
    folder = root / c
    folder.mkdir()
    (folder / "manifest.yaml").write_text("files: []\n", encoding="utf-8")
    return _caught(lambda: load_name_hint_terms(folder))


def _name_hint_url_detector(root: Path, c: str) -> object:
    body = (
        "detectors:\n"
        f"  - detector_id: 'https://host/{c}'\n    patterns: [a]\n"
        f"  - detector_id: 'https://host/{c}'\n    patterns: [b]\n"
    )
    return _caught(lambda: load_name_hint_terms(_hints(root, body)))


def _pin_list(root: Path, c: str) -> object:
    return _caught(
        lambda: CodeSetConfig.from_dict({"code_set": "icd10", "corpus_source_version": [c]})
    )


def _code_set_url(root: Path, c: str) -> object:
    return _caught(lambda: CodeSetConfig.from_dict({"code_set": f"https://user:{c}@host/x"}))


def _joint_reference(root: Path, c: str) -> object:
    cfg = {"columns": ["city"], "reference": f"customer:/{c}/nope.parquet", "key_by": "k"}
    return _caught(lambda: validate_joint_mask_config(cfg))


def _pinned_missing(root: Path, c: str) -> object:
    return _caught(
        lambda: _generation.read_pinned_artifact(
            fileaccess.FileRole.SNAPSHOT, str(root / c / "s.json"), "snapshot_file", None, 1024
        )
    )


def _verify_tz(root: Path, c: str) -> object:
    return verify_corpus(_tz_corpus(root, c))


def _load_tz(root: Path, c: str) -> object:
    return _caught(lambda: load_corpus("mine", _tz_corpus(root, c)))


def _spec_source_list(root: Path, c: str) -> object:
    cfg = {**_STAT_COL, "allow_real_categories": True, "source_column": [c]}
    return _caught(lambda: load_spec(cfg, snapshot=_snapshot()))


def _spec_condition_list(root: Path, c: str) -> object:
    cfg = {**_STAT_COL, "allow_real_categories": True, "condition_on": [c]}
    return _caught(lambda: load_spec(cfg, snapshot=_snapshot()))


def _spec_name_url(root: Path, c: str) -> object:
    cfg = {**_STAT_COL, "allow_real_categories": True, "source_column": f"https://h/{c}"}
    return _caught(lambda: load_spec(cfg, snapshot=_snapshot()))


def _model_pack_fallback(root: Path, c: str) -> object:
    pack = root / "pack"
    pack.mkdir()
    (pack / "manifest.json").write_text('{"x": "' + c + '" ', encoding="utf-8")
    return ModelPackLoader(pack).load_with_fallback()


def _model_pack_raises(root: Path, c: str) -> object:
    pack = root / "pack2"
    pack.mkdir()
    (pack / "manifest.json").write_text('{"x": "' + c + '" ', encoding="utf-8")
    return _caught(lambda: ModelPackLoader(pack).load())


def _recorded_provenance(root: Path, c: str) -> object:
    recorded = {"platform": ("Linux", c, "CPython", "glibc"), "cpython": c, "fingerprint": c}
    return _caught(lambda: prov.validate_recorded_provenance(recorded))


def _is_none(outcome: object, canary: str, strict: bool) -> None:
    assert outcome is None


def _pinned(outcome: object, canary: str, strict: bool) -> None:
    if strict:
        assert isinstance(outcome, fileaccess.FileAccessDenied), outcome
        return
    assert isinstance(outcome, _generation.PinnedRead)
    assert outcome.raw is None
    assert outcome.cause_type


def _report(code: str) -> Callable[[object, str, bool], None]:
    def check(outcome: object, canary: str, strict: bool) -> None:
        from decoy_engine.transforms._codeset_loader import CorpusVerifyReport

        assert isinstance(outcome, CorpusVerifyReport)
        assert outcome.ok is False
        assert outcome.problems[0].startswith(f"{code}: ")

    return check


_CASES: tuple[Case, ...] = (
    (
        "name_hint_scalar",
        _name_hint_value,
        _refused(
            NameHintLoaderError,
            "pre_scan.name_hints/bad.yaml: could not be parsed",
            read_error_when_strict=True,
        ),
    ),
    (
        "name_hint_pattern_key",
        _name_hint_pattern,
        _refused(NameHintLoaderError, "patterns[0]: wrong type", "got dict"),
    ),
    ("name_hint_directory", _name_hint_directory, _refused(NameHintLoaderError, "files: empty")),
    (
        "name_hint_url_detector_name",
        _name_hint_url_detector,
        _refused(NameHintLoaderError, "detectors.<name>: declared more than once"),
    ),
    (
        "code_set_pin_list",
        _pin_list,
        _coded(PlanCompileError, "code_set_corpus_source_version_invalid", "got list"),
    ),
    (
        "code_set_url",
        _code_set_url,
        _coded(
            PlanCompileError, "code_set_corpus_not_found", "provider_config.code_set: not found"
        ),
    ),
    (
        "joint_reference",
        _joint_reference,
        _coded(
            PlanCompileError,
            "joint_mask_reference_invalid",
            "joint_masks.reference",
            denied_when_strict=True,
        ),
    ),
    ("pinned_snapshot", _pinned_missing, _pinned),
    ("verify_corpus_tz", _verify_tz, _report("code_set_corpus_read_error")),
    (
        "load_corpus_tz",
        _load_tz,
        _coded(PlanCompileError, "code_set_corpus_read_error", "could not be"),
    ),
    (
        "spec_source_list",
        _spec_source_list,
        _coded(StatisticalSpecError, "statistical_column_not_in_snapshot", "got list"),
    ),
    (
        "spec_condition_list",
        _spec_condition_list,
        _coded(StatisticalSpecError, "statistical_joint_missing", "condition_on", "got list"),
    ),
    (
        "spec_source_url_name",
        _spec_name_url,
        _coded(StatisticalSpecError, "statistical_column_not_in_snapshot", "source_column.<name>"),
    ),
    ("model_pack_fallback", _model_pack_fallback, _is_none),
    (
        "model_pack_raises",
        _model_pack_raises,
        _refused(ModelPackLoadError, "manifest.json: could not be parsed"),
    ),
    (
        "recorded_provenance",
        _recorded_provenance,
        _coded(prov.ProvenanceError, "dp_platform_uncertified", "recorded.platform"),
    ),
)


@pytest.mark.parametrize("strict", [False, True], ids=["ambient", "strict"])
@pytest.mark.parametrize(("name", "run", "check"), _CASES, ids=[c[0] for c in _CASES])
@settings(
    max_examples=6, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(canary=_CANARIES)
def test_every_loader_outcome_is_value_free(
    name: str,
    run: Callable[[Path, str], object],
    check: Callable[[object, str, bool], None],
    strict: bool,
    canary: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.clear()
    with caplog.at_level(logging.DEBUG), _world(strict) as root:
        outcome = run(root, canary)
    check(outcome, canary, strict)
    surfaces = _surfaces(outcome) + [r.getMessage() for r in caplog.records]
    surfaces += [
        str(a) for r in caplog.records for a in (r.args if isinstance(r.args, tuple) else ())
    ]
    for surface in surfaces:
        assert canary not in surface, (name, strict, surface)


def test_manifest_url_member_does_not_expose_its_final_segment() -> None:
    """Ambient regression: the URL's last segment passes `approve_name`, the URL as a whole must
    still show as `<file>`."""
    token = "BEARER_CANARY"
    assert approve_name(token) is not None
    with _world(False) as root:
        folder = _hints(
            root, "detectors: []\n", f"files:\n  - https://example.invalid/download/{token}\n"
        )
        outcome = _caught(lambda: load_name_hint_terms(folder))
    assert isinstance(outcome, NameHintLoaderError), outcome
    assert str(outcome).startswith("pre_scan.name_hints/<file>: not found"), str(outcome)
    for surface in _surfaces(outcome):
        assert token not in surface, surface


@settings(max_examples=10, deadline=None)
@given(canary=_CANARIES)
def test_name_slot_canaries_are_shapes_that_approve_name_refuses(canary: str) -> None:
    for shaped in (f"https://host/{canary}", f"/etc/{canary}", canary * 20):
        assert approve_name(shaped) is None
