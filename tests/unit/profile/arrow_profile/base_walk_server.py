"""Runs the BASE (pre-S1b) profile walk for `support.base_profile` when pins are recorded.

Start it with `PYTHONPATH=<base checkout>/src`, so `decoy_engine` here is the merge base and
never the code under test. It reads pickled requests on stdin and answers with a JSON-ready
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
                profile = walk_dataframe(
                    req["frame"],
                    table_name="t",
                    declared_pk_cols=req["declared_pk"],
                    fk_specs=req["fk_specs"],
                    sample_rows=req["sample_rows"],
                    rng=random.Random(0),
                    total_row_count=max(req["total"], len(req["frame"])),
                    arrow_schema=req["schema"],
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
