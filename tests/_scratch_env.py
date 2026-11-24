"""One shared fixture for tests that redirect scratch by setting `tempfile.tempdir`.

`scratch_root()` reads TMPDIR, TEMP and TMP before `tempfile.gettempdir()`, so a runner that
exports TMPDIR would win over the patched `tempfile.tempdir`. A test that patches the cache
asks for `scratch_env_clean` so the patched value is the one the product sees. Conftests in
the narrow directories that need it import the fixture; there is no global autouse.
"""

from __future__ import annotations

import pytest

SCRATCH_ENV_VARS = ("TMPDIR", "TEMP", "TMP")


@pytest.fixture
def scratch_env_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SCRATCH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
