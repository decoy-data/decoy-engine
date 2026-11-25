"""Validator registry for the SP-05 job-level validator framework (P5.INFRA.4).

The registry maps validator names to their callable implementations. Each
callable has the signature::

    fn(
        outputs: dict[str, pa.Table],
        entry: dict[str, Any],
        config: dict[str, Any],
        *,
        sources: dict[str, pa.Table] | None = None,
    ) -> tuple[ValidatorFinding, ...]

Sprint 2 honesty-pack S1 (2026-07-04, D2): ``sources`` is an additive,
keyword-only parameter carrying the caller-loaded pre-mask source tables
(``run_pipeline``'s ``caller_sources``, always in scope even for pure-generate
configs, where it is ``{}``). It exists so a validator that compares output
values against source values (leak_check, S2) can do so without a second
plumbing mechanism. The five pre-existing validators accept and ignore it.

Calling ``validate(outputs, config)`` runs every entry in the ``validators:``
config block through one ``ValidationSession`` (one span per table) and returns a frozen
``ValidationReport``.

Each built-in validator is a fold with a shape (``cell``, ``paired`` or ``keyed``) and a factory
in ``_SPECS``. ``_REGISTRY`` keeps the whole-table function of each one, which is also the
registry's public name-to-validator map; an entry added to ``_REGISTRY`` alone (a stub in a test)
runs as one whole-table call at the end of the session.

Adding a validator:
  1. Implement the fold and its whole-table function (see _catalog.py or _fk_validators.py).
  2. Register both: the function in ``_REGISTRY`` and its shape and factory in ``_SPECS``.
  3. Write a happy + deny-path test in tests/unit/validators/test_catalog.py.

The registry raises ``ValueError`` for unknown validator names at the point of
the ``validate()`` call so the operator gets a clear error at runtime rather
than a silent no-op.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, NamedTuple

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine.errors import ValidatorStateError
from decoy_engine.validators._catalog import (
    check_digit_fold,
    validate_iban,
    validate_luhn,
    validate_npi,
    validate_vin,
)
from decoy_engine.validators._fk_validators import (
    FkIntactFold,
    NoOrphanChildrenFold,
    validate_fk_intact,
    validate_no_orphan_children,
)
from decoy_engine.validators._fold import Fold, FoldResult, KeyStateBudget
from decoy_engine.validators._generic import (
    ColumnInSetFold,
    RegexMatchFold,
    validate_column_in_set,
    validate_regex_match,
)
from decoy_engine.validators._leak_check import LeakCheckFold, validate_leak_check
from decoy_engine.validators._relationship_checks import (
    ParentWindowFold,
    ReconciliationFold,
    validate_parent_window_respected,
    validate_reconciliation_holds,
)
from decoy_engine.validators._types import RowSpan, ValidationReport, ValidatorFinding

_ValidatorFn = Callable[..., tuple[ValidatorFinding, ...]]
# (entry, config, index cap, key-state budget) -> fold
_FoldFactory = Callable[[dict[str, Any], dict[str, Any], int | None, KeyStateBudget], Fold]

_REGISTRY: dict[str, _ValidatorFn] = {
    "luhn": validate_luhn,
    "npi": validate_npi,
    "iban": validate_iban,
    "vin": validate_vin,
    "fk_intact": validate_fk_intact,
    "no_orphan_children": validate_no_orphan_children,
    "leak_check": validate_leak_check,
    "regex_match": validate_regex_match,
    "column_in_set": validate_column_in_set,
    "parent_window_respected": validate_parent_window_respected,
    "reconciliation_holds": validate_reconciliation_holds,
}


class ValidatorSpec(NamedTuple):
    """How one built-in validator is folded."""

    shape: Literal["cell", "paired", "keyed"]
    factory: _FoldFactory
    fn: _ValidatorFn


_SPECS: dict[str, ValidatorSpec] = {
    "luhn": ValidatorSpec(
        "cell", lambda e, c, cap, b: check_digit_fold("luhn", e, c), validate_luhn
    ),
    "npi": ValidatorSpec("cell", lambda e, c, cap, b: check_digit_fold("npi", e, c), validate_npi),
    "iban": ValidatorSpec(
        "cell", lambda e, c, cap, b: check_digit_fold("iban", e, c), validate_iban
    ),
    "vin": ValidatorSpec("cell", lambda e, c, cap, b: check_digit_fold("vin", e, c), validate_vin),
    "regex_match": ValidatorSpec(
        "cell", lambda e, c, cap, b: RegexMatchFold(e, cap=cap), validate_regex_match
    ),
    "column_in_set": ValidatorSpec(
        "cell", lambda e, c, cap, b: ColumnInSetFold(e, cap=cap), validate_column_in_set
    ),
    "no_orphan_children": ValidatorSpec(
        "cell", lambda e, c, cap, b: NoOrphanChildrenFold(c, cap=cap), validate_no_orphan_children
    ),
    "leak_check": ValidatorSpec(
        "paired", lambda e, c, cap, b: LeakCheckFold(e, c, cap=cap), validate_leak_check
    ),
    "fk_intact": ValidatorSpec(
        "keyed", lambda e, c, cap, b: FkIntactFold(c, cap=cap, budget=b), validate_fk_intact
    ),
    "parent_window_respected": ValidatorSpec(
        "keyed",
        lambda e, c, cap, b: ParentWindowFold(e, c, cap=cap, budget=b),
        validate_parent_window_respected,
    ),
    "reconciliation_holds": ValidatorSpec(
        "keyed",
        lambda e, c, cap, b: ReconciliationFold(e, c, cap=cap, budget=b),
        validate_reconciliation_holds,
    ),
}


class _WholeTableFold:
    """A validator known only by its whole-table function: it sees every table at finish."""

    # The function may read any table's source, so a caller offers every resident source.
    reads_sources = True

    def __init__(
        self,
        fn: _ValidatorFn,
        entry: dict[str, Any],
        config: dict[str, Any],
        sources: dict[str, pa.Table] | None,
    ) -> None:
        self._fn = fn
        self._entry = entry
        self._config = config
        self._sources = sources
        self._tables: dict[str, pa.Table] = {}
        self._paired: dict[str, pa.Table] = {}

    def add(self, table: str, span: RowSpan) -> None:
        if table in self._tables:
            # A second batch would overwrite the first and the verdict would cover the last one.
            raise ValidatorStateError(
                code=reasons.runtime.VALIDATOR_SPAN_REPEATED,
                message=f"a whole-table validator was given table {table!r} in several batches.",
            )
        self._tables[table] = span.output
        # The source rows the route paired with this table are what the function compares to.
        if isinstance(span.source, pa.Table):
            self._paired[table] = span.source

    def table_complete(self, table: str) -> None:
        return None

    def paired_tables(self) -> frozenset[str]:
        return frozenset()

    def finish(self) -> FoldResult:
        sources = {**(self._sources or {}), **self._paired}
        return FoldResult(
            self._fn(self._tables, self._entry, self._config, sources=sources or self._sources)
        )


def validator_function(name: str) -> _ValidatorFn:
    """The registered whole-table function for ``name``, looked up at call time.

    Raises:
        KeyError: ``name`` is not a registered validator.
    """
    return _REGISTRY[name]


# Numeric parameters, by validator. Checked by type before any `float()` or `int()` runs, because
# Python's conversion errors echo the supplied text, and a config value may be a credential.
_NUMERIC_PARAMS: dict[str, dict[str, type]] = {
    "leak_check": {"max_identical_ratio": float, "min_rows": int},
    "reconciliation_holds": {"tolerance": float},
}


def _require_numeric_params(name: str, entry: dict[str, Any], index: int) -> None:
    params = entry.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError(f"validators entry {index}: params must be a mapping.")
    for param, kind in _NUMERIC_PARAMS.get(name, {}).items():
        if param not in params:
            continue
        value = params[param]
        accepted = (int, float) if kind is float else (int,)
        if isinstance(value, bool) or not isinstance(value, accepted):
            raise ValueError(
                f"validators entry {index}: params.{param} must be a number."
                if kind is float
                else f"validators entry {index}: params.{param} must be an integer."
            )


def build_fold(
    entry: Any,
    config: dict[str, Any],
    *,
    cap: int | None,
    budget: KeyStateBudget,
    sources: dict[str, pa.Table] | None,
    index: int = 0,
) -> tuple[str, Fold]:
    """Open the fold for one ``validators:`` entry.

    Raises:
        ValueError: The entry is not a dict, names an unknown validator, or has bad parameters
            (a bad regex, a missing ``allowed_values``): all before any row is read.
    """
    if not isinstance(entry, dict):
        raise ValueError(
            f"validators entry {index} must be a dict with a 'name' key, "
            f"got {type(entry).__name__!r}."
        )
    name: str = entry.get("name") or ""
    fn = _REGISTRY.get(name)
    if fn is None:
        raise ValueError(
            f"validators entry {index} names an unknown validator. "
            f"Known validators: {sorted(_REGISTRY)}"
        )
    _require_numeric_params(name, entry, index)
    spec = _SPECS.get(name)
    if spec is not None and spec.fn is fn:
        return name, spec.factory(entry, config, cap, budget)
    return name, _WholeTableFold(fn, entry, config, sources)


def validate(
    outputs: dict[str, pa.Table],
    config: dict[str, Any],
    *,
    sources: dict[str, pa.Table] | None = None,
) -> ValidationReport:
    """Run all configured validators and return a frozen ValidationReport.

    Reads the ``validators:`` list from ``config`` and opens one ``ValidationSession``, feeds it
    every output table as one span and finishes it. The report's ``passed`` attribute is
    ``True`` iff no findings were produced.

    This function is read-only with respect to ``outputs``: it does not mutate
    any ``pa.Table`` it receives (per CLAUDE.md: "Validation never mutates").

    Args:
        outputs: Read-only pipeline output tables, keyed by table name.
        config: Pipeline config dict (the validated dump from
            ``PipelineConfig.model_validate``). Validators are read from the
            ``validators:`` list.
        sources: Read-only caller-loaded pre-mask source tables, keyed by
            table name (Sprint 2 honesty pack, D2). ``None`` when the caller
            has no sources to offer (identical to passing ``{}``). Used by
            ``leak_check`` to compare output values against their source.

    Returns:
        Frozen ValidationReport.

    Raises:
        ValueError: If a validator entry names an unknown validator.
    """
    from decoy_engine.validators._session import ValidationSession

    session = ValidationSession(config, sources=sources)
    for table, output in outputs.items():
        session.observe(table, output)
    return session.finish()
