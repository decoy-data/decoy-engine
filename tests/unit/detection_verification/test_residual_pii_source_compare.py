"""Source-aware residual-PII escalation (audit C1/H6 regression suite).

Pre-fix, ``check_residual_pii`` never saw the source frames, so a column
whose mask silently failed (output byte-identical to source) on a
faker-family strategy reported severity='info' -- indistinguishable from
a correctly-synthesized column. These tests pin the escalation contract:
positional output==source identity on a strategy that should have
replaced values escalates the finding, while legitimate-by-design value
reuse (shuffle permutations, categorical resampling from the source
category set) never false-positives.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.fileaccess import FileAccessReadError
from decoy_engine.verification.postmask import _column_facts as facts_module
from decoy_engine.verification.postmask import from_table, run_post_mask
from decoy_engine.verification.postmask._column_facts import cell_view, standalone_writes
from decoy_engine.verification.postmask.residual_pii import (
    _frame_column_facts,
    check_residual_pii,
    residual_pii_findings,
)

_EMAILS = [f"user{i}@realmail.com" for i in range(100)]


def _findings(facts, config, failed=None):
    """`residual_pii_findings` with the writer query the frame path computes for these tables."""
    schemas = {table: list(columns) for table, columns in facts.items()}
    return residual_pii_findings(facts, config, failed, writes=standalone_writes(config, schemas))


def _cfg(strategy: str | None, column: str = "email") -> dict:
    columns = [] if strategy is None else [{"name": column, "strategy": strategy}]
    return {"version": 2, "tables": [{"name": "t", "columns": columns}]}


def _frames(src_vals: list, out_vals: list, column: str = "email"):
    return (
        {"t": pd.DataFrame({column: src_vals})},
        {"t": pd.DataFrame({column: out_vals})},
    )


def _one(findings):
    assert len(findings) == 1, f"expected exactly one finding, got {findings!r}"
    return findings[0]


class TestC1RegressionFakerLeak:
    def test_faker_output_identical_to_source_is_fail(self):
        """The audit's C1 repro: masking failed, output IS source -> fail."""
        source, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=source))
        assert finding.severity == "fail"
        assert finding.source_compared is True
        assert finding.source_identity_rate == 1.0

    def test_faker_leak_fails_through_runner(self):
        source, output = _frames(_EMAILS, _EMAILS)
        report = run_post_mask(source, output, config=_cfg("faker"))
        assert report["fail_count"] >= 1
        sevs = [f["severity"] for f in report["residual_pii"]]
        assert "fail" in sevs

    def test_faker_legit_synthetic_output_stays_info(self):
        synthetic = [f"fake{i}@masked.example" for i in range(100)]
        source, output = _frames(_EMAILS, synthetic)
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=source))
        assert finding.severity == "info"
        assert finding.source_compared is True
        assert finding.source_identity_rate == 0.0

    def test_faker_partial_leak_warns_below_fail_threshold(self):
        # 20% of rows kept their source value: above the 5% warn floor,
        # below the 50% fail bar.
        out = [s if i < 20 else f"fake{i}@masked.example" for i, s in enumerate(_EMAILS)]
        source, output = _frames(_EMAILS, out)
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=source))
        assert finding.severity == "warning"

    def test_faker_majority_leak_is_fail(self):
        out = [s if i < 60 else f"fake{i}@masked.example" for i, s in enumerate(_EMAILS)]
        source, output = _frames(_EMAILS, out)
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=source))
        assert finding.severity == "fail"


class TestValueReuseStrategiesNoFalsePositive:
    def test_categorical_resample_from_source_categories_stays_info(self):
        # from_profile-style reuse: same category SET, different positions.
        src = (["alice@x.com", "bob@x.com"] * 50)[:100]
        out = (["bob@x.com", "alice@x.com"] * 50)[:100]  # rotated, identity rate 0
        source, output = _frames(src, out)
        finding = _one(check_residual_pii(output, _cfg("categorical"), source_frames=source))
        assert finding.severity == "info"

    def test_categorical_full_identity_is_fail(self):
        src = [f"u{i}@x.com" for i in range(100)]
        source, output = _frames(src, list(src))
        finding = _one(check_residual_pii(output, _cfg("categorical"), source_frames=source))
        assert finding.severity == "fail"

    def test_shuffle_derangement_stays_info(self):
        src = [f"u{i}@x.com" for i in range(100)]
        out = src[1:] + src[:1]  # full derangement, 100% value overlap
        source, output = _frames(src, out)
        finding = _one(check_residual_pii(output, _cfg("shuffle"), source_frames=source))
        assert finding.severity == "info"

    def test_shuffle_with_zero_movement_is_fail(self):
        src = [f"u{i}@x.com" for i in range(100)]
        source, output = _frames(src, list(src))
        finding = _one(check_residual_pii(output, _cfg("shuffle"), source_frames=source))
        assert finding.severity == "fail"

    def test_constant_source_never_escalates(self):
        # Identity rate is meaningless when the source has one distinct
        # value; identical output is a coincidence, not a leak signal.
        src = ["same@x.com"] * 50
        source, output = _frames(src, list(src))
        finding = _one(check_residual_pii(output, _cfg("categorical"), source_frames=source))
        assert finding.severity == "info"


class TestH6UnconfiguredColumns:
    def test_unconfigured_leak_is_fail(self):
        """Output==source on an unconfigured PII column with a
        high-confidence detector hit must fail the report (pre-fix it
        capped at 'warning', making the CLI's exit 4 unreachable)."""
        source, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, _cfg(None), source_frames=source))
        assert finding.severity == "fail"

    def test_unconfigured_synthetic_column_stays_warning(self):
        synthetic = [f"fake{i}@masked.example" for i in range(100)]
        source, output = _frames(_EMAILS, synthetic)
        finding = _one(check_residual_pii(output, _cfg(None), source_frames=source))
        assert finding.severity == "warning"

    def test_unconfigured_column_missing_from_source_stays_warning(self):
        source = {"t": pd.DataFrame({"other": ["x"] * 100})}
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        finding = _one(check_residual_pii(output, _cfg(None), source_frames=source))
        assert finding.severity == "warning"
        assert finding.source_compared is False


class TestNonComparablePathsDegrade:
    def test_no_source_frames_keeps_legacy_behavior(self):
        # Two-positional-arg call shape must keep working and must not
        # escalate (the documented degradation when source is absent).
        _, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, _cfg("faker")))
        assert finding.severity == "info"
        assert finding.source_compared is False
        assert finding.source_identity_rate is None

    def test_source_missing_table_degrades(self):
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        finding = _one(
            check_residual_pii(output, _cfg("faker"), source_frames={"elsewhere": pd.DataFrame()})
        )
        assert finding.severity == "info"
        assert finding.source_compared is False

    def test_row_count_mismatch_degrades(self):
        source = {"t": pd.DataFrame({"email": _EMAILS[:50]})}
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=source))
        assert finding.severity == "info"
        assert finding.source_compared is False

    def test_nondefault_index_alignment(self):
        # Frames with weird indexes still compare positionally.
        src_df = pd.DataFrame({"email": _EMAILS}, index=range(1000, 1100))
        out_df = pd.DataFrame({"email": _EMAILS}, index=range(100))
        finding = _one(
            check_residual_pii({"t": out_df}, _cfg("faker"), source_frames={"t": src_df})
        )
        assert finding.severity == "fail"
        assert finding.source_identity_rate == 1.0

    def test_passthrough_never_compared(self):
        source, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, _cfg("passthrough"), source_frames=source))
        assert finding.severity == "info"

    def test_destroys_pattern_strategies_unchanged(self):
        # hash already fails on any surviving hit; source comparison
        # must not lower or alter that.
        source, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, _cfg("hash"), source_frames=source))
        assert finding.severity == "fail"


class TestUnknownTableWording:
    """DI-CLOSE E2: with no config entry for the table, the engine cannot say a column was not
    configured; the wording says what it knows. Severity is unchanged."""

    def test_table_absent_hit_says_the_config_has_no_entry_for_the_table(self):
        out_vals = [f"fake{i}@masked.example" for i in range(100)]
        source, output = _frames(_EMAILS, out_vals)
        finding = _one(
            check_residual_pii(output, {"version": 2, "tables": []}, source_frames=source)
        )
        assert finding.severity == "warning"
        assert "has no entry for its table" in finding.message
        assert "not configured to be masked" not in finding.message

    def test_table_absent_leak_stays_fail_with_the_new_wording(self):
        source, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, {}, source_frames=source))
        assert finding.severity == "fail"
        assert "has no entry for its table" in finding.message
        assert "not configured to be masked" not in finding.message

    def test_table_present_column_absent_keeps_the_old_wording(self):
        source, output = _frames(_EMAILS, _EMAILS)
        finding = _one(check_residual_pii(output, _cfg(None), source_frames=source))
        assert finding.severity == "fail"
        assert "was not configured to be masked" in finding.message
        synthetic = [f"fake{i}@masked.example" for i in range(100)]
        source, output = _frames(_EMAILS, synthetic)
        finding = _one(check_residual_pii(output, _cfg(None), source_frames=source))
        assert "was not configured to be masked" in finding.message


class _CellWhoseEqualityRaises:
    """A source cell whose comparison fails with a message that carries a value."""

    def __hash__(self) -> int:
        return 1

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or TypeError("cannot compare secret-cell-value")

    def __eq__(self, other: object) -> bool:
        raise self._error


def _raising_source(error: Exception | None = None):
    cells = [_CellWhoseEqualityRaises(error) for _ in _EMAILS]
    return {"t": pd.DataFrame({"email": cells})}


class TestIdentityComparisonRaises:
    def test_frame_path_comparison_raise_is_error_finding(self):
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=_raising_source()))
        assert finding.severity == "error"
        assert "TypeError" in finding.message
        assert "secret-cell-value" not in finding.message
        assert "realmail.com" not in finding.message

    def test_no_op_by_design_strategy_stays_quiet(self):
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        finding = _one(
            check_residual_pii(output, _cfg("passthrough"), source_frames=_raising_source())
        )
        assert finding.severity != "error"

    def test_frame_path_passes_through_exception_propagates(self):
        source = _raising_source(FileAccessReadError("sources.t.path"))
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        with pytest.raises(FileAccessReadError):
            check_residual_pii(output, _cfg("faker"), source_frames=source)

    def test_not_comparable_still_quiet(self):
        source = {"t": pd.DataFrame({"email": _EMAILS[:50]})}
        output = {"t": pd.DataFrame({"email": _EMAILS})}
        finding = _one(check_residual_pii(output, _cfg("faker"), source_frames=source))
        assert finding.severity != "error"


# Output that fires no detector, so only the source comparison can speak for the column.
_PLAIN = [f"item-{i}-zq" for i in range(100)]
_OTHER_EMAILS = [f"fake{i}@masked.example" for i in range(100)]
_RAISE = "raise-on-compare"


def _with_raising_cells(series: pd.Series) -> pd.Series:
    return series.map(lambda v: _CellWhoseEqualityRaises() if v == _RAISE else v)


def _both_paths(src_cols: dict, out_cols: dict, config: dict, tmp_path: Path, monkeypatch):
    """Findings and facts from the frame check and the batch check on one source and output.

    The frame check gets the native Python cells (a list stays a list), as a caller's pandas
    frame holds them; the batch check reads the same cells through Arrow."""
    src_frame, out_frame = pd.DataFrame(src_cols), pd.DataFrame(out_cols)
    if any(_RAISE in cells for cells in src_cols.values()):
        # Arrow cannot hold a cell whose equality raises, so both paths swap the marker cells
        # for one at the point each reads its cells.
        src_frame = src_frame.apply(_with_raising_cells)
        real_series = facts_module._series
        real_column = facts_module._column
        monkeypatch.setattr(
            facts_module, "_series", lambda batch, c: _with_raising_cells(real_series(batch, c))
        )

        def column(batch, c):
            # The identity pass reads Arrow columns, which cannot hold the marker cell.
            cells = real_column(batch, c)
            return _with_raising_cells(cells.to_pandas()) if _RAISE in cells.to_pylist() else cells

        monkeypatch.setattr(facts_module, "_column", column)
    frame = check_residual_pii({"t": out_frame}, config, source_frames={"t": src_frame})
    frame_facts = {c: _frame_column_facts("t", out_frame, c, {"t": src_frame}) for c in out_cols}
    batch_facts = facts_module.column_facts(
        from_table("t", pa.table(src_cols)),
        from_table("t", pa.table(out_cols)),
        list(out_cols),
        scratch=tmp_path,
        memory_limit="256MB",
    )
    batch = _findings({"t": batch_facts}, config)
    return frame, batch, frame_facts, batch_facts


def _compared(fact) -> tuple:
    return (
        fact.comparable_rows,
        fact.identical_rows,
        fact.source_distinct,
        fact.source_distinct_failed,
        fact.identity_error,
    )


_CONSTANT = [[_EMAILS[0]]] * 100
# (source cells, output cells, severity on a faker column, identical rows, source distinct)
_PARITY_CASES = {
    "one-element lists": ([[e] for e in _EMAILS], _OTHER_EMAILS, "info", 0, 100),
    # A list is not its one element, on either path.
    "one-element lists, scalar output": ([[e] for e in _EMAILS], _EMAILS, "info", 0, 100),
    "two-element lists": ([[e, "x"] for e in _EMAILS], _OTHER_EMAILS, "info", 0, 100),
    "one constant list": (_CONSTANT, [_EMAILS[0]] * 100, "info", 0, 1),
    "equality raises": ([_RAISE] * 100, _OTHER_EMAILS, "error", 0, 1),
}


class TestFrameAndBatchAgree:
    """Codex R1 and R2 on #784: both real paths, one input, the same facts and findings."""

    @pytest.mark.parametrize("case", list(_PARITY_CASES))
    def test_same_findings_on_both_paths(self, case, tmp_path, monkeypatch):
        src_cells, out_cells, severity, _, _ = _PARITY_CASES[case]
        frame, batch, _, _ = _both_paths(
            {"email": src_cells}, {"email": out_cells}, _cfg("faker"), tmp_path, monkeypatch
        )
        assert frame == batch
        assert [f.severity for f in frame] == [severity]

    @pytest.mark.parametrize("case", [c for c in _PARITY_CASES if c != "equality raises"])
    def test_same_comparison_facts_on_both_paths(self, case, tmp_path, monkeypatch):
        src_cells, out_cells, _, identical, distinct = _PARITY_CASES[case]
        _, _, frame, batch = _both_paths(
            {"email": src_cells}, {"email": out_cells}, _cfg("faker"), tmp_path, monkeypatch
        )
        expected = (100, identical, distinct, False, None)
        assert _compared(frame["email"]) == _compared(batch["email"]) == expected

    def test_failed_comparison_without_a_detector_hit_is_an_error(self, tmp_path, monkeypatch):
        """A column no detector flags still reports a comparison that raised."""
        frame, batch, _, _ = _both_paths(
            {"email": [_RAISE] * 100}, {"email": _PLAIN}, _cfg("faker"), tmp_path, monkeypatch
        )
        assert frame == batch
        finding = _one(frame)
        assert finding.severity == "error"
        assert finding.detector_id == ""
        assert finding.source_compared is False
        assert "secret-cell-value" not in finding.message

    def test_passthrough_failed_comparison_without_a_detector_hit_stays_quiet(
        self, tmp_path, monkeypatch
    ):
        frame, batch, _, _ = _both_paths(
            {"email": [_RAISE] * 100},
            {"email": _PLAIN},
            _cfg("passthrough"),
            tmp_path,
            monkeypatch,
        )
        assert frame == batch == []

    def test_a_column_a_mask_writes_but_no_entry_names_reports_a_failed_comparison(
        self, tmp_path, monkeypatch
    ):
        """A joint_mask entry on `city` also writes `zip` and `state`, so a failed comparison on
        `zip` is reported though no column entry names it. `note` no entry writes stays quiet."""
        joint = {
            "name": "city",
            "strategy": "joint_mask",
            "provider_config": {
                "columns": ["zip", "city", "state"],
                "reference": "us_zip5_city_state",
                "key_by": "pid",
            },
        }
        config = {"version": 2, "tables": [{"name": "t", "columns": [joint]}]}
        src = {"zip": [_RAISE] * 100, "note": [_RAISE] * 100}
        out = {"zip": _PLAIN, "note": _PLAIN}
        frame, batch, _, _ = _both_paths(src, out, config, tmp_path, monkeypatch)
        assert frame == batch
        finding = _one(frame)
        assert (finding.column, finding.severity) == ("zip", "error")


# ----- round 5: detectors read the cells as written, not the comparison keys -----------------

from decimal import Decimal  # noqa: E402

from decoy_engine.verification.postmask import post_scan_verdict  # noqa: E402
from decoy_engine.verification.postmask import runner as _runner  # noqa: E402


def _mixed_run(column: str, cells: list, marker: tuple, strategy: str = "hash") -> dict:
    """60 unchanged `cells`, then one changed marker. The marker is a different type, so Arrow
    refuses the column and the runner carries it as text keys."""
    src = pd.DataFrame({column: pd.Series([*cells, marker[0]], dtype=object)})
    out = pd.DataFrame({column: pd.Series([*cells, marker[1]], dtype=object)})
    return run_post_mask({"t": src}, {"t": out}, config=_cfg(strategy, column))


def _residual(report: dict, column: str) -> dict[str, str]:
    return {
        f["detector_id"]: f["severity"] for f in report["residual_pii"] if f["column"] == column
    }


def _blocks(report: dict) -> None:
    assert post_scan_verdict(report).blocking


class TestRound5DetectorText:
    def test_a1a_dotted_phone_text_still_hits_us_phone(self):
        report = _mixed_run("phone", ["212555.0100"] * 60, (1, 2))
        assert _residual(report, "phone").get("us_phone") == "fail"
        _blocks(report)

    def test_a1e_a_luhn_valid_int_above_2_53_keeps_its_digits(self):
        report = _mixed_run("v", [411111111111111936] * 60, ("old", "new"))
        assert _residual(report, "v").get("pan") == "fail"
        _blocks(report)

    def test_a1g_decimals_keep_their_digits(self):
        report = _mixed_run("device_id", [Decimal("12.0000000000000001")] * 60, ("x", "z"))
        assert _residual(report, "device_id").get("device_id") == "fail"
        _blocks(report)
        report = _mixed_run("phone", [Decimal("212555.0100")] * 60, ("x", "z"))
        assert _residual(report, "phone").get("us_phone") == "fail"

    def test_a1h_an_integral_decimal_reads_without_its_zero_fraction(self):
        report = _mixed_run("v", [Decimal("4111111111111111.00")] * 60, ("old", "new"))
        assert _residual(report, "v").get("pan") == "fail"
        _blocks(report)

    def test_a1c_whole_float_phones_still_hit(self):
        report = _mixed_run("phone", [2125550100.0] * 60, ("x", "z"))
        assert _residual(report, "phone").get("us_phone") == "fail"


def _tables(src: pd.DataFrame, out: pd.DataFrame):
    return _runner._frame_table("t", src, out)[0], _runner._frame_table("t", out, src)[0]


def _hits(facts, column: str) -> dict[str, tuple[float, str]]:
    return {d.detector_id: (d.match_rate, d.confidence) for d in facts[column].detectors}


def _table(frame: pd.DataFrame):
    columns = _runner._first_columns(frame)
    return _runner._frame_table("t", columns, {c: cell_view(v) for c, v in columns.items()})


class TestRound5BatchEdges:
    def test_a1i_one_run_per_batch_gives_the_same_hits_at_every_batch_size(self, tmp_path):
        cells = ["212555.0100"] * 30 + ["2125550100.0"] * 30
        src = pd.DataFrame({"phone": pd.Series([*cells, 1], dtype=object)})
        out = pd.DataFrame({"phone": pd.Series([*cells, 2], dtype=object)})
        tables = {}
        for rows in (1, 7, 1000):
            source, output = _table(src), _table(out)
            facts = facts_module.column_facts(
                source, output, ["phone"], batch_rows=rows, scratch=tmp_path, memory_limit="256MB"
            )
            tables[rows] = _hits(facts, "phone")
        assert tables[1] == tables[7] == tables[1000]
        assert tables[1]["us_phone"][0] == pytest.approx(30 / 61, abs=1e-4)

    def test_a1f_the_output_offset_is_per_batch_not_per_column(self, tmp_path):
        phones = ["212555.0100"] * 8
        emails = [f"user{i}@realmail.com" for i in range(8)]
        late = [None, None, None, None, *phones[:4]]
        src = pd.DataFrame(
            {
                "phone": pd.Series([*late[:-1], 1], dtype=object),
                "email": pd.Series([None, None, None, None, *emails[:3], 1], dtype=object),
            }
        )
        out = pd.DataFrame(
            {
                "phone": pd.Series([*late[:-1], 2], dtype=object),
                "email": pd.Series([None, None, None, None, *emails[:3], 2], dtype=object),
            }
        )
        seen = {}
        for rows in (2, 100):
            source, output = _table(src), _table(out)
            facts = facts_module.column_facts(
                source,
                output,
                ["phone", "email"],
                batch_rows=rows,
                scratch=tmp_path,
                memory_limit="256MB",
            )
            seen[rows] = {c: _hits(facts, c) for c in ("phone", "email")}
        assert seen[2] == seen[100]
        assert "us_phone" in seen[2]["phone"] and "email" in seen[2]["email"]
