"""The one place the Arrow profile package reaches into its parent `profile` package for types
and the key-field rule. Moving a parent-private one changes this file only.

`observed_shape` is not here: the column-shape sentry tracks its callers by the import from
`profile._walk`. Imported lazily by its callers, because the parent imports this package."""

from __future__ import annotations

from decoy_engine.profile._types import ColumnProfile, TableProfile, column_key_fields

__all__ = ["ColumnProfile", "TableProfile", "column_key_fields"]
