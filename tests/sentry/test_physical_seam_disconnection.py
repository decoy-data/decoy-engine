"""D4 disconnection proof: the physical-execution adapter seam
(Task 4.2, `decoy_engine.execution.physical`) is REACHED BY NOTHING in
production -- except the one sanctioned Task 4.5 connection point.

Mirrors `test_public_import_boundary.py`'s regex-sentry pattern for the
opposite direction: that file guards the public boundary from reaching INTO
`internal.*`; this one guards every current route/coordinator/executor/
generation module from reaching INTO the new `execution.physical` package.
Task 4.2 is additive and disconnected by design (docs/plans/2026-09-13-
physical-plan-design.md; production activation is Task 4.5+) -- this test is
what keeps that true as the seam grows.

The byte-identical diff gate against `origin/main` that used to sit beside
these checks was deleted (owner decision 2026-11-15); the import-direction
checks below are what remains of the seam guard.

Task 4.3 (the physical-plan compiler, `_compiler.py` / `_inputs.py` /
`_snapshot.py` / `_reasons.py` / `_plan.py`) extends this same disconnection
proof rather than adding a parallel one: `GUARDED_MODULES` already covers
every module the compiler's own snapshot builder (`capture_physical_plan_
inputs`) imports from (`_pipeline_routing`, `_planner`, ...), so the existing static regex sweep already
re-verifies 4.3's disconnection unmodified. The one
genuine addition below (`test_compile_physical_plan_is_unreachable_from_a_
fresh_import_of_run_pipeline`) is DYNAMIC rather than static: it proves, in
a fresh subprocess, that importing `decoy_engine.execution.run_pipeline`
never pulls `execution.physical` into `sys.modules` -- a complementary check
the regex sweep (which only reads source text) cannot make, since a hidden
dynamic/conditional import would not appear as a matchable `import`
statement at all.

Task 4.5 (engine production-readiness) is the connection this test's own
docstring always named as the point the seam stops being fully disconnected:
a single new module, `execution/_unified_slice.py`, is now the ONE place
outside `execution/physical/` allowed to import it -- behind a default-OFF
per-run flag it checks BEFORE ever reaching for the seam (see that module's
own docstring). `DELIBERATELY_CONNECTED_MODULES` below is that one-file
allowlist; every OTHER production module stays exactly as disconnected as
`GUARDED_MODULES` + the broad sweep already proved. `run_pipeline`
(`_pipeline.py`) itself is unchanged in this respect: it imports
`_unified_slice`, a sibling execution module, never `execution.physical`
directly, so it still passes the static regex sweep below with no
modification.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from tests.sentry.layout._reexport_init import imports_physical, is_pure_reexport_init

ENGINE_ROOT = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
REPO_ROOT = ENGINE_ROOT.parents[1]

# Every current production entry/coordinator/router/executor module the
# design doc names as a driver's real delegate, plus the routing-decision
# layers that select between them. If a NEW module needs to route through
# physical/ someday, that is Task 4.5+ and this list (or the whole test)
# must be revisited deliberately -- not silently pass because a new file
# never got added here.
GUARDED_MODULES: tuple[str, ...] = (
    "execution/_pipeline.py",
    "execution/pipeline/_subset_stage.py",
    # PS-7: the post-scan gate core checks outputs before commit; no physical import.
    "execution/pipeline/_post_scan.py",
    "execution/_pipeline_routing.py",
    "execution/_pipeline_routing_signals.py",
    "execution/_pipeline_chunk_route.py",
    "execution/_pipeline_route_exec.py",
    # R3: the resolve/route context and the layer-1 route dispatch adapters. Routing and
    # executor modules, so neither may import `execution.physical`.
    "execution/_pipeline_context.py",
    "execution/_pipeline_route_dispatch.py",
    "execution/_pipeline_full_frame.py",
    # F2 (production mixed route): the shared admission core, FK bridge, static admission,
    # pre-resolved-column carrier and executor. Production routing code, so none may import
    # `execution.physical`; the shadow imports the first two, never the reverse.
    "execution/_mixed_admission.py",
    "execution/_mixed_fk_bridge.py",
    "execution/_mixed_static.py",
    "execution/_chunked_preresolved.py",
    "execution/_pipeline_mixed_route.py",
    # B2 (auto-chunk on the chunked dispatcher): a routing executor, so it must
    # not import `execution.physical` either.
    "execution/_pipeline_auto_chunk.py",
    # B7 (independent multi-table dispatch): another routing executor, it calls
    # `run_auto_chunk` per table and must not import `execution.physical` either.
    "execution/_pipeline_multi_table.py",
    # RUN-STREAM E1a: the strict stream preflight is routing code and must not import the seam.
    "execution/pipeline/_stream.py",
    # RUN-STREAM E3: the route summary only reads recorded metrics; no physical import.
    "execution/pipeline/_route_summary.py",
    # RUN-STREAM E5: the resident-fallback pre-pass reads config, profile and plan owners
    # only; no physical import.
    "execution/pipeline/_lazy_input.py",
    # The routing facts the run context and the pre-pass share: declaration, profile, plan and
    # graph owners only; no physical import.
    "execution/pipeline/_routing_facts.py",
    # B6a (incremental output sink): the streamed lane's row-group assembly and publish
    # session sit between the dispatcher lane and the caller's sink; no physical import.
    "execution/_chunked_output_sink.py",
    # B6b (LazySource batch input): footer-fact capture, the batch re-cut and the handle
    # lifecycle for a lazy routed table; no physical import.
    "execution/_chunked_input.py",
    "execution/_pipeline_sources.py",
    "execution/_pipeline_finalize.py",
    "execution/_planner.py",
    "execution/_pandas_adapter.py",
    "execution/_sequential.py",
    "execution/_chunked.py",
    "execution/chunked/_progress.py",
    "execution/_adapter.py",
    "execution/_substrate.py",
    "execution/_runner.py",
    "execution/native/_dispatch.py",
    "execution/native/_plan.py",
    "execution/native/_requirements.py",
    "execution/native/_capabilities.py",
    # R1b: the resolved per-operator parameters and the shared kernel step both native routes
    # call. They are leaf modules under `native/`, which must not reach the physical seam.
    "execution/native/_operator_params.py",
    "execution/native/_operator_step.py",
    "execution/out_of_core/_runner.py",
    "execution/out_of_core/_rewrite_pass.py",
    "execution/out_of_core/_compat.py",
    "execution/out_of_core/_preflight.py",
    "execution/out_of_core/_null_int_guard.py",
    "execution/out_of_core/_route_policy.py",
    "generation/_plan_entry.py",
    "generation/synthesize.py",
)


# Task 4.5's sanctioned connection points: the ONLY files outside
# `execution/physical/` itself permitted to import the seam. Widening this
# is a deliberate, reviewed decision (the next task after 4.5 to touch
# production routing), never an incidental add. `_unified_slice_admission.py`
# is the D3 admission-predicate module `_unified_slice.py` was split out of
# to hold the ~600-LOC orchestration cap; its `resident_contract_admission`
# reaches for `execution.physical._types.DriverId`, lazily, behind the same
# flag-checked-before-import discipline. `_unified_slice_resident_types.py` is the
# per-strategy resident-type gate module split out of it (C5a remediation, pure move); it
# keeps the one `PhysicalTable` annotation import, under TYPE_CHECKING.
# `_unified_slice_evidence.py` holds the completed-evidence assembly and the output
# reconstruction split out of `_unified_slice.py`; it imports physical types only for
# annotations, under TYPE_CHECKING.
DELIBERATELY_CONNECTED_MODULES: tuple[str, ...] = (
    "execution/_unified_slice.py",
    "execution/_unified_slice_admission.py",
    "execution/_unified_slice_resident_types.py",
    "execution/_unified_slice_evidence.py",
)


def _imports_physical(path: Path) -> bool:
    return imports_physical(path, ENGINE_ROOT)


def test_guarded_modules_exist() -> None:
    missing = [rel for rel in GUARDED_MODULES if not (ENGINE_ROOT / rel).exists()]
    assert not missing, (
        "GUARDED_MODULES entries that do not exist on disk (update the list if "
        "one of these was intentionally removed/renamed):\n  - " + "\n  - ".join(missing)
    )


def test_no_production_module_imports_the_physical_seam() -> None:
    offenders = [rel for rel in GUARDED_MODULES if _imports_physical(ENGINE_ROOT / rel)]
    assert not offenders, (
        "Production execution/generation modules importing "
        "decoy_engine.execution.physical (the Task 4.2 seam is additive and "
        "must not be wired into any live route until Task 4.5+):\n  - " + "\n  - ".join(offenders)
    )


def test_no_module_anywhere_under_src_imports_the_physical_seam_except_itself() -> None:
    """Broader sweep than `GUARDED_MODULES`: NOTHING under `src/decoy_engine`
    outside the `execution/physical/` package itself -- or the one Task 4.5
    `DELIBERATELY_CONNECTED_MODULES` entry -- may import it. Catches a future
    module neither list has been updated to name yet."""
    offenders: list[str] = []
    for path in ENGINE_ROOT.rglob("*.py"):
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        if rel.startswith("execution/physical/") or rel in DELIBERATELY_CONNECTED_MODULES:
            continue
        if _imports_physical(path):
            offenders.append(rel)
    assert not offenders, (
        "Modules outside execution/physical/ (and outside "
        "DELIBERATELY_CONNECTED_MODULES) importing decoy_engine.execution.physical:\n  - "
        + "\n  - ".join(offenders)
    )


def test_deliberately_connected_modules_exist_and_do_import_physical() -> None:
    """The flip side of the sweep above: every allowlisted module must both
    exist and actually import the seam, so the allowlist cannot silently
    become stale (a removed/renamed file that no longer needs the
    exemption) without a test failure pointing at it."""
    for rel in DELIBERATELY_CONNECTED_MODULES:
        path = ENGINE_ROOT / rel
        assert path.exists(), f"DELIBERATELY_CONNECTED_MODULES entry does not exist: {rel}"
        assert _imports_physical(path), (
            f"{rel} is listed in DELIBERATELY_CONNECTED_MODULES but does not import "
            "decoy_engine.execution.physical; remove it from the allowlist if that is intended"
        )


# ---------------------------------------------------------------------------
# Task 4.3 addition: a DYNAMIC check, in a fresh subprocess, that importing
# `run_pipeline` never pulls `execution.physical` into `sys.modules`.
# ---------------------------------------------------------------------------

_FRESH_IMPORT_PROBE = (
    "import sys\n"
    "from decoy_engine.execution import run_pipeline\n"
    "assert callable(run_pipeline)\n"
    "hits = [name for name in sys.modules if name.startswith('decoy_engine.execution.physical')]\n"
    "print(','.join(sorted(hits)))\n"
)


def test_compile_physical_plan_is_unreachable_from_a_fresh_import_of_run_pipeline() -> None:
    """A fresh interpreter that imports only `decoy_engine.execution.
    run_pipeline` (production's real entry point) must never end up with any
    `decoy_engine.execution.physical*` module in `sys.modules` -- proof by
    dynamic observation, not source-text pattern matching, that nothing on
    the real import path reaches the compiler package."""
    result = subprocess.run(
        [sys.executable, "-c", _FRESH_IMPORT_PROBE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    hits = [name for name in result.stdout.strip().split(",") if name]
    assert not hits, (
        "Importing decoy_engine.execution.run_pipeline in a fresh interpreter "
        "pulled in execution.physical module(s), which must stay unreachable "
        "from production until Task 4.5+:\n  - " + "\n  - ".join(hits)
    )


def test_no_hand_entry_is_a_pure_reexport_init() -> None:
    """A hand entry for a pure re-export is dead: the rule already permits the file."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    entries = {
        n.value if n.value.startswith("src/") else f"src/decoy_engine/{n.value}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.endswith("/__init__.py")
        and "execution/" in n.value
    }
    dead = sorted(e for e in entries if is_pure_reexport_init(REPO_ROOT / e))
    assert dead == [], f"remove these hand entries, the rule covers them: {dead}"
