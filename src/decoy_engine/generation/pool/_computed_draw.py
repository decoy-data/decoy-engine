"""Bits to values for the computed Faker draws (uuid, bounded integer, element choice).

Both sides use this module: masking draws the index or the 128 bits from a keyed kernel, the
generate side from a seeded word stream. What a drawn index or 16 bytes turn into is one fact and
lives here. `ComputedDrawSpec` is built once per column from the shared argument contract
(`providers_v2._faker_draw_contracts`) and carries the exact Arrow type every route must produce.

Source pattern: RFC 9562 section 5.4 (version 4: 122 random bits, version nibble `0100`, variant
bits `10`), laid over keyed pseudorandom bits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pyarrow as pa

from decoy_engine.generation.pool._identity import POOL_BUILD_KNOBS
from decoy_engine.providers_v2 import (
    FAMILY_INT,
    FAMILY_UUID,
    FakerDrawContract,
    faker_draw_contract,
)

__all__ = [
    "COMPUTED_NAMESPACE_MARKER",
    "ComputedDrawSpec",
    "DrawRefusal",
    "choice_from_index",
    "computed_draw_spec",
    "computed_selection_namespace",
    "draw_kwargs",
    "int_from_index",
    "parse_computed_draw",
    "uuid_from_bits",
    "uuid_from_hex",
]

Caller = Literal["mask", "faker_type", "provider"]
RefusalKind = Literal["range", "choice"]

# int64 holds the top value; the pool-size limit of the index kernel is 2**56.
_COUNT_MAX = 2**56
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1
COMPUTED_NAMESPACE_MARKER = "/computed:"
_HEX = np.frombuffer(b"0123456789abcdef", dtype=np.uint8)
_SCALARS = (str, int, float, bool)


@dataclass(frozen=True)
class DrawRefusal:
    """Why a draw's arguments are outside the contract: its range or its choice arguments."""

    kind: RefusalKind


@dataclass(frozen=True)
class ComputedDrawSpec:
    """One column's computed draw: what to draw, how many values it spans, the exact output type."""

    contract: FakerDrawContract
    caller: Caller
    output_type: pa.DataType
    lo: int = 0
    step: int = 1
    count: int = 0
    elements: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def family(self) -> str:
        return self.contract.family

    @property
    def provider(self) -> str:
        return self.contract.provider


def computed_selection_namespace(namespace: str, provider: str) -> str:
    """The key namespace for a computed draw, apart from any pool draw in the same column."""
    return f"{namespace}{COMPUTED_NAMESPACE_MARKER}{provider}"


def _is_int(value: Any) -> bool:
    return type(value) is int


def _parse_range(
    contract: FakerDrawContract, kwargs: Mapping[str, Any]
) -> tuple[int, int, int] | DrawRefusal:
    lo_key, hi_key, step_key = contract.arguments
    unknown = set(kwargs) - set(contract.arguments)
    if unknown:
        return DrawRefusal("range")
    lo = kwargs.get(lo_key, contract.defaults[lo_key])
    hi = kwargs.get(hi_key, contract.defaults[hi_key])
    step = kwargs.get(step_key, contract.defaults[step_key])
    if not (_is_int(lo) and _is_int(hi) and _is_int(step)):
        return DrawRefusal("range")
    if hi < lo or step < 1:
        return DrawRefusal("range")
    count = (hi - lo) // step + 1
    top = lo + (count - 1) * step
    if count > _COUNT_MAX or not (INT64_MIN <= lo <= INT64_MAX and top <= INT64_MAX):
        return DrawRefusal("range")
    return lo, step, count


def _homogeneous_type(elements: Sequence[Any]) -> pa.DataType | None:
    kinds = {type(e) for e in elements}
    if len(kinds) != 1 or not kinds <= set(_SCALARS):
        return None
    try:
        arrow = pa.array(list(elements))
    except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError):
        return None
    return arrow.type


def _parse_elements(
    contract: FakerDrawContract, kwargs: Mapping[str, Any], caller: Caller
) -> tuple[tuple[Any, ...], pa.DataType] | DrawRefusal:
    (key,) = contract.arguments
    if set(kwargs) - {key}:
        return DrawRefusal("choice")
    elements = kwargs.get(key, contract.defaults[key])
    if not isinstance(elements, (list, tuple)) or not elements:
        return DrawRefusal("choice")
    if not all(type(e) in _SCALARS for e in elements):
        return DrawRefusal("choice")
    if caller == "provider":
        return tuple(elements), pa.string()
    natural = _homogeneous_type(elements)
    if natural is None:
        return DrawRefusal("choice")
    return tuple(elements), natural


def parse_computed_draw(
    caller: Caller,
    name: str,
    kwargs: Mapping[str, Any] | None,
    *,
    planned_output_type: pa.DataType | None = None,
) -> ComputedDrawSpec | DrawRefusal | None:
    """Build the spec for a computed draw, a refusal if its arguments are out of contract, or
    `None` when `name` is not a computed draw. Messages never carry argument values."""
    contract = faker_draw_contract(name)
    if contract is None:
        return None
    args = kwargs or {}
    if contract.family == FAMILY_UUID:
        if args:
            # uuid takes no argument; it shares the argument-shape refusal of random_choice
            # (`computed_draw_elements_invalid`) rather than minting a code for one provider.
            return DrawRefusal("choice")
        return ComputedDrawSpec(contract, caller, pa.string())
    if contract.family == FAMILY_INT:
        parsed = _parse_range(contract, args)
        if isinstance(parsed, DrawRefusal):
            return parsed
        lo, step, count = parsed
        if caller == "provider":
            out = pa.string()
        elif caller == "faker_type" and planned_output_type is not None:
            out = planned_output_type
        else:
            out = pa.int64()
        return ComputedDrawSpec(contract, caller, out, lo=lo, step=step, count=count)
    parsed_choice = _parse_elements(contract, args, caller)
    if isinstance(parsed_choice, DrawRefusal):
        return parsed_choice
    elements, out = parsed_choice
    if caller == "faker_type" and planned_output_type is not None:
        out = planned_output_type
    return ComputedDrawSpec(contract, caller, out, count=len(elements), elements=elements)


def computed_draw_spec(
    caller: Caller,
    name: str,
    kwargs: Mapping[str, Any] | None,
    *,
    planned_output_type: pa.DataType | None = None,
) -> ComputedDrawSpec | None:
    """The spec, or `None` for a non-computed name or a refused shape (generate: stay per row)."""
    found = parse_computed_draw(caller, name, kwargs, planned_output_type=planned_output_type)
    return found if isinstance(found, ComputedDrawSpec) else None


def uuid_from_bits(bits: np.ndarray[Any, Any]) -> pa.Array:
    """`(n, 16)` uint8 bytes to RFC 9562 version 4 strings, `8-4-4-4-12` lowercase hex."""
    raw = np.array(bits, dtype=np.uint8, copy=True)
    if raw.ndim != 2 or raw.shape[1] != 16:
        raise ValueError("uuid bits must have shape (n, 16)")
    raw[:, 6] = (raw[:, 6] & 0x0F) | 0x40
    raw[:, 8] = (raw[:, 8] & 0x3F) | 0x80
    n = raw.shape[0]
    digits = np.empty((n, 32), dtype=np.uint8)
    digits[:, 0::2] = _HEX[raw >> 4]
    digits[:, 1::2] = _HEX[raw & 0x0F]
    text = np.full((n, 36), ord("-"), dtype=np.uint8)
    for src, dst, width in ((0, 0, 8), (8, 9, 4), (12, 14, 4), (16, 19, 4), (20, 24, 12)):
        text[:, dst : dst + width] = digits[:, src : src + width]
    offsets = (np.arange(n + 1, dtype=np.int32) * 36).astype(np.int32)
    return pa.StringArray.from_buffers(
        n, pa.py_buffer(offsets), pa.py_buffer(text.tobytes()), None, 0
    )


def uuid_from_hex(hexes: pa.Array) -> pa.Array:
    """Keyed hex tokens (32 chars, null where the source was null) to version 4 strings.

    A token that is not exactly 32 hex characters is a kernel fault, refused before decoding."""
    import pyarrow.compute as pc

    present = pc.is_valid(hexes).to_numpy(zero_copy_only=False)  # type: ignore[attr-defined, unused-ignore]
    tokens = pc.drop_null(hexes).to_pylist()  # type: ignore[attr-defined, unused-ignore]
    if any(len(t) != 32 for t in tokens):
        raise ValueError("keyed uuid token is not 32 hex characters")
    bits = np.frombuffer(bytes.fromhex("".join(tokens)), dtype=np.uint8).reshape(-1, 16)
    formatted = uuid_from_bits(bits)
    if len(tokens) == len(hexes):
        return formatted
    out: list[str | None] = [None] * len(hexes)
    for pos, value in zip(np.flatnonzero(present).tolist(), formatted.to_pylist(), strict=True):
        out[pos] = value
    return pa.array(out, type=pa.string())


def int_from_index(index: np.ndarray[Any, Any], *, lo: int, step: int) -> pa.Array:
    """`lo + index * step` as int64, for every range `parse_computed_draw` accepts.

    The arithmetic runs modulo 2**64 on uint64 operands, so a step at or past 2**63 (legal when
    the count is small) cannot overflow a conversion, and a wrapped product is exact because the
    final value fits int64. A step past 2**64 only occurs with one value, where the index is 0."""
    word = 1 << 64
    idx = np.asarray(index).astype(np.uint64, copy=False)
    with np.errstate(over="ignore"):
        wrapped = np.uint64(lo % word) + idx * np.uint64(step % word)
    return pa.array(wrapped.view(np.int64), type=pa.int64())


def choice_from_index(index: np.ndarray[Any, Any], elements: Sequence[Any]) -> list[Any]:
    """The element at each index as Python scalars, left for the caller to type and coerce."""
    table = np.empty(len(elements), dtype=object)
    for i, element in enumerate(elements):
        table[i] = element
    chosen: list[Any] = table[np.asarray(index, dtype=np.int64)].tolist()
    return chosen


def draw_kwargs(provider_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The draw arguments of a `provider_config`: everything but the pool-build knobs."""
    return {k: v for k, v in (provider_config or {}).items() if k not in POOL_BUILD_KNOBS}
