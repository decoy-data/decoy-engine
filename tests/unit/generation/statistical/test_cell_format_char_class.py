"""FIT-CODES-TEXT engine acceptance tests E1 to E7: the digit-only freetext `char_class`."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from decoy_engine.generation.statistical import (
    StatisticalSpecError,
    sample_column,
    spec_from_dict,
    spec_to_dict,
)
from decoy_engine.profiling._snapshot_values import distribution_snapshot_document
from decoy_engine.quality.snapshot import compute_distribution_snapshot
from tests.unit.generation._cf_routes_support import config, pinned, stat, whole, write_snapshot
from tests.unit.generation.statistical._cf_support import fit, spec_of

CODE = "statistical_cell_format_invalid"
FIVE = re.compile(r"[0-9]{5}")
# Arabic-Indic, full-width and superscript digits: five characters each, none ASCII 0-9.
UNICODE_CELLS = (
    "\u0660\u0662\u0661\u0663\u0664",
    "\uff10\uff12\uff11\uff13\uff14",
    "12\u00b245",
)


def _zips(n: int = 200) -> list[str]:
    return [f"{i * 37 % 100_000:05d}" for i in range(n)]


def _frame(cells: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"zip": cells})


def _block(cells: list[str]) -> dict[str, Any]:
    return fit(_frame(cells))["columns"]["zip"]["cell_format"]


# E1 learn


def test_e1_digit_only_column_learns_the_class() -> None:
    cells = _zips()
    assert any(c.startswith("0") for c in cells)  # non-vacuity: leading zeros are present
    snap = fit(_frame(cells))
    assert snap["columns"]["zip"]["kind"] == "freetext"
    assert snap["columns"]["zip"]["cell_format"] == {"blank_count": 0, "char_class": "digits"}


@pytest.mark.parametrize("bad", ["12a45", " 1234", "1234\n", *UNICODE_CELLS])
def test_e1_any_non_ascii_digit_cell_keeps_the_column_without_the_member(bad: str) -> None:
    cells = _zips()
    cells[7] = bad
    block = _block(cells)
    assert "char_class" not in block
    assert block["blank_count"] == 0


def test_e1_blanks_do_not_block_the_class_but_all_blank_does() -> None:
    cells = _zips()
    cells[3] = ""
    assert _block(cells) == {"blank_count": 1, "char_class": "digits"}
    assert "char_class" not in _block([""] * 200)


def test_e1_other_kinds_never_get_the_member() -> None:
    frame = pd.DataFrame({"n": range(200), "c": ["01", "02"] * 100})
    columns = fit(frame)["columns"]
    assert all("char_class" not in col["cell_format"] for col in columns.values())


# E2 sample


def test_e2_sampled_values_are_five_digit_strings() -> None:
    snap = fit(_frame(_zips()))
    out = sample_column(spec_of(snap, "zip"), 2_000, col_seed=7)
    assert all(v is not None and FIVE.fullmatch(v) for v in out)
    assert any(v.startswith("0") for v in out)


def test_e2_lengths_follow_the_fitted_histogram() -> None:
    cells = ["1" * 3] * 100 + ["2" * 8] * 100
    out = sample_column(spec_of(fit(_frame(cells)), "zip"), 2_000, col_seed=7)
    assert {len(v) for v in out} <= set(range(3, 9))
    assert all(v.isascii() and v.isdigit() for v in out)


# E3 routes


def test_e3_pinned_plan_route_draws_digits_and_matches_whole(tmp_path: Path) -> None:
    file = write_snapshot(tmp_path / "zip.json", fit(_frame(_zips())))
    cfg = config([stat(file, "zip")], rows=1_000)
    values = pinned(cfg).column("zip").to_pylist()
    assert all(FIVE.fullmatch(v) for v in values)
    assert any(v.startswith("0") for v in values)
    assert values == whole(cfg).column("zip").to_pylist()


def test_e3_stored_spec_round_trips_the_member() -> None:
    spec = spec_of(fit(_frame(_zips())), "zip")
    stored = spec_to_dict(spec)
    assert stored["cell_format"]["char_class"] == "digits"
    assert spec_from_dict(json.loads(json.dumps(stored))) == spec


# E4 redacted


def test_e4_redacted_document_carries_the_token_and_no_cell_value() -> None:
    cells = _zips()
    doc = distribution_snapshot_document(_frame(cells), include_values=False)
    assert doc["schema_version"].endswith("/v2")
    block = doc["columns"]["zip"]["cell_format"]
    assert block == {"blank_count": 0, "char_class": "digits"}
    text = json.dumps(doc)
    assert not any(f'"{c}"' in text for c in cells[:50])


def test_e4_scrub_nulls_any_value_but_the_token() -> None:
    from decoy_engine.profiling.cell_format import scrub_cell_format

    assert scrub_cell_format("freetext", {"char_class": "digits"}) == {"char_class": "digits"}
    assert scrub_cell_format("freetext", {"char_class": "02134"}) == {"char_class": None}
    assert scrub_cell_format("numeric", {"char_class": "digits"}) == {"char_class": None}


# E5 strict decode


def _with(snap: dict[str, Any], column: str, **members: Any) -> dict[str, Any]:
    out = copy.deepcopy(snap)
    out["columns"][column]["cell_format"].update(members)
    return out


@pytest.mark.parametrize("bad", ["letters", "02134", "DIGITS", "", None, True, 5, ["digits"]])
def test_e5_a_value_other_than_digits_is_refused_naming_the_member(bad: Any) -> None:
    snap = _with(fit(_frame(_zips())), "zip", char_class=bad)
    with pytest.raises(StatisticalSpecError) as err:
        spec_of(snap, "zip")
    assert err.value.code == CODE
    assert "char_class" in str(err.value)
    assert "02134" not in str(err.value)


def test_e5_the_member_on_a_numeric_entry_is_refused() -> None:
    snap = fit(pd.DataFrame({"n": [i * 0.5 for i in range(200)]}))
    with pytest.raises(StatisticalSpecError) as err:
        spec_of(_with(snap, "n", char_class="digits"), "n")
    assert err.value.code == CODE


def test_e5_the_stored_form_refuses_a_misplaced_member() -> None:
    stored = spec_to_dict(spec_of(fit(pd.DataFrame({"n": [i * 0.5 for i in range(200)]})), "n"))
    stored["cell_format"]["char_class"] = "digits"
    with pytest.raises(StatisticalSpecError) as err:
        spec_from_dict(stored)
    assert err.value.code == CODE


# E6 unchanged


def test_e6_a_snapshot_without_the_member_draws_lorem_as_before() -> None:
    snap = fit(_frame(_zips()))
    stripped = copy.deepcopy(snap)
    del stripped["columns"]["zip"]["cell_format"]["char_class"]
    out = sample_column(spec_of(stripped, "zip"), 500, col_seed=7)
    assert any(not v.isdigit() for v in out)
    assert "char_class" not in spec_to_dict(spec_of(stripped, "zip"))["cell_format"]


def test_e6_a_pinned_spec_written_before_the_member_still_loads() -> None:
    stored = spec_to_dict(spec_of(fit(pd.DataFrame({"t": [f"w{i}" for i in range(200)]})), "t"))
    assert "char_class" not in stored["cell_format"]
    fmt = spec_from_dict(stored).cell_format
    assert fmt is not None and fmt.char_class is None


# E7 both tags


def test_e7_both_writers_write_the_member_and_load_spec_accepts_each() -> None:
    frame = _frame(_zips())
    v1 = compute_distribution_snapshot(frame, cell_format=True)
    v2 = distribution_snapshot_document(frame, include_values=False)
    assert v1["schema_version"] != v2["schema_version"]
    for snap in (v1, v2):
        snap = json.loads(json.dumps(snap))
        assert snap["columns"]["zip"]["cell_format"]["char_class"] == "digits"
        fmt = spec_of(snap, "zip").cell_format
        assert fmt is not None and fmt.char_class == "digits"


def test_e7_include_values_keeps_the_v1_tag_and_the_member() -> None:
    doc = distribution_snapshot_document(_frame(_zips()), include_values=True)
    assert doc["columns"]["zip"]["cell_format"]["char_class"] == "digits"
