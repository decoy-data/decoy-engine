"""Text that came from a string written in source (F31 AE1).

``SafeText.const`` and ``SafeText.literal_template`` take a ``LiteralString``. Python cannot prove
at run time that an argument was written as a literal, so the proof is static: the AST sentry
``tests/sentry/safe_output/test_safe_text_literals.py`` fails the build for any call under ``src/``
whose first argument is not a string constant. It reads the same on every interpreter. At run time
the leaf refuses what it can see: a value that is not an exact ``str``, a malformed template and a
direct ``SafeText(...)`` call. A refusal never keeps the argument: under the strict switch (tests
only) it raises ``TypeError`` naming the call site; otherwise it returns ``WITHHELD`` and logs one
value-free warning per call site. This leaf imports nothing from ``decoy_engine`` so any layer can
use it.

The strict fixture in ``tests/conftest.py`` is function-scoped, so session- and module-scoped
fixtures and subprocesses run non-strict (they withhold and log instead of raising).
"""

from __future__ import annotations

import inspect
import logging
import os
import string
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from typing_extensions import LiteralString

__all__ = ["WITHHELD", "SafeText"]

_LOG = logging.getLogger(__name__)
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


def _caller_site() -> _Site:
    """Module, function and line of the first frame outside this module and mutmut.

    Frames are skipped by module name only, never by function name. Any error gives an unknown
    site: the location is a log aid, not a proof.
    """
    frame = None
    try:
        frame = inspect.currentframe()
        while frame is not None:
            module = str(frame.f_globals.get("__name__", ""))
            if module != __name__ and not module.startswith(_MUTMUT_PREFIX):
                return module, frame.f_code.co_name, frame.f_lineno
            frame = frame.f_back
    except Exception:  # a log aid must not raise
        pass
    finally:
        del frame
    return "unknown", "unknown", 0


def _is_text(text: object) -> bool:
    # Exact ``str`` only: a subclass's __len__ or a dead weakref proxy must not run or raise here.
    return type(text) is str


def _refuse(site: _Site) -> _Withheld:
    where = f"{site[0]}:{site[1]}:{site[2]}"
    if _strict_active():
        raise TypeError(f"SafeText needs a string literal at {where}")
    if site not in _warned:
        _warned.add(site)
        _LOG.warning("SafeText withheld a refused value at %s", where)
    return WITHHELD


class SafeText:
    """Text proven to be a source literal. Build it with ``const`` or ``literal_template``."""

    __slots__ = ("_text",)
    _text: str

    # Any, not ``SafeText | _Withheld``: a union would force every caller to narrow a direct
    # ``SafeText(...)`` call, which is refused anyway. Public builders return the union.
    def __new__(cls, text: str = "", *, _key: object = None) -> Any:
        if _key is not _KEY:  # a direct SafeText(...) has no provenance
            return _refuse(_caller_site())
        self = object.__new__(cls)
        object.__setattr__(self, "_text", text)
        return self

    @classmethod
    def const(cls, text: LiteralString) -> SafeText | _Withheld:
        site = _caller_site()
        if not _is_text(text):
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
        site = _caller_site()
        if not _is_text(fmt):
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
