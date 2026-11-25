Status: plan (revision 7 build-ready: Codex review-low GO at 88b2e0126, low anchor notes folded at de3421c08)

# PROP batch: quiet fallbacks, unused public names, shims and guard facts (roadmap rows 24zi, 24zj, 24zk, 24zl)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `catalogs/recurring-defects.md`, `proportionality.md`, `cross-cutting-concerns.md`,
`api-and-compatibility.md`, `testing.md` (test depth); engine `CLAUDE.md`, `CODEMAP.md`
("Where Things Go"), `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`,
`docs/strategies.md`; CLI `docs/ROADMAP.md` (rows 24zd, 24ze, 24zi to 24zl, 61, 63a, 93), CLI
`CODEMAP.md`, CLI `docs/roadmap/post-1.0-plan.md`; CLI plan branch `plan/run-stream-r6-5`
(`docs/plans/2026-11-08-run-stream.md`) and engine `plan/deliv` (`docs/plans/2026-11-12-deliv.md`);
owner memory rules: V1 bar, process by risk (2026-11-10), sentry over prose, pre-release no
locking, no new features (2026-11-16).

Revision 7 (2026-11-25): re-anchor only. No design change. Bases: engine `origin/main`
`2b8a47fbe` (engine version 0.28.4); CLI `origin/main` `d6b9e4c7` (pins `decoy-engine==0.28.3`).
Every line number in sections 2, 3, 8b, 9 and 10 was re-read at these bases. Changes:

- Merged since revision 6: E-F0 (engine #617), E-G1 (engine #688), C-S1a (CLI #312), the D6
  saved-scan half (CLI #313) and C-G1 (CLI #318). Their rows below are kept as the record. Still
  open: E-G2a, E-G2b, E-G3, C-G2, E-S2a1, E-S2a2, E-S2b, C-S1b, C-S2 and every 24zi and 24zj
  slice listed in section 10 as not merged.
- A4 is closed on main. Engine #596 (`8b1330157`, the inherit generate type) removed
  `_expression_refs` and its `except Exception`. The one `except Exception` left in
  `E:plan/checks/_generate_columns.py` (`:296`, `_check_categories`) sets a flag and then refuses,
  so it fails closed and is not an A item. E-F1 drops A4 and the file; AT-A3/A4/A6 drops the
  parse-rules ordering half. The E-F2 `_checks.py` narrowing is now at `:637`.
- AT-A5b: the validator-failure parity cell cannot run on the unified lane. On main,
  `ET:physical/test_unified_slice_exception_boundary.py` pins that admission declines any
  validators or quarantine config
  (`test_admission_declines_validators_so_finalize_write_branch_is_unreachable` and its
  quarantine twin), so `finalize_validators_and_quarantine` never raises inside the `try`. The
  cell becomes a pin: with validators configured, the slice declines at admission and the oracle
  raises the validator error. The section 2.3 callee row says so.
- B7: `progress_interval_s` is read inside `run_pipeline` (`E:execution/_pipeline.py:302`,
  `use_progress(progress, interval_s=progress_interval_s)`). Deleting the keyword makes the
  interval the existing default constant; E-S1b keeps that call with the constant. A new file
  carries `stream_chunked_output`: `E:execution/pipeline/_stream.py:179`. E-S1b counts it in its
  file budget (now 7 known files for that keyword family).
- E-S1c: the internal routing values are also passed as literals by three estimators
  (`E:execution/capacity.py:389-390` and `:448-450`, `E:execution/_job_estimate.py:184-185`).
  They call the routing decision function, not `run_pipeline`, so they keep their keywords; only
  the `run_pipeline` keywords go. 62 test files and 5 bench scripts name the keywords.
- B8 test users add `ET:security/test_f29_remediation.py:332` and `:342`.
- Version and pin: the CLI pins 0.28.3, not 0.27.0. "Surface release 0.29.0" stays "the next
  free version at release".
- Sequencing (technical, recommended): E-S1b listed E-S2a2 and E-S2b as dependencies only for
  file overlap (`_chunked_oracle.py`, `_pipeline.py`). None of the 24zk engine slices has started.
  E-S1b may now build first; whichever of E-S1b, E-S2a2 and E-S2b merges second rebases.
- C-F1b is still blocked: DELIV C2a (row 61) and RUN-STREAM C1a (row 63a) are not merged.
  RUN-STREAM `plan/run-stream-r6-5` still has the `seal_result` bullet at line 790. The DELIV
  C2a `run/_execute.py` bullet moved to `plan/deliv` lines 834-839.
- C-F1a: its swallowed-broad-except ratchet step needs the CLI baseline from C-G2, which is not
  merged. If C-F1a builds first, it skips that step and C-G2 writes the baseline without the A7
  and A9 sites.
- Builder anchors (Codex rev 7 review, all low): A5 callees: only the configured validator and
  quarantine branch is unreachable; an admitted run still calls the finalizer at
  `E:execution/_unified_slice.py:325` (the boundary test injects there,
  `ET:physical/test_unified_slice_exception_boundary.py:171-174`); the resident admission decline
  is inside the `try` at `:227-236`; the faker reroute returns at `:265`; the activation flag is at
  `:345-346`. A7's stale comment is `CT:e2e/test_init_command.py:121-122`. A8a schema locations
  come through `C:cli/gate/_layers.py:150-158,204-205` (`:250` adds `.format`). D5 builds
  `_report_kwargs` at `C:cli/run/_execute.py:445-457` and forwards it at `:476`. A8b output
  guards: `C:cli/run/_execute.py:406-408`, `C:cli/demo.py:298-300` (`:301` is the write); A8b
  callers: `C:api.py:653`, `C:cli/tokenize.py:375`, `C:cli/demo.py:293`. B7:
  `stream_chunked_output` is on 21 lines in eight test-tree files, including a real `False`
  override at `ET:test_e1a_stream.py:152-164` forwarded by `run_stream/_support.py:42-44`; E-S1b
  updates that cell. E-S1c: the second capacity call passes `True, False` at
  `E:execution/capacity.py:448-450`; of the 62 test files only public `run_pipeline` overrides
  migrate (the JSON expectation at `r3_failure_trace_baseline.json:104` and the internal
  arguments at `test_unified_slice_admission.py:476-477` stay).
- D6 manifest half: planned separately in CLI `docs/plans/2026-11-25-prop-shims-d6-manifest.md`
  (branch `docs/plans-prop-shims-d6-manifest`). It is the only C-S2 work left.

Revision 6 (2026-11-17). Changes since revision 5, from the Codex rev 5 NO-GO (one DESIGN
finding) and the cross-check of `plan/prop`, CLI #308 and Dennis's findings (2 V1, 6 DESIGN, 23
V2-LOG). Section 17 maps every finding to its fix. Bases unchanged.

- Codex DESIGN, swallowed-broad-except: the save-and-re-raise exemption now needs the alias
  assigned inside that handler and a matching `raise` lexically after the whole `try` statement
  in the same function scope. AT-SBE gains the after-block (0), raise-before-try (1) and
  assigned-outside (1) cells; section 7 gains the ordering mutation. The guard-lane slices
  (E-G1, E-G2a, E-G2b, E-G3, C-G1, C-G2) are R2.
- V1, A5: one rule for the reroute set. `_REROUTABLE` holds the coded declines from the two plan
  callees, the two Arrow errors and `MemoryError`; everything else propagates. A census over the
  named suites runs before the narrowing. New AT-A5c (section 2.3).
- V1, D6b: `decoy demo` and the `decoy.scan()` guidance write `scan-set/v1` before the legacy
  reader goes, in C-S2. New AT-D6b. OQ-5 re-decided.
- DESIGN: module-size DENSE entries move as a `ceiling` field under the rise rule, LEGACY as a
  shrink-only `max` (OQ-9); `count` becomes a ratchet ceiling; the E2 move gets an equivalence
  snapshot test (AT-E2b), removed in E-G3 and C-G2; the CLI import-guard sentry covers every
  listed spelling and `compile_explain.py` moves to D2; D7 importers use the public
  `decoy_engine.profile.LazySource`; OQ-4 re-decided on the correct consumer fact, new slice
  E-S1c.
- B7 count corrected: 47 to 43 in E-S1b, 41 after E-S1c. Section 10a rewritten for the
  module-size rules.
- Folded V2-LOG items: A2 coded error and lazy load; `plan/_checks.py:638` narrowed (E-F2); dead
  `isinstance(outputs, dict)` guards; emit-helper caplog and D12 ATs (AT-EMIT) and the two
  protocol methods; A7 test comment; A9 lane holder; B8b test and doc list; platform note;
  `test_mask_api_native.py`; D2 and D3 tests and dead arms; C-S1b hot files; `exit_codes.py`
  scope; E-S2a split into E-S2a1 and E-S2a2; D8 dual paths and CODEMAP rows; E6 `exit` check; E2
  leftover copies; OQ-6 re-decided (keep the Wave B guard); comment-history date rule and CLI
  `_banned_text.py`; K1 `workflow_dispatch` and stale text; E1 second outside path; A1 logged.
- Re-decided owner questions (section 12): OQ-4, OQ-5, OQ-6, new OQ-9 and the A5 reroute set,
  each "decided under go-with-recommended 2026-11-17, re-decided on new facts". None adds a
  feature, a dependency or raises a cap.

Revision 5 (2026-11-17). Changes since revision 4:

- Merged engine `origin/main` `8796ef691` into this branch. Re-verified every 24zj B item and
  every 24zk D item against engine `8796ef691` and CLI `c558e2fb`. No item closed since
  2026-11-16: every B and D site is still on main. Sections 3 and 4 carry the re-read lines.
- D1 has a second probe site since revision 4. CLI #216 (`7d0f72a3`, ProgressSink wiring) added
  `C:cli/run/_progress.py` `run_pipeline_kwargs`, which calls `run_pipeline_accepts("progress")`
  although the pinned 0.27.0 has the `progress` keyword. It joins C-S1a, which now touches one
  `cli/run/` hot file (sections 4 and 10).
- New class guard for row 24zi under the standing "sentry over prose" rule: a shrink-only
  ratchet `swallowed-broad-except` in each repo (section 2.5). The engine half lands in E-F1 and
  the CLI half in C-G2. Sections 7, 8, 8a, 9, 10 and 11 carry its rows.
- New section 10a "Ratchets touched": each census, allowlist, baseline, pin and ceiling that a
  slice grows or shrinks.
- The re-export sentry's exempt list `PUBLIC_BOUNDARY_FILES` is a JSON baseline from its first
  commit, not an in-code constant, so E-G2 never has to move it (section 7).
- B2 records that its `PERMANENT` expiry row is stale and goes with the function, and that the
  five `src/` comments naming it stay (section 3).
- No new owner question. OQ-1 through OQ-7 stay decided. No Codex GO for revision 4 is recorded
  on this branch or in the vault gate ledger. This revision goes to Codex for the delta and the
  new guard.

Revision 4: the Codex NO-GO after revision 3 (one `V1`, one `V2-LOG`) is remediated;
section 16 maps both findings to their fixes. Dennis round 2 remains mapped in section 15.

Bases (revision 5, 2026-11-17): engine `origin/main` `8796ef691`; CLI `origin/main` `c558e2fb`
(still pins `decoy-engine==0.27.0`); platform `origin/main` `fbaee2a9` (pins
`decoy-engine==0.18.0`, parked; read only to record consumers). Revision 4 read engine
`13c95c7de` and CLI `ba7b613e`. Package A lines (section 2) were not re-read for revision 5;
each slice re-reads its lines at its own base. Input: the audit
`C:docs/records/2026-11-15-proportionality-audit/REMEDIATION.md` sections 4, 5, 7, 8, 14 and
15. The audit was read at engine `64e9349b` and CLI `e716f445`; line numbers below differ from
the audit where the code moved.

Notation: `E:` is engine `src/decoy_engine/`, `ET:` is engine `tests/`, `C:` is CLI
`src/decoy/` (and `C:` plus a repo path such as `C:docs/` for CLI repo files), `CT:` is CLI
`tests/`.

## 0. Why this plan is in the engine repo

Of the 18 build slices below (unchanged in revision 5), 11 land in the engine: the new first slice E-F0, all of package B,
most of A and D, and the engine half of E. The 7 CLI slices are smaller, and five of them do not
depend on an engine release. The plan sits in the repo that holds most of the work so the gate has
one place to look; each CLI slice names its CLI paths in full.

## 1. Pinned guarantee and non-goals

Guarantee. After this batch:

- (a) no `text_mask` span is written back with its real value unless its strategy is
  `passthrough`, and no detector and strategy pair that the code cannot carry out compiles;
- (b) no failure listed in 24zi turns into a weaker output while the run reports success, and
  a new broad handler that swallows its exception under `src/` fails the `swallowed-broad-except`
  ratchet in either repo (section 2.5);
- (c) every public engine name listed in 24zj has a recorded consumer or is gone;
- (d) no CLI line probes for an engine name that the exact pin already ships, and no engine
  module exists only to re-export or forward to another;
- (e) each guard fact listed in 24zl is written in one place, and a new comment that carries a
  task id, review round, dated decision or reviewer name fails a guard.

Non-goals:

- No new feature. Each item is a fix to existing behavior or a deletion.
- D13 (`_V2_CUSTOM_PROVIDERS` beside `_CUSTOM_FAKER_PROVIDERS`) is not a shim: both tables are
  live. It goes to the post-1.0 plan as a duplication item.
- B9 (platform reason codes) stays as the platform wire contract. Reason codes are append-only.
- E5 (exact line pins on four legacy CLI files) stays until V1 (owner 2026-11-15). E8 is V1+.
- The broad catches in `E:execution/_chunked_fk_dtype_safety.py` stay. They fail closed (return
  False, which refuses the edge), and narrowing them safely would have to name `OSError`
  (`ZoneInfo("America")` raises `IsADirectoryError` on Python 3.10) and `AttributeError`
  (`pa.decimal32` is absent before pyarrow 18; the floor is `>=14`). Recorded as kept, not fixed.
- Audit packages C, F, G, H, I and J are not in these rows.
- No platform change. The platform is parked on engine 0.18.0. A name it uses is kept and the
  consumer is recorded.
- Compatibility window: `api-and-compatibility.md` asks for a documented window before a removal.
  The owner's pre-GA hard-delete rule (row 24zk text) is that window: no 1.0 has shipped, and the
  0.29.0 release notes list every removed name. E-F0 ships alone on the preceding daily train.

## 2. Row 24zi PROP-FALLBACK

No item is fixed on main.

### 2.1 Live leak found in review (slice E-F0, first in the batch)

`text_mask` dispatches each span on its strategy with no check that the strategy fits the
detector:

- `_mask_date_shift` (`E:transforms/text_mask.py:434-465`) returns `matched_text` unchanged when
  the span does not parse with `_COMMON_FORMATS`. `per_detector_strategy: {ssn: date_shift}` or
  `{email: date_shift}` therefore writes the real SSN or email into the output (Dennis probed it).
  The same branch leaks a real date-like span supplied through the library `extra_spans` API when
  the span does not parse (for example `2024-02-30`). The default config produces no date spans:
  there is no built-in date detector, and NER emits no date id.
- `_mask_fpe` reads `_FPE_CONFIG.get(detector_id, ("digits", None))` (`:349`), so `fpe` on any
  detector runs a digits cipher whatever the span holds.
- `faker` on a detector with no `_FAKER_METHOD` entry writes a fake person name (the audit's A1).
- An unknown strategy name falls through to the redact token in `_mask_span` (`:505-507`).
- Unknown detector ids in `detectors:` are skipped silently (`docs/strategies.md:380`), and an
  unknown key in `per_detector_strategy` is never read, so a typo leaves that type of span on its
  default.

The first is a real value shown in output: V1, and it blocks. The fix is one predicate and one
compile check:

- `strategy_supported(detector_id: str, strategy: str) -> bool` in `E:transforms/text_mask.py`.
  `faker` needs a `_FAKER_METHOD` entry, `fpe` an `_FPE_CONFIG` entry, `date_shift` a date
  detector (the detectors whose `DETECTOR_DEFAULTS` value is `date_shift`: `iso_date`, `us_date`,
  `eu_date`), and `redact` and `passthrough` accept any id in
  `TEXT_MASK_STRATEGY_DETECTORS`. Any other strategy name is unsupported. The private strategy
  tables stay private: only this module reads them.
- `_mask_span` calls the predicate first and raises a coded error for an unsupported pair (it is
  reached only by a caller that skipped compile, such as a direct `mask_cell_with_spans` call).
  The runtime type is the existing `ConfigError`, tagged with
  `config.mask.text_mask_strategy_unsupported`; the raw error maps to CLI usage exit 1. The
  full-frame handler at `E:execution/_strategies/_text_mask.py:228` currently wraps only
  `FpeUnencryptableError`, so E-F0 adds an exact catch that converts this error to the oracle's
  value-free `StrategyError` after the catch has closed. No cause or context chain survives.
  `_mask_fpe` then indexes `_FPE_CONFIG[detector_id]` with no default. Remove the second
  `("digits", None)` default in `_apply_sub_floor_span_policy` at `text_mask.py:308` too.
  `E:execution/native/_text_mask_native_fpe.py:41` also imports `_FPE_CONFIG`; its eligibility
  lookup stays an exact table lookup and gains no fallback.
- `_mask_date_shift` on a span that does not parse returns the redact token (`cfg["token"]`,
  default `[REDACTED]`), never the input. A parse failure on real data is common enough that a
  raise would break runs, and the token is safe.
- The compile check `check_text_mask_strategies` in `E:plan/checks/_text_mask_strategy.py`,
  wired in `E:plan/_compile.py` beside `check_text_mask_ner_available` in both the full and the
  config-only check lists. It uses two derived inventories, not one hand-written list:
  `SELECTABLE_TEXT_MASK_DETECTORS` is the public `SPAN_DETECTOR_IDS` derived directly from
  `_SPAN_DETECTORS` in `E:detection/detectors.py`, and is the exact set permitted in `detectors:`.
  `TEXT_MASK_STRATEGY_DETECTORS` is the union of that set, the values of the existing
  `NER_ENTITY_MAP` in `E:detection/ner.py`, and the keys of `DETECTOR_DEFAULTS`. The last source is
  the existing Tier 2 library `extra_spans` dispatch inventory documented beside
  `DETECTOR_DEFAULTS`: library callers may inject those ids even when config cannot select them as
  built-in detectors. For each `text_mask` column the check refuses (1) an id in `detectors:` that
  is not in `SELECTABLE_TEXT_MASK_DETECTORS`, (2) a key in `per_detector_strategy` that is not in
  `TEXT_MASK_STRATEGY_DETECTORS`, and (3) a pair for which `strategy_supported` is False. Both
  arguments must be strings; non-string ids and strategies are refused rather than coerced.
  `config.mask.text_mask_detector_unknown` is used for both inventory failures because in both
  cases the id is unknown to that config field; the field path distinguishes `detectors` from
  `per_detector_strategy`. No separate reason code is needed.
- The inventory guard proves equality and derivation, not a subset: `SPAN_DETECTOR_IDS` equals
  `frozenset(_SPAN_DETECTORS)` in its owning module,
  `SELECTABLE_TEXT_MASK_DETECTORS == SPAN_DETECTOR_IDS`, and
  `TEXT_MASK_STRATEGY_DETECTORS` equals the union above. Its realistic mutation replaces the
  selector inventory with `frozenset(DETECTOR_DEFAULTS)`, which must make AT-A1g fail.
- Two new engine reason codes, both value-free (they name the column, detector id and strategy):
  `config.mask.text_mask_strategy_unsupported` (cases 3 and an unknown strategy name) and
  `config.mask.text_mask_detector_unknown` (cases 1 and 2). They are added `UNRELEASED` and
  stamped at release (REG-RELEASE). `config.mask.unknown_strategy` is not reused: it belongs to
  the column-level `strategy:` key.
- `docs/strategies.md:380-386` changes from "Unknown IDs are skipped silently" to the refusal,
  and lists the supported pairs.
- Update every statement of the old leak behavior: the draw-site catalogue at
  `E:execution/native/_draw_sites_mask.py:293`, `text_mask.py:447-448`, and the out-of-core oracle
  wording at `E:execution/out_of_core/_mask_group_c.py:224-225`. Re-pin only the
  `mask.text_mask_date_shift` entry digest and the overall catalogue digest in
  `ET:native/test_draw_sites_catalogue_pinned.py`, with a comment that the reason is the changed
  unparseable-span contract. No other catalogue entry moves.
- The check runs beside `check_text_mask_ner_available` and tail-appends
  `text_mask_strategies` to all three reported check lists in `E:plan/_compile.py`: the
  no-profile `checks_passed` tuple beginning at `:295`, the profiled tuple beginning at `:371`
  (the review's `:348` anchor; `:371` at base), and the config-only return beginning at `:565`
  (`:566` is its first entry). `E:plan/_serialize.py:221` serializes `checks_passed`, so every plan
  YAML gains this final item. The compile-check ownership row names `check_text_mask_strategies`
  as config-only and present in full, no-profile and config-only compilation. Move the pins in
  `ET:unit/plan/test_compile_basic.py:79`,
  `ET:unit/plan/test_compile_s2_refactor.py:72,189` (including positional `[-18]`), and
  `ET:acceptance/test_f06_declared_casting.py`'s `plan_yaml_at_baseline`; add a changelog fragment
  that records the plan YAML addition and the new refusal.

Shipped-surface inventory at the pinned bases found no migration. Engine `docs/strategies.md`,
`docs/proof-manifest.json`, and the two `text_mask` testflight manifests select only `ssn`,
`email`, `us_zip`, or `us_phone`, all keys of `_SPAN_DETECTORS`. CLI `ba7b613e` bundled templates,
examples, and `decoy init` scaffold sources emit no `text_mask.detectors` list. Therefore E-F0
changes the detector-contract wording and adds refusal tests, but changes no shipped template,
init output, testflight manifest, proof manifest, or existing docs example config.

Test fixtures that use unsupported pairs today move to supported ones (section 8, AT-A1f).

### 2.2 Items

| Item | Site (at base) | Defect | Reachable | V1 behavior | Slice |
|---|---|---|---|---|---|
| A1 | `E:transforms/text_mask.py` `_mask_faker` | The audit named the inner `try` in `_mask_faker`. That catch is unreachable (`shared_faker()` is a default-locale `Faker()`). The reachable defect is section 2.1. | Yes, through section 2.1. | Section 2.1. The inner `try` and its `fake.name()` fallback are deleted in the same slice. | E-F0 |
| A2 | `E:transforms/geo_generalize.py` `_build_state_map` (272-282; warning at 281, `return {}` at 282, called at 345) | A failed `load_table("us_zip5_city_state")` returns `{}` with a warning, so every state value is `""`. | Only on a broken install (the table ships in the wheel); reference #308 notes the effect is wrong masked output (over-suppression), not only a warning. | The load error propagates as a coded `ConfigError` (`transform.reference_table_unavailable`), and the zip5 table loads only when `state` is in the cascade, so a run that never asks for state never touches it. | E-F1 |
| A3 | `E:plan/_seed_envelope.py` (`:126`; import at `:73`) | `except _ProviderError: reg_caps = None`. | No. `check_unknown_provider` runs first at `E:plan/_compile.py:194`, and in the config-only checks at 523. | Catch deleted. | E-F1 |
| A4 (closed on main by engine #596, revision 7) | `E:plan/checks/_generate_columns.py` `_expression_refs` (deleted) | `except Exception: return frozenset()`: a bad expression becomes "no references". | No. `_check_parse_rules` runs before `_check_forward_references`, and `DerivedConfig.from_dict` already compiles the only `ref_kind="expression"` field. | Nothing left to do. | none |
| A5 | `E:execution/_unified_slice.py` (370-372) | `except Exception` logs `_REROUTE_LOG` (`:75`) and returns None, so the caller reruns the slice on pandas. A native bug becomes a slower correct run. | Yes, on any exception in the callees listed in section 2.3. Output does not change (the pandas oracle is correct). | Section 2.3. Owner question OQ-3. | E-F2 |
| A6 | `E:execution/physical/_compiler.py` `_post_scan_resident` (442-450) | `except Exception: return None` around `post_scan_resident_for(...)`, evidence only. The runtime calls the same function with no catch. | Only on an internal bug. | Catch deleted. | E-F1 |
| A7 | `C:cli/init.py` `_validate_scaffold` (308-324; `except Exception` at 322) | `try: import yaml; from decoy_engine.config import parse_pipeline_config except Exception: return`. Both are hard dependencies, so a broken install skips scaffold validation. | Only on a broken install. | Plain import; update the comment at `CT:e2e/test_init_command.py:127`. | C-F1a |
| A8a | `E:config/_targets.py:161-173` `duplicate_target_groups` and `E:config/_pipeline.py:490` `PipelineConfig._targets_distinct`; the old CLI skip is `C:cli/io/_targets.py:665-667` (`_file_targets`) | A `targets:` key that names no configured table is never refused; a source name alone is not a valid target key. `write_targets` skips it and the run exits 0 with no file. | Yes, from any config with a typo in a target key. | The engine config validator is the one refusal point. Beside `_targets_distinct`, it checks target keys against table names only, raises the new engine code `config.target_table_unknown`, and updates `duplicate_target_groups`'s docstring so it no longer says writers skip unknown keys. CLI run and validate both exit 1 before any source read. The gate location is `targets.{table}`, not `targets.{table}.format` (`C:cli/gate/_layers.py:213-215`). | E-F1; CLI repin and C-F1a acceptance |
| A8b | `C:cli/io/_targets.py` `write_targets` (`:670-688`, skip in `_file_targets` `:650-667`); DELIV C2a retains `_write_mask_outputs` for `C:cli/tokenize.py:375` and `C:api.py:653` until C4; `C:cli/demo.py:293` has a separate `_write_mask_outputs`; RUN-STREAM C1a adds `seal_result` | A declared file target whose table the engine did not produce is skipped (`table = outputs.get(table_name); if table is None: continue`) and the run exits 0. Engine #584 (LOADER-DROP) closed one cause; the skip still hides any other. | Yes, on any engine result that lacks a declared table. | `missing_target_tables` is the one predicate. Both `seal_result` and `write_targets` call it before any write, so the retained tokenize, API and demo paths refuse too. Demo moves onto the shared check instead of owning a second rule. New CLI code `io.target_table_missing`, exit 3. Section 2.4. Also delete the dead `if not isinstance(outputs, dict)` guards at `C:cli/run/_execute.py:308-310` (in C-F1a, the `_execute.py` lane) and `C:cli/demo.py:300-302` (here); `outputs` is always a dict. | C-F1b |
| A9 | `C:cli/run/_render.py` `_next_hint_for_run` (53-61), used at 186 | Reads `raw_cfg["output"]["path"]`, a key the V2 schema does not have, inside `try/except: pass`. Always None. | Dead code. | Deleted; the caller drops the keyword. `_render.py` is held by RESULT (row 62) inside F29 C1 (row 66): this hunk rides with that holder if it is open when C-F1a builds. | C-F1a |
| Emit helpers | `E:context.py` `emit_step` (99-164), `emit_lineage` (167-182), `emit_fidelity` (185-195), `emit_quarantine` (198-213), `emit_throughput_sample` (216-226) | Five copies of `getattr` probing plus `except Exception: pass`; `emit_step` also retries without `node_id` on `TypeError` (D12). No failure is counted: `sink_failures` (`E:progress.py:178`, `:198`; `E:_progress_events.py:376`) counts only `ProgressReporter` sink failures, not these helpers. | The catch is a deliberate observation boundary: a logger that raises must not fail a run. The five copies and the `TypeError` retry are the defect. | One private `_dispatch_sink` in `E:context.py` owns the probe and the catch; it logs the exception class name (value-free) at DEBUG on the engine logger and counts nothing (adding a counter would be a new feature). The `TypeError` retry goes. `emit_fidelity`, `emit_quarantine` and `node_id` go with B5. | E-S1b |

Failure modes:

- E-F0: a config that runs today with `faker` on email, `date_shift` on ssn, a misspelled
  strategy, an unknown detector id, or a library-only id such as `iso_date` or `person_name` in
  `detectors:` now fails compile with exit 1. This is the intended change. The same library-only
  ids remain valid keys in `per_detector_strategy`. `decoy validate` refuses the invalid selector
  forms too.
- E-F0: an unparseable date-like span supplied through library `extra_spans` now becomes the token
  instead of the real text. Default config, NER, native chunked, out-of-core native and SEQ routes
  cannot produce such spans from config at this base.
- E-F0: a span from a caller-supplied `extra_spans` list with an unknown id or unsupported pair
  raises in `_mask_span`. No production caller passes such spans; tests do, and they move.
- A5: a native exception that rerouted today now fails the run. Section 2.3 has the flight.
- A8b: a sink-route table the engine streamed to the sink is not in `outputs`; the check counts
  it as produced (section 2.4).
- A2: a working install sees no change, so the test injects a loader failure.

### 2.3 A5 detail (slice E-F2)

Callees inside the `try` (`E:execution/_unified_slice.py` 192-361) and the verdict for each:

| Callee | On exception |
|---|---|
| `build_live_physical_plan_inputs` | decided by the census below: its coded raise sites (an `ExecutionError` or `PlanCompileError` that carries a registered "slice not eligible" reason) reroute; anything else propagates |
| `compile_physical_plan` | same rule as the row above |
| `_admission.resident_contract_admission` | propagate (admission declines are return values, handled before the try) |
| `build_unified_slice_activation` | propagate |
| `ShadowContext.from_key_provider` | propagate |
| `capture_shadow_snapshot`, `compute_when_masks` | propagate |
| `ShadowCoordinator(...).run` | The `FAKER_POOL_NON_STRING_OUTPUT` reroute arm at `:257-263` is unchanged; any other `ShadowDifference` raises `UnifiedSliceInvariantError`; anything else propagates |
| `assemble_node_evidence`, `deterministic_faker_pin_columns`, `reconstruct_source_shaped_output` | propagate |
| `_pipeline_finalize.stamp_execution_metrics`, `_pipeline_route_exec.execution_telemetry` | propagate |
| `_pipeline_finalize.finalize_validators_and_quarantine` | propagate. Not reachable on main: admission declines any validators or quarantine config before the `try` (revision 7; AT-A5b pins the decline) |
| `_typed_warnings`, `_typed_row_errors` and `ExecutionResult` construction | propagate |
| `PoolBuildFailed` handler | unchanged |

Revision 6 resolves the contradiction in revision 5, where the first two rows said "propagate"
while this paragraph built a reroute set from those same callees. The rule is now one rule:

- `_REROUTABLE` in `_unified_slice.py` is the only thing that reroutes. Its members:
  1. the coded declines: an exception raised at a coded raise site in
     `build_live_physical_plan_inputs` or `compile_physical_plan` whose reason code means "this
     slice is not eligible". The builder lists every such site with its code, and the handler
     checks the code, not only the class, so a `PlanCompileError` that is a real user error still
     propagates exactly as the oracle would raise it (AT-A5b);
  2. `pyarrow.ArrowInvalid` and `pyarrow.ArrowTypeError`, by exact class. Decided: reroute. The
     native lane converts through Arrow, and Arrow refuses data that the pandas oracle accepts
     (for example a mixed-type object column). The oracle output is correct, so failing those
     runs would be a function break. Both classes subclass `ValueError` and `TypeError`, so the
     tuple names them exactly and a plain `ValueError` or `TypeError` is not caught;
  3. `MemoryError`. Decided: reroute. The unified lane holds the shadow snapshot and the
     reconstructed output at once, so its peak is above the oracle's, and today's reroute is what
     lets those runs finish. Failing them would be a function break.
- Everything else propagates. Reference #308 lists `ValueError`, `KeyError` and `TypeError` as
  classes that reach the handler today; each one found by the census is a lane bug. E-F2 fixes it
  at the source or stops and reports. It is never added to `_REROUTABLE`.
- The reroute log line stays value-free: it names the class and, for a coded decline, the code.

Census (in E-F2, before the narrowing commit, recorded in the PR evidence). A temporary
recording handler writes `type(exc).__qualname__`, the raising module and, if present, the
reason code for every exception that reaches the `except`. It runs over `ET:physical/`,
`ET:parity/`, `ET:native/`, `ET:unit/execution/`, `ET:integration/` (golden), the compat corpus
suite, the testflight acceptance suite, and the flight below. Every class found is placed in one
of the three `_REROUTABLE` groups or named as a lane bug. A census with zero unified-slice
activations is void.

Instrument for OQ-3 (no production change): before E-F2 merges, the test flight
(`scripts/test_flight.py`, golden corpus plus the prodsim set) runs on engine main under a wrapper
that attaches a `logging.Handler` to logger `decoy_engine.execution._unified_slice` and counts
records whose message starts with `unified_slice_unexpected_exception_reroute`, grouped by
`exc_type`. The flight counts only if (1) `decoy_engine.native_companion_status()` reports the
companion loaded and (2) at least one run has
`quality_metrics["unified_slice_activation"]["activated"] is True` (`_unified_slice.py:334-335`).
A flight with zero
activations is void, not clean. The wrapper and the counts go into the E-F2 PR evidence.

### 2.4 A8b detail and plan amendments (slice C-F1b)

Placement. DELIV C2a (row 61, engine `plan/deliv` `docs/plans/2026-11-12-deliv.md`, lines 455-460)
turns the run route into a `DeliverySink.write_table` loop over `result.outputs`, but explicitly
keeps `_write_mask_outputs` as the old non-sink path for `cli/tokenize.py` and `api.py` until C4.
`cli/demo.py:293-301` owns another wrapper over `write_targets`. RUN-STREAM C1a (row 63a, CLI
`plan/run-stream-r6-5` `docs/plans/2026-11-08-run-stream.md`, lines 790-798) adds
`seal_result(outputs)` for run routes. It is not the only post-engine writer.

The check is one function, `missing_target_tables(config_dict, outputs, engine_written) ->
list[str]` in `C:cli/io/_targets.py`: declared file targets whose table is in neither `outputs`
nor the set of tables the engine wrote through the sink. `seal_result` calls it first and raises
`TargetTableMissingError` (`io.target_table_missing`, exit 3) before any write. `write_targets`
calls the same predicate first with an empty `engine_written` set, so tokenize, API and the old
run path refuse too. Demo deletes its local decision and reaches the same check through
`write_targets`. The one predicate and the two writer choke points are guarded together.

Amendment notes for the two plans (the orchestrator applies them to those plan files when this
plan passes the gate; they are written here so the change is reviewed once):

- RUN-STREAM `plan/run-stream-r6-5`, `2026-11-08-run-stream.md`, the `seal_result` bullet at
  lines 790-793: replace "A
  target key that names no output table expects nothing, as in today's `write_targets`
  (`:487-489`) and DELIV's file-target set" with "Every target key names a config table (PROP
  A8a refuses others at config time). A declared file target whose table is neither in `outputs`
  nor engine-written is refused by `missing_target_tables` with `io.target_table_missing`, exit 3,
  before any write (PROP A8b)."
- RUN-STREAM line 1160, AT-C1e: replace "a target key naming no output table (skipped, not
  refused)" with "a target key naming no config table (refused by PROP A8a) and a declared target
  whose table is missing from both resident outputs and the engine-written set (refused by PROP
  A8b before sealing)." Align the revision table at lines 197 and 226 with the same rule.
- DELIV `2026-11-12-deliv.md`, the C2a `run/_execute.py` bullet (lines 834-839 at `plan/deliv` revision 7 read): add
  "`write_targets` calls PROP A8b's shared `missing_target_tables` check before its first write.
  The retained tokenize and API callers therefore refuse until C4; RUN-STREAM's `seal_result`
  calls the same check for sink-aware run routes."

Engine routes and the every-declared-table guarantee. A8b is safe only if every route returns or
streams each config table. The routes, from `E:execution/`:

| Route | How tables reach the CLI |
|---|---|
| full frame (`_pipeline_full_frame.py`) | `outputs` dict, every config table |
| sequential (`_sequential.py`) | `outputs` dict |
| mixed (`_pipeline_mixed_route.py`, `_mixed_static.py`) | `outputs` dict |
| unified slice (`_unified_slice.py`) | `outputs` dict, or rerouted to full frame |
| out-of-core and chunked with a sink (`out_of_core/`, `_chunked_output_sink.py`) | written through the sink (engine-written set) |
| isolated child (`_isolated_reason.py` and the governor) | `outputs` from the child, or a terminal outcome |
| generation only | `outputs` dict |

This table is a claim to prove, not a finding. AT-A8b runs one two-table config per route and
asserts each declared table is in `outputs` or the engine-written set. A route that drops a table
is a finding for that route, fixed at the route; the check is never relaxed to pass it.

### 2.5 Class guard: `swallowed-broad-except` (engine in E-F1, CLI in C-G2)

Row 24zi fixes nine sites by hand. The class is "a broad handler that keeps going", and nothing
stops the tenth. Under the standing "sentry over prose" rule, each repo gets one shrink-only
ratchet over `src/`.

What counts as one site:

- An `except` handler whose type is bare (`except:`), `Exception` or `BaseException` (as a name
  or an attribute such as `builtins.Exception`), or a tuple that holds one of them, and whose
  body holds no `raise` statement. A `raise` inside a nested `def`, `lambda` or `class` in the
  handler does not count as a re-raise.
- A `with contextlib.suppress(...)` or `with suppress(...)` whose arguments include
  `Exception` or `BaseException`.

What does not count:

- A handler with any `raise` in its own body (bare `raise`, `raise X from exc`, or a raise
  under an `if`). A conditional raise is accepted as handled; that under-count is known and
  accepted, since the realistic quiet fallback has no raise at all.
- A handler that saves the error and re-raises after the block. All three must hold: (1) the
  handler binds `as exc`; (2) inside that handler's own body (nested `def`, `lambda` and `class`
  excluded) an assignment stores an expression that holds `exc` into a local name; (3) the same
  function scope has a `raise` whose exception or `from` cause names that local, and that `raise`
  starts lexically after the end of the complete `try` statement (its `end_lineno`, so after
  every handler, `else` and `finally`), not inside a nested `def` or `class`. A raise before the
  `try`, or inside it, does not count. Engine `8796ef691` has about 26 such handlers (for example
  deferred cleanup that raises the first error after closing every resource). They are correct
  and stay uncounted; the exact number is in the E-F1 evidence under the tightened rule.
- Narrow handlers (`except ValueError`, `except OSError`, `suppress(FileNotFoundError)`).
- Anything under `tests/`, `scripts/` or `docs/`.

Count at the base (planning scan, `ast` over `src/` at the revision 5 bases, deduplicated):
engine about 144 sites in 77 files (one `suppress`); CLI about 53 sites in 27 files (four
`suppress`). An earlier row-24zi planning scan counted 158 engine handlers; it did not
exclude the 26 save-and-re-raise handlers and counted a raise in a nested `def` as a re-raise. The exact
numbers are what the guard's `--write` mode records at the slice head.

Mechanism, reusing the existing ratchet:

- One predicate module, engine `tests/sentry/defects/_swallowed_except.py`:
  `swallowed_sites(tree: ast.Module) -> list[Site]`, standard library `ast` only. The CLI vendors
  it byte for byte and pins it in `ci/vendored.toml`, as it already does for
  `tests/sentry/layout/_layout.py` and as the comment-history module does. The rule is written
  once.
- One sentry per repo, `tests/sentry/defects/test_swallowed_broad_except.py`. It counts sites
  per file and compares with the baseline `tests/sentry/baselines/swallowed-broad-except.json`,
  shape `{"sentry_id", "created_in", "entries": {"<repo path>": {"reason", "max"}}}`, the shape
  of the CLI `retired-name-pending.json`. One row in `scripts/dev/sentry_registry.toml` per repo.
  It is a JSON baseline from its first commit, so E2 (E-G2a, E-G2b, C-G1) has nothing to move.
- The sentry fails when a file's count exceeds its `max`, when a file with sites has no entry,
  and when a count falls below its `max` (the message says "lower max to N"), so every fix
  shrinks the baseline in the same PR and no headroom is left for a new site.
- `scripts/dev/ratchet_check.py` already refuses a new key and a raised `max` against the merge
  base. A new file with a swallowing handler is therefore refused twice: by the sentry and by
  the ratchet.
- Each entry carries a reason of at least 15 characters (`MIN_REASON`). The builder assigns one
  of these per file, from reading the handlers:
  - "observation boundary: a telemetry or logger failure must not fail the run" (the engine
    `pyproject.toml` S110 and S112 ignores give the same reason);
  - "fail closed: the handler returns the refusing value";
  - "best-effort cleanup after the primary error is already raised or recorded";
  - "reports a broken install; this command's job is to describe the failure" (for example
    `C:distribution/selfcheck.py`);
  - "unclassified catch-all with no named failure; open 24zi follow-up". This is the honest label
    for any handler the builder cannot place. The build report counts these rows.
- Placement in time: the engine baseline is written at the E-F1 head, after A2, A4 and A6 have
  deleted their catches, so those are never baselined. E-F2 (A5), E-S1b (emit helpers: five
  handlers in `context.py` become one in `_dispatch_sink`) and any later 24zi fix lower the
  `max`. The CLI baseline is written at the C-G2 head. If C-F1a merges first it skips its ratchet
  step and C-G2 writes the baseline without the A7 and A9 sites; otherwise C-F1a lowers it afterwards.

A module split that moves a counted handler into a new file adds a key, which the ratchet
refuses. The split narrows the handler or adds the `raise`; the baseline is never grown. The
per-file comment-history baseline (E-G3, C-G2) has the same property.

Fail-before: the seeded self-test cells below have no scanner to run on main, and the tree test
fails on main with no baseline (about 144 engine and 53 CLI findings).

## 3. Row 24zj PROP-SURFACE

The CLI uses none of these names (`git grep` of `src/` at `ba7b613e`, repeated at `c558e2fb`).
Platform hits are listed where they exist.

Revision 7 re-check at engine `2b8a47fbe` and CLI `d6b9e4c7`: every B item is still on main and
the CLI still uses none of them. Moved anchors: `_F9_KEPT_BINDINGS` at `E:__init__.py:334`;
`deterministic_hash` at `E:internal/crypto.py:19`; the `run_pipeline` keywords at
`E:execution/_pipeline.py:143` (`stream_chunked_output`), `:149-150` (routing), `:155`
(`progress_interval_s`, also read at `:302`), `:157-158` (secrets); the freeze count is still 47
at `ET:unit/execution/test_r3_public_signature_freeze.py:116`, and the contract's 47-count line is
`docs/compatibility-contract.md:99`; the contract's `stream_chunked_output` text is at
`:1186-1194`; `docs/frozen-surfaces.md` lines 101, 103 and 106; `docs/reasons.md:132`; the B2
comment in `E:plan/_compile.py` is at `:51`; the f29 producer baseline key is at
`ET:sentry/baselines/f29-producer-inventory.json:3395` and the fixture row at
`ET:fixtures/f29/producer-inventory.json:1364`. Other anchors below are unchanged.

Revision 5 re-check at engine `8796ef691`: every item below is still on main, so none is
closed. The line anchors are unchanged except where the row says otherwise:
`_F9_KEPT_BINDINGS` at `E:__init__.py:342`; `deterministic_hash` at `E:internal/crypto.py:18`
with its `PERMANENT` row at `ET:sentry/test_deprecation_expiry.py:38-45`; the `ExecutionContext`
leftovers at `E:context.py:248-345`; `TelemetryClient` at `E:context.py:230`; `emit_fidelity` at
`:185`; `E:execution/_events.py` present; the four `run_pipeline` keywords at
`E:execution/_pipeline.py:142,154,156,157`; the alias at `E:validation_result.py:367`;
`event_to_legacy_dict` at `E:_progress_events.py:598`.

Documented-surface check. Each name is on a frozen or documented engine surface:
`docs/frozen-surfaces.md` lines 101 (context and logging), 103 (`ExecutionEvent`) and 106 (progress
events; revision 5 cited 76, 78, 81) list them, and `docs/compatibility-contract.md` names `secret_registry` and
`secret_cache_policy` (lines 43-50) and `stream_chunked_output` (lines 1186-1194; revision 5 cited 842-850). That is not
an open owner question. The contract's own section 1 says pre-GA breaking changes need no shim
or deprecation horizon, and the owner decided this row on 2026-11-15 (delete when no consumer).
Each slice edits those lines in the same commit as the deletion. The names that do have a
consumer (`chunked_dispatcher_enabled`, `multi_table_dispatch_enabled`) stay. The two routing
keywords had no production consumer after all; OQ-4 is re-decided in section 12 and they go in
E-S1c.

| Item | Names | Consumers found | Verdict | Slice |
|---|---|---|---|---|
| B1 | `_F9_KEPT_BINDINGS` in `E:__init__.py` (from `:334`): `BundlePool`, `CompositeAddress`, `PoolCache`, `composite_city_state_zip`, the `Ein`/`Mrn`/`Ndc`/`Npi`/`Ssn` `Adapter`, `Domain` and `Validator` names, `IdentifierError`, `IdentifierFormatError` | `ET:unit/test_identifiers_subimport.py:46-47` only; platform hits are archive logs | Delete the top-level bindings. The names stay importable from their own modules (`decoy_engine.identifiers` and the pool modules). | E-S1a |
| B2 | `deterministic_hash` (`E:internal/crypto.py:19`) | none in src; `ET:unit/internal/test_crypto.py`; the `PERMANENT` row in `ET:sentry/test_deprecation_expiry.py:38-45`, whose rationale ("used when no master key is configured") is stale: no `src/` caller exists | Delete with its tests and the `PERMANENT` row. The five `src/` comments that name it (`E:determinism/_derive.py:77`, `E:execution/_strategies/_hash.py:7`, `E:generators/_formula.py:30,358`, `E:plan/_compile.py:51`) stay: they explain why the keyed scheme replaced it, and editing them would put E-S1a over 10 production files. | E-S1a |
| B3 | `ExecutionContext.resolve_connector`, `captured_outputs`, `pool_resolver`, `column_relationships`, `_exports`, `_current_node_id`, `export()` | none; the platform builds only `ExecutionContext(logger=...)` (`api/storm/router.py:1297`) | Delete. `logger`, `derive_key`, `pipeline_derive_key` and `instance_default_locale` stay (read by `E:execution/_pipeline_full_frame.py`, `_pipeline_mixed_route.py`, `physical/_shadow_generation.py`). | E-S1b |
| B4 | `TelemetryClient`, `ExecutionContext.telemetry` | none | Delete. | E-S1a |
| B5 | `emit_fidelity`, `emit_quarantine`, `emit_step(node_id=)`, and the protocol methods `StructuredEvents.fidelity` and `quarantine` (`E:context.py:83-84`) | tests only; platform `api/persistence/logger.py:337,346` implements the sink methods, on engine 0.18 | Delete the two helpers, the two protocol methods and the keyword. The platform's `Logger.fidelity` and `quarantine` become orphans; the build report lists them, and the stale `ctx.export` comments in `P:api/evidence/assembly.py` and `schema.py` (B3), for the platform. No platform change. | E-S1b |
| B6 | `ExecutionEvent` (`E:execution/_events.py`) | never built | Delete the module and both exports. | E-S1a |
| B7 | `run_pipeline` keywords `progress_interval_s`, `secret_registry`, `secret_cache_policy`, `stream_chunked_output` | no caller anywhere; `stream_chunked_output` has 12 src lines in 6 files (one is the new `E:execution/pipeline/_stream.py:179`) and 3 test lines; `progress_interval_s` is read at `E:execution/_pipeline.py:302`, which keeps the default constant | Delete. `docs/compatibility-contract.md:43-50` names `secret_registry` and `secret_cache_policy` as additive; it records that `SecretCachePolicy` then has no per-run setter (the cache policy is the module default only). The live parameter count is 47 (`ET:unit/execution/test_r3_public_signature_freeze.py:116`, contract `:99`), not the 42 the older paragraph states; E-S1b makes it 43 and adds one dated line with the new count. | E-S1b |
| B7 | `chunked_dispatcher_enabled`, `multi_table_dispatch_enabled` | platform `api/jobs/v2_runner.py:263-264` | Keep; record the consumer in `docs/frozen-surfaces.md`. | E-S1b (doc line) |
| B7 | `use_byte_estimate_routing`, `use_probe_routing` (the `run_pipeline` keywords only) | Revision 5 named the wrong consumer: there is no `E:capacity.py`. The `False` values at `E:execution/_job_estimate.py:184-185` and `E:execution/capacity.py:389-390,448-450` go to the internal `decide_execution_route`, not to `run_pipeline`. No production caller passes the keywords; the callers are 5 bench scripts and 62 test files (revision 7 count) | OQ-4 re-decided: delete both keywords. The internal routing parameters (`_pipeline_context.py`, `decide_execution_route`) stay. Tests and bench scripts that steer routing move to one `routing_overrides` fixture in `ET:conftest.py` that monkeypatches the internal decision the keywords fed; production code is not loosened for tests. Count 43 to 41. | E-S1c |
| B8 | `FK_SELF_REFERENCE` alias at `E:validation_result.py:367`; `event_to_legacy_dict` (`E:_progress_events.py:598`, exported from `E:progress.py` and `__all__`) | tests only | Delete the alias (the code `fk.self_reference` stays). Delete `event_to_legacy_dict`; keep `_LEGACY_FIELDS`, which `event_to_dict` reads. Move the `ET:unit/safe_output/test_value_domains.py:71,281` snapshot pair to `event_to_dict`; update `ET:security/test_f29_remediation.py:27,139,148,332,342`, `ET:unit/progress/test_consumer_contract.py:102`, `ET:unit/progress/test_versioned_contract.py:103` and `docs/reasons.md:132`. E-S1a runs `ET:unit/test_reason_registry.py` and `test_reason_baseline_frozen` on its head. | E-S1a |
| B9 | platform reason codes | platform wire contract | Stays. | none |

Each deletion updates, in the same slice: `docs/frozen-surfaces.md`, `ET:unit/test_public_api.py`
(`test_all_lists_every_public_name`), `ET:unit/execution/test_r3_public_signature_freeze.py`
(B7 only), `docs/compatibility-contract.md` (B7 only), and `CHANGELOG.md` under "Removed".
`ET:sentry/release/test_frozen_surface_map.py` then proves the page matches `__all__`.

Failure mode: an outside user importing a removed name gets `ImportError` or `AttributeError`.
That is the intent before 1.0.

## 4. Row 24zk PROP-SHIMS

No item is fixed on main. Revision 5 re-check at engine `8796ef691` and CLI `c558e2fb`: all
three shim modules (`_source.py`, `_fk_key_compat.py`, `_chunked_adapter_gate.py`) exist;
`_source.py` has 24 importers through the old path (src, tests, scripts); the D8 re-export
lines, the D9 module `__getattr__` (`E:quality/dp_budget.py:503-507`) and the D12 retry
(`E:context.py:143`) are present. Every CLI probe still targets a name that the pinned 0.27.0
ships (checked at tag `v0.27.0`: `run_pipeline` has `unified_slice_enabled` and `progress`;
`native_companion_status`, `estimate_job_capacity`, `EnvFlagError`,
`decoy_engine.internal.logging`, `detection.ner` and `plan.PlanCompileError` exist). No engine
slice removes a name a CLI probe asks for, so no CLI probe removal waits for a repin.

| Item | Site | Change | Slice |
|---|---|---|---|
| D1 | `C:_native_gate.py:506-535` (`run_pipeline_accepts`, an `inspect.signature(run_pipeline)` probe used for `unified_slice_enabled`; `import inspect` at 48; `__all__` entry at 535). New since revision 4: `C:cli/run/_progress.py:51-60` `run_pipeline_kwargs` asks `run_pipeline_accepts("progress", run_pipeline)` (CLI #216) | Pass both keywords. `unified_slice_enabled` and `progress` are in `run_pipeline` (`E:execution/_pipeline.py:152-153`) in the pinned 0.27.0. Delete `run_pipeline_accepts` and `import inspect`. `run_pipeline_kwargs` returns `{"progress": fanout}` whenever `fanout` is set. Delete the tests that pin the probe: the first three cells of `CT:unit/run_progress/test_capability.py` (`:25`, `:39`, `:44`; the `:44` intent, no run module reads an engine signature, moves to the engine-import-guard sentry's `inspect.signature` rule in C-S1b) and the fake-old-engine wrapper case in `CT:e2e/test_run_native.py` (~384-404); `CT:e2e/test_mask_api_native.py:192,346` also uses the probe and moves to the plain keyword | C-S1a |
| D2 | `except ImportError` around engine names: `C:_mask_secret.py:77`, `C:_mask_secret_guidance.py:51-76` and 140 (`_OLD_ENGINE_HEAD`, `_OLD_ENGINE_TAIL`, `OLD_ENGINE_RUN`, `OLD_ENGINE_TOKENIZE`, `OLD_ENGINE_API`), `C:api.py:151-152`, `C:cli/exit_codes.py:274,280`, `C:cli/run/_errors.py:138,150`, `C:cli/run/_prepare.py:428-429`, `C:cli/tokenize.py:306-307`, `C:cli/extras.py:203-206` (`NerUnavailableError`, `PlanCompileError`; was 192-196 at revision 4), `C:ci/engine_logging.py:28-30` (`decoy_engine.internal.logging`) | Plain imports; delete the `OLD_ENGINE_*` texts. Also `C:cli/compile_explain.py:332-346` (`try: from decoy_engine.plan import PlanCompileError ... except ImportError`): an engine probe for a name 0.27.0 ships, not an optional dependency, so it moves here from the kept list. And `C:ci/engine_logging.py:35` `getattr(engine_log, "_LOGGER_INSTANCE", None)` becomes plain `engine_log._LOGGER_INSTANCE` (module-level in 0.27.0, `internal/logging.py:14`). Tests deleted with the branches they cover: `CT:e2e/test_run_mask_secret.py::TestPreDE02EngineGuard` and the `old_engine` tests in `CT:e2e/first_user/test_items_text.py`. `C:cli/exit_codes.py` (shared with 24zf CL3): touch only the probe lines; `exit_code_for` is unchanged. | C-S1b |
| D3 | `getattr(decoy_engine, "native_companion_status", None)` at `C:_native_gate.py:139`, `C:cli/info.py:84`, `C:distribution/selfcheck.py:47`; `hasattr(_engine_execution, "estimate_job_capacity")` at `C:cli/preflight.py:386` (module imported under an alias; was 395-397 at revision 4), and the `native_companion_status` probe at `C:cli/preflight.py:546`; `getattr(engine_errors, "EnvFlagError", None)` at `C:cli/exit_codes.py:233` | Plain attribute access. Also delete the too-old branch at `C:_native_gate.py:352-358` and the `_NativeProbeUnavailable` arms at `:379` and `:393`, with the six `*older_engine*` tests and the skip at `CT:unit/test_exit_code_for.py:112-114`. `selfcheck.py` keeps its `try: import decoy_engine except Exception` (`:42-44`): reporting a broken install is that command's job. | C-S1a (`exit_codes.py` site in C-S1b) |
| D4 | `C:cli/report.py` ~893 `import pandas` guard | Delete (pandas is a hard dependency). | C-S1a |
| D5 | `C:cli/run/_execute.py` ~342-368, `_report_kwargs` left out "so the default call shape stays valid on an older engine" | Pass the keywords. | C-F1a (same hot file as A9) |
| D6 | `C:cli/io/_scan_set.py` `_LEGACY_FIELD_*`, `_from_legacy`, `_legacy_field`; `C:cli/io/_targets.py` ~193 `_legacy_format_for_path` | The reader still has live writers (reference #308, confirmed at `c558e2fb`): `C:cli/demo.py:166` writes `profile_document(profile)`, the untagged shape, and the `decoy.scan()` docstring at `C:api.py:686-688` tells library users to save that shape. C-S2 therefore first switches both writers (D6b), then deletes the readers (D6a): demo writes the value-free `scan-set/v1` core through the same writer `decoy scan --output` uses (the `_multi_payload` shape, `C:cli/scanning/_multi.py:289-298`), and the docstring points at `decoy scan --output`. The fixtures that feed the old shape move to `scan-set/v1` (`CT:fixtures/scan/legacy_profile.json`, `CT:e2e/cli_fmt/test_scan_saved.py`, `CT:e2e/test_scan_fields_show.py`, `CT:e2e/test_scan_diff_move.py:67-68`). Then the readers refuse an untagged or pre-`scan-set/v1` saved scan, and a manifest entry with no `format`, with a coded CLI error (`scan.saved_scan_schema_unsupported`, `io.manifest_format_missing`), exit 1, value-free. OQ-5 re-decided on this fact (section 12). | C-S2 |
| D7 | `E:execution/out_of_core/_source.py`, a re-export of `LazySource` from `E:profile/_readers` | Move 8 src importers (`out_of_core/__init__.py`, `_preflight.py`, `_relation.py`, `_rewrite_pass.py`, `_route_policy.py`, `_runner.py`, `_stage.py`, `_stream_driver.py`), `scripts/build_floor_probe.py:55` and about 15 tests to the public `from decoy_engine.profile import LazySource` (`E:profile/__init__.py:44,66`). Import from `profile._readers` only where an import cycle is proven, and list each such site in the PR. Edit the `E:profile/_readers.py:27` docstring and CODEMAP row 107. Delete `ET:unit/execution/test_out_of_core_source.py::test_lazy_source_is_public_export` and the module. | E-S2a1 |
| D8 | Re-exports in `E:execution/_mem_estimate.py` (~84-93), `_planner_columns.py` (through `_planner`), `_sequential.py:169` (`table_topo_order`), `_chunked_fk.py` (~22-35), `_pipeline_routing.py` (~22-40), `native/_dispatch.py` (`noqa: F401 -- re-exported for tests`) | Importers move to the owning module; the re-export lines go. `run_pipeline` imports the owning modules directly. `_planner_columns` and `_sequential_order` are real modules with their own use (dual paths), not shims: only their 5 old-path importers retarget. Edit engine CODEMAP rows 42 and 111 ("re-exported"). | E-S2b |
| D9 | `E:quality/dp_budget.py` ~499-520, a module `__getattr__` that re-exports `OpenDpReleaseSession`, plus an empty `if TYPE_CHECKING: pass` | Delete. Update the docstrings that name the old path (`E:quality/dp.py:11`, `E:quality/dp_session.py:16`). | E-F1 |
| D10 | `E:execution/_fk_key_compat.py`, a one-line delegate to `_fk_keys.fk_key_value` | Importers (`_pandas_adapter.py:51`, `ET:unit/execution/test_pandas_adapter_helper_kills.py:14`) move; delete; drop its rows in `ET:sentry/layout/test_module_size.py` and the seam test. | E-S2a2 |
| D11 | `E:execution/_chunked_adapter_gate.py`: `chunked_adapter_touches_pandas_ingestion` always returns True | Fold the constant into the one caller (`_chunked_oracle.py:32`) and remove the dead branch; delete the module and its test references (`ET:unit/execution/test_de10_chunked_fk_passthrough.py:365`). | E-S2a2 |
| D12 | `E:context.py` `emit_step` `TypeError` retry | Goes with the emit dispatch helper. | E-S1b |
| D13 | V2 custom-provider table | Not a shim; out of scope (section 1). | none |

Guards that stay, and form the kept entries of the CLI import-guard sentry's baseline:
`C:_private_file.py:45` (Windows `fcntl`) and `C:distribution/selfcheck.py:42-44` (reports a
broken install). `C:cli/compile_explain.py:345` was on this list in revision 5; it is an engine
probe and moved to D2. Two handlers that look alike
are not engine probes and are outside the sentry's scope, since their `try` imports no
`decoy_engine` module: `C:cli/extras.py:98` (the generic missing-extra probe) and
`C:cli/run/_notify.py:37` (the CLI's own `decoy.telemetry` extra).

Failure modes: D1 to D5 rely on the exact engine pin. If the pin ever moves backwards, the plain
import fails at import time with an `ImportError` naming the module, which is the right failure.
D7, D8, D10 and D11 are private paths. A missed importer fails at import, so each E-S2 slice runs
`python -c "import decoy_engine; import decoy_engine.execution"` and the seam tests on the VM in
addition to T1.

## 5. Row 24zl PROP-GUARDS

| Item | Today | Change | Slice |
|---|---|---|---|
| E2 | Each allowlist is written up to four times: an in-code constant in the sentry, `tests/sentry/baselines/<id>.json`, a row in `scripts/dev/sentry_registry.toml`, and a `Source` in `tests/sentry/_baseline_sources.py` (engine 36 rows, 19 `in_code`; CLI 26 rows). | E-G2a adds a `kind` column to `sentry_registry.toml` and builds `SOURCES` from it, so `_baseline_sources.py` stops being a hand table. One loader, `load_allowlist(sentry_id)` in `tests/sentry/_ratchet.py`, reads the source the row names. Source per kind: `in_code` moves to the baseline JSON (the only allowlist from then on); `json_keys` and `from_file` already read a JSON file; `toml_keys` and `import_layer_keys` keep their own files (`pyproject.toml`, `.importlinter`) because those files are the configuration itself. `test_baseline_registry.py` keeps its job (every registry row has its source, every JSON has a row). The shrink-only ratchet keeps its meaning, with two corrections below (module-size fields and `count`). Leftover copies go in the same slices: the CLI middle copy `BASELINE_ROWS` (`CT:sentry/io_policy/test_private_files.py:185`), the nine CLI tests that assert JSON equals constant (their constant no longer exists; each becomes the shared registry check), and the engine `UNCHECKED_HELPERS` three-way copy (`ET:sentry/test_reason_registry.py:202-210` and `:838-848`), collapsed to the baseline. Row 24ze builds on this loader. | E-G2a, E-G2b, C-G1 |
| E1 | Hand list `SENTRIES` in `tests/sentry/test_sentry_manifest.py` (engine about 106 entries, including `tests/secret_providers/test_leak_sentry.py`; CLI about 72). The test cross-checks `scripts/dev/gates.sh` `SENTRY_PATHS`, `LAYER_TEST` and `LAYER_IGNORE`. | `SENTRIES` becomes the glob `tests/sentry/**/test_*.py` plus an explicit tuple of the paths outside `tests/sentry/` (engine: `ET:secret_providers/test_leak_sentry.py` and `test_classifier_equivalence.py`). The gates.sh cross-check stays. | E-G1, C-G1 |
| E3 | `ET:sentry/test_physical_seam_disconnection.py` (1057 lines) holds `test_production_execution_modules_are_byte_identical_to_origin_main` (~296) and its ~720-line allowlist. | Delete that test and its allowlist (owner 2026-11-15). Keep the import-direction tests (~164-221 and ~1039). Update the two CODEMAP rows that describe the seam guard. `.github/workflows/ci.yml:121-128` keeps `fetch-depth: 0` (`scripts/dev/ratchet_check.py:44` needs the merge base) and its comment is rewritten to name the ratchet instead of the deleted gate. | E-G1 |
| E4 | `CT:sentry/layout/test_codemap_paths.py` pins the `KINDS` frozenset of verbatim row titles. | Drop `KINDS`; keep the path-exists test. | C-G1 |
| E6 | Baseline header pins (`doc["created_in"] ==`, `sentry_id`, registry text) in seven CLI files: `CT:sentry/cli_text/test_one_error_emitter.py`, `cli_text/test_stdout_writes.py`, `defects/test_exit_code_owner.py`, `defects/test_exception_context.py:26`, `io_policy/test_config_load_choke_point.py`, `io_policy/test_environment_reads.py`, `io_policy/test_private_files.py`. The engine has none. | Delete the header asserts; `test_baseline_registry.py` already checks every baseline header once. Keep the `exit` check at `CT:sentry/io_policy/test_private_files.py:615` (it is a behavior fact, not a header). Drop the third hand copy of the keys in `test_exit_code_owner.py`. | C-G1 |
| E7 | `ET:sentry/test_wave_b_no_registry_version_literal.py` (obsolete since REG-RELEASE: `REGISTRY_VERSION` moves only at release); `ET:sentry/test_perf_claim_provenance.py` (a forward invariant on `docs/`). | OQ-6 re-decided on reference #308's evidence (section 12): keep the Wave B guard until Wave B closes (its E1.x, E2, E4, E6, E7 and E0r handoffs are not yet written), then delete it with its baseline in the Wave B closing slice. Keep the perf-claim guard's scope; rewrite its docstring to say what it checks (32 docs carry claims; one provenance keyword passes). Strengthening it is a follow-up. E7 therefore changes only one docstring here. | E-G1 |
| Comment history | No guard. | A sentry in each repo fails a new comment or docstring under `src/` that carries a task id, review round, dated decision or reviewer name. C-G2 also rewrites the CLI sentence at `CT:sentry/cli_text/_banned_text.py:8-12` ("Comments and docstrings keep their ids"), which the new guard contradicts. Baseline: per-file counts of today's hits in `tests/sentry/baselines/comment-history.json`, numeric `max`, shrink-only through the existing ratchet. | E-G3, C-G2 |
| K1 | `C:.github/workflows/regen-diagrams.yml` commits `docs/diagrams/{classes_decoy,deps,packages_decoy}.svg` as `github-actions[bot]` after each push to main, with `permissions: contents: write`. | Upload the three SVGs with `actions/upload-artifact`; add a `workflow_dispatch` trigger; `permissions: contents: read`; fix the text that describes the bot commits at `CONTRIBUTING.md:44` and `scripts/dev/gates.sh:18,63,318`; delete the committed SVGs; drop `docs/diagrams/*.svg` from `GENERATED_UNREAD_GLOBS` (`scripts/dev/gates.sh:65`) and the three entries in `CT:sentry/baselines/retired-name-pending.json` (~37-45). `CT:unit/scripts/test_gates_baseline_file.py:710-729` uses synthetic paths and stays. `C:docs/records/2026-11-08-cli-baseline-build.md` is a record and stays. | C-G2 |

Comment-history scanner:

- One pattern module, `tests/sentry/_comment_history.py`, written in the engine. The CLI vendors
  it byte for byte and pins it in `ci/vendored.toml`, as it already does for
  `tests/sentry/layout/_layout.py`. The patterns are written once.
- It reads `tokenize` `COMMENT` tokens and `ast` docstrings (module, class, function). It does
  not read other string literals, so reason texts and test data do not count.
- Patterns (case-sensitive unless marked):
  - Dated decision: an ISO date `\b20\d\d-\d\d-\d\d\b` only in the same comment as one of
    `owner`, `decided`, `decision`, `added`, `fixed`, `merged`, `landed`, `as of`, `per`
    (case-insensitive). A date in parentheses alone does not match (revision 6). An example date
    in a docstring (`"2024-01-15" -> "2024-03-02"`) passes.
  - Reviewer names as whole words: `\b(Dennis|Codex|Barry|Fable)\b`.
  - Review phrases: `plan-gate`, `cold-read`, `\b(review|gate) round \d+\b`, `\bround \d+
    (finding|review)\b`, `\bBLOCKER\b`.
  - Task ids: `\b(Task|Sprint|Slice|Wave) [A-Z0-9][\w.-]*` and `\b[A-Z]{1,6}-\d+[a-z]?\b`, minus
    an exclusion list of standards and code systems: `AES-\d+`, `SHA-\d+`, `UTF-\d+`,
    `RFC-?\d+`, `ISO-?\d+`, `CVE-\d+`, `GHSA-`, `PEP-?\d+`, `ICD-\d+`, `HKDF-`, `FF\d-`.
- Scope: `src/` only.

E2 corrections (revision 6):

- **Module-size fields (OQ-9 correction, `ET:sentry/test_module_size.py` header policy and
  `catalogs/recurring-defects.md` class 11).** In the E2 move only LEGACY entries (over 700
  lines) carry a ratcheted `max`; they are exact and may only shrink. DENSE entries carry a
  separate `ceiling` field that `_ratchet.py` does not treat as shrink-only: it may rise by the
  lines the change adds, never above 700 (`new_ceiling - old_ceiling <= max(0, new_loc -
  old_loc)`), and `ratchet_check` enforces that rise rule for `ceiling` fields. A dense pin moves
  down only when the sentry's 40-line stale rule demands it, and then to `ceiling_for(loc)`, never
  to the raw count. The CLI exact pins on `report.py` and `preflight.py` are legacy (over 700),
  so lowering them is right.
- **`count` is a ceiling.** `_ratchet.max_raised` reads only `max` (`_ratchet.py:108-117`), so a
  moved `count` (CLI `engine-internal-boundary`, `engine-reason-code-copies`) could rise
  unseen. `_max_of` reads `max`, else `count`, so both are ceilings. Mutation: raise one `count`
  by 1; `ratchet_check` goes red.
- **Equivalence proof.** E-G2a's first commit, and C-G1's first commit, add
  `tests/sentry/allowlist-before.json` (a snapshot of each moved guard's decoded allowlist object
  with its Python types: frozenset or dict, int `max`, `count`, `ceiling`) and
  `tests/sentry/test_allowlist_move_equivalence.py`, which asserts the object `load_allowlist`
  returns equals the snapshot. It passes before the move by construction and must still pass
  after it. Each migrated guard keeps one seeded violation that stays red after the move. The
  snapshot and its test are deleted in E-G3 (engine) and C-G2 (CLI), after which
  `ratchet_check` against the merge base carries the guarantee.

Failure modes for package E:

- E2: a sentry that loads its allowlist from JSON but skips the ratchet would accept a grown
  file. Growth is still caught by `scripts/dev/ratchet_check.py`, which compares the JSON against
  the merge base.
- E1: the glob picks up any `test_*.py` under `tests/sentry/`. Accepted: by the CODEMAP rule
  every file there is a sentry.
- E3: with the byte-identical gate gone, a production module under `execution/` could start to
  import the physical seam. The kept import-direction tests fail that, which is the property the
  owner chose to keep.
- Comment history: a false positive on a real word. The negative fixtures pin the known
  non-hits. A new false positive is fixed in the pattern module, never by an inline allow
  comment.

## 6. Design notes

- New structure: one predicate and one compile check (E-F0), one private dispatch helper (emit),
  one post-engine check function (A8b), one loader (E2), one scanner module (comment history).
  Each replaces copies or a gap; none adds a variant expected to grow.
- One place per fact: `_SPAN_DETECTORS` owns runnable regex span ids and exports its derived
  `SPAN_DETECTOR_IDS`; `NER_ENTITY_MAP` owns NER-produced ids; `DETECTOR_DEFAULTS` owns ids the
  library `extra_spans` dispatch contract supports. `SELECTABLE_TEXT_MASK_DETECTORS` and
  `TEXT_MASK_STRATEGY_DETECTORS` are derived views of those sources, and `strategy_supported`
  owns pair compatibility for dispatch and compile. The allowlist is the source its registry row
  names, and the comment patterns live in the engine module vendored by pin. Unknown target keys
  are owned only by `PipelineConfig._targets_distinct`; the CLI consumes that validation and does
  not add a second validator.
- Pattern followed: E2 copies the engine's `env_flags.FLAGS` pattern (one registry a sentry
  derives its inventory from). The E-F0 check follows `check_text_mask_ner_available` (row 30), a
  check in `plan/` wired into all three reported check lists of `_compile.py`.

## 7. Choke points and guard mutations

| Class | Choke point | Guard test | Mutation that must turn the guard red |
|---|---|---|---|
| Text-mask detector inventories (E-F0) | `_SPAN_DETECTORS`, `NER_ENTITY_MAP`, and `DETECTOR_DEFAULTS` are the sources; `SELECTABLE_TEXT_MASK_DETECTORS` and `TEXT_MASK_STRATEGY_DETECTORS` are derived in `E:transforms/text_mask.py` and read by `check_text_mask_strategies` | `ET:unit/plan/test_text_mask_strategy_check.py` proves exact derivation and distinguishes selector ids from override-only ids | Replace `SELECTABLE_TEXT_MASK_DETECTORS` with `frozenset(DETECTOR_DEFAULTS)`: AT-A1g compiles `iso_date` and `person_name` selectors and fails. |
| Detector and strategy pairs (E-F0) | `strategy_supported` in `E:transforms/text_mask.py`, read by `_mask_span` and by `check_text_mask_strategies` | `ET:unit/plan/test_text_mask_strategy_check.py`; a parity case asserts that for every (strategy-detector id, strategy) pair the check refuses exactly when `_mask_span` raises | Make `date_shift` accept any detector: AT-A1a's `ssn: date_shift` refusal goes red because it compiles. The safe parse fallback means this mutation no longer returns the real SSN. |
| Unparseable date span (E-F0) | `_mask_date_shift` | `ET:unit/transforms/test_text_mask_date_shift.py` | Return `matched_text` again: the unparseable-date case shows the input. |
| Unknown target key (A8a) | `PipelineConfig._targets_distinct`, using the target-name helper beside `duplicate_target_groups` in `E:config/_targets.py` | Engine config tests plus `CT:unit/cli_fmt/test_target_table_unknown.py`; the CLI test asserts gate location `targets.custmers` | Drop the validator call: the typo config exits 0. |
| Declared table not produced (A8b) | `missing_target_tables`, called first in both `seal_result` and `write_targets`; demo reaches it through `write_targets` | `CT:unit/cli_fmt/test_write_targets_missing_table.py` plus tokenize, API and demo caller cells | Skip the call in either writer: that writer's cell sees exit 0 and a written file. |
| Native-lane reroute (A5) | the `except` in `E:execution/_unified_slice.py` | `ET:physical/test_unified_slice_exception_boundary.py`, an intended rewrite of the current reroute assertion at `:213` | Widen the catch back to `Exception`: an injected `RuntimeError` reroutes. |
| Observation sinks (emit helpers) | one private `_dispatch_sink` in `E:context.py` | `ET:unit/test_context_emit_dispatch.py` | Delete the `except` in the helper: a raising sink fails the run. |
| Allowlist source (E2) | `load_allowlist` in `tests/sentry/_ratchet.py` (both repos) | new case `test_no_sentry_holds_an_inline_allowlist` in `tests/sentry/test_baseline_registry.py`: an AST walk of `tests/sentry/**` for a module-level `Assign` or `AnnAssign` whose value is a `frozenset`, `set`, `tuple`, `list` or `dict` literal or constructor call, in a module that a registry row of kind `in_code` named before E2 | Re-add `_ALLOWED: dict[str, str] = {...}` to one migrated sentry: the case fails. |
| Comment history | `tests/sentry/_comment_history.py` | `tests/sentry/defects/test_comment_history.py` (both repos) | Drop the reviewer-name pattern: the positive fixture `# per Dennis` no longer fails and the self-test goes red. |
| CLI engine-import probes (D1 to D3) | the exact pin in `pyproject.toml` | `CT:sentry/defects/test_engine_import_guards.py`: an AST walk of `src/` that fails (1) a `try` whose body imports a `decoy_engine` module and whose handler catches `ImportError`, `ModuleNotFoundError`, `Exception` or a tuple holding one of them (`except (ImportError, X)`); (2) `getattr` (with or without a default) or `hasattr` with a string constant on a name bound to a `decoy_engine` module; (3) `getattr` without a default inside a `try` whose handler catches `AttributeError`; (4) `inspect.signature` applied to a name imported from `decoy_engine`; (5) any name starting `OLD_ENGINE_`. Bound-name spellings it resolves, each with one seeded failing case: `import decoy_engine`, `import decoy_engine.x as y`, `from decoy_engine import x` and `from decoy_engine.x import y` where the imported name is a module, and a local alias of any of these. Baseline JSON: the two kept sites listed under section 4, plus, shrink-only, any `cli/run/` site whose hunk rides with its lane holder (C-S1b) instead of landing in C-S1b. | Re-add `hasattr(_engine_execution, "estimate_job_capacity")` in `preflight.py`: the walk fails. |
| Re-export and delegate engine modules (D7, D8, D10, D11) | the walk itself | `ET:sentry/layout/test_no_reexport_modules.py`: an AST walk of `src/` fails a non-`__init__` module (outside the exempt list, which is the JSON baseline `ET:sentry/baselines/reexport-modules.json` with a reason per file, registered in `sentry_registry.toml`, never an in-code constant) whose body is only imports plus `__all__`; an import line marked `noqa: F401` whose comment says "re-export"; or a module whose only function bodies are a single `return` of a call to an imported name with the same arguments (a delegate) | Re-create `_fk_key_compat.py` with its one-line `_fk_key_value` delegate: the walk fails. |
| Swallowing broad handlers (24zi class, section 2.5) | the per-file `max` in `tests/sentry/baselines/swallowed-broad-except.json` (both repos), enforced by the sentry and by `scripts/dev/ratchet_check.py` | `tests/sentry/defects/test_swallowed_broad_except.py` (both repos) over the one predicate `tests/sentry/defects/_swallowed_except.py` (engine source, CLI vendored copy) | Delete the save-and-re-raise exclusion from the predicate: the seeded `saved_then_raised` cell counts 1 and goes red, and the engine tree count exceeds the baseline by the save-and-re-raise handlers. Ordering mutation: drop the "raise starts after the try's `end_lineno`" check; the seeded `raise_before_try` cell counts 0 instead of 1 and goes red. Second mutation: drop the `suppress` branch; the seeded `suppress(Exception)` cell goes red. Tree mutation: add `except Exception: pass` to a `src/` file with no entry; the sentry and `ratchet_check` both go red. |

Each walk is shown to see a seeded violation in a scratch copy before its count is trusted.

## 8. Acceptance tests (fail before, pass after)

Each test is written first and must fail on the base commit named in the header, except where the
row says it pins a no-regression fact.

| Id | Test | Fails before because |
|---|---|---|
| AT-A1a | Compile `text_mask` with `per_detector_strategy` set to each of `{ssn: date_shift}`, `{email: date_shift}`, `{email: fpe}`, `{email: faker}`: `PlanCompileError` with `config.mask.text_mask_strategy_unsupported`, the detector id and strategy in the message, and a marker cell value absent from `str(exc)`, `exc.args`, `__cause__` and `__context__`. Run the same configs on base: the `date_shift` cells' outputs contain the real SSN and email. | Compiles; `ssn: date_shift` and `email: date_shift` write the real value. |
| AT-A1b | `{person_name: fakr}`: `text_mask_strategy_unsupported`. | Compiles; the span becomes the token. |
| AT-A1c | `detectors: [emial]` and `per_detector_strategy: {emial: redact}`: `config.mask.text_mask_detector_unknown`. | Skipped silently. |
| AT-A1d | Parametrize selectors over `SELECTABLE_TEXT_MASK_DETECTORS` and override keys over `TEXT_MASK_STRATEGY_DETECTORS`. Every selector id compiles, every override-only id is refused when moved into `detectors:`, and every pair `strategy_supported` accepts compiles as an override. Direct `mask_cell_with_spans` and native `mask_cell_hybrid` calls inject supported spans and report more than zero calls through each of `fpe`, `faker` and `date_shift`; those direct calls are the source of the faker and date-shift counts. Route cells do not claim those two strategies: after E-F0, config cannot send faker or date-shift spans to native chunked, out-of-core native or SEQ because NER declines native, no built-in date detector exists, and those routes accept no `extra_spans`. | The base collapses selector and override inventories, so override-only ids compile in `detectors:`. The direct kernel counts keep the strategy coverage non-vacuous. |
| AT-A1e | Direct `_mask_span` with an unsupported pair raises tagged `ConfigError` (bypassing compile), maps to CLI exit 1, and a marker value is absent from `str(exc)`, `exc.args`, `exc.__cause__` and `exc.__context__`; `_mask_date_shift` on an injected `iso_date` span `2024-02-30` returns the token. | Returns the token for the unknown strategy and the real text for the bad date. |
| AT-A1f | Before editing fixtures, run `rg -n -U 'detectors_unknown_noop|per_detector[^\n]*(ssn|email|us_phone)[^\n]*(faker|date_shift)|strategy_map[^\n]*email[^\n]*faker|"(email|ssn)"\s*:\s*"(faker|date_shift)"' tests/` and classify every hit with `strategy_supported`; the changed-file list must equal the grep's refused-pair and unknown-id hits. It includes `tests/parity/test_c6b_ii_text_mask_seq.py`, `tests/parity/test_ooc_text_mask_native.py`, `tests/native/test_c6b_i_text_mask_chunked.py`, `tests/native/test_c6b_ii_b_text_mask_splice.py:224-225`, `tests/native/test_c6b_ii_a_text_mask_detection.py:145-147` (not `tests/parity/`), `tests/unit/transforms/test_text_mask_faker_reuse.py:140`, and `tests/native/_c6b_i_support.py:67,80`. Refused `ssn: faker`, `email: faker`, `us_phone: faker` and `ssn: date_shift` fixtures become supported direct `person_name: faker` or `iso_date: date_shift` spans where kernel coverage is intended; `detectors: [no_such_detector]` becomes an explicit refusal test. Each direct replacement asserts its faker or date-shift call count is above zero. | On base the old fixtures pass; after E-F0 they would fail compile. This row pins that every matching test fixture anywhere under `tests/` is classified and coverage is moved, not dropped. |
| AT-A1g | Compile separate configs with `detectors: [iso_date]` and `detectors: [person_name]`. Both raise `PlanCompileError` with `config.mask.text_mask_detector_unknown`; the same ids remain accepted as keys in a supported `per_detector_strategy` pair. Apply the named mutation `SELECTABLE_TEXT_MASK_DETECTORS = frozenset(DETECTOR_DEFAULTS)` and rerun this cell; both invalid selectors compile, so the mutation is red. | Both selector configs compile, but `iter_spans` skips them because neither id is a key of `_SPAN_DETECTORS`; the default unmatched policy redacts the whole cell and passthrough leaves it unchanged. |
| AT-A2 | Monkeypatch `load_table` to raise `FileNotFoundError`: `geo_generalize` with the state fallback raises it. | Returns `""` states with a warning. |
| AT-A3, A4, A6 | No behavior test (unreachable). An ordering test, `ET:unit/plan/test_compile_check_order.py`, pins that `check_unknown_provider` runs before `_build_seed_envelope` (A4 closed on main, revision 7). | Passes before; it pins why each catch is dead. |
| AT-A5 | Inject a `RuntimeError` into `reconstruct_source_shaped_output`: `run_pipeline` raises it, and no `_REROUTE_LOG` record is emitted. | Reroutes and returns success. |
| AT-A5c | Inject, one cell each: a coded decline from `compile_physical_plan`, `pyarrow.ArrowInvalid`, `pyarrow.ArrowTypeError` and `MemoryError`: each reroutes, the run succeeds, and the log names the class (and the code for the decline). A plain `ValueError` and `TypeError` propagate. Mutation: drop `MemoryError` from `_REROUTABLE`; its cell fails the run. Second mutation: replace the Arrow classes with `ValueError`; the plain-`ValueError` cell reroutes and goes red. | Fail-before only for the `ValueError` and `TypeError` cells (they reroute today); the reroute cells pin today's behavior. |
| AT-A5b | In `ET:physical/test_unified_slice_exception_boundary.py`, error parity covers FPE sub-floor with no `sub_floor_span`, checksum failure, a `when:` expression error, the E-F0 `_mask_span` `ConfigError`, and provider failure. A separate pin (revision 7) configures a validator: the slice declines at admission and the oracle raises the validator error. For each, unified-slice on and `unified_slice_enabled=False` raise the same raw exception type, reason code and CLI exit code; the E-F0 execution cell matches the oracle's wrapped `StrategyError`, exit 3, rather than exposing the direct helper's `ConfigError`. | On base the lane catches and reroutes, so the pandas rerun raises; the rewrite pins that removing the catch preserves the oracle boundary rather than exposing a lower-level type. |
| AT-A7 | Set `sys.modules["decoy_engine.config"] = None` (so the import raises `ImportError`) and call `_validate_scaffold`: the `ImportError` propagates. | Returns silently. |
| AT-A8a | Engine config with a `targets:` key `custmers` and a source of that name but no table: `PipelineConfig` refuses it with `config.target_table_unknown`. Through the repinned CLI, `decoy run` and `decoy validate` exit 1 before any source read and locate the gate finding at `targets.custmers`, not `.format`. | Exits 0, no file. |
| AT-A8b | Route matrix (section 2.4): for each run route, a two-table config, then the engine result with one table removed; `seal_result` raises `io.target_table_missing`, exit 3, and neither file is written. Separate cells call the retained `_write_mask_outputs` path through `cli/tokenize.py` and `api.py`, and the wrapper in `cli/demo.py`; each raises the same error before either target is written. A chunked run whose tables were engine-written still exits 0. | Each old writer skips the missing table, writes the other file and exits 0. |
| AT-A9 | The run summary for a golden config is unchanged after the deletion. | Passes before; pins no regression. |
| AT-B | `ET:unit/test_public_api.py` lists the reduced `__all__`; `test_frozen_surface_map.py` passes with the edited page; `hasattr(decoy_engine, "BundlePool")` is False. | `__all__` holds the names. |
| AT-B7 | `test_r3_public_signature_freeze.py` pins the signature without the four keywords; `docs/compatibility-contract.md` states the new count. | The signature has them. |
| AT-D | `test_no_reexport_modules.py` (section 7). | `_source.py`, `_fk_key_compat.py` and the D8 lines exist. |
| AT-C-D | `test_engine_import_guards.py` (section 7). | 13 guarded imports and 7 probes exist. |
| AT-D6 | A saved scan without the `scan-set/v1` tag, and a manifest entry with no `format`: each exits 1 with its code, value-free. | Read through the legacy readers. |
| AT-D6b | `decoy demo` in a temp directory, then `decoy scan show <its scan.json>` and `decoy scan fields <its scan.json>`: both exit 0, and the saved file carries `scan_schema: scan-set/v1` and no cell values. Mutation: restore `profile_document` in demo; with the reader deleted, `scan show` exits 1 and the cell goes red. | On base the demo file is untagged; after C-S2's reader deletion without the writer switch, `scan show` would exit 1. |
| AT-E1 | Add an empty `tests/sentry/test_zz_probe.py` in a scratch copy: the manifest test passes with no list edit. | The manifest fails until the list is edited. |
| AT-E2 | `test_no_sentry_holds_an_inline_allowlist` (section 7). | 19 engine sentries and the CLI `InCode` sentries hold inline constants. |
| AT-E2b | `test_allowlist_move_equivalence.py` (section 5): equal before and after the move; plus one seeded violation per migrated guard that stays red. Mutations: add one key to any moved JSON, or raise one `max` or `count` by 1: the equivalence test and `ratchet_check` go red. Raise a dense `ceiling` by more than the lines the change adds: `ratchet_check` goes red; raise it by exactly the lines added: green. | Passes before by construction; the fail-before proof is AT-E2 and the `count` mutation (today `ratchet_check` ignores `count`). |
| AT-EMIT | `ET:unit/test_context_emit_dispatch.py`: a sink method that raises is swallowed and `caplog` holds one DEBUG record naming the class; a sink `step()` whose body raises `TypeError` is called once, not retried (D12; the fake `CapturingStructured.step` at `ET:unit/test_structured_events.py:40` widens to the protocol signature). Mutation: restore the `TypeError` retry; the call count is 2 and the cell goes red. | Today `emit_step` retries on `TypeError` and logs nothing. |
| AT-E3 | The seam test file runs no `git show origin/main:`; the import-direction tests still fail when a fixture module under `execution/` imports `execution.physical`. | It calls git and compares bytes. |
| AT-E4, E6 | Rename a CODEMAP row title in a scratch copy: `test_codemap_paths` passes. Change one baseline's `created_in`: only `test_baseline_registry` reacts. | `KINDS` and the seven header asserts fail. |
| AT-CH | Positive fixtures (one per pattern family) fail the scanner. Negative fixtures pass: `AES-256`, `UTF-8`, `SHA-256`, `RFC 3339`, `ICD-10`, `Argon2`, `HKDF-SHA256`, "round to 2 decimal places", an example date in a date-shift docstring (`"2024-01-15" -> "2024-03-02"`), a date inside a string literal. The real tree passes against the committed baseline. Adding `# per Dennis round 2` to a src file fails. | No scanner exists. |
| AT-SBE | `test_swallowed_broad_except.py` seeded cells, each a parsed snippet with its expected count: bare `except: pass` (1); `except Exception: log(...)` (1); `except (ValueError, Exception): return None` (1); `except BaseException: continue` (1); `with contextlib.suppress(Exception)` (1); `with suppress(OSError)` (0); `except Exception as e: raise Wrapped() from e` (0); `except Exception: if bad: raise` (0, the accepted conditional case); `except Exception as e: err = e` then `raise err` after the `try` in the same function (0); `except Exception as e: err = e` with no later raise (1); `except Exception:` whose only `raise` sits in a nested `def` (1); `except ValueError: pass` (0); revision 6 ordering cells: `except Exception as e: err = e` with `raise err` after the whole `try` (after its `finally`) (0), and the same handler with `raise err` placed before the `try` in the same function (1); `err` assigned outside the handler and raised after the `try` (1). The tree cell: every `src/` file's count equals its `max`. | No predicate or baseline exists; on main the tree cell has about 144 engine and 53 CLI unbaselined sites. |
| AT-K1 | A `workflow_dispatch` run on the slice branch shows an `architecture-diagrams` artifact with three SVGs (evidence, not a test). `CT:sentry/tooling/test_no_bot_commits.py`: no workflow step runs `git commit` or `git push`, and `docs/diagrams/*.svg` is not tracked. It does not check `permissions:`, so a release workflow that needs `contents: write` to publish (row 93) is not blocked. | `regen-diagrams.yml` commits and pushes. |

## 8a. Class table (recurring defect classes)

| # | Class | How this batch handles it | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | E-F0 closes a live value leak: `date_shift` on a non-date detector and on an unparseable date returned the real text. All new refusals (E-F0 codes, A8a, A8b, D6) name the column, detector id, strategy, table name or path only. | AT-A1a (real value on base, marker absent from the error after), AT-A1e, AT-A8a, AT-A8b. | Return `matched_text` in `_mask_date_shift`: AT-A1e fails. Format a sample row into the A8b message: its marker check fails. |
| 2 | Cleanup missing on an exit path | A8a refuses before any read; A8b refuses before the first write, so no staged file is left. | AT-A8a and AT-A8b assert the target directory holds no new file. | Move the A8b check after the first write: one file remains. |
| 3 | State machine and concurrency | N/A: no state or thread is added. The emit dispatch helper keeps today's swallow rule. | | |
| 4 | Route parity and silent fallback | The batch's main class. The E-F0 check runs at compile, before route choice, so every route sees the same refusal. It also distinguishes built-in selector ids from override-only ids before `iter_spans` can skip the latter. Direct `mask_cell_with_spans` and `mask_cell_hybrid` cells cover the otherwise unreachable faker and date-shift kernel branches. A5 removes a silent route switch. A8b is proved per engine route and per retained CLI writer. The `swallowed-broad-except` ratchet (section 2.5) stops a new quiet fallback in either repo by construction. | AT-A1a; AT-A1g; direct AT-A1d kernel cells; AT-A1f fixture inventory; AT-A5, AT-A5b; AT-A8b route and writer matrix; AT-SBE. | Replace the selector inventory with all `DETECTOR_DEFAULTS` keys: AT-A1g fails. Wire the check into only one check list: the `decoy validate` cell of AT-A1c fails. Widen the A5 catch: AT-A5 fails. Drop the save-and-re-raise exclusion: AT-SBE fails. |
| 5 | Referential integrity | N/A: no key, FK or join behavior changes. The FK dtype catches are kept (section 1). | | |
| 6 | Untrusted producer | The config is the untrusted input for E-F0 and A8a; each is validated once by engine compilation or `PipelineConfig`. Inside, `_mask_span` raises on a pair the compile check should have refused. | AT-A1b, AT-A1c, AT-A1e, AT-A1g, AT-A8a. | Drop the predicate call in `_mask_span`: AT-A1e fails. |
| 7 | TOCTOU on a path | N/A: A8b reads the in-memory outputs and the sink's engine-written set, not the file system. | | |
| 8 | Weak tests and overclaimed evidence | Each acceptance test is labeled fail-before or no-regression pin. AT-A1d now fails on the base inventory collapse and requires non-zero span counts per strategy. AT-A1g names the realistic inventory mutation. AT-A1f, AT-A3/A4/A6, AT-A5b and AT-A9 state their exact role. The A5 flight is void with zero activations. Every new walk is shown red on a seeded violation. | The builder records the base-commit result of each fail-before test in the PR body. | Remove the span-count assertion from AT-A1d: the faker branch can go uncovered unnoticed. Restore `frozenset(DETECTOR_DEFAULTS)` as the selector set: AT-A1g fails. |
| 9 | Refactor drift | The D shim deletions and the emit helper collapse must not change behavior. D11 folds an always-true predicate, so the oracle branch it guarded runs as today. | Existing unit and parity tests for each moved importer stay green on T1; AT-D; `test_context_emit_dispatch.py` asserts each `emit_*` still calls the matching logger method once and a raising method does not fail the run. | Make D11's folded constant False: the chunked oracle tests fail. Swap two method names in the dispatch: the emit test fails. |
| 10 | Frozen contract drift | B1 to B8 and D9 remove public names on purpose, recorded in `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`, `test_public_api.py`, the r3 signature freeze and `CHANGELOG.md` in the same slice. The plan YAML `checks_passed` list changes for every config and its three pin sites move. Reason codes are append-only: `fk.self_reference` stays; the engine adds the two E-F0 codes and `config.target_table_unknown`; the CLI adds `io.target_table_missing`, `scan.saved_scan_schema_unsupported`, `io.manifest_format_missing`. | AT-B, AT-B7, E-F0 plan YAML pins, `test_frozen_surface_map.py`, `test_reason_registry.py`, `test_reason_baseline_frozen`. | Remove a name from `__all__` without editing the page: `test_frozen_surface_map.py` fails. Delete `fk.self_reference` with the alias: `test_reason_registry.py` fails. |

## 8b. Enumerations (from the code at the bases)

### Routes

- Text mask runs on the full-frame strategy (`E:execution/_strategies/_text_mask.py:100`), the
  out-of-core group C path (`E:execution/out_of_core/_mask_group_c.py:259`), the out-of-core
  native path (`E:execution/out_of_core/_text_mask_native.py:75`) and the native operator path
  (`E:execution/native/_operator_params.py:243`), whose FPE eligibility is derived from
  `_FPE_CONFIG` (`E:execution/native/_text_mask_native_fpe.py:41-49`). E-F0 validates
  `detectors:` against the exact built-in selector inventory at compile, before route choice, so
  all four routes refuse `iso_date`, `person_name`, and every other non-runnable selector. After
  that refusal, config cannot make faker or date-shift spans reach native chunked, out-of-core
  native or SEQ: NER declines native, no built-in date detector exists, and the route APIs accept
  no `extra_spans`. Direct `mask_cell_with_spans` and `mask_cell_hybrid` cells cover those kernels.
- A5 is the unified-slice route only (`E:execution/_unified_slice.py:359`).
- A8b: the engine routes in section 2.4.

### Exit paths

- E-F0 compile refusals, A8a and D6: a coded config error, CLI exit 1, at compile or config check
  and in `decoy validate`. A direct caller that bypasses compile gets tagged `ConfigError`,
  CLI exit 1; execution routes expose the oracle's wrapped `StrategyError`, exit 3.
- A2, A5, A6, A7: the original exception propagates; CLI exit 3 (runtime).
- A8b: `TargetTableMissingError`, exit 3, before any write.
- Emit helpers: no exit change; a raising logger method is swallowed and logged at DEBUG.

### FK shapes

- N/A: no FK behavior changes.

### Fields (every key this plan adds or reads)

- No config key is added. E-F0 validates the existing `detectors` list and the keys and values of
  `per_detector_strategy`. A8a validates the keys of the existing `targets` map.
- No result or report field is added. `checks_passed` is an existing field, but E-F0 appends one
  item to it and therefore changes serialized plan YAML for every config.

### Output surfaces

- Masked output bytes: unchanged for every parseable span of every config that compiles after
  E-F0 and uses a runnable selector. An unparseable date-like span becomes the token instead of
  the real text. A config that selected a library-only id such as `iso_date` or `person_name` no
  longer produces the base's whole-cell redaction or passthrough output because it is refused at
  compile.
- Files on disk: A8a and A8b now refuse runs that exited 0 with a missing file; neither writes a
  partial set.
- Logs: A5 removes the `_REROUTE_LOG` line for non-coded exceptions; A2 removes one warning.
- Public API: the B and D9 removals. E-F0 adds only the public-in-package
  `detection.detectors.SPAN_DETECTOR_IDS` derived view; it is not exported from the engine root.

### Lists

- Strategy names: `fpe`, `faker`, `date_shift`, `redact`, `passthrough`.
- Selector inventory: `SELECTABLE_TEXT_MASK_DETECTORS`, derived exactly from
  `SPAN_DETECTOR_IDS`, which is derived from `_SPAN_DETECTORS` keys.
- Per-detector strategy-key inventory: `TEXT_MASK_STRATEGY_DETECTORS`, derived from the selector
  inventory, `NER_ENTITY_MAP` values, and `DETECTOR_DEFAULTS` keys. `DETECTOR_DEFAULTS` is the
  existing source for ids accepted from the library `extra_spans` API.
- `_FAKER_METHOD` keys: `person_name`, `first_name`, `last_name`, `address`, `location`.
- `_FPE_CONFIG` keys: `ssn`, `us_phone`, `us_zip`, `pan`, `fax_number`, `npi`.
- Date detectors: `iso_date`, `us_date`, `eu_date`.
- `write_targets` callers: `C:cli/run/_execute.py` `_write_mask_outputs` (itself called from
  `C:api.py:633` and `C:cli/tokenize.py:371`) and `C:cli/demo.py:295` `_write_mask_outputs`.
  DELIV C2a keeps the tokenize and API old path until C4; demo remains separate. RUN-STREAM C1a
  adds `seal_result` for run routes. `missing_target_tables` is shared by `seal_result` and
  `write_targets`, and demo reaches it through `write_targets`.
- `emit_*` helpers: `emit_step`, `emit_lineage`, `emit_fidelity`, `emit_quarantine`,
  `emit_throughput_sample`. Three remain after B5.
- CLI engine-import guards: the D2 sites (13 imports in 9 files) and the D3 probes (7 sites);
  three allowlisted sites stay (section 4).
- `swallowed-broad-except` baseline keys: one per `src/` file with a counted site (about 77
  engine, 27 CLI at the revision 5 bases), each with a `reason` and a `max`.
- Engine sentry baselines: 36 registry rows (19 `in_code`, 5 `json_keys`, the rest other kinds);
  CLI: 26 rows.

## 8c. Reuse inventory and frozen contracts

- Reuse: `_SPAN_DETECTORS`, `NER_ENTITY_MAP`, and `DETECTOR_DEFAULTS` as the three existing
  detector-id sources; the `plan/_compile.py` check lists that already carry
  `check_text_mask_ner_available`;
  the engine's `PipelineConfig._targets_distinct` validator and `duplicate_target_groups` helper;
  the ratchet and
  `test_baseline_registry.py` in both repos; the CLI vendoring pin `ci/vendored.toml`;
  `scripts/test_flight.py` for OQ-3.
- Frozen contracts touched: `decoy_engine.__all__` and `docs/frozen-surfaces.md` (B1, B2, B4,
  B5, B6, B8 removals, and D9 in E-F1); the `run_pipeline` signature and `docs/compatibility-contract.md`
  (B7); the serialized plan YAML `checks_passed` list; the engine reason registry (three added
  codes); the CLI reason registry (three added codes);
  CLI exit codes (A8a moves a typo config from exit 0 to exit 1, A8b moves a missing-table run from
  exit 0 to exit 3); report tags (D6 drops the pre-`scan-set/v1` reader). The JSON result schemas
  change is documented and pinned. Masking output remains identical for every parseable span of
  every config that still compiles.

## 8d. Pre-mortem

| Risk | Guard |
|---|---|
| E-F0 refuses a pairing users rely on (for example `faker` on `us_phone`) | OQ-2 is decided; the release notes name each refusal and list the supported pairs; `docs/strategies.md` lists them too. |
| E-F0 fixture moves drop faker or date-shift kernel coverage | AT-A1f inventories every refused fixture; direct `mask_cell_with_spans` and `mask_cell_hybrid` AT-A1d cells require non-zero calls. |
| A5 turns a rare native exception into failed customer runs | The OQ-3 flight with a counted instrument and a non-zero activation count; E-F2 can ship after the E-F0 daily train. |
| A8b fires on a route that legitimately streams a table | The check counts the engine-written set; AT-A8b covers each route. |
| A8b lands before its choke point exists | C-F1b waits for DELIV C2a and RUN-STREAM C1a (section 10). |
| A removed public name has an unseen outside user | Pre-GA rule; the platform was checked; the 0.29.0 notes list every removal. |
| A deleted shim still has an importer in a test outside T1 selection | Each E-S2 slice runs the import smoke and the full suite (moved or deleted tests are an escalation trigger). |
| The E2 move loosens a sentry by loading the wrong source | `test_baseline_registry.py` checks each row's source; each migrated sentry keeps its seeded-violation self-test. |
| The comment guard blocks normal work on false positives | Negative fixtures; the baseline holds today's hits; fixes go in the pattern module. |

## 9. Placement

Checked against the engine and CLI CODEMAP "Where Things Go".

| New or moved thing | Path | CODEMAP row | Beside |
|---|---|---|---|
| `SPAN_DETECTOR_IDS` | `E:detection/detectors.py`, derived from `_SPAN_DETECTORS` | Detectors, profiling | `_SPAN_DETECTORS` |
| `strategy_supported`, `SELECTABLE_TEXT_MASK_DETECTORS`, `TEXT_MASK_STRATEGY_DETECTORS` | `E:transforms/text_mask.py` | transforms (owning module) | `DETECTOR_DEFAULTS`, `_FAKER_METHOD`, `_FPE_CONFIG` |
| E-F0 compile check | `E:plan/checks/_text_mask_strategy.py` | plan checks | `plan/checks/_generate_columns.py` |
| E-F0 reason codes | `E:reasons/config/` (the part file that holds `mask.*` codes) | reason registry | `MASK_UNKNOWN_STRATEGY` |
| E-F0 tests | `ET:unit/plan/test_text_mask_strategy_check.py`, `ET:unit/transforms/test_text_mask_date_shift.py`, and existing native/parity files from AT-A1f | unit tests for the owning surface plus named existing route suites | existing `plan`, `transforms`, native and parity tests |
| A5 tests | `ET:physical/test_unified_slice_exception_boundary.py` | Physical seam tests, CODEMAP row 256 | the existing test rewritten at line 213 |
| Emit dispatch helper | private function in `E:context.py` | Public API (private helper in a public module) | the `emit_*` functions |
| A8a validator and code | target-name helper in `E:config/_targets.py`, called by `PipelineConfig._targets_distinct` in `E:config/_pipeline.py`; `config.target_table_unknown` in the engine reason registry | Config models, engine CODEMAP row 247 | `duplicate_target_groups` and `TARGET_SHARED_DESTINATION` |
| A8b check and error | `missing_target_tables` and `TargetTableMissingError` in `C:cli/io/_targets.py`; `io.target_table_missing` in the CLI reason registry | same | `write_targets` |
| A8 tests | `CT:unit/cli_fmt/test_target_table_unknown.py`, `CT:unit/cli_fmt/test_write_targets_missing_table.py` | `tests/unit/cli_fmt/` | other target tests |
| D6 codes | CLI reason registry | same as its `scan.*` and `io.*` codes | |
| Allowlist loader | `load_allowlist` in `tests/sentry/_ratchet.py` (both repos) | Sentry test (`tests/sentry/_ratchet.py`) | the ratchet functions |
| Comment-history pattern module | engine `tests/sentry/_comment_history.py`; CLI vendored copy at the same path, pinned in `ci/vendored.toml` | Sentry test helper; CLI vendored pin | `_ratchet.py` |
| Comment-history sentry | `tests/sentry/defects/test_comment_history.py` (both repos); baseline `tests/sentry/baselines/comment-history.json`; one registry row each | recurring-defect class rules in `tests/sentry/defects/` | other `defects/` sentries |
| Engine-import-guard sentry | `CT:sentry/defects/test_engine_import_guards.py`; baseline `CT:sentry/baselines/engine-import-guards.json` | same | same |
| Re-export sentry | `ET:sentry/layout/test_no_reexport_modules.py` | layout fitness functions | `test_module_size.py` |
| Swallowed-broad-except predicate | engine `tests/sentry/defects/_swallowed_except.py`; CLI vendored copy at the same path, pinned in `ci/vendored.toml` | recurring-defect class rules in `tests/sentry/defects/` (engine CODEMAP "Sentry test" row; CLI vendored pin row) | `tests/sentry/defects/_defect_scan.py` |
| Swallowed-broad-except sentry and baseline | `tests/sentry/defects/test_swallowed_broad_except.py` and `tests/sentry/baselines/swallowed-broad-except.json` (both repos); one `sentry_registry.toml` row each | same; baselines live in `tests/sentry/baselines/` | other `defects/` sentries; `retired-name-pending.json` (CLI) for the per-file `max` shape |
| Re-export sentry exempt list | `ET:sentry/baselines/reexport-modules.json`, one registry row | baselines in `tests/sentry/baselines/` | `module-size.json` |
| Bot-commit sentry | `CT:sentry/tooling/test_no_bot_commits.py` | test tooling rules | other `tooling/` sentries |
| Routing override fixture (E-S1c) | `routing_overrides` in `ET:conftest.py`; the module constants it patches in `E:execution/_pipeline.py` | shared test fixtures | the existing root fixtures |
| E2 equivalence snapshot and test (temporary) | `tests/sentry/allowlist-before.json` and `tests/sentry/test_allowlist_move_equivalence.py` (both repos) | Sentry test | `_ratchet.py`; deleted in E-G3 and C-G2 |
| A5 reroute set | `_REROUTABLE` in `E:execution/_unified_slice.py` | execution (owning module) | the handler it narrows |

Every new element has a present consumer in the same slice; no slice merges a helper for a later
slice.

`E:transforms/text_mask.py` is 650 lines at the base and pinned at 670 by
`ET:sentry/test_module_size.py:143`. E-F0 deletes the inner Faker fallback and both FPE lookup
defaults before adding the predicate and guard, and the finished file must stay at or below 670.
The ceiling is never raised. `transforms/` already has 26 direct entries and its CODEMAP says the
next module requires a named sub-package, so E-F0 adds no sibling transform module merely to evade
the cap. `E:detection/detectors.py` is pre-existing oversize code; adding only the derived
`SPAN_DETECTOR_IDS` beside its owning map is a `V2-LOG` size follow-up, not a change-created design
blocker. E-F0 does not add a module or another detector list.

## 10. Slices

Production files exclude tests, baselines, docs and CI YAML. Each slice stays at or under 10
production files and 800 changed lines; a slice that grows past either splits at the boundary its
row names.

| Slice | Repo | Items | Prod files (est.) | Lines (est.) | Risk | Depends on |
|---|---|---|---|---|---|---|
| E-F0 | engine | Section 2.1 (leak fix, two derived detector inventories, predicate, compile check, detector-id refusal, runtime error boundary, draw-site wording and pin), AT-A1d and AT-A1g inventory and direct-kernel cells, AT-A1f fixture moves, plan YAML pins, changelog, `docs/strategies.md` | 9 (`detection/detectors.py`, `transforms/text_mask.py`, `_strategies/_text_mask.py`, `native/_text_mask_native_fpe.py`, `native/_draw_sites_mask.py`, `out_of_core/_mask_group_c.py`, new `plan/checks/_text_mask_strategy.py`, `plan/_compile.py`, the `reasons/config` part file) | <=800 total changed lines, currently estimated ~680 including tests and docs | R2 (live value leak; wrong output from accepted non-runnable selectors; output and serialized-plan change; new compile refusal) | none; first in the batch; `text_mask.py` stays at or below its 670-line pin without raising it; split before review if either cap is exceeded |
| E-F0 release | engine | Daily train containing E-F0 alone; changelog names the masking refusal, safe date fallback and plan YAML `checks_passed` addition | | | R2 | E-F0 |
| E-F0 repin | CLI | Pin the E-F0 engine release before any surface-lane release | | | R1 | E-F0 release |
| E-G1 | engine | E3, E1, E7 (perf-guard docstring only), `ci.yml` comment | 0 | -800 / +80 | R2 (sentry machinery; Codex rev 5) | none |
| E-G2a | engine | E2 `kind` column, registry-derived `SOURCES`, loader, `count`-as-ceiling and module-size `ceiling` field (section 5), equivalence snapshot and test (AT-E2b), first half of the `in_code` sentries | 0 | ~650 | R2 (shared ratchet machinery) | E-G1 |
| E-G2b | engine | E2 remaining sentries, `UNCHECKED_HELPERS` collapse, `test_no_sentry_holds_an_inline_allowlist` | 0 | ~500 | R2 | E-G2a |
| E-G3 | engine | comment-history guard, pattern module, baseline; deletes the engine equivalence snapshot and test | 0 | ~400 | R2 | E-G2b |
| E-F1 | engine | A2 (coded error, load only when `state` is asked for), A3, A6, A8a, D9 (A4 closed on main); engine `swallowed-broad-except` predicate, sentry, baseline and registry row (tests only, written last so the A2, A4 and A6 deletions are not baselined) | 9 (`transforms/geo_generalize.py`, `plan/_seed_envelope.py`, `execution/physical/_compiler.py`, `quality/dp_budget.py`, `quality/dp.py`, `quality/dp_session.py`, `config/_targets.py`, `config/_pipeline.py`, engine reason registry) | ~300 | R2 (D9 removes an old public import path; A8a adds a config refusal) | E-G1 |
| E-F2 | engine | A5: census, `_REROUTABLE`, AT-A5, AT-A5b, AT-A5c; also narrows the A4-adjacent `except Exception: continue` at `E:plan/_checks.py:637` to the parse error type (`ValidationError`), which E-F1 has no file budget for | 2 (`execution/_unified_slice.py`, `plan/_checks.py`) | ~220 | R2 (a native-lane exception now fails the run) | E-G1; OQ-3 flight and census evidence |
| E-S1a | engine | B1, B2, B4, B6, B8 | 8 (`__init__.py`, `internal/crypto.py`, `context.py`, `execution/_events.py` deleted, `execution/__init__.py`, `validation_result.py`, `_progress_events.py`, `progress.py`) | ~280 | R2 (public API) | none |
| E-S2a1 | engine | D7 | 9 (8 `out_of_core` importers, `scripts/build_floor_probe.py`; `_source.py` deleted; `profile/_readers.py` docstring) | ~150 | R1 (private paths) | E-G1 |
| E-S2a2 | engine | D10, D11, re-export sentry | 2 (`_pandas_adapter.py`, `_chunked_oracle.py`; 2 modules deleted) | ~150 | R1 | E-S2a1 |
| E-S2b | engine | D8 | up to 10 (`_mem_estimate.py`, `_planner.py`, `_sequential.py`, `_chunked_fk.py`, `_pipeline_routing.py`, `native/_dispatch.py`, the importers that move) | ~300 | R1 | E-S2a2 |
| E-S1b | engine | B3, B5, B7, D12, emit dispatch helper | up to 9 (`context.py`, `execution/_pipeline.py`, and the files that carry `stream_chunked_output`, `progress_interval_s`, `secret_registry`, `secret_cache_policy`) | ~450 | R2 (public API, `run_pipeline` signature) | E-S1a (`context.py`); E-S2a2 and E-S2b only by file overlap, so whichever merges second rebases (revision 7); split by keyword if over 10 files |
| E-S1c | engine | B7 routing keywords (OQ-4): delete `use_byte_estimate_routing` and `use_probe_routing` from `run_pipeline`; the internal values become module constants in `_pipeline.py` that one `routing_overrides` fixture in `ET:conftest.py` monkeypatches; 62 test files and 5 bench scripts move to the fixture (estimators in `capacity.py` and `_job_estimate.py` keep their own keywords); docs in `execution/__init__.py:45-53` and `_governor.py:46-47` | 8 (`execution/_pipeline.py`, `execution/__init__.py`, `execution/_governor.py`, 5 bench scripts) | ~600, split by test directory if over 800 | R2 (public `run_pipeline` signature; full-suite trigger: `tests/conftest.py` is a shared fixture) | E-S1b (`_pipeline.py`) |
| Surface release | engine | 0.29.0 (or the next free version at release); notes list every removed name (D9 included), A8a, and the remaining refusals | | | | E-F1, E-S1a, E-S1b, E-S1c; E-F2 if merged by then, else the next train |
| Surface repin | CLI | pin `decoy-engine==0.29.0` (engine repin checklist) | | | R1 | Surface release |
| C-G1 | CLI | E2 (with `count`-as-ceiling, equivalence snapshot, `BASELINE_ROWS` and the nine JSON-equals-constant tests), E1, E4, E6 | 0 | ~650 | R2 (shared ratchet machinery) | none; split E2 from E1/E4/E6 if over 800 |
| C-G2 | CLI | comment-history guard (vendored module), CLI `swallowed-broad-except` (vendored predicate, sentry, baseline, registry row), K1, bot-commit sentry | 0 (workflow YAML, SVG deletions) | ~450 plus the baseline JSON; deletes the CLI equivalence snapshot; rewrites `_banned_text.py:8-12` | R2 | C-G1; E-G3 and E-F1 merged (vendored sources) |
| C-S1a | CLI | D1 (both sites, plus `test_mask_api_native.py`), D3 (except `exit_codes.py`; dead `_native_gate.py` arms and their tests), D4 | 6 (`_native_gate.py`, `cli/run/_progress.py`, `cli/preflight.py`, `cli/info.py`, `distribution/selfcheck.py`, `cli/report.py`) | ~170 | R1 | none (0.27.0 ships every name); `cli/run/_progress.py` is a `cli/run/` hot file, so the orchestrator confirms no open writer holds it (LIB L5a, RUN-STREAM) or the hunk rides with the holder |
| C-S1b | CLI | D2 (with `compile_explain.py`), D3 `exit_codes.py` site, engine-import-guard sentry with one seeded case per covered spelling | 10 (`_mask_secret.py`, `_mask_secret_guidance.py`, `api.py`, `cli/exit_codes.py`, `cli/run/_errors.py`, `cli/run/_prepare.py`, `cli/tokenize.py`, `cli/extras.py`, `ci/engine_logging.py`, `cli/compile_explain.py`); at the cap, so it splits into C-S1b1 (the eight non-`run/` files) and C-S1b2 (`run/` files and the sentry) if one more file appears | ~400 | R1 | C-S1a. `cli/run/_errors.py` and `cli/run/_prepare.py` are hot files: the orchestrator confirms no open writer holds them, or those hunks ride with the holder and the sentry baseline keeps the remaining `run/` sites, shrink-only |
| C-S2 | CLI | D6b and the saved-scan reader merged (#313). Left: the D6 manifest reader (AT-D6), per CLI plan `2026-11-25-prop-shims-d6-manifest.md` | 4 (`cli/io/_scan_set.py`, `cli/io/_targets.py`, `cli/demo.py`, `api.py`) plus the reason registry module | ~300 | R1 | none; `demo.py` is shared with C-F1b, so whichever merges second rebases |
| C-F1a | CLI | A7, A8a acceptance and gate-location pin, A9, D5 | 4 (`cli/init.py`, `cli/gate/_layers.py` only if location rendering needs a fix, `cli/run/_render.py`, `cli/run/_execute.py`) | ~180 | R2 (exit code change on a config that exits 0 today) | Surface repin; the open row 63a RUN-STREAM CLI slices (C1l, C1a, C1b) that edit `_execute.py` and `_render.py` merge first |
| C-F1b | CLI | A8b | 3 (`cli/io/_targets.py`, the module holding `seal_result`, CLI reason registry module) | ~200 | R2 (exit code change) | row 61 DELIV C2a and row 63a RUN-STREAM C1a merged; the section 2.4 amendments applied to both plans |

Ordering:

- E-F0, its own daily engine release and its CLI repin land first. Only then does E-G1 start, so
  the live leak ships ahead of the surface lane and later `execution/` slices stop editing the
  720-line allowlist.
- After E-G1 the lanes run in parallel in separate worktrees: guard lane E-G2a, E-G2b, E-G3; fix
  lane E-F1, E-F2; surface lane E-S1a, then E-S1b, E-S2a1, E-S2a2 and E-S2b in any order (whichever
  merges second rebases), then E-S1c. The surface lane is
  serial because `context.py` (E-S1a, E-S1b), `_chunked_oracle.py` (E-S2a2, E-S1b) and
  `execution/_pipeline.py` and its routing modules (E-S2b, E-S1b) overlap.
- CLI lanes do not wait for the engine except C-G2 (two vendored modules, from E-G3 and E-F1), E-F0 repin, Surface repin,
  and C-F1a's A8a acceptance. C-F1a also waits on row 63a; C-F1b waits on rows 61 and 63a.
- Row 24zj merges before row 93 (REL-GATE). Row 24ze plans on top of E-G2b and C-G1.

Expected size: 20 build slices plus two engine releases and two CLI repins, so 24 PRs. Production
code is net negative; the B, D and E deletions remove about 2,500 lines, most of them the E3 allowlist and
the shims. New root public names: none. New public-in-package name: `SPAN_DETECTOR_IDS` in
`detection.detectors`. New private names: `strategy_supported`,
`SELECTABLE_TEXT_MASK_DETECTORS`, `TEXT_MASK_STRATEGY_DETECTORS`,
`check_text_mask_strategies`, `_dispatch_sink`, `_REROUTABLE`, the `routing_overrides` test fixture,
`missing_target_tables`, `TargetTableMissingError`, `load_allowlist`. New reason codes: engine
`config.mask.text_mask_strategy_unsupported`,
`config.mask.text_mask_detector_unknown`, `config.target_table_unknown`, `transform.reference_table_unavailable` (A2); CLI
`io.target_table_missing`, `scan.saved_scan_schema_unsupported`, `io.manifest_format_missing`.

Testing per slice (owner test-depth rule): T0 per edit, T1 impact selection per commit, gates run
T1 on the exact head. Full suite only on an escalation trigger: E-S1a, E-S1b and E-F1 (frozen
contract), E-S1c (shared `tests/conftest.py` fixture), E-G1, E-G2a, E-G2b and C-G1 (shared test machinery and moved or deleted tests), E-F0
(golden output and moved parity fixtures). All runs on the Mac or a VM through `~/bin/vm-run`,
never on the devbox. Mutation testing only on the E-F0 predicate and check and the A8b check (core
logic). The `swallowed-broad-except` predicate carries the three named mutations of section 7
instead.

## 10a. Ratchets touched

Ratchets touched: new shrink-only baselines `swallowed-broad-except` (one per repo),
`comment-history` (one per repo), `engine-import-guards` (CLI) and `reexport-modules` (engine);
shrinks to the public `__all__`, the `run_pipeline` freeze count, the f29 producer inventory
(one key), module-size pins and the CLI `retired-name-pending` baseline; reason registries grow
by appended codes only. Detail per slice below.

Every census, allowlist, baseline, ceiling and pin that a slice grows or shrinks. "Shrinks" on a
shrink-only baseline is expected and is the point of the slice. Nothing in this batch raises a
`max`, adds a key to an existing baseline, or raises a module-size ceiling. A slice that finds it
must do so stops and reports.

New shrink-only baselines (each born as JSON with a registry row, so E2 has nothing to move):

- `swallowed-broad-except`: one per repo (engine in E-F1, CLI in C-G2).
- `comment-history`: one per repo (E-G3, C-G2).
- `engine-import-guards`: CLI, two kept entries plus any `cli/run/` site whose hunk rides with its lane holder (C-S1b).
- `reexport-modules`: engine exempt list of the re-export sentry (E-S2a2).

Per slice:

- **E-F0**: the draw-site catalogue pin in `ET:native/test_draw_sites_catalogue_pinned.py` is
  re-pinned for the one `mask.text_mask_date_shift` entry and the overall digest (section 2.1).
  The plan YAML `checks_passed` pins move (three sites). Reason registry grows by two
  `UNRELEASED` codes, appended. `text_mask.py` stays at or under its 670 module-size ceiling;
  the ceiling does not move. If the f29 producer inventory refuses the new codes' producer rows
  as growth, the builder stops and reports: the plan does not authorize that growth.
- **E-G1**: deletes the byte-identical allowlist in `ET:sentry/test_physical_seam_disconnection.py`
  (about 720 lines, in-code) and the hand `SENTRIES` list (E1). E7 deletes the Wave B guard and
  E7 keeps the Wave B guard (OQ-6 re-decided) and changes only the perf guard's docstring. All
  are shrinks.
- **E-G2a, E-G2b**: move `in_code` allowlists into their JSON baselines. Keys, `max` and `count`
  values are unchanged; the equivalence test (section 5, "E2 corrections", AT-E2b) proves it.
  `count` becomes a ceiling in `_ratchet.py`. Module-size DENSE entries move as a `ceiling`
  field, which is not shrink-only; LEGACY entries move as `max`. `UNCHECKED_HELPERS` collapses to
  its baseline (E-G2b). The equivalence snapshot is added in E-G2a and deleted in E-G3.
- **E-G3**: adds `comment-history` (new).
- **E-F1**: adds `swallowed-broad-except` (new, written after the A2, A4, A6 deletions). Reason
  registry grows by `config.target_table_unknown` and `transform.reference_table_unavailable`,
  appended. Module-size: a LEGACY (over 700, exact) entry of a file that shrinks moves down to
  the new count. A DENSE entry moves only if the file is now more than 40 lines under its
  ceiling, and then to `ceiling_for(loc)`, never to the raw count.
- **E-F2**: the `except Exception` arm in `src/decoy_engine/execution/_unified_slice.py` becomes
  `except _REROUTABLE`, so that file's `swallowed-broad-except` `max` drops by one (or the key
  goes if it was the file's only site). `src/decoy_engine/plan/_checks.py` drops by one the same
  way.
- **E-S1a**: `__all__` and `docs/frozen-surfaces.md` shrink (B1, B2, B4, B6, B8);
  `ET:unit/test_public_api.py` expected set shrinks; the `PERMANENT` row in
  `ET:sentry/test_deprecation_expiry.py` goes (B2). B8 removes one key from
  `ET:sentry/baselines/f29-producer-inventory.json` (`validation_result.py::CODES::class_attr::'fk.self_reference'`)
  and its row in `ET:fixtures/f29/producer-inventory.json`. `ET:fixtures/f29/reason-baseline.json`
  is never edited (frozen digest); `test_baseline_identities_all_registered` still holds because
  the code `fk.self_reference` stays registered.
- **E-S1b**: `run_pipeline` loses four keywords, so `FROZEN_PARAMETERS` in
  `ET:unit/execution/test_r3_public_signature_freeze.py:116` and the contract count at
  `docs/compatibility-contract.md:87` shrink (47 to 43). `swallowed-broad-except` `max` for
  `src/decoy_engine/context.py` drops from five handlers to one (`_dispatch_sink`). The
  `context.py` module-size entry follows the E-F1 rule: legacy moves down, dense only past the
  40-line stale rule.
- **E-S1c**: `run_pipeline` loses two more keywords (47 to 43 to 41 across the two slices).
- **E-S2a1**: deletes `out_of_core/_source.py`; its rows go from the seam test's lists if E-G1
  has not already removed them.
- **E-S2a2**: deletes two modules; the `_fk_key_compat` row goes from
  `ET:sentry/test_module_size.py`. Adds `reexport-modules` (new).
- **E-S2b**: `src/decoy_engine/execution/native/_dispatch.py` is a DENSE entry at 688 with 677
  lines at `8796ef691`. Losing a few re-export lines leaves it well within 40 lines of its
  ceiling, so its entry most likely does not move; if it does, it moves to `ceiling_for(loc)`.
  The same rule applies to any other dense file that loses re-export lines; a legacy file moves
  to its new count.
- **Surface release and repin**: CLI pin `decoy-engine==0.27.0` moves to the surface release
  (engine repin checklist). The E-F0 repin moves it first.
- **C-S1a**: CLI module-size `SIZE_ALLOWLIST` entries for `cli/report.py` and `cli/preflight.py`
  are legacy exact pins (both files over 700), so they are lowered to the new counts, or dropped
  if a file falls under its cap.
- **C-S1b**: adds `engine-import-guards` (new, two kept entries plus any riding `run/` sites).
- **C-G1**: same as E-G2 in the CLI; no key, `max` or `count` changes; `count` becomes a ceiling
  (CLI `engine-internal-boundary`, `engine-reason-code-copies`).
- **C-G2**: adds `comment-history` and `swallowed-broad-except` (new); `ci/vendored.toml` gains
  two pins (the two engine pattern modules); `CT:sentry/baselines/retired-name-pending.json` loses
  the three SVG entries (K1).
- **C-S2**: CLI reason registry grows by two codes, appended. Four test fixtures change shape to
  `scan-set/v1` (D6b); no baseline moves.
- **C-F1a**: CLI `swallowed-broad-except` `max` drops for `src/decoy/cli/init.py` (A7) and
  `src/decoy/cli/run/_render.py` (A9).
- **C-F1b**: CLI reason registry grows by `io.target_table_missing`, appended.

## 11. Established solutions

- The R2 slices (E-F0, E-F1, E-F2, E-S1a, E-S1b, C-F1a, C-F1b) add no parser, scheduler, protocol or
  method. E-F0 is a validation at an existing compile check list plus a closed lookup over
  existing tables; the rest delete catches or names. The patterns followed are in the codebase:
  `check_text_mask_ner_available` for the compile check, the frozen-surface update steps in
  `docs/frozen-surfaces.md` for removals.
- E2 follows the engine's `env_flags.FLAGS` registry pattern; no library needed.
- Swallowed-broad-except guard. Searched 2026-11-17: "ruff BLE001 blind-except", "pylint
  broad-exception-caught W0718", "ruff S110 try-except-pass baseline". The published rules are
  ruff `BLE001` (blind except), `E722` (bare except), `S110`/`S112` (try-except-pass/continue)
  and pylint `W0718`/`W0719`. The predicate follows `BLE001`: a broad handler that re-raises is
  not flagged. It differs in two ways, on purpose. `BLE001` also exempts a handler that logs with
  `exc_info`, and a logged-and-continued failure is exactly the 24zi class. And `BLE001`'s only
  baseline is inline `# noqa`, which a contributor can add without review; the project's
  `_ratchet.py` baseline is shrink-only against the merge base. The engine already ignores
  `S110`/`S112` globally (`pyproject.toml`, "telemetry paths intentionally swallow"), so turning
  them on would need hundreds of `noqa` lines. The custom code is one `ast` predicate (about 80
  lines) plus a sentry in the existing ratchet framework.
- Comment scanning uses the standard library `tokenize` and `ast`. Ruff (the linter both repos
  run) has no rule that matches comment text against a project pattern list, so a small scanner
  is needed.
- K1: `actions/upload-artifact` is the standard way to publish CI build output.

## 12. Owner questions (decided 2026-11-16 as recommended; OQ-4, OQ-5, OQ-6, OQ-9 and the A5 set re-decided 2026-11-17)

- OQ-1. Scope split: do all nine A items in this batch, although the CLI post-1.0 plan (#284)
  lists A2, A5, A6, A7 and A9 as 1.x patch. Decided: yes. E-F0 (the leak) is V1 under any reading.
- OQ-2. Refuse at compile every detector and strategy pair the code cannot carry out, unknown
  strategy names and unknown detector ids. For `detectors:`, "carry out" means exactly a key of
  `_SPAN_DETECTORS`; the broader derived inventory remains available only to
  `per_detector_strategy` and library-injected spans. Decided: yes, with the two new codes of
  section 2.1.
- OQ-3. Let an unexpected native-lane exception fail the run instead of rerunning on pandas.
  Decided: yes, after the section 2.3 flight shows no reroute from a non-coded exception with a
  non-zero activation count.
- OQ-4. Delete the `run_pipeline` keywords `use_byte_estimate_routing` and `use_probe_routing`.
  Decided under go-with-recommended 2026-11-17, re-decided on new facts: delete (E-S1c). Reason:
  the "documented rollback switch" consumer cited earlier does not exist (no `E:capacity.py`;
  the `False` at `_job_estimate.py:176-177` goes to the internal route), so the keywords serve
  only tests and bench scripts, which move to one fixture. Earlier answer: keep.
- OQ-5. Delete the pre-`scan-set/v1` and pre-CLI-FMT readers. Decided under go-with-recommended
  2026-11-17, re-decided on new facts: yes, after `decoy demo` and the `decoy.scan()` guidance
  write `scan-set/v1` in the same slice (D6b), with coded refusals. Reason: the new fact is that
  demo still writes the old shape, which the writer switch removes; pre-GA there are no saved
  user files to protect, so keeping the reader until a later breaking release buys nothing.
- OQ-6. Wave B guard and perf-claim guard. Decided under go-with-recommended 2026-11-17,
  re-decided on new facts: keep the Wave B guard until Wave B closes, then delete it in the
  closing slice; keep the perf guard and fix its docstring. Reason: reference #308 shows Wave B
  is not finished (its handoffs are not written), so the guard still protects open work.
  Earlier answer: delete the Wave B guard.
- OQ-9 (new in revision 6, from the cross-check). How the E2 move stores module-size pins.
  Decided under go-with-recommended 2026-11-17, re-decided on new facts: LEGACY entries as a
  shrink-only `max`, DENSE entries as a `ceiling` field under the documented rise rule (section
  5). Reason: the sentry's own header policy lets a dense ceiling rise by the lines added, and a
  shrink-only `max` would forbid that.
- A5 reroute set (revision 6, not an owner question before). Decided under go-with-recommended
  2026-11-17, re-decided on new facts: `MemoryError`, `pyarrow.ArrowInvalid` and
  `pyarrow.ArrowTypeError` keep rerouting with the coded declines; all else propagates. Reason:
  each one is a run the oracle completes today (#308), and failing it would be a function break.
- OQ-7 (changed by review finding H2). A target key that names no table is a config error: exit 1
  at config time (A8a). A declared table that the engine did not produce is a runtime failure:
  exit 3 at the post-engine choke point (A8b). Decided: yes to both.

## 13. Follow-ups outside this batch

- The memory note on the physical-seam sentry allowlist is out of date once E-G1 merges; the
  orchestrator updates it.
- D13 goes to the post-1.0 plan as a duplication item.
- Each `swallowed-broad-except` row labeled "unclassified catch-all" is open 24zi debt. The E-F1
  and C-G2 build reports list them; the orchestrator files them as V2-LOG unless one turns out to
  hide a V1 failure, which then gets its own row.
- The post-1.0 plan rows for B1 to B8, D6, D9 and A1 to A9 are marked done as each slice merges.
- The section 2.4 amendments go into the RUN-STREAM and DELIV plan files.
- Wave B closing slice deletes `ET:sentry/test_wave_b_no_registry_version_literal.py` and its
  baseline (OQ-6).
- Strengthen the perf-claim guard beyond a single provenance keyword (E7, V2-LOG).
- Platform: `Logger.fidelity` and `Logger.quarantine` (`P:api/persistence/logger.py:337,346`)
  become orphans after E-S1b, and `P:api/evidence/assembly.py` and `schema.py` carry stale
  `ctx.export` comments (B3). Listed in the E-S1b build report; the platform is parked.
- A1 tests were already deleted in #617 (E-F0); logged here only so the review map is complete.
- Cross-check items not folded in: see the section 17 map; each row there marked "follow-up"
  goes to V2-LOG with its finding id.

## 14. Review round 1 map (Dennis, `68d581ba243c`)

| Finding | Where resolved |
|---|---|
| BLOCKER 1 live leak (`date_shift` and `fpe` on any detector) | Section 2.1; slice E-F0 first; AT-A1a, AT-A1c, AT-A1e; section 7 rows 1 and 2; section 12 OQ-2 |
| H2 A8 split, choke point, plan amendments, routes | Sections 2.2 (A8a, A8b), 2.4; AT-A8a, AT-A8b; section 10 C-F1a, C-F1b and ordering (rows 61 and 63a); OQ-7 |
| H3 FK dtype narrowing | Dropped; section 1 non-goals |
| H4 A5 instrument, callees, parity | Section 2.3; AT-A5, AT-A5b |
| M5 replacement fixtures | AT-A1f; AT-A1d span counts |
| M6 slice file overlaps | Section 10 ordering (serial surface lane) and E-S1b dependencies |
| M7 import-guard scope and split | Section 4 D2, D3 and the allowlist; section 7 import-guard row; C-S1a, C-S1b |
| M8 delegate rule | Section 7 re-export row |
| M9 inline-allowlist guard scope | Section 5 E2; section 7 allowlist row |
| M10 AT-A7 red on base | AT-A7 |
| M11 B7 contract text, `SecretCachePolicy`, AT-K1 scope | Section 3 B7; AT-B7; AT-K1 |
| LOW slice counts | Sections 0 and 10 |
| LOW E6 list | Section 5 E6 |
| LOW section 8b callers | Section 8b Lists |
| LOW comment-pattern negatives | Section 5 scanner patterns; AT-CH |
| LOW `ci.yml` fetch-depth comment | Section 5 E3 |
| LOW `dp.py` and `dp_session.py` docstrings | Section 4 D9 |
| LOW B8 registry tests at E-S1a | Section 3 B8 |
| LOW D6 coded refusal | Section 4 D6; AT-D6 |
| LOW emit-helper count location | Section 2.2 emit row (no count exists; none added) |

## 15. Review round 2 map (Dennis, `68d581ba243c`)

Verdict received: NO-GO, 0 blocker, 1 high, 9 medium, 7 low. H1 is `V1`; M9 is
`DESIGN` because the earlier plan would have created a second target-key validator. The remaining
items are `V2-LOG` plan and coverage corrections and do not independently decide the verdict.

| Finding | Label | Where resolved |
|---|---|---|
| H1 A8b writers | V1 | Sections 2.2 and 2.4; section 7 A8b choke point; AT-A8b; section 8b Lists; C-F1b |
| M1 AT-A1f inventory | V2-LOG | AT-A1f grep and complete anchored fixture list |
| M2 unreachable route cells and date spans | V2-LOG | Section 2.1 default-config statement; AT-A1d direct kernel cells; section 8b Routes |
| M3 `checks_passed` plan YAML drift | V2-LOG | Section 2.1 compile ownership and three list tails; AT-A1d support; section 8b Fields; section 8c contracts; E-F0 slice |
| M4 leak wording and draw-site digest | V2-LOG | Section 2.1 wording and pin paragraph; E-F0 slice |
| M5 runtime error value isolation | V2-LOG | Section 2.1 tagged `ConfigError`; AT-A1e; section 8b Exit paths |
| M6 RUN-STREAM r6-5 amendment | V2-LOG | Section 2.4 amendment notes, including lines 197, 226, 790-793 and 1160 |
| M7 A5 boundary inventory and parity | V2-LOG | Section 2.3 callee table and activation metric; section 7 A5; AT-A5b; Placement |
| M8 E-F0 release order | V2-LOG | Section 10 E-F0 release and repin rows and Ordering |
| M9 one unknown-target validator | DESIGN | Sections 2.2 and 6; section 7 A8a choke point; AT-A8a; Placement; E-F1 and C-F1a |
| L1 `text_mask.py` ceiling | V2-LOG | E-F0 slice line budget; section 9 keeps the existing module and forbids raising 670 |
| L2 both `_FPE_CONFIG` defaults | V2-LOG | Section 2.1 runtime paragraph |
| L3 section 7 mutation effect | V2-LOG | Section 7 detector-and-strategy mutation |
| L4 strict predicate inputs | V2-LOG | Section 2.1 predicate and compile-check paragraph |
| L5 detector set derivation | V2-LOG | Superseded by revision 4's two exact derived inventories in section 2.1 and their equality guard |
| L6 E-F0 estimate | V2-LOG | Section 10 E-F0 row, at most 10 production files and 800 total changed lines |
| L7 AT-A5 placement | V2-LOG | Section 7 A5 guard, AT-A5b and section 9 Placement |

## 16. Codex review after revision 3

Verdict received: NO-GO, one `V1` and one `V2-LOG`. No `DESIGN` finding was raised. The `V1`
decides the verdict; the `V2-LOG` scope correction does not.

| Finding | Label | Where resolved |
|---|---|---|
| E-F0 accepted detector selectors that `iter_spans` cannot execute because the plan derived one inventory from every `DETECTOR_DEFAULTS` key | V1 | Section 2.1 defines exact selector and override inventories from `_SPAN_DETECTORS`, `NER_ENTITY_MAP`, and the documented `DETECTOR_DEFAULTS` library-extra-span source; section 6 names one fact source per inventory; section 7 adds the equality guard and named mutation; AT-A1d distinguishes the inventories; fail-before AT-A1g refuses `iso_date` and `person_name`; sections 8b, 9 and 10 carry the route, placement and slice effects. The shipped-surface paragraph records that no template, init output, testflight manifest, proof manifest or docs example requires migration. |
| AT-A1f grep covered only three test subtrees | V2-LOG | AT-A1f widens the same inventory command to all of `tests/`. |

## 17. Codex rev 5 and cross-check map (revision 6)

| Finding | Tier | Fix |
|---|---|---|
| Codex: save-and-re-raise exemption ignores order and scope | DESIGN | Section 2.5 rule; AT-SBE ordering cells; section 7 ordering mutation |
| Codex: guard-lane slices under-tiered | V2-LOG | E-G1, E-G2a, E-G2b, E-G3, C-G1, C-G2 are R2 (section 10) |
| V1-a A5 decline set | V1 | Section 2.3 rule and census; AT-A5c; section 12 A5 entry |
| V1-b D6b live writer | V1 | Section 4 D6; C-S2; AT-D6b; OQ-5 |
| D-a OQ-9 dense ceilings | DESIGN | Section 5 "E2 corrections"; section 10a; OQ-9 |
| D-b `count` invisible to the ratchet | DESIGN | Section 5; AT-E2b mutation; section 10a C-G1 |
| D-c E2 equivalence proof | DESIGN | Section 5; AT-E2b; snapshot removal in E-G3 and C-G2 |
| D-d import-guard gaps | DESIGN | Section 4 D2 and kept list; section 7 sentry spellings; C-S1b |
| D-e D7 target | DESIGN | Section 4 D7 |
| D-f OQ-4 consumer fact | DESIGN | Section 3 B7; E-S1c; OQ-4 |
| V2-LOG 1 A2 | folded | Section 2.2 A2; E-F1 |
| V2-LOG 2 `plan/_checks.py:638` | folded | E-F2 |
| V2-LOG 3 `isinstance(outputs, dict)` | folded | Section 2.2 A8b; C-F1a, C-F1b |
| V2-LOG 4 emit helpers | folded | Section 3 B5; AT-EMIT |
| V2-LOG 5 A7 test comment | folded | Section 2.2 A7 |
| V2-LOG 6 A9 lane | folded | Section 2.2 A9 |
| V2-LOG 7 B7 count | folded | Section 3 B7; section 10a |
| V2-LOG 8 B8b tests and docs | folded | Section 3 B8 |
| V2-LOG 9 platform note | folded | Section 3 B5; section 13 |
| V2-LOG 10 `test_mask_api_native.py` | folded | Section 4 D1 |
| V2-LOG 11 D2 and D3 tests and dead arms | folded | Section 4 D2, D3 |
| V2-LOG 12 C-S1b hot files | folded | Section 10 C-S1b; section 7 baseline |
| V2-LOG 13 `exit_codes.py` scope | folded | Section 4 D2 |
| V2-LOG 14 E-S2a count | folded | E-S2a split into E-S2a1, E-S2a2 |
| V2-LOG 15 D8 dual paths | folded | Section 4 D8 |
| V2-LOG 16 E3 risk | folded | E-G1 R2 |
| V2-LOG 17 E6 | folded | Section 5 E6 |
| V2-LOG 18 E2 leftovers | folded | Section 5 E2; E-G2b, C-G1 |
| V2-LOG 19 E7 and OQ-6 | folded | Section 5 E7; OQ-6; section 13 |
| V2-LOG 20 comment-history | folded | Section 5 scanner and C-G2 |
| V2-LOG 21 K1 | folded | Section 5 K1; AT-K1. The CI lane files that name the workflow are rechecked only if its trigger or job name changes |
| V2-LOG 22 E1 outside paths | folded | Section 5 E1 |
| V2-LOG 23 A1 tests | logged | Section 13 |
