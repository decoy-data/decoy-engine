"""Runs the BASE (pre-S1b) profile walk for `support.base_profile` when pins are recorded.

Start it with `PYTHONPATH=<base checkout>/src`, so `decoy_engine` here is the merge base and
never the code under test. It samples the table with the base's own readers, then walks it. It reads pickled requests on stdin and answers with a JSON-ready
dict on stdout. Importing nothing from the tests keeps the two code trees apart.
"""

from __future__ import annotations

import dataclasses
import enum
import pickle
import random
import sys
from typing import Any

import pandas as pd


def _plain(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _profile_dict(profile: Any) -> dict[str, Any]:
    out = dataclasses.asdict(profile)
    out["columns"] = [{k: _plain(v) for k, v in c.items()} for c in out["columns"]]
    return out


def _base_sample(req: dict[str, Any]) -> tuple[Any, Any, int]:
    """(frame, shape schema, total rows) as the merge base's own readers gave them."""
    import io

    import pyarrow.parquet as pq

    rows = req["sample_rows"]
    table = req["table"]
    if req["kind"] == "resident":
        from decoy_engine.profile._readers_resident import _frame_of

        return _frame_of(table.slice(0, rows)), table.schema, table.num_rows
    from decoy_engine.profile._readers import head_frame_from_batches

    parquet = pq.ParquetFile(io.BytesIO(req["data"]))
    frame = head_frame_from_batches(parquet.iter_batches(rows), rows, parquet.schema_arrow)
    return frame, parquet.schema_arrow, parquet.metadata.num_rows


def main() -> None:
    from decoy_engine.profile._walk import walk_dataframe

    inp, out = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            req = pickle.load(inp)  # noqa: S301  (our own parent process)
        except EOFError:
            return
        try:
            flat = [x for kv in req["options"].items() for x in kv]
            with pd.option_context(*flat):
                frame, schema, total = _base_sample(req)
                profile = walk_dataframe(
                    frame,
                    table_name="t",
                    declared_pk_cols=req["declared_pk"],
                    fk_specs=req["fk_specs"],
                    sample_rows=req["sample_rows"],
                    rng=random.Random(0),
                    total_row_count=max(total, len(frame)),
                    arrow_schema=schema,
                    source_format=req["source_format"],
                )
            reply: dict[str, Any] = {
                "profile": _profile_dict(dataclasses.replace(profile, row_count_exact=True))
            }
        except Exception as exc:
            reply = {"raises": type(exc).__name__}
        pickle.dump(reply, out)
        out.flush()


if __name__ == "__main__":
    main()
