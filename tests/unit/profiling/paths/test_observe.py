"""F07 82-E2b: bounded path-observation discovery (acceptance tests AT-E2-1 and 4 to 6, 8 to 13)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from decoy_engine._canonical import (
    SCAN_ARRAY_ITEMS,
    SCAN_CELL_BYTES,
    SCAN_MAP_KEYS,
    SCAN_MAX_CELLS,
    SCAN_MAX_DEPTH,
    SCAN_MAX_PATHS,
)
from decoy_engine.profiling import paths, scan_set_to_dict
from decoy_engine.profiling.paths import _walk

from ._support import by_path, dumps, observation, ref, scan_cells, warning_codes


def test_at_e2_1_paths_use_wildcards_with_exact_counts(tmp_path: Path) -> None:
    cells = []
    for i in range(10):
        email = None if i == 8 else f"user{i}@example.com"
        user: dict[str, Any] = {} if i == 9 else {"email": email}
        sku = None if i == 3 else f"S{i}"
        cells.append({"user": user, "items": [{"sku": sku}]})
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    found = by_path(obs)
    assert "$.items[*].sku" in found and "$.user.email" in found
    assert not any("[0]" in p for p in found)
    email = found["$.user.email"]
    assert email.detector_hits == ["email"]
    assert (email.present_count, email.null_count) == (9, 1)
    assert list(email.kinds) == ["string"]
    sku = found["$.items[*].sku"]
    assert (sku.present_count, sku.null_count) == (10, 1)
    assert (found["$.user"].present_count, list(found["$.user"].kinds)) == (10, ["object"])
    assert list(found["$.items"].kinds) == ["array"]
    assert (obs.cells_sampled, obs.cells_parsed) == (10, 10)


@pytest.mark.parametrize("keys, collapsed", [(65, True), (SCAN_MAP_KEYS, False)])
def test_at_e2_4_a_level_over_the_key_limit_collapses(
    tmp_path: Path, keys: int, collapsed: bool
) -> None:
    cell = {f"field_{n:03d}": 1 for n in range(keys)}
    scan = scan_cells(tmp_path, dumps([cell] * 3))
    obs = observation(scan)
    found = by_path(obs)
    if collapsed:
        assert set(found) == {"$.*"}
        assert obs.map_collapsed == 1
    else:
        assert len(found) == SCAN_MAP_KEYS and "$.*" not in found
        assert obs.map_collapsed == 0


def _deep(levels: int) -> Any:
    value: Any = 1
    for _ in range(levels):
        value = {"a": value}
    return value


def test_at_e2_5_depth_bound(tmp_path: Path) -> None:
    deep = dumps([_deep(SCAN_MAX_DEPTH + 1)] * 3)
    obs = observation(scan_cells(tmp_path, deep))
    assert obs.depth_truncated_cells == 3
    assert "$" + ".a" * SCAN_MAX_DEPTH in by_path(obs)
    assert "$" + ".a" * (SCAN_MAX_DEPTH + 1) not in by_path(obs)
    scan = scan_cells(tmp_path, deep)
    assert ref("NESTED_CELLS_UNREADABLE") in warning_codes(scan)
    control = scan_cells(tmp_path, dumps([_deep(SCAN_MAX_DEPTH)] * 3))
    assert observation(control).depth_truncated_cells == 0
    assert ref("NESTED_CELLS_UNREADABLE") not in warning_codes(control)


def test_at_e2_5_array_item_bound(tmp_path: Path) -> None:
    items: list[Any] = [{"a": 1}] * SCAN_ARRAY_ITEMS + [{"late": 1}]
    obs = observation(scan_cells(tmp_path, dumps([{"items": items}] * 3)))
    assert obs.arrays_truncated == 3
    assert "$.items[*].a" in by_path(obs) and "$.items[*].late" not in by_path(obs)
    full = observation(scan_cells(tmp_path, dumps([{"items": items[:SCAN_ARRAY_ITEMS]}] * 3)))
    assert full.arrays_truncated == 0


def test_at_e2_5_cell_byte_bound(tmp_path: Path) -> None:
    def padded(size: int) -> str:
        head, tail = '{"k": "', '"}'
        return head + "x" * (size - len(head) - len(tail)) + tail

    good = ['{"k": "a"}', '{"k": "b"}']
    scan = scan_cells(tmp_path, [*good, padded(SCAN_CELL_BYTES + 1)])
    obs = observation(scan)
    assert (obs.cells_oversized, obs.cells_parsed, obs.cells_sampled) == (1, 2, 3)
    assert ref("NESTED_CELLS_UNREADABLE") in warning_codes(scan)
    exact = observation(scan_cells(tmp_path, [*good, padded(SCAN_CELL_BYTES)]))
    assert (exact.cells_oversized, exact.cells_parsed) == (0, 3)


def test_at_e2_5_cell_count_bound_holds_for_a_full_read(tmp_path: Path) -> None:
    cells = ['{"a": 1}'] * (SCAN_MAX_CELLS + 1)
    obs = observation(scan_cells(tmp_path, cells, strategy="full"))
    assert (obs.cells_sampled, obs.cells_parsed) == (SCAN_MAX_CELLS, SCAN_MAX_CELLS)
    assert by_path(obs)["$.a"].present_count == SCAN_MAX_CELLS


def test_at_e2_5_path_cap_and_map_collapse_in_one_column(tmp_path: Path) -> None:
    groups = 12
    cell: dict[str, Any] = {"m": {f"inner_{n:03d}": 1 for n in range(100)}}
    cell.update({f"grp_{g:02d}": {f"leaf_{n:02d}": 1 for n in range(22)} for g in range(groups)})
    scan = scan_cells(tmp_path, dumps([cell] * 3))
    obs = observation(scan)
    found = by_path(obs)
    assert obs.paths_truncated and len(found) == SCAN_MAX_PATHS
    assert obs.map_collapsed == 1
    assert "$.m.*" in found and not any(p.startswith("$.m.inner") for p in found)
    assert ref("NESTED_PATHS_TRUNCATED") in warning_codes(scan)
    # Without the 12th group the same column fits: the 100 collapsed keys took no path slot.
    del cell["grp_11"]
    fits = observation(scan_cells(tmp_path, dumps([cell] * 3)))
    assert not fits.paths_truncated and len(fits.paths) < SCAN_MAX_PATHS


def test_at_e2_6_present_null_malformed_and_mixed_kinds(tmp_path: Path) -> None:
    cells = ['{"v": 1}', '{"v": "x"}', '{"v": null}', "{}", '{"v": ', '{"v": 2}', '{"v": "y"}']
    scan = scan_cells(tmp_path, cells)
    obs = observation(scan)
    value = by_path(obs)["$.v"]
    assert (value.present_count, value.null_count) == (5, 1)
    assert list(value.kinds) == ["integer", "string"]
    assert (obs.cells_malformed, obs.cells_parsed, obs.cells_sampled) == (1, 6, 7)
    assert ref("NESTED_CELLS_UNREADABLE") in warning_codes(scan)


def test_at_e2_8_other_columns_get_no_nested_and_bytes_repeat(tmp_path: Path) -> None:
    plain = scan_cells(tmp_path, ["hello", "world", "plain text {with braces}"])
    assert observation(plain) is None
    mostly_text = ['{"a": 1}'] * 3 + ["text"] * 7
    assert observation(scan_cells(tmp_path, mostly_text)) is None
    doc = scan_set_to_dict(plain, detail=False)
    assert doc["tables"][0]["fields"][0]["nested"] is None

    cells = dumps([{"z": {"y": 1, "b": 2}, "a": [1, 2], "m": "s"}] * 4)
    first = scan_set_to_dict(scan_cells(tmp_path, cells), detail=False)["tables"]
    second = scan_set_to_dict(scan_cells(tmp_path, cells), detail=False)["tables"]
    assert json.dumps(first) == json.dumps(second)
    listed = [p["path"] for p in first[0]["fields"][0]["nested"]["paths"]]
    assert listed == sorted(listed) and len(listed) > 3


def test_at_e2_9_the_switch_skips_qualification_and_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = paths.observe_frame

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(paths, "observe_frame", spy)
    cells = dumps([{"a": 1}] * 3)
    off = scan_cells(tmp_path, cells, nested_paths=False)
    assert calls == [] and off.tables[0].nested == {}
    assert scan_set_to_dict(off, detail=False)["tables"][0]["fields"][0]["nested"] is None
    on = scan_cells(tmp_path, cells)
    assert calls == [1] and observation(on) is not None


def test_at_e2_10_keys_that_are_data_collapse(tmp_path: Path) -> None:
    names = [f"Name{n}" for n in range(20)]
    scan = scan_cells(tmp_path, dumps([{name: 1} for name in names]))
    obs = observation(scan)
    assert set(by_path(obs)) == {"$.*"}
    assert obs.key_suspect_collapsed == 20
    assert ref("NESTED_PATH_KEY_SUSPECT") in warning_codes(scan)


def test_at_e2_10_appearance_rule_one_of_twenty_collapses_two_of_twenty_stays(
    tmp_path: Path,
) -> None:
    cells: list[dict[str, Any]] = [{"common": 1} for _ in range(20)]
    cells[0]["once"] = 1
    cells[0]["twice"] = 1
    cells[1]["twice"] = 1
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    assert set(by_path(obs)) == {"$.common", "$.twice", "$.*"}
    assert obs.key_suspect_collapsed == 1


def test_at_e2_10_a_key_a_detector_hits_collapses_but_its_siblings_stay(tmp_path: Path) -> None:
    cells = dumps([{"status": "ok", "GB82WEST12345698765432": "x", "note": "n"}] * 4)
    obs = observation(scan_cells(tmp_path, cells))
    assert set(by_path(obs)) == {"$.status", "$.note", "$.*"}
    assert obs.key_suspect_collapsed == 4


def test_at_e2_10_one_qualifying_cell_collapses_every_key(tmp_path: Path) -> None:
    obs = observation(scan_cells(tmp_path, ['{"a": {"b": 1}}']))
    assert set(by_path(obs)) == {"$.*", "$.*.*"}


def test_at_e2_11_plain_strings_are_never_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.profiling.paths import _observe

    calls: list[int] = []
    real = _observe.strict_json_read

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(_observe, "strict_json_read", spy)
    scan = scan_cells(tmp_path, ["alpha", "beta", "x {not json}", "  gamma"])
    assert calls == [] and observation(scan) is None
    scan_cells(tmp_path, ['{"a": 1}', '{"a": 2}'])
    assert len(calls) >= 2


class _Probe(_walk.Levels):
    """Records the most keys the pass-1 state ever held (`widest`) and every key it was asked to store."""

    widest = 0
    stored: list[str] = []

    def add(self, level: Any, key: str) -> None:
        super().add(level, key)
        type(self).widest = max(type(self).widest, self.key_total)
        type(self).stored.append(key)


def test_at_e2_12_a_map_of_maps_keeps_bounded_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Probe.widest, _Probe.stored = 0, []
    monkeypatch.setattr(_walk, "Levels", _Probe)
    cell = {f"outer_{o:03d}": {f"inner_{i:03d}": 1 for i in range(100)} for o in range(100)}
    text = json.dumps(cell)
    obs = observation(scan_cells(tmp_path, [text] * 100))
    assert set(by_path(obs)) == {"$.*", "$.*.*"}
    assert obs.map_collapsed == 2
    assert 0 < _Probe.widest <= SCAN_MAX_PATHS * (SCAN_MAP_KEYS + 1)
    # Two levels exist, each held to its key limit as it was read: no end-of-pass collapse.
    assert _Probe.widest <= 2 * (SCAN_MAP_KEYS + 1)


def test_at_e2_12_a_key_that_fails_a_rule_is_never_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _Probe.widest, _Probe.stored = 0, []
    monkeypatch.setattr(_walk, "Levels", _Probe)
    cell = {"alice@example.com": 1, "name\n": 2, "123": 3, "GB82WEST12345698765432": 4, "ok": 5}
    scan_cells(tmp_path, dumps([cell] * 3))
    assert _Probe.stored == ["ok"]


def test_at_e2_13_non_finite_literals_are_number_leaves(tmp_path: Path) -> None:
    cells = ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e400}', '{"a": 7}']
    obs = observation(scan_cells(tmp_path, cells * 2))
    assert obs.cells_malformed == 0 and obs.cells_parsed == 10
    leaf = by_path(obs)["$.a"]
    assert list(leaf.kinds) == ["integer", "number"] and leaf.present_count == 10


def test_python_dict_and_list_cells_are_walked_without_a_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pandas as pd

    from decoy_engine.profiling.paths import _observe

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a dict cell is not parsed")

    monkeypatch.setattr(_observe, "strict_json_read", refuse)
    frame = pd.DataFrame(
        {
            "objs": [{"a": 1, "b": True}, {"a": 2, "b": None}, None],
            "lists": [[1, 2], [3], []],
            "ints": [1, 2, 3],
        }
    )
    found = paths.observe_frame(frame)
    assert set(found) == {"objs", "lists"}
    objs = {p.path: p for p in found["objs"].paths}
    assert list(objs["$.a"].kinds) == ["integer"] and list(objs["$.b"].kinds) == ["boolean"]
    assert (objs["$.b"].present_count, objs["$.b"].null_count) == (2, 1)
    assert found["objs"].cells_sampled == 2
    assert {p.path for p in found["lists"].paths} == {"$[*]"}


# -- review fixes: fold of dropped keys, the share half of rule 3, rule 1b, list values ---------


def test_fold_inner_fields_of_name_keyed_records_keep_their_paths_and_hits(tmp_path: Path) -> None:
    names = ["Maria", "Ahmed", "Chen", "Olga", "Pedro", "Aiko", "Lars", "Nia", "Omar", "Tess"]
    cells = [
        {
            f"{n}{i}": {
                "email": f"{n.lower()}{i}@example.com",
                "city": "Springfield",
                "tier": "gold",
                "note": "x",
            }
        }
        for i, n in enumerate(names * 2)
    ]
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    found = by_path(obs)
    assert "$.*" in found and "$.*.email" in found
    assert found["$.*.email"].detector_hits == ["email"]
    assert {"$.*.city", "$.*.tier", "$.*.note"} <= set(found)
    assert found["$.*.email"].present_count == 20


def test_fold_id_keyed_records_keep_the_ssn_hit(tmp_path: Path) -> None:
    cells = [
        {f"emp_{i:03d}": {"ssn": f"{101 + i}-45-{6700 + i}", "role": "clerk"}} for i in range(20)
    ]
    found = by_path(observation(scan_cells(tmp_path, dumps(cells))))
    assert found["$.*.ssn"].detector_hits == ["ssn"]


def test_fold_keeps_a_level_under_a_kept_key_apart_from_the_folded_ones(tmp_path: Path) -> None:
    cells = [{"stable": {"a_key": 1}, f"Name{i}": {"b_key": 2}} for i in range(20)]
    found = by_path(observation(scan_cells(tmp_path, dumps(cells))))
    assert {"$.stable.a_key", "$.*.b_key"} <= set(found)
    assert "$.stable.b_key" not in found


def test_rule_3_share_a_key_in_two_of_thirty_cells_collapses(tmp_path: Path) -> None:
    cells: list[dict[str, Any]] = [{"common": 1} for _ in range(30)]
    cells[0]["rare"] = 1
    cells[1]["rare"] = 1
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    assert set(by_path(obs)) == {"$.common", "$.*"}
    assert obs.key_suspect_collapsed == 2


def test_rule_3_count_a_key_in_one_of_five_cells_collapses(tmp_path: Path) -> None:
    cells: list[dict[str, Any]] = [{"common": 1} for _ in range(5)]
    cells[0]["single"] = 1
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    assert set(by_path(obs)) == {"$.common", "$.*"}


@pytest.mark.parametrize("key", ["acct_12345", "d20240102", "zip90210", "p5551234567"])
def test_rule_1b_a_key_with_a_run_of_four_digits_is_a_wildcard(tmp_path: Path, key: str) -> None:
    obs = observation(scan_cells(tmp_path, dumps([{key: 1, "status": 2}] * 5)))
    assert set(by_path(obs)) == {"$.status", "$.*"}
    assert key not in str(obs)


@pytest.mark.parametrize("key", ["line1", "v2", "sha256", "col_123", "a1b2c3"])
def test_rule_1b_short_digit_runs_keep_their_name(tmp_path: Path, key: str) -> None:
    obs = observation(scan_cells(tmp_path, dumps([{key: 1, "status": 2}] * 5)))
    assert f"$.{key}" in by_path(obs)


def test_numpy_arrays_from_parquet_are_walked_as_arrays() -> None:
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame(
        {
            "lst": [np.array([1, 2]), np.array([3]), np.array([4, 5, 6])],
            "st": [{"a": np.array(["x", "y"])}, {"a": np.array(["z"])}, {"a": np.array(["w"])}],
        }
    )
    found = paths.observe_frame(frame)
    assert set(found) == {"lst", "st"}
    lst = {p.path: p for p in found["lst"].paths}
    assert list(lst["$[*]"].kinds) == ["integer"]
    st = {p.path: p for p in found["st"].paths}
    assert list(st["$.a"].kinds) == ["array"] and list(st["$.a[*]"].kinds) == ["string"]


def test_a_parquet_list_column_is_observed_from_its_frame(tmp_path: Path) -> None:
    # `scan_sources` itself cannot profile a list column yet (the profiler hashes cells), so the
    # frame a parquet reader returns is observed directly.
    pytest.importorskip("pyarrow")
    import pandas as pd

    path = tmp_path / "t.parquet"
    pd.DataFrame(
        {"tags": [["a", "b"], ["c"], ["d", "e"]], "row": [{"k": 1}, {"k": 2}, {"k": 3}]}
    ).to_parquet(path)
    found = paths.observe_frame(pd.read_parquet(path))
    assert {p.path for p in found["tags"].paths} == {"$[*]"}
    assert {p.path for p in found["row"].paths} == {"$.k"}


def test_fold_counts_a_key_once_per_cell_not_once_per_folded_sibling(tmp_path: Path) -> None:
    cell = {"Maria": {"x": 1}, "Bob": {"x": 2}}
    found = by_path(observation(scan_cells(tmp_path, dumps([cell]))))
    assert set(found) == {"$.*", "$.*.*"}


def test_fold_names_the_inner_key_when_it_repeats_across_enough_cells(tmp_path: Path) -> None:
    cells = [{f"Maria{i}": {"x": 1}, f"Bob{i}": {"x": 2}} for i in range(5)]
    found = by_path(observation(scan_cells(tmp_path, dumps(cells))))
    assert "$.*.x" in found and found["$.*.x"].present_count == 5


def test_fold_share_uses_distinct_cells_as_the_denominator(tmp_path: Path) -> None:
    # `x` sits in 2 of 30 cells (under 10%). Summed sibling cells would read 2 of 5 and keep it.
    cells: list[dict[str, Any]] = [{f"Name{i}": {"y": 1}} for i in range(28)]
    cells += [{"Maria": {"x": 1}, "Bob": {"x": 2}}, {"Ann": {"x": 3}, "Cy": {"x": 4}}]
    found = by_path(observation(scan_cells(tmp_path, dumps(cells))))
    assert "$.*.x" not in found and "$.*.y" in found


def test_an_array_cell_is_cut_to_the_item_cap_before_it_is_converted() -> None:
    import numpy as np
    import pandas as pd

    from decoy_engine._canonical import SCAN_ARRAY_ITEMS

    converted: list[int] = []

    class Spy(np.ndarray):
        def tolist(self) -> Any:
            converted.append(len(self))
            return super().tolist()

    cells = [np.arange(SCAN_ARRAY_ITEMS * 50).view(Spy) for _ in range(3)]
    obs = paths.observe_column(pd.Series(cells, dtype=object))
    assert obs is not None and obs.arrays_truncated == 3
    assert converted and max(converted) <= SCAN_ARRAY_ITEMS
    assert {p.path for p in obs.paths} == {"$[*]"}


# -- review round 2: a collapse folds its named children, and every named segment is earned ------

_SEGMENT = re.compile(r"\.[^.\[]+|\[\*\]")


def assert_every_named_segment_is_earned(obs: Any) -> None:
    """Each key written by name is in at least 2 cells and a tenth of its parent's cells."""
    from decoy_engine._canonical import SCAN_KEY_APPEARANCE

    present = {p.path: p.present_count for p in obs.paths}
    kinds = {p.path: list(p.kinds) for p in obs.paths}
    for path in present:
        parts = _SEGMENT.findall(path[1:])
        for i, part in enumerate(parts):
            if part == "[*]" or part == ".*":
                continue
            here = "$" + "".join(parts[: i + 1])
            above = "$" + "".join(parts[:i])
            parent = obs.cells_parsed if above == "$" else present[above]
            assert present[here] >= 2, (path, present[here])
            if above == "$" or kinds[above] == ["object"]:  # a mixed parent counts non-objects too
                assert present[here] / parent >= SCAN_KEY_APPEARANCE, (path, present[here], parent)


def _repro_a() -> list[dict[str, Any]]:
    names = [f"feat_{n:03d}" for n in range(65)]
    cells: list[dict[str, Any]] = [{"m": {names[i % 64]: {"id": 1}}} for i in range(1000)]
    cells.append({"m": {names[64]: {"id": 1}}})
    cells += [{"m": {"q": {"zorblax" if i < 3 else "id": 1}}} for i in range(19)]
    return cells


def _repro_b() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = [{f"Usr_{i:03d}": {f"fld_{i:03d}": {"id": 1}}} for i in range(70)]
    cells += [{"bad-key": {"bad-2": {"zorblax" if i < 2 else "id": 1}}} for i in range(10)]
    return cells


def test_a_late_collapse_judges_the_wildcard_level_on_all_its_cells(tmp_path: Path) -> None:
    obs = observation(scan_cells(tmp_path, dumps(_repro_a())))
    found = by_path(obs)
    assert "$.m.*.zorblax" not in found and "$.m.*.id" in found
    assert found["$.m.*.id"].present_count == 1017
    assert_every_named_segment_is_earned(obs)


def test_a_collapse_by_fold_judges_the_wildcard_level_on_all_its_cells(tmp_path: Path) -> None:
    obs = observation(scan_cells(tmp_path, dumps(_repro_b())))
    assert "$.*.*.zorblax" not in by_path(obs)
    assert_every_named_segment_is_earned(obs)


def test_fold_into_a_level_that_already_collapsed_keeps_the_cells(tmp_path: Path) -> None:
    # `$.*` collapses in cell 0 (65 keys under a key that is not a name). `zorblax` sits in 2 cells
    # under it and in none of the 40 later cells that fold in; those cells must count.
    cells: list[dict[str, Any]] = [
        {"bad-key": {f"fld_{n:03d}": {"id": 1, "zorblax": 1} for n in range(65)}},
        {"bad-key": {"fld_000": {"zorblax": 1}}},
    ]
    cells += [{f"Usr_{i:03d}": {f"fld_x{i:03d}": {"id": 1}}} for i in range(40)]
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    assert "$.*.*.zorblax" not in by_path(obs)
    assert_every_named_segment_is_earned(obs)


def test_fold_of_a_collapsed_level_collapses_the_level_it_lands_on(tmp_path: Path) -> None:
    cells: list[dict[str, Any]] = [{"bad-key": {"a_key": 1}} for _ in range(10)]
    cells.append({"Usr_one": {f"fld_{n:03d}": 1 for n in range(65)}})
    found = by_path(observation(scan_cells(tmp_path, dumps(cells))))
    assert "$.*.a_key" not in found and "$.*.*" in found


def test_fold_that_pushes_a_level_over_the_key_limit_collapses_it(tmp_path: Path) -> None:
    cells = [
        {"Usr_zero": {f"k_{n:03d}": 1 for n in range(40)}},
        {"Usr_one": {f"k_{n:03d}": 1 for n in range(30, 70)}},
    ]
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    assert set(by_path(obs)) == {"$.*", "$.*.*"} and obs.map_collapsed >= 1


def test_a_name_is_dropped_for_a_cell_pass_1_never_counted(tmp_path: Path) -> None:
    # Cells 0 and 1 give two dropped keys whose `x` folds into `$.*`. Cell 2 fills the level cap,
    # so cell 3's object under `bad-key` is never counted at `$.*` in pass 1. It must not be named.
    fill = {f"grp_{g}": {f"leaf_{n:02d}": {} for n in range(62)} for g in range(5)}
    cells: list[dict[str, Any]] = [
        {"Maria": {"x": 1}},
        {"Bob": {"x": 1}},
        {"fill": fill},
        {"bad-key": {"x": 1}},
    ]
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    found = by_path(obs)
    assert found["$.*.x"].present_count == 2
    assert found["$.*.*"].present_count >= 1
    assert_every_named_segment_is_earned(obs)


def test_rule_3_keeps_a_key_at_exactly_a_tenth_of_the_cells(tmp_path: Path) -> None:
    cells: list[dict[str, Any]] = [{"common": 1} for _ in range(30)]
    for i in range(3):
        cells[i]["tenth"] = 1
    found = by_path(observation(scan_cells(tmp_path, dumps(cells))))
    assert "$.tenth" in found


@pytest.mark.parametrize("seed", range(6))
def test_random_trees_never_name_a_key_the_rule_would_drop(tmp_path: Path, seed: int) -> None:
    import random

    rng = random.Random(seed)
    words = ["alpha", "beta", "gamma", "delta"]

    def tree(depth: int) -> Any:
        roll = rng.random()
        if depth == 0 or roll < 0.25:
            return rng.choice([1, "x", None, True])
        if roll < 0.55:  # a record
            return {w: tree(depth - 1) for w in words if rng.random() < 0.6}
        if roll < 0.8:  # a map of data-looking or random keys
            return {
                f"fld_{rng.randrange(400):03d}": tree(depth - 1)
                for _ in range(rng.choice([1, 3, 70]))
            }
        return [tree(depth - 1) for _ in range(rng.randrange(4))]

    cells = [
        {"root": tree(3), rng.choice(["Usr_a", "Usr_b", "bad-key"]): tree(3)} for _ in range(120)
    ]
    obs = observation(scan_cells(tmp_path, dumps(cells)))
    assert_every_named_segment_is_earned(obs)
