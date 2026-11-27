"""S2a runs main's ordering: plans whose output the branch's extra ordering edges had changed.

Plan: `docs/plans/2026-11-22-when-reads-source.md`, revision 2.6. Plans A and B are red on PR head
`880ec2afc` (its `_composite_overwrites` edge ran the bundle last); F2 is red there with a
read-only assignment error; every expected value is main's output.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from decoy_engine.execution._errors import ExecutionError
from tests.unit.execution.when import _write_support as ws
from tests.unit.execution.when import test_write_order as tw

N = tw.N
FIRST = tw.FIRST
ROUTES = [ws.run, ws.run_sequential]
ROUTE_IDS = ["adapter", "sequential"]


def _table() -> pa.Table:
    return pa.table(
        {
            "first_name": pa.array(FIRST),
            "last_name": pa.array([f"L{i}" for i in range(N)]),
            "email": pa.array([f"u{i}@x.test" for i in range(N)]),
        }
    )


@pytest.mark.parametrize("run", ROUTES, ids=ROUTE_IDS)
def test_plan_a_derived_email_reads_the_masked_first_name(run: object) -> None:
    """A `first_name` bundle and `email = concat(first_name, "!")`. The derived email runs after
    the bundle on main, so every email is the masked first name plus `!`."""
    seed_plan = ws.plan(
        [("first_name", ws.bundle()), ("email", ws.derived('concat(first_name, "!")'))]
    )
    out = run(seed_plan, _table())  # type: ignore[operator]
    assert out.column("email").to_pylist() == [
        f + "!" for f in out.column("first_name").to_pylist()
    ]
    assert out.column("first_name").to_pylist() == ws.bundle_oracle(FIRST)["first_name"]


@pytest.mark.parametrize("run", ROUTES, ids=ROUTE_IDS)
def test_plan_b_derived_surname_reads_the_bundle_email(run: object) -> None:
    """A `first_name` bundle and `last_name = concat(email, "?")`: every surname is the bundle
    email plus `?` on main, not overwritten by the bundle."""
    seed_plan = ws.plan(
        [("first_name", ws.bundle()), ("last_name", ws.derived('concat(email, "?")'))]
    )
    out = run(seed_plan, _table())  # type: ignore[operator]
    assert out.column("last_name").to_pylist() == [e + "?" for e in out.column("email").to_pylist()]
    assert out.column("email").to_pylist() == ws.bundle_oracle(FIRST)["email"]


@pytest.mark.parametrize("run", ROUTES, ids=ROUTE_IDS)
def test_gated_partial_email_matches_main(run: object) -> None:
    """F2. A derived email gated on the source `first_name == 'F0'`, with copy-on-write on and
    off. Rows the gate matches take the output of main's run with the gate removed; the others
    take the output of main's run with the gated node removed (the bundle's email)."""
    import pandas as pd

    table = tw._indirect_table([f"u{i}@x.test" for i in range(N)]).drop_columns(["z_view"])

    def plan(gated: bool, with_email: bool = True) -> object:
        cols = [("first_name", ws.bundle())]
        if with_email:
            when = "first_name == 'F0'" if gated else None
            cols.append(("email", ws.derived('concat(summary, "@x.test")', when=when)))
        cols.append(("summary", ws.derived('concat(last_name, "!")')))
        return ws.plan(cols)

    for cow in (False, True):
        with pd.option_context("mode.copy_on_write", cow):
            gated = run(plan(True), table)  # type: ignore[operator]
            ungated = run(plan(False), table)  # type: ignore[operator]
            no_email = run(plan(True, with_email=False), table)  # type: ignore[operator]
        want = [
            ungated.column("email")[i].as_py()
            if first == "F0"
            else no_email.column("email")[i].as_py()
            for i, first in enumerate(FIRST)
        ]
        assert gated.column("email").to_pylist() == want, cow
        assert want[0] != want[1]  # the gate does select a strict subset


@pytest.mark.parametrize("run", ROUTES, ids=ROUTE_IDS)
def test_bundle_key_follows_main_queue_order(run: object, tmp_path: Path) -> None:
    """F3 (characterization). A bundle keyed on `last_name` and a joint writer that sets every
    surname to `JOINT`. Main runs the bundle where the queue puts it, and the output below is what
    main gives at `8ee461e0f` (captured with the same fixture on main). S2b row
    `WRS-S2B-BUNDLE-KEY-EDGE` adds the edge that would change it."""
    ref = ws.reference(tmp_path / "j.parquet", last_name=["JOINT"])
    seed_plan = ws.plan(
        [
            ("first_name", ws.bundle(coherent_with=("last_name",))),
            ("last_name", ws.joint(ref, ["last_name"])),
            ("email", ws.derived('concat(summary, "@x.test")')),
            ("summary", ws.derived('concat(last_name, "!")')),
        ]
    )
    table = pa.table(
        {"k": pa.array([f"k{i}" for i in range(N)]), **tw._indirect_table([""] * N).to_pydict()}
    )
    out = run(seed_plan, table, bound=(("first_name", "last_name"),))  # type: ignore[operator]
    assert out.column("last_name").to_pylist() == ["JOINT"] * N
    assert out.column("summary").to_pylist() == ["JOINT!"] * N
    assert out.column("email").to_pylist() == ["JOINT!@x.test"] * N
    assert out.column("first_name").to_pylist() == ["Todd", "Stephen", "William", "James"]


@pytest.mark.parametrize("entry", ["classify_job", "run_single", "run_sequential"], ids=lambda e: e)
def test_two_derived_columns_reading_each_other_are_refused(entry: str) -> None:
    """Case 4d, the one refusal control: it raises `cyclic_work_ordering` from every entry point,
    as on main."""
    table = pa.table({"a": pa.array(["1"] * N), "b": pa.array(["2"] * N)})
    cyclic = ws.plan([("a", ws.derived('concat(b, "!")')), ("b", ws.derived('concat(a, "?")'))])
    call = {
        "classify_job": lambda: ws.classify(cyclic, table),
        "run_single": lambda: ws.run(cyclic, table, bound=(("a",),)),
        "run_sequential": lambda: ws.run_sequential(cyclic, table, bound=(("a",),)),
    }[entry]
    with pytest.raises(ExecutionError) as err:
        call()
    assert err.value.code == "cyclic_work_ordering"
