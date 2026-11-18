"""Anonymity enforcement: generalization, search and transforms for quasi-identifiers.

``decoy_engine.anonymize.hierarchies`` builds per-column generalization
hierarchies and the lattice of level vectors that a search walks;
``decoy_engine.anonymize.search`` finds the least-loss node that meets privacy
models within a suppression limit; ``decoy_engine.anonymize.microaggregation``
replaces numeric quasi-identifiers by group means (MDAV) so the table is
k-anonymous on them. Nothing in config, the planner or a run reaches this
package; callers import it.

``type_family`` is the one value-identity rule for the anonymity code: cells
are the same value only when they are equal and of the same type family.
"""

from __future__ import annotations

from decoy_engine._value_family import type_family

__all__ = ["type_family"]
