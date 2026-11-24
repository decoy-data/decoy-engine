"""Sentry: engine code copies exception text into other values; the count only goes down.

A copy is exception text moved into a raise message, return value, log call or other sink
(rules in `_copies.py`). The pin is the registered baseline `engine-exception-text-copies`:
one entry per stable site key (bucket, file, function, rule, sink) with its multiplicity as
`max`. The merge-base ratchet (`scripts/dev/sentry_registry.toml`, `tests/sentry/_ratchet.py`)
refuses a raised `max` and a new key, so a swap of one site for another fails too. This test
fails on any difference between the live census and the file, so a removed copy also needs the
baseline lowered in the same change. Never raise an entry to pass: render the cause by type or
reuse an existing reason code instead (docs/plans/2026-11-24-f31-audit.md, slice AE5).

Two buckets are pinned apart. `audit` is the F31 audit census (100). `extra` holds shapes the
audit did not count (an alias of an exception binding, a literal `getattr`).

Messages name site keys only (file, function, rule), never the copied text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.sentry import _baseline_sources, _ratchet
from tests.sentry.safe_output._copies import Copy, census, scan_source, scan_tree

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
SENTRY_ID = "engine-exception-text-copies"
BASELINE = _baseline_sources.baseline_path(SENTRY_ID)
# The F31 audit figure. The audit bucket must still match it until AE5 lowers it, in the same
# change that lowers the baseline entries.
AUDIT_PARITY = 100


def _pinned() -> dict[str, int]:
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {k: int(v["max"]) for k, v in doc["entries"].items()}


def verdict(live: dict[str, int], pinned: dict[str, int]) -> list[str]:
    """Value-free differences between the live census and the pinned one."""
    out = [
        f"new or grown site {k} (live {n}, pinned {pinned.get(k, 0)})"
        for k, n in live.items()
        if n > pinned.get(k, 0)
    ]
    out += [
        f"shrunk or removed site {k} (live {live.get(k, 0)}, pinned {n}): lower the baseline"
        for k, n in pinned.items()
        if live.get(k, 0) < n
    ]
    return out


def _total(counts: dict[str, int], bucket: str) -> int:
    return sum(n for k, n in counts.items() if k.startswith(f"{bucket}::"))


def test_engine_copies_match_baseline() -> None:
    assert verdict(census(scan_tree(SRC)), _pinned()) == []


def test_audit_bucket_matches_the_historical_census() -> None:
    live = census(scan_tree(SRC))
    assert _total(live, "audit") == AUDIT_PARITY
    assert _total(_pinned(), "audit") == AUDIT_PARITY


def test_extra_bucket_is_pinned_apart() -> None:
    live = census(scan_tree(SRC))
    assert _total(live, "extra") == _total(_pinned(), "extra")
    assert _total(live, "extra") > 0  # the SFTP `last_exc` alias is one of them


# ---- the pin cannot move up or sideways -------------------------------------------------------


def test_verdict_fails_on_growth_swap_and_unlowered_shrink() -> None:
    a, b = "audit::a.py::f::str(exc)::raise", "audit::b.py::g::str(exc)::raise"
    assert verdict({a: 2}, {a: 1}) != []
    assert verdict({a: 1, b: 1}, {a: 1}) != []
    assert verdict({a: 1}, {a: 1, b: 1}) != []  # shrink without lowering
    assert verdict({b: 1}, {a: 1}) != []  # equal count, swapped site
    assert verdict({a: 1}, {a: 1}) == []


def test_merge_base_ratchet_catches_a_raised_pin_and_a_site_swap() -> None:
    a, b = "audit::a.py::f::str(exc)::raise", "audit::b.py::g::str(exc)::raise"
    assert _ratchet.max_raised({"max": 101}, {"max": 100})
    assert _ratchet.max_raised({}, {"max": 100})  # dropping the max is also a raise
    assert not _ratchet.max_raised({"max": 99}, {"max": 100})
    grown, _ = _ratchet.growth(frozenset({b}), frozenset({a}), per_site=False)
    assert grown == {b}  # equal count, different site: new key, needs an approval
    assert _ratchet.growth(frozenset({a}), frozenset({a}), per_site=False)[0] == frozenset()


def test_the_pin_is_registered_with_the_merge_base_ratchet() -> None:
    reg = (ROOT / _ratchet.REGISTRY).read_text(encoding="utf-8")
    rows, findings = _ratchet.parse_registry(reg)
    assert findings == []
    assert rows[SENTRY_ID] == str(BASELINE.relative_to(ROOT))


# ---- red seeds: every rule form fires ---------------------------------------------------------

_EXC = "try:\n    pass\nexcept ValueError as exc:\n    {body}\n"
SEEDS = {
    "str(exc)": _EXC.format(body="raise RuntimeError(str(exc))"),
    "repr(exc)": _EXC.format(body="x = repr(exc)"),
    "format(exc)": _EXC.format(body="x = format(exc)"),
    "f{exc}": _EXC.format(body='raise RuntimeError(f"x {exc}")'),
    "%exc": _EXC.format(body='x = "x %s" % exc'),
    "traceback": "import traceback\ntry:\n    pass\nexcept ValueError:\n    x = traceback.format_exc()\n",
}


@pytest.mark.parametrize("form", sorted(SEEDS))
def test_seed_fires(form: str) -> None:
    copies = scan_source(SEEDS[form])
    assert form in {c.form for c in copies}
    assert {c.bucket for c in copies} == {"audit"}


def test_parameter_bindings_fire() -> None:
    by_name = scan_source("def f(err):\n    return str(err)\n")
    annotated = scan_source("def f(boom: ValueError):\n    return f'{boom}'\n")
    assert {c.binding for c in by_name + annotated} == {"param"}
    assert len(by_name) == len(annotated) == 1


def test_seed_sinks() -> None:
    src = (
        "import logging\nlog = logging.getLogger('x')\n"
        "def f(exc):\n    log.error('%s', str(exc))\n    print(str(exc))\n"
        "    d = {'k': str(exc)}\n    raise ValueError(str(exc))\n"
    )
    assert [c.sink for c in scan_source(src)] == ["log", "terminal", "dict", "raise"]


def test_clean_code_is_not_a_copy() -> None:
    clean = (
        "try:\n    pass\nexcept ValueError as exc:\n"
        "    raise RuntimeError(type(exc).__name__) from exc\n"
        "def g(value):\n    return str(value)\n"
        "def h(exc):\n    return exc.code\n"
    )
    assert scan_source(clean) == []


# ---- the extra bucket -------------------------------------------------------------------------

ALIAS = (
    "def f(items):\n    last = None\n    for i in items:\n        try:\n            return i()\n"
    "        except ValueError as exc:\n            last = exc\n"
    '    raise RuntimeError(f"failed: {last}")\n'
)


def test_alias_of_an_exception_binding_is_an_extra_copy() -> None:
    (copy,) = scan_source(ALIAS)
    assert (copy.bucket, copy.binding, copy.form, copy.sink) == (
        "extra",
        "alias",
        "f{exc}",
        "raise",
    )
    assert copy.key == "extra::<memory>::f::f{exc}::raise"


def test_alias_of_a_plain_name_is_not_a_copy() -> None:
    assert scan_source("def f(items):\n    last = items\n    return str(last)\n") == []


def test_literal_getattr_is_an_extra_copy() -> None:
    src = _EXC.format(body='x = getattr(exc, "message", None)')
    (copy,) = scan_source(src)
    assert (copy.bucket, copy.form) == ("extra", "getattr(exc.message)")
    assert scan_source(_EXC.format(body='x = getattr(exc, "code", None)')) == []
    assert scan_source(_EXC.format(body="x = getattr(exc, name, None)")) == []


def test_deferred_log_argument_is_owned_by_the_log_sentry() -> None:
    # `_log.warning("... %s", exc)` (profiling/model_pack/loader.py) is test_log_interpolation.py's
    # shape; counting it here too would double count it.
    assert scan_source(_EXC.format(body='log.warning("x %s", exc)')) == []


# ---- every rule entry has its own, independently written case ---------------------------------
# These lists are typed out on purpose and not read from `_copies`: deleting an entry there must
# turn a case red, and a list derived from the set would drop its own case.

ATTRS = [
    "args",
    "message",
    "msg",
    "detail",
    "details",
    "raw_message",
    "stderr",
    "stdout",
    "problem_mark",
    "note",
    "text",
    "reason_text",
    "description",
    "strerror",
    "filename",
    "filename2",
    "doc",
    "pos",
    "context_mark",
]
TRACEBACKS = [
    "format_exc",
    "format_exception",
    "print_exc",
    "format_exception_only",
    "print_exception",
]
TERMINALS = [
    "emit_error",
    "_emit_error",
    "emit_json",
    "echo",
    "secho",
    "print",
    "write",
    "fail",
    "add_fail",
    "print_error",
    "print_warning",
]
LOGS = ["debug", "info", "warning", "warn", "error", "exception", "critical", "log"]


@pytest.mark.parametrize("attr", ATTRS)
def test_text_attribute_entry(attr: str) -> None:
    (copy,) = scan_source(_EXC.format(body=f"x = exc.{attr}"))
    assert copy.form == f"exc.{attr}"
    (via_getattr,) = scan_source(_EXC.format(body=f'x = getattr(exc, "{attr}", None)'))
    assert via_getattr.form == f"getattr(exc.{attr})"


@pytest.mark.parametrize("name", TRACEBACKS)
def test_traceback_entry(name: str) -> None:
    (copy,) = scan_source(f"import traceback\nx = traceback.{name}()\n")
    assert copy.form == "traceback"


@pytest.mark.parametrize("name", TERMINALS)
def test_terminal_entry(name: str) -> None:
    (copy,) = scan_source(_EXC.format(body=f"{name}(str(exc))"))
    assert copy.sink == "terminal"


@pytest.mark.parametrize("name", LOGS)
def test_log_entry(name: str) -> None:
    (copy,) = scan_source(_EXC.format(body=f"log.{name}(str(exc))"))
    assert copy.sink == "log"


def test_typed_lists_match_the_rule_sets() -> None:
    from tests.sentry.safe_output import _copies

    assert set(ATTRS) == _copies.TEXT_ATTRS
    assert set(TRACEBACKS) == _copies.TRACEBACK
    assert set(TERMINALS) == _copies.TERMINAL
    assert set(LOGS) == _copies.LOG


def test_copy_is_a_named_tuple_with_a_value_free_key() -> None:
    copy = Copy("a.py", 3, "str(exc)", "except", "raise", "f")
    assert copy.key == "audit::a.py::f::str(exc)::raise"
