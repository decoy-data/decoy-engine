"""F24 84-E2: the lifecycle of generate-only and mixed jobs.

Expectations are written out in bytes from the plan's section 4.3 terms, so a change to a term in
`_lifecycle_generate.py` or `generation/_bounds.py` cannot move its own test with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from decoy_engine import PipelineConfig, generation
from decoy_engine.execution._job_estimate import JobEstimate, estimate_job
from decoy_engine.execution._mem_estimate import route_intercept_bytes
from decoy_engine.execution.pipeline import _lifecycle as lc
from decoy_engine.generation._admission import classify_plan
from decoy_engine.generation._bounds import generation_floor_bytes
from tests.parity import _f0_fixtures as fx

INTERCEPT = route_intercept_bytes("full_frame")
INT_OBJ = sys.getsizeof(1 << 20)
ROWS = 1000


def _config(tmp_path: Path, columns: list[dict], *, rows: int = ROWS, fmt: str = "parquet") -> dict:
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {},
        "targets": {"g": {"type": "file", "path": str(tmp_path / f"g.out.{fmt}"), "format": fmt}},
        "tables": [{"name": "g", "row_count": rows, "generate_columns": columns}],
    }
    return PipelineConfig.model_validate(raw).model_dump()


def _phases(est: JobEstimate) -> dict[str, int]:
    return dict(est.phase_bytes)


SEQUENCE = {"name": "id", "type": "sequence", "start": 1}
EMAIL = {"name": "em", "type": "faker", "faker_type": "email"}
_EMAIL_COL = EMAIL


# --- AT-E2-1 ----------------------------------------------------------------------------


def test_generate_only_execute_is_intercept_plus_resident_plus_unique_peak(tmp_path: Path) -> None:
    # A unique faker column is declined by admission, so the plan runs the legacy whole-table
    # path: every cell is a Python object.
    unique_email = {**EMAIL, "unique": True}
    est = estimate_job(_config(tmp_path, [SEQUENCE, unique_email]), tmp_path)
    # id: a list slot plus an int object. em: a str of the declared email width (24) plus its slot.
    resident = ROWS * (8 + INT_OBJ) + ROWS * (57 + 24)
    unique = ROWS * (24 + 57 + 72) + ROWS * (32 + 72)
    arrow_out = ROWS * 8 + ROWS * (4 + 24)  # the written table is Arrow either way
    assert est.lifecycle_peak_bytes is not None, est.notes
    assert [name for name, _ in est.phase_bytes] == ["ingest", "execute", "write"]
    assert _phases(est) == {
        "ingest": 0,
        "execute": INTERCEPT + resident + unique,
        "write": INTERCEPT + arrow_out,
    }
    assert est.lifecycle_peak_bytes == INTERCEPT + resident + unique
    assert est.limiting_phase == "execute"
    assert est.peak_bytes is None  # the existing field keeps its value
    assert est.priceable is True


def test_an_eligible_generate_job_holds_arrow_buffers_and_no_unique_set(tmp_path: Path) -> None:
    est = estimate_job(_config(tmp_path, [SEQUENCE, EMAIL]), tmp_path)
    arrow = ROWS * 8 + ROWS * (4 + 24)
    assert _phases(est) == {
        "ingest": 0,
        "execute": INTERCEPT + arrow,
        "write": INTERCEPT + arrow,
    }
    assert est.limiting_phase == "execute"  # a tie goes to the earlier phase


def test_two_unique_columns_of_one_table_cost_the_largest_set_not_the_sum(tmp_path: Path) -> None:
    other = {"name": "em2", "type": "faker", "faker_type": "email", "unique": True}
    est = estimate_job(_config(tmp_path, [{**EMAIL, "unique": True}, other]), tmp_path)
    resident = 2 * ROWS * (57 + 24)
    unique = ROWS * (24 + 57 + 72) + ROWS * (32 + 72)
    assert _phases(est)["execute"] == INTERCEPT + resident + unique


def test_a_second_table_adds_its_bytes_but_not_a_second_unique_set(tmp_path: Path) -> None:
    raw = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {},
        "targets": {
            n: {"type": "file", "path": str(tmp_path / f"{n}.parquet"), "format": "parquet"}
            for n in ("a", "b")
        },
        "tables": [
            {"name": n, "row_count": ROWS, "generate_columns": [{**EMAIL, "unique": True}]}
            for n in ("a", "b")
        ],
    }
    est = estimate_job(PipelineConfig.model_validate(raw).model_dump(), tmp_path)
    resident = 2 * ROWS * (57 + 24)
    unique = ROWS * (24 + 57 + 72) + ROWS * (32 + 72)  # the largest one, not the sum
    assert _phases(est)["execute"] == INTERCEPT + resident + unique


# --- AT-E2-2 ----------------------------------------------------------------------------


def test_a_column_with_no_width_source_leaves_the_lifecycle_unpriced(tmp_path: Path) -> None:
    formula = {"name": "f", "type": "formula", "formula": "i"}
    est = estimate_job(_config(tmp_path, [SEQUENCE, formula]), tmp_path)
    assert est.lifecycle_peak_bytes is None
    assert est.limiting_phase is None and est.phase_bytes == ()
    assert "lifecycle not priced: generated column g.f has no width source" in est.notes
    assert est.priceable is True and est.peak_bytes is None and est.runtime is not None


# --- AT-E2-3 ----------------------------------------------------------------------------


def _mixed_config(tmp_path: Path) -> tuple[dict, dict]:
    src = str(tmp_path / "m.parquet")
    pq.write_table(pa.table({"n": pa.array(range(200), type=pa.int64())}), src)
    mask = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {"m": {"type": "file", "path": src, "format": "parquet"}},
        "targets": {
            "m": {"type": "file", "path": str(tmp_path / "m.out.parquet"), "format": "parquet"}
        },
        "tables": [{"name": "m", "columns": [{"name": "n", "strategy": "passthrough"}]}],
    }
    gen = _config(tmp_path, [SEQUENCE])
    both = {**mask, "targets": {**mask["targets"], **gen["targets"]}}
    both["tables"] = [*mask["tables"], *gen["tables"]]
    return (
        PipelineConfig.model_validate(mask).model_dump(),
        PipelineConfig.model_validate(both).model_dump(),
    )


def test_mixed_execute_is_the_mask_execute_plus_the_generated_bytes(tmp_path: Path) -> None:
    mask_cfg, mixed_cfg = _mixed_config(tmp_path)
    mask = estimate_job(mask_cfg, tmp_path)
    mixed = estimate_job(mixed_cfg, tmp_path)
    assert mask.route == "full_frame"
    assert mixed.priceable is False and mixed.peak_bytes is None and mixed.runtime is None
    assert any("mixed" in n for n in mixed.notes)
    assert mixed.lifecycle_peak_bytes is not None, mixed.notes
    generated = ROWS * 8
    assert _phases(mixed)["execute"] == _phases(mask)["execute"] + generated
    # Ingest covers the mask sources only; write covers every output.
    assert _phases(mixed)["ingest"] == _phases(mask)["ingest"]
    assert _phases(mixed)["write"] == _phases(mask)["write"] + generated


# --- AT-E2-4 ----------------------------------------------------------------------------


def test_the_legacy_path_prices_every_cell_as_a_python_object() -> None:
    formula = {"name": "f", "type": "formula", "formula": "i"}
    config = fx.config([fx.table("t", ROWS, [{"name": "s", "type": "sequence"}, formula])])
    assert not classify_plan(config).eligible
    terms = generation.generated_lifecycle_terms(config, {("t", "f"): 10.0})
    assert terms.legacy is True and terms.unpriced == ()
    # A string cell is a list slot plus the object (57 plus width); a number is a slot plus its
    # object. Arrow would price this table at 8 + 4 + 10 bytes a row.
    assert terms.resident_bytes == {"t": ROWS * (8 + INT_OBJ) + ROWS * (57 + 10)}


def test_an_eligible_plan_prices_string_columns_as_arrow() -> None:
    config = fx.config([fx.table("t", ROWS, [{"name": "s", "type": "sequence"}, dict(_EMAIL_COL)])])
    terms = generation.generated_lifecycle_terms(config, {("t", "em"): 24.0})
    assert terms.legacy is False
    assert terms.resident_bytes == {"t": ROWS * 8 + ROWS * (4 + 24)}


def test_a_faker_without_a_declared_width_takes_the_payload_bound() -> None:
    config = fx.config(
        [fx.table("t", ROWS, [{"name": "n", "type": "faker", "faker_type": "word"}])]
    )
    terms = generation.generated_lifecycle_terms(config, {})
    assert terms.unpriced == ()
    assert terms.resident_bytes == {"t": ROWS * (4 + 256)}


def test_a_column_with_no_width_is_named_not_priced_at_zero() -> None:
    formula = {"name": "f", "type": "formula", "formula": "i"}
    config = fx.config([fx.table("t", ROWS, [dict(formula)])])
    assert generation.generated_lifecycle_terms(config, {}).unpriced == ("t.f",)


# --- AT-E2-5 ----------------------------------------------------------------------------


def test_the_generation_floor_keeps_its_base_head_values() -> None:
    unique_email = {**_EMAIL_COL, "unique": True}
    config = fx.config([fx.table("t", ROWS, [{"name": "s", "type": "sequence"}, unique_email])])
    admission = classify_plan(config)
    # The unique column declines the plan, so each cell is a list slot (8 bytes), plus the unique
    # set at the email payload cap (320).
    assert not admission.eligible
    unique = ROWS * (320 + 57 + 72) + ROWS * (32 + 72)
    assert generation_floor_bytes(config, admission) == ROWS * 16 + unique
    eligible = fx.config([fx.table("t", ROWS, [{"name": "s", "type": "sequence"}, dict(EMAIL)])])
    # Arrow data buffers: 8 bytes a row and one int32 offset a row; the floor prices no payload.
    assert generation_floor_bytes(eligible, classify_plan(eligible)) == ROWS * 12
    # The lifecycle shares the walk but not the number: its string columns carry their payload.
    terms = generation.generated_lifecycle_terms(eligible, {("t", "em"): 24.0})
    assert terms.resident_bytes == {"t": ROWS * 8 + ROWS * (4 + 24)}


# --- guards -----------------------------------------------------------------------------


def test_the_generate_note_is_one_of_the_pinned_shapes() -> None:
    assert "lifecycle not priced: generated column {column} has no width source" in lc.NOTE_SHAPES
    assert lc.note_matches_shape("lifecycle not priced: generated column g.f has no width source")


def test_execution_reaches_generation_only_through_its_package() -> None:
    from decoy_engine.execution.pipeline import _lifecycle_generate
    from tests.unit.generation.test_generation_floor import _private_imports

    assert _private_imports(_lifecycle_generate.__file__, "decoy_engine.generation") == []


# --- AT-E2-7 ----------------------------------------------------------------------------


def test_the_docs_section_names_the_phases_and_what_is_not_priced() -> None:
    text = (Path(__file__).parents[4] / "docs" / "execution-backends.md").read_text("utf-8")
    start = text.index("## Advisory job estimate and lifecycle peak")
    end = text.find("\n## ", start + 1)
    section = text[start : end if end != -1 else len(text)]
    for needle in (
        "ingest",
        "execute",
        "write",
        "holds every input",  # the resident-handoff assumption
        "vault maps",
        "post-scan",
        "quarantine",
        "first 10,000 rows",  # the sample bias
        "peak_bytes",
        "generate",
    ):
        assert needle in section, needle
