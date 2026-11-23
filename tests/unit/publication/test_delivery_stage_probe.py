"""The claim probe at `DeliveryStage.open` (DELIV E2b: AT-66, open half).

A run on a target that cannot hard-link, or that ignores `chmod`, fails at the start with
`publication_failed` and leaves no stage, before any writer has anything to lose.
"""

from __future__ import annotations

import errno
import os
import sys
from typing import Any

import pytest

from decoy_engine.publication import DeliveryStage, PublicationFailed
from tests.unit.publication._stage_support import Run, dir_at

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX stage claims")

UNSUPPORTED = [errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS, errno.EXDEV]
SECRET = "/secret/place"


@pytest.mark.parametrize("fault", [*UNSUPPORTED, "noop-chmod"])
def test_open_refuses_before_a_writer_can_run_and_leaves_no_stage(
    run: Run, monkeypatch: pytest.MonkeyPatch, fault: Any
) -> None:
    if fault == "noop-chmod":
        real = os.fchmod
        monkeypatch.setattr(
            os, "fchmod", lambda fd, mode: None if mode == 0o600 else real(fd, mode)
        )
    else:
        monkeypatch.setattr(os, "link", _always_fail(os.link, OSError(fault, SECRET)))
    (run.folder / "r1").mkdir()
    with pytest.raises(PublicationFailed) as caught:
        DeliveryStage.open(dir_at(run.base, "out/n/r1"), run.pointer, "r1", "op-1")
    assert caught.value.code == "publication_failed" and SECRET not in str(caught.value)
    assert caught.value.__context__ is None
    assert run.litter() == [] and list((run.folder / "r1").iterdir()) == []


def _always_fail(real: Any, error: BaseException) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        raise error

    return wrapper
