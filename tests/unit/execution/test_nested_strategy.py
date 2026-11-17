"""MG-3 / M2 (2026-05-31): nested JSONPath strategy regression cells.

Locks:
- Single-leaf and array-of-objects writebacks preserve JSON structure.
- Non-JSON cells emit a typed QualityWarning and pass through.
- Null cells stay null.
- Subset detector_ids -> no-such-path returns the cell unchanged
  without warning (sparse paths are valid).
- Recursive nested is rejected with a typed warning.
- Unknown child strategy is rejected with a typed warning.
- Bad target paths emit a typed warning (no crash).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies.nested._handler import (
    NestedStrategyHandler,
    _has_prefix_overlap,
    _path_segments,
)
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan._types import ColumnSeed, SeedEnvelope, TableSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry

_REG = get_default_registry()
_GRAPH = RelationshipGraph(edges=(), ordering=())
_NS = NamespaceRegistry(bindings=())
_JOB_SEED = b"\xca\xfe" * 4  # 8 bytes


def _seed(provider_config: dict, namespace: str | None = None) -> ColumnSeed:
    return ColumnSeed(
        namespace=namespace,
        strategy="nested",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(sorted(provider_config.items())),
    )


class _FakeCtx:
    def __init__(self) -> None:
        # Real StrategyContext carries a `row_errors` list; the malformed-cell
        # fail-closed path appends to it, so the stand-in needs one too.
        self.row_errors: list = []
        # A seeded categorical child reads the mask key and the row offset.
        self.job_seed = _JOB_SEED
        self.mask_key = _JOB_SEED
        self.row_offset = 0


# ── happy paths ───────────────────────────────────────────────────────


class TestHappyPaths:
    def test_nested_redact_replaces_target_leaf(self):
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"user": {"name": "Alice", "email": "alice@x.com"}}),
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert warnings == []
        parsed = json.loads(out["data"].iloc[0])
        assert parsed["user"]["email"] == "REDACTED"
        # Sibling field untouched.
        assert parsed["user"]["name"] == "Alice"

    def test_nested_arrayof_objects_target_walks_each_entry(self):
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps(
                        {
                            "users": [
                                {"name": "Alice", "email": "alice@x.com"},
                                {"name": "Bob", "email": "bob@x.com"},
                            ]
                        }
                    )
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.users[*].email", "strategy": "redact"}),
            _FakeCtx(),
        )
        parsed = json.loads(out["data"].iloc[0])
        assert [u["email"] for u in parsed["users"]] == ["REDACTED", "REDACTED"]
        assert [u["name"] for u in parsed["users"]] == ["Alice", "Bob"]

    def test_nested_categorical_child_writeback_preserves_json_structure(self):
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"tier": "free", "id": 1}),
                    json.dumps({"tier": "pro", "id": 2}),
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed(
                {
                    "target": "$.tier",
                    "strategy": "categorical",
                    "strategy_config": {"categories": ["X", "Y"]},
                },
                namespace="tier_ns",
            ),
            _FakeCtx(),
        )
        for row in out["data"]:
            parsed = json.loads(row)
            assert parsed["tier"] in ("X", "Y")
            assert "id" in parsed  # structure preserved


# ── passthrough cases ─────────────────────────────────────────────────


class TestPassthroughCases:
    def test_nested_cell_not_json_records_row_error_and_warning(self):
        # A malformed-JSON cell fails closed: the original stays in the frame
        # (T4, the pipeline layer removes it), a format_error RowError is recorded
        # so it never reaches the main output unmasked, and the advisory
        # QualityWarning still surfaces in the Post-scan integrity report. Pre-fix this emitted
        # only the warning and let the cleartext through (TEST-3 finding 1).
        df = pd.DataFrame({"data": ["not json at all"]})
        handler = NestedStrategyHandler()
        ctx = _FakeCtx()
        out, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.email", "strategy": "redact"}),
            ctx,
        )
        assert out["data"].iloc[0] == "not json at all"
        codes = [w.code for w in warnings]
        assert "nested_cell_json_parse_error" in codes
        assert len(ctx.row_errors) == 1
        assert ctx.row_errors[0].trigger == "format_error"
        assert ctx.row_errors[0].column == "data"

    def test_nested_target_matching_nothing_fails_closed(self):
        # TEST-3 P1-2: a target that matches NOTHING across the whole column is a
        # misconfiguration (a typoed / wrong path), not a valid no-op. Failing
        # closed prevents the whole column of cleartext from passing through
        # unmasked. Pre-fix this returned the column unchanged with no error.
        df = pd.DataFrame({"data": [json.dumps({"x": 1, "y": 2})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError, match="nested_target_matched_nothing"):
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "$.nonexistent", "strategy": "redact"}),
                _FakeCtx(),
            )

    def test_nested_sparse_path_some_cells_match_is_valid(self):
        # A genuine sparse path (SOME cells carry the target, some do not) stays
        # valid: matching cells are masked, non-matching cells pass unchanged, no
        # error. Only the ALL-zero-match case (above) fails closed.
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"email": "a@x.com"}),  # matches -> masked
                    json.dumps({"other": "keep"}),  # no match -> unchanged
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert "a@x.com" not in out["data"].iloc[0]  # matched leaf was redacted
        assert json.loads(out["data"].iloc[1]) == {"other": "keep"}  # sparse passthrough

    def test_nested_null_cell_stays_null(self):
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"user": {"email": "alice@x.com"}}),
                    None,
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert pd.isna(out["data"].iloc[1])
        parsed = json.loads(out["data"].iloc[0])
        assert parsed["user"]["email"] == "REDACTED"


# ── rejections ────────────────────────────────────────────────────────


class TestRejections:
    """QA-3 F12 (2026-05-31, security): config errors below now raise
    StrategyError so the runner fails the job. Pre-fix they returned the
    column unchanged with a QualityWarning; a typoed target or unknown
    child strategy silently passed PII through (the warning surfaced
    only in the Post-scan integrity report, which not all operators audit).
    """

    def test_nested_recursive_nested_rejected(self):
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as exc:
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "$.x", "strategy": "nested"}),
                _FakeCtx(),
            )
        assert exc.value.code == "nested_recursive_nested_rejected"
        assert exc.value.strategy == "nested"

    def test_nested_unknown_child_strategy_raises(self):
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as exc:
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "$.x", "strategy": "no_such_strategy"}),
                _FakeCtx(),
            )
        assert exc.value.code == "nested_child_strategy_unknown"

    def test_nested_jsonpath_parse_error_raises(self):
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as exc:
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "$.x[", "strategy": "redact"}),  # bad jsonpath
                _FakeCtx(),
            )
        assert exc.value.code == "nested_jsonpath_parse_error"
        # Machine `strategy` attribution is fail-closed-load-bearing, not prose.
        assert exc.value.strategy == "nested"

    def test_nested_target_empty_raises(self):
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as exc:
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "", "strategy": "redact"}),
                _FakeCtx(),
            )
        assert exc.value.code == "nested_target_unset"
        assert exc.value.strategy == "nested"

    def test_nested_strategy_empty_raises(self):
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as exc:
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "$.x", "strategy": ""}),
                _FakeCtx(),
            )
        assert exc.value.code == "nested_strategy_unset"


# ── batch delegation ──────────────────────────────────────────────────


class TestDuplicateIndex:
    """QA-3 F2 (2026-05-31): duplicate-index DataFrames used to corrupt
    the nested writeback. The old implementation iterated `col.index`
    and stored per-row state in a dict keyed on the index label; on a
    duplicate index, `col.at[row_idx]` returned a Series and the dict
    silently kept only one entry per duplicate. Post-fix the strategy
    uses positional enumeration: every row visited exactly once and
    written back by position."""

    def test_nested_duplicate_index_writeback_correct(self):
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"user": {"email": "a@x.com"}}),
                    json.dumps({"user": {"email": "b@x.com"}}),
                    json.dumps({"user": {"email": "c@x.com"}}),
                ]
            },
            index=[0, 0, 0],  # all rows share the same index label
        )
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        # All 3 rows must be masked; no row's email survives the
        # writeback. Pre-fix only the FIRST row (or worse: only one of
        # the rows non-deterministically) got the writeback.
        for row in out["data"]:
            parsed = json.loads(row)
            assert parsed["user"]["email"] == "REDACTED"
        assert warnings == []


class TestChildTechniqueClass:
    """QA-3 F7 (2026-05-31): the synthetic child ColumnSeed must carry
    the child strategy's technique class, not None (the parent's class
    for nested is intentionally None per _technique_class.py)."""

    def test_nested_child_technique_class_resolves_for_redact(self):
        # Indirect verification: the child handler runs against a seed
        # whose technique_class is anonymisation (redact's class).
        # Stand-in test: confirm the strategy still produces correct
        # masked output, which is the user-visible signal that the
        # child seed was constructed correctly.
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.x", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert json.loads(out["data"].iloc[0]) == {"x": "REDACTED"}


class TestJsonPathOverlapSecurity:
    """QA-3 F14 (2026-05-31, security): wildcard / recursive JSONPath
    can produce match-sets where one match's path is a prefix of
    another (e.g. `$..*` returns the dict AND its contents). Pre-fix
    `jsonpath_ng.update` in original order silently lost the inner
    write or wrote to the wrong location. Post-fix the matches are
    sorted deepest-first and a typed QualityWarning is emitted when
    prefix-overlap is detected so operators auditing the Post-scan integrity report
    can see the path was ambiguous."""

    def test_nested_recursive_overlap_emits_warning(self):
        # `$..*` returns matches at every level; the root structures
        # are prefixes of their leaves. The strategy must emit the
        # overlap warning and writeback deepest-first.
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"user": {"name": "Alice", "email": "alice@x.com"}}),
                ]
            }
        )
        handler = NestedStrategyHandler()
        _, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$..*", "strategy": "redact"}),
            _FakeCtx(),
        )
        codes = [w.code for w in warnings]
        assert "nested_jsonpath_path_overlap" in codes

    def test_nested_recursive_no_overlap_emits_no_warning(self):
        # `$..ssn` on siblings (not nested) returns parallel matches;
        # no prefix-overlap, no warning.
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps(
                        {
                            "patient": {"ssn": "111"},
                            "spouse": {"ssn": "222"},
                        }
                    )
                ]
            }
        )
        handler = NestedStrategyHandler()
        _, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$..ssn", "strategy": "redact"}),
            _FakeCtx(),
        )
        codes = [w.code for w in warnings]
        assert "nested_jsonpath_path_overlap" not in codes
        # And both ssns are masked.

    def test_nested_recursive_masks_all_target_leaves(self):
        # Even with overlap, every leaf identified by the JSONPath
        # gets written to (deepest-first ordering preserves the
        # contract: every match position receives the masked value).
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps(
                        {
                            "patient": {"ssn": "111-22-3333"},
                            "spouse": {"ssn": "444-55-6666"},
                        }
                    )
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$..ssn", "strategy": "redact"}),
            _FakeCtx(),
        )
        parsed = json.loads(out["data"].iloc[0])
        assert parsed["patient"]["ssn"] == "REDACTED"
        assert parsed["spouse"]["ssn"] == "REDACTED"


class TestBatchDelegation:
    def test_nested_collects_all_leaves_into_one_child_call(self):
        """Multi-row + multi-leaf input must be delegated to the child
        strategy in a single batch (preserves the child's vectorized
        behavior). Verified indirectly: every targeted leaf gets the
        redact token, no untargeted leaf is touched."""
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"a": "x", "b": "keep1"}),
                    json.dumps({"a": "y", "b": "keep2"}),
                    json.dumps({"a": "z", "b": "keep3"}),
                ]
            }
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.a", "strategy": "redact"}),
            _FakeCtx(),
        )
        for i, cell in enumerate(out["data"], start=1):
            parsed = json.loads(cell)
            assert parsed["a"] == "REDACTED"
            assert parsed["b"] == f"keep{i}"


class TestNestedWhenGateFailClosed:
    """Codex round-5 P2 NESTED CODE_SET CHILD NOT PREFLIGHTED UNDER A
    ZERO-MATCH WHEN-GATE remediation: `run_with_when_gate` calls
    `getattr(handler, "preflight", None)` unconditionally, before its
    zero-match short-circuit (see
    test_code_set_strategy.py::TestCodeSetWhenGateFailClosed for the plain
    `code_set` case), but that only reaches a `code_set` column's own
    corpus check when the OUTER handler defines `preflight`.
    `NestedStrategyHandler` (the outer handler for a `nested(code_set)`
    column) previously did not, so the CHILD `CodeSetHandler.preflight` was
    never invoked, and a `nested(code_set)` column referencing a
    missing/invalid corpus succeeded silently whenever its `when:` gate
    matched zero rows. `NestedStrategyHandler.preflight` closes this by
    resolving the child handler and forwarding to its `preflight`."""

    def test_zero_match_when_gate_still_fails_closed_on_missing_child_corpus(self) -> None:
        """A nested(code_set) column whose `when:` predicate matches NO
        rows, and whose child corpus_source points at a customer path that
        does not exist, must still raise through the real pandas-adapter
        route -- not silently pass the raw JSON cells through."""
        table = pa.table({"data": pa.array([json.dumps({"diag": "I10"})], type=pa.string())})
        col_seed = ColumnSeed(
            namespace=None,
            strategy="nested",
            provider=None,
            backend_type="decoy_native",
            backend_version="1",
            cardinality_mode="reuse",
            deterministic=False,
            provider_config=tuple(
                sorted(
                    {
                        "target": "$.diag",
                        "strategy": "code_set",
                        "strategy_config": {
                            "code_set": "missing_corpus",
                            "corpus_source": "customer:/no/such/file.parquet",
                        },
                    }.items()
                )
            ),
            # Never true for the one row: the gate matches zero rows.
            when="data == 'ZZZ_NEVER_MATCHES'",
        )
        plan: Any = SimpleNamespace(
            seed_envelope=SeedEnvelope(
                job_seed=_JOB_SEED,
                per_table=(
                    (
                        "t",
                        TableSeed(
                            per_column=(("data", col_seed),),
                            per_group=(),
                        ),
                    ),
                ),
            )
        )
        with pytest.raises(PlanCompileError) as excinfo:
            PandasExecutionAdapter().run_single(
                plan, table, registry=_REG, relationship_graph=_GRAPH, namespace_registry=_NS
            )
        assert excinfo.value.code == "code_set_corpus_path_not_found", (
            f"expected a fail-closed corpus error, got {excinfo.value.code!r}. "
            "A zero-match when: gate on a nested(code_set) column must not let "
            "a missing child corpus succeed silently."
        )


# ── mutation-hardening (TQ crown-jewels, 2026-07-26) ───────────────────
#
# Kills the LOGIC survivors from the mutmut run on `nested/_handler.py`. Grouped
# by the invariant / method each pins. See
# docs/quality/mutation-ledgers/execution_strategies_nested.md.


class _SpyChild:
    """Child handler double that records the outer-column ctx stamp and
    applies a per-value deterministic transform.

    Lets us pin two `run()` invariants that a constant child (redact)
    cannot observe: (a) the real outer column is visible to the child
    during dispatch (ctx save/stamp/restore), and (b) each collected leaf
    is written back at ITS OWN path (the cursor mapping), by making the
    masked value a function of the input so a misalignment is visible.
    """

    def __init__(self) -> None:
        self.seen_outer_column: Any = "UNSET"

    def run(self, df, column, plan, ctx):
        if ctx is None:
            self.seen_outer_column = "CTX_NONE"
        else:
            self.seen_outer_column = getattr(ctx, "nested_outer_column", "MISSING")
        vals = df[column].tolist()
        df[column] = [f"M::{v}" for v in vals]
        return df, []


def _match_with_path(path_str: str) -> Any:
    """A jsonpath_ng match double whose `full_path` stringifies to
    `path_str`, for exercising `_path_segments` / `_has_prefix_overlap`
    at their documented (deepest-first) contract boundary."""

    class _FullPath:
        def __str__(self) -> str:
            return path_str

    return SimpleNamespace(full_path=_FullPath())


class TestJsonPathParseErrorFields:
    """The parse-error raise site's machine `strategy` is fail-closed
    attribution, not prose (kills strategy=None / XX-wrap / uppercase)."""

    def test_jsonpath_parse_error_strategy_field(self):
        df = pd.DataFrame({"data": [json.dumps({"x": "y"})]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as exc:
            handler.run(
                df.copy(),
                "data",
                _seed({"target": "$.x[", "strategy": "redact"}),
                _FakeCtx(),
            )
        assert exc.value.code == "nested_jsonpath_parse_error"
        assert exc.value.strategy == "nested"


class TestExtensionArrayColumn:
    """The extension-array branch (`col.astype(object)`) must run for a
    pandas StringDtype column. Kills `col = None` (AttributeError on
    `to_list`) and `col.astype(None)` (ValueError)."""

    def test_extension_array_dtype_column_is_masked(self):
        df = pd.DataFrame(
            {"data": pd.Series([json.dumps({"user": {"email": "a@x.com"}})], dtype="string")}
        )
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert warnings == []
        assert json.loads(out["data"].iloc[0])["user"]["email"] == "REDACTED"


class TestRootTargetWriteback:
    """A root / whole-document target (`$` or the backtick-`this` selector) must
    write the masked value back, not leak the original cell. jsonpath_ng's
    Root.update() returns the replacement instead of mutating in place, so a
    writeback that discards the return re-serializes the raw PII (Codex 2026-07-31
    BLOCKER: `"SSN-123-45-6789"` with target `$` + redact published the SSN with
    no error or warning)."""

    def test_root_dollar_target_masks_whole_cell(self):
        df = pd.DataFrame({"data": ['"SSN-123-45-6789"']})
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(), "data", _seed({"target": "$", "strategy": "redact"}), _FakeCtx()
        )
        assert warnings == []
        assert out["data"].iloc[0] == '"REDACTED"'
        assert "123-45-6789" not in out["data"].iloc[0]

    def test_backtick_this_root_target_masks_whole_cell(self):
        df = pd.DataFrame({"data": ['"SSN-123-45-6789"']})
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(), "data", _seed({"target": "`this`", "strategy": "redact"}), _FakeCtx()
        )
        assert warnings == []
        assert out["data"].iloc[0] == '"REDACTED"'
        assert "123-45-6789" not in out["data"].iloc[0]


class TestArraySelectorOnObjectFailsClosed:
    """An array selector (`[*]`, `[i]`, a slice) applied to a JSON OBJECT makes
    jsonpath-ng coerce the dict into a synthetic singleton list, so the writeback
    would add an integer key instead of replacing the object and republish the
    source cleartext (Codex 2026-07-31 second BLOCKER). These must fail closed,
    not leak. Object-appropriate targets (`$.*`, field paths) and array selectors
    on real lists still mask."""

    @pytest.mark.parametrize(
        "target",
        ["$[*]", "$[0:1]", "$.wrapper[*]", "$.wrapper[:]"],
    )
    def test_array_selector_on_object_raises(self, target):
        cell = (
            '{"ssn": "SSN-123-45-6789"}'
            if target.startswith("$[")
            else '{"wrapper": {"ssn": "SSN-123-45-6789"}}'
        )
        df = pd.DataFrame({"data": [cell]})
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError, match="nested_target_unwritable_container"):
            handler.run(
                df.copy(), "data", _seed({"target": target, "strategy": "redact"}), _FakeCtx()
            )
        # The raw SSN must not have been emitted anywhere (fail closed before write).
        assert "123-45-6789" in cell  # sanity: the source did contain it

    def test_array_wildcard_on_real_list_still_masks(self):
        df = pd.DataFrame({"data": ['[{"ssn": "SSN-123-45-6789"}]']})
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(), "data", _seed({"target": "$[*]", "strategy": "redact"}), _FakeCtx()
        )
        assert warnings == []
        assert "123-45-6789" not in out["data"].iloc[0]

    def test_object_wildcard_dotstar_still_masks(self):
        df = pd.DataFrame({"data": ['{"ssn": "SSN-123-45-6789"}']})
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(), "data", _seed({"target": "$.*", "strategy": "redact"}), _FakeCtx()
        )
        assert warnings == []
        assert json.loads(out["data"].iloc[0])["ssn"] == "REDACTED"


class TestRowOrderingBranches:
    """Each per-cell `continue` must skip only its own row, not halt the
    scan. Kills the three `continue -> break` mutants (null cell, parse
    error, no-match) by placing the skipped row BEFORE a maskable row."""

    def test_null_cell_before_valid_row_does_not_halt(self):
        df = pd.DataFrame({"data": [None, json.dumps({"user": {"email": "a@x.com"}})]})
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert pd.isna(out["data"].iloc[0])
        assert json.loads(out["data"].iloc[1])["user"]["email"] == "REDACTED"

    def test_parse_error_cell_before_valid_row_does_not_halt(self):
        df = pd.DataFrame({"data": ["not json", json.dumps({"user": {"email": "a@x.com"}})]})
        handler = NestedStrategyHandler()
        out, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert out["data"].iloc[0] == "not json"
        assert json.loads(out["data"].iloc[1])["user"]["email"] == "REDACTED"
        assert any(w.code == "nested_cell_json_parse_error" for w in warnings)

    def test_no_match_cell_before_valid_row_does_not_halt(self):
        df = pd.DataFrame(
            {"data": [json.dumps({"other": 1}), json.dumps({"user": {"email": "a@x.com"}})]}
        )
        handler = NestedStrategyHandler()
        out, _ = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.user.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        assert json.loads(out["data"].iloc[0]) == {"other": 1}
        assert json.loads(out["data"].iloc[1])["user"]["email"] == "REDACTED"


class TestWarningMachineFields:
    """Both QualityWarnings carry machine fields (`provider`, `column`,
    and the `detail` dict keys/values) that flow into the manifest's
    quality summary. Pin them exactly: kills provider/column None + case
    + XX-wrap, and every `detail` key rename / value / None / dropped."""

    def test_parse_error_warning_fields(self):
        df = pd.DataFrame({"data": ["not json"]})
        handler = NestedStrategyHandler()
        _, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$.email", "strategy": "redact"}),
            _FakeCtx(),
        )
        parse_warnings = [w for w in warnings if w.code == "nested_cell_json_parse_error"]
        assert len(parse_warnings) == 1
        w = parse_warnings[0]
        assert w.provider == "nested"
        assert w.column == "data"
        assert w.detail == {"row_pos": "0"}

    def test_overlap_warning_fields(self):
        df = pd.DataFrame({"data": [json.dumps({"user": {"name": "Alice", "email": "a@x.com"}})]})
        handler = NestedStrategyHandler()
        _, warnings = handler.run(
            df.copy(),
            "data",
            _seed({"target": "$..*", "strategy": "redact"}),
            _FakeCtx(),
        )
        overlaps = [w for w in warnings if w.code == "nested_jsonpath_path_overlap"]
        assert len(overlaps) >= 1
        w = overlaps[0]
        assert w.provider == "nested"
        assert w.column == "data"
        assert set(w.detail.keys()) == {"row_pos", "target", "match_count"}
        assert w.detail["row_pos"] == "0"
        assert w.detail["target"] == "$..*"
        assert w.detail["match_count"].isdigit()
        assert int(w.detail["match_count"]) >= 1


class TestOuterColumnCtxLifecycle:
    """`run()` saves ctx.nested_outer_column, stamps the REAL outer column
    for the child dispatch, then restores the prior value in `finally`.
    Pins save (prior value / default), stamp (name + value seen by the
    child), and restore (correct attr name + value)."""

    def _redact_seed(self):
        return _seed({"target": "$.user.email", "strategy": "redact"})

    def _one_row_df(self):
        return pd.DataFrame({"data": [json.dumps({"user": {"email": "a@x.com"}})]})

    def test_outer_column_restored_to_default_when_absent(self):
        # ctx has no nested_outer_column attr: default "" is saved and
        # restored. Kills prior=None, getattr default None, default "XXXX",
        # and finally restoring the wrong value/attr.
        ctx = _FakeCtx()
        NestedStrategyHandler().run(self._one_row_df(), "data", self._redact_seed(), ctx)
        assert ctx.nested_outer_column == ""

    def test_outer_column_restored_to_prior_value(self):
        # A prior stamp must be restored verbatim (nested dispatch can run
        # mid-dispatch of another node). Kills getattr(None, ...),
        # reading/writing a wrong attr name, and prior=None.
        ctx = _FakeCtx()
        object.__setattr__(ctx, "nested_outer_column", "SENTINEL")
        NestedStrategyHandler().run(self._one_row_df(), "data", self._redact_seed(), ctx)
        assert ctx.nested_outer_column == "SENTINEL"

    def test_child_sees_real_outer_column_during_dispatch(self, monkeypatch):
        import decoy_engine.execution._strategies as strat

        spy = _SpyChild()
        monkeypatch.setitem(strat.SCALAR_HANDLERS, "spy", spy)
        df = pd.DataFrame({"data": [json.dumps({"a": "v1"})]})
        NestedStrategyHandler().run(
            df, "data", _seed({"target": "$.a", "strategy": "spy"}), _FakeCtx()
        )
        # Kills stamp=None, wrong stamp attr name, and ctx=None passed to child.
        assert spy.seen_outer_column == "data"


class TestChildBatchMapping:
    """Each collected leaf is written back at its OWN path in collection
    order. With a per-value child transform and distinct leaf values, a
    misaligned cursor (`+= 1` -> `= 1` / `-= 1`) surfaces as a wrong value
    at some path."""

    def test_each_leaf_maps_to_its_own_masked_value(self, monkeypatch):
        import decoy_engine.execution._strategies as strat

        monkeypatch.setitem(strat.SCALAR_HANDLERS, "spy", _SpyChild())
        df = pd.DataFrame(
            {
                "data": [
                    json.dumps({"a": "alpha", "b": "beta"}),
                    json.dumps({"a": "gamma"}),
                ]
            }
        )
        out, _ = NestedStrategyHandler().run(
            df, "data", _seed({"target": "$.*", "strategy": "spy"}), _FakeCtx()
        )
        row0 = json.loads(out["data"].iloc[0])
        row1 = json.loads(out["data"].iloc[1])
        assert row0["a"] == "M::alpha"
        assert row0["b"] == "M::beta"
        assert row1["a"] == "M::gamma"


class TestWritebackIndexAlignment:
    """The rebuilt column must carry the frame's own index. `index=None`
    / dropped index gives a 0..n-1 RangeIndex that misaligns (all-NaN)
    against a non-default frame index."""

    def test_custom_index_preserved_on_writeback(self):
        df = pd.DataFrame(
            {"data": [json.dumps({"a": "x"}), json.dumps({"a": "y"})]},
            index=[10, 20],
        )
        out, _ = NestedStrategyHandler().run(
            df.copy(), "data", _seed({"target": "$.a", "strategy": "redact"}), _FakeCtx()
        )
        assert list(out.index) == [10, 20]
        assert pd.notna(out["data"].loc[10])
        assert pd.notna(out["data"].loc[20])
        assert json.loads(out["data"].loc[10])["a"] == "REDACTED"
        assert json.loads(out["data"].loc[20])["a"] == "REDACTED"


class TestPathSegments:
    """`_path_segments` strips a single outer paren pair ONLY when both
    parens are present, slicing exactly one char off each end."""

    def test_unbalanced_leading_paren_is_not_stripped(self):
        # Both-parens guard: `and` (not `or`). A leading-only paren keeps
        # the raw segment; an `or` mutant would wrongly slice it.
        assert _path_segments(_match_with_path("(user")) == ("(user",)

    def test_balanced_parens_strip_one_char_each_end(self):
        # `raw[1:-1]`, not `[1:-2]`: the closing paren is the only trailing
        # char removed, so the last segment keeps its full text.
        assert _path_segments(_match_with_path("(a.bc)")) == ("a", "bc")


class TestHasPrefixOverlap:
    """`_has_prefix_overlap` (deepest-first contract) flags a pair iff a
    strictly-shorter path is a prefix of a longer one."""

    def test_adjacent_prefix_pair_is_detected(self):
        # `range(i + 1, n)`, not `i + 2`: the only overlapping pair here is
        # adjacent, so skipping the neighbour would miss it.
        deep = _match_with_path("a.b")
        shallow = _match_with_path("a")
        assert _has_prefix_overlap([deep, shallow]) is True

    def test_shorter_non_prefix_is_not_flagged(self):
        # `and`, not `or`: a shorter path that is NOT a prefix must not
        # count merely for being shorter.
        deep = _match_with_path("a.b")
        other = _match_with_path("x")
        assert _has_prefix_overlap([deep, other]) is False

    def test_equal_length_identical_paths_are_not_flagged(self):
        # Strict `<`, not `<=`: two equal-length paths (even identical) are
        # not a strict-prefix overlap.
        assert _has_prefix_overlap([_match_with_path("a.b"), _match_with_path("a.b")]) is False


# ── F07 E1: bounded cell reading, number lexemes and child output ───────────────────────────────


class _RecordingChild:
    """Child double that records the leaf frame it was handed and returns a fixed transform."""

    def __init__(self, transform: Any = None) -> None:
        self.frames: list[pd.DataFrame] = []
        self.transform = transform

    def run(self, df, column, plan, ctx):
        self.frames.append(df.copy())
        if self.transform is not None:
            df[column] = pd.Series(
                [self.transform(v) for v in df[column].tolist()], index=df.index, dtype=object
            )
        return df, []


def _run_nested(
    cells: list[Any],
    config: dict,
    monkeypatch: Any,
    child: Any = None,
    namespace: str | None = None,
) -> tuple[pd.DataFrame, list, Any]:
    import decoy_engine.execution._strategies as strat

    if child is not None:
        monkeypatch.setitem(strat.SCALAR_HANDLERS, config["strategy"], child)
    ctx = _FakeCtx()
    out, warnings = NestedStrategyHandler().run(
        pd.DataFrame({"data": cells}), "data", _seed(config, namespace), ctx
    )
    return out, warnings, ctx


def _no_constant(name: str) -> None:
    raise AssertionError(f"non-finite token {name} was written")


class TestNumbersAreWrittenAsRead:
    def test_unselected_numbers_keep_their_lexeme(self, monkeypatch):
        cell = '{"ssn":"123-45-6789","amt":1.10,"big":12345678901234567890.5,"e":1e400}'
        out, warnings, ctx = _run_nested(
            [cell], {"target": "$.ssn", "strategy": "redact"}, monkeypatch
        )
        text = out["data"].iloc[0]
        assert warnings == [] and ctx.row_errors == []
        assert '"amt": 1.10' in text
        assert '"big": 12345678901234567890.5' in text
        assert '"e": 1e400' in text
        assert json.loads(text, parse_constant=_no_constant)["ssn"] == "REDACTED"

    def test_float_exact_cells_write_the_bytes_json_dumps_wrote_before(self, monkeypatch):
        import random

        rng = random.Random(11)
        cells = []
        for _ in range(200):
            cells.append(
                json.dumps(
                    {
                        "ключ": [rng.random(), rng.randint(-9, 9), "\ud800"],
                        "t": {"x": "secret", "n": None, "b": True},
                    }
                )
            )
        out, _, _ = _run_nested(cells, {"target": "$.t.x", "strategy": "redact"}, monkeypatch)
        for cell, got in zip(cells, out["data"].tolist(), strict=True):
            expected = json.loads(cell)
            expected["t"]["x"] = "REDACTED"
            assert got == json.dumps(expected)

    def test_a_matched_object_reaches_the_child_as_plain_python(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        _run_nested(
            ['{"o":{"a":1,"b":[2.5,{"c":3}]}}'],
            {"target": "$.o", "strategy": "rec"},
            monkeypatch,
            child,
        )
        value = child.frames[0]["_nested_leaves"].iloc[0]
        assert value == {"a": 1, "b": [2.5, {"c": 3}]}
        assert type(value["a"]) is int
        assert type(value["b"][0]) is float
        assert type(value["b"][1]["c"]) is int

    def test_a_scalar_number_reaches_the_child_as_plain_int_or_float(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        _run_nested(['{"a":1.10,"b":7}'], {"target": "$.*", "strategy": "rec"}, monkeypatch, child)
        leaves = child.frames[0]["_nested_leaves"].tolist()
        assert sorted(type(v).__name__ for v in leaves) == ["float", "int"]

    def test_an_escaped_surrogate_is_read_and_written_back_unchanged(self, monkeypatch):
        out, _, ctx = _run_nested(
            ['{"k":"\\ud800","x":1}'], {"target": "$.x", "strategy": "redact"}, monkeypatch
        )
        assert ctx.row_errors == []
        assert out["data"].iloc[0] == '{"k": "\\ud800", "x": "REDACTED"}'

    def test_a_long_integer_is_kept_unless_a_rule_selects_it(self, monkeypatch):
        digits = "7" * 4301
        cell = f'{{"n":{digits},"s":"x"}}'
        out, _, ctx = _run_nested([cell], {"target": "$.s", "strategy": "redact"}, monkeypatch)
        assert out["data"].iloc[0] == f'{{"n": {digits}, "s": "REDACTED"}}'
        out, warnings, ctx = _run_nested(
            [cell], {"target": "$.n", "strategy": "redact"}, monkeypatch
        )
        assert [w.code for w in warnings] == ["nested_cell_number_out_of_range"]
        assert [(e.trigger, e.row_index) for e in ctx.row_errors] == [("mask_error", 0)]
        assert out["data"].iloc[0] == cell  # the row fails closed, never written masked


class TestCellFaults:
    def test_a_duplicate_key_fails_that_row_only(self, monkeypatch):
        cells = ['{"a":1,"a":2}', '{"a":"x"}', '{"a":3,"a":4}']
        out, warnings, ctx = _run_nested(
            cells, {"target": "$.a", "strategy": "redact"}, monkeypatch
        )
        assert [w.code for w in warnings] == ["nested_cell_duplicate_key"] * 2
        assert [w.detail for w in warnings] == [{"row_pos": "0"}, {"row_pos": "2"}]
        assert [(e.row_index, e.trigger) for e in ctx.row_errors] == [
            (0, "format_error"),
            (2, "format_error"),
        ]

    def test_an_oversized_cell_is_refused_before_the_parser_runs(self, monkeypatch):
        from decoy_engine._canonical import MASK_CELL_BYTES
        from decoy_engine._canonical import _json as canonical_json

        calls: list[int] = []
        real = canonical_json.json.loads
        monkeypatch.setattr(
            canonical_json.json, "loads", lambda *a, **k: calls.append(1) or real(*a, **k)
        )
        # 3-byte characters: the character count stays under the limit, the byte count does not.
        big = '"' + "€" * (MASK_CELL_BYTES // 3) + '"'
        assert len(big) < MASK_CELL_BYTES < len(big.encode())
        out, warnings, ctx = _run_nested(
            [big, '{"a":"x"}'], {"target": "$.a", "strategy": "redact"}, monkeypatch
        )
        assert [w.code for w in warnings] == ["nested_cell_oversized"]
        assert ctx.row_errors[0].trigger == "format_error"
        assert len(calls) == 1  # only the second cell reached the parser

    def test_a_cell_at_the_byte_limit_is_read(self, monkeypatch):
        from decoy_engine._canonical import MASK_CELL_BYTES

        pad = MASK_CELL_BYTES - len('{"a":"x","p":""}')
        cell = '{"a":"x","p":"' + "y" * pad + '"}'
        assert len(cell.encode()) == MASK_CELL_BYTES
        out, warnings, ctx = _run_nested(
            [cell], {"target": "$.a", "strategy": "redact"}, monkeypatch
        )
        assert warnings == [] and ctx.row_errors == []
        assert json.loads(out["data"].iloc[0])["a"] == "REDACTED"

    def test_depth_limit_and_the_deep_cell(self, monkeypatch):
        from decoy_engine._canonical import MASK_MAX_DEPTH

        def nest(levels: int) -> str:
            return '{"a":' * (levels - 1) + '{"a":"x"}' + "}" * (levels - 1)

        ok, warnings, ctx = _run_nested(
            [nest(MASK_MAX_DEPTH)], {"target": "$..a", "strategy": "redact"}, monkeypatch
        )
        assert ctx.row_errors == []
        for cell, count in ((nest(MASK_MAX_DEPTH + 1), 1), ("[" * 5000 + "]" * 5000, 1)):
            _, warnings, ctx = _run_nested(
                [cell, '{"a":"y"}'], {"target": "$.a", "strategy": "redact"}, monkeypatch
            )
            assert [w.code for w in warnings] == ["nested_cell_too_deep"] * count
            assert len(ctx.row_errors) == count

    def test_a_raw_lone_surrogate_cell_is_not_json_and_names_no_character(self, monkeypatch):
        cell = '{"a":"\ud800secretvalue"}'
        out, warnings, ctx = _run_nested(
            [cell], {"target": "$.a", "strategy": "redact"}, monkeypatch
        )
        assert [w.code for w in warnings] == ["nested_cell_json_parse_error"]
        shown = repr(ctx.row_errors) + repr(warnings)
        assert "secretvalue" not in shown and "ud800" not in shown

    def test_trailing_text_is_not_json(self, monkeypatch):
        _, warnings, ctx = _run_nested(
            ['{"a":"x"}\nrest', '{"a":"x"}x', '{"a":"x"} \n'],
            {"target": "$.a", "strategy": "redact"},
            monkeypatch,
        )
        assert [w.detail["row_pos"] for w in warnings] == ["0", "1"]
        assert len(ctx.row_errors) == 2

    def test_faults_carry_no_cell_text_and_no_chained_error(self, monkeypatch, caplog):
        canary = "CANARY-9f3a"
        cells = [
            f'{{"{canary}":1,"{canary}":2}}',
            '{"a":"' + canary + '"' + "x",
            "[" * 70 + f'"{canary}"' + "]" * 70,
        ]
        with caplog.at_level("DEBUG"):
            _, warnings, ctx = _run_nested(
                cells, {"target": "$.a", "strategy": "redact"}, monkeypatch
            )
        shown = repr(ctx.row_errors) + repr(warnings) + caplog.text
        assert canary not in shown
        assert len(ctx.row_errors) == 3


class TestLeafColumnAndChildOutput:
    def test_integer_leaves_with_a_null_stay_integers_for_the_child(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        cells = ['{"v":1}', '{"v":null}', '{"v":3}']
        out, _, _ = _run_nested(cells, {"target": "$.v", "strategy": "rec"}, monkeypatch, child)
        frame = child.frames[0]["_nested_leaves"]
        assert frame.dtype == object
        assert frame.tolist() == [1, None, 3]
        assert [type(v) for v in frame.tolist()] == [int, type(None), int]
        assert out["data"].tolist() == ['{"v": 1}', '{"v": null}', '{"v": 3}']

    def test_a_null_free_integer_leaf_list_keeps_the_pandas_dtype(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        _run_nested(
            ['{"v":1}', '{"v":2}'], {"target": "$.v", "strategy": "rec"}, monkeypatch, child
        )
        assert str(child.frames[0]["_nested_leaves"].dtype) == "int64"

    def test_mixed_leaves_with_a_null_are_inferred_as_before(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        _run_nested(
            ['{"v":1.5}', '{"v":null}', '{"v":3}'],
            {"target": "$.v", "strategy": "rec"},
            monkeypatch,
            child,
        )
        assert str(child.frames[0]["_nested_leaves"].dtype) == "float64"

    def test_a_hash_child_over_integers_and_a_null_hashes_the_integers(self, monkeypatch):
        import dataclasses

        from decoy_engine.execution._strategies._hash import HashStrategyHandler

        cells = ['{"v":1}', '{"v":null}', '{"v":3}']
        out, _, ctx = _run_nested(
            cells, {"target": "$.v", "strategy": "hash"}, monkeypatch, namespace="ns"
        )
        flat_seed = dataclasses.replace(_seed({}, "ns"), strategy="hash", provider_config=())
        flat, _ = HashStrategyHandler().run(pd.DataFrame({"c": [1, 3]}), "c", flat_seed, _FakeCtx())
        got = [json.loads(c)["v"] for c in out["data"].tolist()]
        assert ctx.row_errors == []
        assert got == [flat["c"].iloc[0], None, flat["c"].iloc[1]]
        joined = "".join(out["data"].tolist())
        assert "NaN" not in joined and "1.0" not in joined and "3.0" not in joined

    def test_an_infinite_child_output_fails_the_row_and_is_never_written(self, monkeypatch):
        child = _RecordingChild(lambda v: float("inf") if v == "bad" else v)
        cells = ['{"v":"ok"}', '{"v":"bad"}']
        out, warnings, ctx = _run_nested(
            cells, {"target": "$.v", "strategy": "rec"}, monkeypatch, child
        )
        assert [w.code for w in warnings] == ["nested_child_non_finite"]
        assert [(e.row_index, e.trigger) for e in ctx.row_errors] == [(1, "mask_error")]
        assert "Infinity" not in "".join(out["data"].tolist())

    def test_a_nan_child_output_is_written_as_json_null(self, monkeypatch):
        child = _RecordingChild(lambda v: float("nan"))
        out, warnings, ctx = _run_nested(
            ['{"v":"a"}'], {"target": "$.v", "strategy": "rec"}, monkeypatch, child
        )
        assert out["data"].iloc[0] == '{"v": null}'
        assert warnings == [] and ctx.row_errors == []

    def test_a_pandas_null_child_output_is_written_as_json_null(self, monkeypatch):
        child = _RecordingChild(lambda v: pd.NA)
        out, _, _ = _run_nested(
            ['{"v":"a"}'], {"target": "$.v", "strategy": "rec"}, monkeypatch, child
        )
        assert out["data"].iloc[0] == '{"v": null}'

    def test_a_positional_child_keeps_the_ordinal_of_a_null_leaf(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        _run_nested(
            ['{"v":"a"}', '{"v":null}', '{"v":"c"}'],
            {"target": "$.v", "strategy": "rec"},
            monkeypatch,
            child,
        )
        assert child.frames[0]["_nested_leaves"].tolist() == ["a", None, "c"]


def test_the_new_cell_codes_are_declared_for_the_mixed_route_and_the_capability_table():
    from decoy_engine.execution._mixed_admission import CHUNK_VARIANT_WARNING_CODES
    from decoy_engine.execution.native._capabilities import capabilities_for

    new = {
        "nested_cell_oversized",
        "nested_cell_too_deep",
        "nested_cell_duplicate_key",
        "nested_cell_number_out_of_range",
        "nested_child_non_finite",
    }
    assert new <= CHUNK_VARIANT_WARNING_CODES
    assert new <= set(capabilities_for("nested").warning_codes)
