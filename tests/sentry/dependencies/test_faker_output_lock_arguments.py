"""Sentry: caller-supplied arguments cannot move Faker output unseen (FAKER-MIGRATE, AT-L16 to
AT-L20).

Callers reach Faker with arguments through four seams: YAML `faker_kwargs` into the reflected
wrapper, the same mapping into the `address` wrapper, `ProviderSpec.extra` into the V2 adapter, and
formula arguments. `argument_grid.py` derives the targets from the runtime callables and their
signatures and one grid of rows from them; the lock stores the grid once and a digest per locale and
row. The static cells prove the derivation is complete, closed and bounded. The marked cells prove
a change that only an argument can reach turns the lock red (those cells carry the marker and
live in `test_faker_output_lock.py`, the only marked file).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from tests.sentry.dependencies._faker_output_lock_support import (
    _load_lock,
    _minimal_lock,
    derived_surface,
    output_lock,
)

ag = output_lock.argument_grid


def test_the_directly_changed_no_argument_cell_is_blind_without_the_grid() -> None:
    # The no-argument reflected `random_int` cell does not read `min`/`max`: only a row can.
    grid, _ = derived_surface()
    row = grid["reflected.random_int.min_max_equal"]
    assert row["arguments"]["kwargs"] == {"min": 7, "max": 7} and "en_US" in row["locales"]


def test_every_discovered_parameter_has_a_grid_row() -> None:
    grid, prov = derived_surface()
    assert ag.uncovered(grid, prov) == [] and ag.stray(grid, prov) == []
    for (loc, family, target), params in prov.items():
        ids = [i for i, r in grid.items() if r["family"] == family and r["target"] == target]
        assert not params or any(loc in grid[i]["locales"] for i in ids), (loc, family, target)
        if family in ("address_override", "adapter") and not params:
            assert f"{family}.{target}.unexpected_keyword" in ids
        if family == "formula" and params:
            assert any(i.startswith(f"formula.{target}.positional_") for i in ids), target
    # The check sees a missing row: drop one and the parameter is reported.
    cut = {k: v for k, v in grid.items() if k != "reflected.random_int.step_set"}
    assert any(n.endswith("reflected random_int step") for n in ag.uncovered(cut, prov))


def test_an_unclassified_parameter_name_fails_closed() -> None:
    def probe(zz_probe=None):
        return zz_probe

    with pytest.raises(output_lock.OutputLockError):
        ag.params_of(probe)


def test_derived_argument_grid_is_closed_and_bounded() -> None:
    grid, prov = derived_surface()
    assert ag.ROW_LIMIT == 64_000 and ag.BYTE_LIMIT == 32 * 1024 * 1024
    assert ag.projected_rows(grid) <= ag.ROW_LIMIT
    lock = _load_lock()
    assert ag.text_within_limit(output_lock.canonical_text(lock))
    assert list(grid) == sorted(grid)
    for case_id, row in grid.items():
        assert case_id.startswith(f"{row['family']}.{row['target']}.")
        assert ag.arguments_ok(row["arguments"]) and row["covers"] == sorted(set(row["covers"]))
        for d in (*row["arguments"]["args"], *row["arguments"]["kwargs"].values()):
            again = ag.encode_descriptor(ag.decode_descriptor(d))
            assert json.dumps(again, sort_keys=True) == json.dumps(d, sort_keys=True)
    # The equal-boundary rule produces these two required rows.
    for case in ("reflected.random_int.min_max_equal", "adapter.random_int_range.min_max_equal"):
        assert grid[case]["arguments"] == {"args": [], "kwargs": {"min": 7, "max": 7}}


@pytest.mark.parametrize(
    "bad",
    [
        {"date": 1},
        {"date": "2000-13-45"},
        {"date": "2000-01-01\n"},
        {"datetime": "2000-01-01"},
        {"date": "2000-01-01", "x": 1},
        {"when": "2000-01-01"},
        {"tuple": "ab"},
        {"mapping": {1: 2}},
        {"mapping": {"a": {"when": 1}}},
        {"tuple": [{"tuple": [{"tuple": [{"tuple": [{"tuple": []}]}]}]}]},
        float("nan"),
        [1],
        {},
    ],
)
def test_descriptor_codec_refuses_unknown_forms(bad: Any) -> None:
    assert not ag.descriptor_ok(bad)
    with pytest.raises(output_lock.OutputLockError):
        ag.decode_descriptor(bad)


def test_descriptor_codec_round_trips_every_tagged_form() -> None:
    for d in (
        None,
        True,
        7,
        0.5,
        "x",
        {"date": "2001-03-04"},
        {"datetime": "2001-03-04T05:06:07"},
        {"tuple": ["a", 1, {"date": "2001-03-04"}]},
        {"mapping": {"a": {"tuple": [1]}}},
    ):
        assert ag.descriptor_ok(d)
        assert ag.encode_descriptor(ag.decode_descriptor(d)) == d


def test_known_argument_families_are_exact() -> None:
    grid, prov = derived_surface()
    found = {family for (_, family, _) in prov}
    assert found == set(ag.FAMILIES)
    for family in ag.FAMILIES:
        assert any(f == family for (_, f, _) in prov), family
    # Discovery cannot silently lose a method or family: the committed grid is its output.
    assert grid == _load_lock()["argument_grid"]


def test_a_formula_callable_rebound_through_an_alias_is_still_found() -> None:
    import _engine_access as access

    fake = access.make_faker("en_US")
    scope = access.formula_scope(fake)
    alias = scope["date_between"]
    target = ag._formula_target(access, fake, "renamed_helper", alias)
    assert target is not None and target.method == "date_between"
    assert [p.name for p in target.params] == ["start_date", "end_date"]


def test_a_changed_grid_row_is_named_by_family_target_and_case() -> None:
    old = _minimal_lock()["argument_grid"]
    new = copy.deepcopy(old)
    new["reflected.random_int.min_max_equal"]["arguments"]["kwargs"]["max"] = 8
    diff = output_lock.diff_grid(old, new)
    assert diff["changed"] == [
        "grid reflected random_int reflected.random_int.min_max_equal arguments"
    ]
    assert output_lock.diff_grid(old, {})["removed"] and output_lock.diff_grid({}, old)["added"]
