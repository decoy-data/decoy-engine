"""Where each engine sentry's committed allowlist or baseline lives, as a set of keys.

``SOURCES`` is the single table the registry test and the one-off ``--write-initial``
generator share. Entries here are the X0a initial inventory; after that the ratchet
(``scripts/dev/ratchet_check.py``) lets a baseline only shrink.
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
SENTRY = ROOT / "tests" / "sentry"
BASELINES = SENTRY / "baselines"
CREATED_IN = "X0a"


def _flat(item: object) -> str:
    return "::".join(map(str, item)) if isinstance(item, (tuple, list)) else str(item)


@dataclass(frozen=True)
class InCode:
    """Keys of a module-level dict or tuple in a sentry test file."""

    test_file: str
    constant: str
    # Module attributes naming a removed surface. The residual-surface sentry bars that token in
    # tracked files, so the baseline stores a placeholder for it.
    masks: tuple[str, ...] = ()
    # When each value is a tuple, the index of its integer count (the entry's ``max``).
    count_at: int | None = None
    # When the constant maps each guarded name to its own allowlist, key by ``name::site``.
    nested: bool = False

    def _module(self) -> object:
        path = SENTRY / self.test_file
        spec = importlib.util.spec_from_file_location(f"_bl_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # a dataclass in the module looks itself up here
        spec.loader.exec_module(mod)
        return mod

    def __call__(self) -> set[str]:
        mod = self._module()
        tokens = [getattr(mod, name) for name in self.masks]
        table = getattr(mod, self.constant)
        if self.nested:
            table = [f"{name}::{_flat(site)}" for name, sites in table.items() for site in sites]
        out = set()
        for k in table:
            key = _flat(k)
            for token in tokens:
                key = key.replace(token, "<removed-surface>")
            out.add(key)
        return out

    def maxes(self) -> dict[str, int]:
        """Integer values of the constant, keyed like ``__call__``: the live ``max`` per entry."""
        table = getattr(self._module(), self.constant)
        at = self.count_at
        return {_flat(k): int(v if at is None else v[at]) for k, v in table.items()}


in_code = InCode


def _limits() -> ModuleType:
    """``ratchet/_limit_constants.py``, loaded by path; it imports its sibling helper by package."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    path = SENTRY / "ratchet" / "_limit_constants.py"
    spec = importlib.util.spec_from_file_location("_bl_limit_constants", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def live_bounds(kind: str) -> dict[str, int]:
    """Live value per ``sentry-limits`` key for the ``"max"`` or ``"min"`` rows of ``LIMITS``."""
    mod = _limits()
    if problems := mod.direction_problems(mod.LIMITS):
        raise ValueError("; ".join(problems))
    out: dict[str, int] = {}
    for (f, c), k in sorted(mod.LIMITS.items()):
        if k != kind:
            continue
        try:
            value: int | None = mod.read_int((SENTRY / f).read_text(encoding="utf-8"), c)
        except ValueError:
            value = None
        if value is None:  # raised outside the handler so no context carries the refused text
            raise ValueError(f"{mod.key_of(f, c)} {mod.REFUSED}")
        out[mod.key_of(f, c)] = value
    return out


@dataclass(frozen=True)
class InLimits:
    """Keys of ``LIMITS``: one ``<test file>::<constant>`` per scalar cap or floor."""

    test_file: str = "ratchet/_limit_constants.py"
    constant: str = "LIMITS"

    def __call__(self) -> set[str]:
        mod = _limits()
        return {mod.key_of(f, c) for f, c in mod.LIMITS}


def json_keys(rel: str, section: str, fields: tuple[str, ...]) -> Callable[[], set[str]]:
    def keys() -> set[str]:
        rows = json.loads((ROOT / rel).read_text(encoding="utf-8"))[section]
        return {"::".join(str(r.get(f, "")) for f in fields) for r in rows}

    return keys


def toml_keys(rel: str) -> Callable[[], set[str]]:
    def keys() -> set[str]:
        data = tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
        out: set[str] = set()
        for section, rows in data.items():
            for row in rows:
                if isinstance(row, dict):
                    ident = (
                        row.get("module"),
                        row.get("function"),
                        row.get("sink"),
                        row.get("ordinal"),
                    )
                    out.add(f"{section}::" + "::".join(str(p) for p in ident if p is not None))
                else:
                    out.add(f"{section}::{row}")
        return out

    return keys


def import_layer_keys(rel: str) -> Callable[[], set[str]]:
    """``<contract>::<importer> -> <imported>`` for each ignore line of an import-linter config.

    Each contract keeps its own namespace, so each ignore list shrinks on its own. Layer
    membership is not keyed here: it is the exact snapshot in ``test_import_layers.py``.
    """

    def keys() -> set[str]:
        path = SENTRY / "layout" / "_layout.py"
        spec = importlib.util.spec_from_file_location("_bl_layout", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # dataclasses in the module look themselves up here
        spec.loader.exec_module(mod)
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.read_string((ROOT / rel).read_text(encoding="utf-8"))
        found: set[str] = set()
        for section in parser.sections():
            raw = parser.get(section, "ignore_imports", fallback="")
            lines = "".join(f"    {ln}\n" for ln in raw.splitlines())
            contract = section.removeprefix("importlinter:contract:")
            found |= {
                f"{contract}::{key}" for key in mod.ignore_keys(f"[c]\nignore_imports =\n{lines}")
            }
        return found

    return keys


def exception_text_copy_census() -> dict[str, int]:
    """Live engine exception-text copies: site key to multiplicity (the entry's ``max``)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.sentry.safe_output._copies import census, scan_tree

    return census(scan_tree(ROOT / "src" / "decoy_engine"))


def self_maxes(name: str) -> Callable[[], dict[str, int]]:
    """For a baseline its own sentry reads as the source of truth: the ``max`` it records."""

    def maxes() -> dict[str, int]:
        entries = json.loads((BASELINES / f"{name}.json").read_text(encoding="utf-8"))["entries"]
        return {k: e["max"] for k, e in entries.items() if "max" in e}

    return maxes


def config_refusal_census() -> dict[str, int]:
    """Live refusal constructions outside the zero set that break S1: site key to count."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.sentry.defects._config_refusal_scan import baselined_counts, scan_tree

    return baselined_counts(scan_tree(ROOT / "src" / "decoy_engine"))


@dataclass(frozen=True)
class Source:
    sentry_id: str
    where: str  # file the sentry reads, for the reason text
    keys: Callable[[], set[str]]
    note: str = ""
    # Live numeric value per key, for a list whose entries are counts (recorded as ``max``).
    maxes: Callable[[], dict[str, int]] | None = None
    # Live floor per key, for a bound that may only rise (recorded as ``min``).
    mins: Callable[[], dict[str, int]] | None = None


F29 = "tests/fixtures/f29"
SOURCES: tuple[Source, ...] = (
    Source(
        "engine-exception-text-copies",
        "safe_output/test_exception_text_copy.py",
        lambda: set(exception_text_copy_census()),
        maxes=exception_text_copy_census,
    ),
    Source(
        "config-refusal-text",
        "defects/test_config_refusal_text.py",
        lambda: set(config_refusal_census()),
        maxes=config_refusal_census,
    ),
    Source(
        "f29-reason-baseline",
        f"{F29}/reason-baseline.json",
        json_keys(f"{F29}/reason-baseline.json", "identities", ("namespace", "code")),
        "frozen: test_reason_baseline_frozen.py digest stays authoritative",
    ),
    Source(
        "f29-producer-inventory",
        f"{F29}/producer-inventory.json",
        json_keys(f"{F29}/producer-inventory.json", "sites", ("file", "function", "kind", "expr")),
    ),
    Source(
        "f29-consumer-inventory",
        f"{F29}/producer-inventory.json",
        json_keys(f"{F29}/producer-inventory.json", "consumers", ("file", "function", "expr")),
    ),
    Source(
        "secret-material-census",
        "tests/sentry/secret_material_census.json",
        json_keys(
            "tests/sentry/secret_material_census.json", "entries", ("file", "function", "name")
        ),
    ),
    Source(
        "reason-unchecked-helpers",
        "tests/sentry/baselines/reason-unchecked-helpers.json",
        in_code("test_reason_registry.py", "UNCHECKED_HELPERS"),
    ),
    Source(
        "module-size",
        "test_module_size.py",
        in_code("test_module_size.py", "ALLOWLIST"),
        maxes=in_code("test_module_size.py", "ALLOWLIST").maxes,
    ),
    Source(
        "date-shift-window-reader",
        "test_date_shift_window_reader.py",
        in_code("test_date_shift_window_reader.py", "CENSUS"),
        maxes=in_code("test_date_shift_window_reader.py", "MAX_HITS").maxes,
    ),
    Source(
        "column-shape-classifier",
        "test_column_shape_classifier.py",
        in_code("test_column_shape_classifier.py", "ALLOWED_CALLERS", nested=True),
    ),
    Source(
        "bucketize-width-contract",
        "test_bucketize_width_contract.py",
        in_code("test_bucketize_width_contract.py", "ALLOWED_CALLERS"),
    ),
    Source(
        "package-fanout",
        "layout/test_package_fanout.py",
        in_code("layout/test_package_fanout.py", "FANOUT_ALLOWLIST"),
        maxes=in_code("layout/test_package_fanout.py", "FANOUT_ALLOWLIST").maxes,
    ),
    Source(
        "table-kind-truth-tests",
        "test_table_kind_classifier.py",
        in_code("test_table_kind_classifier.py", "TRUTH_TEST_BASELINE"),
        maxes=in_code("test_table_kind_classifier.py", "TRUTH_TEST_BASELINE").maxes,
    ),
    Source(
        "win32-import-surface",
        "test_win32_import_surface.py",
        in_code("test_win32_import_surface.py", "EXCEPTIONS", count_at=0),
        maxes=in_code("test_win32_import_surface.py", "EXCEPTIONS", count_at=0).maxes,
    ),
    Source(
        "platform-census",
        "test_platform_checks.py",
        in_code("test_platform_checks.py", "CENSUS"),
        maxes=in_code("test_platform_checks.py", "CENSUS").maxes,
    ),
    Source(
        "dir-fd-readers",
        "test_platform_checks.py",
        in_code("test_platform_checks.py", "DIR_FD_ALLOWLIST"),
    ),
    Source(
        "signature-exemptions",
        "release/_signatures.py",
        in_code("release/_signatures.py", "SIGNATURE_EXEMPTIONS"),
    ),
    Source(
        "ci-write-scopes",
        "_ci_lock_scan.py",
        in_code("_ci_lock_scan.py", "WRITE_ALLOWLIST"),
    ),
    Source(
        "canonical-json-choke-point",
        "defects/test_canonical_json_choke_point.py",
        in_code("defects/test_canonical_json_choke_point.py", "ALLOWLIST"),
    ),
    Source(
        "ner-mismatch-single-site",
        "defects/test_ner_mismatch_single_site.py",
        in_code("defects/test_ner_mismatch_single_site.py", "ALLOWED"),
    ),
    Source(
        "group-by-single-reader",
        "defects/test_group_by_single_reader.py",
        in_code("defects/test_group_by_single_reader.py", "ALLOWED"),
    ),
    Source(
        "faker-pool-size-one-resolver",
        "defects/test_faker_pool_size_one_resolver.py",
        in_code("defects/test_faker_pool_size_one_resolver.py", "ALLOWED"),
    ),
    Source(
        "faker-native-allowlist-total",
        "defects/test_faker_native_allowlist_total.py",
        in_code("defects/test_faker_native_allowlist_total.py", "EXCLUDED"),
    ),
    Source(
        "lossless-int-columns",
        "defects/test_lossless_int_columns.py",
        in_code("defects/test_lossless_int_columns.py", "ALLOWED", nested=True),
    ),
    Source(
        "output-assembly-one-path",
        "defects/test_output_assembly_one_path.py",
        in_code("defects/test_output_assembly_one_path.py", "ALLOWED"),
    ),
    Source(
        "validation-route-allowlist",
        "defects/test_validation_sites.py",
        in_code("defects/test_validation_sites.py", "ROUTE_ALLOWLIST"),
    ),
    Source(
        "snapshot-parse-single-owner",
        "generation/test_snapshot_parse_single_owner.py",
        in_code("generation/test_snapshot_parse_single_owner.py", "ALLOWED"),
        maxes=in_code("generation/test_snapshot_parse_single_owner.py", "ALLOWED").maxes,
    ),
    Source(
        "physical-seam-scoped",
        "layout/_scoped_changes.py",
        in_code("layout/_scoped_changes.py", "SCOPED_EXCEPTIONS"),
    ),
    Source("import-layers", ".importlinter", import_layer_keys(".importlinter")),
    Source(
        "public-import-boundary",
        "test_public_import_boundary.py",
        in_code("test_public_import_boundary.py", "PUBLIC_BOUNDARY_ALLOWLIST"),
    ),
    Source(
        "exception-hierarchy",
        "test_exception_hierarchy.py",
        in_code("test_exception_hierarchy.py", "_ALLOWLIST"),
    ),
    Source(
        "reason-policy-single-source",
        "test_reason_policy_single_source.py",
        in_code("test_reason_policy_single_source.py", "EXEMPT"),
    ),
    Source(
        "file-access-entry-seams",
        "test_file_access_entry_points.py",
        in_code("test_file_access_entry_points.py", "INTERNAL_SEAMS"),
    ),
    Source(
        "post-scan-route-exempt",
        "test_post_scan_route_guard.py",
        in_code("test_post_scan_route_guard.py", "EXEMPT"),
    ),
    Source(
        "locator-waivers",
        "test_locator_hygiene.py",
        in_code("test_locator_hygiene.py", "WAIVERS"),
        maxes=in_code("test_locator_hygiene.py", "WAIVERS", count_at=0).maxes,
    ),
    Source(
        "log-interpolation",
        "test_log_interpolation.py",
        in_code("test_log_interpolation.py", "ALLOWLIST"),
        maxes=in_code("test_log_interpolation.py", "ALLOWLIST", count_at=0).maxes,
    ),
    Source(
        "sentry-limits",
        "ratchet/_limit_constants.py",
        InLimits(),
        "scalar caps and floors the sentries compare against; a guard, so a key may not be dropped",
        maxes=lambda: live_bounds("max"),
        mins=lambda: live_bounds("min"),
    ),
    Source(
        "eval-sites", "test_source_hygiene.py", in_code("test_source_hygiene.py", "_EVAL_ALLOWLIST")
    ),
    Source(
        "phase-containment",
        "test_phase_containment.py",
        in_code("test_phase_containment.py", "EXEMPT"),
    ),
    Source(
        "validate-no-mutation",
        "test_validate_no_mutation.py",
        in_code("test_validate_no_mutation.py", "ALLOWLIST"),
    ),
    Source(
        "physical-seam-connected",
        "test_physical_seam_disconnection.py",
        in_code("test_physical_seam_disconnection.py", "DELIBERATELY_CONNECTED_MODULES"),
    ),
    Source(
        "wave-b-string-target-exempt",
        "test_engine_string_targets.py",
        in_code("test_engine_string_targets.py", "EXEMPT"),
    ),
    Source(
        "wave-b-e0-test-files",
        "test_wave_b_no_registry_version_literal.py",
        in_code("test_wave_b_no_registry_version_literal.py", "E0_TEST_FILES"),
    ),
    Source(
        "handler-row-guard-exempt",
        "test_handler_row_guard_call_sites.py",
        in_code("test_handler_row_guard_call_sites.py", "_ALLOWED"),
    ),
    Source(  # live keys: the registry rows marked private that are not on write_private yet
        "private-file-sinks",
        "tests/sentry/baselines/private-file-sinks.json",
        lambda: {
            "entry::" + "::".join(str(e[f]) for f in ("module", "function", "sink", "ordinal"))
            for e in tomllib.loads(
                (SENTRY / "file_access_registry.toml").read_text(encoding="utf-8")
            )["entry"]
            if e.get("disposition") == "private"
        },
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "parquet-intermediate-writers",
        "tests/sentry/baselines/parquet-intermediate-writers.json",
        lambda: set(
            json.loads(
                (BASELINES / "parquet-intermediate-writers.json").read_text(encoding="utf-8")
            )["entries"]
        ),
        maxes=self_maxes("parquet-intermediate-writers"),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "metadata-carrier-allow",
        "tests/sentry/baselines/metadata-carrier-allow.json",
        lambda: set(
            json.loads((BASELINES / "metadata-carrier-allow.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
        maxes=self_maxes("metadata-carrier-allow"),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "serial-resources",
        "tests/sentry/baselines/serial-resources.json",
        lambda: set(
            json.loads((BASELINES / "serial-resources.json").read_text(encoding="utf-8"))["entries"]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "exception-context",
        "tests/sentry/baselines/exception-context.json",
        lambda: set(
            json.loads((BASELINES / "exception-context.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "validation-name-messages",
        "tests/sentry/baselines/validation-name-messages.json",
        lambda: set(
            json.loads((BASELINES / "validation-name-messages.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "gcs-call-kwargs",
        "tests/sentry/baselines/gcs-call-kwargs.json",
        lambda: set(
            json.loads((BASELINES / "gcs-call-kwargs.json").read_text(encoding="utf-8"))["entries"]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-blocking",
        "tests/sentry/baselines/post-scan-blocking.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-blocking.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-pass-through",
        "tests/sentry/baselines/post-scan-pass-through.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-pass-through.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-key-core",
        "tests/sentry/baselines/post-scan-key-core.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-key-core.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-reason-identity",
        "tests/sentry/baselines/post-scan-reason-identity.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-reason-identity.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-gate-applies",
        "tests/sentry/baselines/post-scan-gate-applies.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-gate-applies.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-commit",
        "tests/sentry/baselines/post-scan-commit.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-commit.json").read_text(encoding="utf-8"))["entries"]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-model-predicate",
        "tests/sentry/baselines/post-scan-model-predicate.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-model-predicate.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(  # keys of the ratchet-schema baseline itself
        "post-scan-readability",
        "tests/sentry/baselines/post-scan-readability.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-readability.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(
        "post-scan-route-coverage",
        "tests/sentry/baselines/post-scan-route-coverage.json",
        lambda: set(
            json.loads((BASELINES / "post-scan-route-coverage.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
    Source(
        "strategy-docs-agree",
        "tests/sentry/baselines/strategy-docs-agree.json",
        lambda: set(
            json.loads((BASELINES / "strategy-docs-agree.json").read_text(encoding="utf-8"))[
                "entries"
            ]
        ),
    ),
)

# Committed data a sentry reads that is a pinned contract, not an allowlist that could grow.
# Each is held by its own digest or golden test.
NOT_A_LIST: dict[str, str] = {
    "route-format-matrix-v1.json": "pinned F06 route matrix, compared whole by test_f06_route_matrix",
    "capability-manifest-v1.json": "pinned F06 capability catalog, compared whole",
    "legacy-compat-baseline.json": "pinned F06 legacy config fixture, compared whole",
    "proof-manifest.json": "generated proof page data, regenerated and compared by test_proof_manifest",
    "reason-manifest-v1.json": "released reason manifest, frozen by the F29 registry tests",
    "reason-manifest-v1.4-f06.json": "released reason manifest, frozen by the F29 registry tests",
    "reason-manifest-v1.6-sub-stop.json": "released reason manifest, frozen by the F29 registry tests",
    "reason-manifest-v1.7-lib-l0-1.json": "released reason manifest, frozen by the F29 registry tests",
    "reason-manifest-v1.19-config-explicit-e2a.json": (
        "released reason manifest, frozen by the F29 registry tests"
    ),
    "reason-manifest-v1.15-config-explicit-e1.json": (
        "released reason manifest, frozen by the F29 registry tests"
    ),
    "reason-manifest-v1.8-scanml-m1.json": "released reason manifest, frozen by the F29 registry tests",
    "reason-registry-release.json": "released reason registry, frozen by the F29 registry tests",
    "consumer-contract.json": "F29 consumer contract, compared whole by test_reason_registry",
    "openapi.json": "generated schema used as a negative fixture in a residual-surface test",
    "file_access_registry.toml": "file access registry, allowed to grow; guarded by its Count header",
    "required_serial.toml": "grow-only serial-test registry; removal needs a [[removed]] reason and every id is checked at collection",
    "file_access_modules.toml": "file access module list, allowed to grow with new access modules",
}


def baseline_path(sentry_id: str) -> Path:
    return BASELINES / f"{sentry_id}.json"


def write_initial() -> None:
    """One-off: write each baseline from its live source. Refuses to overwrite (no add mode)."""
    BASELINES.mkdir(exist_ok=True)
    rows = []
    for src in SOURCES:
        path = baseline_path(src.sentry_id)
        if path.exists():
            raise SystemExit(f"{path} exists; baselines only shrink after the first inventory")
        reason = f"initial X0a inventory of {src.where}; existing entry, reviewed by its own sentry"
        entries: dict[str, dict[str, object]] = {k: {"reason": reason} for k in sorted(src.keys())}
        for k, value in (src.maxes() if src.maxes else {}).items():
            entries[k]["max"] = value
        for k, value in (src.mins() if src.mins else {}).items():
            entries[k]["min"] = value
        doc = {"sentry_id": src.sentry_id, "created_in": CREATED_IN, "entries": entries}
        path.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        rows.append(
            f'[[sentry]]\nid = "{src.sentry_id}"\nbaseline = "tests/sentry/baselines/{path.name}"\n'
        )
    reg = ROOT / "scripts" / "dev" / "sentry_registry.toml"
    reg.write_text(
        reg.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + "\n".join(rows), encoding="utf-8"
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--write-initial"]:
        write_initial()
    else:
        raise SystemExit("usage: _baseline_sources.py --write-initial")
