"""engine-v2 S10 slice 3a: structural scans (pk_uniqueness + cardinality).

These read the masked output + the plan/profile only (no source comparison).
Tested directly on the scan callables and through the runner's merge + skip path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.config import PipelineConfig
from decoy_engine.execution import ExecutionResult, run_pipeline
from decoy_engine.generation.pool._runtime_pool_size import DEFAULT_POOL_SIZE
from decoy_engine.plan._types import ColumnSeed, SeedEnvelope, TableSeed
from decoy_engine.profile import ColumnProfile, Profile, TableProfile
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from decoy_engine.validation.post import PostValidationRunner, QualitySummary
from decoy_engine.validation.post._checks._cardinality import run_cardinality
from decoy_engine.validation.post._checks._pk_uniqueness import run_pk_uniqueness
from decoy_engine.validation.post._scan import ScanContext
from tests._declared_schema import declare_rest

_RUN_KW: dict[str, Any] = {}

_REG = get_default_registry()
_GRAPH = RelationshipGraph(edges=(), ordering=())
_NS = NamespaceRegistry(bindings=())


def _seed(cardinality_mode: str = "reuse") -> ColumnSeed:
    return ColumnSeed(
        namespace="ns",
        strategy="faker",
        provider="person_email",
        backend_type="faker",
        backend_version="v",
        cardinality_mode=cardinality_mode,
        deterministic=True,
        provider_config=(),
        coherent_with=(),
    )


def _cp(name: str, *, declared_pk: bool = False, distinct: int | None = None) -> ColumnProfile:
    return ColumnProfile(
        name=name,
        dtype="object",
        row_count=3,
        null_count=0,
        distinct_count=distinct,
        sampled=False,
        is_candidate_key_sampled=False,
        declared_pk=declared_pk,
        is_fk=False,
        fk_target=None,
        pii_class=None,
    )


def _ctx(
    *,
    outputs: dict[str, pa.Table],
    profile_cols: tuple[ColumnProfile, ...],
    plan_cols: tuple[tuple[str, ColumnSeed], ...],
    sources: dict[str, pa.Table] | None = None,
) -> ScanContext:
    profile = Profile(
        schema_version=1,
        tables=(TableProfile(name="t", row_count=3, columns=profile_cols),),
        relationships=(),
        profiled_at=datetime(2026, 5, 28),
        decoy_engine_version="0.1.0",
    )
    plan = SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=b"\x00" * 8,
            per_table=(("t", TableSeed(per_column=plan_cols, per_group=())),),
        )
    )
    return ScanContext(
        plan=plan,  # type: ignore[arg-type]
        outputs=outputs,
        sources=sources if sources is not None else outputs,
        profile=profile,
        registry=_REG,
        relationship_graph=_GRAPH,
        namespace_registry=_NS,
    )


class TestPkUniqueness:
    def test_all_distinct_passes(self) -> None:
        ctx = _ctx(
            outputs={"t": pa.table({"id": ["a", "b", "c"]})},
            profile_cols=(_cp("id", declared_pk=True),),
            plan_cols=(("id", _seed()),),
        )
        outcome = run_pk_uniqueness(ctx)
        assert outcome.failed is False
        assert outcome.duplicate_counts["t.id"] == 0

    def test_duplicate_pk_fails(self) -> None:
        ctx = _ctx(
            outputs={"t": pa.table({"id": ["a", "b", "a"]})},
            profile_cols=(_cp("id", declared_pk=True),),
            plan_cols=(("id", _seed()),),
        )
        outcome = run_pk_uniqueness(ctx)
        assert outcome.failed is True
        assert outcome.duplicate_counts["t.id"] == 1

    def test_non_pk_columns_ignored(self) -> None:
        ctx = _ctx(
            outputs={"t": pa.table({"v": ["x", "x", "x"]})},  # repeats, but not a PK
            profile_cols=(_cp("v", declared_pk=False),),
            plan_cols=(("v", _seed()),),
        )
        outcome = run_pk_uniqueness(ctx)
        assert outcome.failed is False
        assert outcome.duplicate_counts == {}


class TestCardinality:
    def test_unique_mode_all_distinct_passes(self) -> None:
        ctx = _ctx(
            outputs={"t": pa.table({"id": ["a", "b", "c"]})},
            profile_cols=(_cp("id", distinct=3),),
            plan_cols=(("id", _seed("unique")),),
        )
        outcome = run_cardinality(ctx)
        assert outcome.failed is False
        assert outcome.distinct_counts["t.id"].output_distinct == 3
        assert outcome.distinct_counts["t.id"].source_distinct == 3

    def test_unique_mode_repeat_fails(self) -> None:
        ctx = _ctx(
            outputs={"t": pa.table({"id": ["a", "b", "a"]})},
            profile_cols=(_cp("id", distinct=3),),
            plan_cols=(("id", _seed("unique")),),
        )
        outcome = run_cardinality(ctx)
        assert outcome.failed is True

    def test_match_source_deviation_warns_not_fails(self) -> None:
        ctx = _ctx(
            outputs={"t": pa.table({"g": ["a", "b", "c"]})},  # 3 distinct
            profile_cols=(_cp("g", distinct=2),),  # source had 2
            plan_cols=(("g", _seed("match_source_cardinality")),),
        )
        outcome = run_cardinality(ctx)
        assert outcome.failed is False
        codes = [w.code for w in outcome.warnings]
        assert "cardinality_match_deviation" in codes


class TestRunnerMergeAndSkip:
    def _runner_summary(self, config: dict[str, Any]) -> QualitySummary | None:
        outputs = {"t": pa.table({"id": ["a", "b", "a"]})}  # duplicate PK + unique violation
        profile = Profile(
            schema_version=1,
            tables=(TableProfile(name="t", row_count=3, columns=(_cp("id", declared_pk=True),)),),
            relationships=(),
            profiled_at=datetime(2026, 5, 28),
            decoy_engine_version="0.1.0",
        )
        plan = SimpleNamespace(
            seed_envelope=SeedEnvelope(
                job_seed=b"\x00" * 8,
                per_table=(("t", TableSeed(per_column=(("id", _seed("unique")),), per_group=())),),
            )
        )
        # Distinct source so the leakage scan does not fire (this test is about
        # pk_uniqueness + cardinality populating failed_checks).
        sources = {"t": pa.table({"id": ["x", "y", "z"]})}
        return PostValidationRunner().run(
            plan=plan,  # type: ignore[arg-type]
            execution_result=ExecutionResult(outputs=outputs, warnings=()),
            sources=sources,
            profile=profile,
            registry=_REG,
            relationship_graph=_GRAPH,
            namespace_registry=_NS,
            config=config,
        )

    def test_merge_populates_failed_checks(self) -> None:
        summary = self._runner_summary({"post_validation": True})
        assert summary is not None
        assert summary.duplicate_counts["t.id"] == 1  # from pk_uniqueness
        assert "t.id" in summary.distinct_counts  # from cardinality
        assert set(summary.failed_checks) == {"pk_uniqueness", "cardinality"}

    def test_skip_list_excludes_a_scan(self) -> None:
        summary = self._runner_summary(
            {"post_validation": True, "post_validation_skip": ["cardinality"]}
        )
        assert summary is not None
        assert "cardinality" not in summary.failed_checks
        assert "pk_uniqueness" in summary.failed_checks  # still runs
        assert summary.distinct_counts == {}  # cardinality skipped -> no distinct counts


# ---------------------------------------------------------------------------
# 24z: cardinality_collisions (deterministic faker is a keyed many-to-one pick)
# ---------------------------------------------------------------------------

_MARKER = "ZZ-MARKER-SOURCE-VALUE"
_VERSION = "z-e1-collisions"


def _faker_cfg(
    tmp_path: Path,
    values: list[str | None],
    columns: list[dict[str, Any]],
    *,
    extra: tuple[dict[str, Any], ...] = (),
    quarantine: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    data: dict[str, list[Any]] = {"a": values, "b": values}
    for col in extra:
        data[col["name"]] = col["_values"]
    src = pa.table({k: pa.array(v, type=pa.string()) for k, v in data.items()})
    path = tmp_path / "t.parquet"
    pq.write_table(src, path)
    raw: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 5},
        "sources": {"t": {"type": "file", "path": str(path), "format": "parquet"}},
        "targets": {
            "t": {"type": "file", "path": str(tmp_path / "o.parquet"), "format": "parquet"}
        },
        "tables": [
            {
                "name": "t",
                "columns": [
                    *columns,
                    *({k: v for k, v in e.items() if k != "_values"} for e in extra),
                ],
            }
        ],
    }
    if quarantine is not None:
        raw["quarantine"] = quarantine
    return PipelineConfig.model_validate(declare_rest(raw)).model_dump(), {"t": src}


def _fcol(name: str, **kw: Any) -> dict[str, Any]:
    col: dict[str, Any] = {
        "name": name,
        "strategy": "faker",
        "provider": "person_first_name",
        "namespace": f"ns_{name}",
        "deterministic": True,
    }
    col.update(kw)
    return col


def _collisions(result: Any) -> list[dict[str, Any]]:
    warns = result.quality_metrics["quality_summary"]["quality_warnings"]
    return [w for w in warns if _w(w, "code") == "cardinality_collisions"]


def _w(w: Any, key: str) -> Any:
    return w[key] if isinstance(w, dict) else getattr(w, key)


def _detail(w: Any) -> dict[str, Any]:
    return dict(_w(w, "detail"))


_DISTINCT = [f"src-{i}" for i in range(200)]


class TestCardinalityCollisionsSeed:
    def test_omitted_pool_size_stays_none_on_the_seed(self, tmp_path: Path) -> None:
        """AT-Z0 (no-regression): compile never stamps DEFAULT_POOL_SIZE on the seed."""
        from decoy_engine.execution.native._requirements import faker_pool_precondition_met_seed
        from decoy_engine.plan import compile_plan

        cfg, src = _faker_cfg(tmp_path, _DISTINCT, [_fcol("a")])
        plan = compile_plan(cfg, _profile_for(src), decoy_engine_version=_VERSION, no_profile=True)
        seed = dict(dict(plan.seed_envelope.per_table)["t"].per_column)["a"]
        assert seed.pool_size is None
        assert faker_pool_precondition_met_seed(seed) is False


def _profile_for(src: dict[str, pa.Table]) -> Profile:
    cols = tuple(_cp(n) for n in src["t"].column_names)
    return Profile(
        schema_version=1,
        tables=(TableProfile(name="t", row_count=src["t"].num_rows, columns=cols),),
        relationships=(),
        profiled_at=datetime(2026, 11, 16),
        decoy_engine_version="0.1.0",
    )


class TestCardinalityCollisions:
    def _run(
        self, tmp_path: Path, columns: list[dict[str, Any]], values: Any = None, **kw: Any
    ) -> Any:
        cfg, src = _faker_cfg(tmp_path, values if values is not None else _DISTINCT, columns, **kw)
        return run_pipeline(
            cfg, sources=src, engine_version=_VERSION, post_validation=True, **_RUN_KW
        )

    def test_reports_lost_distinct_with_effective_pool_size(self, tmp_path: Path) -> None:
        """AT-Z1: a declared pool of 10, and an omitted pool_size that reports the default."""
        values = [f"src-{i}" for i in range(3000)]
        r = self._run(tmp_path, [_fcol("a", pool_size=10), _fcol("b")], values=values)
        by_col = {_w(w, "column"): _detail(w) for w in _collisions(r)}
        a = by_col["a"]
        assert a["pool_size"] == 10
        assert a["source_distinct"] == 3000
        assert a["distinct_lost"] == a["source_distinct"] - a["output_distinct"] > 0
        assert a["table"] == "t"
        assert by_col["b"]["pool_size"] == DEFAULT_POOL_SIZE

    def test_no_source_value_in_summary_warnings_or_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """AT-Z2."""
        values = [_MARKER, *_DISTINCT]
        with caplog.at_level(logging.DEBUG):
            r = self._run(tmp_path, [_fcol("a", pool_size=10)], values=values)
        assert _collisions(r)
        assert _MARKER not in json.dumps(r.quality_metrics["quality_summary"], default=str)
        for w in r.quality_metrics["quality_summary"]["quality_warnings"]:
            assert _MARKER not in str(w)
        assert _MARKER not in caplog.text

    def test_when_gated_column_has_no_collision_entry(self, tmp_path: Path) -> None:
        """AT-Z3."""
        r = self._run(tmp_path, [_fcol("a", pool_size=10, when="b != 'src-0'")])
        assert _collisions(r) == []
        assert "t.a" in r.quality_metrics["quality_summary"]["distinct_counts"]

    def test_quarantine_counts_the_aligned_rows_only(self, tmp_path: Path) -> None:
        """AT-Z4: one row removed by another column's format_error."""
        values = [f"src-{i}" for i in range(60)]
        ages = [f"{10 + i}" for i in range(60)]
        ages[0] = "badX"
        # row 0 carries the only src-0, so a count over the unaligned source says 60, not 59
        bucket = {
            "name": "age",
            "strategy": "bucketize",
            "provider_config": {"width": 10},
            "_values": ages,
        }
        q = {
            "enabled": True,
            "output_path": str(tmp_path / "q.jsonl"),
            "triggers": ["format_error"],
        }
        r = self._run(
            tmp_path, [_fcol("a", pool_size=10)], values=values, extra=(bucket,), quarantine=q
        )
        assert r.quality_metrics["quarantine"]["total_quarantined"] == 1
        (a,) = [_detail(w) for w in _collisions(r) if _w(w, "column") == "a"]
        assert a["source_distinct"] == 59

    def test_source_distinct_follows_the_samplers_canonical_form(self) -> None:
        """AT-Z5: integer column, compared with a direct canonicalizer call."""
        from decoy_engine.kernel import canonicalize_derive_source

        ints = [1, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15] * 3
        ctx = _ctx(
            outputs={"t": pa.table({"n": pa.array([0] * len(ints), type=pa.int64())})},
            profile_cols=(_cp("n", distinct=None),),
            plan_cols=(("n", _pool_seed(pool_size=4)),),
            sources={"t": pa.table({"n": pa.array(ints, type=pa.int64())})},
        )
        (w,) = [w for w in run_cardinality(ctx).warnings if w.code == "cardinality_collisions"]
        assert w.detail["source_distinct"] == len({canonicalize_derive_source(v) for v in ints})

    def test_source_distinct_merges_values_the_sampler_canonicalizes_alike(self) -> None:
        """AT-Z5: NFC-equal strings are two raw values and one canonical value, so only the
        canonical count matches the keyed pick (raw counting would report 20 and 10 here)."""
        composed = [f"caf\u00e9{i}" for i in range(10)]
        decomposed = [f"cafe\u0301{i}" for i in range(10)]
        ctx = _ctx(
            outputs={"t": pa.table({"n": pa.array(["x"] * 20, type=pa.string())})},
            profile_cols=(_cp("n", distinct=None),),
            plan_cols=(("n", _pool_seed(pool_size=4)),),
            sources={"t": pa.table({"n": pa.array(composed + decomposed, type=pa.string())})},
        )
        (w,) = [w for w in run_cardinality(ctx).warnings if w.code == "cardinality_collisions"]
        assert w.detail["source_distinct"] == 10
        assert w.detail["distinct_lost"] == 9

    def test_both_routes_report_equal_detail(self, tmp_path: Path) -> None:
        """AT-Z6: every route that can run post-validation reports the same detail.

        `out_of_core` is refused when post-validation is on (`post_validation_requested`), because
        the scans need resident output. The streamed and chunked routes fall back to the resident
        path, so the cells are full_frame and the auto-chunk lane. `sequential` is refused the same way.
        """
        n = 200
        parent = pa.table(
            {
                "id": pa.array([f"p{i}" for i in range(n)], type=pa.string()),
                "name": pa.array([f"src-{i}" for i in range(n)], type=pa.string()),
            }
        )
        child = pa.table(
            {
                "cid": pa.array([f"c{i}" for i in range(n)], type=pa.string()),
                "parent_id": pa.array([f"p{i}" for i in range(n)], type=pa.string()),
            }
        )
        paths = {}
        for name, tbl in (("parent", parent), ("child", child)):
            paths[name] = tmp_path / f"{name}.parquet"
            pq.write_table(tbl, paths[name])

        def hash_col(name: str, ns: str) -> dict[str, Any]:
            return {"name": name, "strategy": "hash", "namespace": ns}

        raw = {
            "version": 2,
            "global_settings": {"seed": 7},
            "sources": {
                n_: {"type": "file", "path": str(p_), "format": "parquet"}
                for n_, p_ in paths.items()
            },
            "targets": {
                n_: {
                    "type": "file",
                    "path": str(tmp_path / f"{n_}.out.parquet"),
                    "format": "parquet",
                }
                for n_ in paths
            },
            "tables": [
                {"name": "parent", "columns": [hash_col("id", "ns"), _fcol("name", pool_size=10)]},
                {"name": "child", "columns": [hash_col("cid", "cns"), hash_col("parent_id", "ns")]},
            ],
            "relationships": [
                {
                    "parent": {"table": "parent", "columns": ["id"]},
                    "children": [{"table": "child", "columns": ["parent_id"]}],
                    "orphan_policy": "preserve",
                    "namespace": "ns",
                }
            ],
        }
        cfg = PipelineConfig.model_validate(declare_rest(raw)).model_dump()
        seen = []
        for kwargs in (
            {"execution_mode": "full_frame"},
            {"auto_chunk_threshold_rows": 1, "chunk_size_rows": 64},
        ):
            r = run_pipeline(
                cfg,
                sources={"parent": parent, "child": child},
                engine_version=_VERSION,
                post_validation=True,
                **kwargs,  # type: ignore[arg-type]
            )
            (w,) = _collisions(r)
            seen.append(_detail(w))
        assert seen[0] == seen[1]
        assert seen[0]["pool_size"] == 10 and seen[0]["distinct_lost"] > 0

    def test_scale_and_match_modes_are_covered(self, tmp_path: Path) -> None:
        """AT-Z6b."""
        r = self._run(
            tmp_path,
            [
                _fcol("a", pool_size=10, cardinality_mode="scale_source_cardinality"),
                _fcol("b", pool_size=10, cardinality_mode="match_source_cardinality"),
            ],
        )
        warns = r.quality_metrics["quality_summary"]["quality_warnings"]
        coll = {_w(w, "column") for w in warns if _w(w, "code") == "cardinality_collisions"}
        dev = {_w(w, "column") for w in warns if _w(w, "code") == "cardinality_match_deviation"}
        assert coll == {"a", "b"}
        assert "b" in dev


def _pool_seed(*, pool_size: int | None = None, when: str | None = None) -> ColumnSeed:
    return ColumnSeed(
        namespace="ns",
        strategy="faker",
        provider="person_first_name",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=True,
        provider_config=(("pool_size", pool_size),) if pool_size is not None else (),
        coherent_with=(),
        pool_size=pool_size,
        when=when,
    )
