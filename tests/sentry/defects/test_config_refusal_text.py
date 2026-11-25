"""Sentry: config loader refusals take their text and `path` only from `config_refusal`.

The scan is `_config_refusal_scan.py` (rules S1 to S4, S6 and the raise-bare copy rule R). The
zero set, the nine AE5 loader modules, has no findings. Everywhere else a construction that
breaks S1 is pinned in `baselines/config-refusal-text.json`, one entry per
`<file>::<function>::<digest>` with its occurrence count as `max`; AE5b shrinks it to zero.
The pin must equal the live count: a removed occurrence lowers it in the same change, and a new
one fails. Never raise an entry: build the refusal with `config_refusal`.

Messages name rules and site keys, never the offending text.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

import pytest

from tests.sentry import _baseline_sources, _ratchet
from tests.sentry.defects import _config_refusal_scan as scan

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
SENTRY_ID = "config-refusal-text"
BASELINE = _baseline_sources.baseline_path(SENTRY_ID)

# ---- the real tree ----------------------------------------------------------------------------


def test_the_zero_set_has_no_findings() -> None:
    zero = [f for f in scan.scan_tree(SRC) if f.file in scan.ZERO_SET]
    assert sorted((f.rule, f.key) for f in zero) == []


def test_every_zero_set_module_exists() -> None:
    assert [m for m in sorted(scan.ZERO_SET) if not (SRC / m).is_file()] == []


def test_findings_outside_the_zero_set_are_s1_only_and_pinned() -> None:
    outside = [f for f in scan.scan_tree(SRC) if f.file not in scan.ZERO_SET]
    assert {f.rule for f in outside} <= {"S1"}


def test_no_baseline_entry_belongs_to_a_zero_set_module() -> None:
    import json

    entries = json.loads(BASELINE.read_text(encoding="utf-8"))["entries"]
    assert [k for k in entries if k.split("::")[0] in scan.ZERO_SET] == []


def test_the_sentry_is_not_a_rekey_per_site_sentry() -> None:
    assert SENTRY_ID not in _ratchet.REKEY_PER_SITE


def _merge_base() -> str:
    for ref in ("origin/main", "main"):
        res = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(ROOT), "merge-base", "HEAD", ref],  # noqa: S607
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    pytest.fail("no merge base is reachable (a shallow clone?); fetch origin/main")


def _base_counts(base: str) -> Counter[str]:
    names = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", base, "src/decoy_engine"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    prefix = "src/decoy_engine/"
    texts = {}
    for name in names:
        if name.endswith(".py"):
            shown = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "-C", str(ROOT), "show", f"{base}:{name}"],  # noqa: S607
                capture_output=True,
                text=True,
                check=True,
            )
            texts[name[len(prefix) :]] = shown.stdout
    return Counter(scan.baselined_counts(scan.scan_texts(texts)))


def test_config_refusal_baseline_is_from_the_merge_base() -> None:
    import json

    entries = json.loads(BASELINE.read_text(encoding="utf-8"))["entries"]
    base = _base_counts(_merge_base())
    stray = sorted(k for k in entries if k not in base)
    assert stray == [], "baseline entries that the merge base does not hold"
    over = sorted(k for k, e in entries.items() if e["max"] > base[k])
    assert over == [], "baseline counts above the merge-base count"


def test_the_baseline_equals_the_live_counts() -> None:
    import json

    entries = json.loads(BASELINE.read_text(encoding="utf-8"))["entries"]
    live = _baseline_sources.config_refusal_census()
    assert {k: e["max"] for k, e in entries.items()} == live
    assert all(n > 0 for n in live.values())


def test_the_pin_is_registered_with_the_merge_base_ratchet() -> None:
    text = (ROOT / _ratchet.REGISTRY).read_text(encoding="utf-8")
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    rows, findings = _ratchet.parse_registry(tomllib.loads(text))
    assert findings == []
    assert rows[SENTRY_ID] == str(BASELINE.relative_to(ROOT))


# ---- the count rule (Codex R2 design 2), on a seeded tree --------------------------------------

_DUP = (
    "from decoy_engine.plan._errors import PlanCompileError\n"
    "def f(v):\n    if v:\n        raise PlanCompileError('c', 'p', f'{v}')\n"
    "    if not v:\n        raise PlanCompileError('c', 'p', f'{v}')\n"
)


def _counts(text: str) -> dict[str, int]:
    return scan.baselined_counts(scan.scan_source("x/mod.py", text, zero=False))


def _check(pinned: dict[str, int], live: dict[str, int]) -> bool:
    """The rule the registered source and the equality test enforce together: the same keys and
    the same counts, and no count above its pin."""
    return pinned == live and all(n > 0 for n in live.values())


def test_a_duplicated_construction_shares_one_key_with_a_count_of_two() -> None:
    live = _counts(_DUP)
    assert list(live.values()) == [2]
    (key,) = live
    assert _check({key: 2}, live)
    assert not _check({key: 1}, live)  # head count above the pin


def test_deleting_one_occurrence_keeps_the_pin_honest_only_when_it_is_lowered() -> None:
    one = _DUP.split("    if not v:")[0]
    live = _counts(one)
    (key,) = live
    assert not _check({key: 2}, live)  # a stale max of 2 fails
    assert _check({key: 1}, live)


def test_deleting_the_last_occurrence_needs_the_key_removed() -> None:
    live = _counts("def f(v):\n    return v\n")
    assert live == {}
    assert not _check({"x/mod.py::f::abc": 1}, live)
    assert not _check({"x/mod.py::f::abc": 0}, live)
    assert _check({}, live)


def test_the_merge_base_ratchet_catches_a_raised_count() -> None:
    assert _ratchet.max_raised({"max": 3}, {"max": 2})
    assert not _ratchet.max_raised({"max": 1}, {"max": 2})


# ---- seeded snippets: every rule fires, and clean forms pass ----------------------------------

ZERO = "detection/name_hints/loader.py"
IMPORTS = (
    "from decoy_engine._config_text import (Expected, Kind, Member, Name, Problem, Refusal,"
    " config_position, config_refusal, read_config)\n"
    "from decoy_engine._error_base import raise_bare\n"
    "from decoy_engine.errors import ConfigError\n"
    "from decoy_engine.plan import PlanCompileError, refusal_error\n"
    "from decoy_engine.generation.statistical._spec import StatisticalSpecError\n"
    "from decoy_engine.quality.dp_provenance import ProvenanceError\n"
)
OK_REFUSAL = "    r = config_refusal(config_position('a'), Problem.MISSING)\n"


def _rules(body: str, *, zero: bool = True, rel: str = ZERO) -> set[str]:
    found = scan.scan_source(rel, IMPORTS + body, zero=zero)
    return {f.rule for f in found}


FIRES: dict[str, tuple[str, str]] = {
    "fstring message": ("S1", "def f(v):\n    raise_bare(ConfigError(f'{v}'))\n"),
    "repr message": ("S1", "def f(v):\n    raise_bare(ConfigError(repr(v)))\n"),
    "str(exc) message": (
        "S1",
        "def f():\n    try:\n        pass\n    except ValueError as exc:\n"
        "        err = ConfigError(str(exc))\n",
    ),
    "raise inside except": (
        "S3",
        "def f():\n    try:\n        pass\n    except ValueError:\n"
        "        raise ConfigError('x')\n",
    ),
    "from exc": (
        "S3",
        "def f():\n    try:\n        pass\n    except ValueError as exc:\n"
        "        raise ConfigError('x') from exc\n",
    ),
    "literal path": (
        "S1",
        "def f():\n" + OK_REFUSAL + "    raise_bare(PlanCompileError('c', 'a.b', r.detail))\n",
    ),
    "non-literal path": (
        "S1",
        "def f(p):\n" + OK_REFUSAL + "    raise_bare(PlanCompileError('c', p, r.detail))\n",
    ),
    "non-constant choices": (
        "S2",
        "def f(xs):\n    config_refusal(config_position('a'), Problem.MISSING, choices=xs)\n",
    ),
    "runtime hint": (
        "S2",
        "def f(text):\n    config_refusal(config_position('a'), Problem.MISSING, hint=text)\n",
    ),
    "risky segment": (
        "S2",
        "def f(v):\n    config_position(f'{v}')\n    config_refusal("
        "config_position(f'{v}'), Problem.MISSING)\n",
    ),
    "Name(str(v))": (
        "S2",
        "def f(v):\n    config_refusal(config_position(Name(str(v))), Problem.MISSING)\n",
    ),
    "Name(fstring)": (
        "S2",
        "def f(v):\n    config_refusal(config_position(Name(f'{v}')), Problem.MISSING)\n",
    ),
    "Member(repr(v))": (
        "S2",
        "def f(v):\n    config_refusal(config_position(Member(repr(v))), Problem.MISSING)\n",
    ),
    "converted then wrapped": (
        "S2",
        "def f(condition_on):\n    condition_on = str(condition_on)\n"
        "    config_refusal(config_position(Name(condition_on)), Problem.MISSING)\n",
    ),
    "copy of a converted value": (
        "S2",
        "def f(x):\n    y = str(x)\n    z = y\n"
        "    config_refusal(config_position(Member(z)), Problem.MISSING)\n",
    ),
    "helper returns the error": ("S1", "def _bad(v):\n    return ConfigError(f'{v}')\n"),
    "assign then raise": (
        "S1",
        "def f(v):\n    err = ProvenanceError(code='c', message=f'{v}')\n    raise err\n",
    ),
    "third positional": ("S1", "def f(v):\n    raise_bare(PlanCompileError('c', None, f'{v}'))\n"),
    "second mapping, inline": (
        "S1",
        "def f():\n" + OK_REFUSAL + "    raise_bare(PlanCompileError('c', r.key, r.detail))\n",
    ),
    "second mapping, keywords": (
        "S1",
        "def f():\n"
        + OK_REFUSAL
        + "    raise_bare(PlanCompileError(code='c', path=r.key, message=r.detail))\n",
    ),
    "second mapping, helper-returned refusal": (
        "S1",
        "def f(table):\n    r = make_refusal(table)\n"
        "    raise_bare(PlanCompileError(code='c', path=r.key, message=r.detail))\n",
    ),
    "second mapping, aliased class": (
        "S1",
        "from decoy_engine.plan import PlanCompileError as PCE\n"
        "def f():\n" + OK_REFUSAL + "    raise_bare(PCE('c', r.key, r.detail))\n",
    ),
    "message in the path slot": (
        "S1",
        "def f():\n" + OK_REFUSAL + "    raise_bare(PlanCompileError('c', r.key, r.text))\n",
    ),
    "subclass fstring": (
        "S1",
        "class Mine(StatisticalSpecError):\n    pass\n"
        "def f(v):\n    raise_bare(Mine(code='c', message=f'{v}'))\n",
    ),
    "subclass own init, no row": (
        "S1",
        "class Odd(ConfigError):\n    def __init__(self, a, b):\n        super().__init__(a)\n",
    ),
    "builtin fstring (zero set)": ("S1", "def f(v):\n    raise_bare(ValueError(f'{v}'))\n"),
    "Refusal outside the package": (
        "S1",
        "def f():\n    r = Refusal('x', 'x', 'x')\n    raise_bare(ConfigError(r.text))\n",
    ),
    "context-clearing copy": (
        "R",
        "def again(err):\n    try:\n        raise err\n    except BaseException as fresh:\n"
        "        fresh.__context__ = None\n        raise\n",
    ),
    "materializer after read_config": (
        "S6",
        "def f(table):\n    value = read_config(lambda: table, config_position('a'), g)\n"
        "    return table.column('x')[0].as_py()\n",
    ),
    "second call outside the protection": (
        "S6",
        "def _check(tbl):\n    return tbl.column('x').to_pylist()\n"
        "def f(tbl):\n    read_config(lambda: _check(tbl), config_position('a'), g)\n"
        "    return _check(tbl)\n",
    ),
}

MATERIALIZER_CALLS = {
    "as_py": "t.column('x')[0].as_py()",
    "to_pylist": "t.column('x').to_pylist()",
    "to_pydict": "t.to_pydict()",
    "read_table": "adapter.read_table(h)",
    "json.loads": "json.loads(b)",
    "json.load": "json.load(b)",
    "yaml.safe_load": "yaml.safe_load(b)",
    "serial load": "serial.yaml_safe_load(b)",
    "toml load": "toml_reader.load(b)",
    "from_parquet_metadata": "CodeSetProvenance.from_parquet_metadata(t)",
}


@pytest.mark.parametrize("name", sorted(FIRES))
def test_seed_fires(name: str) -> None:
    rule, body = FIRES[name]
    outside = name == "Refusal outside the package"
    rules = _rules(body, rel="x/other.py" if outside else ZERO)
    assert rule in rules, rules


@pytest.mark.parametrize("name", sorted(MATERIALIZER_CALLS))
def test_every_materializer_is_flagged_outside_a_read_callable(name: str) -> None:
    body = f"def f(t, b, h):\n    return {MATERIALIZER_CALLS[name]}\n"
    assert "S6" in _rules(body)
    inside = (
        f"def f(t, b, h):\n    return read_config(lambda: {MATERIALIZER_CALLS[name]},"
        " config_position('a'), g)\n"
    )
    assert "S6" not in _rules(inside)


def test_a_runtime_hint_is_s2_outside_the_zero_set_for_both_s1_valid_forms() -> None:
    direct = (
        "def f(runtime_text):\n"
        "    r = config_refusal(config_position('a'), Problem.MISSING, hint=runtime_text)\n"
        "    return ConfigError(r.text)\n"
    )
    factory = (
        "def make(r: Refusal):\n    return ConfigError(r.text)\n"
        "def f(runtime_text):\n"
        "    return make(config_refusal(config_position('a'), Problem.MISSING, hint=runtime_text))\n"
    )
    fixed = direct.replace("hint=runtime_text", "hint='fixed'")
    for body in (direct, factory):
        found = scan.scan_source("x/other.py", IMPORTS + body, zero=False)
        assert {f.rule for f in found} == {"S2"}, body
    assert scan.scan_source("x/other.py", IMPORTS + fixed, zero=False) == []


def test_a_hint_name_must_be_bound_to_a_literal() -> None:
    template = (
        "HINT = {value}\n"
        "def f(runtime_text):\n"
        "    r = config_refusal(config_position('a'), Problem.MISSING, hint=HINT)\n"
        "    return ConfigError(r.text)\n"
    )
    literal = template.format(value="'fixed text'")
    assert scan.scan_source("x/other.py", IMPORTS + literal, zero=False) == []
    for value in ("runtime_text", "f'{runtime_text}'", "str(runtime_text)"):
        found = scan.scan_source("x/other.py", IMPORTS + template.format(value=value), zero=False)
        assert {f.rule for f in found} == {"S2"}, value
    # A name this module does not bind is another module's constant.
    imported = template.replace("HINT = {value}\n", "")
    assert scan.scan_source("x/other.py", IMPORTS + imported, zero=False) == []


def test_a_builtin_fstring_is_flagged_only_in_the_zero_set() -> None:
    body = "def f(v):\n    raise ValueError(f'{v}')\n"
    assert "S1" in _rules(body, zero=True)
    assert "S1" not in _rules(body, zero=False, rel="x/other.py")


def test_s3_and_s4_do_not_apply_outside_the_zero_set() -> None:
    body = (
        "def f():\n    try:\n        pass\n    except ValueError as exc:\n"
        "        raise ConfigError('x') from exc\n"
    )
    assert _rules(body, zero=False, rel="x/other.py") == set()


CLEAN: dict[str, str] = {
    "bound builder then raise_bare": (
        "def f():\n" + OK_REFUSAL + "    err = ConfigError(r.text)\n    raise_bare(err)\n"
    ),
    "plan error from detail and key": (
        "def f():\n" + OK_REFUSAL + "    raise_bare(refusal_error('c', r))\n"
    ),
    "factory passed to read_config": (
        "def _refuse(r: Refusal) -> PlanCompileError:\n    return refusal_error('c', r)\n"
        "def f(read):\n    return read_config(read, config_position('a'), _refuse)\n"
    ),
    "keeps_class check": (
        "def f(fileaccess):\n    try:\n        pass\n    except OSError as e:\n"
        "        if fileaccess.keeps_class(e):\n            raise\n"
    ),
    "as_py inside a lambda": (
        "def f(t):\n    return read_config(lambda: t[0].as_py(), config_position('a'), g)\n"
    ),
    "as_py inside a named read callable": (
        "def f(t):\n    def _load():\n        return t[0].as_py()\n"
        "    return read_config(_load, config_position('a'), g)\n"
    ),
    "helper called only inside the protection": (
        "def _check(tbl):\n    return tbl.column('x').to_pylist()\n"
        "def f(tbl):\n    return read_config(lambda: _check(tbl), config_position('a'), g)\n"
    ),
    "plain raw binding": (
        "def f(v):\n    config_refusal(config_position(Name(v)), Problem.MISSING)\n"
    ),
    "index segment": (
        "def f(xs):\n    for i, x in enumerate(xs):\n"
        "        config_refusal(config_position('a', i), Problem.MISSING)\n"
    ),
    "builtin with a constant": "def f():\n    raise ValueError('fixed text')\n",
    "builtin with the fixed memory text": (
        "def f(fileaccess):\n    raise_bare(MemoryError(fileaccess.MEMORY_TEXT))\n"
    ),
    "refusal built in an except outside the zero set": "",
}


@pytest.mark.parametrize("name", sorted(k for k in CLEAN if CLEAN[k]))
def test_clean_form_passes(name: str) -> None:
    assert scan.scan_source(ZERO, IMPORTS + CLEAN[name], zero=True) == []


def test_the_rebuild_exemption_is_one_function_in_its_module() -> None:
    body = (
        "def _rebuild_load_error(message, cause):\n"
        "    return ModelPackLoadError(message, cause=cause)\n"
    )
    imports = "from decoy_engine.profiling.model_pack.loader import ModelPackLoadError\n"
    real = scan.scan_source("profiling/model_pack/loader.py", imports + body, zero=True)
    assert [f for f in real if f.rule == "S1"] == []
    renamed = body.replace("_rebuild_load_error", "_other")
    assert any(
        f.rule == "S1"
        for f in scan.scan_source("profiling/model_pack/loader.py", imports + renamed, zero=True)
    )


def test_a_refusal_built_in_an_except_outside_the_zero_set_is_not_s3_or_s4() -> None:
    body = (
        "def f():\n    r = config_refusal(config_position('a'), Problem.MISSING)\n"
        "    try:\n        pass\n    except ValueError as exc:\n"
        "        raise ConfigError(r.text) from exc\n"
    )
    assert _rules(body, zero=False, rel="x/other.py") == set()


# ---- S4: typed uses of a caught error ------------------------------------------------------------

VERIFY = "transforms/_codeset_loader.py"
VERIFY_OK = (
    "def verify_corpus(path):\n    try:\n        record = path\n"
    "    except PlanCompileError as exc:\n"
    "        return report(problems=(f'{exc.code}: {exc.message}',))\n"
)


def test_s4_allows_the_typed_report_path_only() -> None:
    ok = scan.scan_source(VERIFY, IMPORTS + VERIFY_OK, zero=True)
    assert [f for f in ok if f.rule == "S4"] == []
    broad = VERIFY_OK.replace("except PlanCompileError", "except Exception")
    assert any(f.rule == "S4" for f in scan.scan_source(VERIFY, IMPORTS + broad, zero=True))
    for stringified in ("str(exc)", "exc.args", "repr(exc)"):
        body = VERIFY_OK.replace("f'{exc.code}: {exc.message}'", stringified)
        assert any(f.rule == "S4" for f in scan.scan_source(VERIFY, IMPORTS + body, zero=True))
    moved = VERIFY_OK.replace("def verify_corpus", "def other")
    assert any(f.rule == "S4" for f in scan.scan_source(VERIFY, IMPORTS + moved, zero=True))


GEN = "plan/_generation.py"


def test_s4_allows_the_failure_map_store_and_the_code_forward() -> None:
    store = (
        "def read_and_pin_snapshots(failures, path):\n    try:\n        pass\n"
        "    except StatisticalSpecError as exc:\n        failures[path] = exc\n"
    )
    assert [f for f in scan.scan_source(GEN, IMPORTS + store, zero=True) if f.rule == "S4"] == []
    broad = store.replace("except StatisticalSpecError", "except Exception")
    assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + broad, zero=True))
    msg = store.replace("failures[path] = exc", "failures[path] = exc.message")
    assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + msg, zero=True))
    # The stored expression is the caught object itself: a copy of its text is a finding.
    for copied in ("str(exc)", "repr(exc)", "f'{exc}'", "(exc,)"):
        body = store.replace("failures[path] = exc", f"failures[path] = {copied}")
        assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + body, zero=True)), copied
    fwd = (
        "def check_fitted_references():\n    try:\n        pass\n"
        "    except StatisticalSpecError as exc:\n        spec_code = exc.code\n"
    )
    assert [f for f in scan.scan_source(GEN, IMPORTS + fwd, zero=True) if f.rule == "S4"] == []
    text = fwd.replace("exc.code", "exc.message")
    assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + text, zero=True))
    wrapped = fwd.replace("exc.code", "str(exc.code)")
    assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + wrapped, zero=True))


def test_s4_allows_passthrough_and_an_identity_test_but_not_an_equality_test() -> None:
    body = (
        "def read_pinned_artifact(f):\n    try:\n        pass\n"
        "    except Exception as exc:\n        out = passthrough(exc)\n"
        "        if out is exc:\n            raise\n"
    )
    assert [f for f in scan.scan_source(GEN, IMPORTS + body, zero=True) if f.rule == "S4"] == []
    equal = body.replace("out is exc", "out == exc")
    assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + equal, zero=True))
    stored = body.replace("out = passthrough(exc)", "out = exc")
    assert any(f.rule == "S4" for f in scan.scan_source(GEN, IMPORTS + stored, zero=True))


def test_s6_protected_checker_passes_and_an_extra_unprotected_call_fails() -> None:
    protected = (
        "def _check(tbl):\n    return tbl.column('c').to_pylist()\n"
        "def f(tbl):\n    def _load():\n        return _check(tbl)\n"
        "    return read_config(_load, config_position('a'), g)\n"
    )
    assert "S6" not in _rules(protected)
    extra = protected + "def other(tbl):\n    return _check(tbl)\n"
    assert "S6" in _rules(extra)


FACTORY = (
    "def refusal_error(code, refusal: Refusal):\n"
    "    return PlanCompileError(code=code, path=refusal.key, message=refusal.detail)\n"
)


def test_the_one_factory_is_the_only_place_the_mapping_may_live() -> None:
    real = scan.scan_source("plan/_errors.py", IMPORTS + FACTORY, zero=False)
    assert [f for f in real if f.rule == "S1"] == []
    moved = FACTORY.replace("refusal_error", "other_error")
    assert any(f.rule == "S1" for f in scan.scan_source("plan/_errors.py", IMPORTS + moved))
    elsewhere = scan.scan_source("plan/_checks.py", IMPORTS + FACTORY, zero=False)
    assert any(f.rule == "S1" for f in elsewhere)


def test_the_real_tree_maps_a_refusal_to_a_plan_error_once() -> None:
    import ast

    sites = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PlanCompileError":
                fields = [*node.args, *(k.value for k in node.keywords)]
                if any(isinstance(f, ast.Attribute) and f.attr == "detail" for f in fields):
                    sites.append(path.relative_to(SRC).as_posix())
    assert sites == ["plan/_errors.py"]
