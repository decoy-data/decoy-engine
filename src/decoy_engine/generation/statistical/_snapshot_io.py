"""Parse step for statistical snapshot bytes, shared by every site that holds the bytes.

Value-free by construction: a refusal carries the typed position and, for a JSON syntax error,
the integer line and column, never file content or decoder text.
"""

from __future__ import annotations

import json
from typing import Any

from decoy_engine import reasons
from decoy_engine._config_text import Name, Refusal, config_position, read_config


def parse_snapshot_json(raw: bytes, *, shown: str) -> Any:
    """Parse snapshot bytes as JSON or raise `StatisticalSpecError` (unreadable).

    `shown` names where the bytes came from (a config position such as
    ``generation.snapshots[0]``); it is displayed only when it is an approved name. The decode
    errors hold the file (`UnicodeDecodeError.object`, `JSONDecodeError.doc`), so `read_config`
    reads only the integer line and column, and the refusal has no cause or context.
    """
    # Function-local: `_spec` imports this module, and its error class must finish defining first.
    from decoy_engine.generation.statistical._spec import StatisticalSpecError

    def _refuse(refusal: Refusal) -> StatisticalSpecError:
        return StatisticalSpecError(
            code=reasons.plan.STATISTICAL_SNAPSHOT_UNREADABLE, message=refusal.text
        )

    return read_config(lambda: json.loads(raw), config_position(Name(shown)), _refuse)
