"""Profile construction for `_chunked.run_mask_pipeline_chunked`.

Extracted from `_chunked.py` to keep that module under the orchestration LOC
cap (`tests/sentry/test_module_size.py`); both functions here are
self-contained Profile builders with no state shared with the rest of
`_chunked.py` beyond their return value.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection
from datetime import datetime
from typing import Any

import pyarrow as pa

from decoy_engine.internal.pandas_compat import table_to_pandas
from decoy_engine.profile.arrow import arrow_column_profile


def profile_input(first_chunk: pa.Table, carried: Collection[str] = frozenset()) -> pa.Table:
    """The table the pandas profile walk sees: each carried passthrough column is
    replaced, in place and under the same name, by an all-null column, so its real
    values never reach pandas (rule R3)."""
    for name in carried:
        if name in first_chunk.column_names:
            index = first_chunk.schema.get_field_index(name)
            first_chunk = first_chunk.set_column(index, name, pa.nulls(first_chunk.num_rows))
    return first_chunk


def walk_one_table(table: pa.Table, *, table_name: str, source_format: str | None = None) -> Any:
    """The pandas half of the first-chunk profile: one conversion and one walk. The table's own
    schema gives each column its shape, and `source_format` (the descriptor's, so a csv column
    stays text whatever the chunk reader inferred) makes it agree with the full-frame profile."""
    import random

    from decoy_engine.profile._walk import walk_dataframe

    return walk_dataframe(
        table_to_pandas(table),
        table_name=table_name,
        declared_pk_cols=frozenset(),
        fk_specs={},
        sample_rows=None,
        rng=random.Random(0),
        arrow_schema=table.schema,
        source_format=source_format,
    )


def _as_chunk_sample(table_profile: Any) -> Any:
    """Label every column of a first-chunk table as a sample.

    The chunk is the head of a larger source, so its counts are not whole-source
    counts and none of its columns may claim to be a key. Runs last, so columns
    rebuilt from Arrow for carried passthrough names are covered too."""
    return dataclasses.replace(
        table_profile,
        columns=tuple(
            dataclasses.replace(c, sampled=True, is_candidate_key_sampled=False)
            for c in table_profile.columns
        ),
    )


def first_chunk_profile(
    first_chunk: pa.Table,
    *,
    table: str,
    engine_version: str,
    carried: Collection[str] = frozenset(),
    source_format: str | None = None,
) -> Any:
    """Profile the FIRST chunk so compile_plan can build the seed envelope.

    The envelope iterates `profile.tables` (the table must exist there
    for its columns to mask at all), so a fully-empty --no-profile-style
    Profile silently masks nothing. The first chunk gives real dtypes;
    distinct counts and row_count describe only that chunk, which is
    fine -- admitted strategies consume nothing distribution-dependent.
    `row_count` is the chunk length, not the source's, and `row_count_exact`
    stays True because `execution/capacity.py` reads it; every column is
    labelled `sampled` with no candidate-key flag (`_as_chunk_sample`). No route
    serializes this profile.
    Faker pools size from the config-declared pool_size (the admission
    rule requires it explicitly), never from profile distinct counts,
    and the pool-capacity pre-flight lands in checks_skipped under
    no_profile=True, which is correct here: with admission restricted
    to deterministic REUSE, pool capacity is a collision-rate knob, not
    a correctness input. Epoch `profiled_at` keeps the 'not a real
    source profile' sentinel from the --no-profile path.

    `carried` names passthrough columns that must never enter pandas
    (`run_mask_chunked`, rule R3): the walk sees them as all-null columns, then
    each one's `ColumnProfile` is replaced by `arrow_column_profile`, computed
    from the real Arrow column, so the profile equals the full pandas one."""
    from decoy_engine.profile import Profile

    table_profile = walk_one_table(
        profile_input(first_chunk, carried), table_name=table, source_format=source_format
    )
    if carried:
        real = {
            name: arrow_column_profile(name, first_chunk.column(name), source_format=source_format)
            for name in carried
            if name in first_chunk.column_names
        }
        table_profile = dataclasses.replace(
            table_profile,
            columns=tuple(real.get(c.name, c) for c in table_profile.columns),
        )
    return Profile(
        schema_version=1,
        tables=(_as_chunk_sample(table_profile),),
        relationships=(),
        profiled_at=datetime(1970, 1, 1, 0, 0, 0),
        decoy_engine_version=engine_version,
        profile_seed=None,
    )


def empty_input_profile(
    config: dict[str, Any],
    *,
    table: str,
    engine_version: str,
    source_schema: pa.Schema | None = None,
    source_format: str | None = None,
) -> Any:
    """Placeholder Profile for a chunked source with ZERO chunks (no data at all).

    There is no real chunk to derive dtypes from, so this profiles an EMPTY
    frame built from the config's DECLARED column names only (object dtype
    placeholder). That is enough to `compile_plan(..., no_profile=True)` and
    run the DE-02 fail-closed gate (`require_mask_key`) before the
    empty-input short-circuit returns (Codex-found: the gate was skippable
    by handing a keyed job zero rows/batches). `no_profile=True` already
    treats profile-derived dtype/null-count checks as unreliable and skips
    them (see `check_null_bearing_int_unsupported`), so a placeholder here
    goes through the exact same classification path
    (`keyprovider.plan_has_keyed_strategy`) a real chunk would -- no
    duplicated keyed-strategy logic, and no behavior change to the non-empty
    path.

    `source_schema` is the schema the entry was given for this source. When there is one, the
    empty frame takes its columns and types from it, so a typed zero-chunk input gets the shapes
    a non-empty one would. A config column the schema lacks stays an object placeholder. An
    arbitrary iterable has no schema, so its columns stay `unknown`.
    """
    import random

    import pandas as pd

    from decoy_engine.profile import Profile
    from decoy_engine.profile._walk import walk_dataframe

    tables = config.get("tables") or []
    table_cfg = next((t for t in tables if isinstance(t, dict) and t.get("name") == table), None)
    columns = [
        col.get("name")
        for col in ((table_cfg or {}).get("columns") or [])
        if isinstance(col, dict) and col.get("name")
    ]
    empty_df = pd.DataFrame({name: pd.Series([], dtype="object") for name in columns})
    if source_schema is not None:
        typed = table_to_pandas(source_schema.empty_table())
        for name in columns:
            if name not in typed.columns:
                typed[name] = pd.Series([], dtype="object")
        empty_df = typed
    table_profile = walk_dataframe(
        empty_df,
        table_name=table,
        declared_pk_cols=frozenset(),
        fk_specs={},
        sample_rows=None,
        rng=random.Random(0),
        arrow_schema=source_schema,
        source_format=source_format,
    )
    return Profile(
        schema_version=1,
        tables=(table_profile,),
        relationships=(),
        profiled_at=datetime(1970, 1, 1, 0, 0, 0),
        decoy_engine_version=engine_version,
        profile_seed=None,
    )


__all__ = [
    "empty_input_profile",
    "first_chunk_profile",
    "profile_input",
    "walk_one_table",
]
