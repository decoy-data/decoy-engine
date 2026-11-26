"""The environment fingerprint, shared by the map build and the selector.

A map is only evidence for a host that runs the same code paths. The fields below decide that:
platform, Python minor, the lock file, the installed distributions, the native companion and the
env vars that gate skips. The build and the selector both call `fingerprint()`; a second
implementation would let the two sides drift and nothing would notice.

Stdlib only: the build runs this file under the build venv's interpreter (`python _select_env.py`)
and compares the result with the gates venv's. Values are never stored, only set/unset and a
sha256 (catalog class 1)."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import os
import platform
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# A mismatch in a hard field means the executed Python paths differ (companion fallback,
# sys.platform branches, another resolved dependency), so the map proves nothing for this host.
HARD_FIELDS = ("platform", "python", "uv_lock_sha256", "dists_sha256", "companion")
REQUIRED_KEYS = (*HARD_FIELDS, "env")

# The build venv adds the `mutation` extra for coverage; these roots and what only they pull in
# are left out of `dists_sha256` so the build venv and the gates venv can still compare equal.
BUILD_ONLY_ROOTS = ("coverage", "pytest-cov", "mutmut")
COMPANION_DIST = "decoy-engine-native"
_NATIVE_SUFFIXES = (".so", ".pyd", ".dylib")

# Env vars that change which tests run or skip. Seeded from the gating names found in src and the
# shared test helpers; the S2 completeness sentry (`test_fingerprint_env_complete.py`) owns the
# full inventory and the hard/soft split. Secrets never belong here.
FINGERPRINT_ENV = (
    "DECOY_CUSTOM_PROVIDERS_DIR",
    "DECOY_ML_DISABLED",
    "DECOY_PACK_REQUIRE_SIGNATURE",
    "DECOY_REQUIRE_ML",
    "DECOY_REQUIRE_NER",
    "DECOY_REQUIRE_PG",
    "DECOY_SUBSTRATE",
)

# id -> (fullmatch pattern for a skip reason, the fingerprint env names that decide it). Empty on
# purpose: an id is only safe once its skip condition is matched by identity and shape (S2). Until
# then every skip is unclassified and the selector keeps the file (D5).
ENV_SKIPS: Mapping[str, tuple[str, tuple[str, ...]]] = {}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _requires(dist: md.Distribution) -> list[str]:
    out = []
    for line in dist.requires or ():
        if "extra ==" in line or "extra==" in line:
            continue  # an optional extra the installer did not ask for
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if m:
            out.append(_norm(m.group(0)))
    return out


def _closure(seeds: set[str], edges: Mapping[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    todo = [s for s in seeds if s in edges]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(d for d in edges.get(name, ()) if d in edges)
    return seen


def distribution_lines() -> list[str]:
    """`name==version` of every installed distribution except those only the build venv adds."""
    installed: dict[str, md.Distribution] = {}
    for d in md.distributions():
        raw = d.metadata["Name"]
        if raw:
            installed.setdefault(_norm(raw), d)
    edges = {n: _requires(d) for n, d in installed.items()}
    build_only = _closure({_norm(r) for r in BUILD_ONLY_ROOTS}, edges)
    roots = set(installed) - build_only
    keep = roots | _closure(roots, edges)
    return sorted(f"{n}=={installed[n].version}" for n in keep)


def _companion() -> str:
    try:
        dist = md.distribution(COMPANION_DIST)
    except md.PackageNotFoundError:
        return "absent"
    libs = sorted(f for f in (dist.files or ()) if str(f).endswith(_NATIVE_SUFFIXES))
    if not libs:
        return "absent"
    h = hashlib.sha256()
    for f in libs:
        h.update(_sha256_bytes(Path(str(dist.locate_file(f))).read_bytes()).encode())
    return h.hexdigest()


def fingerprint(repo: Path, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    lock = repo / "uv.lock"
    return {
        "platform": f"{sys.platform}-{platform.machine().lower()}",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "uv_lock_sha256": _sha256_bytes(lock.read_bytes()) if lock.is_file() else "absent",
        "dists_sha256": _sha256_bytes("\n".join(distribution_lines()).encode()),
        "companion": _companion(),
        "env": {
            n: {"set": n in env, "sha256": _sha256_bytes(env[n].encode()) if n in env else ""}
            for n in sorted(FINGERPRINT_ENV)
        },
    }


def hard_mismatches(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    return [f for f in HARD_FIELDS if a.get(f) != b.get(f)]


def valid_fingerprint(obj: object) -> bool:
    """Strict shape check for a fingerprint read from a map (catalog class 2 and 4)."""
    if not isinstance(obj, dict) or any(k not in obj for k in REQUIRED_KEYS):
        return False
    if not all(isinstance(obj[k], str) for k in HARD_FIELDS):
        return False
    env = obj["env"]
    return isinstance(env, dict) and all(
        isinstance(k, str)
        and isinstance(v, dict)
        and isinstance(v.get("set"), bool)
        and isinstance(v.get("sha256"), str)
        for k, v in env.items()
    )


def classify_skips(
    reasons: list[str], registry: Mapping[str, tuple[str, tuple[str, ...]]] = ENV_SKIPS
) -> tuple[list[str], bool]:
    """Registry ids for skip reasons, and whether any reason matched none (class 1: text dropped)."""
    ids: set[str] = set()
    unclassified = False
    for reason in reasons:
        hit = next((i for i, (pat, _f) in registry.items() if re.fullmatch(pat, reason)), None)
        if hit is None:
            unclassified = True
        else:
            ids.add(hit)
    return sorted(ids), unclassified


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Print this interpreter's environment fingerprint.")
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    args = ap.parse_args(argv)
    print(json.dumps(fingerprint(args.repo), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
