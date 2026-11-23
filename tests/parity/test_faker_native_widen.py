"""FAKER-NATIVE-WIDEN: every poolable string Faker provider runs native under the default pool.

Plan: docs/plans/2026-11-22-faker-native-widen.md (revision 6 plus Amendment A1). The one
admission fact is `OPERATORS["faker"].provider_allowlist`; each cell here proves a provider on that
list takes the same route, and gives the same output, as the forced full-frame run.

`FAIL_BEFORE_PROVIDER` is a fixed sentinel outside the old two-name allowlist, so P1-P5 each carry a
genuine fail-before cell whatever the production set grows to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution._operator_registry import OPERATORS
from decoy_engine.generation.pool._builder import PoolBuilder
from decoy_engine.generation.pool._value_pool import measured_pool_bytes
from decoy_engine.providers_v2 import CapabilityMatrix, ProviderRegistry, get_default_registry
from tests.native._chunked_entry_support import NEEDS_COMPANION
from tests.parity.test_faker_default_pool import (
    _backend,
    _column,
    _faker_child_job,
    _fk_job,
    _forced_full_frame,
    _hash,
    _job,
    _run,
    _source,
)

FAIL_BEFORE_PROVIDER = "person_email"
_ALLOWLIST = OPERATORS["faker"].provider_allowlist or frozenset()
_CASES = sorted(_ALLOWLIST | {FAIL_BEFORE_PROVIDER})
_NATIVE = {"rust_pool_select", "rust_companion"}


def _shape(provider: str, *, deterministic: bool, pool_size: int | None) -> dict[str, Any]:
    return _column(
        provider,
        deterministic=deterministic or None,
        namespace="ns_fnw" if deterministic else None,
        pool_size=pool_size,
    )


# ---------------------------------------------------------------------------
# P1. Pool proof and admission.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("locale", [None, "de_DE"], ids=["en_US", "de_DE"])
@pytest.mark.parametrize("provider", _CASES)
def test_p1_the_provider_is_allowlisted_and_builds_a_pool_of_strings(
    provider: str, locale: str | None
) -> None:
    from decoy_engine.execution.native._chunked_pools import pool_values_are_strings

    assert provider in _ALLOWLIST
    pool = PoolBuilder(get_default_registry()).build(
        provider, size=10_000, job_seed=b"\x07" * 8, locale=locale
    )
    assert all(isinstance(v, str) and v for v in pool.values.tolist())
    assert pool_values_are_strings(pool)


# ---------------------------------------------------------------------------
# P2. Route parity: unified slice and chunked native.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize("rows", [2_000, 120_000])
@pytest.mark.parametrize("pool_size", [None, 500])
@pytest.mark.parametrize("deterministic", [True, False], ids=["deterministic", "positional"])
@pytest.mark.parametrize("provider", _CASES)
def test_p2_the_route_is_native_and_equals_the_forced_full_frame_run(
    tmp_path: Path, provider: str, deterministic: bool, pool_size: int | None, rows: int
) -> None:
    cfg, src = _job(
        tmp_path,
        [_shape(provider, deterministic=deterministic, pool_size=pool_size)],
        _source(rows),
    )
    got = _run(cfg, src)
    reference = _forced_full_frame(cfg, src)
    assert _backend(got) in _NATIVE
    assert _backend(reference) == "pandas_oracle"
    if rows >= 100_000:
        assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    out = got.outputs["t"]
    assert out.equals(reference.outputs["t"])  # values and schema
    assert _hash(out) == _hash(reference.outputs["t"])


@NEEDS_COMPANION
def test_p2_two_providers_in_one_chunked_table_never_share_a_pool(tmp_path: Path) -> None:
    from tests.unit.execution import _multi_table_support as mt

    rows = 120_000
    columns = [
        _column(FAIL_BEFORE_PROVIDER, name="a", deterministic=True, namespace="ns_same"),
        _column("person_phone", name="b", deterministic=True, namespace="ns_same"),
        {"name": "p", "strategy": "passthrough"},
    ]
    values = _source(rows)["f"]
    table = pa.table({"a": values, "b": values, "p": pa.array(range(rows), pa.int64())})
    cfg, src = mt.build_job(tmp_path, {"t": (columns, table)})
    got = _run(cfg, src)
    assert got.outputs["t"].equals(_forced_full_frame(cfg, src).outputs["t"])
    assert _backend(got, "a") in _NATIVE and _backend(got, "b") in _NATIVE
    assert got.outputs["t"].column("a").to_pylist() != got.outputs["t"].column("b").to_pylist()


# ---------------------------------------------------------------------------
# P3. Typed sources.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize(
    ("source_type", "deterministic"),
    [(pa.int64(), True), (pa.float64(), False)],
    ids=["int64_deterministic", "float64_positional"],
)
@pytest.mark.parametrize("provider", _CASES)
def test_p3_a_typed_source_equals_the_forced_full_frame_run(
    tmp_path: Path, provider: str, source_type: pa.DataType, deterministic: bool
) -> None:
    rows = 120_000
    values = [None if i % 13 == 0 else i % 997 for i in range(rows)]
    table = pa.table({"f": pa.array(values, source_type), "p": pa.array(range(rows), pa.int64())})
    cfg, src = _job(
        tmp_path, [_shape(provider, deterministic=deterministic, pool_size=None)], table
    )
    got = _run(cfg, src)
    assert got.quality_metrics["auto_chunk"]["mode"] == "chunked"
    assert "chunked_route" in got.quality_metrics  # admitted, not a whole-frame fallback
    assert got.outputs["t"].equals(_forced_full_frame(cfg, src).outputs["t"])


# ---------------------------------------------------------------------------
# P4. Sequential and out-of-core.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize(
    ("kw", "key"),
    [
        ({"execution_mode": "sequential"}, "sequential_faker"),
        ({"execution_mode": "out_of_core"}, "out_of_core_faker"),
    ],
    ids=["sequential", "out_of_core"],
)
@pytest.mark.parametrize("provider", _CASES)
def test_p4_a_non_key_faker_column_in_an_fk_job_runs_native(
    tmp_path: Path, provider: str, kw: dict[str, Any], key: str
) -> None:
    columns = [_column(provider, name="f", deterministic=True, namespace="ns_fnw")]
    cfg, src = _fk_job(tmp_path, columns)
    got = _run(cfg, src, out_of_core_budget_bytes=1 << 30, **kw)
    ref = _run(cfg, src, execution_mode="full_frame")
    [entry] = got.quality_metrics[key]
    assert entry["executed_backend"] in _NATIVE
    for table in ("P", "C"):
        assert got.outputs[table].equals(ref.outputs[table])


# ---------------------------------------------------------------------------
# P5. Mimesis-bound providers.
# ---------------------------------------------------------------------------


def _mimesis_cases() -> list[str]:
    # The matrix is pure data, but its package imports `mimesis`; load the file alone so the
    # always-on stub cells collect without the optional extra.
    import importlib.util

    import decoy_engine

    path = Path(decoy_engine.__file__).parent / "providers_v2" / "mimesis" / "_adoption_matrix.py"
    spec = importlib.util.spec_from_file_location("_adoption_matrix_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return sorted(module.ADOPTED_MIMESIS_PROVIDERS & (_ALLOWLIST | {FAIL_BEFORE_PROVIDER}))


class _StubMimesis:
    """A string-returning adapter bound under backend `mimesis`."""

    backend_type = "mimesis"
    backend_version = "stub-1"

    def generate(self, provider: str, *, spec: object, source_value: bytes | None = None) -> Any:
        return f"{provider}-0"

    def generate_batch(self, provider: str, *, spec: object, count: int) -> list[Any]:
        return [f"{provider}-{i}-{'x' * (i % 7)}" for i in range(count)]

    def capability_matrix(self, provider: str) -> CapabilityMatrix:
        return get_default_registry().get_capabilities(provider)


def _mimesis_registry(provider: str) -> ProviderRegistry:
    default = get_default_registry()
    caps = default.get_capabilities(provider).model_copy(
        update={"backend_type": "mimesis", "backend_version": "stub-1"}
    )
    return default.override(provider, _StubMimesis(), caps)


@NEEDS_COMPANION
@pytest.mark.parametrize("rows", [2_000, 120_000])
@pytest.mark.parametrize("provider", _mimesis_cases())
def test_p5a_a_mimesis_bound_provider_runs_native_and_equals_full_frame(
    tmp_path: Path, provider: str, rows: int
) -> None:
    cfg, src = _job(tmp_path, [_shape(provider, deterministic=True, pool_size=500)], _source(rows))
    registry = _mimesis_registry(provider)
    got = _run(cfg, src, registry=registry)
    reference = _run(cfg, src, registry=registry, auto_chunk=False, unified_slice_enabled=False)
    assert _backend(got) in _NATIVE
    assert got.outputs["t"].equals(reference.outputs["t"])


@NEEDS_COMPANION
@pytest.mark.parametrize("rows", [2_000, 120_000])
@pytest.mark.parametrize("provider", _mimesis_cases())
def test_p5b_mimesis_real_runs_native_and_equals_full_frame(
    tmp_path: Path, provider: str, rows: int
) -> None:
    pytest.importorskip("mimesis")
    cfg, src = _job(tmp_path, [_shape(provider, deterministic=True, pool_size=500)], _source(rows))
    got = _run(cfg, src)
    assert _backend(got) in _NATIVE
    assert got.outputs["t"].equals(_forced_full_frame(cfg, src).outputs["t"])


# ---------------------------------------------------------------------------
# P6. Degenerate output types (marked byte changes B1 and B2).
# ---------------------------------------------------------------------------


_DEGENERATE = [
    pa.table({"f": pa.array([None] * 12, pa.string()), "p": pa.array(range(12))}),
    pa.table({"f": pa.array([], pa.string()), "p": pa.array([], pa.int64())}),
]


@NEEDS_COMPANION
@pytest.mark.parametrize("table", _DEGENERATE, ids=["all_null", "empty"])
def test_p6_a_degenerate_unified_slice_column_is_typed_like_first_name(
    tmp_path: Path, table: pa.Table
) -> None:
    # The unified slice keeps the type pandas infers for an empty or all-null column. The new
    # providers must match `person_first_name` there; the plan text that says "string" on the
    # unified slice is wrong for first name today, so parity with it is the checked behavior.
    types = {}
    for provider in (FAIL_BEFORE_PROVIDER, "person_first_name"):
        cfg, src = _job(tmp_path / provider, [_column(provider)], table)
        types[provider] = _run(cfg, src).outputs["t"].schema.field("f").type
    assert types[FAIL_BEFORE_PROVIDER] == types["person_first_name"]


@NEEDS_COMPANION
@pytest.mark.parametrize("provider", _CASES)
def test_p6_a_degenerate_chunked_column_is_typed_string(tmp_path: Path, provider: str) -> None:
    kw = {"auto_chunk_threshold_rows": 3, "chunk_size_rows": 4}
    cfg, src = _job(tmp_path, [_column(provider)], _DEGENERATE[0])
    got = _run(cfg, src, **kw)
    assert got.outputs["t"].schema.field("f").type == pa.string()


@pytest.mark.parametrize("provider", _CASES)
def test_p6_the_full_frame_pin_covers_each_provider_on_an_all_null_int_source(
    tmp_path: Path, provider: str
) -> None:
    table = pa.table({"f": pa.array([None] * 12, pa.int64()), "p": pa.array(range(12))})
    column = _column(provider, deterministic=True, namespace="ns_fnw", pool_size=500)
    cfg, src = _job(tmp_path, [column], table)
    got = _forced_full_frame(cfg, src)
    assert got.outputs["t"].schema.field("f").type == pa.string()


# ---------------------------------------------------------------------------
# P7. An FK key column never goes native (control: unchanged behavior).
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
@pytest.mark.parametrize("provider", ["person_first_name", "synthetic_member_id"])
def test_p7_a_faker_on_an_fk_child_key_builds_no_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    from decoy_engine.execution.out_of_core import _runner
    from decoy_engine.execution.out_of_core._faker_pool import OocFakerPoolContext

    seen: list[tuple[int, int, int]] = []

    class Recording(OocFakerPoolContext):
        def close(self) -> None:
            seen.append((self.pool_count, self.reserved_bytes, self.builds))
            super().close()

    monkeypatch.setattr(_runner, "OocFakerPoolContext", Recording)
    faker_k = _column(provider, name="k", deterministic=True, namespace="ns_k")
    cfg, src = _faker_child_job(tmp_path, faker_k)
    _run(cfg, src, execution_mode="out_of_core", out_of_core_budget_bytes=100 * 1024 * 1024)
    assert seen == [(0, 0, 0)]


# ---------------------------------------------------------------------------
# P8. A custom provider that returns non-strings.
# ---------------------------------------------------------------------------


@NEEDS_COMPANION
def test_p8_a_non_string_custom_provider_fails_the_chunked_route_before_any_chunk() -> None:
    from tests.native._b8_support import run_one
    from tests.native._chunked_faker_support import (
        make_config,
        nd_faker,
        passthrough,
        source,
        split,
    )
    from tests.native.test_chunked_nondet_faker_admission import _override

    written: list[Any] = []
    with pytest.raises(Exception) as info:
        written.append(
            run_one(
                make_config([nd_faker(provider=FAIL_BEFORE_PROVIDER), passthrough("p")]),
                split(source(["a", "b", None, "c", "d", "e"]), 2),
                registry=_override(FAIL_BEFORE_PROVIDER),
                vault=True,
            )
        )
    assert getattr(info.value, "code", None) == "chunked_faker_nondeterministic_pool_not_string"
    assert written == []


@NEEDS_COMPANION
def test_p8_a_non_string_custom_provider_reroutes_on_the_unified_slice_and_succeeds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from tests.physical.test_unified_slice_faker import CountingAdapter

    default = get_default_registry()
    registry = default.override(
        FAIL_BEFORE_PROVIDER,
        CountingAdapter(lambda i: i),
        default.get_capabilities(FAIL_BEFORE_PROVIDER),
    )
    column = _column(FAIL_BEFORE_PROVIDER, deterministic=True, namespace="ns_fnw")
    cfg, src = _job(tmp_path, [column], _source(40, nulls=False))
    with caplog.at_level("INFO", logger="decoy_engine.execution._unified_slice"):
        got = _run(cfg, src, registry=registry)
    off = _run(cfg, src, registry=registry, unified_slice_enabled=False)
    assert any(
        r.getMessage().startswith("unified_slice_faker_non_string_pool_reroute")
        for r in caplog.records
    )
    assert got.outputs["t"].equals(off.outputs["t"], check_metadata=True)


# ---------------------------------------------------------------------------
# P9. The four CLI templates.
# ---------------------------------------------------------------------------

# The faker columns of C:src/decoy/templates/{hipaa,pci,gdpr,minimal}.yaml (position-keyed).
_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "hipaa": [
        ("first_name", "person_first_name"),
        ("last_name", "person_last_name"),
        ("street", "address_street"),
        ("city", "address_city"),
        ("phone", "person_phone"),
        ("fax", "person_phone"),
        ("email", "person_email"),
    ],
    "pci": [("cardholder_name", "person_name"), ("email", "person_email")],
    "gdpr": [
        ("full_name", "person_name"),
        ("email", "person_email"),
        ("phone", "person_phone"),
        ("city", "address_city"),
    ],
    "minimal": [
        ("first_name", "person_first_name"),
        ("last_name", "person_last_name"),
        ("email", "person_email"),
    ],
}


def _template_job(
    tmp_path: Path, template: str, rows: int
) -> tuple[dict[str, Any], dict[str, pa.Table], list[str]]:
    from tests.unit.execution import _multi_table_support as mt

    names = [name for name, _ in _TEMPLATES[template]]
    columns = _template_fk_columns(template, deterministic=False)
    values = pa.array([f"src{i % 977}" for i in range(rows)], pa.string())
    cfg, src = mt.build_job(tmp_path, {"t": (columns, pa.table({n: values for n in names}))})
    return cfg, src, names


@NEEDS_COMPANION
@pytest.mark.parametrize("rows", [2_000, 120_000])
@pytest.mark.parametrize("template", sorted(_TEMPLATES))
def test_p9a_every_template_faker_column_runs_native(
    tmp_path: Path, template: str, rows: int
) -> None:
    cfg, src, names = _template_job(tmp_path, template, rows)
    got = _run(cfg, src)
    for name in names:
        assert _backend(got, name) in _NATIVE, name
    assert got.outputs["t"].equals(_forced_full_frame(cfg, src).outputs["t"])


def _template_fk_columns(template: str, *, deterministic: bool) -> list[dict[str, Any]]:
    return [
        _column(
            provider,
            name=name,
            deterministic=True if deterministic else None,
            namespace=f"ns_{name}" if deterministic else None,
        )
        for name, provider in _TEMPLATES[template]
    ]


@NEEDS_COMPANION
@pytest.mark.parametrize("template", sorted(_TEMPLATES))
def test_p9a_out_of_core_declines_a_position_keyed_template_and_the_job_reroutes(
    tmp_path: Path, template: str
) -> None:
    from decoy_engine.errors import ConfigError

    cfg, src = _fk_job(tmp_path, _template_fk_columns(template, deterministic=False))
    with pytest.raises(ConfigError, match="out_of_core_faker_pool_unsupported"):
        _run(cfg, src, execution_mode="out_of_core")
    rerouted = _run(cfg, src)
    assert rerouted.outputs["P"].equals(_run(cfg, src, execution_mode="full_frame").outputs["P"])


@NEEDS_COMPANION
def test_p9b_a_deterministic_hipaa_copy_is_admitted_on_out_of_core(tmp_path: Path) -> None:
    columns = _template_fk_columns("hipaa", deterministic=True)
    cfg, src = _fk_job(tmp_path, columns)
    got = _run(cfg, src, execution_mode="out_of_core")
    assert len(got.quality_metrics["out_of_core_faker"]) == len(columns)
    assert got.outputs["P"].equals(_run(cfg, src, execution_mode="full_frame").outputs["P"])


# ---------------------------------------------------------------------------
# W1 (Amendment A1.1). The shipped construction floor and measured reservation, per family.
# ---------------------------------------------------------------------------

_FAMILIES = ("person_name", "person_email", "person_phone", "address_street")


@pytest.mark.parametrize("provider", _FAMILIES)
def test_w1_the_string_floor_applies_to_each_new_provider_family(provider: str) -> None:
    from decoy_engine.execution.out_of_core._faker_pool import _is_stock_string_provider

    assert _is_stock_string_provider(get_default_registry(), provider)


@pytest.mark.parametrize("provider", _FAMILIES)
def test_w1_a_pool_over_the_floor_is_refused_before_building_and_a_fitting_one_is_admitted(
    provider: str,
) -> None:
    from decoy_engine import reasons
    from decoy_engine.execution._errors import ExecutionError
    from decoy_engine.execution.out_of_core._faker_pool import OocFakerPoolContext
    from decoy_engine.generation.pool._value_pool import construction_floor

    builds: list[int] = []

    class Spy(PoolBuilder):
        def build(self, *a: Any, **k: Any) -> Any:
            builds.append(1)
            return super().build(*a, **k)

    registry = get_default_registry()
    small = 1_000
    budget = construction_floor(small, strings=True) * 4

    def make(size: int) -> tuple[OocFakerPoolContext, Any]:
        ctx = OocFakerPoolContext(
            registry=registry, job_seed=b"\x05" * 8, max_pool_bytes=budget, builder=Spy(registry)
        )
        return ctx, ctx.prepare(provider=provider, namespace="ns_w1", cfg={}, plan_pool_size=size)

    ctx, prepared = make(small * 100)  # the floor alone exceeds the budget
    with pytest.raises(ExecutionError) as info:
        ctx.get_pool(prepared)
    assert info.value.code == reasons.runtime.OUT_OF_CORE_FAKER_POOL_BUDGET_EXCEEDED
    assert builds == [] and ctx.builds == 0 and ctx.pool_count == 0

    ctx, prepared = make(small)  # fits
    pool = ctx.get_pool(prepared)
    assert builds == [1]
    assert ctx.reserved_bytes == measured_pool_bytes(pool) <= budget
