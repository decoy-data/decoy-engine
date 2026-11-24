"""Write and ordering model, acceptance tests 8, 9, 11 and 13 (writers and readers of one
column). Plan: `docs/plans/2026-11-22-when-reads-source.md`, "Write and ordering model"."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from tests.unit.execution.when import _write_support as ws

N = 4
FIRST = [f"F{i}" for i in range(N)]


def test_overlapping_derived_and_joint_gates(tmp_path: Path) -> None:
    """8. A gated derived `state` and a later gated joint write to `city` and `state`: the joint
    handler runs from its source key; the derived state commits last on its selected rows."""
    ref = ws.reference(tmp_path / "r.parquet", city=["JC"], state=["JS"])
    table = pa.table(
        {
            "k": pa.array(["a", "b", "c", "d"]),
            "f1": pa.array(["y", "n", "y", "n"]),
            "f2": pa.array(["n", "y", "y", "n"]),
            "city": pa.array(["c0", "c1", "c2", "c3"]),
            "state": pa.array(["s0", "s1", "s2", "s3"]),
        }
    )
    seed_plan = ws.plan(
        [
            ("state", ws.derived('concat(city, "!")', when="f1 == 'y'")),
            ("city", ws.joint(ref, ["city", "state"], when="f2 == 'y'")),
        ]
    )
    out = ws.run(seed_plan, table)
    assert out.column("state").to_pylist() == ["c0!", "JS", "JC!", "s3"]
    assert out.column("city").to_pylist() == ["c0", "JC", "JC", "c3"]


def test_truncate_reads_generated_surname() -> None:
    """9. An unconditional head `truncate` on last_name, declared after the bundle, reads the
    bundle's generated surname, not the source one."""
    table = pa.table(
        {
            "first_name": pa.array(FIRST),
            "last_name": pa.array([f"ZZZ{i}" for i in range(N)]),
            "email": pa.array([f"u{i}@x.test" for i in range(N)]),
        }
    )
    trunc = ws.seed("truncate", provider_config=(("length", 3), ("keep", "head")))
    out = ws.run(ws.plan([("first_name", ws.bundle()), ("last_name", trunc)]), table)
    oracle = ws.bundle_oracle(FIRST)["last_name"]
    assert out.column("last_name").to_pylist() == [s[:3] for s in oracle]


def test_date_shift_uses_original_group_key() -> None:
    """11. A grouped `date_shift` shifts by the ORIGINAL group key even when an earlier node masks
    that key to one value."""
    table = pa.table(
        {
            "grp": pa.array(["g1", "g2", "g3", "g4", "g5", "g6"]),
            "d": pa.array(["2020-01-01"] * 6),
        }
    )
    ds = ws.seed(
        "date_shift",
        namespace="nm",
        deterministic=True,
        provider_config=(
            ("max_shift_days", 30),
            ("group_by", "grp"),
            ("date_format", "%Y-%m-%d"),
        ),
    )
    base = ws.run(ws.plan([("d", ds)]), table, bound=(("d",),))
    masked = ws.run(ws.plan([("d", ds), ("grp", ws.seed("redact"))]), table, bound=(("d",),))
    assert set(masked.column("grp").to_pylist()) == {"REDACTED"}
    assert masked.column("d").to_pylist() == base.column("d").to_pylist()
    assert len(set(base.column("d").to_pylist())) > 1  # the shifts differ per group


def _two_table_plan() -> object:
    """Table `t` holds the unknown writer, table `u` only a reader of the same driver."""
    from types import SimpleNamespace

    from decoy_engine.plan._types import SeedEnvelope, TableSeed

    reader = ("reader", ws.derived('concat(drv, "!")'))
    t_seed = TableSeed(per_column=(reader, ("z_stub", ws.seed("z_stub"))), per_group=())
    u_seed = TableSeed(per_column=(reader,), per_group=())
    envelope = SeedEnvelope(job_seed=ws.SEED, per_table=(("t", t_seed), ("u", u_seed)))
    return SimpleNamespace(seed_envelope=envelope)


def test_unknown_writer_is_table_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """6. A strategy whose writes cannot be named may write any column of ITS OWN table: a
    reader in that table waits for it and sees its replacement; a reader in another table gets no
    edge from it."""
    from decoy_engine.execution._runner import build_work_list, column_dependency_edges
    from decoy_engine.execution._strategies import SCALAR_HANDLERS

    class Stub:
        name = "z_stub"

        def run(self, df, column, plan, ctx):  # type: ignore[no-untyped-def]
            df["drv"] = ["STUB"] * len(df)
            return df, []

    monkeypatch.setitem(SCALAR_HANDLERS, "z_stub", Stub())
    table = pa.table(
        {
            "drv": pa.array(["src"] * N),
            "reader": pa.array(["x"] * N),
            "z_stub": pa.array(["y"] * N),
        }
    )
    plan = ws.plan([("reader", ws.derived('concat(drv, "!")')), ("z_stub", ws.seed("z_stub"))])
    assert ws.run(plan, table).column("reader").to_pylist() == ["STUB!"] * N
    work = build_work_list(_two_table_plan(), ws.REG)
    edges = column_dependency_edges(work, ws.NO_GRAPH)
    assert ("t", ("z_stub",)) in edges[("t", ("reader",))]
    assert ("t", ("z_stub",)) not in edges.get(("u", ("reader",)), set())


def test_three_writers_share_one_order(tmp_path: Path) -> None:
    """13. A bundle, a joint mask and a derived creator all write `last_name`. The creator runs
    before the bundle that overwrites it. With the joint node keyed `city` it runs first and the
    bundle's surname wins; keyed `zip` it runs after the bundle and its surname wins. A fixed
    bundle priority would fail the second run."""
    table = pa.table(
        {
            "k": pa.array([f"k{i}" for i in range(N)]),
            "first_name": pa.array(FIRST),
            "last_name": pa.array([f"L{i}" for i in range(N)]),
            "email": pa.array([f"u{i}@x.test" for i in range(N)]),
            "city": pa.array([f"c{i}" for i in range(N)]),
            "zip": pa.array([f"z{i}" for i in range(N)]),
            "drv": pa.array([f"d{i}" for i in range(N)]),
        }
    )
    oracle = ws.bundle_oracle(FIRST)["last_name"]
    for key_column, expected in (("city", oracle), ("zip", ["JOINT"] * N)):
        ref = ws.reference(
            tmp_path / f"{key_column}.parquet", **{key_column: ["J"], "last_name": ["JOINT"]}
        )
        seed_plan = ws.plan(
            [
                ("first_name", ws.bundle()),
                (key_column, ws.joint(ref, [key_column, "last_name"])),
                ("last_name", ws.derived('concat(drv, "?")')),
            ]
        )
        out = ws.run(seed_plan, table)
        assert out.column("last_name").to_pylist() == expected, key_column
        assert out.column(key_column).to_pylist() == ["J"] * N
