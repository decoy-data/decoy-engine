"""DELIV E2f (AT-56, AT-58, AT-60): `publish_unit(members=...)` and the closed stage.

Units are staged by hand through the stage capability, so a stray entry, a link or a FIFO can be
planted before the call. Every refusal is a receipt (`failed`), never a bound unit.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.unit.publication._publish_support import (
    POLICIES,
    close_root,
    descriptor,
    make_out,
    stages_left,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX publication")


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


def _write(txn: Any, path: str, data: bytes) -> None:
    parts = path.split("/")
    stage = txn
    for part in parts[:-1]:
        stage = stage.create_dir(part)
    fd = stage.create_file(parts[-1])
    os.write(fd, data)
    os.close(fd)


def _parquet(rows: int) -> bytes:
    import io

    import pyarrow as pa
    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(pa.table({"id": list(range(rows))}), buf)
    return buf.getvalue()


def _stage_five(out: Any) -> Any:
    txn = out.begin("dir", "exclusive", label="publication")
    txn_dirs: dict[str, Any] = {}
    for sub in ("masked", "quarantine"):
        txn_dirs[sub] = txn.create_dir(sub)
    for stage, name, data in (
        (txn_dirs["masked"], "customers.csv", b"id\n1\n"),
        (txn, "orders.parquet", _parquet(3)),
        (txn_dirs["quarantine"], "rows.jsonl", b'{"a":1}\n'),
        (txn, "report.json", b"{}"),
        (txn, "empty.csv", b""),
    ):
        fd = stage.create_file(name)
        os.write(fd, data)
        os.close(fd)
    return txn


FIVE = [
    ("empty.csv", "table"),
    ("masked/customers.csv", "table"),
    ("orders.parquet", "table"),
    ("quarantine/rows.jsonl", "quarantine"),
    ("report.json", "report"),
]


def _members() -> list[Any]:
    from decoy_engine.publication import Member

    return [Member(p, r) for p, r in FIVE]  # type: ignore[arg-type]


@pytest.mark.parametrize("policy", POLICIES)
def test_at56_five_members_nested_and_empty(base: Path, policy: str) -> None:
    from decoy_engine.publication import PublicationRequest, publish_unit

    out, root_fd = make_out(policy, base, "unit")
    try:
        receipt = publish_unit(
            out, _stage_five(out), PublicationRequest("op-1"), members=_members()
        )
        assert receipt.outcome == "published", receipt
        leaf = base / "unit"
        doc = descriptor(leaf)
        listed = doc["artifacts"]
        assert [(a["path"], a["role"]) for a in listed] == FIVE
        assert [a["rows"] for a in listed] == [None, None, 3, None, None]
        for art in listed:
            data = (leaf / art["path"]).read_bytes()
            assert art["size"] == len(data)
            assert art["sha256"] == hashlib.sha256(data).hexdigest()
        assert listed[0]["sha256"] == hashlib.sha256(b"").hexdigest() and listed[0]["size"] == 0
        # result_id is stable across two runs of the same content
        out2, fd2 = make_out(policy, base, "unit2")
        try:
            again = publish_unit(
                out2, _stage_five(out2), PublicationRequest("op-2"), members=_members()
            )
            assert again.result_id == receipt.result_id
        finally:
            close_root(fd2)
    finally:
        close_root(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
def test_at58_parquet_only_unit_matches_tables_form(base: Path, policy: str) -> None:
    """`tables=` and `members=` of the same Parquet files bind the same bytes and `rows`."""
    from decoy_engine.publication import Member, PublicationRequest, publish_unit

    results = []
    for name, kwargs in (
        ("one", {"tables": ["t.parquet"]}),
        ("two", {"members": [Member("t.parquet", "table")]}),
    ):
        out, root_fd = make_out(policy, base, name)
        try:
            txn = out.begin("dir", "exclusive", label="publication")
            _write(txn, "t.parquet", _parquet(2))
            receipt = publish_unit(out, txn, PublicationRequest("op-1"), **kwargs)
            assert receipt.outcome == "published"
            results.append(descriptor(base / name)["artifacts"])
        finally:
            close_root(root_fd)
    assert results[0] == results[1]
    assert results[0][0]["rows"] == 2 and results[0][0]["role"] == "table"


def _plant(plant: str, stage: str) -> None:
    """Put one entry the declared members do not name straight into the stage directory."""
    if plant == "stray_file":
        Path(stage, "stray.txt").write_bytes(b"s")
    elif plant == "empty_dir":
        os.mkdir(os.path.join(stage, "extra"))
    elif plant == "symlink":
        os.symlink("/etc/hostname", os.path.join(stage, "link"))
    elif plant == "fifo":
        os.mkfifo(os.path.join(stage, "fifo"))
    elif plant == "dir_for_file":
        os.unlink(os.path.join(stage, "orders.parquet"))
        os.mkdir(os.path.join(stage, "orders.parquet"))
    elif plant == "stray_in_nested":
        Path(stage, "a", "inner.txt").write_bytes(b"s")
    elif plant == "link_for_file":
        os.unlink(os.path.join(stage, "a", "t.csv"))
        os.symlink("/etc/hostname", os.path.join(stage, "a", "t.csv"))
    else:  # link_for_folder
        os.rename(os.path.join(stage, "a"), os.path.join(stage, "real"))
        os.symlink("real", os.path.join(stage, "a"))


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize(
    "plant",
    [
        "stray_file",
        "empty_dir",
        "symlink",
        "fifo",
        "dir_for_file",
        "stray_in_nested",
        "link_for_file",
        "link_for_folder",
    ],
)
def test_at60_closed_stage_refuses_before_bind(base: Path, policy: str, plant: str) -> None:
    from decoy_engine.publication import Member, PublicationRequest, publish_unit

    out, root_fd = make_out(policy, base, "unit")
    try:
        txn = out.begin("dir", "exclusive", label="publication")
        _write(txn, "a/t.csv", b"x\n")
        _write(txn, "orders.parquet", _parquet(1))
        (stage,) = stages_left(base)
        _plant(plant, str(base / stage))
        members = [Member("a/t.csv", "table"), Member("orders.parquet", "table")]
        receipt = publish_unit(out, txn, PublicationRequest("op-1"), members=members)
        assert receipt.outcome == "failed"
        assert receipt.reason_code is not None and "publication_failed" in receipt.reason_code
        assert not (base / "unit").exists()
        assert stages_left(base) == []
    finally:
        close_root(root_fd)


@pytest.mark.parametrize("policy", POLICIES)
def test_both_forms_and_bad_units_refuse_before_any_read(base: Path, policy: str) -> None:
    from decoy_engine.publication import Member, PublicationRequest, publish_unit

    out, root_fd = make_out(policy, base, "unit")
    try:
        cases: list[dict[str, Any]] = [
            {"tables": ["a.parquet"], "members": [Member("b.csv", "table")]},
            {"members": ["b.csv"]},
            {"members": [Member("a", "table"), Member("a/b.csv", "table")]},
            {"members": [Member("a.csv", "table"), Member("a.csv", "table")]},
            {"tables": ["a.parquet", "a.parquet"]},
        ]
        for kwargs in cases:
            txn = out.begin("dir", "exclusive", label="publication")
            with pytest.raises(ValueError) as caught:
                publish_unit(out, txn, PublicationRequest("op-1"), **kwargs)
            assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert stages_left(base) == []
    finally:
        close_root(root_fd)
