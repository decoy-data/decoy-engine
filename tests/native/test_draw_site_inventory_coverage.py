"""Coverage guard for the RNG draw-site inventory (native program, Task 0.1).

Proves the inventory is complete and internally consistent, and stays that
way: a new masking strategy, generation kind, or RNG-bearing source file that
is not catalogued fails a test here rather than silently escaping the
determinism protocol Task 0.3 builds on. The scan reads the SAME
``decoy_engine`` package that is imported, so it checks the live source tree.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

import pytest

import decoy_engine
from decoy_engine.config._tables import GENERATE_TYPES
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.execution.native._determinism_protocol import (
    DETERMINISTIC_NO_DRAW,
    DRAW_SITES,
    ENTROPY_ROOTS,
    FAMILIES,
    GEN_KIND_TO_SITE,
    IDENTITIES,
    MASK_STRATEGY_TO_SITE,
    PROVIDER_IDENTIFIER_SITES,
    DrawSite,
)
from decoy_engine.providers_v2._registry import get_default_registry
from decoy_engine.providers_v2.identifiers import (
    CusipAdapter,
    EinAdapter,
    IbanAdapter,
    Icd10Adapter,
    MrnAdapter,
    NdcAdapter,
    NpiAdapter,
    PanAdapter,
    SsnAdapter,
)

_IDENTIFIER_ADAPTERS = (
    SsnAdapter,
    NpiAdapter,
    EinAdapter,
    IbanAdapter,
    PanAdapter,
    Icd10Adapter,
    MrnAdapter,
    NdcAdapter,
    CusipAdapter,
)

REQUIRED_FAMILIES = {
    "numpy_pcg64",
    "python_mt19937",
    "per_row_reseed",
    "source_keyed_hmac",
    "per_group_stream",
    "faker_seed_instance",
    "gen_derive_context",
}

_ALL_IDS = {s.draw_site_id for s in DRAW_SITES}


# --------------------------------------------------------------------------
# Spec Step 1 assertions.
# --------------------------------------------------------------------------
def test_all_known_families_catalogued() -> None:
    assert {s.family for s in DRAW_SITES} >= REQUIRED_FAMILIES


def test_shuffle_and_statistical_and_faker_present() -> None:
    sites = {s.call_site.split(":")[0].split("/")[-1] for s in DRAW_SITES}
    assert "_shuffle.py" in sites  # numpy permutation
    assert "_sample.py" in sites  # statistical per-row reseed
    assert "synthesize.py" in sites  # sequential random.Random + Faker


# --------------------------------------------------------------------------
# Internal consistency of the catalog.
# --------------------------------------------------------------------------
def test_draw_site_ids_unique() -> None:
    ids = [s.draw_site_id for s in DRAW_SITES]
    assert len(ids) == len(set(ids)), "duplicate draw_site_id in DRAW_SITES"


def test_every_required_field_populated_and_from_allowed_enum() -> None:
    for s in DRAW_SITES:
        assert isinstance(s, DrawSite)
        # Non-empty text fields.
        for name in (
            "draw_site_id",
            "family",
            "call_site",
            "seed_derivation",
            "api_operation",
            "call_shape",
            "null_draw_behavior",
            "config_fingerprint_source",
            "provider_version",
        ):
            value = getattr(s, name)
            assert isinstance(value, str) and value.strip(), f"{s.draw_site_id}: empty {name}"
        # Enum-constrained fields.
        assert s.family in FAMILIES, f"{s.draw_site_id}: family {s.family!r}"
        assert s.entropy_root in ENTROPY_ROOTS, f"{s.draw_site_id}: entropy_root {s.entropy_root!r}"
        assert s.identity in IDENTITIES, f"{s.draw_site_id}: identity {s.identity!r}"
        # Typed flags.
        assert isinstance(s.consumes_variable_draws, bool)
        assert isinstance(s.partitionable, bool)
        assert isinstance(s.uncertain, bool)
        # call_site is "path::qualified_function[#n]", never a line number.
        parse_call_site(s.call_site)
        for mirror in s.mirror_call_sites:
            parse_call_site(mirror)


def test_unseeded_sites_are_not_partitionable() -> None:
    # A genuinely unseeded (entropy_root='none') site cannot be reproduced at
    # all, so it can never be partition-reproducible.
    for s in DRAW_SITES:
        if s.entropy_root == "none":
            assert not s.partitionable, f"{s.draw_site_id}: unseeded but marked partitionable"


# --------------------------------------------------------------------------
# Spec Step 5: cross-check against the LIVE registries (not copied constants).
# --------------------------------------------------------------------------
def test_mask_strategy_map_covers_live_registry_exactly() -> None:
    live = set(SCALAR_HANDLERS)
    mapped = set(MASK_STRATEGY_TO_SITE)
    missing = live - mapped
    extra = mapped - live
    assert not missing, f"masking strategies not catalogued: {sorted(missing)}"
    assert not extra, f"MASK_STRATEGY_TO_SITE names not in the live registry: {sorted(extra)}"


def test_gen_kind_map_covers_live_registry_exactly() -> None:
    live = set(GENERATE_TYPES)
    mapped = set(GEN_KIND_TO_SITE)
    missing = live - mapped
    extra = mapped - live
    assert not missing, f"generation kinds not catalogued: {sorted(missing)}"
    assert not extra, f"GEN_KIND_TO_SITE names not in the live registry: {sorted(extra)}"


def test_every_map_target_resolves_to_a_site_or_the_no_draw_sentinel() -> None:
    for mapping, label in (
        (MASK_STRATEGY_TO_SITE, "mask"),
        (GEN_KIND_TO_SITE, "gen"),
        (PROVIDER_IDENTIFIER_SITES, "provider"),
    ):
        for name, target in mapping.items():
            if target == DETERMINISTIC_NO_DRAW:
                continue
            assert target in _ALL_IDS, f"{label} {name!r} maps to unknown draw_site_id {target!r}"


def test_provider_identifier_map_covers_live_registry_exactly() -> None:
    # Enumerate every registered provider whose adapter is a synthetic-identifier
    # adapter (each carries the derive_value + unseeded default_rng draws). A new
    # identifier adapter registered without a catalog entry fails here.
    reg = get_default_registry()
    live_identifier_providers = {
        name
        for name in reg.known_providers()
        if isinstance(reg.get_adapter(name), _IDENTIFIER_ADAPTERS)
    }
    mapped = set(PROVIDER_IDENTIFIER_SITES)
    missing = live_identifier_providers - mapped
    extra = mapped - live_identifier_providers
    assert not missing, f"identifier providers not catalogued: {sorted(missing)}"
    assert not extra, f"PROVIDER_IDENTIFIER_SITES names not registered: {sorted(extra)}"
    assert live_identifier_providers, "expected identifier providers in the default registry"


# --------------------------------------------------------------------------
# Spec Steps 3-5: a real static scan. Every RNG-bearing source file under the
# masked/generated-output directories must be represented in the catalog (as a
# call_site or a mirror) or explicitly allowlisted as non-output plumbing. A
# brand-new draw site therefore fails this test until it is catalogued.
# --------------------------------------------------------------------------
_PKG_DIR = Path(decoy_engine.__file__).resolve().parent

# Directories where a draw produces masked or generated OUTPUT. providers_v2
# is included so a new provider adapter with a new RNG draw is seen here.
_SCAN_ROOTS = (
    "execution",
    "generation",
    "generators",
    "transforms",
    "kernel",
    "reference_tables",
    "providers_v2",
)

# Call-level tokens that indicate an actual randomness draw. Includes the three
# keyed primitives (derive / derive_index / derive_value), the numpy and Python
# RNG constructors, Faker.seed_instance, the whole-column numpy ops, and the
# Mimesis Generic() seeded constructor. Prose is stripped before matching (see
# _strip_prose) so a docstring mention of `derive(...)` does not count.
_DRAW_TOKEN = re.compile(
    r"np\.random\.default_rng\(|np\.random\.RandomState\(|random\.Random\(|"
    r"\.seed_instance\(|\.permutation\(|\.shuffle\(|\.choices\(|"
    r"derive_index\(|derive_value\(|\bderive\(|Generic\("
)

_TRIPLE_QUOTED = re.compile(r"(\"\"\".*?\"\"\"|'''.*?''')", re.DOTALL)


def _strip_prose(text: str) -> str:
    """Remove triple-quoted blocks and line comments so the scan matches code.

    Bare `derive(` also appears in docstrings and comments describing the keyed
    primitive; stripping prose keeps the scan matching real call sites, not
    documentation. Single-line string literals are intentionally left in (a
    handful are handled by the allowlist), since removing them reliably needs a
    real tokenizer.
    """
    without_docstrings = _TRIPLE_QUOTED.sub("", text)
    return "\n".join(re.sub(r"#.*$", "", line) for line in without_docstrings.splitlines())


# RNG-token-bearing files that are NOT masked/generated-output draw sites:
# execution orchestration that only threads seeds, chunk-profiling that draws a
# fixed Random(0) over sampling, a diagnostic message string that quotes
# `derive(...)`, and this inventory module itself (whose data literals quote the
# very call shapes the scan looks for).
_ALLOWLIST = frozenset(
    {
        "execution/_chunked.py",
        "execution/_chunked_fk_edge_checks.py",  # a log-message string quotes "derive(seed, ns, value)"
        "execution/_chunked_profile.py",
        "execution/_pipeline.py",
        "execution/native/_determinism_protocol.py",
        # GP2 (2026-09-17): DRAW_SITES data siblings split out of
        # _determinism_protocol.py's own recorded LOC ceiling (test_module_size.py).
        # Same reason as that module's own entry: these are DrawSite literals whose
        # seed_derivation/notes strings quote the call shapes the scan looks for.
        "execution/native/_draw_sites_gen_pool.py",
        # MG-5 (vault V0): the mask.tokenize DrawSite + provider-primitive data
        # siblings split out of _determinism_protocol.py / _draw_site_providers.py's
        # own recorded LOC ceiling. Same non-output-draw rationale as the GP2
        # siblings above: these are DrawSite literals whose seed_derivation/notes
        # strings quote the call shape the scan looks for.
        "execution/native/_draw_sites_tokenize.py",
        # Per-family DRAW_SITES data modules assembled by _determinism_protocol.py.
        # Same rationale as the siblings above: DrawSite literals whose
        # seed_derivation/notes strings quote the call shapes the scan looks for.
        "execution/native/_draw_sites_gen.py",
        "execution/native/_draw_sites_mask.py",
        "execution/native/_draw_sites_provider_backed.py",
        # Task 0.3 protocol plumbing: reproduces the catalogued draws off the
        # hot path (one provider per DRAW_SITES entry). Not a new output site.
        "execution/native/_draw_site_providers.py",
        # The provider classes split out of _draw_site_providers.py into the
        # protocol package; same non-output-draw rationale as that module's entry.
        "execution/native/protocol/providers_base.py",
        "execution/native/protocol/providers_gen.py",
        "execution/native/protocol/providers_gen_unique.py",
        "execution/native/protocol/providers_mask.py",
        # GP2 (2026-09-17): DrawSiteProvider siblings split out of
        # _draw_site_providers.py's own recorded LOC ceiling; same non-output-draw
        # rationale as that module's own entry above.
        "execution/native/_draw_site_providers_gen_pool.py",
        # Task 0.4 crypto contract: the reference kernels call derive/fpe_encrypt_value
        # to reproduce shipped KEYED derivation, which is deterministic, not an RNG
        # output draw. Not a new draw site. (Split out of _crypto_ext.py into this
        # sibling by the 2026-09-10 module-size remediation; _crypto_ext.py no longer
        # carries the derive calls, so only this module needs the allowlist entry.)
        "execution/native/_crypto_reference.py",
        # Task 2.3 index-kernel contract: the loader's KAT self-test and the
        # `_ReferenceIndexDerivation` oracle both call the already-catalogued
        # `derive_index` primitive to reproduce/verify deterministic pool selection.
        # Not a new draw site (mirrors the _crypto_reference.py entry above).
        "execution/native/_index_ext.py",
        # S-slate group_key raw-hex kernel contract: the loader's KAT self-test and
        # the `_ReferenceRawHexDerivation` oracle call the already-catalogued
        # `derive` primitive (group_key's source-keyed HMAC site) to reproduce the
        # uncanonicalized hex derivation. Not a new draw site (mirrors _index_ext.py).
        "execution/native/_group_key_ext.py",
        # Phase F FR0 unified generation core: the persistent per-column streams re-express the
        # ALREADY-catalogued legacy draws (sequence has none; categorical, reference, per-row
        # faker, pooled faker and the null mask use the same GenDeriveContext roots and RNG
        # families), consumed `size=batch` at a time. They are the same draw sites, advanced
        # incrementally, not new ones; `synthesize.py` and `_synthesize_derived.py` keep the
        # catalogued entries for the legacy whole-table path.
        "generation/_column_streams.py",
    }
)


def _catalogued_paths() -> set[str]:
    paths: set[str] = set()
    for s in DRAW_SITES:
        for entry in (s.call_site, *s.mirror_call_sites):
            paths.add(parse_call_site(entry).path)
    return paths


def _scan_rng_files() -> set[str]:
    found: set[str] = set()
    for root in _SCAN_ROOTS:
        base = _PKG_DIR / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if _DRAW_TOKEN.search(_strip_prose(text)):
                found.add(path.relative_to(_PKG_DIR).as_posix())
    return found


def test_static_scan_finds_no_uncatalogued_draw_site() -> None:
    known = _catalogued_paths() | _ALLOWLIST
    scanned = _scan_rng_files()
    uncatalogued = sorted(scanned - known)
    assert not uncatalogued, (
        "RNG-bearing source files not represented in DRAW_SITES (add a catalog "
        f"entry or, if not an output draw, the allowlist): {uncatalogued}"
    )


def test_scan_actually_matched_the_known_output_files() -> None:
    # Guard against a scan that silently matches nothing (e.g. a broken regex or
    # wrong root): the shuffle, statistical, and synthesize files must be seen.
    scanned = _scan_rng_files()
    for expected in (
        "execution/_strategies/_shuffle.py",
        "generation/statistical/_sample.py",
        "generation/synthesize.py",
        "providers_v2/identifiers/_ssn.py",
    ):
        assert expected in scanned, f"static scan missed {expected}"


def test_catalogued_call_sites_point_at_real_files() -> None:
    # Every call_site file (not the drifting line number) must exist in the tree.
    for s in DRAW_SITES:
        for entry in (s.call_site, *s.mirror_call_sites):
            rel = parse_call_site(entry).path
            assert (_PKG_DIR / rel).is_file(), f"{s.draw_site_id}: missing file {rel}"


# --------------------------------------------------------------------------
# Resolving `path::qualified_function[#n]` call sites (row 24ze G1).
# --------------------------------------------------------------------------
# A catalogued function may reach the keyed primitive through an alias or a helper (a
# `derive_func` parameter, `DeriveContext.derive_sources`, `hmac_hex`, a batch kernel), so the
# per-entry check also counts those spellings. The tree-wide scan keeps the narrower DRAW_TOKEN.
ENTRY_DRAW_TOKEN = re.compile(
    _DRAW_TOKEN.pattern
    + r"|\bderive_sources?\(|\bderive_func\(|\bhmac_hex\(|\w*hmac\w*\.new\(|"
    + r"derive_index_batch\(|\bpositional_pool_indices\(|\bderive_validated_indices\(|\.sample\(|\.integers\(|\.random\("
)

_CALL_SITE = re.compile(r"(?P<path>[\w/]+\.py)::(?P<qual>\w+(?:\.\w+)*)(?:#(?P<n>[1-9]\d*))?\Z")


class CallSite(NamedTuple):
    path: str
    qualified: str
    ordinal: int | None

    @property
    def base(self) -> str:
        return f"{self.path}::{self.qualified}"


def parse_call_site(reference: str) -> CallSite:
    match = _CALL_SITE.match(reference)
    if match is None:
        raise ValueError(f"call site {reference!r} is not path::function[#n]")
    n = match.group("n")
    return CallSite(match.group("path"), match.group("qual"), int(n) if n else None)


def _functions(tree: ast.AST) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    def walk(node: ast.AST, prefix: tuple[str, ...]) -> Iterable[tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = (*prefix, child.name)
                if not isinstance(child, ast.ClassDef):
                    yield ".".join(names), child
                yield from walk(child, names)
            else:
                yield from walk(child, prefix)

    return walk(tree, ())  # type: ignore[return-value]


def call_site_token_count(package_dir: Path, ref: CallSite) -> int:
    """Draw tokens in the referenced function's body. Raises LookupError if it is missing."""
    path = package_dir / ref.path
    if not path.is_file():
        raise LookupError(f"module {ref.path} does not exist")
    text = path.read_text(encoding="utf-8")
    for qualified, node in _functions(ast.parse(text)):
        if qualified == ref.qualified:
            lines = text.splitlines()[node.lineno - 1 : node.end_lineno]
            return len(ENTRY_DRAW_TOKEN.findall(_strip_prose("\n".join(lines))))
    raise LookupError(f"function {ref.qualified} does not exist in {ref.path}")


def call_site_function_source(package_dir: Path, ref: CallSite) -> str:
    """The referenced function's source text (for tests that look for a call in it)."""
    text = (package_dir / ref.path).read_text(encoding="utf-8")
    for qualified, node in _functions(ast.parse(text)):
        if qualified == ref.qualified:
            return "\n".join(text.splitlines()[node.lineno - 1 : node.end_lineno])
    raise LookupError(f"function {ref.qualified} does not exist in {ref.path}")


def call_site_problems(package_dir: Path, sites: Iterable[object]) -> list[str]:
    """Every defect in the catalogue's references, as `draw_site_id: reason` lines."""
    found: list[str] = []
    claimed: dict[str, list[tuple[str, int | None]]] = defaultdict(list)
    for site in sites:
        sid = site.draw_site_id  # type: ignore[attr-defined]
        refs = (site.call_site, *site.mirror_call_sites)  # type: ignore[attr-defined]
        drawing = False
        for raw in refs:
            try:
                ref = parse_call_site(raw)
                count = call_site_token_count(package_dir, ref)
            except (ValueError, LookupError) as exc:
                found.append(f"{sid}: {exc}")
                continue
            claimed[ref.base].append((sid, ref.ordinal))
            if ref.ordinal is not None and count < ref.ordinal:
                found.append(f"{sid}: {ref.base}#{ref.ordinal} has only {count} draw tokens")
            elif count:
                drawing = True
        if not drawing:
            found.append(f"{sid}: no referenced function holds a draw token")
    for base, uses in claimed.items():
        if len(uses) > 1:
            ordinals = [ordinal for _, ordinal in uses]
            if None in ordinals or len(ordinals) != len(set(ordinals)):
                owners = sorted({sid for sid, _ in uses})
                found.append(f"{base}: used {len(uses)} times by {owners} without distinct #n")
    return found


# --------------------------------------------------------------------------
# Call sites name a function, not a line (row 24ze G1).
# --------------------------------------------------------------------------
def test_every_call_site_resolves_to_a_function_that_draws() -> None:
    assert call_site_problems(_PKG_DIR, DRAW_SITES) == []


def _scratch_copy(tmp_path: Path, transform) -> Path:  # type: ignore[no-untyped-def]
    """A copy of every module the catalogue names, with `transform(path, text)` applied."""
    scratch = tmp_path / "decoy_engine"
    for site in DRAW_SITES:
        for entry in (site.call_site, *site.mirror_call_sites):
            rel = parse_call_site(entry).path
            target = scratch / rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    transform(rel, (_PKG_DIR / rel).read_text(encoding="utf-8")), encoding="utf-8"
                )
    return scratch


def test_a_blank_line_above_every_draw_keeps_every_entry_resolving(tmp_path: Path) -> None:
    def add_blank_lines(_rel: str, text: str) -> str:
        out: list[str] = []
        for line in text.splitlines():
            if ENTRY_DRAW_TOKEN.search(_strip_prose(line)):
                out.append("")
            out.append(line)
        return "\n".join(out) + "\n"

    scratch = _scratch_copy(tmp_path, add_blank_lines)
    assert call_site_problems(scratch, DRAW_SITES) == []


def test_renaming_a_catalogued_function_fails(tmp_path: Path) -> None:
    victim = parse_call_site(DRAW_SITES[0].call_site)
    leaf = victim.qualified.rsplit(".", 1)[-1]

    def rename(rel: str, text: str) -> str:
        return text.replace(f"def {leaf}(", f"def {leaf}_renamed(") if rel == victim.path else text

    scratch = _scratch_copy(tmp_path, rename)
    found = call_site_problems(scratch, DRAW_SITES)
    assert any(line.startswith(f"{DRAW_SITES[0].draw_site_id}:") for line in found)


def test_two_sites_in_one_function_need_distinct_ordinals() -> None:
    clash = DrawSite(
        **{
            **{f: getattr(DRAW_SITES[0], f) for f in DrawSite.__dataclass_fields__},
            "draw_site_id": "scratch.clash",
            "call_site": DRAW_SITES[0].call_site.split("#")[0],
            "mirror_call_sites": (),
        }
    )
    base = DRAW_SITES[0].call_site.split("#")[0]
    found = call_site_problems(_PKG_DIR, (DRAW_SITES[0], clash))
    assert any(base in line and "distinct" in line for line in found)


def test_a_line_number_call_site_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_call_site("generation/synthesize.py:491")
