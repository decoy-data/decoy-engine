"""EXPECT-OFF-ROUTE S2: validators no longer pick a resident route, and `execute_route` finishes them.

A job with a `validators:` block takes the route the same job takes without it (unified slice,
mixed route). `execute_route` binds one validation session beside the post-scan gate, feeds it every
resident output no route fed yet, finishes it before `settle`, stores the report, and hands each
passing resident output to a plain callable sink once, after `settle`.

Mutations these tests kill (plan section 10): M6 (the unified admission decline comes back), M12
(`execute_route` skips resident completion), M15 (a table's second observer adds to its folds).
"""

from __future__ import annotations

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
from decoy_engine.execution.pipeline import _post_scan
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
def test_callable_gets_each_passing_resident_table_once_after_validation_and_settle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_finish = ValidationSession.finish
    real_settle = _post_scan.settle

    def finish(self: ValidationSession) -> Any:
        events.append("finish")
        return real_finish(self)

    def settle(*args: Any, **kwargs: Any) -> Any:
        events.append("settle")
        return real_settle(*args, **kwargs)

    monkeypatch.setattr(ValidationSession, "finish", finish)
    monkeypatch.setattr(_post_scan, "settle", settle)
    config, child = _mixed_job(tmp_path, _MIXED_PASSING)
    _, result = _routes(config, child, sink=lambda name, table: events.append(f"write:{name}"))
    writes = [e.removeprefix("write:") for e in events if e.startswith("write:")]
    assert sorted(writes) == sorted(result.outputs), "each table exactly once"
    first_write = events.index(f"write:{writes[0]}")
    assert events.index("finish") < events.index("settle") < first_write


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
