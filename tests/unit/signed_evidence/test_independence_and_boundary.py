"""The low-level ES256 check stays private.

OQ-4 (docs/plans/2026-11-17-f33-v1.md) folded the verifier into the engine, so the standalone
contract this file used to hold (a dependency-light core importable without the engine) is retired.
The engine layer placement and the alias-aware import walk in ``test_layer_placement.py`` replace it.
"""

from __future__ import annotations


def test_low_level_jws_verify_is_not_public() -> None:
    import decoy_engine.signed_evidence as se

    for name in dir(se):
        assert "verify_es256" not in name and name not in {"verify_signature", "jws_verify"}
    assert "verify_signed_evidence" in se.__all__
