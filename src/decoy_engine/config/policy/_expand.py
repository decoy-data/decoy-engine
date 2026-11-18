"""Pure expansion of a `policy` block over a raw pipeline config.

`expand_policy(raw, inputs)` decides every mask column from the highest-precedence level that
matches it (`_precedence`), writes the decision into a new column dict, and reports why. It reads
only config names and labels, never a cell value, and never writes to `raw`: tables and columns
are copied before the decided keys go in. Every problem found is collected and raised together,
at its config location, as one `ValidationError`; messages carry rule ids and `table.column`
names only. Prohibitions run on the decided fields, level 1 included (`_prohibit`).

`expansion_to_dict` writes the `policy-expansion/v1` explanation: one decision per field with its
level and every agreeing source, the rules and prohibitions with their match counts, and a fingerprint of the
decisions. It holds a digest of each decision, never `provider_config` itself.

A malformed structure (tables not a list, a column without a string `name`, a column whose own
keys fail the decision types) is skipped here so the model's own validation reports it.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as _PydanticValidationError
from pydantic_core import ValidationError

from decoy_engine import reasons
from decoy_engine._canonical import canonical_json_bytes
from decoy_engine.config._generate_options import ContextProblem, problem_details
from decoy_engine.config.policy._policy import (
    ColumnDecision,
    DisguisePin,
    PolicyConfig,
    PolicyRule,
    Prohibition,
    json_carryable,
)
from decoy_engine.config.policy._precedence import PrecedenceLevel, selector_level
from decoy_engine.config.policy._prohibit import (
    ProhibitionMatch,
    evaluate_prohibitions,
)
from decoy_engine.config.policy._selectors import (
    FieldFacts,
    facts_for,
    matches,
    roles_by_field,
)
from decoy_engine.contracts.declared_casting import CONTRACT_FIELDS
from decoy_engine.detection.domains import registered_detector_ids

__all__ = [
    "POLICY_EXPANSION_SCHEMA",
    "DecisionSource",
    "ExpansionInputs",
    "FieldDecision",
    "PolicyExpansion",
    "RuleMatch",
    "expand_policy",
    "expansion_to_dict",
]

POLICY_EXPANSION_SCHEMA: Final = "policy-expansion/v1"
SourceKind = Literal["column", "rule", "disguise", "default"]
_SOURCE_ORDER: Final[dict[str, int]] = {"column": 0, "rule": 1, "disguise": 2, "default": 3}

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
    str(reasons.config.POLICY_PROHIBITED): (
        "Prohibition {prohibition} does not allow strategy {strategy} on {field}."
    ),
    str(reasons.config.POLICY_COLUMN_PARTIAL): (
        "Column {field} has no strategy but sets {key}; write its strategy to tune it."
    ),
}


@dataclass(frozen=True)
class DecisionSource:
    """Where a decision came from. `kind` is column, rule, disguise or default."""

    kind: SourceKind
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
    prohibitions: tuple[ProhibitionMatch, ...] = ()


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

    Returns `(None, False)` when `ColumnConfig` would refuse the keys too, so its own error
    reports them, or when the strategy string is empty or over 64 characters, which `ColumnConfig`
    accepts and the caller reports as an unknown strategy. The flag is set for a `provider_config`
    JSON cannot carry.
    """
    own = {k: column[k] for k in _DECISION_KEYS if k in column}
    if isinstance(own.get("provider_config"), Mapping) and not json_carryable(
        own["provider_config"]
    ):
        return None, True
    try:
        return ColumnDecision.model_validate(own, strict=False), False
    except _PydanticValidationError:
        return None, False


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
        self._prohibitions = self._screened_prohibitions()
        self._fields: list[FieldDecision] = []
        self._facts: list[FieldFacts] = []

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

    def _screened_prohibitions(self) -> list[tuple[int, Prohibition]]:
        """Prohibitions whose strategy names are all known; a typo would never trigger."""
        active = []
        for index, prohibition in enumerate(self._inputs.policy.prohibit):
            mode = "forbid" if prohibition.forbid is not None else "require"
            names = prohibition.forbid if prohibition.forbid is not None else prohibition.require
            if all(name in self._inputs.strategies for name in names or ()):
                active.append((index, prohibition))
            else:
                self._problem(
                    ("policy", "prohibit", index, mode),
                    reasons.config.POLICY_UNKNOWN_STRATEGY,
                    where=f"prohibition {prohibition.id}",
                )
        return active

    def _check_prohibitions(self) -> tuple[ProhibitionMatch, ...]:
        decided = [(f, d.decision.strategy) for f, d in zip(self._facts, self._fields, strict=True)]
        found, violations = evaluate_prohibitions(self._prohibitions, decided)
        for violation in violations:
            self._problem(
                ("policy", "prohibit", violation.index),
                reasons.config.POLICY_PROHIBITED,
                prohibition=violation.id,
                strategy=violation.strategy,
                field=violation.field,
            )
        return found

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
        prohibitions = self._check_prohibitions()
        if self._problems:
            details = problem_details(self._problems, _TEMPLATES)
            raise ValidationError.from_exception_data("PipelineConfig", details)
        out = dict(self._raw)
        if isinstance(tables, list):
            out["tables"] = new_tables
        rule_matches = tuple(
            RuleMatch(rule.id, level, self._matched[rule.id]) for _, rule, level in self._rules
        )
        return out, PolicyExpansion(self._pin, tuple(self._fields), rule_matches, prohibitions)

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
                elif isinstance(column["strategy"], str) and not 1 <= len(column["strategy"]) <= 64:
                    self._problem(
                        (*loc, "strategy"),
                        reasons.config.POLICY_UNKNOWN_STRATEGY,
                        where=f"column {name}",
                    )
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
        # Column first, then rules in policy order, then disguise, then default. The sort is
        # stable, so rules keep policy order; the conflict message and the explanation share it.
        chosen = sorted(
            (c for c in candidates if c.level == best), key=lambda c: _SOURCE_ORDER[c.source.kind]
        )
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
        self._facts.append(facts)
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


# -- policy-expansion/v1 ------------------------------------------------------------------------

_WRITER = ConfigDict(extra="forbid", strict=True, frozen=True)


class _SourceDoc(BaseModel):
    model_config = _WRITER
    kind: SourceKind
    id: str


class _FieldDoc(BaseModel):
    model_config = _WRITER
    table: str
    column: str
    strategy: str
    provider: str | None
    deterministic: bool
    level: int
    level_name: str
    sources: list[_SourceDoc] = Field(min_length=1)
    overridden: list[str]
    classification: str | None
    decision_digest: str


class _RuleDoc(BaseModel):
    model_config = _WRITER
    id: str
    level: int
    matched: int


class _ProhibitionDoc(BaseModel):
    model_config = _WRITER
    id: str
    matched: int


class _PinDoc(BaseModel):
    model_config = _WRITER
    id: str
    version: str


class _ExpansionDoc(BaseModel):
    """The one strict writer of `policy-expansion/v1`. Nothing reads the document back in V1."""

    model_config = _WRITER
    schema_: Literal["policy-expansion/v1"] = Field(serialization_alias="schema")
    disguise: _PinDoc | None
    fingerprint: str
    fields: list[_FieldDoc]
    rules: list[_RuleDoc]
    prohibitions: list[_ProhibitionDoc]


def _digest(decision: ColumnDecision) -> str:
    return hashlib.sha256(_decision_key(decision)).hexdigest()


def _fingerprint(expansion: PolicyExpansion) -> str:
    """SHA-256 of the sorted `[table, column, decision_digest]` list and the disguise pin."""
    pin = expansion.disguise
    body = {
        "disguise": {"id": pin.id, "version": pin.version} if pin else None,
        "fields": sorted([f.table, f.column, _digest(f.decision)] for f in expansion.fields),
    }
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def expansion_to_dict(expansion: PolicyExpansion) -> dict[str, Any]:
    """The `policy-expansion/v1` explanation of `expansion`, in field order."""
    pin = expansion.disguise
    doc = _ExpansionDoc(
        schema_=POLICY_EXPANSION_SCHEMA,
        disguise=_PinDoc(id=pin.id, version=pin.version) if pin else None,
        fingerprint=_fingerprint(expansion),
        fields=[
            _FieldDoc(
                table=f.table,
                column=f.column,
                strategy=f.decision.strategy,
                provider=f.decision.provider,
                deterministic=f.decision.deterministic,
                level=int(f.level),
                level_name=f.level.label,
                sources=[_SourceDoc(kind=s.kind, id=s.id) for s in f.sources],
                overridden=list(f.overridden),
                classification=f.classification,
                decision_digest=_digest(f.decision),
            )
            for f in expansion.fields
        ],
        rules=[_RuleDoc(id=r.id, level=int(r.level), matched=r.matched) for r in expansion.rules],
        prohibitions=[_ProhibitionDoc(id=p.id, matched=p.matched) for p in expansion.prohibitions],
    )
    return doc.model_dump(by_alias=True)
