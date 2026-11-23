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
from decoy_engine.contracts.bucketize_width import MAX_EXACT_DECIMAL_WIDTH, resolve_bucketize_width
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

    ``requirement`` is the setting itself (None for a strategy that needs none, such as ``fpe``),
    the same descriptor ``REQUIREMENTS_BY_STRATEGY`` holds for ``date_shift``, so its code, path
    and message live in one place. A column whose resolved shape is not in ``needs_declaration``
    runs without the setting. ``declared_counts`` says that a top-level F06 date declaration also
    satisfies it. ``cast_declared`` says the setting is the F06 cast itself: its absence is what
    makes the column text, so a column whose shape needs it has not made it.

    ``admitted`` is every shape the strategy can read at all; any other known shape is refused as a
    mismatch, with ``hints`` (a fixed text per shape, else ``default_hint``) saying what to do
    instead. ``exact_decimal_width`` adds one condition on an admitted decimal: the effective width
    must be an integer float64 divides exactly, else the decimal is refused with its hint.
    """

    family: str
    requirement: StrategyRequirement | None
    needs_declaration: frozenset[ColumnShape]
    declared_counts: bool = False
    cast_declared: bool = False
    admitted: frozenset[ColumnShape] = frozenset(ColumnShape)
    default_hint: str = ""
    hints: Mapping[ColumnShape, str] = field(default_factory=lambda: MappingProxyType({}))
    exact_decimal_width: bool = False


def _number_declaration(strategy: str, tail: str) -> StrategyRequirement:
    return StrategyRequirement(
        ("logical_type",),
        reasons.plan.COLUMN_SHAPE_REQUIRED,
        f"{strategy} reads numbers from text; declare logical_type integer with a parse_format{tail}.",
    )


_DATE_SHIFT_HINT = (
    "date_shift reads dates: use a date or zoned timestamp column, or text with a date_format."
)
_NEEDS_NUMBER_DECLARATION = frozenset({ColumnShape.TEXT, ColumnShape.UNKNOWN})
_TOP_CODE_DECIMAL_HINT = "top_code reads integers; cast the column to an integer."
_TOP_CODE_ADMITTED = _NEEDS_NUMBER_DECLARATION | {ColumnShape.INTEGER, ColumnShape.FLOAT}

# ``date_shift`` runs bare on a date or a zoned timestamp. Text needs its format, and so does an
# ``unknown`` column (compile has no proof it is typed). Every other shape cannot be read. The
# numeric strategies need an F06 integer declaration on text (``bucketize`` also takes a bounded
# decimal) and compute as they do today on typed numbers. ``fpe`` needs no declaration: a text
# column is its charset's business.
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
        "bucketize": ShapeRequirement(
            "number",
            _number_declaration("bucketize", ", or decimal with precision 15 or less"),
            _NEEDS_NUMBER_DECLARATION,
            cast_declared=True,
            admitted=_TOP_CODE_ADMITTED | {ColumnShape.DECIMAL},
            default_hint="cast the column to a type bucketize can read.",
            hints=MappingProxyType(
                {
                    ColumnShape.DECIMAL: (
                        "a decimal column needs an integer width from 1 to 10^15 so float64 "
                        "buckets it exactly."
                    ),
                    ColumnShape.DECIMAL_WIDE: (
                        "more than 15 significant digits, or a negative scale, cannot be "
                        "bucketed exactly; reduce the precision or cast to float."
                    ),
                }
            ),
            exact_decimal_width=True,
        ),
        "top_code": ShapeRequirement(
            "number",
            _number_declaration("top_code", ""),
            _NEEDS_NUMBER_DECLARATION,
            cast_declared=True,
            admitted=_TOP_CODE_ADMITTED,
            default_hint="cast the column to a type top_code can read.",
            hints=MappingProxyType(
                {
                    ColumnShape.DECIMAL: _TOP_CODE_DECIMAL_HINT,
                    ColumnShape.DECIMAL_WIDE: _TOP_CODE_DECIMAL_HINT,
                }
            ),
        ),
        "fpe": ShapeRequirement(
            "text-or-integer",
            None,
            frozenset(),
            admitted=frozenset({ColumnShape.TEXT, ColumnShape.INTEGER, ColumnShape.UNKNOWN}),
            default_hint="fpe reads text or integers; cast the column to text or an integer.",
        ),
    }
)


def shape_requirement_for(strategy: str, req: StrategyRequirement) -> ShapeRequirement | None:
    """The shape rule that governs ``req`` for ``strategy``, or None when ``req`` is not shape-bound."""
    shaped = SHAPE_REQUIREMENTS_BY_STRATEGY.get(strategy)
    return shaped if shaped is not None and shaped.requirement is req else None


def _exact_decimal_width(provider_config: Mapping[str, Any]) -> bool:
    """Whether the effective bucketize width is an integer float64 divides exactly.

    An unresolved width fails too: the bucketize width check names it first at compile, and a
    plan that skipped it has no width to bucket a decimal by.
    """
    width = resolve_bucketize_width(provider_config)
    return type(width) is int and 1 <= width <= MAX_EXACT_DECIMAL_WIDTH


def shape_mismatch_message(
    strategy: str,
    shaped: ShapeRequirement,
    shape: ColumnShape,
    column: str,
    table: str,
    provider_config: Mapping[str, Any] | None = None,
) -> str | None:
    """The fixed refusal text when ``strategy`` cannot read a ``shape`` column, else None."""
    readable = shape in shaped.admitted
    if readable and shaped.exact_decimal_width and shape is ColumnShape.DECIMAL:
        readable = _exact_decimal_width(provider_config or {})
    if readable:
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
