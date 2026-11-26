"""The shared scratch-env fixture for the execution tests that patch `tempfile.tempdir`."""

from __future__ import annotations

from tests._scratch_env import scratch_env_clean  # noqa: F401 - registers the fixture
