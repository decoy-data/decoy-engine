"""Parse step for statistical snapshot bytes, shared by every site that holds the bytes.

Value-free by construction: a refusal carries the typed position and, for a JSON syntax error,
the integer line and column, never file content or decoder text.
"""

from __future__ import annotations

import json
from typing import Any

from decoy_engine import reasons
from decoy_engine._config_text import ConfigPosition, Refusal, read_config


def parse_snapshot_json(raw: bytes, *, at: ConfigPosition) -> Any:
    """Parse snapshot bytes as JSON or raise `StatisticalSpecError` (unreadable).

    `at` is where the bytes came from, a typed position (rooted for a complete key such as
    ``generation.snapshots[0]``, relative for a field under the active column). The decode
    errors hold the file (`UnicodeDecodeError.object`, `JSONDecodeError.doc`), so `read_config`
    reads only the integer line and column, and the refusal has no cause or context.
    """
    # Function-local: `_spec` imports this module, and its error class must finish defining first.
    from decoy_engine.generation.statistical._spec import StatisticalSpecError

    def _refuse(refusal: Refusal) -> StatisticalSpecError:
        return StatisticalSpecError(
            code=reasons.plan.STATISTICAL_SNAPSHOT_UNREADABLE, message=refusal.text
        )

    return read_config(lambda: json.loads(raw), at, _refuse)
