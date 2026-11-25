# Execution backends and route coverage

What actually computes each masking strategy, by route, and where a shape is
declined with a caller-visible reason instead of run natively. Generation is
covered at the end.

This page is a human-readable reading of the authoritative, test-enforced sources:
the per-operator compute classification in
`docs/records/2026-10-16-d-audit-compute-matrix.md`
(masking) and the generation compute audit (the
[F-audit plan](https://github.com/decoy-data/decoy-engine/blob/main/docs/plans/2026-10-19-phase-f-f-audit-no-legacy.md)).
The enumerated strategy/provider list is [`capability-matrix.md`](capability-matrix.md);
install and wheel/ABI facts are [`native/supported-matrix.md`](native/supported-matrix.md).
If this page and those sources ever disagree, the sources win: they are derived from
the dispatch constants and guarded by parity tests, this page is prose.

The ExecutionAdapter substrate is pandas-only and there is no setting for it. Execution routes
are separate from the substrate. Rust and Arrow kernels can run inside those routes.

## Backends, in one line each

- **compiled Rust kernel**: the native companion owns the compute. `text_redact` is Rust
  span detection with the splice in Python. `text_mask` is Rust span detection, with native
  splice/FPE paths for admitted `text_mask` configurations and Python splice fallback.
- **compiled index selection**: `faker` draws from a pool via the compiled index kernel.
- **named-Arrow**: `redact` / `truncate` run as Arrow array kernels (`redact_array` /
  `truncate_array`), no companion needed.
- **no-op**: `passthrough` carries the column through untouched.
- **dedicated Python**: a named handler or primitive with no Rust or Arrow kernel. This is
  the designed compute for that strategy on that route, not the generic pandas fallback for
  an admitted kernel cell.
- **key declined, reporting-only**: used only for an FK key. The strategy is not admitted as
  a native key, so its Python handler runs in place for the key as a reporting-only entry;
  the job is not rerouted and the key surface stays correct.
- **excluded**: not admitted on that route (an off-the-key-surface FK cell, a native-chunked
  FK cell, or the full-frame oracle itself).
- **declined (caller-visible reason)**: a route decline excludes the job from that route.
  Auto routing can choose sequential or full-frame, subject to memory admission. A forced
  incompatible route raises an error. A native-kernel decline can instead retain the current
  route and use its reference implementation. Backend evidence identifies that choice. This is
  distinct from a reporting-only key decline, which runs in place.
- **full-frame oracle**: the pandas adapter is the reference oracle for every native route,
  and the path a native cell downgrades to (with a coded reason, byte-identical) when the
  companion is absent. A few cells, such as out-of-core `bucket_perturb`, keep a dedicated
  companion-absent Python bridge instead. The full-frame route can also run the unified native
  slice.

The compiled companion is reachable only from masking. Generation never calls it (see
"Generation" below).

## Masking by route

The router selects an execution route from job shape, eligibility, and memory signals.
`execution_mode` can force a supported route. A caller does not select a masking
backend. Default byte-estimate routing can select OOC below five million
rows. The row threshold applies when byte-estimate routing is disabled. A confirmed probe can
select full-frame. The router lives in
[`_pipeline_routing.py`](../src/decoy_engine/execution/_pipeline_routing.py). Byte-parity with
the full-frame oracle is mandatory on every native route.

These cells identify available native implementations, not unconditional admission.
Configuration, source dtype, companion availability, and runtime guards still apply. A Python
fallback inside an admitted route is distinct from a route rejection. The per-strategy
qualifications are in [Native admission qualifications](#native-admission-qualifications)
below.

### Sequential route (FK, table-at-a-time)

| Strategy | Payload | As an FK key |
| --- | --- | --- |
| `hash`, `fpe` | compiled Rust | compiled Rust |
| `categorical`, `bucket_perturb`, `date_shift` | compiled Rust | dedicated Python (key declined, reporting-only) |
| `faker` | compiled index selection | dedicated Python (key declined, reporting-only) |
| `text_redact`, `text_mask` | compiled Rust spans; `text_redact` Python splice, `text_mask` native splice/FPE for admitted configs with Python splice fallback | dedicated Python (key declined, reporting-only) |
| `redact`, `truncate` | named-Arrow | named-Arrow |
| `passthrough` | no-op | no-op |
| `code_set` | dedicated Python | dedicated Python |
| `bucketize`, `shuffle`, `top_code`, `formula`, `derived`, `derived_aggregate`, `nested`, `joint_mask`, `geo_generalize`, `grouped_series`, `windowed_date` | dedicated Python (shared handler, no SEQ native admission) | dedicated Python |
| `group_key` | compiled raw-hex kernel when the `group_by` sibling is admitted (`_sequential_native_group_key.py`, `decide_group_key`); otherwise the shared Python handler | dedicated Python |

A non-injective but natively-capable strategy used as an FK key is declined with a
reporting-only entry and the Python handler runs; the key surface stays correct.

### Out-of-core route (payload; large FK jobs that spill)

The FK key surface here is only `hash`, `redact`, `truncate`, `passthrough`.

| Strategy | Payload | Parent-key strategy |
| --- | --- | --- |
| `hash` | compiled Rust | compiled Rust (needs a namespace) |
| `fpe`, `text_redact` | compiled Rust | excluded (off the key surface) |
| `categorical` (deterministic) | compiled Rust | excluded (off the key surface) |
| `bucket_perturb` (explicit `date_format`) | compiled Rust | excluded (off the key surface) |
| `redact`, `truncate` | named-Arrow | named-Arrow |
| `passthrough` | no-op | no-op |
| `text_mask` | compiled span kernel for an admitted non-NER config on an exact-string source (`out_of_core/_text_mask_native.py`); NER configs and other sources stay on the dedicated Python per-cell loop | excluded (off the key surface) |
| `code_set` (mask mode without `chapter_preserve`) | dedicated Python (no kernel on any route; backlog: Arrow dict-map) | excluded (off the key surface) |
| `faker` (deterministic REUSE, exact-string, person-name provider) | compiled index selection | excluded (off the key surface) |
| `date_shift`, `bucketize` | declined (`out_of_core_row_error_strategy_unsupported`) | excluded (off the key surface) |
| `categorical` (non-deterministic) | declined (`out_of_core_categorical_nondeterministic_unsupported`) | excluded (off the key surface) |
| `geo_generalize` | declined (`out_of_core_whole_column_aggregation_unsupported`) | excluded (off the key surface) |
| `formula`, `derived` | declined (`out_of_core_dynamic_output_type_unsupported`) | excluded (off the key surface) |
| `nested` | declined (`out_of_core_child_dispatch_unsupported`) | excluded (off the key surface) |
| `grouped_series`, `windowed_date`, `derived_aggregate`, `group_key`, `joint_mask` | declined (`out_of_core_cross_row_strategy_unsupported`) | excluded (off the key surface) |
| `shuffle`, `top_code` | declined (`out_of_core_strategy_unsupported`) | excluded (off the key surface) |

These cells describe main. A later slice (B1) changes the `date_shift`/`bucketize` cells after
its own merge. A `bucket_perturb` payload with no explicit `date_format` declines separately
with `out_of_core_bucket_perturb_autodetect_unsupported`; whole-column format auto-detection
does not chunk.

Parent-key masking and orphan remapping have separate compute paths. Native hash masks
admitted parent batches. Hash remapping currently uses the Python reference. Other payload
strategies are excluded as parent-key strategies, even when their payload implementation is
native.

On this route a composite FK whose child columns would be masked independently as scalars is
declined (`out_of_core_composite_fk_scalar_child_unsupported`); the canonical
`composite_fk_group` unit is admitted and pinned strictly against the full-frame oracle
(`tests/parity/test_phase_d_dcomp_composite_ooc*.py`; the recorded differences are in
`tests/parity/SEMANTIC_DIFFERENCES.md`). A composite chain, a composite child used as a parent
key, is declined (`out_of_core_composite_fk_chain_unsupported`) and runs on the sequential
route; a `uint64` or `decimal` key component fails closed at the joiner
(`out_of_core_fk_key_dtype_unsupported`). A multi-parent child (more than one parent targeting
the same child FK column tuple) is admitted: the parents' key relations are merged
first-hit-wins in relationship order and the child is joined once, matching the full-frame
oracle (`tests/parity/test_phase_d_dmp_multi_parent_ooc*.py`); parents whose masked key types
differ fail closed (`out_of_core_fk_key_dtype_unsupported`) and the router keeps such a job on
the sequential route. Distinct child keys referencing different parents are supported as before.
A-9 delivered the admitted composite and multi-parent FK shapes. It did not schedule OOC
`date_shift`. OOC `faker` is admitted only for the deterministic-REUSE person-name variant on an
exact-string source (see the `faker` qualification below); other faker shapes decline. Composite scalar children, composite chains, and unsupported key
dtypes retain the restrictions above.

OOC also declines when predicates, unsupported non-scalar work, self-referential relationships,
and table-level cycles. The public supported-strategy set is only a coarse payload list. It does
not establish job admission or native dtype support.

#### Why the out-of-core route declines some payload strategies (known limitations, never a silent no-op)

Every decline above is a caller-visible coded reason, and the job runs the strategy on the
full-frame (or sequential) oracle instead; the out-of-core route never silently passes a column
through or drops a strategy. Some declines are inherent to a single-pass, per-column batch
stream and are not a near-term wiring gap:

- `faker` shapes outside the admitted variant (`out_of_core_faker_pool_unsupported`,
  `out_of_core_faker_source_type_unsupported`): the route has a bounded, run-scoped `PoolCache`
  (`out_of_core/_faker_pool.py`), but `_compat.py` admits only a provider on the native
  allowlist, `deterministic` with `cardinality_mode=reuse`, a namespace and an explicit
  `pool_size`, and a source column of exact `string` type. Any other shape declines and
  keeps the sequential or full-frame route; it is never a silent no-op.
- `geo_generalize` (`out_of_core_whole_column_aggregation_unsupported`): its k-anonymity cascade
  thresholds each row's generalization level on whole-dataset counts (ZIP5/ZIP3/state or H3
  resolutions), which a single chunk cannot see.
- `group_key`, `windowed_date`, `grouped_series`, `derived_aggregate`, `joint_mask`
  (`out_of_core_cross_row_strategy_unsupported`): each needs state the per-column kernel does not
  receive -- other columns of the same row (`group_key`), a durable global row ordinal
  (`windowed_date`), a per-group sequential stream (`grouped_series`), an intra-table aggregate
  (`derived_aggregate`), or a reference-table row (`joint_mask`). Admitting them needs a bounded
  relational lowering not yet built.
- `shuffle` (`out_of_core_strategy_unsupported`): a whole-column keyed permutation is
  order-sensitive and non-partitionable by construction, so it cannot stream per batch.
- `bucketize` / `date_shift` (`out_of_core_row_error_strategy_unsupported`): row-local in value,
  but they record per-value format errors that the full-frame path removes via a quarantine
  pass; the streaming route has no row-error/quarantine channel (`date_shift` without an
  explicit `date_format` also needs whole-column format detection). `top_code` is in the same
  class and declines through the generic surface for the same missing channel.
- `formula` / `derived` (`out_of_core_dynamic_output_type_unsupported`) and `nested`
  (`out_of_core_child_dispatch_unsupported`): their output Arrow type is not knowable from the
  plan alone (or they re-enter the full pandas child-strategy dispatch), which the fixed-schema
  streaming writer cannot satisfy.

These verdicts are pinned by `tests/parity/test_out_of_core_group_b_parity.py` and
`tests/parity/test_out_of_core_group_c_parity.py` (each asserts the exact coded reason), so a
future change that silently admitted one would fail the suite rather than leak a divergence.

### Native-chunked route (single-table, chunked)

FK-participating tables on either side reroute to the oracle
(`fk_relationship_not_native_route`), so no FK cell runs here. Non-FK payload follows the
operator registry: `hash`, `categorical`, `bucket_perturb`, `date_shift`, `fpe`,
`group_key` on compiled Rust; `faker` as compiled index selection; `redact` / `truncate`
as named-Arrow; `text_redact` / `text_mask` as the compiled span kernel behind an
`arrow_python` operator; `passthrough` as a no-op. For `text_redact` / `text_mask` the
chunked-route tests prove the `arrow_python` routing and byte-parity with the oracle, not
that the compiled span kernel is consumed; the compiled-span-consumption witness is the
sequential route's.

### Native admission qualifications

The route tables above identify available native implementations, not unconditional admission.
Each cell is further qualified by the guards below.

| Strategy | Exact qualification to document |
| --- | --- |
| `hash` | SEQ/OOC native hashing admits string, large_string, bool, and signed/unsigned integers. Timestamp types decline there. Chunked also admits timezone-aware timestamps through its shared predicate, subject to other guards. Namespace requirements remain enforced. |
| `fpe` | Native payload requires exact string, namespace, valid FPE configuration, and no checksum option. SEQ keys additionally admit supported integer representations. Do not imply all integer payloads are native. |
| `categorical` | SEQ/OOC native selection requires deterministic mode, namespace, exact-string source, string categories, and a buildable weighted CDF. Seeded positional categorical is separately native on chunked. OOC rejects its non-deterministic mode. |
| `bucket_perturb` | OOC requires explicit `date_format` at route admission. Native execution further requires exact string, namespace, supported bucket and format, no timezone or special pandas format, and valid preserve_values. Runtime range guards still apply. |
| `date_shift` | Native SEQ/chunked requires exact string, namespace, explicit non-special timezone-free format (plan compile requires one, except for a top-level declared-casting column), no group_by, integer day bounds within the accepted range, and valid preserve_values. Main OOC rejects the entire strategy. |
| `faker` | Providers are person_first_name and person_last_name on these native paths. SEQ admits exact string with deterministic REUSE or positional REUSE. Chunked additionally admits bool/integer deterministic REUSE with its fixed-schema producer guarantee and accepted conversion metadata. Positional bool/integer/float REUSE requires explicit pool_size. Other modes and providers use their existing Python path. OOC admits the deterministic-REUSE person-name variant with an exact-string source through the compiled index selection (run-scoped pool); other faker shapes, and a non-string source, decline. |
| `text_redact` / `text_mask` | Native paths have source/configuration guards. NER remains Python. OOC text_mask runs the compiled span kernel for an admitted non-NER config on an exact-string source (`out_of_core/_mask_group_c.py:224-227`); NER configs keep the dedicated loop, including batched NER inference. |
| `code_set` | OOC admits mask mode without chapter_preserve. Gen mode and chapter_preserve remain route declines. There is no named Arrow code-set kernel on main. |
| `group_key` | SEQ runs the raw-hex kernel when `decide_group_key` admits the column: the `group_by` sibling is present, is not the column itself, is unmasked and not an FK key or FK child, and has Arrow type string, int64 or bool (`_sequential_native_group_key.py:106-130`); anything else keeps the shared Python handler. Native chunked requires an exact string/int64/bool sibling, an unmasked non-self sibling, and valid even length in [8,64]. Unified full-frame also has a native implementation. |
| `redact` / `truncate` / `passthrough` | Keep the named-Arrow/no-op classifications, but do not promise arbitrary dtype/schema identity beyond each route's existing contract. |

Masked nullable integer columns under `truncate` or `categorical` can fail with
`null_bearing_int_unsupported`. FK children resolved through relationships are exempt.

### Dedicated-Python exceptions (the documented set)

These run their own Python handler by design, not the generic fallback:

- `code_set`: no native kernel on any route. It remaps each value through a required corpus
  state table (a keyed corpus lookup), which no per-value Arrow/Rust kernel carries today, so it
  runs its dedicated Python handler everywhere; backlog: kernelize as a named-Arrow dict-map that
  threads the corpus. Its chunked and out-of-core support is this same mask-mode handler, admitted
  for mask mode without `chapter_preserve`; `gen` mode and `chapter_preserve` decline
  (`out_of_core_code_set_shape_unsupported`, pinned by
  `tests/parity/test_out_of_core_group_c_parity.py`).
- NER (the `ner` config of `text_redact` / `text_mask`): Python by design (spaCy inference).
- `faker` masking runs as compiled index selection only on its native legs. Providers are
  person_first_name and person_last_name on these native paths. SEQ admits an exact-`string`
  source with deterministic REUSE or positional REUSE; chunked additionally admits bool/integer
  deterministic REUSE with its fixed-schema producer guarantee and accepted conversion metadata.
  It stays on its Python handler when the provider is not on the native allowlist, when a
  deterministic config is not the REUSE variant or carries no namespace (the oracle rejects it),
  when a non-deterministic mode other than REUSE is used (UNIQUE, MATCH, and SCALE need
  whole-column RNG state), or when the source type is outside the native leg's domain. A faker
  column that stays on Python is still pool-backed: the handler builds and caches one value pool
  and samples it, not per-row live-provider calls. OOC admits the
  deterministic-REUSE person-name variant with an exact-string source through the
  compiled index selection, drawing from a run-scoped pool; other faker shapes and
  a non-string source decline (`out_of_core_faker_pool_unsupported` at routing, or
  a fail-closed `out_of_core_faker_source_type_unsupported` for a non-string
  source once the schema is seen).
- out-of-core `text_mask` with an NER config, or a source the span kernel does not admit: the
  per-cell loop. Other OOC `text_mask` configs run the Rust span kernel, as the SEQ and
  native-chunked routes do.
- the shared SEQ handlers listed in the sequential table (`bucketize`, `shuffle`, `top_code`,
  `formula`, `derived`, `derived_aggregate`, `nested`, `joint_mask`, `geo_generalize`,
  `grouped_series`, `windowed_date`): full-frame handler by design, with no SEQ native
  admission. `group_key` runs natively on SEQ when its sibling is admitted, and also on the
  native-chunked route (above) and on eligible unified full-frame execution; otherwise it falls
  to the shared Python handler.

## Route decision order (decide_execution_route)

This section is the route-decision narrative of
[`_pipeline_routing.py`](../src/decoy_engine/execution/_pipeline_routing.py).

### The two routing layers

Two independent routing layers compose in `_pipeline_routing.py`, in a fixed decision order
`run_pipeline` enforces by calling them in sequence:

1. S2 relationship routing + SC2 out-of-core auto-routing:
   `decide_execution_route` is the SINGLE live router for
   relationship-bearing (FK) jobs -- it runs first and early-returns
   before the layer-2 chunk classifier is ever consulted for routing.
   For a relationship-bearing PURE-MASK job (no generate tables, no
   validators, no fidelity_report, no vault_writer -- see
   `_sequential_eligible`) under `execution_mode="auto"` it picks, in
   priority order (SC2):

   - a. **out_of_core** -- the bounded-RAM DuckDB route -- when the job is
        out-of-core-compatible (`check_out_of_core_compatibility` admits
        the plan: an accepted strategy set, an acyclic table-level FK
        graph, no `when` predicate; a multi-parent child is admitted) AND
        either the default byte-estimate routing applies (a compat-admitted job takes this
        route whatever its row count, unless the full-frame estimate fits and an FK key
        dtype hazard sends it to sequential, see below; `out_of_core_threshold_rows` is not
        consulted) or,
        with that flag off or for a job outside its scope, the largest mask table is
        at/above `out_of_core_threshold_rows`.
        `_pipeline_route_exec.run_out_of_core_route` executes + packages it.
        Inside that route, a sink-path table auto-selects the reorder driver
        over `_batch_join` once its largest incoming edge's deduped
        parent-key count reaches `out_of_core_reorder_threshold_rows`
        (default 2M; `0` forces every eligible table, per-run override) --
        an independent, narrower-scoped threshold from this layer's own
        `out_of_core_threshold_rows` (see `_route_policy.decide_route`).
   - b. **sequential** -- the bounded-memory (but O(cardinality), so still
        OOM-able at extreme scale) `run_sequential` path -- for a
        pure-mask FK job that is NOT out-of-core-eligible (an unsupported
        strategy, a self-referential FK, a multi-parent child whose
        parents' masked key types differ, a key dtype the joiner rejects) or, when the row-count
        gate is in force, is below the out-of-core size threshold. A job whose full-frame
        estimate fits and that has an FK key dtype hazard (out-of-core rejects some key
        types that sequential completes) also takes sequential. A cross-table cycle is
        never sequential: bounded admission excludes it.
        `_pipeline_route_exec.run_sequential_route` executes + packages it.
   - c. **full_frame** -- the adapter-selected `run` path -- for a job with
        no relationships, and for a relationship job disqualified from
        sequential (generate+mask, validators, fidelity, vault,
        non-pandas substrate) that is small enough to be full-frame-safe.

   And it REJECTS before the read/mask step (fail-closed
   `ExecutionError` code `fk_full_frame_oom_risk_rejected`) when a
   relationship job can ONLY run full-frame (neither out-of-core- nor
   sequential-eligible) AND the largest mask table is at/above
   `full_frame_reject_rows` -- the "never a silent OOM" half of GATE-1's
   prevention posture: a too-big job that no bounded route can take is
   diverted to a clean typed error, not left to the OOM-killer.

   A generate+mask job whose static shape `_mixed_static` admits takes a fourth route under
   `auto`, `mixed`: generation stays resident and the mask tables run on the chunked lane
   (`_pipeline_mixed_route`). Every job it declines keeps the outcomes above unchanged.

   `execution_mode="full_frame"` always forces full-frame (even when
   eligible, even when large -- an explicit operator escape hatch that
   bypasses the reject: the operator owns the OOM risk they asked for);
   `execution_mode="sequential"` forces sequential and
   `execution_mode="out_of_core"` forces out-of-core, each raising
   `ConfigError` if the job is not eligible for the forced route
   (fail-closed: never silently ignore an explicit request). The
   sequential path is pandas-only by construction (`run_sequential` is
   typed to `PandasExecutionAdapter`), so it always constructs its own
   adapter regardless of the caller's `substrate` knob; the out-of-core
   route is likewise pandas-oracle-parity by construction.

   `execution_mode="stream"` means "must stream" (RUN-STREAM E1a). `run_pipeline` translates it once to
   `auto` plus an immutable `stream_required`, and `decide_route` hands that run to
   `execution/pipeline/_stream.py` instead of the two layers. A preflight over config, plan and source
   footers takes the chunked lane (one table) or the B7 split (several) when every mask table passes
   `check_chunked_compatibility`, with the size threshold dropped and the Parquet row groups kept at
   one per chunk. A job with FK edges whose tables all pass that gate runs as per-table lane units; one
   the gate rejects takes the out-of-core route only when out-of-core accepts it and the FK dtype hazard
   is clear. Anything else raises `runtime.streaming_unavailable` before the passed `sources` are read.
2. S3 (engine-efficiencies P3) auto-chunk routing: reached only when (1)
   did NOT take the sequential early return -- every path into
   `decide_chunk_route` is either explicitly forced full_frame or was
   found sequential-ineligible, relationship-bearing jobs in particular.
   `classify_job`'s own `chunked` gate independently excludes any job
   with FK edges or a `relationships` block (`_planner._chunked_rejection`),
   so a relationship-bearing job that reaches this layer (e.g.
   generate+mask FK, or an FK job disqualified from sequential by
   validators) cannot be misrouted into the chunked path either -- the
   two layers compose without overlap: (1) owns relationship routing
   (sequential vs. full_frame); (2) owns non-relationship routing, single
   table in `_pipeline_routing.py` and per table in `_pipeline_multi_table` (B7). When the job classifies `chunked`,
   `_pipeline_route_exec.run_mask_chunked` runs it in `chunk_size_rows`-row
   slices through the chunked lane (`_pipeline_auto_chunk`: B1's
   `run_mask_chunked`, or the oracle under the kill switch) instead of one
   full-frame adapter call; masked values are unchanged (the output shape
   follows guarantee 3 of docs/plans/2026-10-01-dispatcher-auto-chunk.md)
   and every eligibility miss fails CLOSED to the exact full-frame path.

Row-error honesty (D7/D8, S1): the chunked route is never eligible for
row-error quarantine -- both lanes fail closed with `RowErrorsFailedError`
(the oracle's H1 check in `_chunked.py`) the moment ANY chunk reports a row
error, so `run_pipeline` never sees row errors to quarantine on that route
(same policy the pre-existing manual chunked entrypoint already enforced).

Sprint B1b (OOM-avoidance routing redesign, docs/plans/2026-07-10-oom-avoidance-routing-redesign.md
 §13): `decide_execution_route`'s
`use_byte_estimate_routing` flag (TB-5 default ON) wires the B1a byte-level
estimator (`_mem_estimate.fits`) into the "auto" full_frame-admission
decision, additively -- see the flag's entry under `decide_execution_route`
below for the exact scope and rule. Forced OFF (the rollback path), `_pipeline_routing.py`'s
routing is BYTE-FOR-BYTE the pre-B1b row-count logic described above.

### `decide_execution_route`

`decide_execution_route` decides `(route, route_reason)` -- `"out_of_core"`, `"sequential"`,
`"mixed"`, or `"full_frame"` -- or RAISES a fail-closed reject-before-read.

`mixed_admitted` (caller-precomputed by `_mixed_static.admit_mixed_static`): a
generate+mask job whose static shape the production mixed route can run. It is
consulted only under `auto`, after the forced modes returned or raised, so
`full_frame` still runs the oracle and `out_of_core` / `sequential` still reject a
mixed job with the existing typed `ConfigError`. A mixed job it does not admit keeps
every existing outcome below, including the fail-closed reject of a large coupled job
no bounded route can take.

`use_byte_estimate_routing` (Sprint B1b; TB-5 flipped the default to
`True`, additive + forceable OFF for rollback): OFF, `decide_execution_route` is
BYTE-FOR-BYTE the row-count logic below -- `full_frame_fits_estimate` is
never read, the rollback path. ON (the default), for a job IN SCOPE
(`has_relationships and has_mask_table and not has_generate_table` --
see `byte_estimate_full_frame_fits`'s docstring for why generate+mask is
excluded), the "auto" decision is REPLACED by the §13 conservative-filter
ruling: full_frame only when `full_frame_fits_estimate is True` (the
caller precomputes this via `byte_estimate_full_frame_fits` +
`resolve_budget`) AND no bounded route applies -- a bounded-eligible
(eligible, acyclic) job takes its bounded route even when it fits, because
the full-frame oracle is the slowest route per row; otherwise -- UNPRICEABLE
(`None`) treated identically to `False`, per §13 -- the job routes to whichever BOUNDED path
eligibility admits (out_of_core when compat-admitted, else sequential),
or the existing reject when NEITHER applies (§13's one irreducible reject
class). The choice AMONG bounded routes stays eligibility-based, never an
estimate of out_of_core/sequential peak (unmeasured placeholders, §13);
`out_of_core_threshold_rows` is not consulted in this mode. Out of scope,
the flag has NO effect, even when `full_frame_fits_estimate` is set.

Sprint B2 (§3.3/§11/§13): `use_probe_routing` (TB-5 default `True`,
additive, composes with `use_byte_estimate_routing` -- it has NO effect
unless that flag is also `True`) is the fast-path RECOVERY for a job the
conservative
B1b estimate over-downgrades. `probe_recovers_full_frame` is the caller's
precomputed `_pipeline_routing_signals.resolve_probe_recovery` result:
`True` only when the two-point micro-probe (`_probe.probe_peak_bytes`)
actually MEASURED this job's real full_frame peak (at small scale,
extrapolated) and confirmed it clears the budget with margin. Checked
ONLY after `full_frame_fits_estimate is True` fails to admit the job (a
confirmed static fit never needs a probe) -- when it is `True`,
`decide_execution_route` returns `full_frame` only when no bounded route applies
(`not bounded_eligible`). A bounded-eligible job, such as an out_of_core-compatible
one, still takes its bounded route: the full-frame oracle is the slowest route per
row, so a measured fit does not override eligibility. Anything other than `True`
(`False` or `None` -- an inconclusive probe, or one that was never run
because it was out of scope/unnecessary) falls straight through to the
exact same bounded-by-eligibility logic below as if the probe did not
exist -- an inconclusive probe NEVER yields full_frame, only a
CONFIRMED fit does (the load-bearing safety property: recovery only on
a measured fit).

`fk_ooc_dtype_hazard` (caller-precomputed from the source schemas by
`_pipeline_routing_fk_dtype`): out-of-core would reject a key type the oracle
completes, so a fitting job with it takes sequential rather than out-of-core.

`vault_ooc_safe` (D3b, caller-precomputed by `out_of_core._vault_collect.vault_ooc_safe`):
every vaulted column is on the reviewed allowlist, string-typed in and out, and not an
incoming FK child key. Such a job is otherwise a pure-mask job, so it takes the
out-of-core route (which collects the vault per batch) instead of full-frame-or-reject.
It never enables sequential, which has no vault collector, and the byte-estimate flag
OFF restores the old behaviour.

`validators_ooc_safe` (D3a, `out_of_core._validate_batch.validators_ooc_safe`): every
validator is a per-cell check on a route-stable string column, with no quarantine. Such a
FITTING job takes out-of-core; a probe-recovered job still routes full-frame, and sequential
stays closed to validators.

Priority (SC2), for a relationship-bearing PURE-MASK job under `auto`:
out-of-core (when compat-admitted; AND large when the row-count gate is in force) > sequential (bounded but
O(cardinality)) > full-frame. A large relationship job that no bounded
route can take is REJECTED before read (`ExecutionError`
`fk_full_frame_oom_risk_rejected`) rather than left to OOM full-frame.

Out-of-core eligibility is a STRICT SUBSET of sequential eligibility: it
needs the pure-mask FK shape (`_sequential_eligible`) and an acyclic
FK graph (single- or multi-parent children) with only supported strategies
(`out_of_core_compatible`). Under the default byte-estimate routing that is
enough; the row-count gate (a largest mask table at/above
`out_of_core_threshold_rows`) applies only when the flag is off or the job is
outside its scope. So a pure-mask FK job with an unsupported strategy or a
self-referential FK keeps taking the existing sequential route. A cross-table
cycle (A -> B -> A) is excluded from bounded admission: it runs full-frame when
memory admission passes, otherwise it is rejected with
`fk_full_frame_oom_risk_rejected`.

When the full-frame estimate fits (or the probe confirms a fit) and the job
has an FK key dtype hazard, the router picks sequential instead of
out-of-core. Probe recovery selects full-frame only when no bounded route
applies.

`largest_table_rows` carries the largest mask table's row count from the
(SC7a bounded) profile metadata even on the lazy `source_loader` path where
no source is resident -- so the SC2 size gates fire there too, closing the
F2 `None`-on-lazy-path hole. `largest_table_rows_exact` is False when that
count is a CSV byte-size estimate (CSV has no footer); an estimated
full-frame-bound table at/above `full_frame_reject_rows` is rejected with
the distinct `fk_full_frame_oom_risk_rejected_estimated` code (convert to
Parquet or set `execution_mode`), while an estimated OOC-eligible table
still reroutes to out-of-core as usual. `largest_table_rows` is None only
when there is genuinely no size signal (no mask table); the size gates then
never fire.

A mutual cross-table FK cycle (A -> B -> A) cannot be ordered by
table_topo_order, so `auto` must not route it to sequential (it ran
fine under full_frame before this program; routing it to sequential is
a functional regression, not a leak -- see
docs/backlog/s2-fk-leak-remediation-r3-guide.md section 6). A
self-referencing table (one table, not a cross-table cycle) is NOT
flagged and still routes normally.

`resolved_substrate` disqualifies sequential eligibility when it is
not `"pandas"` (see `_sequential_eligible`'s docstring): pandas is the only
masking substrate, so any other resolved value routes to full_frame
(fail-closed) rather than the pandas-only sequential path, and a future
non-pandas substrate would need its own explicit handling first.

Threshold ordering (L2): the reject-before-read branch reads most naturally
when `out_of_core_threshold_rows <= full_frame_reject_rows`, and that is the
default (5M <= 7.5M). The two knobs are validated positive+typed at the
`run_pipeline` submit choke point but their ORDERING is deliberately NOT
force-validated, because an inverted override
(`full_frame_reject_rows < out_of_core_threshold_rows`) is a legitimate,
SAFE config -- e.g. a small-RAM host that rejects full-frame-bound FK jobs
early while leaving the out-of-core reroute at its default. The reject
branch's correctness does not actually depend on the ordering: an
out-of-core-eligible job can NEVER reach the reject branch regardless of
threshold order, because out-of-core eligibility is a strict subset of
sequential eligibility, and a sequential-eligible non-cyclic job takes the
`sequential` early return in `decide_execution_route` before the reject test is evaluated. The
reject branch is reached ONLY by full-frame-bound jobs (not
sequential-eligible, or a cross-table cyclic FK graph), which no bounded route can take
at any threshold ordering. So the ordering is an explanatory expectation,
not a load-bearing invariant, and is left to the operator rather than
rejected at submit time.

## Large jobs with no foreign keys

Status: current. Plan: `docs/plans/2026-11-19-nonfk-oom.md`. Memory before the guard:
`docs/records/2026-11-19-nonfk-oom-baseline.md`.

Under `execution_mode="auto"`, a mask job with no foreign key takes one of three routes. The
route does not depend on the memory the host has, so each route needs its own guard.

1. **Chunked.** A large single table, or each large table of an independent multi-table job,
   goes to the chunked lane when its columns are chunk-stable. A passthrough column that nothing
   reads (no `when:` names it) no longer blocks this: the lane carries it past pandas, so an
   integer with nulls above 2^53 stays `int64`, a decimal keeps its precision, and a dictionary
   column keeps its index width. A masked `hash`, `redact` (a string `redact_with`) or deterministic `faker` (integer sources)
   column of an integer-with-nulls, decimal or binary type also stays chunked, when no `when:`
   reads it. Memory is bounded by the chunk size.
2. **Unified slice.** A small, resident, Parquet-backed table that the physical plan admits.
3. **Full-frame.** Every other table. The table is held whole, once as Arrow and once as a pandas
   copy, so a large table that cannot be chunked (a `shuffle` column, for example) needs several
   times its Arrow size. Memory grows with the row count: the baseline record measures about 2 GB
   per million rows for the W2 column mix.

A job on the full-frame route is priced before it runs. The check is one verdict with three
outcomes: `FIT`, `INSUFFICIENT` and `UNKNOWN`. It reads the memory ceiling `H` that the host or
cgroup enforces, and an admission ceiling `A` of 85% of `H`.

- A strict lower bound (the input bytes plus one pandas copy, taken from the Parquet footer for a
  lazy source) above `H` is refused.
- A measured probe on a small sample, scaled up, that clears `H` by the calibration band is refused.
- A job that fits `A` runs. A job in between, or one the engine cannot measure (a lazy CSV, a
  `source_loader`, strict file access), runs as before and records
  `route/nonfk_full_frame_unverified`.

The verdict never refuses on the static estimate alone, because the estimate is biased high.

A refusal raises `ExecutionError` with `runtime/nonfk_full_frame_capacity_exceeded`. It is a
capacity code, so `decoy run` exits 5. The message holds byte counts and remedies only. It is
raised with no chained error, and no output, staging directory or cast run exists when it
reaches the caller. The verdict is stored on the route decision and reported as
`quality_metrics["resident_fit"]`.

### What "before the read" means for each entry point

The check runs at four points, because a whole-table copy can happen before a route is chosen.

| Entry point | What is checked | When |
|---|---|---|
| `run_pipeline` with a resident table | the full lower bound, at the end of route selection | before any output opens |
| `run_pipeline` with a `LazySource` | the footer input bytes of the tables about to be read whole, then the full lower bound once the route is known | before the source is read |
| A table with transforms | every resident input byte plus that table's pandas copy | before the first transform copy |
| A mixed generate and mask job that declines to full-frame | the same verdict, with the generated tables counted at their input bytes | before the mask sources are read |

`decoy run` hands a Parquet `path:` source to the engine as a `LazySource`, so the second row
applies and nothing is read whole before the check. A source the CLI itself reads whole before it
calls the engine is outside this check, as is `execution_mode="full_frame"` set by hand. A job
with a foreign key is not priced here: it takes the sequential or out-of-core route, or is
rejected by `fk_full_frame_oom_risk_rejected`.

### The ceiling ignores `--max-memory`

`H` is the detected host or cgroup limit. `--max-memory` sets the out-of-core budget only, so it
moves neither `H` nor `A`. A smaller `--max-memory` does not make this check refuse more. Honoring
it is logged as a V2 item.

## Generation

Generation computes every value on Python and NumPy and never on the Rust companion. The Rust
generation-kernel-selection experiment (FR3) was shelved after it measured slower than
vectorized NumPy RNG, so this is by design, not a gap. The compiled index kernel is reachable
only from masking's deterministic pool path; no generation column enters it. PoolSampler's
compiled deterministic selection branch serves masking. Generation's pool call sets
deterministic=False and REUSE. The streamed pooled selector also uses NumPy integers. Per-kind
compute:
`sequence` and sequential `reference` draw by direct index (no selection event); `categorical`
and random/weighted `reference` draw via Python RNG; pooled `faker` via NumPy selection; per-row
`faker` via live provider calls; `windowed_date` via a NumPy offset draw plus date arithmetic.
The ineligible families run on the legacy whole-table synthesize path with distinct compute:
`formula` is a formula-expression evaluation; `derived` and `derived_aggregate` select nothing
(they are computed from other columns); `statistical`, `grouped_series`, and `group_key` are
whole-table synthesize. Resident and streamed materialization produce byte-identical output for
admitted streamed generation shapes; this does not imply that every legacy whole-table
statistical family streams.

## Advisory job estimate and lifecycle peak

`estimate_job` reports the route, `peak_bytes` and a runtime band before a job runs. It also
reports the memory the whole job needs, in three fields on `JobEstimate`: `lifecycle_peak_bytes`,
`limiting_phase` and `phase_bytes`. It is advice. It never raises, never refuses a job and never
changes a route.

The lifecycle peak is the largest of three phase peaks. Each phase peak is the sum of the memory
that is live at the same time in that phase.

- ingest: each source is read whole, one after the other, and every earlier table stays resident.
  A CSV source is read as text into a pandas frame and then copied to Arrow. A fixed_width source
  builds a list of row dicts first. A Parquet source holds its Arrow table and one row group.
- execute: the measured route model (the same one that gives `peak_bytes`), plus the input tables
  the caller still holds that the measurement did not. A strategy that turns numbers into
  strings (`hash`, `redact`) is priced with the strings it writes.
- write: every input and every output are resident, plus the largest copy a target needs (a pandas
  frame for CSV, the coercion and list copies for fixed_width, nothing for Parquet).

`limiting_phase` names the phase that sets the peak; a tie goes to the earlier phase.

Generate-only and mixed jobs get the same fields. A generate table has no source, so it adds
nothing to ingest. In execute it adds what a resident run holds for its columns, with the width of
each text column included, and the largest working set of a unique column draw. A plan that runs
the legacy whole-table path (any column that admission declines, such as a `unique` faker column)
holds every cell as a Python object, and the estimate prices it that way. In write its Arrow
output sits beside the mask outputs. A column with no width source (a `formula`, for example)
leaves the lifecycle fields unset, with a note naming it. A generate-only job keeps
`peak_bytes=None`, and a mixed job stays `priceable=False`.

What the estimate assumes and does not price:

- The caller holds every input and output until the last target is written (the CLI does). The
  `--chunked` path and a lazy handoff hold less, so the estimate is higher than they need.
- String widths come from the first 10,000 rows of each source. A file whose later rows are wider
  is under-priced.
- Row counts of a CSV source are estimated from the file size; the estimate says so in `notes`.
- The vault maps, post-scan baseline tables and quarantine frames are live beside the route's working
  set and are not priced. Subset jobs are not priced. Disk and scratch space are not priced.
- `peak_bytes` stays the router's own model on input widths. A job whose strategies turn numbers
  into strings has a lifecycle execute phase above `peak_bytes`.
- The estimate prices the pandas form of a string output. The native unified slice can keep it in
  Arrow, so the real run can be well below the estimate (several times, for string outputs).
- A file that changes between the estimate and the run only makes the estimate stale.

On the measured fixtures the estimate is never below the measured peak. It is also within 1.5
times the measured peak for type-preserving numeric jobs and for jobs whose limiting phase is
ingest or write, on the matching route with at least 1,000,000 rows. String-output jobs are
checked against the lower bound only.

## Progress events

Every route reports the same value-free event stream when the caller passes
`run_pipeline(progress=sink)` (or wraps another entry point in
`decoy_engine.progress.use_progress(sink)`): a resolve phase, one route event naming
the layer-1 route and the lane, per-table mask or generate phases with row counts, rate
samples (rows done and rows/s, time-throttled) from the chunked dispatcher, the
out-of-core batch stream and generation batches, and a terminal event. The full-frame
oracle reports its mask step once, not per table, because it has no finer boundary.
Output bytes never depend on the sink.

## What this means for a caller

- If a job lands on a native route, the strategies marked compiled Rust / compiled index
  selection / named-Arrow run natively; the dedicated-Python, reporting-only-key, excluded, and
  declined cells do not, and a declined cell always says why.
- A missing native companion is not a silent slow-path: a native-kernel decline retains the
  current route and uses its reference implementation, or downgrades to the byte-identical
  full-frame oracle, always with a coded reason (a few cells keep a companion-absent Python
  bridge instead).
- Generation speed comes from vectorized NumPy, not the companion; installing the companion does
  not change generation throughput.
