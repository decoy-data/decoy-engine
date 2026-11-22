"""Required strategy settings, declared once.

Each descriptor names one setting a strategy cannot run without. The plan check
(``plan.checks.check_required_strategy_settings``), the strategy catalog and the starter config
builder all read this one table, so no layer keeps its own list of which strategies need a
namespace. Descriptors hold a registered code and a fixed message only: no submitted value and no
callable predicate, so a refusal cannot echo config data. This module imports ``reasons`` only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import TYPED_DATE_SHAPES, ColumnShape

__all__ = [
    "REQUIREMENTS_BY_STRATEGY",
    "SHAPE_REQUIREMENTS_BY_STRATEGY",
    "ShapeRequirement",
    "StrategyRequirement",
    "lookup_path",
    "requirement_applies",
    "requirement_missing",
    "requirements_for",
    "shape_declaration_needed",
    "shape_mismatch_message",
    "shape_requirement_for",
]


@dataclass(frozen=True)
class StrategyRequirement:
    """One setting a strategy needs, as a path from a column entry.

    ``when_path`` and ``when_equals`` make the requirement conditional: it applies only when the
    value at ``when_path`` has exactly the type and value of ``when_equals``, so ``1`` never
    activates a boolean condition.
    """

    path: tuple[str, ...]
    code: str
    message: str
    when_path: tuple[str, ...] | None = None
    when_equals: bool | str | None = None

    def __post_init__(self) -> None:
        if not self.path or not self.message:
            raise ValueError("a strategy requirement needs a path and a message")
        if (self.when_path is None) != (self.when_equals is None):
            raise ValueError("when_path and when_equals are set together")


def _namespace(strategy: str, what: str | None = None, **when: Any) -> StrategyRequirement:
    code = getattr(reasons.plan, f"{strategy.upper()}_REQUIRES_NAMESPACE")
    return StrategyRequirement(
        ("namespace",), code, f"{what or strategy} needs a namespace; set `namespace`.", **when
    )


_PROVIDER = ("provider_config",)

_DATE_SHIFT_FORMAT = StrategyRequirement(
    (*_PROVIDER, "date_format"),
    reasons.plan.DATE_SHIFT_REQUIRES_DATE_FORMAT,
    "date_shift needs provider_config.date_format, the strftime format of its dates.",
)

REQUIREMENTS_BY_STRATEGY: Mapping[str, tuple[StrategyRequirement, ...]] = MappingProxyType(
    {
        "hash": (_namespace("hash"),),
        "fpe": (_namespace("fpe"),),
        "date_shift": (
            _namespace("date_shift"),
            _DATE_SHIFT_FORMAT,
        ),
        "bucket_perturb": (_namespace("bucket_perturb"),),
        "categorical": (_namespace("categorical"),),
        "tokenize": (_namespace("tokenize"),),
        "shuffle": (_namespace("shuffle", when_path=("deterministic",), when_equals=True),),
        "code_set": (
            _namespace(
                "code_set_gen",
                "code_set in gen mode",
                when_path=(*_PROVIDER, "mode"),
                when_equals="gen",
            ),
        ),
        "nested": (
            StrategyRequirement(
                (*_PROVIDER, "strategy"),
                reasons.plan.NESTED_STRATEGY_UNSET,
                "nested needs a child strategy; set `provider_config.strategy`.",
            ),
            StrategyRequirement(
                (*_PROVIDER, "target"),
                reasons.plan.NESTED_TARGET_UNSET,
                "nested needs a target path; set `provider_config.target`.",
            ),
        ),
    }
)


@dataclass(frozen=True)
class ShapeRequirement:
    """A setting a strategy needs for the column shapes in ``needs_declaration``.

    ``requirement`` is the setting itself, the same descriptor ``REQUIREMENTS_BY_STRATEGY`` holds,
    so its code, path and message live in one place. A column whose resolved shape is not in
    ``needs_declaration`` runs without the setting. ``declared_counts`` says that a top-level F06
    date declaration also satisfies it. ``admitted`` is every shape the strategy can read at all;
    any other known shape is refused as a mismatch, with ``hints`` (a fixed text per shape, else
    ``default_hint``) saying what to do instead.
    """

    family: str
    requirement: StrategyRequirement
    needs_declaration: frozenset[ColumnShape]
    declared_counts: bool = False
    admitted: frozenset[ColumnShape] = frozenset(ColumnShape)
    default_hint: str = ""
    hints: Mapping[ColumnShape, str] = field(default_factory=lambda: MappingProxyType({}))


_DATE_SHIFT_HINT = (
    "date_shift reads dates: use a date or zoned timestamp column, or text with a date_format."
)

# ``date_shift`` runs bare on a date or a zoned timestamp. Text needs its format, and so does an
# ``unknown`` column (compile has no proof it is typed). Every other shape cannot be read.
SHAPE_REQUIREMENTS_BY_STRATEGY: Mapping[str, ShapeRequirement] = MappingProxyType(
    {
        "date_shift": ShapeRequirement(
            "date",
            _DATE_SHIFT_FORMAT,
            frozenset({ColumnShape.TEXT, ColumnShape.UNKNOWN}),
            declared_counts=True,
            admitted=frozenset({ColumnShape.TEXT, ColumnShape.UNKNOWN}) | TYPED_DATE_SHAPES,
            default_hint=_DATE_SHIFT_HINT,
            hints=MappingProxyType(
                {
                    ColumnShape.TIMESTAMP_NAIVE: (
                        "cast it to a date or a zoned timestamp, or write it as text with a "
                        "date_format."
                    )
                }
            ),
        ),
    }
)


def shape_requirement_for(strategy: str, req: StrategyRequirement) -> ShapeRequirement | None:
    """The shape rule that governs ``req`` for ``strategy``, or None when ``req`` is not shape-bound."""
    shaped = SHAPE_REQUIREMENTS_BY_STRATEGY.get(strategy)
    return shaped if shaped is not None and shaped.requirement is req else None


def shape_mismatch_message(
    strategy: str, shaped: ShapeRequirement, shape: ColumnShape, column: str, table: str
) -> str | None:
    """The fixed refusal text when ``strategy`` cannot read a ``shape`` column, else None."""
    if shape in shaped.admitted:
        return None
    hint = shaped.hints.get(shape, shaped.default_hint)
    return (
        f"column {column!r} in table {table!r} is a {shape.value} column; "
        f"{strategy} cannot read it. {hint}"
    ).rstrip()


def shape_declaration_needed(
    shaped: ShapeRequirement, shape: ColumnShape, *, config_only: bool
) -> bool:
    """Whether a column of ``shape`` must carry the setting.

    A config-only pass cannot see typed sources, so an ``unknown`` column is refused only when
    every shape it could turn out to be needs the setting. Compile has the schema, so there an
    ``unknown`` column is refused like text.
    """
    if config_only and shape is ColumnShape.UNKNOWN:
        return all(s in shaped.needs_declaration for s in ColumnShape if s is not shape)
    return shape in shaped.needs_declaration


def requirements_for(strategy: str) -> tuple[StrategyRequirement, ...]:
    """The requirements of ``strategy``; empty when it declares none."""
    return REQUIREMENTS_BY_STRATEGY.get(strategy, ())


def requirement_missing(value: Any) -> bool:
    """Every required setting is a name, so anything but a non-blank string is missing."""
    return not isinstance(value, str) or not value.strip()


def lookup_path(entry: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = entry
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def requirement_applies(req: StrategyRequirement, entry: Mapping[str, Any]) -> bool:
    """Whether ``req`` binds the column ``entry``: always, or when its condition holds exactly."""
    if req.when_path is None:
        return True
    actual = lookup_path(entry, req.when_path)
    return type(actual) is type(req.when_equals) and actual == req.when_equals
