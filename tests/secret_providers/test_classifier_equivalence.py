"""F13 §5 equivalence: the config-only classifier and the compiled-plan classifier agree.

The config classifier runs BEFORE any source read, so it is conservative: it must report keyed
whenever the plan is keyed (drift would admit keyed work without a secret), and it must agree
exactly on every strategy it recognises. Unrecognised strategies default to keyed.
"""

from __future__ import annotations

import ast
import inspect
import tempfile
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from decoy_engine.config import PipelineConfig
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.execution._technique_class import TECHNIQUE_CLASS_BY_STRATEGY
from decoy_engine.keyprovider import KeyedStrategyRequiresSecret
from decoy_engine.plan import compile_plan
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.profile import profile_source
from decoy_engine.secret_providers import (
    admit_mask_key,
    secret_requirements_for_config,
    secret_requirements_for_plan,
)
from decoy_engine.secret_providers._requirements import (
    ALWAYS_KEYED_STRATEGIES,
    KNOWN_UNKEYED_STRATEGIES,
    MASK_ROOT,
    column_is_keyed,
)

# Strategies whose columns compile with only a name + strategy (no extra required config).
SIMPLE = [
    "redact",
    "passthrough",
    "truncate",
    "hash",
    "fpe",
    "shuffle",
    "categorical",
    "text_redact",
]


_DIR = Path(tempfile.mkdtemp(prefix="f13-equiv-"))
(_DIR / "t.csv").write_text("email\n" + "\n".join(["a", "b", "a", "b"] * 5) + "\n")


def _compile(_unused, columns):
    return PipelineConfig.model_validate(
        {
            "version": 2,
            "global_settings": {"seed": 1},
            "sources": {
                "t": {
                    "type": "file",
                    "format": "csv",
                    "has_header": True,
                    "path": str(_DIR / "t.csv"),
                }
            },
            "tables": [{"name": "t", "columns": columns}],
            "targets": {"t": {"type": "file", "format": "csv", "path": str(_DIR / "o.csv")}},
        }
    ).model_dump()


def test_strategy_universe_is_fully_classified():
    universe = set(TECHNIQUE_CLASS_BY_STRATEGY) | {"from_parent"}
    assert universe <= ALWAYS_KEYED_STRATEGIES | KNOWN_UNKEYED_STRATEGIES, (
        "a strategy the registry knows is unclassified; the conservative default would force a "
        "secret for it. Add it to ALWAYS_KEYED_STRATEGIES or KNOWN_UNKEYED_STRATEGIES."
    )
    assert not ALWAYS_KEYED_STRATEGIES & KNOWN_UNKEYED_STRATEGIES


def test_unrecognised_strategies_default_to_keyed():
    assert column_is_keyed("brand_new", deterministic=False, vault=False, provider_config={})
    assert column_is_keyed(
        "nested", deterministic=False, vault=False, provider_config={"strategy": "brand_new"}
    )
    assert not column_is_keyed("redact", deterministic=False, vault=False, provider_config={})


@settings(max_examples=60, deadline=None)
@given(
    strategy=st.sampled_from(SIMPLE),
    deterministic=st.booleans(),
    vault=st.booleans(),
)
def test_config_and_plan_classifiers_agree_on_recognised_strategies(strategy, deterministic, vault):
    col = {"name": "email", "strategy": strategy, "namespace": "ns"}
    if strategy == "truncate":
        col["provider_config"] = {"length": 3}
    if strategy == "categorical":
        col["provider_config"] = {"categories": ["a", "b"]}
    if deterministic and strategy in ("categorical",):
        col["deterministic"] = True
    if vault:
        col["vault"] = True
    cfg = _compile(None, [col])
    prof = profile_source(cfg, seed=1)
    try:
        plan = compile_plan(cfg, prof, decoy_engine_version="f13")
    except PlanCompileError:
        assume(False)  # the compiler rejects this combination; nothing to classify
    assert bool(secret_requirements_for_config(cfg)) == bool(secret_requirements_for_plan(plan))


def test_composite_fk_groups_are_keyed_from_config_alone():
    cfg = _compile(None, [{"name": "a", "strategy": "redact"}])
    cfg["relationships"] = [
        {
            "parent": {"table": "p", "columns": ["x", "y"]},
            "children": [{"table": "t", "columns": ["a", "b"]}],
            "orphan_policy": "preserve",
        }
    ]
    assert secret_requirements_for_config(cfg)


def test_generate_tables_do_not_require_a_secret():
    cfg = _compile(None, [{"name": "a", "strategy": "redact"}])
    cfg["tables"] = [
        {"name": "g", "generate_columns": [{"name": "n", "type": "int"}], "columns": []}
    ]
    assert secret_requirements_for_config(cfg) == ()


# --- date_shift classification (roadmap row 24zb, E1) -------------------------------------------


def _raw(columns, **table_extra):
    return {"tables": [{"name": "t", "columns": columns, **table_extra}]}


_DATE = {"name": "d", "strategy": "date_shift", "namespace": "ns"}
_KEYED_DATE_SHAPES = {
    "plain": _raw([_DATE]),
    "group_by": _raw([{**_DATE, "provider_config": {"group_by": "pid"}}]),
    "preserve_values": _raw([{**_DATE, "provider_config": {"preserve_values": ["1900-01-01"]}}]),
    "deterministic_false": _raw([{**_DATE, "deterministic": False}]),
    "when": _raw([{**_DATE, "when": "d is not null"}]),
    "nested_child": _raw(
        [
            {
                "name": "d",
                "strategy": "nested",
                "namespace": "ns",
                "provider_config": {"target": "$.d", "strategy": "date_shift"},
            }
        ]
    ),
    "text_mask_date_detector": _raw(
        [
            {
                "name": "d",
                "strategy": "text_mask",
                "namespace": "ns",
                "provider_config": {
                    "detectors": ["iso_date", "us_date", "eu_date"],
                    "per_detector_strategy": {"iso_date": "date_shift"},
                },
            }
        ]
    ),
}


@pytest.mark.parametrize("shape", sorted(_KEYED_DATE_SHAPES))
def test_every_date_shift_shape_needs_the_mask_secret(shape):
    cfg = _KEYED_DATE_SHAPES[shape]
    assert secret_requirements_for_config(cfg) == (MASK_ROOT,)
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        admit_mask_key(cfg)
    assert info.value.code == "keyed_strategy_requires_secret"


def test_mask_columns_beside_generate_columns_are_not_skipped():
    """A raw table dict that holds both kinds must not hide a keyed mask column. Validated input
    cannot have this shape; the public classifiers take raw dicts, so they walk it anyway."""
    cfg = _raw([_DATE], generate_columns=[{"name": "n", "type": "int"}])
    assert secret_requirements_for_config(cfg) == (MASK_ROOT,)


def _reads_mask_key(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "mask_key":
            return True
        if isinstance(node, ast.keyword) and node.arg == "mask_key":
            return True
        if isinstance(node, ast.Name) and node.id == "mask_key":
            return True
    return False


def _handler_modules_reading_mask_key() -> list[tuple[str, Path]]:
    out = []
    for name, handler in sorted(SCALAR_HANDLERS.items()):
        src = inspect.getsourcefile(type(handler))
        assert src is not None, name
        if _reads_mask_key(ast.parse(Path(src).read_text(encoding="utf-8"))):
            out.append((name, Path(src)))
    return out


def test_handlers_that_read_mask_key_are_classified_keyed():
    """A handler that derives from `ctx.mask_key` is keyed work. Default-unkeyed is allowed only
    when the handler advertises the `deterministic` option and both the deterministic and the
    vault shape classify keyed (faker, categorical)."""
    readers = _handler_modules_reading_mask_key()
    assert readers, "the walk found no handler that reads mask_key; the scan is broken"
    assert "date_shift" in {name for name, _ in readers}
    bad = []
    for name, _src in readers:

        def keyed(det: bool, vault: bool, name: str = name) -> bool:
            return column_is_keyed(name, deterministic=det, vault=vault, provider_config={})

        if keyed(False, False):
            continue
        option_names = {o.name for o in SCALAR_HANDLERS[name].wizard_options}
        if not ("deterministic" in option_names and keyed(True, False) and keyed(False, True)):
            bad.append(name)
    assert not bad, (
        f"handlers read mask_key but classify unkeyed with no conditional shape: {sorted(bad)}. "
        "Move the strategy to ALWAYS_KEYED_STRATEGIES."
    )


def test_every_always_keyed_handler_is_refused_without_a_secret():
    names = sorted(ALWAYS_KEYED_STRATEGIES & set(SCALAR_HANDLERS))
    assert "date_shift" in names
    for name in names:
        cfg = _raw([{"name": "c", "strategy": name, "namespace": "ns"}])
        with pytest.raises(KeyedStrategyRequiresSecret) as info:
            admit_mask_key(cfg)
        assert info.value.code == "keyed_strategy_requires_secret", name


def _strategy_context_calls() -> list[tuple[str, int, ast.Call]]:
    root = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
    calls = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                called = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if called == "StrategyContext":
                    calls.append((path.relative_to(root).as_posix(), node.lineno, node))
    return calls


def test_every_strategy_context_gets_its_mask_key_from_require_mask_key():
    """`StrategyContext.__post_init__` falls back to `job_seed` for an empty mask_key, so a
    construction that leaves the keyword out would run keyed work off the visible seed."""
    calls = _strategy_context_calls()
    assert len(calls) >= 2, "the walk found fewer StrategyContext constructions than exist"
    bad = []
    for rel, line, node in calls:
        kw = {k.arg: k.value for k in node.keywords}
        value = kw.get("mask_key")
        ok = isinstance(value, ast.Call) and (
            getattr(value.func, "id", None) == "require_mask_key"
            or getattr(value.func, "attr", None) == "require_mask_key"
        )
        if not ok:
            bad.append(f"{rel}:{line}")
    assert not bad, f"StrategyContext built without mask_key=require_mask_key(...): {bad}"
