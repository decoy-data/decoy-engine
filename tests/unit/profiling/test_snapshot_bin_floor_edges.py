"""Plain fit numeric histograms on a decimal grid: released counts are the recount (row 24f).

`np.histogram` builds its edges with `linspace`, so a cell sitting on an edge of a 0.1 or 0.2 grid
can fall in the neighbouring bin compared with the exact Decimal edges the level search checks.
The last guard in `_top_coded_stats` rejects such a level instead of releasing numpy's counts.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import numpy as np
import pandas as pd

from decoy_engine.profiling import MIN_RELEASE_COUNT, distribution_snapshot_document
from decoy_engine.profiling import _snapshot_values as sv

# Rows per grid value -0.6, -0.5, ..., 0.4: the domain is (-0.6, 0.4) with 5 bins of width 0.2.
_GROUPS = [8, 4, 5, 5, 12, 8, 1, 12, 4, 8, 8]


def _frame() -> pd.DataFrame:
    cells = [round(-0.6 + 0.1 * i, 1) for i, n in enumerate(_GROUPS) for _ in range(n)]
    return pd.DataFrame({"x": cells})


def _plain_stats(df: pd.DataFrame) -> dict[str, Any]:
    with mock.patch.object(sv, "value_sensitive_names", return_value=[]):
        doc = json.loads(json.dumps(distribution_snapshot_document(df, numeric_bins=5)))
    return doc["columns"]["x"]["stats"]  # type: ignore[no-any-return]


def test_grid_cells_on_an_edge_release_the_exact_recount_with_no_small_bin() -> None:
    df = _frame()
    stats = _plain_stats(df)
    assert not any(s in stats for s in ("quantile_grid", "exact_values"))
    edges = stats["bin_edges"]
    recount = np.histogram(np.clip(df["x"].to_numpy(), edges[0], edges[-1]), bins=edges)[0]
    assert stats["bin_counts"] == recount.tolist()
    assert not any(0 < c < MIN_RELEASE_COUNT for c in stats["bin_counts"])
    assert sum(stats["bin_counts"]) == len(df)
