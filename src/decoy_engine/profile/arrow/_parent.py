"""The one place the Arrow profile package reaches into its parent `profile` package for types
and the key-field rule, through the parent's public API only.

`observed_shape` is not here: the column-shape sentry tracks its callers by the import from
`decoy_engine.profile`. Imported lazily by its callers, because the parent imports this package."""

from __future__ import annotations

from decoy_engine.profile import ColumnProfile, TableProfile, column_key_fields

__all__ = ["ColumnProfile", "TableProfile", "column_key_fields"]
