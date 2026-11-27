"""Unit tests for decoy_engine.internal.crypto."""

from __future__ import annotations

import warnings

from decoy_engine.internal.crypto import hmac_hex


class TestHmacHexIsClean:
    def test_hmac_hex_does_not_emit_deprecation_warning(self):
        """Sanity check: the preferred replacement is clean."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            hmac_hex(b"key" * 11, "value-x")
        depr_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert depr_warnings == [], (
            f"QA-internal F12: hmac_hex should not emit DeprecationWarning. "
            f"Got: {[str(w.message) for w in depr_warnings]}"
        )
