"""C6c-ii: per-cell ASCII-domain routing for the native `text_redact` span detection.

The oracle's `iter_spans` runs eleven detectors in Python per cell. C6c-ii moved the eight
lookaround-free detectors (`email`, `us_phone`, `pan`, `iban`, `ipv4`, `icd10`, `npi`, `url`)
into the compiled companion for cells in the ASCII-safe domain; the lookaround port then added the
remaining three (`ssn`, `us_zip`, `street_address`, which use lookahead/lookbehind) as hand-written
ASCII byte scanners (`fancy-regex` was tried and rejected on measured perf; see the text_redact.rs
module doc), so all eleven built-ins run in Rust on an eligible cell. On that domain Python's
`\\d`/`\\s`/`\\w`/`\\b`/ASCII case-fold classes and the Rust `(?-u)` classes coincide
code-point-for-code-point (plan 2.1/2.2). Every other cell (non-ASCII, a 0x1c-0x1f separator, a
lone surrogate, a non-string) still stays on the unchanged Python path, so the spliced output is
byte-identical to the oracle always.

This module owns three pieces the wrapper in `_kernels_scalar.py` builds on:

- The versioned detector catalog (ids, labels, Rust-supported flag) mirrored in Rust under
  `CATALOG_VERSION`. The loader rejects a version or supported-set skew and falls back to full
  Python (plan 4.6); a detector known to the oracle but not in the supported set runs in Python,
  never a silent no-op.
- `load_text_redact_kernel()`, which returns a thin kernel wrapper or `None` (companion absent,
  the symbol absent on an older companion, or a catalog skew), each resolving to the literal
  Python path.
- `merge_text_redact_spans(...)`, which assembles one cell's final span list in the EXACT order
  `iter_spans` builds it (extras, then built-ins in requested order, then custom), so Python's
  stable sort resolves ties identically. A supported built-in's candidates come from the Rust
  call; any unsupported built-in (and the custom specs) run `finditer` here.

Keeping `finditer` out of `_kernels_scalar.py` is deliberate: that module's "no regex of its own"
contract (C6c-i) stays intact because every regex call for the lookaround/custom path lives here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from decoy_engine.detection.detectors import _SPAN_DETECTORS, Span
from decoy_engine.execution.native._crypto_ext import _EXPECTED_ABI_VERSION

if TYPE_CHECKING:
    from collections.abc import Sequence

# The eleven Rust-supported detector ids, in catalog order. The index returned by the Rust kernel
# is a position in this tuple; it maps back to the id (and its `[REDACTED:<id>]` label) here. The
# first eight are the lookaround-free detectors (regex crate); the last three are the lookaround
# detectors ported as hand-written ASCII byte scanners, appended so the first eight keep their
# indices. Keep in sync with `decoy-engine-native/src/text_redact.rs::SUPPORTED_IDS`.
SUPPORTED_IDS: tuple[str, ...] = (
    "email",
    "us_phone",
    "pan",
    "iban",
    "ipv4",
    "icd10",
    "npi",
    "url",
    "ssn",
    "us_zip",
    "street_address",
)
_SUPPORTED_SET = frozenset(SUPPORTED_IDS)
_INDEX_OF: dict[str, int] = {det_id: i for i, det_id in enumerate(SUPPORTED_IDS)}

# The detector-catalog contract id. Bump when ANY detector's id, order, label, pattern, validator,
# OR Rust-supported flag changes (plan 4.6). The Rust mirror (`text_redact.rs::CATALOG_VERSION`)
# must match this exactly, or the loader falls back to full Python. v2 added the three lookaround
# detectors (`ssn`, `us_zip`, `street_address`) to the supported set.
CATALOG_VERSION = 2

# The label emitted for a detector under `label_token=True` is the detector id itself (the oracle's
# `_splice` reads `Span.detector_id`), so the catalog's label column equals its id column. An
# agreement test pins that the Rust-supported set, order, labels and version all match.
CATALOG_LABELS: dict[str, str] = {det_id: det_id for det_id in SUPPORTED_IDS}


def is_ascii_safe(text: str) -> bool:
    """The routing predicate (plan 2.1): every code point is ASCII and none is in 0x1c-0x1f.

    This Python mirror of the Rust `is_eligible` exists for the boundary tests; the live routing
    decision is the kernel's own per-cell `None` return. A lone surrogate is not ASCII, so it is
    ineligible here and cannot be decoded to a Rust `str` there -- both route it to Python.
    """
    return text.isascii() and not any("\x1c" <= ch <= "\x1f" for ch in text)


class TextRedactKernel(Protocol):
    """The compiled span kernel as this module calls it."""

    def text_redact_candidates(
        self,
        values: Sequence[object],
        detector_ids: Sequence[str],
        catalog_version: int,
    ) -> list[list[tuple[int, int, int]] | None]: ...


class _CompiledTextRedactKernel:
    """Thin wrapper over the companion's `_kernel.text_redact_candidates`."""

    def __init__(self, candidates_fn: Any) -> None:
        self._candidates_fn = candidates_fn

    def text_redact_candidates(
        self,
        values: Sequence[object],
        detector_ids: Sequence[str],
        catalog_version: int,
    ) -> list[list[tuple[int, int, int]] | None]:
        return self._candidates_fn(values, list(detector_ids), catalog_version)


# The wire contract of the additive `text_span_splice` entry; the companion reports the same value
# from `text_span_splice_contract_version()`. Bump both when its arguments or result change.
SPLICE_CONTRACT_VERSION = 1

# The ABI tag this core runs against: the crypto loader's one pin, so an ABI change is one edit.
_EXPECTED_ABI = _EXPECTED_ABI_VERSION

# The known-answer cells every probe runs. Synthetic: one match, one non-ASCII decline, one null.
_KAT_CELLS = ["a@b.com", "café", None]
_KAT_TOKEN = "<X>"  # noqa: S105 - a replacement literal, not a credential


class TextSpanSplice(Protocol):
    """The additive Arrow splice entry as job code calls it."""

    def __call__(
        self,
        values: Any,
        *,
        detector_ids: Sequence[str],
        outs: Sequence[str | None],
        gap_out: str | None,
        native_threads: int | None = None,
    ) -> list[tuple[Any, Any]]: ...


@dataclass(frozen=True)
class CompanionCompat:
    """One compatibility decision for one imported companion, shared by every loader.

    `candidates` is None when the base agreement or the candidates known-answer test failed (E1:
    nothing else is usable either). `additive` is the checked `text_span_splice` entry, or None
    (E1b). `legacy` is the checked `(text_mask_splice_spans, text_mask_detect_splice)` pair, or
    None when either legacy check failed.
    """

    candidates: Callable[..., Any] | None
    additive: Callable[..., Any] | None
    legacy: tuple[Callable[..., Any], Callable[..., Any]] | None


_REJECTED = CompanionCompat(None, None, None)
# The last decision, keyed by the companion module and the core catalog version it was made for. A
# different module object (a reinstall, a test double) or core version rebinds; the same pair never
# probes twice.
_BOUND: tuple[object, int, CompanionCompat] | None = None


def _is_exact_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _candidates_kat_ok(candidates_fn: Callable[..., Any]) -> bool:
    answer = candidates_fn(_KAT_CELLS, ["email"], CATALOG_VERSION)
    if type(answer) is not list or len(answer) != 3:
        return False
    first = answer[0]
    if type(first) is not list or len(first) != 1:
        return False
    triple = first[0]
    if type(triple) is not tuple or len(triple) != 3:
        return False
    if not all(type(field) is int for field in triple):
        return False
    return triple == (0, 0, 7) and answer[1] is None and answer[2] is None


def _additive_kat_ok(additive_fn: Callable[..., Any]) -> bool:
    import pyarrow as pa

    result = additive_fn(
        pa.array(_KAT_CELLS, type=pa.string()),
        detector_ids=["email"],
        outs=[_KAT_TOKEN],
        gap_out=None,
        catalog_version=CATALOG_VERSION,
        splice_contract_version=SPLICE_CONTRACT_VERSION,
    )
    if type(result) is not list or len(result) != 1:
        return False
    pair = result[0]
    if type(pair) is not tuple or len(pair) != 2:
        return False
    values, mask = pair
    if not isinstance(values, pa.Array) or not isinstance(mask, pa.Array):
        return False
    if values.type != pa.string() or mask.type != pa.bool_():
        return False
    if len(values) != 3 or len(mask) != 3 or mask.null_count != 0:
        return False
    return values.to_pylist() == [_KAT_TOKEN, None, None] and mask.to_pylist() == [
        False,
        True,
        False,
    ]


def _legacy_pair(kernel: Any) -> tuple[Callable[..., Any], Callable[..., Any]] | None:
    splice_spans = getattr(kernel, "text_mask_splice_spans", None)
    detect_splice = getattr(kernel, "text_mask_detect_splice", None)
    if not callable(splice_spans) or not callable(detect_splice):
        return None
    expected = [_KAT_TOKEN, None, None]
    spans = splice_spans(_KAT_CELLS, [[(0, 7, False)], [], []], _KAT_TOKEN, True)
    detected = detect_splice(_KAT_CELLS, ["email"], [False], _KAT_TOKEN, True, CATALOG_VERSION)
    if spans != expected or detected != expected:
        return None
    return splice_spans, detect_splice


def _additive_entry(kernel: Any) -> Callable[..., Any] | None:
    entry = getattr(kernel, "text_span_splice", None)
    getter = getattr(kernel, "text_span_splice_contract_version", None)
    if not callable(entry) or not callable(getter):
        return None
    if not _is_exact_int(getter(), SPLICE_CONTRACT_VERSION):
        return None
    return entry if _additive_kat_ok(entry) else None


def _decide(kernel: Any) -> CompanionCompat:
    abi_fn = getattr(kernel, "abi_version", None)
    version_fn = getattr(kernel, "text_redact_catalog_version", None)
    supported_fn = getattr(kernel, "text_redact_supported_ids", None)
    candidates_fn = getattr(kernel, "text_redact_candidates", None)
    if (
        not callable(abi_fn)
        or not callable(version_fn)
        or not callable(supported_fn)
        or not callable(candidates_fn)
    ):
        return _REJECTED
    if abi_fn() != _EXPECTED_ABI:
        return _REJECTED
    if not _is_exact_int(version_fn(), CATALOG_VERSION):
        return _REJECTED
    if tuple(supported_fn()) != SUPPORTED_IDS:
        return _REJECTED
    if not _candidates_kat_ok(candidates_fn):
        return _REJECTED
    # Each capability past the base is checked on its own, so one failing leaves the others.
    additive = _guarded(_additive_entry, kernel)
    legacy = _guarded(_legacy_pair, kernel)
    return CompanionCompat(candidates_fn, additive, legacy)


def _guarded(check: Callable[[Any], Any], kernel: Any) -> Any:
    try:
        return check(kernel)
    except Exception:
        return None


def companion_compat() -> CompanionCompat:
    """The compatibility decision for the importable companion (all-None when absent or skewed).

    Computed once per companion module object. The candidates loader, the legacy splice loader and
    the additive probe all read this one result, so no job path can reach a data entry that a
    check rejected.
    """
    global _BOUND
    try:
        from decoy_engine_native import _kernel
    except Exception:
        # Absent, or `sys.modules["decoy_engine_native"] = None` (the tests' companion-absent
        # simulation), or any import-time failure: run the full Python path.
        return _REJECTED
    if _BOUND is not None and _BOUND[0] is _kernel and _BOUND[1] == CATALOG_VERSION:
        return _BOUND[2]
    try:
        decision = _decide(_kernel)
    except Exception:
        decision = _REJECTED
    _BOUND = (_kernel, CATALOG_VERSION, decision)
    return decision


def load_text_redact_kernel() -> TextRedactKernel | None:
    """Return the compiled span kernel, or `None` to run the full Python path.

    `None` (never an exception) is returned when the companion is absent or fails to import, is an
    older build without the `text_redact_candidates` symbol or its agreement helpers, reports the
    wrong ABI tag, or its catalog version / supported set / known answer does not match this
    core's. Each case resolves to the literal C6c-i Python detection path, so output is unchanged.
    A silent per-cell `None` from the kernel (ineligible cell) is a different mechanism and is
    handled by the caller, not here.
    """
    candidates = companion_compat().candidates
    return None if candidates is None else _CompiledTextRedactKernel(candidates)


def load_text_span_splice() -> TextSpanSplice | None:
    """The checked additive Arrow splice entry, or `None` (E1/E1b) to keep the candidates path."""
    entry = companion_compat().additive
    if entry is None:
        return None

    def call(
        values: Any,
        *,
        detector_ids: Sequence[str],
        outs: Sequence[str | None],
        gap_out: str | None,
        native_threads: int | None = None,
    ) -> list[tuple[Any, Any]]:
        return entry(
            values,
            detector_ids=list(detector_ids),
            outs=list(outs),
            gap_out=gap_out,
            catalog_version=CATALOG_VERSION,
            splice_contract_version=SPLICE_CONTRACT_VERSION,
            native_threads=native_threads,
        )

    return call


def requested_rust_ids(detector_ids: list[str] | None) -> list[str]:
    """The Rust-supported subset of `detector_ids`, in the requested order (plan 2.3).

    `None` means the oracle's "all built-in detectors", whose Rust-supported members are
    `SUPPORTED_IDS` in catalog order. Duplicates and unknown ids are preserved/dropped exactly as
    the merge replays them: a duplicate supported id re-emits the same spans (the overlap sweep
    collapses them), so sending it once is byte-equivalent and the kernel receives each requested
    occurrence filtered to the supported set.
    """
    if detector_ids is None:
        return list(SUPPORTED_IDS)
    # Dedupe, preserving first-seen order: the kernel need only scan each detector once. The merge
    # replays each requested occurrence against that one scan, so a repeated supported id still
    # emits its spans once per occurrence, exactly as the oracle's repeated `finditer` pass does.
    seen: set[str] = set()
    ids: list[str] = []
    for det_id in detector_ids:
        if det_id in _SUPPORTED_SET and det_id not in seen:
            seen.add(det_id)
            ids.append(det_id)
    return ids


def merge_text_redact_spans(
    text: str,
    detector_ids: list[str] | None,
    *,
    rust_candidates: list[tuple[int, int, int]] | None,
    custom: list[dict[str, Any]] | None = None,
    extra_spans: list[Span] | None = None,
) -> list[Span]:
    """Assemble one cell's resolved spans, reproducing `iter_spans` exactly (plan 4.3).

    `rust_candidates` is the kernel's per-cell list `[(detector_index, start, end), ...]` for an
    eligible cell, or `None` to run every detector in Python (an ineligible cell, equivalent to
    `iter_spans`). The candidate order is the oracle's: `extra_spans` (NER, supplied order), then
    the built-ins in `detector_ids` order -- each eligible supported detector's spans taken from
    `rust_candidates`, every other detector run through its Python regex + validator in `finditer`
    order -- then custom (supplied spec then `finditer` order). A stable sort by
    `(start, -(end - start))` then a leftmost-then-longest sweep (`start >= last_end`, zero-length
    custom spans included) resolves overlaps. `_splice` is the caller's.
    """
    if not text:
        return []

    candidates: list[Span] = list(extra_spans or [])

    rust_by_index: dict[int, list[tuple[int, int, int]]] = {}
    if rust_candidates is not None:
        for triple in rust_candidates:
            rust_by_index.setdefault(triple[0], []).append(triple)

    # `None` is the oracle's "all built-in detectors" in `_SPAN_DETECTORS` insertion order, which
    # is the order its stable sort breaks ties by; preserve it exactly (never supported-first).
    ids = list(_SPAN_DETECTORS.keys()) if detector_ids is None else detector_ids

    for det_id in ids:
        if rust_candidates is not None and det_id in _SUPPORTED_SET:
            for _idx, start, end in rust_by_index.get(_INDEX_OF[det_id], ()):
                candidates.append(Span(det_id, start, end, text[start:end]))
            continue
        entry = _SPAN_DETECTORS.get(det_id)
        if entry is None:
            continue
        regex, validator = entry
        for m in regex.finditer(text):
            matched = m.group(0)
            if validator is not None and not validator(matched):
                continue
            candidates.append(Span(det_id, m.start(), m.end(), matched))

    for spec in custom or []:
        pattern = spec["pattern"]
        validator = spec.get("validator")
        det_id = spec["detector_id"]
        for m in pattern.finditer(text):
            matched = m.group(0)
            if validator is not None and not validator(matched):
                continue
            candidates.append(Span(det_id, m.start(), m.end(), matched))

    candidates.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[Span] = []
    last_end = -1
    for s in candidates:
        if s.start >= last_end:
            out.append(s)
            last_end = s.end
    return out


__all__ = [
    "CATALOG_LABELS",
    "CATALOG_VERSION",
    "SPLICE_CONTRACT_VERSION",
    "SUPPORTED_IDS",
    "CompanionCompat",
    "TextRedactKernel",
    "TextSpanSplice",
    "companion_compat",
    "is_ascii_safe",
    "load_text_redact_kernel",
    "load_text_span_splice",
    "merge_text_redact_spans",
    "requested_rust_ids",
]
