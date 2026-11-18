"""AT-E12: the no-follow open reports why it refused, as one closed value-free word.

``FileAccessDenied.kind`` is ``None`` for every denial that does not come from a no-follow open,
and one of ``absent``, ``link``, ``not_regular`` or ``unreadable`` for one that does. The message
(`str()`) never changes, so no existing denial test sees the attribute.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import pytest

from decoy_engine import fileaccess
from decoy_engine.fileaccess import FileAccessDenied, _openat2
from decoy_engine.fileaccess._errors import deny, scrub

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX file semantics")


@pytest.fixture(params=["kernel", "portable"])
def tree(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if request.param == "portable":
        monkeypatch.setattr(_openat2, "FORCE_PORTABLE", True)
    elif not _openat2.usable():
        pytest.skip("openat2 is not available here")
    (tmp_path / "file").write_text("x")
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "inner").write_text("y")
    (tmp_path / "link").symlink_to(tmp_path / "file")
    (tmp_path / "linkdir").symlink_to(tmp_path / "dir", target_is_directory=True)
    os.mkfifo(tmp_path / "fifo")
    with fileaccess.open_ambient_tree(tmp_path) as handle:
        yield handle


def _kind(call, *args: str) -> str | None:  # type: ignore[no-untyped-def]
    try:
        call(*args)
    except FileAccessDenied as denial:
        kind = denial.kind
    else:
        pytest.fail("expected a denial")
    return kind


def test_a_missing_name_is_absent(tree) -> None:  # type: ignore[no-untyped-def]
    assert _kind(tree.open_file, "nope") == "absent"
    assert _kind(tree.open_file, "dir/nope") == "absent"


def test_a_symlink_is_a_link(tree) -> None:  # type: ignore[no-untyped-def]
    assert _kind(tree.open_file, "link") == "link"


def test_a_symlinked_intermediate_directory_is_a_link(tree) -> None:  # type: ignore[no-untyped-def]
    assert _kind(tree.open_file, "linkdir/inner") == "link"


def test_a_symlinked_directory_request_is_refused_as_a_link_or_not_a_directory(tree) -> None:  # type: ignore[no-untyped-def]
    # openat2 reports ELOOP (link); the portable descriptor walk reports ENOTDIR on Linux.
    assert _kind(tree.open_dir, "linkdir") in {"link", "not_regular"}


def test_a_fifo_and_a_directory_are_not_regular(tree) -> None:  # type: ignore[no-untyped-def]
    assert _kind(tree.open_file, "fifo") == "not_regular"
    assert _kind(tree.open_file, "dir") == "not_regular"


def test_enotdir_is_link_for_a_file_request_or_a_separator_and_not_regular_otherwise(tree) -> None:  # type: ignore[no-untyped-def]
    assert _kind(tree.open_dir, "file") == "not_regular"
    assert _kind(tree.open_dir, "file/sub") == "link"
    assert _kind(tree.open_file, "file/sub") == "link"


def test_str_is_what_it_was_without_a_kind(tree) -> None:  # type: ignore[no-untyped-def]
    try:
        tree.open_file("nope")
    except FileAccessDenied as denial:
        assert str(denial) == f"file access denied: {denial.field_key}"
        assert "nope" not in str(denial)
        assert denial.__cause__ is None and denial.__context__ is None
    else:
        pytest.fail("expected a denial")


def test_a_plain_denial_has_no_kind() -> None:
    assert deny("some key").kind is None
    assert FileAccessDenied("some key").kind is None


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        FileAccessDenied("k", kind="whatever")  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["absent", "link", "not_regular", "unreadable", None])
def test_a_kind_survives_pickle_and_scrub(kind) -> None:  # type: ignore[no-untyped-def]
    denial = deny("a key", kind=kind)
    clone = pickle.loads(pickle.dumps(denial))  # noqa: S301 -- own round trip
    assert clone.kind == kind and str(clone) == str(denial)
    scrubbed = scrub(RuntimeError("outer"))
    assert scrubbed is not None
    try:
        raise RuntimeError("outer") from denial
    except RuntimeError as outer:
        fresh = scrub(outer)
    assert isinstance(fresh, FileAccessDenied) and fresh.kind == kind


def test_the_root_open_reports_absent_and_not_a_directory(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    assert _kind(fileaccess.open_ambient_tree, str(tmp_path / "missing")) == "absent"
    assert _kind(fileaccess.open_ambient_tree, str(tmp_path / "f")) == "not_regular"
