"""The subprocess environment both determinism tools give their workers.

One copy, standard library only: it must stay free of any `decoy_engine` import so a driver can
build a worker environment before an engine module loads (AT-L14 guards both properties).
"""

from __future__ import annotations

from pathlib import Path


def worker_env(root: Path, hash_seed: int, commit: str) -> dict[str, str]:
    """Explicit, minimal environment: nothing leaks in from the caller's shell."""
    return {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONPATH": str(root / "src"),
        "PYTHONHASHSEED": str(hash_seed),
        "TZ": "UTC",
        "LC_ALL": "C",
        "LANG": "C",
        "DECOY_ENGINE_COMMIT": commit,
    }
