"""Public/internal import-boundary sentry (V2.0-C).

The V2 boundary contract has two halves:

  1. Engine side (this file): public modules at the engine boundary
     (``decoy_engine.providers``, ``decoy_engine.errors``,
     ``decoy_engine.__init__``, ``decoy_engine.sdk``) must not import
     from ``decoy_engine.internal.*``. If they did, the public surface
     would leak the unstable internal API to every caller that touches
     it.

  2. Platform/CLI side (enforced separately in those repos): no file
     under ``api/`` or the CLI source tree may import from
     ``decoy_engine.internal.*``. The platform repo carries its own
     copy of this gate.

Engine-internal subpackages (graph/, generators/, transforms/,
masker/, etc.) MAY freely import from decoy_engine.internal because
they are part of the engine implementation, not the public boundary.
A V2.0-D follow-up sprint will narrow that as more of the public API
moves out of internal/.

A new public-boundary file added to the engine must either avoid
internal imports entirely OR earn an entry in PUBLIC_BOUNDARY_ALLOWLIST
below with a comment naming the sprint that will remove it. Adding an
entry without a comment is a review blocker.
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"

# The exact set of files V2 calls out as the public engine boundary.
# These are what platform/CLI/users import from; if any of these reaches
# into decoy_engine.internal at the import-line level, the boundary is
# broken.
PUBLIC_BOUNDARY_FILES: tuple[str, ...] = (
    "__init__.py",
    "errors.py",
    "providers.py",
    "sdk.py",
    "verification/canary/__init__.py",
    "telemetry/__init__.py",
    "safe_output/__init__.py",
    "support/__init__.py",
)

# Narrow exceptions: a public-boundary file is allowed to import from
# internal IFF there is an explicit entry below. Each entry must include
# the migration sprint that removes it. Empty today: V2.0-C aims to keep
# it that way. (sdk.py is allowed because its current implementation
# still pulls in the legacy validator base class -- the V2.0-D split
# moves that to a public ABC.)
PUBLIC_BOUNDARY_ALLOWLIST: dict[str, str] = {
    "providers.py": (
        "decoy_engine.providers is by-design a thin public wrapper "
        "around decoy_engine.internal.faker_setup; the implementation "
        "details (Faker reflection denylist, list-provider snapshotting, "
        "make_faker locale fallback) are kept internal so they can "
        "evolve without an API change. The public surface re-exports "
        "the six stable function names. Callers depend on "
        "decoy_engine.providers; the import inside providers.py itself "
        "is the engine's own seam, not an external leak. No removal "
        "trigger -- this is the architectural pattern V2.0-C committed "
        "to."
    ),
}


_INTERNAL_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+decoy_engine\.internal(?:\.\S+)?\s+import\b|"
    r"import\s+decoy_engine\.internal(?:\.\S+)?\b)",
    re.MULTILINE,
)


def _imports_internal(path: Path) -> bool:
    """True iff the file references ``decoy_engine.internal[.subpkg]``
    in an import statement (top-level or inside a function)."""
    text = path.read_text(encoding="utf-8")
    if "decoy_engine.internal" not in text:
        return False
    return bool(_INTERNAL_IMPORT_RE.search(text))


def test_public_boundary_files_exist() -> None:
    """Sanity: the files this sentry checks must actually be present.
    A missing public-boundary file is a much bigger problem than a
    boundary violation; surface it loudly here."""
    missing = [rel for rel in PUBLIC_BOUNDARY_FILES if not (ENGINE_ROOT / rel).exists()]
    assert not missing, (
        "PUBLIC_BOUNDARY_FILES entries that do not exist on disk:\n  - "
        + "\n  - ".join(missing)
        + "\nIf a public-boundary file was intentionally removed, "
        "update PUBLIC_BOUNDARY_FILES in this test."
    )


def test_no_internal_imports_at_public_boundary() -> None:
    """Public-boundary files (decoy_engine.__init__, errors, providers,
    sdk) must not import from decoy_engine.internal. Engine-internal
    subpackages (graph/, transforms/, etc.) are not checked here --
    they're part of the implementation, not the boundary."""
    offenders: list[str] = []
    for rel in PUBLIC_BOUNDARY_FILES:
        path = ENGINE_ROOT / rel
        if not path.exists():
            continue
        if not _imports_internal(path):
            continue
        if rel in PUBLIC_BOUNDARY_ALLOWLIST:
            continue
        offenders.append(rel)

    assert not offenders, (
        "Public-boundary files importing from decoy_engine.internal.*:\n"
        "  - " + "\n  - ".join(offenders) + "\n"
        "Fix: move the import to a public engine module, OR add an "
        "entry to PUBLIC_BOUNDARY_ALLOWLIST in this file with a comment "
        "naming the sprint that will remove it."
    )


def test_allowlist_entries_are_real() -> None:
    """Every PUBLIC_BOUNDARY_ALLOWLIST entry must still exist and still
    actually import from decoy_engine.internal.*. Stale entries
    silently weaken the gate."""
    stale: list[str] = []
    for rel in PUBLIC_BOUNDARY_ALLOWLIST:
        path = ENGINE_ROOT / rel
        if not path.exists():
            stale.append(f"{rel} (file missing)")
            continue
        if not _imports_internal(path):
            stale.append(f"{rel} (no longer imports decoy_engine.internal.*)")

    assert not stale, (
        "Stale PUBLIC_BOUNDARY_ALLOWLIST entries -- remove them:\n  - " + "\n  - ".join(stale)
    )


# `generation.pool` exports `canonicalize_typed_array`; execution/ reads it from the package,
# not the private `_canonicalize` module. The only name execution/ may still take from the
# private module is `_canonicalize_source`, at the sites below (this set may only shrink).
_CANONICALIZE_PRIVATE = "decoy_engine.generation.pool._canonicalize"
_CANONICALIZE_PRIVATE_SITES = frozenset(
    {
        "execution/_strategies/_categorical.py",
        "execution/_strategies/_date_shift.py",
        "execution/native/_index_ext.py",
        "execution/out_of_core/_mask_group_b.py",
    }
)


def _private_canonicalize_imports(rel: str, source: str) -> set[tuple[str, str]]:
    import ast

    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == _CANONICALIZE_PRIVATE:
            found |= {(rel, alias.name) for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {(rel, a.name) for a in node.names if a.name == _CANONICALIZE_PRIVATE}
    return found


def _canonicalize_offenders(sources: dict[str, str]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for rel, text in sources.items():
        found |= _private_canonicalize_imports(rel, text)
    return {
        (rel, name)
        for rel, name in found
        if rel not in _CANONICALIZE_PRIVATE_SITES or name != "_canonicalize_source"
    }


def _execution_sources() -> dict[str, str]:
    root = ENGINE_ROOT / "execution"
    return {
        p.relative_to(ENGINE_ROOT).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*.py")
    }


def test_execution_reads_canonicalize_through_the_package() -> None:
    sources = _execution_sources()
    assert not _canonicalize_offenders(sources)
    still = {
        rel
        for rel, _ in set().union(
            *(_private_canonicalize_imports(r, t) for r, t in sources.items())
        )
    }
    assert still == _CANONICALIZE_PRIVATE_SITES, "ratchet the site set down"


def test_a_private_canonicalize_import_in_execution_is_red() -> None:
    """Mutation: `_date_shift_ext.py` takes `canonicalize_typed_array` from the private module."""
    rel = "execution/native/_date_shift_ext.py"
    text = (ENGINE_ROOT / rel).read_text(encoding="utf-8")
    old = "from decoy_engine.generation.pool import GenerationError, canonicalize_typed_array"
    assert old in text
    mutated = text.replace(
        old,
        "from decoy_engine.generation.pool import GenerationError\n"
        f"from {_CANONICALIZE_PRIVATE} import canonicalize_typed_array",
    )
    assert _canonicalize_offenders({rel: mutated}) == {(rel, "canonicalize_typed_array")}
    rel2 = "execution/_strategies/_date_shift.py"
    text2 = (ENGINE_ROOT / rel2).read_text(encoding="utf-8")
    mutated2 = text2.replace(
        f"from {_CANONICALIZE_PRIVATE} import _canonicalize_source",
        f"from {_CANONICALIZE_PRIVATE} import _canonicalize_source, canonicalize_typed_array",
    )
    assert mutated2 != text2
    assert _canonicalize_offenders({rel2: mutated2}) == {(rel2, "canonicalize_typed_array")}
