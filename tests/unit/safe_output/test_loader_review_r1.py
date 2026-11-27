"""Codex R1 findings 2 to 5: each canary shows on no surface a caller can read.

2. A mistyped `condition_on` is refused as mistyped even when the snapshot also withheld values.
3. A strict pinned read rebuilds a memory failure and a disk failure alike.
4. A malformed column name is never rendered by the spec's own decoders.
5. `verify_corpus` redacts a credential in the report's display path.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine import fileaccess
from decoy_engine.generation.statistical import StatisticalSpecError, load_spec
from decoy_engine.plan import _generation
from decoy_engine.profiling._value_redaction import (
    POLICY_REDACTED,
    REDACTED_COLUMNS_KEY,
    VALUE_POLICY_KEY,
)
from decoy_engine.quality.snapshot import compute_distribution_snapshot
from decoy_engine.transforms._codeset_loader import verify_corpus
from tests.unit.safe_output.test_loader_outcomes_value_free import _surfaces, _world

_COL = {
    "name": "a",
    "type": "statistical",
    "snapshot_file": "s.json",
    "allow_real_categories": True,
}


def _snapshot(values: list[object]) -> dict[str, object]:
    snap = compute_distribution_snapshot(pd.DataFrame({"a": values}))
    return json.loads(json.dumps(snap))


def test_mistyped_condition_on_beats_the_withheld_values_refusal() -> None:
    snap = _snapshot(["x", "y", "z"])
    snap[VALUE_POLICY_KEY] = POLICY_REDACTED
    snap[REDACTED_COLUMNS_KEY] = ["a"]
    # Proves the fixture reaches the withheld refusal when the request is well formed.
    with pytest.raises(StatisticalSpecError) as withheld:
        load_spec({**_COL, "condition_on": "a"}, snapshot=snap)
    assert withheld.value.code == "statistical_snapshot_values_redacted"
    with pytest.raises(StatisticalSpecError) as exc:
        load_spec({**_COL, "condition_on": ["PRIVATE_RELEASE"]}, snapshot=snap)
    assert exc.value.code == "statistical_joint_missing"
    assert "condition_on" in str(exc.value)
    assert "got list" in str(exc.value)
    assert "PRIVATE_RELEASE" not in "".join(_surfaces(exc.value))


def _strict_pinned(
    error: BaseException, monkeypatch: pytest.MonkeyPatch, root: Path
) -> BaseException:
    from tests.fileaccess.support import RootRelative

    def boom(*_a: object, **_k: object) -> object:
        raise error

    monkeypatch.setattr(_generation.fileaccess, "read_all", boom)
    policy = RootRelative(root)
    try:
        with fileaccess.scope(policy), pytest.raises(BaseException) as info:
            _generation.read_pinned_artifact(
                fileaccess.FileRole.SNAPSHOT, "s.json", "snapshot_file", None, 1024
            )
    finally:
        policy.close()
    return info.value


def test_strict_pinned_read_rebuilds_a_memory_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for error in (
        MemoryError("MEMORY_CANARY"),
        pa.ArrowException("Unknown error: Wrapping MEMORY_CANARY failed"),
    ):
        raised = _strict_pinned(error, monkeypatch, root)
        assert fileaccess.is_memory_failure(raised)
        assert str(raised) == fileaccess.MEMORY_TEXT
        assert "MEMORY_CANARY" not in "".join(_surfaces(raised))


def test_strict_pinned_read_rebuilds_a_disk_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    raised = _strict_pinned(
        OSError(errno.ENOSPC, "No space left on device", "DISK_CANARY"), monkeypatch, root
    )
    assert isinstance(raised, OSError) and raised.errno == errno.ENOSPC
    assert "DISK_CANARY" not in "".join(_surfaces(raised))


def test_spec_decoders_do_not_render_a_malformed_name() -> None:
    cfg = {**_COL, "name": ["NAME_CANARY"], "source_column": "a"}
    cell = _snapshot(["x", "y", "z"])
    cell["columns"]["a"]["cell_format"] = False  # type: ignore[index]
    with pytest.raises(StatisticalSpecError) as bad_cell:
        load_spec(cfg, snapshot=cell)
    assert bad_cell.value.code == "statistical_cell_format_invalid"
    shape = _snapshot([1.0, 2.0, 3.0, 4.0])
    stats = shape["columns"]["a"]["stats"]  # type: ignore[index]
    stats["quantile_grid"] = {"probs": [0.0, 1.0], "values": [1.0, 4.0]}
    stats["exact_values"] = {"values": [1.0], "counts": [1], "dropped_count": 0}
    with pytest.raises(StatisticalSpecError) as bad_shape:
        load_spec(cfg, snapshot=shape)
    assert bad_shape.value.code == "statistical_stats_degenerate"
    for exc in (bad_cell.value, bad_shape.value):
        assert "NAME_CANARY" not in "".join(_surfaces(exc))
    # An ordinary name is still shown, so the message keeps saying which column failed.
    with pytest.raises(StatisticalSpecError) as named:
        load_spec({**cfg, "name": "age"}, snapshot=cell)
    assert "age" in str(named.value)


def test_verify_corpus_report_path_redacts_credentials() -> None:
    with _world(False) as root:
        secret = root / "https:" / "user:PATH_CANARY@host"
        secret.mkdir(parents=True)
        absent = verify_corpus(secret / "c.parquet")
        query = verify_corpus(root / "c.parquet?token=PATH_CANARY")
        plain = verify_corpus(root / "plain.parquet")
    for report in (absent, query):
        assert report.ok is False
        assert "PATH_CANARY" not in "".join(_surfaces(report))
    assert plain.ok is False
    assert plain.path.endswith("plain.parquet")


def test_verify_corpus_report_path_is_the_position_under_a_strict_policy(tmp_path: Path) -> None:
    from decoy_engine.transforms._codeset_loader import _display_path

    with _world(True) as root:
        shown = _display_path(root / "https:" / "user:PATH_CANARY@host" / "c.parquet")
    assert "PATH_CANARY" not in shown
    assert "c.parquet" not in shown
