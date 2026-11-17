"""Pure expansion of a `policy` block over a raw pipeline config.

`expand_policy(raw, inputs)` decides every mask column from the highest-precedence level that
matches it (`_precedence`), writes the decision into a new column dict, and reports why. It reads
only config names and labels, never a cell value, and never writes to `raw`: tables and columns
are copied before the decided keys go in. Every problem found is collected and raised together,
at its config location, as one `ValidationError`; messages carry rule ids and `table.column`
names only.

A malformed structure (tables not a list, a column without a string `name`, a column whose own
keys fail the decision types) is skipped here so the model's own validation reports it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as _PydanticValidationError
from pydantic_core import ValidationError

from decoy_engine import reasons
from decoy_engine._canonical import canonical_json_bytes
from decoy_engine.config._generate_options import ContextProblem, problem_details
from decoy_engine.config.policy._policy import ColumnDecision, DisguisePin, PolicyConfig, PolicyRule
from decoy_engine.config.policy._precedence import PrecedenceLevel, selector_level
from decoy_engine.config.policy._selectors import facts_for, matches, roles_by_field
from decoy_engine.contracts.declared_casting import CONTRACT_FIELDS
from decoy_engine.detection.domains import registered_detector_ids

__all__ = [
    "DecisionSource",
    "ExpansionInputs",
    "FieldDecision",
    "PolicyExpansion",
    "RuleMatch",
    "expand_policy",
]

# The keys a column may carry without a strategy: identity, labels and the F06 declared-casting
# contract. Anything else shapes the strategy, so a policy-decided column may not set it.
_ALLOWED_WITHOUT_STRATEGY = frozenset({"name", "classification", "tags", *CONTRACT_FIELDS})
_DECISION_KEYS = tuple(ColumnDecision.model_fields)


_TEMPLATES = {
    str(reasons.config.POLICY_UNKNOWN_CLASSIFICATION): (
        "Column {field} names a classification the engine does not know."
    ),
    str(reasons.config.POLICY_UNKNOWN_STRATEGY): (
        "The policy {where} names a masking strategy the engine does not know."
    ),
    str(reasons.config.POLICY_SELECTOR_UNMATCHED): "Rule {rule} selects no mask column.",
    str(reasons.config.POLICY_RULE_CONFLICT): (
        "{first} and {second} decide {field} differently at level {level}; "
        "make them agree or write the column's own strategy."
    ),
    str(reasons.config.POLICY_FIELD_UNDECIDED): (
        "No policy level decides {field}; give the column a strategy or add a rule or default."
    ),
    str(reasons.config.POLICY_BLOCK_INVALID): (
        "Column {field} has a provider_config value JSON cannot carry."
    ),
    str(reasons.config.POLICY_COLUMN_PARTIAL): (
        "Column {field} has no strategy but sets {key}; write its strategy to tune it."
    ),
}


@dataclass(frozen=True)
class DecisionSource:
    """Where a decision came from. `kind` is column, rule, disguise or default."""

    kind: str
    id: str

    @property
    def label(self) -> str:
        return self.kind if self.kind == "default" else f"{self.kind} {self.id}"


@dataclass(frozen=True)
class FieldDecision:
    """The decision for one mask field, its level, the sources that agree at that level and the
    rule ids that matched at a less specific level and lost."""

    table: str
    column: str
    decision: ColumnDecision
    level: PrecedenceLevel
    sources: tuple[DecisionSource, ...]
    overridden: tuple[str, ...]
    classification: str | None


@dataclass(frozen=True)
class RuleMatch:
    id: str
    level: PrecedenceLevel
    matched: int


@dataclass(frozen=True)
class PolicyExpansion:
    disguise: DisguisePin | None
    fields: tuple[FieldDecision, ...]
    rules: tuple[RuleMatch, ...]


@dataclass(frozen=True)
class ExpansionInputs:
    """`classification_default` is the level 4 source: a disguise rule for a classification."""

    policy: PolicyConfig
    strategies: frozenset[str]
    classification_default: Callable[[str], ColumnDecision | None]


@dataclass(frozen=True)
class _Candidate:
    level: PrecedenceLevel
    source: DecisionSource
    decision: ColumnDecision


def _decision_key(decision: ColumnDecision) -> bytes:
    """Equality of normalized decisions: the canonical JSON of the full decision."""
    return canonical_json_bytes(decision.model_dump())


def _own_decision(column: Mapping[str, Any]) -> tuple[ColumnDecision | None, bool]:
    """The column's own strategy as a decision, with the coercion `ColumnConfig` applies.

    Returns `(None, False)` only when `ColumnConfig` would refuse the keys too, so its own error
    reports them. The flag is set for a `provider_config` JSON cannot carry.
    """
    own = {k: column[k] for k in _DECISION_KEYS if k in column}
    try:
        return ColumnDecision.model_validate(own, strict=False), False
    except _PydanticValidationError as exc:
        unjson = any(e["type"] == str(reasons.config.POLICY_BLOCK_INVALID) for e in exc.errors())
    return None, unjson


def _decided_column(column: Mapping[str, Any], decision: ColumnDecision) -> dict[str, Any]:
    decided = {k: copy.deepcopy(v) for k, v in decision.model_dump().items()}
    return {**column, **{k: decided[k] for k in _DECISION_KEYS}}


class _Expansion:
    """One run of `expand_policy`: the screened rules, the problems found and the decided fields."""

    def __init__(self, raw: Mapping[str, Any], inputs: ExpansionInputs) -> None:
        self._raw = raw
        self._inputs = inputs
        self._problems: list[ContextProblem] = []
        self._known_classes = registered_detector_ids()
        self._roles = roles_by_field(raw.get("relationships"))
        pin = inputs.policy.disguise
        self._pin = pin
        self._disguise = DecisionSource(
            "disguise", f"{pin.id}@{pin.version}" if pin else "disguise"
        )
        self._rules = self._screened_rules()
        self._default = self._screened_default()
        self._matched = dict.fromkeys((r.id for _, r, _ in self._rules), 0)
        self._fields: list[FieldDecision] = []

    def _problem(self, loc: tuple[str | int, ...], code: object, **ctx: str) -> None:
        self._problems.append((loc, str(code), ctx))

    def _screened_rules(self) -> list[tuple[int, PolicyRule, PrecedenceLevel]]:
        """Rules with a known strategy and their level; an unknown strategy is a problem."""
        active = []
        for index, rule in enumerate(self._inputs.policy.rules):
            if rule.strategy in self._inputs.strategies:
                active.append((index, rule, selector_level(rule.select)))
            else:
                self._problem(
                    ("policy", "rules", index, "strategy"),
                    reasons.config.POLICY_UNKNOWN_STRATEGY,
                    where=f"rule {rule.id}",
                )
        return active

    def _screened_default(self) -> ColumnDecision | None:
        default = self._inputs.policy.default
        if default is None or default.strategy in self._inputs.strategies:
            return default
        self._problem(
            ("policy", "default", "strategy"),
            reasons.config.POLICY_UNKNOWN_STRATEGY,
            where="default",
        )
        return None

    def run(self) -> tuple[dict[str, Any], PolicyExpansion]:
        tables = self._raw.get("tables")
        new_tables: list[Any] = copy.deepcopy(tables) if isinstance(tables, list) else []
        for ti, table in enumerate(new_tables):
            if isinstance(table, dict) and isinstance(table.get("name"), str):
                columns = table.get("columns")
                if not isinstance(columns, list):
                    continue
                for ci, column in enumerate(columns):
                    if isinstance(column, dict) and isinstance(column.get("name"), str):
                        self._field(table["name"], ("tables", ti, "columns", ci), columns, ci)
        for index, rule, _ in self._rules:
            if self._matched[rule.id] == 0:
                self._problem(
                    ("policy", "rules", index),
                    reasons.config.POLICY_SELECTOR_UNMATCHED,
                    rule=rule.id,
                )
        if self._problems:
            details = problem_details(self._problems, _TEMPLATES)
            raise ValidationError.from_exception_data("PipelineConfig", details)
        out = dict(self._raw)
        if isinstance(tables, list):
            out["tables"] = new_tables
        rule_matches = tuple(
            RuleMatch(rule.id, level, self._matched[rule.id]) for _, rule, level in self._rules
        )
        return out, PolicyExpansion(self._pin, tuple(self._fields), rule_matches)

    def _classification(
        self, column: Mapping[str, Any], loc: tuple[str | int, ...], name: str
    ) -> str | None:
        label = column.get("classification")
        if not isinstance(label, str):
            return None
        if label in self._known_classes:
            return label
        self._problem(
            (*loc, "classification"),
            reasons.config.POLICY_UNKNOWN_CLASSIFICATION,
            field=name,
        )
        return None

    def _field(
        self, table: str, loc: tuple[str | int, ...], columns: list[Any], index: int
    ) -> None:
        column = columns[index]
        name = f"{table}.{column['name']}"
        classification = self._classification(column, loc, name)
        facts = facts_for(
            table, column, classification, self._roles.get((table, column["name"]), frozenset())
        )
        candidates: list[_Candidate] = []
        for _, rule, level in self._rules:
            if matches(rule.select, facts):
                self._matched[rule.id] += 1
                candidates.append(
                    _Candidate(level, DecisionSource("rule", rule.id), rule.decision())
                )
        if column.get("strategy") is not None:
            own, unjson = _own_decision(column)
            if own is None:
                if unjson:
                    self._problem(loc, reasons.config.POLICY_BLOCK_INVALID, field=name)
                return
            source = DecisionSource("column", name)
            candidates.append(_Candidate(PrecedenceLevel.EXACT_FIELD, source, own))
        else:
            shaping = sorted(set(column) - _ALLOWED_WITHOUT_STRATEGY - {"strategy"})
            if shaping:
                self._problem(loc, reasons.config.POLICY_COLUMN_PARTIAL, field=name, key=shaping[0])
                return
        if classification is not None:
            from_disguise = self._inputs.classification_default(classification)
            if from_disguise is not None:
                level = PrecedenceLevel.CLASSIFICATION_DEFAULT
                candidates.append(_Candidate(level, self._disguise, from_disguise))
        if self._default is not None:
            source = DecisionSource("default", "default")
            candidates.append(_Candidate(PrecedenceLevel.GLOBAL_DEFAULT, source, self._default))
        if not candidates:
            self._problem(loc, reasons.config.POLICY_FIELD_UNDECIDED, field=name)
            return
        best = min(c.level for c in candidates)
        chosen = [c for c in candidates if c.level == best]
        clash = next(
            (
                c
                for c in chosen[1:]
                if _decision_key(c.decision) != _decision_key(chosen[0].decision)
            ),
            None,
        )
        if clash is not None:
            self._problem(
                loc,
                reasons.config.POLICY_RULE_CONFLICT,
                first=chosen[0].source.label,
                second=clash.source.label,
                field=name,
                level=best.label,
            )
            return
        columns[index] = _decided_column(column, chosen[0].decision)
        self._fields.append(
            FieldDecision(
                table=table,
                column=column["name"],
                decision=chosen[0].decision,
                level=best,
                sources=tuple(c.source for c in chosen),
                overridden=tuple(
                    c.source.id for c in candidates if c.level > best and c.source.kind == "rule"
                ),
                classification=classification,
            )
        )


def expand_policy(
    raw: Mapping[str, Any], inputs: ExpansionInputs
) -> tuple[dict[str, Any], PolicyExpansion]:
    """Decide every mask column of `raw` and return the explicit config with the explanation."""
    return _Expansion(raw, inputs).run()
