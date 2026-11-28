"""K6 sentry: one fpe checksum rule (FPE-CHECKSUM-NATIVE).

Whether a checksum scheme runs on the compiled kernel is decided in one function,
`fpe_checksum_rejection`. This guard pins, by `(path, function)`:

- who reads the registry field `checksum_schemes` (only the decision);
- who reads the configured scheme under `execution/` and how many times (carriers forward it,
  nothing else branches on it);
- who calls the decision and the mapping adapter, and with which route context.

Any other edge fails, even inside an already listed function: the pinned count per function
catches a second read there. Imports and local aliases are normalized, so renaming a call or
reading through `getattr`, a subscript, a `.get`, or a bound alias is still seen.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from tests.sentry.defects._defect_scan import ModuleIndex
from tests.sentry.defects.routing._fpe_checksum_scan import (
    ADAPTER,
    ADM,
    CHUNKED,
    DECISION,
    REJ,
    ROOT,
    Edge,
    bound_scheme_names,
    callers,
    context_forwarders,
    defining_modules,
    delivery_violations,
    field_readers,
    scheme_reads,
    sources,
    text_mask_restriction_pinned,
    trees,
    under_execution,
    ungoverned_calls,
)

FIELD_READERS: dict[Edge, str] = {
    (REJ, DECISION): "the one decision",
}

# Every read of the configured scheme, with the number of reads in that function. A carrier
# forwards the scheme to its destination; none of them decides a route.
SCHEME_READS: dict[Edge, tuple[int, str]] = {
    ("execution/_strategies/_fpe.py", "FpeStrategyHandler.run"): (
        2,
        "oracle carrier: one read, then the annotated bound name feeds the luhn guard",
    ),
    ("execution/_strategies/_fpe.py", "FpeStrategyHandler.run.encrypt_one"): (
        1,
        "oracle carrier: the closure forwards the scheme it captures from `run`",
    ),
    ("execution/out_of_core/_mask_group_b.py", "fpe_array"): (
        3,
        "oracle carrier: one read, then the annotated bound name feeds the luhn guard and the call",
    ),
    ("execution/native/_crypto_ext.py", "FpeConfig.from_mapping"): (1, "config carrier"),
    ("execution/native/_crypto_ext.py", "FpeConfig._resolve"): (
        3,
        "config carrier: one read, then the bound name is used twice (the luhn guard, the return)",
    ),
    ("execution/native/_crypto_reference.py", "_ReferenceFpe._run"): (1, "oracle carrier"),
    ("execution/native/_operator_params.py", "resolve_operator_params"): (1, "params carrier"),
    ("execution/native/_fpe_route.py", "fpe_config_from_params"): (1, "params to config"),
    (REJ, ADAPTER): (2, "adapter reads the scheme once and forwards the bound name"),
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): (1, "wrapper backstop"),
    ("execution/native/_fpe_ext.py", "load_compiled_fpe_kernel"): (
        1,
        "ordinary-FF1 load probe asserts no scheme (replaced by the shared probe in S2b)",
    ),
}

DECISION_CALLERS: dict[Edge, str] = {
    (REJ, ADAPTER): "adapter forwards scheme and charset",
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): "wrapper backstop, payload",
}

# (path, function) -> route context literal passed to the adapter.
ADAPTER_CALLERS: dict[Edge, str] = {
    (ADM, CHUNKED): "payload",
    ("execution/_sequential_native_ops.py", "_fpe_config_reason"): "<forwarded>",
    ("execution/out_of_core/_fpe_native.py", "decline_reason"): "payload",
    ("execution/physical/_shadow_bindings.py", "execution_binding_for_slice_node"): "payload",
}
# The chunked admission wraps the adapter in `_fpe_checksum_decline`; its one caller must let the
# result govern the table's route.
CHUNKED_CALLERS: dict[Edge, str] = {(ADM, "real_type_decline"): "chunked decision"}

# Where the scheme and context go. Kinds: `bind` = the argument that binds to the destination's
# `checksum` parameter (by keyword or by that parameter's position in its `def`); `kw` = the
# `checksum=` keyword of any call; `arg1` = what binds to the decision's `scheme` parameter;
# `ctx` = `arg1` plus `context=<the function's own context parameter>`; `ret4` = the fourth item
# of the returned tuple. `transform` is the oracle's local `encrypt if forward else decrypt`.

# Where a refusal must lead, by `(path, function)`; the default is a returned non-None reason.
# `none` is the unified binding, where declining means "unbound" (`return None`).
GOVERN_OUTCOME: dict[Edge, str] = {
    ("execution/physical/_shadow_bindings.py", "execution_binding_for_slice_node"): "none",
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): "raise",
}
DELIVERIES: dict[Edge, tuple[str, frozenset[str]]] = {
    ("execution/_strategies/_fpe.py", "FpeStrategyHandler.run.encrypt_one"): (
        "bind",
        frozenset({"fpe_encrypt_value"}),
    ),
    ("execution/out_of_core/_mask_group_b.py", "fpe_array"): (
        "bind",
        frozenset({"fpe_encrypt_value"}),
    ),
    ("execution/native/_crypto_reference.py", "_ReferenceFpe._run"): (
        "bind",
        frozenset({"transform"}),
    ),
    ("execution/native/_crypto_ext.py", "FpeConfig.from_mapping"): ("kw", frozenset()),
    ("execution/native/_crypto_ext.py", "FpeConfig._resolve"): ("ret4", frozenset()),
    ("execution/native/_fpe_route.py", "fpe_config_from_params"): ("kw", frozenset()),
    ("execution/native/_operator_params.py", "resolve_operator_params"): ("kw", frozenset()),
    (REJ, ADAPTER): ("ctx", frozenset({DECISION})),
    ("execution/native/_fpe_ext.py", "_CompiledFpeKernel.run"): ("arg1", frozenset({DECISION})),
}

# The two sequential admission callers pin the context the shared helper receives.
CONTEXT_FORWARDERS: dict[Edge, str] = {
    ("execution/_sequential_native_ops.py", "_fpe_admit"): "payload",
    ("execution/_sequential_native_ops.py", "_fpe_key_admit"): "key",
}


def test_only_the_decision_reads_the_registry_field() -> None:
    found: Counter[Edge] = Counter()
    for rel, src in sources():
        found += field_readers(src, rel)
    assert set(found) == set(FIELD_READERS), sorted(found)
    assert found[(REJ, DECISION)] == 1, "one read, in the decision"


def test_scheme_reads_match_the_pinned_carriers() -> None:
    found: Counter[Edge] = Counter()
    for rel, src in sources():
        if under_execution(rel):
            found += scheme_reads(src, rel)
    pinned = Counter({edge: n for edge, (n, _why) in SCHEME_READS.items()})
    assert found == pinned, {
        "unexpected_or_changed": sorted((found - pinned).items()),
        "missing": sorted((pinned - found).items()),
    }


@pytest.fixture(scope="module")
def index() -> ModuleIndex:
    return ModuleIndex(ROOT)


def _call_sites(index: ModuleIndex, name: str) -> list[tuple[Edge, str]]:
    out: list[tuple[Edge, str]] = []
    for rel, tree in trees(index):
        if under_execution(rel):
            out += callers(rel, tree, name)
    return out


def test_decision_callers_are_the_adapter_and_the_wrapper(index: ModuleIndex) -> None:
    sites = _call_sites(index, DECISION)
    assert sorted(e for e, _c in sites) == sorted(DECISION_CALLERS), sites
    assert defining_modules(index, DECISION) == [REJ], "a private copy of the decision"


def test_adapter_callers_are_the_route_sites_with_their_context(index: ModuleIndex) -> None:
    sites = _call_sites(index, ADAPTER)
    # the rejections module itself defines, never calls, the adapter
    assert dict(sites) == ADAPTER_CALLERS and len(set(sites)) == len(sites), sites
    assert defining_modules(index, ADAPTER) == [REJ], "a private copy of the adapter"


def test_the_chunked_wrapper_has_one_caller(index: ModuleIndex) -> None:
    sites = _call_sites(index, CHUNKED)
    assert sorted(e for e, _c in sites) == sorted(CHUNKED_CALLERS), sites
    assert defining_modules(index, CHUNKED) == [ADM]


def test_every_decision_result_governs_its_route_or_refusal(index: ModuleIndex) -> None:
    found = {n: ungoverned_calls(index, n, GOVERN_OUTCOME) for n in (DECISION, ADAPTER, CHUNKED)}
    assert found == {DECISION: [], ADAPTER: [], CHUNKED: []}, found


def test_the_scheme_and_context_reach_each_destination(index: ModuleIndex) -> None:
    assert delivery_violations(index, DELIVERIES) == []


def test_text_mask_detector_restriction_is_pinned_until_s3() -> None:
    rel = "execution/native/_text_mask_native_fpe.py"
    assert text_mask_restriction_pinned((ROOT / rel).read_text(encoding="utf-8"))


def test_sequential_admission_callers_pin_payload_and_key_context(index: ModuleIndex) -> None:
    rel = "execution/_sequential_native_ops.py"
    assert dict(context_forwarders(rel, dict(trees(index))[rel])) == CONTEXT_FORWARDERS


# Seeded spellings: each must be seen by the scanner it targets.


@pytest.mark.parametrize(
    "rel", ["execution/_strategies/_fpe.py", "execution/out_of_core/_mask_group_b.py"]
)
def test_a_refusal_after_an_annotated_binding_changes_the_count(rel: str) -> None:
    """A refusal after the handlers' `checksum: str | None = ...` binding moves the count."""
    src = dict(sources())[rel]
    anchor = '        checksum: str | None = cfg.get("checksum") or None\n'
    assert src.count(anchor) == 1
    mutated = src.replace(
        anchor, anchor + "        if checksum == 'vin':\n            raise ValueError\n"
    )
    before, after = scheme_reads(src, rel), scheme_reads(mutated, rel)
    assert sum(after.values()) == sum(before.values()) + 1


def test_scanner_sees_every_registry_field_spelling() -> None:
    spellings = [
        "def f(spec):\n    return spec.checksum_schemes\n",
        "def f(spec):\n    return getattr(spec, 'checksum_schemes')\n",
        "def f(spec):\n    return vars(spec)['checksum_schemes']\n",
        "def f(spec):\n    return spec.__dict__.get('checksum_schemes')\n",
        "def f():\n    s = OPERATORS['fpe']\n    return s.checksum_schemes\n",
    ]
    for src in spellings:
        assert field_readers(src, "x.py"), src
    declared = (
        "class A:\n    checksum_schemes: frozenset[str] = frozenset()\nA(checksum_schemes=1)\n"
    )
    assert not field_readers(declared, "x.py")


def test_scanner_sees_every_scheme_read_spelling() -> None:
    spellings = [
        "def f(cfg):\n    return cfg.get('checksum')\n",
        "def f(cfg):\n    return cfg['checksum']\n",
        "def f(p):\n    return p.checksum\n",
        "def f(cfg):\n    return getattr(cfg, 'checksum', None)\n",
        "def f(c):\n    a, b, d, e = c._resolve()\n    return e\n",
    ]
    for src in spellings:
        assert scheme_reads(src, "x.py"), src


def _seeded(tmp_path: Path, files: dict[str, str]) -> ModuleIndex:
    """A throwaway `decoy_engine` tree, so a bypass is scanned without touching real source."""
    root = tmp_path / "decoy_engine"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return ModuleIndex(root)


_ORACLE_DEF = (
    "def fpe_encrypt_value(val, key, charset, tweak, preserve_separators=True,\n"
    "                      validate_luhn=False, checksum=None):\n    return val\n"
)
_ORACLE_EDGE: dict[Edge, tuple[str, frozenset[str]]] = {
    ("execution/o.py", "f"): ("bind", frozenset({"fpe_encrypt_value"}))
}


def _oracle(tmp_path: Path, call: str, pre: str = "") -> ModuleIndex:
    body = (
        "def f(cfg, v):\n    checksum = cfg.get('checksum') or None\n"
        f"{pre}    return fpe_encrypt_value({call})\n"
    )
    return _seeded(tmp_path, {"execution/o.py": body, "transforms/fpe.py": _ORACLE_DEF})


def test_delivery_accepts_the_configured_scheme(tmp_path: Path) -> None:
    for call in (
        "v, 1, 2, 3, 4, 5, checksum",
        "v, 1, 2, 3, 4, 5, checksum=checksum",
        "v, 1, 2, 3, checksum=checksum",
    ):
        assert delivery_violations(_oracle(tmp_path, call), _ORACLE_EDGE) == [], call


@pytest.mark.parametrize(
    "call, pre",
    [
        ("v, 1, 2, 3, 4, 5, None", ""),
        ("v, 1, 2, 3, 4, 5, checksum", "    checksum = None\n"),
        ("v, 1, 2, 3, 4, 5, 'luhn'", ""),
        ("v, 1, 2, 3, 4, checksum", ""),  # one argument short: the scheme lands in validate_luhn
        ("v, 1, 2, 3, checksum", ""),  # scheme lands in preserve_separators
        ("v, 1, 2, 3, 4, 5, 6, checksum", ""),  # past the end of the signature
        ("v, 1, 2, 3, 4, checksum, checksum=None", ""),
        ("*args", ""),
    ],
    ids=[
        "none",
        "rebound",
        "constant",
        "validate-luhn-slot",
        "separator-slot",
        "overlong",
        "kw-none",
        "starred",
    ],
)
def test_delivery_rejects_a_scheme_that_misses_the_checksum_parameter(
    tmp_path: Path, call: str, pre: str
) -> None:
    assert delivery_violations(_oracle(tmp_path, call, pre), _ORACLE_EDGE)


def test_delivery_rejects_a_dropped_context_and_a_missing_destination(tmp_path: Path) -> None:
    table = {("execution/r.py", "adapter"): ("ctx", frozenset({DECISION}))}
    decl = "def fpe_checksum_rejection(column, scheme, resolved_charset, *, context):\n    pass\n"
    ok = (
        "def adapter(column, cfg, *, context):\n"
        "    scheme = cfg.get('checksum') or None\n"
        "    return fpe_checksum_rejection(column, scheme, 'x', context=context)\n"
    )
    files = {"execution/r.py": ok, "execution/native/_operator_config_rejections.py": decl}
    assert delivery_violations(_seeded(tmp_path, files), table) == []
    bad_cases = (
        ok.replace("context=context", "context='payload'"),
        ok.replace("column, scheme, 'x'", "column, 'x', scheme"),  # scheme in the charset slot
        "def adapter():\n    pass\n",
    )
    for n, bad in enumerate(bad_cases):
        files = {"execution/r.py": bad, "execution/native/_operator_config_rejections.py": decl}
        assert delivery_violations(_seeded(tmp_path / str(n), files), table), bad


_DECISION_DEF = "def fpe_checksum_config_rejection(c, p, *, context):\n    return None\n"


def _governed_case(tmp_path: Path, body: str, outcome: str = "value") -> list[Edge]:
    files = {
        "execution/native/_operator_config_rejections.py": _DECISION_DEF,
        "execution/route.py": (
            "from decoy_engine.execution.native import fpe_checksum_config_rejection as ask\n"
            "def route(c, p):\n" + body
        ),
    }
    return ungoverned_calls(
        _seeded(tmp_path, files),
        "fpe_checksum_config_rejection",
        {("execution/route.py", "route"): outcome},
    )


_BOUND = "    r = ask(c, p, context='payload')\n"


@pytest.mark.parametrize(
    "body, outcome",
    [
        ("    return ask(c, p, context='payload')\n", "value"),
        (_BOUND + "    if r is not None:\n        return r\n    return None\n", "value"),
        (_BOUND + "    if r:\n        return ('x', r)\n    return None\n", "value"),
        (
            "    if ask(c, p, context='payload') is not None:\n        raise ValueError('x')\n",
            "raise",
        ),
        (_BOUND + "    if c or r is not None:\n        return None\n    return 1\n", "none"),
    ],
    ids=["returned", "bound-then-tested", "truthy", "raise", "unbound-on-refusal"],
)
def test_a_result_that_governs_the_outcome_is_accepted(
    tmp_path: Path, body: str, outcome: str
) -> None:
    assert _governed_case(tmp_path, body, outcome) == []


@pytest.mark.parametrize(
    "body, outcome",
    [
        ("    ask(c, p, context='payload')\n    return None\n", "value"),
        (_BOUND + "    return None\n", "value"),
        (_BOUND + "    if r is not None:\n        pass\n    return None\n", "value"),
        # the refusal branch admits the column
        (_BOUND + "    if r is not None:\n        return None\n    return 'ok'\n", "value"),
        (_BOUND + "    if r is not None:\n        return (None, None)\n    return 'ok'\n", "value"),
        # the test is reversed: a refusal takes the admit path
        (_BOUND + "    if r is None:\n        return 'x'\n    return None\n", "value"),
        (_BOUND + "    if not r:\n        return 'x'\n    return None\n", "value"),
        # raise expected, a return found; and the reverse
        (_BOUND + "    if r is not None:\n        return r\n", "raise"),
        (_BOUND + "    if r is not None:\n        raise ValueError('x')\n", "value"),
    ],
    ids=[
        "discarded",
        "bound-unused",
        "tested-no-exit",
        "branch-admits",
        "branch-admits-tuple",
        "reversed-is-none",
        "reversed-not",
        "return-for-raise",
        "raise-for-return",
    ],
)
def test_a_discarded_or_reversed_decision_result_is_rejected(
    tmp_path: Path, body: str, outcome: str
) -> None:
    assert _governed_case(tmp_path, body, outcome) == [("execution/route.py", "route")]


@pytest.mark.parametrize(
    "spelling",
    [
        "from decoy_engine.execution.native import fpe_checksum_config_rejection as r\n",
        "from decoy_engine.execution.native import fpe_checksum_config_rejection\nr = fpe_checksum_config_rejection\n",
        "from decoy_engine.execution.native import fpe_checksum_config_rejection as a\nr = a\n",
        "import decoy_engine.execution.native as n\nr = n.fpe_checksum_config_rejection\n",
    ],
    ids=["import-alias", "assignment-alias", "alias-of-alias", "module-attribute-alias"],
)
def test_every_local_spelling_of_the_adapter_is_a_caller(tmp_path: Path, spelling: str) -> None:
    src = spelling + "def f():\n    return r('c', {}, context='payload')\n"
    index = _seeded(tmp_path, {"execution/a.py": src})
    ((rel, tree),) = trees(index)
    assert callers(rel, tree, "fpe_checksum_config_rejection") == [
        (("execution/a.py", "f"), "payload")
    ]


def test_a_private_copy_of_a_decision_function_is_seen(tmp_path: Path) -> None:
    files = {
        "execution/native/_operator_config_rejections.py": _DECISION_DEF,
        "execution/b.py": "def fpe_checksum_config_rejection(c, p, *, context):\n    return None\n",
    }
    index = _seeded(tmp_path, files)
    assert defining_modules(index, "fpe_checksum_config_rejection") == [
        "execution/b.py",
        "execution/native/_operator_config_rejections.py",
    ]


_MASK = (
    "NATIVE_FPE_DETECTORS: frozenset[str] = frozenset(\n"
    "    d for d, (charset, checksum) in _FPE_CONFIG.items()\n"
    "    if {cond}\n)\n"
)


@pytest.mark.parametrize(
    "cond, pinned",
    [
        ("checksum is None and charset == 'digits'", True),
        ("checksum is None and charset == 'digits' and d != 'fax_number'", True),
        ("checksum is None or charset == 'digits'", False),
        ("not (checksum is None and charset == 'digits')", False),
        ("(checksum is None or d == 'x') and charset == 'digits'", False),
        ("charset == 'digits'", False),
        ("checksum is None", False),
        ("checksum is not None and charset == 'digits'", False),
    ],
)
def test_the_text_mask_restriction_check_reads_the_boolean_relation(
    cond: str, pinned: bool
) -> None:
    assert text_mask_restriction_pinned(_MASK.format(cond=cond)) is pinned


def test_a_second_read_inside_a_listed_function_changes_the_count() -> None:
    src = "def f(cfg):\n    a = cfg.get('checksum')\n    return cfg.get('checksum') or a\n"
    assert scheme_reads(src, "x.py")[("x.py", "f")] == 3  # two reads and a use of the bound `a`


def test_a_refusal_branching_on_a_name_bound_to_the_scheme_changes_the_count() -> None:
    """The mutation Codex inserted in `FpeConfig._resolve`: a second checksum refusal on the
    bound name, right after `checksum = self.checksum or None`."""
    rel = "execution/native/_crypto_ext.py"
    src = dict(sources())[rel]
    anchor = "        checksum = self.checksum or None\n"
    assert anchor in src
    mutated = src.replace(
        anchor, anchor + "        if checksum == 'vin':\n            raise FpeConfigError('vin')\n"
    )
    edge = (rel, "FpeConfig._resolve")
    assert scheme_reads(mutated, rel)[edge] == scheme_reads(src, rel)[edge] + 1


_CAPTURED = (
    "def outer(cfg):\n"
    "    checksum = cfg.get('checksum') or None\n"
    "    def inner(v):\n"
    "        if checksum == 'vin':\n"
    "            raise ValueError\n"
    "        return v\n"
    "    return inner\n"
)
_FPE_ROW = (
    "def f(det_id):\n"
    "    charset, checksum = _FPE_CONFIG[det_id]\n"
    "    if checksum == 'vin':\n"
    "        raise ValueError\n"
    "    return charset\n"
)


def test_a_branch_on_a_name_captured_by_a_nested_function_is_counted() -> None:
    """The read counter and the delivery check share one binding rule, so a closure that
    branches on the enclosing function's scheme name changes the count."""
    reads = scheme_reads(_CAPTURED, "x.py")
    assert reads[("x.py", "outer")] == 1  # the key read
    assert reads[("x.py", "outer.inner")] == 1


def test_an_fpe_config_row_unpacking_binds_the_scheme() -> None:
    """`charset, checksum = _FPE_CONFIG[det_id]` carries the scheme in its second item."""
    assert scheme_reads(_FPE_ROW, "x.py")[("x.py", "f")] == 1
    tree = ast.parse(_FPE_ROW)
    assert bound_scheme_names(tree, "f") == {"checksum"}


def test_the_first_item_of_an_fpe_config_row_is_not_the_scheme() -> None:
    src = "def f(d):\n    charset, checksum = _FPE_CONFIG[d]\n    return charset\n"
    assert scheme_reads(src, "x.py")[("x.py", "f")] == 0
