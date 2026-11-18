"""A plain profile document keeps no rare or exact cell of any column (row 24zm, AT-1 to AT-14).

Every canary test first asserts the canary is in the raw `to_dict()` and that the column is
unflagged, so a green run cannot come from a column the redactor already withholds.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from decoy_engine.profiling import (
    is_value_sensitive,
    profile_columns,
    profile_document,
    redact_profile_dict,
)
from decoy_engine.profiling._value_redaction import MIN_RELEASE_COUNT, REDACTED
from decoy_engine.profiling.sentinels import is_table_sentinel

K = MIN_RELEASE_COUNT
_SAFE = {"detector_matches": [], "pii_score": 0.0, "is_likely_unique": False}


def _col(doc: dict[str, Any], name: str) -> dict[str, Any]:
    (field,) = [f for f in doc["fields"] if f["name"] == name]
    return field


def _words(i: int) -> str:
    return (
        f"{['red', 'blue', 'green', 'gold', 'grey'][i % 5]} {['oak', 'elm', 'ash'][i % 3]} n{i:02d}"
    )


def _floor_frame() -> pd.DataFrame:
    salary = (
        [120_000] * 59 + [130_000 + 1_000 * i for i in range(47) for _ in range(20)] + [987_654]
    )
    diagnosis = (
        ["Asthma"] * 400
        + ["Diabetes"] * 300
        + ["Migraine"] * 280
        + ["Eczema"] * 10
        + ["Gout"] * 9
        + ["ZXQ-RARE-LABEL"]
    )
    visit = [pd.Timestamp("1921-06-15")] + [
        pd.Timestamp(year=2015 + i % 10, month=1 + i % 12, day=1 + i % 28) for i in range(999)
    ]
    frame = pd.DataFrame(
        {
            "salary": salary,
            "diagnosis": diagnosis,
            "note": [_words(i % 30) for i in range(1000)],
            "tier": ["A"] * 334 + ["B"] * 333 + ["C"] * 333,
            "region": ["New York"] * 500 + ["San Diego"] * 500,
            "comment": [None] * 900 + [_words(i % 10) for i in range(100)],
            "is_active": [True] * 999 + [False],
            "visited": visit,
        }
    )
    return frame.sample(frac=1.0, random_state=31).reset_index(drop=True)


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return _floor_frame()


@pytest.fixture(scope="module")
def raw(frame: pd.DataFrame) -> dict[str, Any]:
    return profile_columns(frame, "floor.csv").to_dict()


@pytest.fixture(scope="module")
def doc(frame: pd.DataFrame) -> dict[str, Any]:
    return profile_document(profile_columns(frame, "floor.csv"))


def _as_unflagged(raw: dict[str, Any], *names: str) -> dict[str, Any]:
    """Copy of a profile dict with these columns' detector hit and PII score cleared.

    The profiler always reads a native date column as an ISO date (score 0.6) and so flags it,
    so a date column only reaches the floor in a loaded document. Everything else in the entry is
    the profiler's own output.
    """
    out = json.loads(json.dumps(raw))
    for name in names:
        assert is_value_sensitive(_col(out, name)), name
        _col(out, name).update(detector_matches=[], pii_score=0.0, is_likely_unique=False)
    return out


def _unflagged(raw: dict[str, Any], *names: str) -> None:
    for name in names:
        assert not is_value_sensitive(_col(raw, name)), name


def test_at1_numeric_extremes_and_edges_are_withheld(
    raw: dict[str, Any], doc: dict[str, Any]
) -> None:
    _unflagged(raw, "salary")
    before, after = _col(raw, "salary"), _col(doc, "salary")
    assert before["max_value"] == "987654"
    assert before["top_values"][0]["count"] == 59
    assert after["max_value"] is None
    assert after["min_value"] == before["min_value"]
    dist = after["distribution"]
    assert dist["labels"] == [REDACTED] * len(before["distribution"]["labels"])
    assert dist["data"] == before["distribution"]["data"]
    assert dist["min"] is None and dist["max"] is None
    assert after["mean_value"] == before["mean_value"]
    assert "987654" not in json.dumps(after)


def test_at1_a_numeric_column_under_2k_cells_loses_its_mean() -> None:
    small = pd.DataFrame({"v": [1000 + 7 * (i % 5) for i in range(15)]})
    prof = profile_columns(small, "s.csv")
    assert not is_value_sensitive(_col(prof.to_dict(), "v"))
    out = _col(profile_document(prof), "v")
    assert out["mean_value"] is None and out["distribution"]["mean"] is None


def test_at2_a_label_under_k_rows_is_withheld(
    frame: pd.DataFrame, raw: dict[str, Any], doc: dict[str, Any]
) -> None:
    _unflagged(raw, "diagnosis")
    before, after = _col(raw, "diagnosis"), _col(doc, "diagnosis")
    assert "ZXQ-RARE-LABEL" in before["distribution"]["labels"]
    assert "ZXQ-RARE-LABEL" not in json.dumps(after)
    top = {t["value"]: t["count"] for t in before["top_values"]}
    assert top["Eczema"] == K and top["Gout"] == K - 1
    counts = Counter(frame["diagnosis"])
    labels = after["distribution"]["labels"]
    assert "Eczema" in labels and "Gout" not in labels
    for text in [*labels, *(t["value"] for t in after["top_values"])]:
        assert text == REDACTED or counts[text] >= K
    assert [t["value"] for t in after["top_values"]][-2:] == ["Eczema", REDACTED]


def test_at3_free_text_columns_release_no_string(raw: dict[str, Any], doc: dict[str, Any]) -> None:
    _unflagged(raw, "note", "comment", "region", "tier")
    assert _col(raw, "comment")["top_values"][0]["value"] == "(null)"
    for name in ("note", "comment"):
        col = _col(doc, name)
        text = json.dumps(col)
        assert not any(_words(i) in text for i in range(30)), name
        assert col["mode_value"] is None
        assert col["distribution"] is None or set(col["distribution"]["labels"]) == {REDACTED}
    region = _col(doc, "region")
    assert set(region["distribution"]["labels"]) == {"New York", "San Diego"}
    assert {t["value"] for t in region["top_values"]} == {"New York", "San Diego"}


def test_at4_one_far_out_date_is_counted_into_the_kth_decade(raw: dict[str, Any]) -> None:
    loaded = _as_unflagged(raw, "visited")
    before, after = _col(loaded, "visited"), _col(redact_profile_dict(loaded), "visited")
    assert before["date_min"].startswith("1921") and "1920s" in before["distribution"]["labels"]
    dist = after["distribution"]
    assert dist["labels"] == ["2010s", "2020s"]
    assert all(c >= K for c in dist["data"])
    assert sum(dist["data"]) == sum(before["distribution"]["data"])
    assert after["date_min"] == "2010-01-01T00:00:00"
    assert after["date_max"] == "2029-12-31T23:59:59.999999"
    assert dist["min"] == "2010-01-01" and dist["max"] == "2029-12-31"
    assert "1921" not in json.dumps(after) and "1920" not in json.dumps(after)


_TAIL_DECADES = {1950: 9, 1980: 70, 2000: 50, 2010: 62, 2020: 9}


def _tail_doc(low_decade: int = 1950, high_decade: int = 2020) -> dict[str, Any]:
    """200 dated rows whose 9th and 10th lowest, and 9th and 10th highest, sit in two decades."""
    years: list[int] = []
    for decade, n in _TAIL_DECADES.items():
        decade = low_decade if decade == 1950 else high_decade if decade == 2020 else decade
        years += [decade + i % 10 for i in range(n)]
    dates = pd.to_datetime([f"{y}-0{1 + i % 9}-1{i % 9}" for i, y in enumerate(years)])
    raw = profile_columns(pd.DataFrame({"visited": dates}), "t.csv").to_dict()
    return redact_profile_dict(_as_unflagged(raw, "visited"))


def _date_view(doc: dict[str, Any]) -> tuple[Any, ...]:
    col = _col(doc, "visited")
    dist = col["distribution"]
    return (
        dist["labels"],
        dist["data"],
        dist["min"],
        dist["max"],
        col["date_min"],
        col["date_max"],
    )


def test_at4_tail_rows_moved_past_the_kth_row_change_nothing() -> None:
    base = _date_view(_tail_doc())
    assert base[0] == ["1980s", "2000s", "2010s"]
    assert base[4] == "1980-01-01T00:00:00" and base[5] == "2019-12-31T23:59:59.999999"
    for low in (1900, 1920, 1930, 1940):
        assert _date_view(_tail_doc(low_decade=low)) == base
    for high in (2030, 2050, 2090):
        assert _date_view(_tail_doc(high_decade=high)) == base


def _decades(**counts: int) -> dict[str, Any]:
    labels = [f"{k[1:]}s" for k in counts]
    data = [float(v) for v in counts.values()]
    entry = {
        "name": "d",
        **_SAFE,
        "inferred_type": "date",
        "row_count": int(sum(data)),
        "null_count": 0,
        "date_min": "1950-01-01T00:00:00",
        "date_max": "2009-12-31T23:59:59.999999",
        "distribution": {"kind": "date", "data": data, "labels": labels, "min": "x", "max": "y"},
    }
    return redact_profile_dict({"fields": [entry]})["fields"][0]


def test_at4_nineteen_rows_code_to_one_range_and_eighteen_release_none() -> None:
    nineteen = _decades(_1950=9, _1990=1, _2000=9)
    assert nineteen["distribution"]["labels"] == ["1990s"]
    assert nineteen["distribution"]["data"] == [19.0]
    assert nineteen["date_min"] == "1990-01-01T00:00:00"
    assert nineteen["date_max"] == "1999-12-31T23:59:59.999999"
    eighteen = _decades(_1950=9, _2000=9)
    assert eighteen["distribution"]["labels"] == [REDACTED, REDACTED]
    assert eighteen["date_min"] is None and eighteen["date_max"] is None
    assert eighteen["distribution"]["min"] is None


def test_at4_a_short_date_column_and_a_string_date_column_release_no_bound() -> None:
    short = pd.DataFrame({"visited": pd.date_range("2020-01-01", periods=5)})
    raw = profile_columns(short, "s.csv").to_dict()
    out = _col(redact_profile_dict(_as_unflagged(raw, "visited")), "visited")
    assert out["distribution"]["labels"] == [REDACTED]
    assert out["date_min"] is None and out["date_max"] is None
    text = pd.DataFrame({"visited": [f"2021-03-{d:02d}" for d in range(1, 21)] * 2})
    loaded = _as_unflagged(profile_columns(text, "t.csv").to_dict(), "visited")
    before = _col(loaded, "visited")
    assert before["date_min"] is not None and before["distribution"]["kind"] != "date"
    out = _col(redact_profile_dict(loaded), "visited")
    assert out["date_min"] is None and out["date_max"] is None


def _top(value: str, count: Any) -> dict[str, Any]:
    return {"value": value, "count": count, "pct": 1.0}


def _cat(labels: list[Any], data: list[Any], *, top: Any = ()) -> dict[str, Any]:
    entry = {
        "name": "c",
        **_SAFE,
        "inferred_type": "string",
        "row_count": 1000,
        "null_count": 0,
        "top_values": list(top),
        "distribution": {"kind": "categorical", "labels": labels, "data": data},
    }
    return redact_profile_dict({"fields": [entry]})["fields"][0]


def test_at5_a_label_without_a_count_is_kept_on_the_lower_bound_of_its_share() -> None:
    out = _cat(["lo", "hi"], [1.0, 1.1])
    assert out["distribution"]["labels"] == [REDACTED, "hi"]


def test_at5_the_eleventh_other_is_the_aggregate_and_a_real_other_is_a_label() -> None:
    labels = [f"l{i}" for i in range(10)] + ["other"]
    out = _cat(labels, [1.0] * 11)
    assert out["distribution"]["labels"][10] == "other"
    assert out["distribution"]["labels"][:10] == [REDACTED] * 10
    real = _cat(["a", "b", "c", "other"], [50.0, 20.0, 20.0, 0.1])
    assert real["distribution"]["labels"] == ["a", "b", "c", REDACTED]


@pytest.mark.parametrize("share", [float("nan"), "5.0", True, None, -1.0, float("inf")], ids=repr)
def test_at5_an_unreadable_share_proves_nothing(share: Any) -> None:
    assert _cat(["x"], [share])["distribution"]["labels"] == [REDACTED]


@pytest.mark.parametrize("count", [True, "20", 20.0, -1, None], ids=repr)
def test_at6_an_ill_typed_top_value_count_proves_nothing(count: Any) -> None:
    entry = {
        "name": "c",
        **_SAFE,
        "inferred_type": "string",
        "row_count": 100,
        "null_count": 0,
        "mode_value": "m",
        "min_value": "m",
        "top_values": [_top("m", count)],
    }
    out = redact_profile_dict({"fields": [entry]})["fields"][0]
    assert out["mode_value"] is None and out["min_value"] is None
    assert out["top_values"][0]["value"] == REDACTED


@pytest.mark.parametrize("count", [True, 20, 2.5, float("nan"), -1.0], ids=repr)
def test_at6_an_ill_typed_date_bin_count_releases_no_decade(count: Any) -> None:
    entry = {
        "name": "d",
        **_SAFE,
        "inferred_type": "date",
        "row_count": 40,
        "null_count": 0,
        "date_min": "1990-01-01T00:00:00",
        "distribution": {"kind": "date", "data": [count, 20.0], "labels": ["1990s", "2000s"]},
    }
    out = redact_profile_dict({"fields": [entry]})["fields"][0]
    assert out["distribution"]["labels"] == [REDACTED, REDACTED]
    assert out["date_min"] is None


@pytest.mark.parametrize(
    "labels",
    [["1990s ", "2000s"], ["1990s\n", "2000s"], ["2000s", "1990s"], ["1990s-2009s", "2000s"]],
    ids=repr,
)
def test_at6_an_off_grammar_or_unordered_decade_label_releases_no_decade(labels: list[str]) -> None:
    entry = {
        "name": "d",
        **_SAFE,
        "inferred_type": "date",
        "row_count": 40,
        "null_count": 0,
        "distribution": {"kind": "date", "data": [20.0, 20.0], "labels": labels},
    }
    out = redact_profile_dict({"fields": [entry]})["fields"][0]
    assert out["distribution"]["labels"] == [REDACTED, REDACTED]


def test_at6_a_length_mismatch_and_unknown_shapes_fail_closed() -> None:
    assert _cat(["a", "b"], [50.0])["distribution"]["labels"] == [REDACTED, REDACTED]
    weird = {"kind": "weird", "labels": ["CANARY"], "min": "CANARY"}
    out = redact_profile_dict({"fields": [{"name": "u", **_SAFE, "distribution": weird}]})
    assert out["fields"][0]["distribution"]["labels"] == [REDACTED]
    assert out["fields"][0]["distribution"]["min"] is None
    key = {"name": "k", **_SAFE, "raw_sample": "CANARY", "top_values": "CANARY"}
    out = redact_profile_dict({"fields": [key]})["fields"][0]
    assert out["raw_sample"] == REDACTED and out["top_values"] == REDACTED


def test_at7_a_second_pass_changes_nothing_and_the_input_is_untouched(raw: dict[str, Any]) -> None:
    snapshot = json.dumps(raw, sort_keys=True)
    once = redact_profile_dict(_as_unflagged(raw, "visited"))
    assert json.dumps(raw, sort_keys=True) == snapshot
    assert redact_profile_dict(once) == once


def test_at7_two_labels_under_k_and_one_sentence_over_k_keep_one_verdict() -> None:
    entry = {"name": "m", **_SAFE, "row_count": 1000, "null_count": 0}
    entry["top_values"] = [_top("three four five", 994), _top("one", 3), _top("two", 3)]
    labels = ["one", "two", "three four five"]
    entry["distribution"] = {"kind": "categorical", "labels": labels, "data": [0.3, 0.3, 99.4]}
    first = redact_profile_dict({"fields": [entry]})
    assert set(first["fields"][0]["distribution"]["labels"]) == {REDACTED}
    assert redact_profile_dict(first) == first


def test_at7_profile_document_is_redact_profile_dict_over_to_dict(frame: pd.DataFrame) -> None:
    prof = profile_columns(frame, "floor.csv")
    assert profile_document(prof) == redact_profile_dict(prof.to_dict())


def test_at8_include_values_is_to_dict_plus_the_two_keys(raw: dict[str, Any]) -> None:
    out = redact_profile_dict(raw, include_values=True)
    assert {k: v for k, v in out.items() if k not in ("value_policy", "redacted_columns")} == raw


def test_at9_a_bool_column_and_profiled_sentinels_are_kept(
    raw: dict[str, Any], doc: dict[str, Any]
) -> None:
    assert _col(raw, "is_active")["top_values"][-1]["count"] == 1
    assert _col(doc, "is_active")["top_values"] == _col(raw, "is_active")["top_values"]
    frame = pd.DataFrame({"v": [" N/A "] + [f"cell {i % 12}" for i in range(60)]})
    prof = profile_columns(frame, "s.csv")
    assert not is_value_sensitive(_col(prof.to_dict(), "v"))
    flags = _col(prof.to_dict(), "v")["sentinels"]
    assert [f["value"] for f in flags] == ["n/a"]
    assert _col(profile_document(prof), "v")["sentinels"] == flags


def test_at12_the_demo_sample_withholds_its_two_genders() -> None:
    sample = pd.DataFrame({"gender": ["F", "M"] * 5, "id": range(10)})
    prof = profile_columns(sample, "demo.csv")
    assert not is_value_sensitive(_col(prof.to_dict(), "gender"))
    out = profile_document(prof)
    gender = _col(out, "gender")
    assert gender["mode_value"] is None
    assert {t["value"] for t in gender["top_values"]} == {REDACTED}
    assert set(gender["distribution"]["labels"]) == {REDACTED}
    assert "gender" not in out["redacted_columns"]


def test_at13_a_literal_null_marker_is_not_proven_by_the_null_count() -> None:
    cells: list[Any] = [None] * 999 + ["(null)"]
    prof = profile_columns(pd.DataFrame({"nullish": cells}), "n.csv")
    before = _col(prof.to_dict(), "nullish")
    assert not is_value_sensitive(before)
    assert before["mode_value"] == "(null)"
    last = before["top_values"][-1]
    assert (last["value"], last["count"]) == ("(null)", 1)
    out = _col(profile_document(prof), "nullish")
    assert out["mode_value"] is None and out["min_value"] is None and out["max_value"] is None
    labels = out["distribution"]["labels"] if out["distribution"] else []
    assert "(null)" not in labels
    assert [t["count"] for t in out["top_values"] if t["value"] == "(null)"] == [999]
    assert out["top_values"][-1]["value"] == REDACTED


_DOB = "DOB values outside 1880-today"


def _sentinels(*flags: dict[str, Any]) -> list[dict[str, Any]]:
    entry = {"name": "s", **_SAFE, "sentinels": list(flags)}
    return redact_profile_dict({"fields": [entry]})["fields"][0]["sentinels"]


def _flag(kind: str, value: str, count: Any, note: str) -> dict[str, Any]:
    return {"kind": kind, "value": value, "count": count, "note": note}


def test_at14_profiled_sentinels_match_their_table_and_raw_cells_are_absent() -> None:
    frame = pd.DataFrame({"v": [" N/A "] + [f"cell {i % 12}" for i in range(60)]})
    prof = profile_columns(frame, "s.csv")
    (flag,) = _col(prof.to_dict(), "v")["sentinels"]
    assert flag["value"] == "n/a"
    assert is_table_sentinel(flag["kind"], flag["value"], flag["note"], flag["count"])
    assert " N/A " not in json.dumps(profile_document(prof))
    nums = pd.DataFrame({"n": [-999, *(1000 + i % 12 for i in range(60))]})
    (nflag,) = _col(profile_columns(nums, "n.csv").to_dict(), "n")["sentinels"]
    assert nflag["value"] == "-999"
    assert is_table_sentinel(nflag["kind"], nflag["value"], nflag["note"], nflag["count"])


def test_at14_a_loaded_sentinel_off_its_table_follows_the_count_floor() -> None:
    table_note = "placeholder string 'x' - probably means missing data"
    out = _sentinels(
        _flag("string_sentinel", "Jane Q Example", 1, "free form"),
        _flag("string_sentinel", "Jane Q Example", 12, "free form"),
        _flag("string_sentinel", "x", 1, table_note),
        _flag("string_sentinel", "x", 1, "changed note"),
    )
    assert (out[0]["value"], out[0]["note"]) == (REDACTED, REDACTED)
    assert (out[1]["value"], out[1]["note"]) == ("Jane Q Example", "free form")
    assert (out[2]["value"], out[2]["note"]) == ("x", table_note)
    assert (out[3]["value"], out[3]["note"]) == (REDACTED, REDACTED)


def test_at14_an_out_of_range_value_must_equal_its_own_count() -> None:
    out = _sentinels(
        _flag("date_out_of_range", "12 value(s)", 1, _DOB),
        _flag("date_out_of_range", "1 value(s)", 1, _DOB),
        _flag("date_out_of_range", "1 value(s)", True, _DOB),
    )
    assert out[0]["value"] == REDACTED and out[0]["note"] == REDACTED
    assert out[1]["value"] == "1 value(s)" and out[1]["note"] == _DOB
    assert out[2]["value"] == REDACTED


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    strings=st.lists(st.sampled_from(["red", "green", "blue", "amber"]), min_size=1, max_size=60),
    ints=st.lists(st.integers(-5, 5), min_size=1, max_size=60),
    stamps=st.lists(st.integers(1700, 2200), min_size=1, max_size=60),
    flags=st.lists(st.booleans(), min_size=1, max_size=30),
)
def test_at11_released_text_and_buckets_are_held_by_k_rows(
    strings: list[str], ints: list[int], stamps: list[int], flags: list[bool]
) -> None:
    n = 60
    frame = pd.DataFrame(
        {
            "s": (strings * n)[:n],
            "i": (ints * n)[:n],
            "b": (flags * n)[:n],
            "t": pd.to_datetime([f"{y}-06-15" for y in (stamps * n)[:n]]),
        }
    )
    prof = profile_columns(frame, "h.csv")
    raw = _as_unflagged(prof.to_dict(), "t")
    out = redact_profile_dict(raw)
    for name in ("s", "i"):
        if is_value_sensitive(_col(raw, name)):
            continue
        counts = Counter(frame[name].astype(str))
        col = _col(out, name)
        texts = [t["value"] for t in col["top_values"]]
        texts += [col["mode_value"], col["min_value"], col["max_value"]]
        texts += col["distribution"]["labels"] if col["distribution"] else []
        for text in texts:
            assert text in (None, REDACTED, "other") or counts[text] >= K
    if is_value_sensitive(_col(raw, "t")):
        return
    col = _col(out, "t")
    dist = col["distribution"]
    assert all(c >= K for c in dist["data"]) or set(dist["labels"]) == {REDACTED}
    assert all(isinstance(c, float) for c in dist["data"])
    assert redact_profile_dict(out) == out
    years = sorted(frame["t"].dt.year)
    if len(years) >= 2 * K - 1 and years[K - 1] // 10 <= years[-K] // 10:
        assert dist["min"] == f"{years[K - 1] // 10 * 10:04d}-01-01"
        assert dist["max"] == f"{years[-K] // 10 * 10 + 9:04d}-12-31"
        assert col["date_min"] == f"{years[K - 1] // 10 * 10:04d}-01-01T00:00:00"
        assert col["date_max"] == f"{years[-K] // 10 * 10 + 9:04d}-12-31T23:59:59.999999"
    else:
        assert dist["min"] is None and col["date_min"] is None


def test_at3_the_null_marker_is_not_a_word_in_the_free_text_sample() -> None:
    entry = {"name": "c", **_SAFE, "inferred_type": "string", "row_count": 1000, "null_count": 900}
    entry["mode_value"] = "red oak n01"
    entry["top_values"] = [_top("(null)", 900), _top("red oak n01", 100)]
    out = redact_profile_dict({"fields": [entry]})["fields"][0]
    assert "red oak n01" not in json.dumps(out)
    assert out["mode_value"] is None


def _numeric_entry(
    top_counts: list[int],
    rows: int,
    sentinel: tuple[str, int] | None = None,
    null_count: Any = 0,
    last_text: str | None = None,
) -> dict[str, Any]:
    texts = [str(100 + i) for i in range(len(top_counts))]
    if last_text is not None:
        texts[-1] = last_text
    tops = [_top(t, c) for t, c in zip(texts, top_counts, strict=True)]
    entry = {
        "name": "n",
        **_SAFE,
        "inferred_type": "integer",
        "row_count": rows,
        "null_count": null_count,
        "mean_value": "123.4",
        "top_values": tops,
        "distribution": {"kind": "numeric", "data": [1.0], "labels": ["a"], "mean": 123.4},
    }
    if sentinel is not None:
        note = "-1 - common 'unknown / no parent' sentinel"
        flag = {
            "kind": "numeric_sentinel",
            "value": sentinel[0],
            "count": sentinel[1],
            "note": note,
        }
        entry["sentinels"] = [flag]
    return entry


@pytest.mark.parametrize(
    ("top_counts", "rows", "sentinel", "kept"),
    [
        ([20, 20, 20, 20, 17], 100, None, False),  # 3 rows outside the released values
        ([20, 20, 20, 20, 11], 100, None, False),  # 9 rows outside
        ([20, 20, 20, 20, 10], 100, None, True),  # 10 rows outside
        ([20, 20, 20, 20, 20], 100, None, True),  # none outside
        ([20, 20, 20, 20, 5], 100, None, True),  # the 5-row value is not released, 14 outside
        ([20, 20], 50, ("-1", 9), False),  # a kept -1 flag covers 9 rows; 1 row is left
        ([20, 20], 49, ("-1", 9), True),  # the flag covers the rest
        ([20, 20], 60, ("-1", 10), True),  # 10 rows left: nothing a reader can isolate
        ([20, 20, 12], 52, ("-1", 12), True),  # -1 is also a top value: its rows count once
        ([20, 20, 12], 53, ("-1", 12), False),  # and one row is left outside both
    ],
)
def test_the_mean_is_withheld_when_one_to_k_minus_one_rows_sit_outside_the_top_values(
    top_counts: list[int], rows: int, sentinel: tuple[str, int] | None, kept: bool
) -> None:
    entry = _numeric_entry(top_counts, rows, sentinel, last_text="-1" if rows in (52, 53) else None)
    out = redact_profile_dict({"fields": [entry]})["fields"][0]
    assert (out["mean_value"] == "123.4") is kept
    assert (out["distribution"]["mean"] == 123.4) is kept


@pytest.mark.parametrize("null_count", [True, False, "0", 0.0, None, -1], ids=repr)
def test_an_ill_typed_null_count_withholds_the_mean(null_count: Any) -> None:
    entry = _numeric_entry([20, 20, 20, 20, 20], 100, None, null_count)
    out = redact_profile_dict({"fields": [entry]})["fields"][0]
    assert out["mean_value"] is None and out["distribution"]["mean"] is None
