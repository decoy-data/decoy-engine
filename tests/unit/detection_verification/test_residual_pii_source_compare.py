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
from decoy_engine.internal.pandas_compat import exact_int_types_mapper
from decoy_engine.verification.postmask import _column_facts as facts_module
from decoy_engine.verification.postmask import from_table, run_post_mask
from decoy_engine.verification.postmask.residual_pii import (
    check_residual_pii,
    residual_pii_findings,
)

_EMAILS = [f"user{i}@realmail.com" for i in range(100)]


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


def _frame_of(table: pa.Table) -> pd.DataFrame:
    # The cells the batch path sees: list cells arrive as numpy arrays, as in `_series`.
    return pd.DataFrame(
        {c: table[c].to_pandas(types_mapper=exact_int_types_mapper) for c in table.column_names}
    )


def _with_raising_cells(series: pd.Series) -> pd.Series:
    return series.map(lambda v: _CellWhoseEqualityRaises() if v == _RAISE else v)


def _both_paths(src_cells: list, out_cells: list, strategy: str, tmp_path: Path, monkeypatch):
    """Findings from the frame check and the batch check on the same source and output."""
    src = pa.table({"email": src_cells})
    out = pa.table({"email": out_cells})
    src_frame = _frame_of(src)
    if _RAISE in src_cells:
        # Arrow cannot hold a cell whose equality raises, so both paths swap the marker cells
        # for one at the point each reads its cells.
        src_frame = src_frame.apply(_with_raising_cells)
        real_series = facts_module._series
        monkeypatch.setattr(
            facts_module, "_series", lambda batch, c: _with_raising_cells(real_series(batch, c))
        )
    frame = check_residual_pii(
        {"t": _frame_of(out)}, _cfg(strategy), source_frames={"t": src_frame}
    )
    facts = facts_module.column_facts(
        from_table("t", src),
        from_table("t", out),
        ["email"],
        scratch=tmp_path,
        memory_limit="256MB",
    )
    batch = residual_pii_findings({"t": facts}, _cfg(strategy))
    return frame, batch


_PARITY_CASES = {
    "one-element lists": ([[e] for e in _EMAILS], _OTHER_EMAILS, "info"),
    "one-element lists, leaked": ([[e] for e in _EMAILS], _EMAILS, "fail"),
    "two-element lists": ([[e, "x"] for e in _EMAILS], _OTHER_EMAILS, "error"),
    "equality raises": ([_RAISE] * 100, _OTHER_EMAILS, "error"),
}


class TestFrameAndBatchAgree:
    """Codex R1 on #784: both real paths, one input, the same findings."""

    @pytest.mark.parametrize("case", list(_PARITY_CASES))
    def test_same_findings_on_both_paths(self, case, tmp_path, monkeypatch):
        src_cells, out_cells, severity = _PARITY_CASES[case]
        frame, batch = _both_paths(src_cells, out_cells, "faker", tmp_path, monkeypatch)
        assert frame == batch
        assert [f.severity for f in frame] == [severity]

    @pytest.mark.parametrize("case", ["two-element lists", "equality raises"])
    def test_failed_comparison_without_a_detector_hit_is_an_error(
        self, case, tmp_path, monkeypatch
    ):
        """A column no detector flags still reports a comparison that raised."""
        src_cells = _PARITY_CASES[case][0]
        frame, batch = _both_paths(src_cells, _PLAIN, "faker", tmp_path, monkeypatch)
        assert frame == batch
        finding = _one(frame)
        assert finding.severity == "error"
        assert finding.detector_id == ""
        assert finding.source_compared is False
        assert "realmail.com" not in finding.message
        assert "secret-cell-value" not in finding.message

    def test_passthrough_failed_comparison_without_a_detector_hit_stays_quiet(
        self, tmp_path, monkeypatch
    ):
        src_cells = _PARITY_CASES["two-element lists"][0]
        frame, batch = _both_paths(src_cells, _PLAIN, "passthrough", tmp_path, monkeypatch)
        assert frame == batch == []
