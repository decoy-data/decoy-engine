"""F07 E1 nested strategy tests: bounded cell reading, number lexemes and child output.

Split out of test_nested_strategy.py to keep both files under the size cap. The
tests are unchanged; the shared seed and context stand-ins live in
_nested_strategy_support.py.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from decoy_engine.execution._errors import StrategyError
from decoy_engine.execution._strategies.nested._handler import NestedStrategyHandler
from tests.unit.execution._nested_strategy_support import _FakeCtx, _seed

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
        for cell, kind in (('{"a":1.10}', "float64"), ('{"a":7}', "int64")):
            child = _RecordingChild(lambda v: v)
            _run_nested([cell], {"target": "$.a", "strategy": "rec"}, monkeypatch, child)
            assert str(child.frames[0]["_nested_leaves"].dtype) == kind

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
    assert new.issubset(CHUNK_VARIANT_WARNING_CODES)
    assert new.issubset(capabilities_for("nested").warning_codes)


class TestArraySelectorOnAScalarNumber:
    """A number is a plain int or float again, so an array selector on it fails typed, as on main."""

    @pytest.mark.parametrize(
        ("cell", "target"),
        [
            ("5", "$[*]"),
            ('{"a":5}', "$.a[*]"),
            ('{"a":1.5}', "$.a[*]"),
            # Lossy numbers stay `JsonNumber`; jsonpath-ng must not fail on them with a TypeError.
            ('{"a":1.10}', "$.a[*]"),
            ('{"a":1e400}', "$.a[*]"),
            ('{"a":-0}', "$.a[*]"),
            ("1e400", "$[*]"),
            ("-0", "$[*]"),
            ("1.10", "$[*]"),
        ],
    )
    def test_the_selector_gives_the_typed_unwritable_container_error(self, cell, target):
        handler = NestedStrategyHandler()
        with pytest.raises(StrategyError) as caught:
            handler.run(
                pd.DataFrame({"data": [cell]}),
                "data",
                _seed({"target": target, "strategy": "redact"}),
                _FakeCtx(),
            )
        assert caught.value.code == "nested_target_unwritable_container"


def test_every_fault_the_handler_records_maps_to_its_own_warning_code():
    from decoy_engine.execution._strategies.nested import _leaves

    codes = {}
    for fault in _leaves._FAULTS:
        warning = _leaves._warning(fault, "c", 0)
        codes[fault] = warning.code
    assert len(set(codes.values())) == len(_leaves._FAULTS)
    assert codes["not_json"] == "nested_cell_json_parse_error"
    assert codes["child_non_finite"] == "nested_child_non_finite"
    assert {"duplicate_key", "oversized", "too_deep"} < set(_leaves._FAULTS)
    # Every token the reader can raise has a row-error entry.
    from decoy_engine._canonical._json import STRICT_JSON_TOKENS

    assert {t for t in STRICT_JSON_TOKENS if t != "non_finite"} <= set(_leaves._FAULTS)


def _vault_ctx() -> _FakeCtx:
    from tests.unit.execution.test_tokenize import FakeVault

    ctx = _FakeCtx()
    ctx.vault_writer = FakeVault()  # tokenize checks for a vault before it checks the dtype
    return ctx


def _flat_vs_nested(name: str) -> tuple[Any, Any]:
    """The child run on the flat int64 leaf frame (the pre-E1 frame), and the same child under nested."""
    handler, child_seed = NestedStrategyHandler()._resolve_child(
        _seed({"target": "$.v", "strategy": name}, "ns")
    )
    outcomes = []
    for run in ("flat", "nested"):
        try:
            if run == "flat":
                frame, _ = handler.run(
                    pd.DataFrame({"c": [1, 2, 3]}), "c", child_seed, _vault_ctx()
                )
                outcomes.append(frame["c"].tolist())
            else:
                cells = ['{"v":1}', '{"v":2}', '{"v":3}']
                frame, _ = NestedStrategyHandler().run(
                    pd.DataFrame({"data": cells}),
                    "data",
                    _seed({"target": "$.v", "strategy": name}, "ns"),
                    _vault_ctx(),
                )
                outcomes.append([json.loads(c)["v"] for c in frame["data"].tolist()])
        except Exception as exc:
            outcomes.append((type(exc).__name__, getattr(exc, "code", None)))
    return outcomes[0], outcomes[1]


class TestNullFreeIntegerLeavesAreUnchanged:
    """AT-E1-13: a null-free integer leaf list gives each child the frame and the bytes it gave
    before E1. The oracle is the child run on the flat int64 frame, which is what the old
    nested code built."""

    @staticmethod
    def _children() -> list[str]:
        import decoy_engine.execution._strategies as strat

        return sorted(n for n in strat.SCALAR_HANDLERS if n != "nested")

    def test_every_scalar_child_matches_its_flat_run(self):
        mismatches = {}
        for name in self._children():
            flat, nested = _flat_vs_nested(name)
            if flat != nested:
                mismatches[name] = (flat, nested)
        assert mismatches == {}

    def test_tokenize_still_refuses_integer_leaves(self):
        flat, nested = _flat_vs_nested("tokenize")
        assert nested == flat == ("StrategyError", "tokenize_requires_string_dtype")

    def test_the_leaf_column_is_int64_without_a_null(self, monkeypatch):
        child = _RecordingChild(lambda v: v)
        _run_nested(
            ['{"v":1}', '{"v":2}', '{"v":3}'],
            {"target": "$.v", "strategy": "rec"},
            monkeypatch,
            child,
        )
        assert str(child.frames[0]["_nested_leaves"].dtype) == "int64"
