"""Strict JSON intake for every document the verifier trusts or inspects.

Pattern: RFC 8259 (JSON) with the hardening RFC 8785 section 3.2 and RFC 8725 assume of a
verifier: strict UTF-8 (no BOM), duplicate-member rejection at every depth, no trailing content,
no non-finite numbers, no unpaired surrogates, and size/depth/node limits applied before the
recursive decoder runs. Floats are refused outright: this profile has none, so JCS number
formatting is never load-bearing for a signed value. The engine's one strict reader (``decoy_engine._canonical``) does the parsing; this module sets
its profile options, maps its tokens to the frozen wire tokens and walks the result.
"""

from __future__ import annotations

import re
from typing import Any

from decoy_engine._canonical import STRICT_JSON_TOKENS, strict_json_loads
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
}

if set(OWNER_TOKEN_MAP) != set(STRICT_JSON_TOKENS):
    raise ImportError("the strict-json token map is out of step with the owner")

StrictJsonError = SignedEvidenceError

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[\[\]{}]', re.DOTALL)
_SURROGATE = re.compile("[\ud800-\udfff]")


def _err(code: ReasonCode) -> SignedEvidenceError:
    return SignedEvidenceError(code)


def _check_depth(text: str) -> None:
    depth = 0
    for m in _TOKEN.finditer(text):
        c = m.group(0)[0]
        if c in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise _err(ev.TOO_DEEP)
        elif c in "]}":
            depth = max(0, depth - 1)


def _walk(root: Any) -> None:
    nodes = 0
    stack = [root]
    while stack:
        node = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise _err(ev.TOO_MANY_NODES)
        if isinstance(node, dict):
            for key, value in node.items():
                if _SURROGATE.search(key):
                    raise _err(ev.INVALID_UNICODE)
                stack.append(value)
        elif isinstance(node, bool):
            continue
        elif isinstance(node, int):
            if abs(node) > MAX_SAFE_INT:
                raise _err(ev.INTEGER_OUT_OF_DOMAIN)
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str) and _SURROGATE.search(node):
            raise _err(ev.INVALID_UNICODE)


def parse_strict(data: bytes | bytearray | memoryview, *, max_bytes: int = MAX_BYTES) -> Any:
    raw = bytes(data)
    if len(raw) > max_bytes:
        raise _err(ev.TOO_LARGE)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _err(ev.BOM)
    text = ""
    undecodable = False
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        undecodable = True
    if undecodable:
        raise _err(ev.NOT_UTF8)
    _check_depth(text)
    token: ReasonCode | None = None
    value: Any = None
    try:
        value = strict_json_loads(
            text, max_int_digits=MAX_INT_DIGITS, forbid_float=True, forbid_negative_zero=True
        )
    except _OwnerError as exc:
        token = OWNER_TOKEN_MAP[exc.token]
    if token is not None:
        raise _err(token)
    _walk(value)
    return value
