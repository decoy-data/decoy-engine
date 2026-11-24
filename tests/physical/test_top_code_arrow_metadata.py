"""Handler and kernel agree on a double column that keeps int64[pyarrow] pandas metadata."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa

from decoy_engine.kernel import top_code_array
from tests._column_shapes import INT_DECL
from tests.physical._shadow_helpers import build_config, write_read_only_fixture
from tests.physical.test_shadow_full_frame import (
    _build_ctx,
    _capture,
    _direct_full_frame_result,
)


def test_full_frame_double_with_int64_arrow_metadata_matches_the_kernel(tmp_path: Path) -> None:
    metadata = pa.Table.from_pandas(
        pd.DataFrame({"n": pd.Series([-1, None, 95], dtype="int64[pyarrow]")})
    ).schema.metadata
    values = pa.array([-1.0, None, 95.0], pa.float64())
    source = pa.table({"n": values}).replace_schema_metadata(metadata)
    columns = [
        {
            "name": "n",
            "strategy": "top_code",
            "provider_config": {"cap": 89, "over_label": "over"},
            **INT_DECL,
        }
    ]
    path = write_read_only_fixture(tmp_path, source, "t")
    config = build_config(tmp_path, "t", path, columns)
    sources = {"t": source}
    inputs, _ = _capture(config, sources)
    result = _direct_full_frame_result(inputs, sources, _build_ctx(inputs, config))

    handler_cells = result.outputs["t"].column("n").to_pylist()
    kernel = top_code_array(values, 89, "over")
    assert handler_cells == kernel.labels.to_pylist() == ["-1", None, "over"]
    assert [(w.detail["over_count"], w.detail["under_count"]) for w in result.warnings] == [
        (kernel.over_count, kernel.under_count)
    ]
