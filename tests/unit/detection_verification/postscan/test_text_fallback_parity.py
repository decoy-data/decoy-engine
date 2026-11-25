"""The runner's text fallback keeps the frame check's equality (G8-S1, AT-12 and AT-13).

A column Arrow refuses is carried as one text key per cell. The keys must count equal cells
as identical exactly as pandas `==` does (AT-12). Where the keys cannot, the table fails with
a fixed class name instead of grading the column on keys that disagree with the cells
(AT-13). All values are synthetic."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from fractions import Fraction
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from decoy_engine.internal.cell_text import detector_text, key_text
from decoy_engine.verification.postmask import post_scan_verdict, run_post_mask
from decoy_engine.verification.postmask import runner as runner_module
from decoy_engine.verification.postmask._column_facts import canonical_cells, identity_counts
from decoy_engine.verification.postmask.residual_pii import check_residual_pii

BACKSTOP = "ComparisonNotPreservedError"
SENTINEL = "x-sentinel"  # one text cell, so Arrow refuses the column natively
EMAILS = [f"user{i}@realmail.com" for i in range(64)]
FAKE = [f"fake{i}@masked.example" for i in range(64)]


def _cfg(*columns: tuple[str, str]) -> dict[str, Any]:
    return {
        "version": 2,
        "tables": [{"name": "t", "columns": [{"name": c, "strategy": s} for c, s in columns]}],
    }


def _texted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The columns the runner carried as text keys."""
    seen: list[str] = []
    real = runner_module._text

    def text(series: pd.Series) -> Any:
        seen.append(str(series.name))
        return real(series)

    monkeypatch.setattr(runner_module, "_text", text)
    return seen


def _both_paths(
    src: pd.DataFrame, out: pd.DataFrame, config: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report = run_post_mask({"t": src}, {"t": out}, config=config)
    residual = [asdict(f) for f in check_residual_pii({"t": out}, config, source_frames={"t": src})]
    return report, residual


def _keys(series: pd.Series) -> pd.Series:
    return pd.Series(key_text(series), dtype=object)


GRADED = ("severity", "match_rate", "source_identity_rate")


def _assert_same_grades(report: dict[str, Any], residual: list[dict[str, Any]]) -> None:
    """Every frame-path hit is graded the same on the runner path.

    The runner may report extra hits: its keys print a whole float as an integer, which a
    detector can match where the frame text does not."""
    runner = {(f["column"], f["detector_id"]): f for f in report["residual_pii"]}
    for hit in residual:
        graded = runner[(hit["column"], hit["detector_id"])]
        assert {k: graded[k] for k in GRADED} == {k: hit[k] for k in GRADED}


# ----- AT-12: one equality rule through the text fallback ---------------------------------------

WHOLE = [10000.0 + i for i in range(38)]
FRACTIONS = [1.5, 0.25]


def _float_case(kind: Any) -> tuple[list[Any], list[Any]]:
    src = [kind(v) for v in [*WHOLE, *FRACTIONS]]
    return src, [float(c) for c in src]


def _int_case(kind: Any) -> tuple[list[Any], list[Any]]:
    src = [kind(v) for v in range(1, 41)]
    return src, [float(int(c)) for c in src]


FLOATS = [np.float16, np.float32, np.float64, np.longdouble]
INTS = [np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64]
STAMPS = [pd.Timestamp("2020-01-01") + pd.Timedelta(hours=i) for i in range(40)]
CASES: dict[str, tuple[list[Any], list[Any]]] = {
    **{f"{k.__name__}_vs_float": _float_case(k) for k in FLOATS},
    **{f"{k.__name__}_vs_float": _int_case(k) for k in INTS},
    "bool_vs_int": ([np.bool_(i % 2) for i in range(40)], [i % 2 for i in range(40)]),
    "decimal_vs_float": ([Decimal(str(v)) for v in [*WHOLE, *FRACTIONS]], [*WHOLE, *FRACTIONS]),
    "int_vs_float": ([int(v) for v in WHOLE], list(WHOLE)),
    "float_vs_int": (list(WHOLE), [int(v) for v in WHOLE]),
    "datetime64_vs_timestamp": ([np.datetime64(s) for s in STAMPS], STAMPS),
    "timedelta64_vs_timedelta": (
        [np.timedelta64(i + 1, "D") for i in range(40)],
        [pd.Timedelta(days=i + 1) for i in range(40)],
    ),
}


@pytest.mark.parametrize("case", list(CASES))
def test_equal_cells_of_two_types_keep_their_identity_through_the_text_keys(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cells, equal = CASES[case]
    src = pd.Series([*cells, cells[0]], dtype=object, name="v")
    out = pd.Series([*equal, SENTINEL], dtype=object, name="v")
    texted = _texted(monkeypatch)
    # The raw counts: every equal pair is identical as cells and as keys.
    assert identity_counts(src, out) == (len(src), len(src) - 1)
    assert identity_counts(_keys(src), _keys(out)) == identity_counts(src, out)
    report, residual = _both_paths(src.to_frame(), out.to_frame(), _cfg(("v", "faker")))
    assert "v" in texted
    _assert_same_grades(report, residual)
    assert "error" not in {f["severity"] for f in report["residual_pii"]}


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (np.timedelta64(1, "D"), pd.Timedelta(days=1)),
        (np.bool_(True), 1),
        (np.bool_(False), 0),
        (np.float64(1.5), 1.5),
        (np.float32(0.25), 0.25),
        (np.float32(12345.0), 12345),
        (np.datetime64("2020-01-01T00:00:00"), pd.Timestamp("2020-01-01")),
    ],
    ids=[
        "timedelta",
        "bool_true",
        "bool_false",
        "float64_half",
        "float32_quarter",
        "float32_whole",
        "datetime",
    ],
)
def test_one_equal_scalar_pair_has_one_key(left: Any, right: Any) -> None:
    pair = pd.Series([left, right], dtype=object)
    assert bool(pair[0] == pair[1])
    first, second = key_text(pair)
    assert first == second


def test_round_1_a_float32_zip_leak_fails_on_both_paths_and_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zips = [10000 + i for i in range(60)]
    cells = [*map(np.float32, zips), np.float32(99999)]
    src = pd.DataFrame({"zip": pd.Series(cells, dtype=object)})
    out = pd.DataFrame({"zip": pd.Series([*zips, "changed"], dtype=object)})
    texted = _texted(monkeypatch)
    report, residual = _both_paths(src, out, _cfg(("zip", "faker")))
    assert "zip" in texted
    (finding,) = report["residual_pii"]
    assert finding["severity"] == "fail"
    assert finding["source_identity_rate"] == pytest.approx(60 / 61)
    _assert_same_grades(report, residual)
    assert len(residual) == 1
    verdict = post_scan_verdict(report)
    assert verdict.blocking
    assert [c.code for c in verdict.codes] == ["finding_blocked"]


# ----- AT-13: the backstop fails a table whose keys lost the cells' equality --------------------


def _table_errors(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in report["residual_pii"] if f["severity"] == "error"]


def _assert_backstop_blocks(report: dict[str, Any]) -> None:
    (error,) = _table_errors(report)
    assert BACKSTOP in error["message"]
    verdict = post_scan_verdict(report)
    assert verdict.blocking
    assert [c.code for c in verdict.codes] == ["check_error"]


def test_a_cell_equal_to_its_output_but_keyed_differently_fails_the_table() -> None:
    cells = [Fraction(2 * i + 1, 4) for i in range(40)]
    src = pd.DataFrame({"email": EMAILS[:40], "amount": pd.Series(cells, dtype=object)})
    out = pd.DataFrame(
        {"email": FAKE[:40], "amount": pd.Series([float(c) for c in cells], dtype=object)}
    )
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker")))
    _assert_backstop_blocks(report)
    assert "/4" not in repr(report) and "realmail" not in repr(report)


def test_extra_key_matches_with_unchanged_counts_and_diversity_are_allowed() -> None:
    src = pd.DataFrame({"email": EMAILS[:40], "code": pd.Series(range(40), dtype=object)})
    out = pd.DataFrame(
        {"email": FAKE[:40], "code": pd.Series([str(i) for i in range(40)], dtype=object)}
    )
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker")))
    assert not _table_errors(report)


PAN = 4111111111111111  # a synthetic, Luhn-valid test number


def test_a_source_that_only_looks_constant_through_its_keys_blocks_through_a_finding() -> None:
    pans = pd.Series([PAN if i % 2 else str(PAN) for i in range(64)], dtype=object)
    src = pd.DataFrame({"email": EMAILS, "pan": pans})
    out = pd.DataFrame({"email": FAKE, "pan": pans.copy()})
    config = _cfg(("email", "faker"))
    frame = [asdict(f) for f in check_residual_pii({"t": out}, config, source_frames={"t": src})]
    (pan,) = [f for f in frame if f["column"] == "pan"]
    assert pan["severity"] == "fail" and pan["source_identity_rate"] == 1.0
    assert identity_counts(src["pan"], out["pan"]) == (64, 64)
    assert identity_counts(_keys(src["pan"]), _keys(out["pan"])) == (64, 64)
    assert canonical_cells(src["pan"]).nunique(dropna=True) == 2
    assert _keys(src["pan"]).nunique(dropna=True) == 1
    report = run_post_mask({"t": src}, {"t": out}, config=config)
    assert not _table_errors(report)
    (finding,) = [f for f in report["residual_pii"] if f["column"] == "pan"]
    assert finding["severity"] == "fail"
    assert post_scan_verdict(report).blocking
    assert str(PAN) not in repr(report)


def test_a_source_diversity_that_drops_but_stays_varied_passes() -> None:
    src = pd.DataFrame({"email": EMAILS[:3], "code": pd.Series([1, "1", 2], dtype=object)})
    out = pd.DataFrame(
        {"email": FAKE[:3], "code": pd.Series(["alpha", "beta", "gamma"], dtype=object)}
    )
    assert canonical_cells(src["code"]).nunique(dropna=True) == 3
    assert _keys(src["code"]).nunique(dropna=True) == 2
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker")))
    assert not _table_errors(report)
    assert not post_scan_verdict(report).blocking


# ----- precision and the zero-comparable guard --------------------------------------------------

# longdouble is binary64 on some platforms (arm64): the wide-float cases need a wider mantissa.
needs_wide_longdouble = pytest.mark.skipif(
    np.finfo(np.longdouble).nmant <= 52, reason="longdouble is no wider than a double here"
)

WIDE = [np.longdouble(2**53 + (i % 2)) for i in range(64)]


@needs_wide_longdouble
@pytest.mark.parametrize("kind", ["object", "longdouble"])
def test_an_unchanged_wide_float_column_that_keys_alike_in_a_double_still_fails(kind: str) -> None:
    cells = pd.Series(WIDE, dtype=object if kind == "object" else np.longdouble)
    src = pd.DataFrame({"email": EMAILS, "n": cells})
    out = pd.DataFrame({"email": FAKE, "n": cells.copy()})
    # Two distinct cells in the source; both round to one double, so they share a key.
    assert canonical_cells(src["n"]).nunique(dropna=True) == 2
    assert _keys(src["n"]).nunique(dropna=True) == 1
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker"), ("n", "hash")))
    (finding,) = [f for f in report["policy_validation"] if f["column"] == "n"]
    assert finding["severity"] == "fail"
    assert post_scan_verdict(report).blocking


def test_a_source_that_cannot_be_counted_is_not_counted_when_no_row_is_comparable() -> None:
    src = pd.DataFrame(
        {"email": EMAILS[:3], "mixed": pd.Series([bytearray(b"ab"), 7, 8], dtype=object)}
    )
    out = pd.DataFrame({"email": FAKE[:3], "mixed": pd.Series([None, None, None], dtype=object)})
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker")))
    assert not _table_errors(report)
    assert not post_scan_verdict(report).blocking


def test_the_backstop_checks_the_keys_the_emitter_produced(monkeypatch: pytest.MonkeyPatch) -> None:
    """An emitter that changes one output key of an unchanged, varied column is caught: the
    backstop reads the emitted arrays, not keys it computes again from the frames."""
    import pyarrow as pa

    cells = pd.Series([1, "a"] * 32, dtype=object)
    src = pd.DataFrame({"email": EMAILS, "code": cells})
    out = pd.DataFrame({"email": FAKE, "code": cells.copy()})
    real = runner_module._text
    calls = [0]

    def text(series: pd.Series) -> Any:
        calls[0] += 1
        array = real(series)
        # The output's keys come first in `_frame_tables`: break its first key only.
        if str(series.name) == "code" and calls[0] == 1:
            keys = array.to_pylist()
            keys[0] = "broken"
            return pa.array(keys, type=pa.string())
        return array

    monkeypatch.setattr(runner_module, "_text", text)
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker")))
    _assert_backstop_blocks(report)


def _masked_wide_run(values: list[Any], replacement: list[Any]) -> dict[str, Any]:
    src = pd.DataFrame({"email": EMAILS, "n": pd.Series(values * 32, dtype=object)})
    out = pd.DataFrame({"email": FAKE, "n": replacement * 32})
    return run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker"), ("n", "hash")))


HUGE_FINITE = np.isfinite(np.longdouble("1e4500"))  # false where the exponent range is a double's


@pytest.mark.skipif(not HUGE_FINITE, reason="longdouble cannot hold 1e4500 here")
@needs_wide_longdouble
def test_huge_finite_longdouble_keys_do_not_hit_the_int_string_limit() -> None:
    """Run in a child interpreter with the default digit limit, so the result does not depend on
    the limit the test process runs with."""
    import subprocess
    import sys

    script = (
        "import sys\n"
        "sys.set_int_max_str_digits(4300)\n"
        "import numpy as np, pandas as pd\n"
        "from decoy_engine.internal.cell_text import detector_text, key_text\n"
        "values = [np.longdouble('1e4500'), np.longdouble('2e4500')]\n"
        "keys = key_text(pd.Series(values, dtype=object))\n"
        "assert keys[0] != keys[1] and len(keys[0]) > 4300\n"
    )
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, check=False)  # noqa: S603
    assert done.returncode == 0, done.stderr.decode()[-300:]


@needs_wide_longdouble
def test_wide_fractional_keys_do_not_depend_on_the_decimal_context() -> None:
    from decimal import localcontext

    low = np.longdouble(1) + np.longdouble(2) ** -62
    high = np.longdouble(1) + np.longdouble(2) ** -61
    with localcontext() as ctx:
        ctx.prec = 15
        keys = key_text(pd.Series([low, high], dtype=object))
        report = _masked_wide_run([low, high], [1, 2])
    assert keys[0] == keys[1]
    assert not _table_errors(report)
    assert not post_scan_verdict(report).blocking


@needs_wide_longdouble
def test_a_whole_wide_float_keys_as_the_equal_int() -> None:
    whole = np.longdouble(2**53 + 1)
    assert key_text(pd.Series([whole, 2**53 + 1], dtype=object)) == [str(2**53)] * 2


@needs_wide_longdouble
@pytest.mark.parametrize("form", ["decimal_cells", "decimal_text"])
def test_an_unchanged_wide_fraction_is_not_counted_as_masked(form: str) -> None:
    """Output equal to the source reads as the same key whatever form it is emitted in."""
    values = [np.longdouble("9007199254740992.5"), np.longdouble("9007199254740994.5")]
    assert values[0] != float(values[0])
    same = (
        [Decimal(str(v)) for v in values] if form == "decimal_cells" else [str(v) for v in values]
    )
    assert key_text(pd.Series(values, dtype=object)) == key_text(pd.Series(same, dtype=object))
    report = _masked_wide_run(values, same)
    (finding,) = [f for f in report["policy_validation"] if f["column"] == "n"]
    assert finding["severity"] == "fail"
    assert post_scan_verdict(report).blocking


# ----- round 4: one exact-value key for every numeric cell --------------------------------------

# A Decimal and a float in one column: Arrow refuses it, so the column is keyed as text.
HALVES = [Decimal("9007199254740992.5"), 2.5]


@pytest.mark.parametrize(
    "spelling",
    [["9007199254740992.50", "2.50"], ["9.0071992547409925E15", "25e-1"]],
    ids=["trailing_zero", "scientific"],
)
def test_another_spelling_of_an_unchanged_decimal_keys_and_blocks_as_the_decimal(
    spelling: list[str],
) -> None:
    assert key_text(pd.Series(HALVES, dtype=object)) == key_text(pd.Series(spelling, dtype=object))
    report = _masked_wide_run(HALVES, spelling)
    (finding,) = [f for f in report["policy_validation"] if f["column"] == "n"]
    assert finding["severity"] == "fail"
    assert post_scan_verdict(report).blocking


def test_a_tiny_decimal_exponent_keys_in_bounded_space() -> None:
    tiny = Decimal("1e-999999999999999999")
    keys = key_text(pd.Series([tiny, "mixed"], dtype=object))
    assert keys == ["1E-999999999999999999", "mixed"]
    report = _masked_wide_run([tiny, "mixed"], [1, 2])
    assert not _table_errors(report)


def test_huge_integral_decimals_key_under_the_default_digit_limit() -> None:
    import sys

    limit = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        keys = key_text(
            pd.Series(
                [Decimal("1E+4500"), Decimal("10E+4499"), Decimal(10**5000 + 1), "x"],
                dtype=object,
            )
        )
    finally:
        sys.set_int_max_str_digits(limit)
    assert keys[0] == keys[1] == "1E4500"
    assert keys[2] is not None and len(keys[2]) == 5001
    assert keys[0] != keys[2]


def test_the_exact_text_of_a_float_keys_as_the_float_and_blocks() -> None:
    # The Decimal holds the float 0.2 exactly, and makes Arrow refuse the column.
    tenth, fifth = 0.1, 0.2
    cells = [tenth, Decimal(fifth)]
    exact = [str(Decimal(tenth)), str(Decimal(fifth))]
    assert key_text(pd.Series(cells, dtype=object)) == ["0.1", "0.2"]
    assert key_text(pd.Series(exact, dtype=object)) == ["0.1", "0.2"]
    report = _masked_wide_run(cells, exact)
    (finding,) = [f for f in report["policy_validation"] if f["column"] == "n"]
    assert finding["severity"] == "fail"
    assert post_scan_verdict(report).blocking


def test_infinities_key_alike_across_float_decimal_and_text() -> None:
    cells = [np.inf, -np.inf, Decimal("Infinity"), Decimal("-Infinity"), "inf", "-INFINITY"]
    keys = key_text(pd.Series(cells, dtype=object))
    assert keys == ["Infinity", "-Infinity"] * 3
    report = _masked_wide_run([np.inf, -np.inf], [Decimal("Infinity"), Decimal("-Infinity")])
    (finding,) = [f for f in report["policy_validation"] if f["column"] == "n"]
    assert finding["severity"] == "fail"
    assert post_scan_verdict(report).blocking


@pytest.mark.parametrize(
    "cell",
    [
        0,
        -0.0,
        Decimal("-0E+7"),
        True,
        12300,
        Decimal("123.4500"),
        1e300,
        np.float32(1.1),
        Decimal("1E-999999999999999999"),
        "Overflow",
        Decimal("1E4500"),
        0.1,
        9007199254740992,
        "02134",
        "+15551234567",
        "nan",
        "1/2",
        "plain text",
    ],
)
def test_the_key_of_a_key_is_the_key(cell: Any) -> None:
    (key,) = key_text(pd.Series([cell], dtype=object))
    assert key_text(pd.Series([key], dtype=object)) == [key]


def test_signed_zero_keys_as_zero_and_leading_zero_text_keeps_its_characters() -> None:
    keys = key_text(pd.Series([-0.0, Decimal("-0.00"), "-0", 0, "02134", "+1"], dtype=object))
    assert keys == ["0", "0", "0", "0", "02134", "+1"]


# ----- round 5: binary64 keys, a bounded exponent and detector text -----------------------------

WIDE_LONGDOUBLE = np.finfo(np.longdouble).nmant > 52


def _one_key(*cells: Any) -> str | None:
    keys = set(key_text(pd.Series(list(cells), dtype=object)))
    assert len(keys) == 1, keys
    return next(iter(keys))


def test_a1b_detector_text_keeps_the_characters_as_written() -> None:
    cells = ["212555.0100", "02134", "+1 212 555 0100", Decimal("212555.0100")]
    assert detector_text(pd.Series(cells, dtype=object)) == [
        "212555.0100",
        "02134",
        "+1 212 555 0100",
        "212555.0100",
    ]
    assert key_text(pd.Series(cells[:1], dtype=object)) == ["212555.01"]
    stamp = np.timedelta64(5, "s")
    assert detector_text(pd.Series([stamp], dtype=object)) == [str(pd.Timedelta(stamp))]


@needs_wide_longdouble
def test_a1b_wide_float_detector_text_reads_as_its_own_export() -> None:
    assert detector_text(pd.Series([np.longdouble("35.001417")], dtype=object)) == ["35.001417"]


def test_a1c_a_whole_float_reads_as_plain_digits() -> None:
    cells = pd.Series([2125550100.0, "x", None, 0.5, True], dtype=object)
    assert detector_text(cells) == ["2125550100", "x", None, "0.5", "True"]


def test_a1e_integers_keep_every_digit_for_the_detectors() -> None:
    cells = [411111111111111936, np.int64(411111111111111936), -12, 0]
    assert detector_text(pd.Series(cells, dtype=object)) == [
        "411111111111111936",
        "411111111111111936",
        "-12",
        "0",
    ]


def test_a1h_integral_decimals_and_big_values_read_as_digits() -> None:
    cells = [Decimal("4111111111111111.00"), 10**33, Decimal("1E+3"), Decimal("0.00")]
    assert detector_text(pd.Series(cells, dtype=object)) == [
        "4111111111111111",
        "1" + "0" * 33,
        "1000",
        "0",
    ]


def test_a2b_one_key_for_every_spelling_of_a_number() -> None:
    assert (
        _one_key(
            0.1,
            np.float64(0.1),
            "0.1",
            "1.00000000000000006e-01",
            Decimal("0.1"),
            str(Decimal.from_float(0.1)),
        )
        == "0.1"
    )
    assert _one_key(1e-07, "1e-07", "1E-7", "0.0000001") == "0.0000001"
    assert _one_key(2125550100.0, "2125550100", "2125550100.0", "2.1255501E9", "2.1255501e+09") == (
        "2125550100"
    )
    assert _one_key(1e23, "1e+23", "99999999999999991611392") == "1" + "0" * 23
    assert _one_key(2**53 + 1, np.int64(2**53 + 1), float(2**53)) == str(2**53)


@needs_wide_longdouble
def test_a2b_wide_floats_key_as_their_own_export() -> None:
    assert _one_key(np.longdouble("0.1"), "0.1") == "0.1"
    assert _one_key(np.longdouble("35.001417"), "35.001417") == "35.001417"


finite_floats = st.floats(allow_nan=False, allow_infinity=False)


@settings(derandomize=True, max_examples=300, deadline=None)
@given(f=finite_floats)
def test_a2c_every_spelling_of_a_binary64_has_one_key(f: float) -> None:
    spellings = [f, repr(f), str(f), str(Decimal(f)), Decimal(f), f"{f:.17e}", f"{f:.17g}"]
    key = _one_key(*spellings)
    assert key is not None
    assert key_text(pd.Series([key], dtype=object)) == [key]
    if f.is_integer():
        assert _one_key(f, int(f)) == key


@settings(derandomize=True, max_examples=300, deadline=None)
@given(n=st.integers(min_value=-(2**1000), max_value=2**1000))
def test_a2c_every_spelling_of_an_int_has_one_key(n: int) -> None:
    assert _one_key(n, str(n), Decimal(n), float(n), np.float64(n)) is not None


def test_a2d_range_edges() -> None:
    assert key_text(pd.Series([Decimal("1e-326")], dtype=object)) == ["1E-326"]
    assert _one_key("1e-325", "2e-324") == "0"
    assert _one_key("3e-324", 5e-324) == "5E-324"
    assert _one_key("1" + "0" * 308 + ".1", 1e308) == "1E308"
    huge = "2" + "0" * 308 + ".1"
    assert _one_key(huge, Decimal(huge)) == huge


def _limit(digits: int) -> Any:
    import contextlib
    import sys

    @contextlib.contextmanager
    def swap() -> Any:
        old = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(digits)
        try:
            yield
        finally:
            sys.set_int_max_str_digits(old)

    return swap()


def test_a3a_the_exponent_does_not_depend_on_the_int_digit_limit() -> None:
    padded = "1e" + "0" * 640 + "1"
    seen = []
    for limit in (640, 4300, 0):
        with _limit(limit):
            seen.append(key_text(pd.Series([10, padded], dtype=object)))
    assert seen[0] == seen[1] == seen[2] == ["10", "10"]


def test_a3b_a_huge_exponent_text_is_a_band_and_raises_nothing() -> None:
    with _limit(640):
        keys = key_text(
            pd.Series(
                [
                    "10e" + "9" * 640,
                    "1e" + "9" * 100_000,
                    "1e-" + "9" * 100_000,
                    "-1e" + "9" * 30,
                    "0e" + "9" * 100_000,
                ],
                dtype=object,
            )
        )
        big = pd.Series([10**700], dtype=object)
        assert key_text(big) == ["1E700"]
        assert detector_text(big) == ["1E700"]
    assert keys == ["Overflow", "Overflow", "Underflow", "-Overflow", "0"]


def test_a3c_a_band_follows_the_value_not_the_spelling() -> None:
    assert _one_key("1e100000000000000000000", "10e99999999999999999999") == "Overflow"
    assert _one_key("10e10000000000000000000", "1e10000000000000000001") == "Overflow"
    assert _one_key("1e10000000000000000000") == "1E10000000000000000000"


def test_a3d_keys_do_not_depend_on_the_decimal_context() -> None:
    from decimal import FloatOperation, Inexact, Rounded, localcontext

    cells = ["1.5", Decimal("1.5"), 0.1, "1e-07", Decimal("1E4500")]
    plain = key_text(pd.Series(cells, dtype=object))
    with localcontext() as ctx:
        ctx.prec, ctx.Emax, ctx.Emin = 1, 9, -9
        ctx.traps[FloatOperation] = ctx.traps[Inexact] = ctx.traps[Rounded] = True
        trapped = key_text(pd.Series(cells, dtype=object))
    assert trapped == plain


# ----- round 5 runs: keys compare, cells count --------------------------------------------------


def _run_n(source: list[Any], output: list[Any], column: str = "n") -> dict[str, Any]:
    src = pd.DataFrame({"email": EMAILS[: len(source)], column: pd.Series(source, dtype=object)})
    out = pd.DataFrame({"email": FAKE[: len(source)], column: pd.Series(output, dtype=object)})
    return run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker"), (column, "hash")))


def _graded(report: dict[str, Any], column: str = "n") -> list[str]:
    return [f["severity"] for f in report["policy_validation"] if f["column"] == column]


@pytest.mark.parametrize(
    ("source", "output"),
    [
        ([0.1, 0.2, "mixed"], ["0.1", "0.2", "mixed"]),
        ([0.1, 0.2, "mixed"], [f"{0.1:.17e}", f"{0.2:.17e}", "mixed"]),
        ([1e23, "mixed"], ["1e+23", "mixed"]),
    ],
    ids=["short_text", "dot17e", "exponent_text"],
)
def test_a2a_an_unchanged_float_written_as_text_blocks(
    source: list[Any], output: list[Any]
) -> None:
    report = _run_n(source * 20, output * 20)
    assert _graded(report) == ["fail"]
    assert post_scan_verdict(report).blocking


@needs_wide_longdouble
def test_a2a_a_wide_float_and_its_str_export_block() -> None:
    wide = np.longdouble("35.001417")
    report = _run_n([wide, "unknown"] * 20, [str(wide), "unknown"] * 20, column="lat")
    assert "fail" in _graded(report, "lat")
    assert post_scan_verdict(report).blocking


def test_a3a_a_padded_exponent_blocks_under_every_digit_limit() -> None:
    padded = "1e" + "0" * 640 + "1"
    verdicts = []
    for limit in (640, 4300, 0):
        with _limit(limit):
            report = _run_n([10, "x"] * 20, [padded, "x"] * 20)
        verdicts.append((_graded(report), post_scan_verdict(report).blocking))
    assert verdicts[0] == verdicts[1] == verdicts[2] == (["fail"], True)


def test_a4a_spellings_of_one_source_value_do_not_fail_the_table() -> None:
    src = pd.DataFrame({"email": EMAILS[:2], "n": ["1.0", "1.00"]})
    out = pd.DataFrame({"email": FAKE[:2], "n": pd.Series([8, "masked"], dtype=object)})
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker")))
    assert not _table_errors(report)
    assert any(f["column"] == "email" for f in report["residual_pii"])


def _facts_of(src: pd.DataFrame, out: pd.DataFrame, column: str, tmp_path: Any) -> Any:
    from decoy_engine.verification.postmask._column_facts import column_facts

    source, _ = runner_module._frame_table("t", src, out)
    output, _ = runner_module._frame_table("t", out, src)
    return column_facts(source, output, [column], scratch=tmp_path, memory_limit="256MB")[column]


def test_a4b_source_distinct_counts_the_cells_not_the_keys(tmp_path: Any) -> None:
    src = pd.DataFrame({"v": pd.Series(["1.0", "1.00", "x"], dtype=object)})
    out = pd.DataFrame({"v": pd.Series([1, "b", "c"], dtype=object)})
    fact = _facts_of(src, out, "v", tmp_path)
    assert fact.source_distinct == 3
    assert fact.output_distinct == 3


def test_a4d_a_bytearray_output_cell_counts_without_error(tmp_path: Any) -> None:
    src = pd.DataFrame({"v": pd.Series([1, "x"], dtype=object)})
    out = pd.DataFrame({"v": pd.Series([bytearray(b"ab"), 2], dtype=object)})
    fact = _facts_of(src, out, "v", tmp_path)
    assert fact.distinct_error is None
    assert fact.output_distinct == 2
    report = run_post_mask(
        {"t": src.assign(email=EMAILS[:2])},
        {"t": out.assign(email=FAKE[:2])},
        config=_cfg(("email", "faker"), ("v", "hash")),
    )
    assert not _table_errors(report)


def test_a4e_equal_instants_keyed_apart_still_fail_the_table() -> None:
    a = pd.Timestamp("2020-01-01", tz="UTC")
    b = a.tz_convert("America/New_York")
    assert a == b
    src = pd.DataFrame({"email": EMAILS[:4], "t": pd.Series([a, b, a, b], dtype=object)})
    out = pd.DataFrame({"email": FAKE[:4], "t": pd.Series([str(a), b, str(a), b], dtype=object)})
    report = run_post_mask({"t": src}, {"t": out}, config=_cfg(("email", "faker"), ("t", "hash")))
    _assert_backstop_blocks(report)


def test_a4g_distinct_counts_reads_the_view_of_a_frame_table(tmp_path: Any) -> None:
    from decoy_engine.verification.postmask._column_facts import distinct_counts

    src = pd.DataFrame({"v": pd.Series(["1.0", "1.00", "x"], dtype=object)})
    out = pd.DataFrame({"v": pd.Series([1, "b", "c"], dtype=object)})
    table, _ = runner_module._frame_table("t", src, out)
    assert distinct_counts(table, ["v"], scratch=tmp_path, memory_limit="256MB") == {"v": 3}


def test_a4h_a_source_count_error_is_recorded_and_graded_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from decoy_engine.verification.postmask import _column_facts as facts_module
    from decoy_engine.verification.postmask._column_facts import distinct_counts

    real = facts_module.source_distinct

    def count(series: pd.Series) -> int:
        if 1 in list(series):  # the source frame only: its marker is 1, the output's 2
            raise RuntimeError
        return real(series)

    phones = ["212555.0100"] * 30
    src = pd.DataFrame({"phone": pd.Series([*phones, 1], dtype=object)})
    out = pd.DataFrame({"phone": pd.Series([*phones, 2], dtype=object)})
    monkeypatch.setattr(facts_module, "source_distinct", count)
    fact = _facts_of(src, out, "phone", tmp_path)
    assert fact.distinct_error == "RuntimeError"
    assert fact.source_distinct_failed
    table, _ = runner_module._frame_table("t", src, out)
    assert distinct_counts(table, ["phone"], scratch=tmp_path, memory_limit="256MB") == {
        "phone": None
    }
    # The frame check reads the same count, so it grades the same way.
    from decoy_engine.verification.postmask.residual_pii import _frame_column_facts

    frame = _frame_column_facts("t", out, "phone", {"t": src})
    assert frame.distinct_error == "RuntimeError" and frame.source_distinct_failed
