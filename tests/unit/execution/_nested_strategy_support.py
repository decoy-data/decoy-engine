"""Shared stand-ins for the nested strategy handler tests."""

from __future__ import annotations

from decoy_engine.plan._types import ColumnSeed

_JOB_SEED = b"\xca\xfe" * 4  # 8 bytes


def _seed(provider_config: dict, namespace: str | None = None) -> ColumnSeed:
    return ColumnSeed(
        namespace=namespace,
        strategy="nested",
        provider=None,
        backend_type="decoy_native",
        backend_version="1",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(sorted(provider_config.items())),
    )


class _FakeCtx:
    def __init__(self) -> None:
        # Real StrategyContext carries a `row_errors` list; the malformed-cell
        # fail-closed path appends to it, so the stand-in needs one too.
        self.row_errors: list = []
        # A seeded categorical child reads the mask key and the row offset.
        self.job_seed = _JOB_SEED
        self.mask_key = _JOB_SEED
        self.row_offset = 0
