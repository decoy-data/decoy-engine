"""WHEN-READS-SOURCE W1: column names and order never change which rows a `when:` selects.

A gated column and the column its predicate reads are named so that the read column sorts
before or after the gated one (`aa_` and `zz_`), so an earlier-masks-later order is exercised in
both directions. The rows selected are the rows whose SOURCE read value matches, whatever the
names, strategies and values.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.native._chunked_entry_support import TABLE, hash_col, make_config, redact
from tests.unit.execution._when_reads_source_support import NS, changed_rows, run_full_frame

_VALUES = ["a", "b", "c"]
_NAMES = {"before": ("aa_read", "mm_gated"), "after": ("zz_read", "mm_gated")}


@settings(
    max_examples=25,
    deadline=None,
    database=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    order=st.sampled_from(sorted(_NAMES)),
    read_strategy=st.sampled_from(["hash", "redact"]),
    gated_strategy=st.sampled_from(["hash", "redact"]),
    values=st.lists(st.sampled_from(_VALUES), min_size=1, max_size=30),
    wanted=st.sampled_from(_VALUES),
)
def test_selected_rows_follow_the_source_value_whatever_the_names(
    tmp_path_factory,
    order: str,
    read_strategy: str,
    gated_strategy: str,
    values: list[str],
    wanted: str,
) -> None:
    read, gated = _NAMES[order]
    tmp = Path(tmp_path_factory.mktemp("w1"))
    source = pa.table(
        {
            read: pa.array(values, pa.string()),
            gated: pa.array([f"original-{i}" for i in range(len(values))], pa.string()),
        }
    )
    earlier = hash_col(read, NS) if read_strategy == "hash" else redact(read)
    target = hash_col(gated, NS) if gated_strategy == "hash" else redact(gated)
    config = make_config([earlier, {**target, "when": f"{read} == '{wanted}'"}])
    out = run_full_frame(config, source, tmp).outputs[TABLE]
    assert changed_rows(out, source, gated) == [v == wanted for v in values]
