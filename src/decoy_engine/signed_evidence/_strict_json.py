"""Strict JSON intake for every document the verifier trusts or inspects.

Pattern: RFC 8259 (JSON) with the hardening RFC 8785 section 3.2 and RFC 8725 assume of a
verifier: strict UTF-8 (no BOM), duplicate-member rejection at every depth, no trailing content,
no non-finite numbers, no unpaired surrogates, and size/depth/node limits applied before the
recursive decoder runs. Floats are refused outright: this profile has none, so JCS number
formatting is never load-bearing for a signed value. The engine's one strict reader (``decoy_engine._canonical``) does the parsing; this module sets
its profile options, maps its tokens to the frozen wire tokens and walks the result.
"""

from __future__ import annotations

from typing import Any

from decoy_engine._canonical import STRICT_JSON_TOKENS, strict_json_read
from decoy_engine._canonical import StrictJsonError as _OwnerError
from decoy_engine.reasons import ReasonCode
from decoy_engine.reasons import evidence as ev

from ._errors import SignedEvidenceError

MAX_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 200_000
MAX_SAFE_INT = 2**53 - 1
MAX_INT_DIGITS = 16

#: The one map from the owner's closed tokens to this profile's frozen wire tokens.
OWNER_TOKEN_MAP: dict[str, ReasonCode] = {
    "duplicate_key": ev.DUPLICATE_MEMBER,
    "non_finite": ev.NON_FINITE_NUMBER,
    "negative_zero": ev.INTEGER_OUT_OF_DOMAIN,
    "float": ev.FLOAT_NOT_ALLOWED,
    "out_of_range": ev.INTEGER_OUT_OF_DOMAIN,
    "not_json": ev.NOT_JSON,
    "oversized": ev.TOO_LARGE,
    "too_deep": ev.TOO_DEEP,
}

if set(OWNER_TOKEN_MAP) != set(STRICT_JSON_TOKENS):
    raise ImportError("the strict-json token map is out of step with the owner")

StrictJsonError = SignedEvidenceError


def _walk(root: Any) -> None:
    """The profile's own limits: a node count and the JSON safe-integer range."""
    nodes = 0
    stack = [root]
    while stack:
        node = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise SignedEvidenceError(ev.TOO_MANY_NODES)
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, bool):
            continue
        elif isinstance(node, int):
            if abs(node) > MAX_SAFE_INT:
                raise SignedEvidenceError(ev.INTEGER_OUT_OF_DOMAIN)
        elif isinstance(node, list):
            stack.extend(node)


def parse_strict(data: bytes | bytearray | memoryview, *, max_bytes: int = MAX_BYTES) -> Any:
    raw = bytes(data)
    if len(raw) > max_bytes:
        raise SignedEvidenceError(ev.TOO_LARGE)
    # The owner reader names a BOM or bad UTF-8 only as not_json; the wire keeps them apart.
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SignedEvidenceError(ev.BOM)
    undecodable = False
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        undecodable = True
    if undecodable:
        raise SignedEvidenceError(ev.NOT_UTF8)
    owner_token: str | None = None
    value: Any = None
    try:
        value = strict_json_read(
            raw,
            max_bytes=max_bytes,
            max_depth=MAX_DEPTH,
            max_int_digits=MAX_INT_DIGITS,
            forbid_float=True,
            forbid_negative_zero=True,
        )
    except _OwnerError as exc:
        owner_token = exc.token
    if owner_token is not None:
        raise SignedEvidenceError(OWNER_TOKEN_MAP[owner_token])
    _walk(value)
    return value
