"""Cases shared by both repos' ratchet meta-tests.

``MAX_VALUE_CASES``: ``(name, base max, head max, red)``; ``None`` means the entry carries no
``max``. ``BASELINE_PATH_CASES``: ``(name, registry baseline path, safe)``; a safe path is a plain
relative path with at least one component below ``tests/sentry/baselines``. Both repos
parametrize their ratchet meta-tests from these tables; the file is vendored byte for byte
and pinned by ``test_vendored_files.py``.
"""

from __future__ import annotations

MAX_VALUE_CASES: tuple[tuple[str, int | None, int | None, bool], ...] = (
    ("no max on either side", None, None, False),
    ("max added", None, 5, False),
    ("max dropped", 5, None, True),
    ("equal", 5, 5, False),
    ("lower", 5, 4, False),
    ("higher", 5, 6, True),
)

BASELINE_PATH_CASES: tuple[tuple[str, str, bool], ...] = (
    ("plain file", "tests/sentry/baselines/a.json", True),
    ("nested file", "tests/sentry/baselines/sub/a.json", True),
    ("dotdot out of the directory", "tests/sentry/baselines/../../src/x.json", False),
    ("dotdot that stays inside", "tests/sentry/baselines/sub/../a.json", False),
    ("backslash separator", "tests/sentry/baselines/a\\b.json", False),
    ("absolute path", "/tests/sentry/baselines/a.json", False),
    ("sibling directory with the same prefix", "tests/sentry/baselines-old/a.json", False),
    ("file outside the directory", "docs/example.json", False),
    ("directory itself", "tests/sentry/baselines", False),
    ("trailing slash only", "tests/sentry/baselines/", False),
    ("dot segment", "tests/sentry/baselines/./a.json", False),
    ("doubled slash", "tests/sentry/baselines//a.json", False),
    ("empty", "", False),
)
