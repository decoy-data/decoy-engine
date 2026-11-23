# ROUTE-RULES: one facts object and one rule list for route selection

Status: plan (recommended; not yet scheduled on the roadmap)

Base: engine main `311ec14`. Six slices, engine only. No routing outcome changes in any slice.

**Guarantee.** For every job, the route, `route_reason`, refusal code and refusal message are
byte-identical before and after each slice. Slice 1 is the one exception and says so: it corrects
the physical compiler's inputs, which can change what the compiler reports, never what a run does.
**Non-goals:** changing any routing outcome; lifting a job that has both a vault and validators;
moving unified-slice admission out of the full-frame executor; removing row-count routing; changing
`execution_mode`, thresholds or any public knob.
**Design notes:** two new modules, `execution/_route_facts.py` and `execution/_route_rules.py`.

## Why

The routing policy is sound. The code that carries it cannot be read in one place, and the same
decision is derived in several places that tests hold together.

- `decide_execution_route` (`execution/_pipeline_routing.py`) takes 25 keyword arguments. Most are
  verdicts worked out by `resolve_execution_route` in `_pipeline_routing_signals.py`, so reading
  the decision means reading both modules.
- `_sequential_eligible` returns only the first disqualifier. To lift a vault or validators the
  router calls it twice more with one argument blanked.
- The bounded-route decision is re-derived in four places:
  `bounded_admission` (`_pipeline_routing.py`, used by `pipeline/_lazy_input.py`),
  `check_rejections_before_preparation` (`_transforms_admission.py`),
  `out_of_core_not_ready_reason` (`physical/_compiler.py`) and
  `_out_of_core_decision` (`pipeline/_stream.py`).
- `decide_execution_route` has five production call sites, each assembling the arguments itself:
  `resolve_execution_route`, `capacity.py` (two), `_job_estimate.py` and
  `physical/_compiler.py::layer1_route`. The last one never passes `mixed_admitted`,
  `vault_ooc_safe` or `validators_ooc_safe`, so they default to `False` there.
- Stream, mixed, FK routing, chunk classification, the multi-table split and the resident-fit
  refusal are decided in different modules and assembled in `_pipeline_context.decide_route`.
- Two `RouteDecision` classes and two `decide_route` functions exist
  (`_pipeline_context.py`, `out_of_core/_route_policy.py`).
- `_pipeline_routing.py` says `use_byte_estimate_routing` "defaults False"; the signature defaults
  it to `True`. `docs/execution-backends.md` says layer 2 is reached only when layer 1 did not
  return sequential; `decide_route` calls it on every route.

## Facts this plan relies on

Checked on the base commit.

- Row-count routing is live, not a rollback path. `capacity.py` and `_job_estimate.py` pass
  `use_byte_estimate_routing=False` on purpose: they never read a source, so there is no resident
  sample to price. Generate+mask FK jobs are outside the byte estimate's scope and use it too.
- Routing is not metadata-only. The byte estimate samples resident columns, the probe runs a
  downscaled copy of the job in a child process, and the resident-fit check reads the host memory
  ceiling. The invariant that holds is: routing reads no rows from a source that is not already
  in memory, at most a file footer.
- Probes are gated. `resolve_probe_recovery` and `gather_resident_fit` run a probe only when the
  static estimate is inconclusive.
- Tests call `decide_execution_route` directly 38 times across 36 files.
- `_pipeline_context.py` is 600 lines and `_pipeline_routing_signals.py` is 613 against a ceiling
  of 633 (`tests/sentry/test_module_size.py`). New code goes in new modules.

## Design

Three steps: gather, decide, execute.

**`JobFacts`** (`_route_facts.py`) is a frozen dataclass of plain values. No profile, plan, graph
or writer object is held, so two facts objects compare equal when they describe the same job.

| Field | Replaces |
| --- | --- |
| `mode` | `execution_mode` |
| `has_relationships`, `has_mask_table`, `has_generate_table` | `profile.relationships`, the two table-kind flags |
| `disqualifiers: frozenset[str]` | every reason `_sequential_eligible` can return, all of them at once |
| `cyclic` | `_has_cross_table_fk_cycle(graph)` |
| `ooc_compatible`, `ooc_reject_code` | the compatibility gate's verdict |
| `ooc_dtype_hazard`, `vault_ooc_safe`, `validators_ooc_safe` | the three out-of-core safety verdicts |
| `largest_rows`, `largest_rows_exact` | the size signal |
| `ooc_threshold_rows`, `full_frame_reject_rows` | the two thresholds |
| `byte_estimate_enabled`, `full_frame_fits` | the flag and the tri-state estimate |
| `probe_enabled`, `probe_fits` | the flag and the tri-state probe result |
| `lazy_transform_bearing`, `mixed_admitted` | unchanged |

`disqualifiers` keeps a fixed priority order (the order of the checks in `_sequential_eligible`
today), so the reported `route_reason` is the first one in that order, as now. A lift is a set
test: the vault lift applies when the set is exactly `{vault_writer_requested}`, the validators
lift when it is exactly `{validators_present}`. A job with both is lifted by neither, which is
today's behaviour.

**`decide(facts) -> (route, reason)`** (`_route_rules.py`) is one function that walks the rules
below in order and returns the first match, or raises the typed refusal. It reads nothing but
`facts`. The order is today's order.

1. `mode == "full_frame"`: full-frame, `override_full_frame`.
2. `mode == "out_of_core"`: refuse without a mask table, with any disqualifier, or when not
   compatible; else out-of-core.
3. `mode == "sequential"`: refuse with any disqualifier, a cycle, or no mask table; else sequential.
4. Mixed admitted and no post-scan-resident disqualifier: mixed.
5. Lazy transform-bearing FK mask job: sequential when bounded-eligible, else refuse.
6. Byte estimate in scope (enabled, relationships, mask table, no generate table), in order:
   lifted and fits, out-of-core; fits and not bounded-eligible, full-frame; probe fits and not
   bounded-eligible, full-frame; fits or probe fits with a dtype hazard, sequential;
   bounded-eligible and compatible, out-of-core; bounded-eligible, sequential; else refuse.
7. Row count (everything else): compatible, bounded-eligible and at or above the out-of-core
   threshold, out-of-core; bounded-eligible, sequential; relationships and at or above the reject
   threshold, refuse (the `_estimated` code for a CSV count); else full-frame.

**`gather_facts(ctx)`** builds `JobFacts` for a real run. It keeps today's probe gating, so a job
pays for a probe only when it does now. The estimators and the physical compiler build `JobFacts`
from their own inputs through a second constructor that takes what they already hold.

**`Decision`** (slice 5) replaces `_pipeline_context.RouteDecision`: route, reason, chunk
classification, split, mixed plan, stream verdict, resident fit. Executors receive it and do not
re-decide. The chunk classification stays in the facts on every route so `explain_plan` can show
it; it does not take part in rules 1 to 7.

## Slices

One pull request each. Every slice leaves the full suite green.

1. **Fixes that need no design.**
   - Correct the "defaults False" comment in `_pipeline_routing.py`.
   - Pass `mixed_admitted`, `vault_ooc_safe` and `validators_ooc_safe` from
     `physical/_compiler.py::layer1_route`. First write a test that compares its route to
     `resolve_execution_route` for a mixed job and a vault job that fits; if the test already
     passes, record why the defaults are unreachable there and leave the call alone.
   - Correct the layer 2 sentence in `docs/execution-backends.md`.
2. **Snapshot, then `JobFacts` and `decide`.** No production caller yet.
   - Land the snapshot first (CLAUDE.md: snapshot before extraction): a generated table of
     inputs to `(route, reason)` or `(refusal code, message)` from the current
     `decide_execution_route`, committed as a fixture.
   - Add `_route_facts.py`, `_route_rules.py` and a test that runs `decide` over the same inputs
     and compares with the snapshot.
   - Domain. The full product of the inputs is about 75 million cases, too many to run. Enumerate
     every non-disqualifier field exhaustively, with four row counts (none, below the out-of-core
     threshold, between the thresholds, at the reject threshold), against a chosen list of
     disqualifier sets: empty, each of the eight alone, vault with validators, validators with
     fidelity. Prune by mode (a forced mode reads no size or estimate field). Add a seeded random
     sample over all 256 disqualifier subsets. The builder measures the run time and records the
     final domain in the test; the target is under 10 seconds in the default suite.
3. **`decide_execution_route` becomes an adapter.** It keeps its signature, builds `JobFacts` and
   calls `decide`. The old body is deleted. The five callers and the 38 direct test calls are
   untouched and act as the second proof. The snapshot test now guards `decide` alone.
4. **The four copies read `JobFacts`.** `bounded_admission`, `check_rejections_before_preparation`,
   `out_of_core_not_ready_reason` and `_out_of_core_decision` each ask the facts. Delete
   `BoundedAdmission` and `test_the_predicate_and_the_router_agree_on_bounded_admission`. Keep the
   source-scan test in `test_lazy_input.py` that stops a copy from coming back, retargeted at the
   new owner.
5. **One `Decision`.** May split per route kind.
   - Fold mixed admission, the chunk classification, the multi-table split, the resident-fit
     refusal and the stream pre-route into the rule list, in today's order.
   - `decide_stream_route` re-enters `decide_route` with a forced mode today; it becomes a facts
     rewrite followed by one `decide` call.
   - Rename `out_of_core/_route_policy.py`'s `RouteDecision` and `decide_route` (they choose a
     join driver inside the out-of-core route, not a route).
6. **Remove the adapter.** Move the callers and the direct test calls to `JobFacts`, delete the
   keyword signature and `resolve_execution_route`, and remove task and sprint codes from the
   comments of the modules this plan touched. Promote the rule list above into
   `docs/execution-backends.md` and archive this plan.

Slices 1 to 4 are low risk and remove most of the duplication. Slice 5 carries the most change.

## What must hold after every slice

- **Fail closed.** A forced mode that does not fit raises; it never falls through.
- **Reject before read.** A large FK job no bounded route can take raises
  `fk_full_frame_oom_risk_rejected` (or `_estimated`); a no-FK job that cannot fit is refused by
  the resident-fit check before any output opens.
- **No unread source is read.** See "Facts this plan relies on".
- **Bounded first.** A bounded-eligible job takes a bounded route even when it would fit.
- **Out-of-core eligibility is a subset of sequential eligibility.** The reject branch is safe at
  any ordering of the two thresholds because of it.
- **Cycles never go bounded.**
- **Exact codes and messages.** `route_reason`, refusal codes and refusal text do not change.
- **The full-frame oracle.** Every native route stays byte-identical to it.

## Verification

Baseline on the base commit: 1,324 passed, 1 skipped for

```bash
python -m pytest tests/unit/execution/test_pipeline_routing_route_kills.py tests/unit/execution/run_stream tests/sentry/test_f06_declared_casting.py tests/sentry/test_module_size.py
```

Each slice also runs the routing unit tests under `tests/unit/execution/` (`test_pipeline_routing*`,
`test_byte_estimate_routing.py`, `test_probe_routing.py`, `test_out_of_core_routing.py`,
`test_prefer_bounded_fk_routing.py`, `test_route_decision_split.py`), the physical-plan tests and
the out-of-core parity suites under `tests/parity/`. Those were not run for this plan.

## Open decisions

- **Roadmap row.** This plan has no row in the cross-repo roadmap yet; it needs one before work
  starts.
- **Vault with validators.** The set form makes lifting both a one-line change. It is a routing
  change and wants its own plan after slice 6.
- **Unified slice.** Its admission was not examined here. Moving it into `decide` is possible only
  if the check is static; the executor would keep a runtime guard.
- **Slice 1, compiler arguments.** Whether the missing arguments cause a wrong report today is
  not yet reproduced; the slice's first test settles it.
