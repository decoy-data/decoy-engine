"""TEXT-REDACT-RUST-SPLICE S1a: the additive `text_span_splice` entry and its bound probe.

Raw tests (AT-2, AT-3, AT-4, AT-8, AT-6 raw codes) call the compiled entry directly. Probe tests
(AT-6) bind fake companions so each skew is varied on its own. Both need only synthetic text.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution.native import _text_mask_native_splice as splice_mod
from decoy_engine.execution.native._text_redact_kernel import (
    CATALOG_VERSION,
    SPLICE_CONTRACT_VERSION,
    SUPPORTED_IDS,
    load_text_redact_kernel,
    load_text_span_splice,
)
from tests.native._c6c_ii_support import ELIGIBLE_TEXTS, INELIGIBLE_TEXTS, oracle_text_redact
from tests.native.text_splice._detector_offset_support import (
    OVERSIZED_EMAIL,
    SHORT_EMAIL,
    build_tooling_missing,
    build_wheel_dir,
    run_snippet,
)

try:
    _REAL: Any = importlib.import_module("decoy_engine_native._kernel")
except Exception:  # companion absent
    _REAL = None

NEEDS_SPLICE = pytest.mark.skipif(
    _REAL is None or not hasattr(_REAL, "text_span_splice"),
    reason="companion without text_span_splice",
)
NEEDS_BUILD = pytest.mark.skipif(
    build_tooling_missing() is not None,
    reason=f"cannot build the test-limit wheel: {build_tooling_missing()}",
)
SRC = Path(__file__).resolve().parents[3] / "src"


def _call(values: Any, **overrides: Any) -> list[tuple[list[Any], list[Any]]]:
    kwargs: dict[str, Any] = {
        "detector_ids": ["email"],
        "outs": ["<X>"],
        "gap_out": None,
        "catalog_version": CATALOG_VERSION,
        "splice_contract_version": SPLICE_CONTRACT_VERSION,
    }
    kwargs.update(overrides)
    arr = values if isinstance(values, pa.Array) else pa.array(values, type=pa.string())
    pieces = _REAL.text_span_splice(arr, **kwargs)
    return [(v.to_pylist(), m.to_pylist()) for v, m in pieces]


def _flat(pieces: list[tuple[list[Any], list[Any]]]) -> tuple[list[Any], list[Any]]:
    return (
        [x for v, _ in pieces for x in v],
        [x for _, m in pieces for x in m],
    )


def _error_text(**kwargs: Any) -> str:
    with pytest.raises(ValueError) as caught:
        _call(["a@b.com"], **kwargs)
    return str(caught.value)


# ── raw entry ──────────────────────────────────────────────────────────────────────────────


@NEEDS_SPLICE
def test_the_contract_getter_reports_version_one() -> None:
    assert _REAL.text_span_splice_contract_version() == SPLICE_CONTRACT_VERSION == 1


@NEEDS_SPLICE
def test_at4_core_pins_email_passthrough_with_redacted_gaps() -> None:
    values, mask = _flat(
        _call(
            ["before a@b.com after", "plain", ""],
            outs=[None],
            gap_out="<X>",
        )
    )
    assert values == ["<X>a@b.com<X>", "<X>", ""]
    assert mask == [False, False, False]


@NEEDS_SPLICE
@pytest.mark.parametrize("batch", [1, 7, 65_536, None])
@pytest.mark.parametrize("threads", [None, 1, 4])
def test_at2_bytes_and_validity_match_the_oracle_at_every_batch_size(
    batch: int | None, threads: int | None
) -> None:
    rows: list[str | None] = []
    for i in range(70_000 // len(ELIGIBLE_TEXTS) + 1):
        rows.extend(None if (i + j) % 11 == 0 else t for j, t in enumerate(ELIGIBLE_TEXTS))
    rows = rows[:70_000]
    ids = list(SUPPORTED_IDS)
    size = batch or len(rows)
    got_values: list[Any] = []
    got_mask: list[Any] = []
    for start in range(0, len(rows), size):
        v, m = _flat(
            _call(
                rows[start : start + size],
                detector_ids=ids,
                outs=["[R]"] * len(ids),
                native_threads=threads,
            )
        )
        got_values += v
        got_mask += m
    assert got_values == oracle_text_redact(rows, detectors=None, token="[R]")
    assert not any(got_mask)


@NEEDS_SPLICE
def test_at3_string_large_string_and_offset_slices() -> None:
    base = ["skip a@b.com", "mail a@b.com now", None, "x"]
    for typ in (pa.string(), pa.large_string()):
        sliced = pa.array(base, type=typ).slice(1, 3)
        assert _flat(_call(sliced)) == (["mail <X> now", None, "x"], [False, False, False])


@NEEDS_SPLICE
def test_at3_empty_and_all_null_input_return_a_typed_pair() -> None:
    (values, mask), *rest = _REAL.text_span_splice(
        pa.array([], type=pa.string()),
        detector_ids=["email"],
        outs=["<X>"],
        gap_out=None,
        catalog_version=CATALOG_VERSION,
        splice_contract_version=SPLICE_CONTRACT_VERSION,
    )
    assert not rest
    assert values.type == pa.string() and len(values) == 0
    assert mask.type == pa.bool_() and len(mask) == 0
    assert _flat(_call([None, None])) == ([None, None], [False, False])


@NEEDS_SPLICE
def test_at3_declined_cells_are_masked_and_null() -> None:
    values, mask = _flat(_call(["a@b.com", None, INELIGIBLE_TEXTS[0], "a\x1fb a@b.com", "ok"]))
    assert values == ["<X>", None, None, None, "ok"]
    assert mask == [False, False, True, True, False]


@NEEDS_SPLICE
def test_at3_a_non_string_input_is_unsupported_with_a_fixed_code() -> None:
    with pytest.raises(ValueError, match=r"^text_splice_unsupported_type: "):
        _call(pa.array([1, 2], type=pa.int64()))


@NEEDS_SPLICE
def test_at3_label_replacement_gives_the_detector_label() -> None:
    values, _ = _flat(
        _call(
            ["mail a@b.com now"],
            detector_ids=["email"],
            outs=["[REDACTED:email]"],
        )
    )
    assert values == ["mail [REDACTED:email] now"]


@NEEDS_SPLICE
def test_at8_raw_duplicate_ids_with_identical_outcomes() -> None:
    assert _flat(_call(["a@b.com"], detector_ids=["email", "email"], outs=["<X>", "<X>"]))[0] == [
        "<X>"
    ]
    assert _flat(_call(["a@b.com"], detector_ids=["email", "email"], outs=[None, None]))[0] == [
        "a@b.com"
    ]


@NEEDS_SPLICE
@pytest.mark.parametrize(
    "outs", [["<A>", "<B>"], [None, "<B>"], ["<B>", None]], ids=["a-b", "none-b", "b-none"]
)
def test_at8_raw_duplicate_ids_with_conflicting_outcomes_are_rejected(outs: list[Any]) -> None:
    message = _error_text(detector_ids=["email", "email"], outs=outs)
    assert message.startswith("text_splice_output_invalid: ")
    assert "<A>" not in message and "<B>" not in message


@NEEDS_SPLICE
@pytest.mark.parametrize(
    ("ids", "outs", "gap"),
    [
        (["email"], [], None),
        (["email"], ["<X>", "<X>"], None),
        (["email"], [5], None),
        (["email"], [b"<X>"], None),
        (["email"], ["<X>"], 5),
        (["email"], ("<X>",), None),
        ([5], ["<X>"], None),
    ],
)
def test_at8_raw_malformed_outcomes_raise_the_fixed_wire_error(
    ids: list[Any], outs: Any, gap: Any
) -> None:
    message = _error_text(detector_ids=ids, outs=outs, gap_out=gap)
    assert message.startswith("text_splice_output_invalid: ")


@NEEDS_SPLICE
def test_at8_raw_an_empty_replacement_removes_the_email() -> None:
    values, mask = _flat(_call(["a@b.com"], outs=[""]))
    assert values == [""] and mask == [False]


@NEEDS_SPLICE
def test_at8_the_legacy_detect_splice_export_keeps_its_last_assignment_rule() -> None:
    def legacy(flags: list[bool]) -> list[Any]:
        return _REAL.text_mask_detect_splice(
            ["a@b.com"], ["email", "email"], flags, "<X>", False, CATALOG_VERSION
        )

    assert legacy([False, True]) == ["a@b.com"]
    assert legacy([True, False]) == ["<X>"]


@NEEDS_SPLICE
def test_at8_the_unequal_length_overlap_keeps_the_longer_email_in_both_orders() -> None:
    for ids in (["email", "ipv4"], ["ipv4", "email"]):
        values, _ = _flat(
            _call(
                ["10.0.0.1a@b.com"],
                detector_ids=ids,
                outs=["<E>" if i == "email" else "<I>" for i in ids],
            )
        )
        assert values == ["<E>"]


@NEEDS_SPLICE
def test_at8_an_exact_tie_takes_the_first_requested_literal() -> None:
    for ids, winner in ((["npi", "us_phone"], "<NPI>"), (["us_phone", "npi"], "<PHONE>")):
        outs = ["<NPI>" if i == "npi" else "<PHONE>" for i in ids]
        assert _flat(_call(["2234567891"], detector_ids=ids, outs=outs))[0] == [winner]


@NEEDS_SPLICE
@pytest.mark.parametrize("field", ["catalog_version", "splice_contract_version"])
@pytest.mark.parametrize(
    "bad",
    [True, "2", "1", 3, 0, 2.0, 2**70, None],
    ids=["bool", "str2", "str1", "three", "zero", "float", "huge", "none"],
)
def test_at6_raw_a_version_argument_must_be_the_exact_int(field: str, bad: Any) -> None:
    good = {"catalog_version": CATALOG_VERSION, "splice_contract_version": SPLICE_CONTRACT_VERSION}
    if bad == good[field] and type(bad) is int:
        pytest.skip("the one accepted value")
    code = "catalog" if field == "catalog_version" else "contract"
    with pytest.raises(ValueError, match=rf"^text_splice_{code}_mismatch: "):
        _call(["a@b.com"], **{field: bad})


@NEEDS_SPLICE
def test_at6_raw_an_int_subclass_is_not_the_exact_int() -> None:
    class Two(int):
        pass

    with pytest.raises(ValueError, match=r"^text_splice_catalog_mismatch: "):
        _call(["a@b.com"], catalog_version=Two(CATALOG_VERSION))
    with pytest.raises(ValueError, match=r"^text_splice_contract_mismatch: "):
        _call(["a@b.com"], splice_contract_version=Two(SPLICE_CONTRACT_VERSION))


@NEEDS_SPLICE
def test_at6_raw_an_unknown_id_is_a_fixed_value_free_error() -> None:
    sentinel = "SENTINEL-ID-9f3"
    message = _error_text(detector_ids=[sentinel], outs=["<X>"])
    assert message.startswith("text_splice_unknown_detector: ")
    assert sentinel not in message


@NEEDS_SPLICE
def test_raw_thread_budgets_validate_like_the_other_kernels() -> None:
    with pytest.raises(ValueError, match="native_threads"):
        _call(["a@b.com"], native_threads=0)


@pytest.fixture(scope="module")
def limit_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_wheel_dir(
        tmp_path_factory.mktemp("s1a-limit-wheel"), features="test-detector-offset-limit"
    )


_OVERSIZED_SNIPPET = f"""
import pyarrow as pa
from decoy_engine_native import _kernel as k
arr = pa.array([{OVERSIZED_EMAIL!r}, None, {SHORT_EMAIL!r}], type=pa.large_string())
only = pa.array([{OVERSIZED_EMAIL!r}], type=pa.large_string())
def run(a):
    out = k.text_span_splice(
        a, detector_ids=["email"], outs=["<X>"], gap_out=None,
        catalog_version=k.text_redact_catalog_version(),
        splice_contract_version=k.text_span_splice_contract_version(),
    )
    return [[v.to_pylist(), m.to_pylist()] for v, m in out]
print(json.dumps({{"mixed": run(arr), "only": run(only)}}))
"""


@NEEDS_BUILD
def test_at3_detector_offsets_decline_an_oversized_cell_on_the_additive_entry(
    limit_wheel: Path,
) -> None:
    got = run_snippet(_OVERSIZED_SNIPPET, wheel_dir=limit_wheel, core_src=SRC)
    assert got["mixed"] == [[[None, None, "<X>"], [True, False, False]]]
    assert got["only"] == [[[None], [True]]]


# ── bound probe ────────────────────────────────────────────────────────────────────────────


class _Calls:
    """Counts calls to each fake entry, so a rejected capability can be shown unused."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def wrap(self, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def inner(*args: Any, **kwargs: Any) -> Any:
            self.counts[name] = self.counts.get(name, 0) + 1
            return fn(*args, **kwargs)

        return inner


_KAT_PAIR = (["<X>", None, None], [False, True, False])


def _good_candidates(*_a: Any, **_k: Any) -> Any:
    return [[(0, 0, 7)], None, None]


def _good_additive(values: Any, **_k: Any) -> Any:
    return [(pa.array(_KAT_PAIR[0], type=pa.string()), pa.array(_KAT_PAIR[1], type=pa.bool_()))]


def _good_legacy(*_a: Any, **_k: Any) -> Any:
    return ["<X>", None, None]


def _attrs(calls: _Calls, **override: Any) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "abi_version": lambda: "decoy-native-abi-3",
        "text_redact_catalog_version": lambda: CATALOG_VERSION,
        "text_redact_supported_ids": lambda: list(SUPPORTED_IDS),
        "text_redact_candidates": calls.wrap("candidates", _good_candidates),
        "text_span_splice": calls.wrap("additive", _good_additive),
        "text_span_splice_contract_version": lambda: SPLICE_CONTRACT_VERSION,
        "text_mask_splice_spans": calls.wrap("legacy_spans", _good_legacy),
        "text_mask_detect_splice": calls.wrap("legacy_detect", _good_legacy),
    }
    attrs.update(override)
    return {k: v for k, v in attrs.items() if v is not _MISSING}


_MISSING = object()


def _install(mp: pytest.MonkeyPatch, attrs: dict[str, Any]) -> None:
    pkg = types.ModuleType("decoy_engine_native")
    kernel = types.ModuleType("decoy_engine_native._kernel")
    for name, value in attrs.items():
        setattr(kernel, name, value)
    pkg._kernel = kernel  # type: ignore[attr-defined]
    mp.setitem(sys.modules, "decoy_engine_native", pkg)
    mp.setitem(sys.modules, "decoy_engine_native._kernel", kernel)


def _loaded(**override: Any) -> tuple[Any, Any, Any, _Calls]:
    calls = _Calls()
    with pytest.MonkeyPatch.context() as mp:
        _install(mp, _attrs(calls, **override))
        return (
            load_text_redact_kernel(),
            load_text_span_splice(),
            splice_mod.load_splice_kernel(),
            calls,
        )


def test_at6_a_compatible_companion_selects_all_three_capabilities() -> None:
    kernel, additive, legacy, _ = _loaded()
    assert kernel is not None and additive is not None and legacy is not None


_BASE_SKEWS: dict[str, dict[str, Any]] = {
    "abi_mismatch": {"abi_version": lambda: "decoy-native-abi-2"},
    "abi_missing": {"abi_version": _MISSING},
    "abi_not_callable": {"abi_version": "decoy-native-abi-3"},
    "catalog_str": {"text_redact_catalog_version": lambda: "2"},
    "catalog_bool": {"text_redact_catalog_version": lambda: True},
    "catalog_other": {"text_redact_catalog_version": lambda: CATALOG_VERSION + 1},
    "catalog_helper_missing": {"text_redact_catalog_version": _MISSING},
    "ids_reordered": {"text_redact_supported_ids": lambda: list(reversed(SUPPORTED_IDS))},
    "ids_subset": {"text_redact_supported_ids": lambda: ["email"]},
    "candidates_missing": {"text_redact_candidates": _MISSING},
    "candidates_not_callable": {"text_redact_candidates": "nope"},
}


@pytest.mark.parametrize("skew", sorted(_BASE_SKEWS))
def test_at6_a_base_mismatch_selects_e1_and_calls_no_data_entry(skew: str) -> None:
    override = dict(_BASE_SKEWS[skew])
    calls = _Calls()
    # The rejected candidates stub would answer with an empty list if anything called it.
    if "text_redact_candidates" not in override:
        override["text_redact_candidates"] = calls.wrap("candidates", lambda *a, **k: [])
    with pytest.MonkeyPatch.context() as mp:
        _install(mp, _attrs(calls, **override))
        kernel = load_text_redact_kernel()
        additive = load_text_span_splice()
        legacy = splice_mod.load_splice_kernel()
    assert kernel is None and additive is None and legacy is None
    assert calls.counts == {}


_BAD_CANDIDATE_ANSWERS: dict[str, Any] = {
    "empty": [],
    "missing_match": [[], None, None],
    "float_offsets": [[(0, 0.0, 7.0)], None, None],
    "bool_index": [[(False, 0, 7)], None, None],
    "wrong_values": [[(0, 1, 7)], None, None],
    "outer_tuple": ([(0, 0, 7)], None, None),
    "cell_tuple": [((0, 0, 7),), None, None],
    "triple_list": [[[0, 0, 7]], None, None],
    "triple_long": [[(0, 0, 7, 9)], None, None],
    "extra_match": [[(0, 0, 7), (0, 0, 7)], None, None],
    "wrong_length": [[(0, 0, 7)], None],
    "tail_not_none": [[(0, 0, 7)], [], None],
}


@pytest.mark.parametrize("answer", sorted(_BAD_CANDIDATE_ANSWERS))
def test_at6_a_bad_candidates_answer_selects_e1_for_every_capability(answer: str) -> None:
    value = _BAD_CANDIDATE_ANSWERS[answer]
    kernel, additive, legacy, calls = _loaded(text_redact_candidates=lambda *a, **k: value)
    assert kernel is None and additive is None and legacy is None
    assert calls.counts == {}


def test_at6_a_candidates_probe_that_raises_selects_e1() -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("probe failed")

    kernel, additive, legacy, _ = _loaded(text_redact_candidates=boom)
    assert kernel is None and additive is None and legacy is None


_ADDITIVE_SKEWS: dict[str, dict[str, Any]] = {
    "entry_missing": {"text_span_splice": _MISSING},
    "entry_not_callable": {"text_span_splice": 1},
    "getter_missing": {"text_span_splice_contract_version": _MISSING},
    "version_two": {"text_span_splice_contract_version": lambda: 2},
    "version_bool": {"text_span_splice_contract_version": lambda: True},
    "version_str": {"text_span_splice_contract_version": lambda: "1"},
    "kat_wrong_values": {
        "text_span_splice": lambda *a, **k: [
            (pa.array(["x", None, None]), pa.array([False, True, False]))
        ]
    },
    "kat_wrong_mask": {
        "text_span_splice": lambda *a, **k: [
            (pa.array(["<X>", None, None]), pa.array([False, False, False]))
        ]
    },
    "kat_mask_type": {
        "text_span_splice": lambda *a, **k: [(pa.array(["<X>", None, None]), pa.array([0, 1, 0]))]
    },
    "kat_mask_has_null": {
        "text_span_splice": lambda *a, **k: [
            (pa.array(["<X>", None, None]), pa.array([False, True, None]))
        ]
    },
    "kat_no_pieces": {"text_span_splice": lambda *a, **k: []},
    "kat_two_pieces": {
        "text_span_splice": lambda *a, **k: [
            (pa.array(["<X>"]), pa.array([False])),
            (pa.array([None, None], type=pa.string()), pa.array([True, False])),
        ]
    },
    "kat_raises": {"text_span_splice": lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))},
}


@pytest.mark.parametrize("skew", sorted(_ADDITIVE_SKEWS))
def test_at6_an_additive_failure_selects_e1b_and_keeps_candidates_and_legacy(skew: str) -> None:
    kernel, additive, legacy, _ = _loaded(**_ADDITIVE_SKEWS[skew])
    assert kernel is not None
    assert additive is None
    assert legacy is not None


@pytest.mark.parametrize("which", ["text_mask_splice_spans", "text_mask_detect_splice"])
@pytest.mark.parametrize(
    "bad", [_MISSING, lambda *a, **k: ["<X>", "<X>", None], lambda *a, **k: ["<X>"], "x"]
)
def test_at6_a_failed_legacy_check_disables_legacy_splice_only(which: str, bad: Any) -> None:
    kernel, additive, legacy, _ = _loaded(**{which: bad})
    assert kernel is not None and additive is not None
    assert legacy is None


def test_at6_the_probe_runs_once_per_companion_instance() -> None:
    calls = _Calls()
    with pytest.MonkeyPatch.context() as mp:
        _install(mp, _attrs(calls))
        for _ in range(3):
            load_text_redact_kernel()
            load_text_span_splice()
            splice_mod.load_splice_kernel()
        first = dict(calls.counts)
        # A different companion instance rebinds and probes again.
        other = _Calls()
        _install(mp, _attrs(other))
        load_text_redact_kernel()
        load_text_span_splice()
        splice_mod.load_splice_kernel()
    assert first == {"candidates": 1, "additive": 1, "legacy_spans": 1, "legacy_detect": 1}
    assert other.counts == first


def test_at6_a_rejection_is_cached_for_the_instance() -> None:
    calls = _Calls()
    with pytest.MonkeyPatch.context() as mp:
        _install(mp, _attrs(calls, abi_version=lambda: "decoy-native-abi-2"))
        for _ in range(3):
            assert load_text_redact_kernel() is None
            assert load_text_span_splice() is None
    assert calls.counts == {}


def test_at6_the_additive_wrapper_sends_the_exact_versions() -> None:
    seen: dict[str, Any] = {}

    def spy(values: Any, **kwargs: Any) -> Any:
        if len(values) == 3 and not seen.get("probe_done"):
            seen["probe_done"] = True
            return _good_additive(values)
        seen.update(kwargs)
        return _good_additive(values)

    _, additive, _, _ = _loaded(text_span_splice=spy)
    assert additive is not None
    additive(pa.array(["a"]), detector_ids=["email"], outs=["<X>"], gap_out=None, native_threads=4)
    assert type(seen["catalog_version"]) is int and seen["catalog_version"] == CATALOG_VERSION
    assert type(seen["splice_contract_version"]) is int
    assert seen["splice_contract_version"] == SPLICE_CONTRACT_VERSION
    assert seen["detector_ids"] == ["email"] and seen["native_threads"] == 4


@NEEDS_SPLICE
def test_at6_the_real_companion_passes_its_own_probe() -> None:
    assert load_text_redact_kernel() is not None
    assert load_text_span_splice() is not None
    assert splice_mod.load_splice_kernel() is not None


def test_the_probe_reads_the_crypto_loaders_abi_pin_and_holds_no_second_literal() -> None:
    import ast
    import inspect

    from decoy_engine.execution.native import _text_redact_kernel as mod
    from decoy_engine.execution.native._crypto_ext import _EXPECTED_ABI_VERSION

    assert mod._EXPECTED_ABI == _EXPECTED_ABI_VERSION
    literals = [
        n.value
        for n in ast.walk(ast.parse(inspect.getsource(mod)))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert not [v for v in literals if v.startswith("decoy-native-abi")]
