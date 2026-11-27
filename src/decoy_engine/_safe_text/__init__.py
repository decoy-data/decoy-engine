"""Text that provably came from a string written in source (F31 AE1).

``SafeText.const`` and ``SafeText.literal_template`` print only a ``str`` that the calling code
loads as a constant at that exact call: the call's first positional argument must be one
``LOAD_CONST`` of the same object, with no branch jumping into the argument. A row value, an
f-string with a field, a wrapper's parameter or a variable can never become safe text, even when
the same function mentions an equal literal elsewhere. A failed check never keeps the argument: under the strict
switch (tests only) it raises ``TypeError`` naming the call site; otherwise it returns ``WITHHELD``
and logs one value-free warning per call site. A value that passes discloses only that it equals a
literal in the calling code. This leaf imports nothing from ``decoy_engine`` so any layer can use it.

Two modes fail closed, by design. The strict fixture in ``tests/conftest.py`` is function-scoped, so
session- and module-scoped fixtures and subprocesses run non-strict (they withhold and log instead
of raising). Code rebuilt from an AST, such as pytest's assert rewriting (which passes each argument through a
temporary variable), can hide the literal, so a check there can withhold text that looks like a
literal in source. Build the text outside an ``assert`` statement in tests.
"""

from __future__ import annotations

import dis
import functools
import inspect
import logging
import os
import string
from collections.abc import Mapping
from types import CodeType
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from typing_extensions import LiteralString

__all__ = ["WITHHELD", "SafeText"]

_LOG = logging.getLogger(__name__)
# One-character strings are cached by CPython, so identity with a literal proves nothing.
_MIN_LEN: Final = 2
_SLOT_WITHHELD: Final = "<withheld>"
_MUTMUT_PREFIX: Final = "mutmut."
_KEY: Final = object()
_Site = tuple[str, str, int]
_warned: set[_Site] = set()
_strict = False
_strict_pid = 0


class _Withheld:
    """The one value standing for text that failed the check; it prints as nothing."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "WITHHELD"

    def __str__(self) -> str:
        return ""

    def __bool__(self) -> bool:
        return False

    def __reduce__(self) -> str:
        return "WITHHELD"  # pickle looks the name up in this module, so identity survives


WITHHELD: Final = _Withheld()


def _set_strict(on: bool) -> bool:
    """Test-only switch; returns the previous value. Production never calls it.

    The switch counts only in the process that set it, so a forked child that inherits ``True``
    runs non-strict like production.
    """
    global _strict, _strict_pid
    previous = _strict_active()  # the effective value: a forked child inherits a raw True
    _strict, _strict_pid = on, os.getpid()
    return previous


def _strict_active() -> bool:
    return _strict and _strict_pid == os.getpid()


def _caller_code() -> tuple[tuple[CodeType, int] | None, _Site]:
    """The code object, call offset and call site of the first frame outside this module and mutmut.

    Frames are skipped by module name only, never by function name, so a caller cannot hide
    behind a function called ``trampoline``. No frame, or any error, means no proof.
    """
    frame = None
    try:
        frame = inspect.currentframe()
        while frame is not None:
            module = str(frame.f_globals.get("__name__", ""))
            if module != __name__ and not module.startswith(_MUTMUT_PREFIX):
                code = frame.f_code
                return (code, frame.f_lasti), (module, code.co_name, frame.f_lineno)
            frame = frame.f_back
    except Exception:  # fail closed
        pass
    finally:
        del frame
    return None, ("unknown", "unknown", 0)


_NO_LITERAL: Final = -1


_CALL_PREFIX: Final = ("PRECALL", "KW_NAMES")  # 3.11 and 3.12: call set-up before CALL


@functools.lru_cache(maxsize=512)
def _literal_index_at_call(code: CodeType, lasti: int) -> int:
    """The ``co_consts`` index of the constant the call at ``lasti`` passes first, or -1.

    The cache holds an index, never the string: equal code objects share a cache entry, and the
    identity check must run against the caller's own constants.

    Walks back from the call over the argument pushes until the first positional argument is
    reached. It is a literal only when that one instruction is ``LOAD_CONST`` and no branch jumps
    into the span, so ``x if c else "lit"`` and ``x or "lit"`` never qualify. A branch inside a
    later argument also withholds: the walk cannot count the stack there. Built from the bytecode
    of 3.10 to 3.12 (``CALL_FUNCTION_KW`` on 3.10, ``KW_NAMES`` and ``PRECALL`` on 3.11).
    """
    try:
        ins = list(dis.get_instructions(code))
        # f_lasti can point into the inline cache after the call, which dis hides: take the
        # last instruction at or before it.
        at = max(i for i, op in enumerate(ins) if op.offset <= lasti)
        call = ins[at]
        if not call.opname.startswith("CALL") or call.opname == "CALL_FUNCTION_EX":
            return _NO_LITERAL
        total = int(call.arg or 0)
        names = 0
        need = total
        top = at  # first instruction of the call set-up; the argument pushes end before it
        if call.opname == "CALL_FUNCTION_KW":  # 3.10: the keyword names are a pushed tuple
            names, need = len(ins[at - 1].argval), total + 1
        else:
            while top > 0 and ins[top - 1].opname in _CALL_PREFIX:
                top -= 1
                if ins[top].opname == "KW_NAMES":
                    names = len(code.co_consts[int(ins[top].arg or 0)])
        if total - names < 1:  # no positional argument: keyword-only text is no proof
            return _NO_LITERAL
        acc = 0
        for j in range(top - 1, -1, -1):
            op = ins[j]
            acc += (
                dis.stack_effect(op.opcode, op.arg, jump=False)
                if op.opcode >= dis.HAVE_ARGUMENT
                else dis.stack_effect(op.opcode)
            )
            if acc >= need:
                break
        else:
            return _NO_LITERAL
        if acc != need or ins[j].opname != "LOAD_CONST":
            return _NO_LITERAL
        if any(x.is_jump_target for x in ins[j + 1 : at + 1]):
            return _NO_LITERAL
        return int(ins[j].arg or 0)
    except Exception:  # fail closed
        return _NO_LITERAL


def _is_constant(text: object, caller: tuple[CodeType, int] | None) -> bool:
    # Exact ``str`` first: a subclass's __len__ or a dead weakref proxy must not run or raise here.
    if caller is None or type(text) is not str or len(text) < _MIN_LEN:
        return False
    code, lasti = caller
    index = _literal_index_at_call(code, lasti)
    return index >= 0 and code.co_consts[index] is text


def _refuse(site: _Site) -> _Withheld:
    where = f"{site[0]}:{site[1]}:{site[2]}"
    if _strict_active():
        raise TypeError(f"SafeText needs a string literal at {where}")
    if site not in _warned:
        _warned.add(site)
        _LOG.warning("SafeText withheld a non-literal at %s", where)
    return WITHHELD


class SafeText:
    """Text proven to be a source literal. Build it with ``const`` or ``literal_template``."""

    __slots__ = ("_text",)
    _text: str

    # Any, not ``SafeText | _Withheld``: a union would force every caller to narrow a direct
    # ``SafeText(...)`` call, which is refused anyway. Public builders return the union.
    def __new__(cls, text: str = "", *, _key: object = None) -> Any:
        if _key is not _KEY:  # a direct SafeText(...) has no provenance
            return _refuse(_caller_code()[1])
        self = object.__new__(cls)
        object.__setattr__(self, "_text", text)
        return self

    @classmethod
    def const(cls, text: LiteralString) -> SafeText | _Withheld:
        caller, site = _caller_code()
        if not _is_constant(text, caller):
            return _refuse(site)
        return cls(text, _key=_KEY)

    @classmethod
    def literal_template(
        cls,
        fmt: LiteralString,
        *,
        names: Mapping[str, Any] | None = None,
        paths: Mapping[str, Any] | None = None,
    ) -> SafeText | _Withheld:
        """A literal format string. AE1a1 has no safe slot type, so every slot is withheld."""
        # ``names`` and ``paths`` are reserved for AE1a2 (safe slot types); unused here.
        caller, site = _caller_code()
        if not _is_constant(fmt, caller):
            return _refuse(site)
        try:
            parts: list[tuple[str, str | None, str | None, str | None]] | None = list(
                string.Formatter().parse(fmt)
            )
        except ValueError:
            parts = None
        if parts is None:  # refuse outside the handler so the parser error is not chained
            return _refuse(site)
        out: list[str] = []
        for literal, field, _spec, _conv in parts:
            out.append(literal or "")
            if field is not None:
                if _strict_active():
                    raise TypeError(
                        f"SafeText slot needs a safe value at {site[0]}:{site[1]}:{site[2]}"
                    )
                out.append(_SLOT_WITHHELD)
        return cls("".join(out), _key=_KEY)

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return "SafeText(<text>)"  # a repr must not print the text into a log by accident

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SafeText):
            return NotImplemented
        return other._text == self._text

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SafeText is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SafeText is immutable")

    def __hash__(self) -> int:
        return hash(self._text)

    def __reduce__(self) -> tuple[Any, tuple[str]]:
        # A pool worker round trip; provenance is not re-checked (a crafted pickle is out of scope).
        return _rebuild, (self._text,)


def _rebuild(text: str) -> SafeText:
    return SafeText(text, _key=_KEY)
