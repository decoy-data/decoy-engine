"""Pipeline `policy` block: selectors, 5-level precedence and expansion (F16, row 81).

Exported here and not from `decoy_engine.config` or the top-level package. The production caller
is the `PipelineConfig` validator (slice E3); until then these names are used by tests only.
"""

from __future__ import annotations

from decoy_engine.config.policy._expand import (
    DecisionSource,
    ExpansionInputs,
    FieldDecision,
    PolicyExpansion,
    RuleMatch,
    expand_policy,
)
from decoy_engine.config.policy._policy import (
    ColumnDecision,
    DisguisePin,
    PolicyConfig,
    PolicyRule,
    Prohibition,
)
from decoy_engine.config.policy._precedence import PrecedenceLevel
from decoy_engine.config.policy._selectors import Selector

__all__ = [
    "ColumnDecision",
    "DecisionSource",
    "DisguisePin",
    "ExpansionInputs",
    "FieldDecision",
    "PolicyConfig",
    "PolicyExpansion",
    "PolicyRule",
    "PrecedenceLevel",
    "Prohibition",
    "RuleMatch",
    "Selector",
    "expand_policy",
]
