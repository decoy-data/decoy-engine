"""Detector ids that fire only on a column-name hint.

Each of these detectors returns None unless the column name carries a hint, because its value
regex is too loose to use alone (``mrn`` matches any 4 to 20 character alphanumeric token, so
the constant ``REDACTED`` matches). A hit on one of them after a mask that replaces whole cells
says little about the output, so residual-PII grading reads the source comparison instead.

The set is kept equal to the detector code by
``tests/sentry/defects/test_hint_gated_registry.py``, which parses ``builtin.py``.
"""

from __future__ import annotations

NAME_HINT_GATED_DETECTORS: frozenset[str] = frozenset(
    {
        "address",
        "biometric_id",
        "cvv",
        "device_id",
        "fax_number",
        "first_name",
        "health_plan_id",
        "last_name",
        "license_num",
        "mrn",
        "person_name",
    }
)
