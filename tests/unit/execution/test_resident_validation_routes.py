"""EXPECT-OFF-ROUTE S2: validators no longer pick a resident route, and `execute_route` finishes them.

A job with a `validators:` block takes the route the same job takes without it (unified slice,
mixed route). `execute_route` binds one validation session beside the post-scan gate, feeds it every
resident output no route fed yet, finishes it before `settle` and stores the report. Validators do
not change what a plain callable sink receives.

Mutations these tests kill (plan section 10): M6 (the unified admission decline comes back), M12
(`execute_route` skips resident completion), M15 (a table's second observer adds to its folds).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.errors import ValidatorFailedError
from decoy_engine.execution import _pipeline_route_dispatch as dispatch
from decoy_engine.execution import run_pipeline
from decoy_engine.execution._unified_slice import QUALITY_METRICS_KEY
from decoy_engine.execution.native._companion_status import native_companion_status
from decoy_engine.keyprovider import SecretKeyProvider
from decoy_engine.validators import ValidationSession
from tests.parity import _f2_mixed_support as mixed
from tests.physical._shadow_helpers import build_config, write_read_only_fixture

_VERSION = "resident-validation-routes"
_ROWS = 2000
_NEEDS_NATIVE = pytest.mark.skipif(
    not native_companion_status().ok, reason="compiled decoy-engine-native companion unavailable"
)

PASSING = [{"name": "regex_match", "columns": {"t": ["email"]}, "params": {"pattern": ".*"}}]
FAILING = [{"name": "regex_match", "columns": {"t": ["email"]}, "params": {"pattern": "^$"}}]


def _key() -> SecretKeyProvider:
    return SecretKeyProvider(secret=bytes(range(32)), key_version="v1")


class _Sink:
    """A transactional sink double that records every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def write(self, table: str, data: pa.Table) -> None:
        self.calls.append("write")

    def write_batches(self, table: str, batches: Iterable[Any], *, schema: pa.Schema) -> None:
        self.calls.append("write_batches")

    def commit(self) -> object:
        self.calls.append("commit")
        return None

    def abort(self) -> None:
        self.calls.append("abort")


def _unified_path(tmp_path: Path) -> Any:
    source = pa.table(
        {"id": [str(i) for i in range(_ROWS)], "email": [f"u{i}@x.com" for i in range(_ROWS)]}
    )
    return write_read_only_fixture(tmp_path, source, "fixture")


def _unified_config(tmp_path: Path, path: Any, validators: list[dict[str, Any]] | None) -> Any:
    config = build_config(
        tmp_path, "t", path, [{"name": "email", "strategy": "hash", "namespace": "n"}]
    )
    if validators is not None:
        config["validators"] = validators
    return config


def _unified_job(tmp_path: Path, validators: list[dict[str, Any]] | None) -> tuple[Any, Any]:
    path = _unified_path(tmp_path)
    return _unified_config(tmp_path, path, validators), path


def _run_unified(config: Any, path: Any, **kwargs: Any) -> Any:
    return run_pipeline(
        config,
        {"t": pq.read_table(path)},
        engine_version=_VERSION,
        key_provider=_key(),
        unified_slice_enabled=True,
        **kwargs,
    )


def _route_facts(result: Any) -> dict[str, Any]:
    execution = result.quality_metrics["execution"]
    return {k: execution.get(k) for k in ("route", "route_reason", "route_label")}


# --- V4 resident rows: the unified slice -----------------------------------------------------


@_NEEDS_NATIVE
def test_unified_slice_runs_with_validators_on_the_route_it_takes_without(tmp_path: Path) -> None:
    config, path = _unified_job(tmp_path, None)
    without = _run_unified(config, path)
    assert QUALITY_METRICS_KEY in without.quality_metrics, "the control job must take the lane"
    with_validators = _run_unified(_unified_config(tmp_path, path, PASSING), path)
    assert QUALITY_METRICS_KEY in with_validators.quality_metrics
    assert _route_facts(with_validators) == _route_facts(without)
    assert with_validators.outputs["t"].equals(without.outputs["t"])


@_NEEDS_NATIVE
def test_unified_slice_reports_every_configured_check(tmp_path: Path) -> None:
    config, path = _unified_job(tmp_path, PASSING)
    result = _run_unified(config, path)
    assert QUALITY_METRICS_KEY in result.quality_metrics
    report = result.quality_metrics["validation"]["validators"]
    assert report["passed"] is True
    assert [r["status"] for r in report["results"]] == ["passed"]


@_NEEDS_NATIVE
def test_unified_slice_failure_raises_and_commits_nothing(tmp_path: Path) -> None:
    config, path = _unified_job(tmp_path, FAILING)
    sink = _Sink()
    with pytest.raises(ValidatorFailedError):
        _run_unified(config, path, sink=sink)
    assert "commit" not in sink.calls
    assert "write" not in sink.calls


# --- V4 resident rows: the mixed route -------------------------------------------------------


def _mixed_job(tmp_path: Path, validators: list[dict[str, Any]] | None) -> tuple[Any, Any]:
    keys = pa.array([str(i) for i in range(5)] * 8, pa.string())
    child = mixed.child_table(keys)
    config = mixed.mixed_config(tmp_path, child)
    if validators is not None:
        config["validators"] = validators
    return config, child


def _routes(config: Any, child: Any, **kwargs: Any) -> tuple[list[str], Any]:
    seen: list[str] = []

    class _Progress:
        def on_event(self, event: Any) -> None:
            if event.kind == "route":
                seen.append(event.route)

    result = mixed.run(config, {mixed.CHILD: child}, progress=_Progress(), **kwargs)
    return seen, result


_MIXED_PASSING = [
    {"name": "regex_match", "columns": {mixed.CHILD: ["email"]}, "params": {"pattern": ".*"}}
]
_MIXED_FAILING = [
    {"name": "regex_match", "columns": {mixed.CHILD: ["email"]}, "params": {"pattern": "^$"}}
]


@mixed.NEEDS_COMPANION
def test_mixed_route_keeps_its_route_with_validators(tmp_path: Path) -> None:
    config, child = _mixed_job(tmp_path, None)
    without, plain = _routes(config, child)
    assert "mixed" in without, "the control job must take the mixed route"
    config_v, _ = _mixed_job(tmp_path, _MIXED_PASSING)
    with_validators, result = _routes(config_v, child)
    assert with_validators == without
    assert result.outputs[mixed.CHILD].equals(plain.outputs[mixed.CHILD])


@mixed.NEEDS_COMPANION
def test_mixed_route_stores_the_session_report(tmp_path: Path) -> None:
    config, child = _mixed_job(tmp_path, _MIXED_PASSING)
    _, result = _routes(config, child)
    report = result.quality_metrics["validation"]["validators"]
    assert report["passed"] is True
    assert report["validators_run"] == ("regex_match",)
    assert [r["status"] for r in report["results"]] == ["passed"]


@mixed.NEEDS_COMPANION
def test_mixed_route_failure_is_raised_by_the_resident_choke(tmp_path: Path) -> None:
    config, child = _mixed_job(tmp_path, _MIXED_FAILING)
    with pytest.raises(ValidatorFailedError) as caught:
        _routes(config, child)
    assert caught.value.report.findings[0].failing_row_count == child.num_rows


# --- V4 callable rows ---------------------------------------------------------------------------


@mixed.NEEDS_COMPANION
def test_validators_do_not_change_what_a_callable_sink_receives(tmp_path: Path) -> None:
    config, child = _mixed_job(tmp_path, None)
    plain: list[str] = []
    _routes(config, child, sink=lambda name, table: plain.append(name))
    config_v, _ = _mixed_job(tmp_path, _MIXED_PASSING)
    checked: list[str] = []
    _routes(config_v, child, sink=lambda name, table: checked.append(name))
    assert checked == plain, "a passing validator changed what the callable received"


@mixed.NEEDS_COMPANION
def test_callable_gets_nothing_when_a_validator_fails(tmp_path: Path) -> None:
    config, child = _mixed_job(tmp_path, _MIXED_FAILING)
    delivered: list[str] = []
    with pytest.raises(ValidatorFailedError):
        _routes(config, child, sink=lambda name, table: delivered.append(name))
    assert delivered == []


# --- M12: the resident completion is one choke point ---------------------------------------------


@mixed.NEEDS_COMPANION
def test_execute_route_completes_resident_validation_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A route that never calls finalize (the mixed route) is validated only by the choke."""
    calls: list[str] = []
    real = dispatch.complete_resident_validation

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append("complete")
        return real(*args, **kwargs)

    monkeypatch.setattr(dispatch, "complete_resident_validation", spy)
    config, child = _mixed_job(tmp_path, _MIXED_PASSING)
    _routes(config, child)
    assert calls == ["complete"]


# --- M15: a table has one folding observer --------------------------------------------------


_TWO_TABLE = {
    "validators": [
        {"name": "regex_match", "columns": {"a": ["v"], "b": ["v"]}, "params": {"pattern": "^a$"}}
    ]
}


def test_a_second_observer_of_a_table_never_adds_to_its_folds() -> None:
    table = pa.table({"v": ["a", "b", "c"]})
    session = ValidationSession(_TWO_TABLE)
    session.observe("a", table)
    session.observe("a", table)
    finding = session.finish().findings[0]
    assert finding.failing_row_count == 2
    assert finding.failing_row_indices == (1, 2)


def test_observe_unobserved_feeds_only_tables_no_observer_folded() -> None:
    bad = pa.table({"v": ["x", "a"]})
    session = ValidationSession(_TWO_TABLE)
    session.observe("a", bad)
    assert session.observe_unobserved({"a": bad, "b": bad}, {}) is True
    findings = {f.table: f.failing_row_count for f in session.finish().findings}
    assert findings == {"a": 1, "b": 1}


def test_observe_unobserved_reports_when_there_was_nothing_to_feed() -> None:
    bad = pa.table({"v": ["x", "a"]})
    session = ValidationSession(_TWO_TABLE)
    session.observe("a", bad)
    assert session.observe_unobserved({"a": bad}, {}) is False


# --- a lazy paired source is read in batches, never whole ---------------------------------------


def _leak_case(tmp_path: Path) -> tuple[dict[str, Any], pa.Table, pa.Table, Any]:
    from decoy_engine.profile import LazySource

    src = [f"v{i}" for i in range(10)]
    source = pa.table({"col": src})
    # Rows 0 and 7 leak; the rest are masked.
    output = pa.table({"col": [v if i in (0, 7) else v + "_m" for i, v in enumerate(src)]})
    path = tmp_path / "t.parquet"
    pq.write_table(source, path)
    config = {
        "validators": [{"name": "leak_check"}],
        "tables": [{"name": "t", "columns": [{"name": "col", "strategy": "hash"}]}],
        "relationships": [],
    }
    return config, source, output, LazySource(path=path)


def _report_or_error(call: Any) -> Any:
    try:
        call()
    except ValidatorFailedError as exc:
        return dataclasses.replace(exc.report, elapsed_ms=0.0)
    except Exception as exc:  # the verdict under test is which error, if any
        return f"raised {type(exc).__name__}"
    return "passed"


def test_a_lazy_paired_source_is_read_in_batches_with_the_resident_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from decoy_engine.profile import LazySource
    from decoy_engine.validators import validate

    config, source, output, lazy = _leak_case(tmp_path)
    whole: list[str] = []
    real_to_table = LazySource.to_table

    def to_table(self: LazySource, *args: Any, **kwargs: Any) -> pa.Table:
        whole.append(str(self.path))
        return real_to_table(self, *args, **kwargs)

    monkeypatch.setattr(LazySource, "to_table", to_table)
    monkeypatch.setattr(dispatch, "_SOURCE_BATCH_ROWS", 3, raising=False)
    oracle = validate({"t": output}, config, sources={"t": source})
    assert oracle.passed is False
    ctx = SimpleNamespace(caller_sources={"t": lazy}, config=config)
    result = SimpleNamespace(outputs={"t": output}, quality_metrics={})
    verdict = _report_or_error(
        lambda: dispatch.complete_resident_validation(ValidationSession(config), ctx, result)
    )
    assert whole == [], "the lazy source was read whole"
    assert verdict == dataclasses.replace(oracle, elapsed_ms=0.0)


def test_a_lazy_source_shorter_than_its_output_is_a_pairing_failure(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from decoy_engine.errors import ValidatorStateError

    config, _, output, lazy = _leak_case(tmp_path)
    longer = pa.concat_tables([output, output.slice(0, 2)])
    ctx = SimpleNamespace(caller_sources={"t": lazy}, config=config)
    result = SimpleNamespace(outputs={"t": longer}, quality_metrics={})
    with pytest.raises(ValidatorStateError) as caught:
        dispatch.complete_resident_validation(ValidationSession(config), ctx, result)
    assert caught.value.code == "validator_source_pairing_mismatch"


def test_a_resident_paired_source_gives_the_resident_verdict(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from decoy_engine.validators import validate

    config, source, output, _ = _leak_case(tmp_path)
    oracle = validate({"t": output}, config, sources={"t": source})
    ctx = SimpleNamespace(caller_sources={"t": source}, config=config)
    result = SimpleNamespace(outputs={"t": output}, quality_metrics={})
    verdict = _report_or_error(
        lambda: dispatch.complete_resident_validation(ValidationSession(config), ctx, result)
    )
    assert verdict == dataclasses.replace(oracle, elapsed_ms=0.0)


def test_a_lazy_source_longer_than_its_output_is_a_pairing_failure(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from decoy_engine.errors import ValidatorStateError

    config, _, output, lazy = _leak_case(tmp_path)
    ctx = SimpleNamespace(caller_sources={"t": lazy}, config=config)
    result = SimpleNamespace(outputs={"t": output.slice(0, 7)}, quality_metrics={})
    with pytest.raises(ValidatorStateError) as caught:
        dispatch.complete_resident_validation(ValidationSession(config), ctx, result)
    assert caught.value.code == "validator_source_pairing_mismatch"


def test_an_empty_lazy_source_and_output_pass(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from decoy_engine.profile import LazySource
    from decoy_engine.validators import validate

    config, source, output, _ = _leak_case(tmp_path)
    path = tmp_path / "empty.parquet"
    pq.write_table(source.slice(0, 0), path)
    session = ValidationSession(config)
    ctx = SimpleNamespace(caller_sources={"t": LazySource(path=path)}, config=config)
    result = SimpleNamespace(outputs={"t": output.slice(0, 0)}, quality_metrics={})
    dispatch.complete_resident_validation(session, ctx, result)
    oracle = validate({"t": output.slice(0, 0)}, config, sources={"t": source.slice(0, 0)})
    report = dataclasses.replace(session.finish(), elapsed_ms=0.0)
    assert report == dataclasses.replace(oracle, elapsed_ms=0.0)
    assert session.unobserved_tables({"t": output}) == []


def test_source_batches_for_a_complete_table_add_nothing(tmp_path: Path) -> None:
    config, source, output, lazy = _leak_case(tmp_path)
    session = ValidationSession(config)
    clean = pa.table({"col": [v.as_py() + "_m" for v in source.column("col")]})
    session.observe_source_batches("t", clean, lazy.iter_batches(4), lazy.schema)
    session.observe_source_batches("t", output, lazy.iter_batches(4), lazy.schema)
    assert session.finish().passed is True
