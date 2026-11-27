"""`run_mask_chunked`: conditional masking, values, and the output-schema rule.

Covers acceptance tests 0, 2 and 3 of the dispatcher production contract. The
oracle (`run_mask_pipeline_chunked`) is the reference for values; the schema
rule pins one type per column for the strategies whose output type the native
and oracle routes otherwise disagree on.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pandas.errors import OutOfBoundsDatetime

from decoy_engine import run_mask_chunked, run_mask_pipeline_chunked
from decoy_engine.execution import ExecutionError, PandasExecutionAdapter, run_pipeline
from decoy_engine.execution.native._chunked_schema_rule import _safe_cast
from decoy_engine.execution.native._dispatch import NativeRouteEvidence
from decoy_engine.plan._errors import PlanCompileError
from tests._declared_schema import declare_rest, declared_schema
from tests.native._b8_support import run_mask_chunked_below_gate
from tests.native._chunked_entry_support import (
    COMPANION_PRESENT,
    ENGINE_VERSION,
    FORCE_ORACLE_VALUE,
    NEEDS_COMPANION,
    TABLE,
    categorical,
    column_values,
    faker_col,
    force_oracle,
    forced_reason,
    hash_col,
    is_forced,
    key_provider,
    make_config,
    passthrough,
    redact,
    split,
    string_source,
    truncate,
)


def _oracle(config: dict[str, Any], chunks: list[pa.Table]) -> list[pa.Table]:
    return list(
        run_mask_pipeline_chunked(
            config,
            list(chunks),
            table=TABLE,
            source_schema=declared_schema(config, TABLE),
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
        )
    )


def _assert_forced_on_oracle(config: dict[str, Any], evidence: list[NativeRouteEvidence]) -> None:
    """Every `force_oracle` column in `config` must have kept the table on the oracle route
    for its exact reason, so a forced leg cannot silently run natively."""
    for t in config.get("tables", ()):
        for col in t.get("columns", ()):
            if is_forced(col):
                assert len(evidence) == 1, evidence
                assert evidence[0].native_admitted is False, evidence[0]
                reason = evidence[0].reroute_reason or ""
                assert forced_reason(col["name"]) in reason


def _entry(
    config: dict[str, Any],
    chunks: list[pa.Table],
    evidence: list[NativeRouteEvidence] | None = None,
    *,
    below_gate: bool = False,
) -> list[pa.Table]:
    """Run the public entry. `below_gate` is for a test whose subject is an unconfigured column."""
    entry = run_mask_chunked_below_gate if below_gate else run_mask_chunked
    owned: list[NativeRouteEvidence] = evidence if evidence is not None else []
    out = list(
        entry(
            config,
            list(chunks),
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            route_evidence_sink=owned,
        )
    )
    _assert_forced_on_oracle(config, owned)
    return out


def _full_frame(config: dict[str, Any], source: pa.Table, tmp_path: Path) -> pa.Table:
    path = str(tmp_path / "source.parquet")
    pq.write_table(source, path)
    config = copy.deepcopy(config)
    config["sources"][TABLE] = {"type": "file", "format": "parquet", "path": path}
    config["targets"][TABLE] = {"type": "file", "format": "parquet", "path": path + ".out"}
    declare_rest(config, {TABLE: source})
    result = run_pipeline(
        config,
        {TABLE: source},
        engine_version=ENGINE_VERSION,
        execution_mode="full_frame",
        auto_chunk=False,
        key_provider=key_provider(),
        use_byte_estimate_routing=False,
        use_probe_routing=False,
    )
    return result.outputs[TABLE]


# ---------------------------------------------------------------------------
# 0. Conditional masking: a `when:` column sends the whole table to the oracle.
# ---------------------------------------------------------------------------

_WHEN_SOURCE = pa.table(
    {
        "tag": pa.array(["x", "y", None, "x", "y", "x", "x"], pa.string()),
        "s": pa.array(
            ["abcdef", "ghijkl", "mnopqr", None, "uvwxyz", "012345", "678901"], pa.string()
        ),
        "n": pa.array([1, 2, None, 4, 5, 6, 7], pa.int64()),
    }
)
_WHEN_PRED = "tag == 'x'"


def _when_config(column: dict[str, Any]) -> dict[str, Any]:
    others = [
        c
        for c in (passthrough("tag"), passthrough("s"), passthrough("n"))
        if c["name"] != column["name"]
    ]
    return make_config([{**column, "when": _WHEN_PRED}, *others])


@pytest.mark.parametrize(
    "column",
    [
        redact("s"),
        truncate("s"),
        passthrough("s"),
        hash_col("s"),
        passthrough("n"),
        redact("n", redact_with=0),
    ],
    ids=["redact", "truncate", "passthrough", "hash", "passthrough_numeric", "redact_zero_numeric"],
)
def test_when_predicate_matches_the_oracle_and_routes_by_admission(column: dict[str, Any]) -> None:
    config = _when_config(column)
    chunks = split(_WHEN_SOURCE, 3)
    evidence: list[NativeRouteEvidence] = []
    got = _entry(config, chunks, evidence)
    want = _oracle(config, chunks)

    name = column["name"]
    assert len(got) == len(want) == 3
    for g, w in zip(got, want, strict=True):
        assert g.column(name).type == w.column(name).type
        assert g.column(name).to_pylist() == w.column(name).to_pylist()
    # A redact, truncate or hash column over a string source with a closed-grammar predicate
    # is admitted natively (slice C8-i); every other column keeps the oracle leg.
    admitted = name == "s" and column["strategy"] in ("redact", "truncate", "hash")
    if admitted and (column["strategy"] != "hash" or COMPANION_PRESENT):
        assert evidence[0].native_admitted is True, evidence[0].reroute_reason
    elif admitted:
        assert evidence[0].reroute_reason == "crypto_extension_unavailable"
    else:
        assert evidence[0].native_admitted is False
        assert evidence[0].reroute_reason == f"when_predicate_not_native:{name}"
    # False and null rows keep their original value.
    if name == "s" and column["strategy"] != "passthrough":
        assert column_values(got, "s")[1] == _WHEN_SOURCE.column("s")[1].as_py()
        assert column_values(got, "s")[2] == _WHEN_SOURCE.column("s")[2].as_py()


# (column, oracle outcome, entry outcome): each is (exception type, code).
_COMPILE_REJECT = (PlanCompileError, "when_string_output_on_numeric_unsupported")


@pytest.mark.parametrize(
    ("column", "oracle_outcome", "entry_outcome"),
    [
        (
            redact("n"),
            (ExecutionError, "gated_string_output_on_numeric_unsupported"),
            _COMPILE_REJECT,
        ),
        (truncate("n"), (ExecutionError, "null_bearing_int_unsupported"), _COMPILE_REJECT),
        (
            hash_col("n"),
            (ExecutionError, "gated_hash_on_integer_unsupported"),
            (ExecutionError, "gated_hash_on_integer_unsupported"),
        ),
    ],
    ids=["redact", "truncate", "hash"],
)
def test_string_output_strategy_with_when_on_numeric_column_is_rejected_on_both_routes(
    column: dict[str, Any],
    oracle_outcome: tuple[type[BaseException], str],
    entry_outcome: tuple[type[BaseException], str],
) -> None:
    """§WHEN-NUMERIC: a `when:`-gated string-output mask on a numeric column has no single
    Arrow type, so both entry points reject the config with a coded error (fail-closed).
    The stage differs by route. The profiled entry point rejects at compile
    (`PlanCompileError`); the oracle runs without a profile, so that check is skipped and
    an execution guard rejects instead. A silent success or an uncoded Arrow type error
    fails the test."""
    config = _when_config(column)
    chunks = split(_WHEN_SOURCE, 3)

    def failure(call: Any) -> tuple[type[BaseException], Any]:
        with pytest.raises((pa.ArrowTypeError, PlanCompileError, ExecutionError)) as info:
            call()
        return type(info.value), getattr(info.value, "code", None)

    assert failure(lambda: _oracle(config, chunks)) == oracle_outcome
    assert failure(lambda: _entry(config, chunks)) == entry_outcome


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_when_is_not_a_veto(blank: str) -> None:
    config = make_config([redact("s"), passthrough("p")])
    config["tables"][0]["columns"][0]["when"] = blank
    evidence: list[NativeRouteEvidence] = []
    _entry(config, split(string_source(), 4), evidence)
    assert evidence[0].native_admitted is True


# ---------------------------------------------------------------------------
# 2. Values: chunked output equals the oracle and the full-frame run.
# ---------------------------------------------------------------------------


def _values_source() -> pa.Table:
    n = 23
    return pa.table(
        {
            "r": pa.array([None if i % 6 == 1 else f"secret-{i}" for i in range(n)], pa.string()),
            "t": pa.array([None if i % 7 == 3 else f"abcdefgh{i}" for i in range(n)], pa.string()),
            "p": pa.array([None if i % 5 == 0 else i * 3 for i in range(n)], pa.int64()),
            "h": pa.array(
                [None if i % 4 == 2 else f"user{i % 9}@x.com" for i in range(n)], pa.string()
            ),
            "f": pa.array([None if i % 8 == 5 else f"first{i % 6}" for i in range(n)], pa.string()),
            "c": pa.array([None if i % 9 == 4 else f"cat{i % 3}" for i in range(n)], pa.string()),
            "d": pa.array(
                [
                    None if i % 7 == 2 else f"2020-{1 + i % 12:02d}-{1 + i % 27:02d}"
                    for i in range(n)
                ],
                pa.string(),
            ),
        }
    )


def _assert_three_way(
    config: dict[str, Any], names: list[str], tmp_path: Path, *, expect_native: bool
) -> None:
    source = _values_source().select(names)
    chunks = split(source, 5)
    evidence: list[NativeRouteEvidence] = []
    got = _entry(config, chunks, evidence)
    want = _oracle(config, chunks)
    full = _full_frame(config, source, tmp_path)
    assert evidence[0].native_admitted is expect_native
    for name in names:
        assert column_values(got, name) == column_values(want, name), name
        assert column_values(got, name) == full.column(name).to_pylist(), name


def test_values_native_set_without_companion(tmp_path: Path) -> None:
    config = make_config([redact("r"), truncate("t"), passthrough("p")])
    _assert_three_way(config, ["r", "t", "p"], tmp_path, expect_native=True)


@NEEDS_COMPANION
def test_values_native_kernel_set_with_hash_and_faker(tmp_path: Path) -> None:
    config = make_config(
        [redact("r"), truncate("t"), passthrough("p"), hash_col("h"), faker_col("f")]
    )
    _assert_three_way(config, ["r", "t", "p", "h", "f"], tmp_path, expect_native=True)


def test_values_vetoed_strategy_runs_on_oracle_route(tmp_path: Path) -> None:
    config = make_config([redact("r"), passthrough("p"), force_oracle("d")])
    _assert_three_way(config, ["r", "p", "d"], tmp_path, expect_native=False)


# ---------------------------------------------------------------------------
# 3. Schema: one type per column across chunks and across routes.
# ---------------------------------------------------------------------------


def _forced_oracle(columns: list[dict[str, Any]]) -> dict[str, Any]:
    """The same columns plus a `force_oracle` one, which the dispatcher never admits."""
    return make_config([*columns, force_oracle("cat_force")])


def _with_force_column(source: pa.Table) -> pa.Table:
    return source.append_column(
        "cat_force", pa.array([FORCE_ORACLE_VALUE] * source.num_rows, pa.string())
    )


def _string_cols_source(values: list[str | None]) -> pa.Table:
    arr = pa.array(values, pa.string())
    return pa.table({"r": arr, "t": arr, "h": arr, "p": pa.array(range(len(values)), pa.int64())})


_SHAPES = {
    "all_null_first": lambda: [
        _string_cols_source([None, None]),
        _string_cols_source(["abcdef", None, "x"]),
    ],
    "all_null_last": lambda: [
        _string_cols_source(["abcdef", "ghijkl"]),
        _string_cols_source([None, None]),
    ],
    "empty_first": lambda: [_string_cols_source([]), _string_cols_source(["abcdef", None])],
    "empty_middle": lambda: [
        _string_cols_source(["abcdef"]),
        _string_cols_source([]),
        _string_cols_source(["ghijkl", None]),
    ],
    "empty_last": lambda: [_string_cols_source(["abcdef", None]), _string_cols_source([])],
}


def _select(chunks: list[pa.Table], names: list[str]) -> list[pa.Table]:
    return [c.select(names) for c in chunks]


def _both_routes(
    columns: list[dict[str, Any]], chunks: list[pa.Table]
) -> tuple[list[pa.Table], list[pa.Table]]:
    """Run `columns` natively, then with a `force_oracle` column that forces the oracle."""
    names = [c["name"] for c in columns]
    native_ev: list[NativeRouteEvidence] = []
    oracle_ev: list[NativeRouteEvidence] = []
    native = _entry(make_config(columns), _select(chunks, names), native_ev)
    oracle_route = _entry(
        _forced_oracle(columns), [_with_force_column(c) for c in _select(chunks, names)], oracle_ev
    )
    assert native_ev[0].native_admitted is True
    assert oracle_ev[0].native_admitted is False
    assert forced_reason("cat_force") in (oracle_ev[0].reroute_reason or "")
    return native, oracle_route


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_string_output_columns_have_one_type_on_both_routes(shape: str) -> None:
    native, oracle_route = _both_routes(
        [redact("r"), truncate("t"), passthrough("p")], _SHAPES[shape]()
    )
    for name in ("r", "t"):
        assert {c.schema.field(name).type for c in native} == {pa.string()}, name
        assert {c.schema.field(name).type for c in oracle_route} == {pa.string()}, name
        assert [c.column(name).to_pylist() for c in native] == [
            c.column(name).to_pylist() for c in oracle_route
        ]


@NEEDS_COMPANION
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_hash_column_has_one_type_on_both_routes(shape: str) -> None:
    native, oracle_route = _both_routes([hash_col("h"), passthrough("p")], _SHAPES[shape]())
    assert {c.schema.field("h").type for c in native} == {pa.string()}
    assert {c.schema.field("h").type for c in oracle_route} == {pa.string()}
    assert [c.column("h").to_pylist() for c in native] == [
        c.column("h").to_pylist() for c in oracle_route
    ]


def _mixed_values(t: pa.DataType) -> pa.Array:
    import datetime
    import decimal

    if pa.types.is_boolean(t):
        return pa.array([True, None, False], t)
    if pa.types.is_integer(t):
        return pa.array([1, None, 3], t)
    if pa.types.is_decimal(t):
        return pa.array([decimal.Decimal("1.2500"), None, decimal.Decimal("3.0000")], t)
    if pa.types.is_date32(t):
        return pa.array([datetime.date(2020, 1, 2), None, datetime.date(2021, 5, 6)], t)
    if pa.types.is_timestamp(t):
        return pa.array([1_600_000_000, None, 1_700_000_000], pa.int64()).cast(t)
    if pa.types.is_duration(t):
        return pa.array([5, None, 7], pa.int64()).cast(t)
    if pa.types.is_binary(t):
        return pa.array([b"ab", None, b"\x00\xff"], t)
    if pa.types.is_list(t):
        return pa.array([[1, 2], None, []], t)
    if pa.types.is_dictionary(t):
        return pa.array(["u", None, "v"], pa.string()).dictionary_encode().cast(t)
    return pa.array(["u", None, "v"], t)


_PASSTHROUGH_TYPES = [
    pa.int8(),
    pa.int16(),
    pa.int32(),
    pa.int64(),
    pa.uint64(),
    pa.bool_(),
    pa.large_string(),
    pa.dictionary(pa.int8(), pa.string()),
    pa.dictionary(pa.int32(), pa.string()),
    pa.decimal128(20, 4),
    pa.date32(),
    pa.timestamp("ns", tz="America/New_York"),
    pa.duration("ms"),
    pa.binary(),
    pa.list_(pa.int32()),
]


@pytest.mark.parametrize("dtype", _PASSTHROUGH_TYPES, ids=str)
@pytest.mark.parametrize("route", ["native", "oracle"])
def test_passthrough_column_is_the_source_column_on_both_routes(
    dtype: pa.DataType, route: str
) -> None:
    mixed = _mixed_values(dtype)
    all_null = pa.nulls(3, dtype)
    zero = pa.array([], dtype)
    s = pa.array(["a", "b", "c"], pa.string())
    chunks = [
        pa.table({"s": s, "p": all_null}),
        pa.table({"s": s, "p": mixed}),
        pa.table({"s": pa.array([], pa.string()), "p": zero}),
        pa.table({"s": s, "p": mixed}),
    ]
    columns = [redact("s"), passthrough("p")]
    if route == "oracle":
        config = _forced_oracle(columns)
        chunks = [_with_force_column(c) for c in chunks]
    else:
        config = make_config(columns)
    evidence: list[NativeRouteEvidence] = []
    out = _entry(config, chunks, evidence)
    assert evidence[0].native_admitted is (route == "native")
    assert len(out) == len(chunks)
    # O3: a pass-through large_string column leaves both routes as string.
    expected = pa.string() if dtype == pa.large_string() else dtype
    for got, src in zip(out, chunks, strict=True):
        assert got.schema.field("p").type == expected
        assert got.column("p").equals(src.column("p").cast(expected))


@pytest.mark.parametrize("dtype", [pa.int64(), pa.uint64()], ids=str)
@pytest.mark.parametrize("route", ["native", "oracle"])
def test_nullable_integer_passthrough_above_2_pow_53_is_exact(
    dtype: pa.DataType, route: str
) -> None:
    top = (2**63 - 1) if dtype == pa.int64() else (2**64 - 1)
    values = [2**53 + 1, None, top, 2**53 + 3, None]
    src = pa.table({"s": pa.array(list("abcde"), pa.string()), "p": pa.array(values, dtype)})
    chunks = split(src, 2)
    columns = [redact("s"), passthrough("p")]
    config = make_config(columns)
    if route == "oracle":
        config = _forced_oracle(columns)
        chunks = [_with_force_column(c) for c in chunks]
    evidence: list[NativeRouteEvidence] = []
    out = _entry(config, chunks, evidence)
    assert evidence[0].native_admitted is (route == "native")
    assert column_values(out, "p") == values
    assert all(c.schema.field("p").type == dtype for c in out)


@pytest.mark.parametrize("policy", ["warn", "error"])
def test_unconfigured_passthrough_column_is_the_source_column(policy: str) -> None:
    """Under `warn` an unconfigured column no longer vetoes the table: it runs natively
    and comes back as the source column. Under `error` the table keeps the oracle route
    and raises `undeclared_output_columns` at the first `next()`."""
    src = pa.table(
        {
            "s": pa.array(["a", None, "c", "d"], pa.string()),
            "extra": pa.array([2**53 + 1, None, 5, 6], pa.int64()),
        }
    )
    config = make_config([redact("s")], global_settings={"unconfigured_column_policy": policy})
    evidence: list[NativeRouteEvidence] = []
    if policy == "error":
        gen = run_mask_chunked_below_gate(
            config,
            split(src, 2),
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            route_evidence_sink=evidence,
        )
        with pytest.raises(ExecutionError) as info:
            next(gen)
        assert info.value.code == "undeclared_output_columns"
        assert evidence[0].native_admitted is False
        assert "uncovered_columns" in (evidence[0].reroute_reason or "")
        return
    out = _entry(config, split(src, 2), evidence, below_gate=True)
    assert evidence[0].native_admitted is True
    assert evidence[0].reroute_reason is None
    assert column_values(out, "extra") == [2**53 + 1, None, 5, 6]
    assert {c.schema.field("extra").type for c in out} == {pa.int64()}


@pytest.mark.parametrize("route", ["native", "oracle"])
def test_yielded_chunks_carry_no_pandas_metadata(route: str) -> None:
    columns = [redact("r"), truncate("t"), passthrough("p")]
    chunks = _select(
        split(_string_cols_source(["abcdef", None, "ghijkl", "mnopqr"]), 2), ["r", "t", "p"]
    )
    config = make_config(columns)
    if route == "oracle":
        config = _forced_oracle(columns)
        chunks = [_with_force_column(c) for c in chunks]
    evidence: list[NativeRouteEvidence] = []
    for chunk in _entry(config, chunks, evidence):
        meta = chunk.schema.metadata or {}
        assert b"pandas" not in meta
    assert evidence[0].native_admitted is (route == "native")


def test_non_string_redact_with_keeps_the_oracle_value_and_type() -> None:
    src = pa.table(
        {
            "n": pa.array([1, 2, None, 4, 5, 6], pa.int64()),
            "p": pa.array([1, 2, 3, 4, 5, 6], pa.int64()),
        }
    )
    config = make_config([redact("n", redact_with=0), passthrough("p")])
    chunks = split(src, 3)
    got = _entry(config, chunks)
    want = _oracle(config, chunks)
    for g, w in zip(got, want, strict=True):
        assert g.schema.field("n").type == w.schema.field("n").type
        assert g.column("n").to_pylist() == w.column("n").to_pylist()


def test_categorical_output_type_is_pinned_to_string_on_the_oracle_route() -> None:
    """A native-admissible categorical column is pinned to `string` on both chunked legs,
    so its Arrow type no longer depends on which chunk holds the nulls."""
    src = pa.table(
        {
            "c": pa.array([None, None, "a", None], pa.string()),
            "p": pa.array([1, 2, 3, 4], pa.int64()),
            "d": pa.array(["2020-03-15"] * 4, pa.string()),
        }
    )
    config = make_config([categorical("c"), passthrough("p"), force_oracle("d")])
    chunks = split(src, 2)
    evidence: list[NativeRouteEvidence] = []
    got = _entry(config, chunks, evidence)
    want = _oracle(
        make_config([categorical("c"), passthrough("p")]), [c.select(["c", "p"]) for c in chunks]
    )
    assert evidence[0].native_admitted is False
    assert {c.schema.field("c").type for c in got} == {pa.string()}
    assert [c.column("c").to_pylist() for c in got] == [c.column("c").to_pylist() for c in want]
    unpinned = [c.schema.field("c").type for c in want]
    assert unpinned[0] != unpinned[1], "the public oracle's per-chunk types differ"


@NEEDS_COMPANION
def test_values_categorical_runs_natively_and_matches_oracle_and_full_frame(
    tmp_path: Path,
) -> None:
    config = make_config([redact("r"), passthrough("p"), categorical("c")])
    _assert_three_way(config, ["r", "p", "c"], tmp_path, expect_native=True)


# ---------------------------------------------------------------------------
# One cell per contract exception class, the adapter rule, and a value-free
# `_safe_cast` message.
# ---------------------------------------------------------------------------

_E4_ROWS = 7


def _e4_source(name: str, values: list[Any], dtype: pa.DataType) -> pa.Table:
    letters = [f"s{i}" for i in range(len(values))]
    return pa.table({"s": pa.array(letters, pa.string()), name: pa.array(values, dtype)})


def test_e4_nullable_integers_agree_with_the_oracle_on_every_chunk() -> None:
    """(a) The oracle writes an untouched column from the source, so a
    nullable integer is no longer rounded through float64 and the two entries agree."""
    n_vals = [None, 2**53 + 1, 5, None, 2**63 - 1, 7, None]
    u_vals = [2**64 - 1, None, 7, 2**63 + 5, None, 9, None]
    src = pa.table(
        {
            "s": pa.array([f"s{i}" for i in range(_E4_ROWS)], pa.string()),
            "n": pa.array(n_vals, pa.int64()),
            "u": pa.array(u_vals, pa.uint64()),
        }
    )
    chunks = split(src, 2)
    config = make_config([redact("s"), passthrough("n"), passthrough("u")])
    oracle = _oracle(config, chunks)
    got = _entry(config, chunks)
    assert len(oracle) == len(got) == len(chunks)
    for chunk in oracle:
        assert chunk.schema.field("n").type == pa.int64()
        assert chunk.schema.field("u").type == pa.uint64()
    assert column_values(oracle, "n") == n_vals
    assert column_values(oracle, "u") == u_vals
    assert pa.concat_tables(oracle).equals(pa.concat_tables(got))


def test_e4_timestamp_ns_minimum_agrees_with_the_oracle() -> None:
    """(b) `-2**63` ns is pandas' NaT sentinel; the oracle used to turn it into null."""
    values = [-(2**63), None, 5, -(2**63), 7, None, 9]
    src = _e4_source("t", values, pa.timestamp("ns"))
    chunks = split(src, 2)
    config = make_config([redact("s"), passthrough("t")])
    oracle, got = _oracle(config, chunks), _entry(config, chunks)
    assert column_values(got, "t") == column_values(oracle, "t")
    assert [v is None for v in column_values(got, "t")] == [v is None for v in values]
    assert pa.concat_tables(oracle).equals(pa.concat_tables(got))


def test_e4_list_of_int64_above_2_pow_53_agrees_with_the_oracle() -> None:
    """(c) Characterization: the oracle already agreed here. It backs the contract text,
    which lists no exception for nested integers."""
    values = [[2**53 + 1, None], None, [5], [], [2**63 - 1], None, [7]]
    src = _e4_source("l", values, pa.list_(pa.int64()))
    chunks = split(src, 2)
    config = make_config([redact("s"), passthrough("l")])
    oracle, got = _oracle(config, chunks), _entry(config, chunks)
    assert column_values(got, "l") == values
    assert pa.concat_tables(oracle).equals(pa.concat_tables(got))


@pytest.mark.parametrize(
    "dtype, values",
    [
        (pa.time64("ns"), [1000, None, 3001, 5, 7, None, 9]),
        (pa.date32(), [2**31 - 1, None, 0, 1, 2, None, 3]),
    ],
    ids=["time64_ns_with_nanoseconds", "date32_outside_pandas_range"],
)
def test_e4_value_pandas_refuses_raises_on_the_oracle_and_is_exact_on_the_entry(
    dtype: pa.DataType, values: list[Any]
) -> None:
    """(d) and (e) The oracle still converts every passthrough column through pandas; the
    stock-adapter entry carries the column from the source."""
    src = _e4_source("p", values, dtype)
    chunks = split(src, 2)
    config = make_config([redact("s"), passthrough("p")])
    with pytest.raises(
        (pa.ArrowInvalid, pa.ArrowTypeError, ValueError, OverflowError, OutOfBoundsDatetime)
    ) as refused:
        _oracle(config, chunks)
    assert not isinstance(refused.value, ExecutionError)
    got = _entry(config, chunks)
    assert pa.concat_tables(got).column("p").equals(pa.chunked_array([pa.array(values, dtype)]))


def test_e9_safe_cast_message_holds_no_value_and_no_exception_context() -> None:
    marker = "MARKER-7f3a9c"
    column = pa.chunked_array([pa.array(["1", marker], pa.string())])
    with pytest.raises(ExecutionError) as caught:
        _safe_cast(column, pa.int64(), table=TABLE, name="c", chunk_index=3)
    exc = caught.value
    assert exc.code == "chunked_schema_mismatch"
    assert marker not in str(exc)
    text = str(exc)
    assert TABLE in text and "chunk 3" in text and "'c'" in text
    assert "string" in text and "int64" in text
    assert exc.__cause__ is None and exc.__context__ is None


class _StockSubclass(PandasExecutionAdapter):
    """No body: the CLI passes exactly this shape to turn the native route off."""


def test_e11_a_subclass_adapter_runs_the_oracle_leg_and_carries_nothing() -> None:
    chunks = split(_e4_source("p", [1, None, 3, 4, None, 6, 7], pa.int64()), 2)
    config = make_config([redact("s"), passthrough("p")])
    evidence: list[NativeRouteEvidence] = []
    default: list[Any] = []
    out_default = list(
        run_mask_chunked(
            config,
            list(chunks),
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            route_evidence_sink=[],
            chunk_result_sink=default,
        )
    )
    sink: list[Any] = []
    out = list(
        run_mask_chunked(
            config,
            list(chunks),
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            adapter=_StockSubclass(),
            route_evidence_sink=evidence,
            chunk_result_sink=sink,
        )
    )
    assert evidence[0].native_admitted is False
    assert evidence[0].reroute_reason == "adapter_requested"
    # The carry is off, so the passthrough column is listed as read through pandas.
    assert {tuple(r.quality_metrics["chunked_route"]["pandas_read_passthrough"]) for r in sink} == {
        ("p",)
    }
    assert {
        tuple(r.quality_metrics["chunked_route"]["pandas_read_passthrough"]) for r in default
    } == {()}
    assert column_values(out, "p") == column_values(out_default, "p")


def test_e11_an_explicit_stock_adapter_carries_like_the_default() -> None:
    """The exact stock type is the carry's other accepted value besides `None`; a
    caller that passes it explicitly must not lose the carry."""
    chunks = split(_e4_source("p", [1, None, 3, 4, None, 6, 7], pa.int64()), 2)
    config = make_config([redact("s"), passthrough("p")])
    sink: list[Any] = []
    evidence: list[NativeRouteEvidence] = []
    out = list(
        run_mask_chunked(
            config,
            list(chunks),
            table=TABLE,
            engine_version=ENGINE_VERSION,
            key_provider=key_provider(),
            adapter=PandasExecutionAdapter(),
            route_evidence_sink=evidence,
            chunk_result_sink=sink,
        )
    )
    assert {tuple(r.quality_metrics["chunked_route"]["pandas_read_passthrough"]) for r in sink} == {
        ()
    }
    assert column_values(out, "p") == [1, None, 3, 4, None, 6, 7]
