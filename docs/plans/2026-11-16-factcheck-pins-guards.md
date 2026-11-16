Status: plan

# Fact-check fixes, certified pins and duplication guards (roadmap rows 24z, 24za, 24zc, 24ze)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `catalogs/recurring-defects.md`, `testing.md` (test depth),
`cross-cutting-concerns.md`, `config-secrets-and-supply-chain.md`, `release-and-rollback.md`,
`documentation.md`; engine `CODEMAP.md` ("Where Things Go"); CLI `docs/ROADMAP.md` rows 24z,
24za, 24zb, 24zc, 24zd, 24ze, 24zi to 24zl; owner memory rules: V1 bar, no new features
(2026-11-16), PLAN defines acceptance tests, develop correctly (registries and sizing), sentry
over prose, dev-loop review 2026-11-11.

Revision 2: resolves Dennis round 1 on `2fad04c9a` (H1, M1 to M9, L1 to L6).

Bases (2026-11-16): engine `origin/main` `13c95c7de` (release 0.27.0 is in); CLI `origin/main`
`60cac678` (pins `decoy-engine==0.27.0`, CLI #290 `bcd025bd`). Plans read and sequenced
against: engine `plan/date-shift-unkeyed-1116` (`dfb8a9453`, row 24zb), engine `plan/prop-batch`
(`feeeccc01`, rows 24zi to 24zl), CLI `plan/certified-pin-cves` (`9bf16551`, the earlier 24zc
plan, written on CLI `ac0cb686` and engine 0.22.0). Inputs: the duplication census
`C:docs/records/2026-11-12-duplication-census/REMEDIATION.md` sections D and G, engine
`docs/qa/06-mask-core-strategies.md` (open point on collisions).

Notation: `E:` is engine `src/decoy_engine/`, `ET:` engine `tests/`, `C:` CLI `src/decoy/`,
`CT:` CLI `tests/`. A repo path with no prefix is in the engine repo unless the slice says CLI.

## 0. Why one plan, and why in the engine repo

The four rows share one engine release and one CLI repin (24z's report code and 24zc's
certified row both ship in the next engine release, and the CLI repins once to take both). Of
the 10 slices below, 7 land in the engine. Each row has its own section; the slices, ordering
and owner questions are shared.

Owner ruling 2026-11-16: the 2026-11-11 automated-scan rows (24zb, 24zc) are built now, not held
for their QA pass. Rows 24z, 24za and 24ze carry no QA hold. All four build now.

## 1. Pinned guarantee and non-goals

Guarantee (V1 rules only):

- (a) 24z: no engine or CLI document says deterministic `faker` maps distinct inputs to distinct
  outputs, and a `--post-validate` run reports, per deterministic `faker` column, how many
  distinct source values were lost to shared masked values. The report holds names and
  counts only, never a value.
- (b) 24za: `docs/strategies.md` has a section for every user-facing mask strategy in the handler
  registry, says what each `format_error` strategy does with an unparseable cell, and no engine
  document says a keyed strategy falls back to or keys off `job_seed`. A sentry keeps the
  section list equal to the registry.
- (c) 24zc: the shipped certified DP set pins exactly certifi 2026.10.18, cryptography 50.0.0,
  pyasn1 0.6.5 and urllib3 2.8.0; no other pin line moves; a real DP fit still completes on the
  certified platform with the CLI's engine pin.
- (d) 24ze: the census sites that have no guard today (RNG construction, `hmac.new`, Arrow text
  predicates, engine environment reads, CLI stdout writes, literal exit codes in any call form,
  unwatched file operations) each get a sentry with a shrink-only baseline; the draw-site catalog
  no longer moves when a line shifts; the release prep writes the DP certified rows. No behavior
  change in 24ze.

Non-goals:

- A collision-free `faker` mapping (owner question OQ-1). It would need a stored per-value
  table. `fpe` is the one-to-one strategy (within its format domain); untruncated `hash` and
  `tokenize` are collision-resistant.
- Making the collision report always-on (OQ-2).
- Any `date_shift` text that 24zb E1 owns (section 3, ordering).
- Changing `bucket_perturb` behavior on unparseable cells (finding F-1, section 3; a new row).
- `jscpd` (D1), recommended for V1+ (OQ-5).
- D3, D7, D8 and the CLI half of D6: already done on main (section 5).
- Moving any certified pin but the four, raising the `cryptography>=42` floor, a `pip-audit` CI
  step, or the parked platform (the earlier 24zc plan's parked-platform exception carries over
  unchanged).

## 2. Row 24z FAKER-POOL-DISTINCT

**Done on main:** nothing. `git log` on engine and CLI main since 2026-11-11 has no change to the
pool sampler, the cardinality scan or the collision text.

**Facts at the base.**

- Deterministic `faker` selects `pool.values[derive_index(mask_key, namespace, canonical source,
  pool_size)]` (`E:generation/pool/_sampler.py:307` `_deterministic`, through
  `_derive_pool_indices` at `:119`; the handler passes `ctx.mask_key` at
  `E:execution/_strategies/_faker.py:140`). Two distinct sources share an output whenever their
  indices meet or the pool holds a repeated value. With the default pool of 10,000, 1,000
  distinct sources already give about 50 shared slots (birthday bound), and a name provider's
  pool holds fewer distinct values than its size.
- `docs/strategies.md:1114` says "By default deterministic identifier and pool strategies
  preserve cardinality: distinct source values map to distinct masked values within a namespace",
  and `:1134` says "The default stays collision-free". Both are false for `faker`.
  `allow_collisions: true` is an alias for `cardinality_mode: reuse` plus `deterministic: true`
  (`E:config/_tables.py:112-117`), which is the same selection a plain deterministic column gets.
- A collision-free mapping is not possible without state: a source domain with no bound maps into
  a finite pool. Only `fpe` is one-to-one, and only within its format domain. `hash` is a keyed
  digest that NFC-normalizes text first and may be truncated (`docs/strategies.md:44-49`);
  `tokenize` is a 128-bit derived token. Both are collision-resistant when not truncated; a
  `truncate` brings collisions back. `docs/security/token-vault.md:105` calls `hash` under a
  namespace "collision-free", which is the same overclaim.
- The opt-in post-validation suite already records `DistinctCount(source_distinct,
  output_distinct)` per masked column (`E:validation/post/_checks/_cardinality.py:44-45`), on every
  route: post-validation forces the resident output path (`E:execution/_chunked_output_sink.py:120`,
  reason `route.post_validation`), and the summary attaches at
  `E:execution/_pipeline_finalize.py:349-351`. The CLI `--json` envelope carries
  `report.quality_summary` (`C:cli/run/_render.py:128-131`); the human renderer prints failed checks
  only (`C:ui/summary.py:308`).

**Scope (recommended answer to OQ-1 and OQ-2).** Correct the promise and report the count through
the existing cardinality scan.

**V1 behavior.**

- `run_cardinality` gains one rule. Which columns: seed `strategy == "faker"`, `deterministic`
  true, `when` empty, and `cardinality_mode` not `unique` and not `match_source_cardinality`.
  `PoolSampler.sample` sends every deterministic mode except `unique` (refused) to
  `_deterministic` (`E:generation/pool/_sampler.py:218-243`), so `reuse` and
  `scale_source_cardinality` both get the keyed pick and both are covered.
  `match_source_cardinality` is excluded because the same scan already warns
  `CARDINALITY_MATCH_DEVIATION` for exactly this deviation in that mode; one fact, one warning.
- How it counts: over the row-aligned source and output (`ctx.sources`, the post-quarantine rows),
  `source_distinct` is the number of distinct non-null source values after the sampler's own
  canonical form (`_canonicalize_source`), `output_distinct` the number of distinct non-null
  outputs on those rows, and `distinct_lost = source_distinct - output_distinct`. This is the
  number of distinct values lost to merging, not the number of source values that share an
  output; the docs and the CLI line say so. When `distinct_lost > 0` it emits a `QualityWarning`
  with the new warning code `cardinality_collisions` and detail `{table, source_distinct,
  output_distinct, distinct_lost, pool_size}`: names and counts only.
- `pool_size` is the effective size from `resolve_faker_pool_identity` (`E:generation/pool/_identity.py`),
  called with the column's provider, plan pool size and namespace, the same call the handler makes
  (`E:execution/_strategies/_faker.py:90`). No second default is restated. There is no
  `allow_collisions` key: the compiler folds it into `cardinality_mode` and `deterministic`
  (`E:plan/_seed_envelope.py:204-221`), so the seed does not carry it.
- The new code is added to the `QualityWarning` code list in the `E:generation/pool/_events.py`
  docstring.
- The existing `DistinctCount` entry for that column is unchanged (same keys, same profile-first
  source count), so the frozen `quality_summary` shape does not move.
- A `when:`-gated column gets no collision warning: its unmasked rows keep source values, so the
  count is not defined. The docs say so.
- `docs/strategies.md`: the `faker` section and the "Intentional collisions" section say that
  deterministic `faker` is a keyed many-to-one pick, that distinct inputs can share an output by
  default, how pool size changes the rate, that `allow_collisions` only states this explicitly,
  that `fpe` is one-to-one within its format domain, that untruncated `hash` and `tokenize` are
  collision-resistant and a `truncate` makes collisions likely again, and that `--post-validate`
  reports the count. `docs/security/token-vault.md:105` is corrected the same way (exact round
  trips need `fpe`, or an untruncated `hash` or `tokenize`, where a collision is negligible, not
  impossible). `docs/qa/06-mask-core-strategies.md`: MASK-10 becomes a normal check against the
  warning, and the open point is closed. `docs/qa/16-vault-and-unmask.md:27` already says round
  trips need a collision-free column; unchanged. The `E:config/_tables.py:112-117` comment is
  corrected to match.
- CLI: `render_post_validation` prints one line per `cardinality_collisions` warning,
  `table.column: M distinct source values became K distinct masked values (N merged, faker pool
  P)`, in warn-only and enforce modes, on both the all-passed path and after the failed-check
  table. It matches the code through the engine constant from `decoy_engine.reasons`, never a
  literal string or an allowlist entry. It does not change the exit code. `--json` already carries
  the warning.

**Failure modes.**

| Failure | Signal | Caught by |
|---|---|---|
| The count is computed against the full pre-quarantine source while the output lost rows | `distinct_lost` too high | AT-Z4 |
| The count uses raw values while the sampler canonicalizes | `distinct_lost` wrong | AT-Z5 |
| A when-gated column reports a count mixing passthrough rows | wrong warning | AT-Z3 |
| A source or output value is formatted into the warning | value in the report | AT-Z2 |
| Only one route produces the warning | route parity break | AT-Z6 |
| Human output still says nothing | CLI user never sees the count | AT-Z8 |

## 3. Row 24za ENGINE-DOCS-TRUTH

**Done on main:** nothing for the three items. Engine #565 (`63beef10b`) and #582 (`6367af593`)
changed code the docs describe but not the docs.

**Facts at the base.**

- `docs/strategies.md:16` says "There are seventeen mask strategies". The generated
  `docs/capability-matrix.md` lists 24 user-facing names, and `docs/strategies.md` has `###`
  sections for 18 plus `passthrough`. Missing: `tokenize`, `top_code`, `group_key`,
  `grouped_series`, `windowed_date`. The capability-matrix sentry
  (`ET:sentry/test_capability_matrix.py`) checks the matrix against the registry, not the
  narrative page.
- `bucketize` records a `format_error` row error for a non-numeric non-null cell
  (`E:execution/_strategies/_bucketize.py:126-141`), and `date_shift` does the same for an
  unparseable date (`E:execution/_strategies/_date_shift.py:233-241`); the run then fails or
  quarantines the row by the row-error policy. `docs/strategies.md:149` (date_shift) and `:276`
  (bucketize) say these cells pass through.
- `docs/determinism.md:59-70` says `mask_key` falls back to `job_seed` with no provider. Every
  strategy in `ALWAYS_KEYED_STRATEGIES` (`E:secret_providers/_requirements.py:173-188`), and any
  deterministic or vault column, is refused without a secret
  (`runtime.keyed_strategy_requires_secret`) in every release phase. The same false statement is
  in more places: `docs/strategies.md:167` and `:193` (`bucket_perturb`, `derive(job_seed, ...)`;
  the handler passes `ctx.mask_key`), `:437` (`text_mask`, `HMAC-SHA256(job_seed, ...)`), `:619`
  and `:625` (`joint_mask`), `:695` and `:700` (`code_set`), and `docs/determinism.md:124-125`
  (FPE key) and `:217` (shuffle). OQ-3.

**Ownership split with 24zb.** 24zb's plan (Q2, recommended yes) folds two sentences into its E1:
the `date_shift` "unparseable values are left as-is" line (`docs/strategies.md:149`) and the
`docs/determinism.md` fallback paragraph. This plan takes everything else in 24za. If 24zb E1 has
merged when slice A-E1 starts and Q2 was yes, A-E1 leaves those two alone. If Q2 was no, or 24zb E1
has not merged by 2026-11-25, A-E1 takes both and the 24zb builder drops them from E1 (a two-line
note in the 24zb PR). One writer per sentence either way.

**V1 behavior (docs only, plus one sentry).**

- The count sentence in `docs/strategies.md` is replaced by a pointer to
  `docs/capability-matrix.md`, so there is no second count to drift.
- Five new `###` sections, each stating options, keyed or not, null handling, and the refusal codes
  the handler raises, read from the handler and its compile checks. No new behavior is described.
- `bucketize` and (if A-E1 owns it) `date_shift`: an unparseable non-null cell is a `format_error`
  row error, so the job fails or the row is quarantined per the row-error policy; nulls stay null.
- `bucket_perturb` text: it says "same contract as date_shift", which is now false. The text states
  what the code does today (`E:transforms/bucket_perturb.py:181` keeps the cell) and drops the
  cross-reference. See finding F-1.
- Every keyed-strategy derivation in both pages names `mask_key`; the fallback paragraph is
  replaced by the no-fallback rule, matching `docs/security/key-derivation.md`. A sentence that
  is true for a generation sub-path (for example `joint_mask` generate mode) stays, named in the
  sentry's allowlist with its reason.

**Finding F-1 (not in this plan).** `bucket_perturb` passes an unparseable date through in clear
text with no row error (`E:transforms/bucket_perturb.py:181`, `continue  # preserve null /
unparseable values`), while `date_shift` records `format_error`. That is a source value in the
output of a masking strategy. Under the owner rule of 2026-11-16 a fix to an existing feature is a
new V1 row; the orchestrator adds it (OQ-6). 24za documents today's behavior until that row lands.

**Failure modes.**

| Failure | Caught by |
|---|---|
| A new mask strategy ships with no `docs/strategies.md` section | AT-A1 |
| A new `format_error` strategy's section says cells pass through | AT-A2 |
| A keyed section says `derive(job_seed` or `HMAC-SHA256(job_seed` again | AT-A3 |
| 24za and 24zb both edit one sentence | ordering rule above; the second PR conflicts in git |

## 4. Row 24zc CERT-PIN-CVES

**Done on main:** none of the four pins. CLI `requirements-certified.txt` still holds
`certifi==2026.7.22` (line 56), `cryptography==49.0.0` (59), `pyasn1==0.6.4` (92) and
`urllib3==2.7.0` (115). The engine lock already holds exactly the four fixed versions (engine
`uv.lock`: certifi 2026.10.18, cryptography 50.0.0, pyasn1 0.6.5, urllib3 2.8.0), so the engine
dev/CI row is already certified with them.

**The earlier plan carries over.** CLI `plan/certified-pin-cves` (`9bf16551`) is the design: same
guarantee, exact-delta test against a pre-repin fixture, fingerprint and public-admission tests in
`CT:unit/test_sbom_script.py`, the exact-50.0.0 Ed25519 cell, mutations M1 to M5, the parked
platform exception. This section records only what changed since it was written on CLI
`ac0cb686`; the builder works from that plan with these corrections.

| Then (CLI `ac0cb686`) | Now (CLI `60cac678`) |
|---|---|
| 63 pins | 67 pins (SCAN-ML M2 added scikit-learn, lightgbm, joblib, threadpoolctl; `CT:unit/test_sbom_script.py:312` asserts 67) |
| engine 0.22.0 | engine 0.27.0, fingerprint `789b1eae...` |
| 15-file repin list from CLI #184 | the file list of CLI #290 (`bcd025bd`): `ci.yml`, `release-smoke.yml`, `CHANGELOG.md`, `LICENSING.md`, `README.md`, the two shape-and-privacy guides, `docs/release/fresh-install-smoke.md`, `pyproject.toml`, `requirements-certified.txt`, `requirements-dev.lock` (engine line only, through `scripts/dev/lock.sh`), `scripts/cert_smoke.py`, `scripts/dev/bootstrap.sh`, `scripts/dev/lock_version.sh`, `C:ci/rule_codes.py`, the e2e version pins, and `tests/fixtures/release_freeze/json-shapes.json` when the engine adds a report shape |
| build at the section-13 QA pass | build now (owner 2026-11-16) |

**Drift found at the base.** `requirements-certified.txt` lines 5 and 25 still name engine 0.26.0
and `scripts/cert_smoke.py`'s docstring still names fingerprint `dceac0cd...`, after #290 moved the
pin to 0.27.0. C-C1 rewrites the header anyway; AT-C7 adds a check that the header's engine
version and fingerprint equal the `pyproject.toml` pin and the computed value, so the next repin
cannot leave them stale. That check is the CLI half of the G2 class (hand-edited release facts).

**Engine side, simplified.** Every engine release already adds one CLI-profile row computed from
the CLI pins for that engine version (`E:quality/dp_provenance.py:273-327`, "one per engine
release, newest first"). For release N the release prep adds two CLI-profile rows: the usual one
(today's pins plus N) and row F (the four new pins plus N). Then the CLI may repin to N with or
without the four pins in either order, and a prop-batch repin to the same release does not block
this row (OQ-4). If G-E4 (G2, below) has merged before N's release prep, the script computes both
rows; otherwise they are computed by hand as today.

**Failure modes** are the earlier plan's table, plus:

| Failure | Caught by |
|---|---|
| A CLI repin to N lands before row F exists in any release | C-C1 cannot merge: the certified-profile CI job fails `dp_stack_uncertified` (AT-C5) |
| The header names an engine version or fingerprint other than the real pin | AT-C7 |
| cryptography 50 breaks CLI Ed25519 signing or verification | AT-C6 |

## 5. Row 24ze DUP-GUARDS

**State of each item at the base.**

| Item | Census row | State on main | This plan |
|---|---|---|---|
| D1 jscpd | all | not started | V1+ (OQ-5) |
| D2 RNG construction | EX-2 | partly: `ET:sentry/defects/test_rng_construction.py` (#582, `6367af593`) holds the seed-form rule and says "The census of the other `default_rng` sites is 24ze's" | add the construction census, slice G-E1 |
| D3 canonical JSON | EX-1 | done: `ET:sentry/defects/test_canonical_json_choke_point.py` (24zf E1, #581 `b1254eb1`) | none |
| D4 `hmac.new` | EX-3 | not started (`ET:sentry/test_hkdf_is_pyca.py` covers the HKDF module only) | G-E1 |
| D5 Arrow text predicates | ED-1 | owner exists: `E:_arrow_types.py` `is_text`, `is_text_or_null` (#565, #570); no sentry; inline `pa.types.is_string` in 26 files | G-E2 |
| D6 engine env reads | ED-6 | partly: `ET:sentry/defects/test_environment_reads.py` (#580, `8a77c8b6f`) guards flag parsing only; 12 read lines are not inventoried | G-E2 |
| D6 CLI env reads | CX-5 | done: `CT:sentry/io_policy/test_environment_reads.py` (CLI #243, `af9b07fc`) | none |
| D7 CLI error text | CX-1 | done: `CT:sentry/cli_text/test_one_error_emitter.py` and the ratchet (CLI #242 `1f36e1ed`, #244 `50da81e6`) | none |
| D8 config load | CX-2 | done: `CT:sentry/io_policy/test_config_load_choke_point.py` (CLI #246, `f876137f`) | none |
| D9 CLI stdout | CX-12, CX-3 | partly: `CT:sentry/cli_text/test_stdout_writes.py` (CLI #243) covers writes of a `json.dumps` result only; 13 `sys.stdout.write` / `typer.echo` lines in `C:cli/` are not inventoried | G-C1 |
| D10 literal exit codes | CX-4 | partly: zero literal sites remain in `C:`; the guard regex in `CT:unit/test_exit_codes.py:65` matches only `typer.Exit(code=N` and `sys.exit(N` | G-C1 |
| D11 file operations | CX-7 | not started: `CT:sentry/test_atomic_writer.py` watches moves and links; 33 `os.unlink`, `shutil.rmtree`, `os.fsync`, `os.open(` lines are not watched | G-C1 |
| G1 draw-site keys | EP-3 | not started: 42 `call_site="path:line"` strings in `E:execution/native/_draw_sites_*.py`; `ET:native/test_draw_site_inventory_coverage.py:115` pins the `.py:\d+` shape and `ET:native/test_c5b_i_metadata_inventory.py:75-81` checks the line | G-E3 |
| G2 DP rows | EP-5 | not started: rows are pasted by hand in release prep; `scripts/release/cut-release.sh` only tags | G-E4 |
| G3 registry version | EP-6 | owned by REG-RELEASE (row 8) | none |

**Builds on the prop batch.** Prop slices E-G2a and E-G2b (engine) and C-G1 (CLI) make the baseline
JSON the only allowlist source, read through `load_allowlist(sentry_id)` in
`tests/sentry/_ratchet.py`, with `SOURCES` derived from `scripts/dev/sentry_registry.toml`. Every
new baseline in G-E1, G-E2 and G-C1 is a JSON file plus one registry row and is read through that
loader; no new sentry holds an inline allowlist constant (the prop sentry
`test_no_sentry_holds_an_inline_allowlist` enforces it). So G-E1 and G-E2 start after E-G2b merges,
and G-C1 after C-G1. G-E3 and G-E4 hold no baseline and do not wait.

**V1 behavior.** Tests and release tooling only; no production output, exit code or message
changes. The Arrow owner exists, so D5 needs no production edit: the sentry baselines today's
inline sites and new code calls `is_text`.

**Sentry rules and covered shapes** (recurring-defect class 5: shapes listed here; deliberate
evasion is V2-LOG).

- D2: one constructor tuple, `_CONSTRUCTORS` in `ET:sentry/defects/test_rng_construction.py`,
  is shared by the existing seed-form rule and the new census rule. It is extended with
  `SystemRandom`, `seed` (as `np.random.seed`) and `Generator` (as `np.random.Generator(`). The
  census counts every call to a name in it outside `E:determinism/` and
  `E:generators/derivation.py`, resolved through
  `tests/sentry/_call_resolution.py` (module aliases, `from numpy.random import default_rng`,
  `import numpy.random as npr`). Baseline key `path::qualified_function::ordinal`, value the
  draw-site id from the catalog when that function is a catalogued draw site, else `"plumbing"`.
  After G-E3 the catalog is keyed by function, so the join is exact; a site whose function is
  catalogued but whose baseline value names another id fails.
- D4: `hmac.new(`, `hmac.HMAC(` and `hmac.digest(` outside `E:determinism/`, including
  `import hmac as h` and `from hmac import new`; baseline of today's sites with a one-line reason
  each.
- D5: `pa.types.is_string`, `is_large_string`, `is_binary`, `is_large_binary` outside
  `E:_arrow_types.py`, including `from pyarrow import types as pat` and `import pyarrow.types`;
  baseline per file with a site count (the shape `test_atomic_writer.py` uses), shrink-only.
- D6 (engine): every `os.environ` or `os.getenv` read (subscript, `.get`, `in`, `from os import
  getenv`) outside `E:internal/env_flags.py`, `E:secret_providers/` and the isolated-worker builder
  (`E:execution/_isolated_common.py`); baseline keyed per read with an ordinal, the CLI sentry's
  shape. Placed in the existing `test_environment_reads.py` as a second test, so one file owns
  environment reads.
- D9: a second inventory in `CT:sentry/cli_text/_stdout_sites.py` of every `sys.stdout.write`,
  `typer.echo`, `click.echo`, `print` without `file=` and `print(..., file=sys.stdout)` under
  `C:cli/` outside `C:ui/output.py`,
  not only the JSON ones; baseline `stdout-writes-all.json`.
- D10: the regex becomes an AST walk in the same test: `typer.Exit(...)` (also as
  `from typer import Exit` and `import typer as t`), `click.exceptions.Exit`, `SystemExit(...)`,
  `sys.exit(...)`, builtin `exit(...)`, `os._exit(...)` and `ctx.exit(...)` with an integer
  literal in the first positional argument or `code=`, in any spacing or line break. Today's count is zero, so no
  baseline.
- D11: `os.unlink`, `os.remove`, `shutil.rmtree`, `os.fsync` and `os.open` join the atomic-writer
  watch list as a second rule in `CT:sentry/test_atomic_writer.py` with its own baseline
  (`file-ops-allow.json`, per file and site count), so a new unwatched file operation is a new key.
- G1: `DrawSite.call_site` becomes `"path::qualified_function"` (and `mirror_call_sites` the same).
  The two line checks become: the module exists, the function exists in it (AST), and the function
  body contains a draw token from the existing `_DRAW_TOKEN`. Line moves no longer edit the catalog.
  Where one function holds two catalogued draws, the entry adds `#<n>` (the nth draw token in the
  body), and the test checks that the nth exists. `ET:native/test_draw_sites_catalogue_pinned.py`
  is re-pinned once as a metadata-only change (`_ENTRY_DIGESTS`, `_CATALOGUE_DIGEST`); the
  output-bearing `_MAP_DIGESTS` and `ET:native/test_draw_site_providers_golden.py` stay
  byte-identical, which proves no draw moved.
- G2: a new `scripts/release/dp_rows.py` owns both computations: the dev/CI row from `uv.lock` alone
  (the logic now in `ET:sentry/test_dp_lock_row.py`: `uv export` plus PEP 508 markers for the
  certified platform, moved here and imported back by the sentry) and a CLI-profile row from a given
  `requirements-certified.txt`, a CLI version and the engine version, both through public
  `compute_lock_fingerprint`. `scripts/release/stamp_release.py` calls it at release prep with
  `--cli-pins PATH --cli-version X` (repeatable, for OQ-4's two rows) and inserts the rows at the top
  of their blocks in `_CERTIFIED_STACKS`, newest first, through the same plan-apply-check
  transaction it uses for the registry. Before computing, it refuses (exit 1, tree unchanged) a
  pins file that `scripts/release/sbom_checks.py::pins` rejects, and one whose package-name set
  differs from the source of the newest CLI-profile row beyond names given in `--allow-delta`.
  `cut-release.sh` stays a tagger that changes no file. An
  unchanged `release_checks.sh` still proves the dev row admits the stamped version.

**Failure modes.**

| Failure | Caught by |
|---|---|
| A new sentry keeps an inline allowlist | prop `test_no_sentry_holds_an_inline_allowlist` |
| A walk misses a listed spelling, so its count is trusted while blind | each sentry's seeded-violation self-test (AT-G1 to AT-G7) |
| A baseline grows | `scripts/dev/ratchet_check.py` against the merge base (existing) |
| G1 makes two sites map to one function silently | AT-G8 (`#n` resolution) |
| G2 writes a row computed for the wrong engine version | AT-G9 compares against the version `stamp_release.py` stamps in the same transaction; `release_checks.sh` admits the dev row |
| G2 drops an older row | AT-G9 (row set is a superset of HEAD's) |

## 6. Acceptance tests (red first)

Each test is written first and must fail on the base named in the header, unless it is marked
"no-regression", which pins a fact that holds before and after and is never counted as red
evidence. The builder records each fail-before result in the PR body.

| Id | Slice | Test | Fails before because |
|---|---|---|---|
| AT-Z1 | Z-E1 | `ET:unit/validation/test_structural_scans.py`: a deterministic `faker` column, `pool_size: 10`, 200 distinct sources, post-validation on: `quality_warnings` holds `cardinality_collisions` with `distinct_lost == source_distinct - output_distinct > 0` and `pool_size == 10` | no such warning |
| AT-Z2 | Z-E1 | Same run with a marker source value: the marker is absent from the JSON of `quality_summary`, from `str()` of each warning and from the captured run log | no warning to check; written red with AT-Z1 |
| AT-Z3 | Z-E1 | A `when:`-gated deterministic `faker` column: no `cardinality_collisions` entry; its `DistinctCount` is still recorded | the `DistinctCount` half is no-regression; the absence is pinned after Z-E1 (MZ2 turns it red) |
| AT-Z4 | Z-E1 | Quarantine on, one row removed by another column's `format_error`: `source_distinct` counts the aligned rows only | no warning |
| AT-Z5 | Z-E1 | An integer column: `source_distinct` equals the count over `_canonicalize_source` forms, compared with a direct call of the sampler's canonicalizer | no warning |
| AT-Z6 | Z-E1 | `run_pipeline` with `execution_mode="full_frame"` and with `"out_of_core"` on the AT-Z1 config: equal warning detail | no warning on either route |
| AT-Z6b | Z-E1 | A deterministic `faker` column with `cardinality_mode: scale_source_cardinality` and a small pool: the warning is emitted; a `match_source_cardinality` column gets `CARDINALITY_MATCH_DEVIATION` and no `cardinality_collisions` | rule absent |
| AT-Z7 | Z-E1 | `ET:sentry/defects/test_strategy_docs_agree.py` case: the "Intentional collisions", `faker` and `hash` sections and `docs/security/token-vault.md` hold no "collision-free", no "one-to-one" for `hash` or `tokenize`, and no "distinct source values map to distinct" claim | `docs/strategies.md:1114` and `:1134`; `token-vault.md:105` |
| AT-Z8 | Z-C1 | `CT:e2e/test_run_flags.py`: `decoy run --post-validate` on a small deterministic `faker` config prints the collision line with `table.column` and counts and no source value; `--json` holds the code under `report.quality_summary.quality_warnings`; exit 0 | no line (engine pin lacks the code) |
| AT-A1 | A-E1 | `test_strategy_docs_agree.py`: the user-facing strategy set is loaded from `scripts/gen_capability_matrix.py::_mask_strategies` the way `ET:sentry/test_capability_matrix.py::_load_generator` loads it; every name in it has a `### <name>` heading under "## Mask strategies" (read with `tests/sentry/layout/_layout.py::section`); a `###` heading equal to a registry handler name that is not user-facing fails; any other `###` heading is prose (for example "Intentional collisions") and is ignored, so there is no hand list; the intro holds no number word | five sections missing; "seventeen" |
| AT-A2 | A-E1 | Same file: for each user-facing strategy whose `capabilities_for(s).row_error_modes` (`E:execution/native/_capabilities.py`) holds `format_error`, its section names `format_error` and says no "pass through" or "left as-is" for unparseable cells | `bucketize` (`:276`), `date_shift` (`:149`) unless 24zb E1 merged first |
| AT-A3 | A-E1 | Same file: no `job_seed` token at all inside the section of a strategy in `ALWAYS_KEYED_STRATEGIES`, nor inside `docs/determinism.md`'s keyed subsections ("Keyed masking: mask_key, not job_seed", "FPE key and tweak model", "Deterministic shuffle and column names"), except allowlisted sentences (exact text plus a reason each, in the sentry's baseline) | `strategies.md:167`, `:193`, `:196`, `:437`, `:619`, `:625`, `:695`, `:700`; `determinism.md:67`, `:125`, `:217` |
| AT-C1 to AT-C6 | C-E1, C-C1 | The earlier plan's AT-1 to AT-6 with 67 pins, base fingerprint `789b1eae...` and the pre-repin fixture taken from CLI main at the C-C1 base | as in that plan |
| AT-C7 | C-C1 | `CT:unit/test_sbom_script.py`: the operative header sentence ("together with decoy-engine X") and the `uv pip install decoy-engine==X` line name the `pyproject.toml` pin; history mentions of older versions are not pinned. `scripts/cert_smoke.py`'s docstring no longer carries a fingerprint and points to the header instead | lines 5 and 25 say 0.26.0; the docstring says `dceac0cd...` |
| AT-G1 | G-E1 | D2 sentry: real tree equals the baseline; a scratch copy with `np.random.default_rng(1)` added to a non-catalogued function fails; a catalogued site whose baseline names another id fails | no census test |
| AT-G2 | G-E1 | D4 sentry: real tree equals the baseline; `import hmac as h; h.new(...)` in a scratch module fails | no sentry |
| AT-G3 | G-E2 | D5 sentry: real tree equals the baseline; one added `pa.types.is_large_string` in a baselined file fails (count grows) | no sentry |
| AT-G4 | G-E2 | D6 engine: real tree equals the baseline; `from os import getenv as g; g("X")` in a scratch module fails | the flag test passes a non-flag read |
| AT-G5 | G-C1 | D9: a scratch `typer.echo("x")` and `print("x", file=sys.stdout)` in `C:cli/` each fail; the same lines in `C:ui/output.py` pass | only JSON writes are scanned |
| AT-G6 | G-C1 | D10: scratch `raise typer.Exit(2)`, `raise SystemExit(3)`, `ctx.exit(1)`, `from typer import Exit; raise Exit(2)`, `import typer as t; raise t.Exit(2)`, builtin `exit(1)` and `os._exit(1)` each fail | the regex misses all of them |
| AT-G7 | G-C1 | D11: a scratch `os.unlink(p)` in a file with no baseline entry fails | not watched |
| AT-G8 | G-E3 | `ET:native/test_draw_site_inventory_coverage.py`, `ET:native/test_c5b_i_metadata_inventory.py` and `ET:native/test_draw_sites_catalogue_pinned.py`: in a scratch copy, insert a blank line above every catalogued draw: all three pass; rename one catalogued function: they fail. `_MAP_DIGESTS` and `ET:native/test_draw_site_providers_golden.py` are byte-identical before and after G-E3 | the line pin and the entry digests fail on the blank line |
| AT-G9 | G-E4 | `ET:unit/scripts/test_dp_rows.py`: on a temp clone, `stamp_release.py --version X --cli-pins A --cli-pins B --cli-version Y` writes the dev row equal to what `test_dp_lock_row.py` computes and two CLI rows equal to `compute_lock_fingerprint` over A and B plus the engine and CLI versions; every row in HEAD's `_CERTIFIED_STACKS` is still present; a second run adds nothing. Refusal cells: a pins file that `sbom_checks.pins()` rejects, and one whose package-name set differs from the newest CLI-profile source beyond the declared `--allow-delta` names, each exit 1 and leave the tree unchanged | no script |

**Named mutations** (each must turn a test red on the slice head): MZ1 compute `distinct_lost` on
the unaligned source (AT-Z4); MZ2 drop the `when` skip (AT-Z3); MZ3 put `out_non_null[:3]` into the
detail (AT-Z2); MA1 delete the `tokenize` section (AT-A1); MA2 restore "Non-numeric and null values
pass through" (AT-A2); MA3 restore the `code_set` "same job_seed" sentence at `:695` (AT-A3); the earlier 24zc plan's M1 to M5, plus MC6 leave line 5 at 0.26.0 (AT-C7);
MG1 to MG7 the scratch violations above; MG8 revert one entry to `path:line` (AT-G8 shape check);
MG9 have the script skip the second `--cli-pins` (AT-G9); MG10 drop the name-set check (AT-G9
refusal cell); MZ4 key the rule on `reuse` only (AT-Z6b).

## 7. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | 24z: the warning is built from source and output values | the warning detail is a fixed key set of names and integers built in one place in `_cardinality.py`; no value is formatted | AT-Z2 | MZ3 |
| 2 | Cleanup missing on an exit path | N/A: no slice creates a file, lock or scratch; G2 writes through `stamp_release.py`'s existing candidate-copy transaction | existing transaction | AT-G9 (second run adds nothing) | n/a |
| 3 | State machine and concurrency | N/A: no state or thread added; the scan runs once at finalize | n/a | n/a | n/a |
| 4 | Route parity and silent fallback | 24z: the count must be the same on every route | computed at finalize from resident outputs, which post-validation forces on every route (`_chunked_output_sink.py:120`) | AT-Z6 | compute inside the faker handler instead (the out-of-core route does not call it): AT-Z6 red |
| 5 | Referential integrity | N/A: no key, FK or join behavior changes; 24z reads outputs only | n/a | n/a | n/a |
| 6 | Untrusted producer | 24zc: package index content | exact pins; the engine gate checks the installed set by fingerprint | AT-C5 | earlier plan M2 |
| 7 | Check then use (TOCTOU) | N/A: no path is checked then used; 24zc's fingerprint is computed from the installed set at fit time | unchanged engine gate | AT-C5 | n/a |
| 8 | Weak tests and overclaimed evidence | every new sentry could count while blind | each walk is shown red on a seeded violation before its baseline is trusted; no-regression pins are labeled | AT-G1 to AT-G8 | replace a walk with a hand list: its seeded case passes and the self-test goes red |
| 9 | Refactor drift | G1 rewrites 42 catalog entries; G2 moves the lock-row logic out of the sentry | the moved function is imported back by `test_dp_lock_row.py`, which must stay green; G1 changes keys only, and the draw-site inventory tests cross-check every entry against the code | AT-G8, AT-G9, existing `test_dp_lock_row.py` | map a catalogued site to the wrong function: AT-G8 red |
| 10 | Frozen contract drift | the reason registry (new warning code), the `quality_summary` shape, the DP certified-row set | the code is added with `since=UNRELEASED` and stamped at release (REG-RELEASE); `DistinctCount` keys unchanged; rows are only added | `test_reason_registry.py`, AT-Z1, AT-G9, AT-C4 | drop an old CLI row: AT-C4 red |

## 8. Enumerations (from the code at the bases)

### Routes

- Post-validation on full-frame and sequential runs: `E:execution/_pipeline_finalize.py:349-351`.
- Post-validation forces the resident path on streamed and chunked runs:
  `E:execution/_chunked_output_sink.py:120`; the mixed static route declines with
  `post_validation_requested` (`E:execution/_mixed_static.py:217`).
- Deterministic `faker` selection: Python `E:generation/pool/_sampler.py:307`, sequential native
  and native chunk masking through the same `derive_index`. 24z reads none of them; it reads their
  outputs.
- DP certification: CLI certified-profile CI job, fit gate and snapshot gate in
  `E:quality/dp_provenance.py:347` and `:382`.

### Exit paths

- 24z: none changes. `--post-validate-enforce` still maps only `failed_checks` to exit 4
  (`C:ui/summary.py:308`); a collision warning is not a failed check.
- 24zc: `scripts/cert_smoke.py` exits non-zero on a fingerprint or row mismatch; a fit on an
  uncertified set raises `dp_stack_uncertified`.
- 24ze: sentries fail the test run only; `stamp_release.py` exits 1 on a refused plan (its
  documented codes), now including a CLI pin file that does not parse.

### FK shapes

N/A: no slice reads or writes keys or foreign keys; 24z counts distinct values of one column.

### Fields

- New warning code `cardinality_collisions` (`reasons.warning`, beside
  `E:reasons/warning/_part1.py:40`), detail keys `table`, `source_distinct`, `output_distinct`,
  `distinct_lost`, `pool_size`.
- New `stamp_release.py` options `--cli-pins` (repeatable), `--cli-version` and `--allow-delta`.
- No config key is added or read anew.

### Output surfaces

- `quality_metrics["quality_summary"]["quality_warnings"]` (engine) and the CLI `--json`
  `report.quality_summary` (`C:cli/run/_render.py:128`).
- CLI human post-validation block (`C:ui/summary.py:308`).
- `docs/strategies.md`, `docs/determinism.md`, `docs/qa/06-mask-core-strategies.md`.
- The CLI SBOM produced from `requirements-certified.txt` at release.
- `E:quality/dp_provenance.py:273` `_CERTIFIED_STACKS` (written by G2).

## 9. Reuse inventory

- 24z reuses the post-validation cardinality scan, its `ScanContext` (aligned sources),
  `QualityWarning`, the sampler's `_canonicalize_source`, and the warning reason registry. No new
  module, no new pass over the data on runs without `--post-validate`. The unwired
  `E:execution/native/_pool_quality.py` measurement spools cleartext pairs to DuckDB and serves a
  different gate; it is not reused.
- 24za reuses `scripts/gen_capability_matrix.py::_mask_strategies` (loaded as
  `ET:sentry/test_capability_matrix.py::_load_generator` does), `capabilities_for(...).row_error_modes`,
  `ALWAYS_KEYED_STRATEGIES` and `tests/sentry/layout/_layout.py::section`. No new section helper.
- 24zc reuses everything the earlier plan names: `scripts/release/sbom_checks.py::pins` and
  `canonical_name`, public `compute_lock_fingerprint`, `Provenance`, `validate_recorded_provenance`,
  `cert_smoke.py`, the certified-profile CI job, `scripts/dev/lock.sh`.
- 24ze reuses `tests/sentry/_call_resolution.py`, `tests/sentry/defects/_defect_scan.py`, the CLI
  `_stdout_sites.py` and `_calls` helpers, the prop batch's `load_allowlist`, the ratchet,
  `E:_arrow_types.py`, `stamp_release.py`'s transaction, and the lock-row logic of
  `test_dp_lock_row.py` (moved, not copied).

## 10. Established solutions

Search run: in-codebase (`git grep` over both repos for collision, cardinality, pool quality,
`hmac.new`, `default_rng`, `call_site`, `_CERTIFIED_STACKS`; the duplication census; the three
named plans) and the standard references below, recalled and cited rather than fetched (no
network step was needed for a fix-only plan; the reviewer may ask for a fetch).

- Collisions in a keyed map into a finite set: the birthday bound (Knuth, TAOCP vol. 3, 6.4) gives
  the expected shared slots, about n^2 / 2m for n inputs and m slots. The standard answers to "I
  need one-to-one" are format-preserving encryption (NIST SP 800-38G FF1, already the `fpe`
  strategy, a permutation of its format domain) and a wide keyed digest, collision-resistant by
  the same birthday bound at 2^64 or more (the untruncated `hash` and the 128-bit `tokenize`).
  Both exist, so 24z follows the established route: say the pick is many-to-one and point to
  those strategies with the correct strength word for each. Counting collisions as `distinct(source) - distinct(output)` is the plain
  definition; no library is needed beyond the existing distinct counts.
- Docs that drift from a registry: generated docs or a docs-agree test (the docs-as-tests pattern
  the repo already uses in `ET:unit/config/test_generate_options_doc.py`). 24za follows that
  precedent; it does not generate the narrative page because each section is prose.
- Duplicate-code guards: architectural fitness functions with ratchet baselines (Ford, Parsons,
  Kua, "Building Evolutionary Architectures"; the repo's `_ratchet.py`). `jscpd` is the standard
  copy detector and is the deferred D1.
- Stable code locations: symbol-qualified references (`module::function`, the pytest node-id
  form) instead of line numbers. G1 follows it.
- Release-time generated facts: the release script computes and writes them from the lock (the
  pattern `stamp_release.py` already uses for the reason registry). G2 follows it.

Custom code left: one rule in `_cardinality.py`, one docs sentry, seven scanner rules on existing
helpers, one release helper module. Each is smaller than any outside tool that would do the same.

## 11. Design notes

- No new module in production code. G2 adds one release-tooling module beside
  `stamp_release.py`; it holds one fact (how a certified row is computed), moved out of a test so
  the test and the release prep share one place.
- One place per fact: the strategy list is in the registry; the docs page points to the
  generated matrix for counts. The collision warning detail is built in one function.
- No flag arguments: the collision rule keys off the seed fields the plan already carries
  (`strategy`, `deterministic`, `cardinality_mode`, `when`).

## 12. Frozen contracts

- Reason registry: one new warning code, append-only, `since=UNRELEASED`, stamped at release
  (REG-RELEASE rule). `ET:sentry/test_reason_registry.py` and the f29 fixtures move in Z-E1.
- `quality_summary` shape: unchanged keys; a new code in an existing list.
- DP certified rows: rows added, never removed (the 0.18.0 rule).
- Public engine API: unchanged. `stamp_release.py` options are release tooling, not a public surface.
- CLI `--json` envelope: unchanged shape. If the engine release adds a report shape,
  `CT:fixtures/release_freeze/json-shapes.json` moves in the repin slice as #290 did.

## 13. Pre-mortem

| Risk | Guard |
|---|---|
| The count is read as "rows that share a value" while it counts distinct values lost | the doc and the CLI line say "M distinct source values became K distinct masked values (N merged)"; detail key `distinct_lost` |
| A large column makes the scan's source set expensive | the scan already builds an output set per column; the source set is the same order and runs only under `--post-validate` |
| 24za and 24zb collide on `docs/strategies.md` | ordering rule in section 3; A-E1 starts from the latest main and drops what 24zb owns |
| G1 conflicts with open generation PRs that add draw sites (engine #523, #546, #555, #557, #561, #596) | G1 lands after 24zb E1; each open PR rebases and writes its new entry in the function form, which AT-G8's shape check enforces |
| Release N ships without row F | C-C1 cannot merge (certified-profile job red); C-E1 is a release-prep checklist item and OQ-4 makes the order free |
| cryptography 50 changes something the CLI uses | the earlier plan's Ed25519 cell on exactly 50.0.0 (AT-C6) |
| A new sentry baselines a real defect and hides it | each baseline entry carries a reason; reviewers read the baseline diff; the census already triaged these sites |

## 14. Placement

Checked against engine and CLI CODEMAP "Where Things Go".

| New or moved thing | Path | CODEMAP row | Beside |
|---|---|---|---|
| Collision rule | `E:validation/post/_checks/_cardinality.py` (about 60 lines added) | post-validation scans | `run_cardinality` |
| Warning code | `E:reasons/warning/_part1.py` (101 lines) | reason registry | `CARDINALITY_MATCH_DEVIATION` |
| Collision tests | `ET:unit/validation/test_structural_scans.py` | unit tests for the owning surface | existing cardinality tests |
| Docs agreement sentry | `ET:sentry/defects/test_strategy_docs_agree.py` | recurring-defect class rules | `test_canonical_json_choke_point.py` |
| CLI collision line | `C:ui/summary.py` `render_post_validation` | UI rendering | the failed-check table |
| CLI e2e | `CT:e2e/test_run_flags.py` | e2e for run flags | existing `--post-validate` cases |
| 24zc tests and fixture | as in the earlier plan: `CT:unit/test_sbom_script.py`, `CT:fixtures/sbom_runtime/requirements-certified-pre-24zc.txt` | release scripts | `_RELEASE_PINS` |
| D2 census | `ET:sentry/defects/test_rng_construction.py` (second rule), `ET:sentry/baselines/rng-construction.json` | sentry, defects | the seed-form rule |
| D4 | `ET:sentry/defects/test_hmac_sites.py`, `ET:sentry/baselines/hmac-sites.json` | sentry, defects | `test_canonical_json_choke_point.py` |
| D5 | `ET:sentry/defects/test_arrow_text_predicates.py`, `ET:sentry/baselines/arrow-text-predicates.json` | sentry, defects | same |
| D6 engine | `ET:sentry/defects/test_environment_reads.py` (second test), `ET:sentry/baselines/env-reads.json` | sentry, defects | the flag rule |
| D9 | `CT:sentry/cli_text/_stdout_sites.py`, `test_stdout_writes.py`, `CT:sentry/baselines/stdout-writes-all.json` | sentry, cli_text | the JSON inventory |
| D10 | `CT:unit/test_exit_codes.py` (regex to AST walk) | existing guard | in place |
| D11 | `CT:sentry/test_atomic_writer.py` (second rule), `CT:sentry/baselines/file-ops-allow.json` | sentry | the move rule |
| G1 | `E:execution/native/_draw_sites_gen.py`, `_draw_sites_gen_pool.py`, `_draw_sites_mask.py`, `_draw_sites_provider_backed.py`, `_draw_sites_tokenize.py`; `ET:native/test_draw_site_inventory_coverage.py`, `ET:native/test_c5b_i_metadata_inventory.py`, `ET:native/test_draw_sites_catalogue_pinned.py` (metadata re-pin) | native determinism protocol | in place |
| G2 | `scripts/release/dp_rows.py` (new, about 200 lines), `scripts/release/stamp_release.py`, `ET:unit/scripts/test_dp_rows.py`, `ET:sentry/test_dp_lock_row.py` (imports the moved logic) | dev tooling, `scripts/release/` | `stamp_release.py`, `reason_release_pin.py` |

Each new sentry registers one row in `scripts/dev/sentry_registry.toml`, so the prop
`test_no_sentry_holds_an_inline_allowlist` walks it and the manifest glob (prop E1) finds it. Every new element has a consumer in its own slice.

## 15. Slices

Production files exclude tests, baselines, docs and CI YAML; scripts under `scripts/release/`
count as production. Every slice is at or under 10 production files and 800 changed lines.

| Slice | Row | Repo | Scope | Prod files | Lines (est.) | Risk | Depends on |
|---|---|---|---|---|---|---|---|
| Z-E1 | 24z | engine | collision rule, warning code, `_events.py` docstring, `_tables.py` comment, docs (`faker`, `hash`, "Intentional collisions", `security/token-vault.md`), QA 06, changelog fragment, AT-Z1 to AT-Z7 | 4 | ~350 | R2 (report built from source values; frozen registry) | none |
| A-E1 | 24za | engine | strategies.md count, five sections, `format_error` text, `job_seed` text in both pages, AT-A1 to AT-A3 | 0 | ~450 docs, ~150 test | R1 | 24zb E1 merged, or the 2026-11-25 fallback in section 3 |
| C-E1 | 24zc | engine | in release N prep: two CLI-profile rows for N; the prior-release rows test | 1 | ~30 | R1 | release N prep; uses G-E4 if merged |
| G-E1 | 24ze | engine | D2 census, D4 | 0 | ~400 | R1 | prop E-G2b; G-E3 for the exact id join (else values are filled by function name and G-E3 rewrites them) |
| G-E2 | 24ze | engine | D5, D6 engine | 0 | ~350 | R1 | prop E-G2b |
| G-E3 | 24ze | engine | G1, catalogue metadata re-pin | 5 | ~350 | R1 | 24zb E1 merged (being built now) |
| G-E4 | 24ze | engine | G2 | 2 | ~450 | R2 (writes the certified-stack set, a supply-chain trust input, at release) | none |
| C-C1 | 24zc | CLI | repin to N, the four pins, header, AT-C1 to AT-C7 | 3 (`pyproject.toml`, `requirements-certified.txt`, `scripts/cert_smoke.py`) plus the #290 list | ~250 | R2 (dependency and crypto pins; full suite on triggers: dependency lock, version pin) | release N tagged |
| Z-C1 | 24z | CLI | collision line in `render_post_validation`, AT-Z8, CLI QA checklist id, roadmap row 24z | 1 | ~120 | R1 | C-C1 merged (or any repin to an engine with Z-E1) |
| G-C1 | 24ze | CLI | D9, D10, D11 | 0 | ~450 | R1 | prop C-G1 |

Review per risk: R1 is Codex only; R2 is Dennis then Codex.

**Release and repin points.** Release N is the first daily engine release after Z-E1 merges. Its
notes list the warning code and row F. C-E1 is part of N's release prep. The CLI repins once, in
C-C1, to N.

**Ordering.**

1. Start now, in parallel worktrees: Z-E1 and G-E4. They touch different files.
2. When 24zb E1 merges: A-E1 and G-E3 start. If 24zb E1 is not merged by 2026-11-25, A-E1 takes
   the two 24zb sentences (section 3) and starts anyway; G-E3 still waits, since E1 repoints a
   draw site.
3. Release N: C-E1 adds both CLI-profile rows in its prep. If G-E4 merged first,
   `stamp_release.py` computes them.
4. C-C1 repins the CLI to N with the four pins. If a prop-batch repin to N lands first, C-C1 moves
   only the four pins and the header (row F is already in N). Then Z-C1.
5. After prop E-G2b merges: G-E1 and G-E2. After prop C-G1: G-C1. They do not block any release.
6. Roadmap: 24zc closes with C-C1; 24z with Z-C1; 24za with A-E1; 24ze with the last of G-E1 to
   G-E4 and G-C1 (D1 moved to V1+ if OQ-5 is accepted).

All of it fits before 2026-12-15. The critical path is Z-E1, release N, C-C1, Z-C1.

**Test depth (owner rule).** T0 per edit; T1 impact selection per commit; the gate runs T1 on the
exact head. Full suite only on an escalation trigger: C-C1 (dependency lock and version pin),
G-E1, G-E2 and G-C1 (shared test machinery), G-E4 (it moves logic out of a sentry other tests
import). All runs on the Mac first or a VM through `~/bin/vm-run`, never the devbox. Mutations
only on Z-E1's rule and the 24zc delta guard.

## 16. Owner questions (each with a recommended answer)

- **OQ-1 (24z).** Make deterministic `faker` collision-free, or correct the promise and report the
  count? Recommended: correct and report. A source set with no bound cannot map one-to-one into a
  finite pool without a stored table. Users who need one output per input use `fpe` (one-to-one
  within its format domain) or an untruncated `hash` or `tokenize` (collision-resistant, not
  collision-free).
- **OQ-2 (24z).** Report always, or only under `--post-validate`? Recommended: only under
  `--post-validate`. The scan already exists there, every route already supports it, and the
  default run pays nothing. The docs tell users to run it on key-like columns.
- **OQ-3 (24za).** Fix the same `job_seed` wording in the `bucket_perturb`, `text_mask`,
  `joint_mask` and `code_set` sections and the FPE and shuffle paragraphs, not only the
  `determinism.md` fallback paragraph the row names? Recommended: yes. It is the same false
  statement, docs only, and AT-A3 holds the class.
- **OQ-4 (24zc).** Release N carries two CLI-profile rows (today's pins and the four new pins), so
  the CLI can repin to N with or without the pin change in either order? Recommended: yes. It costs
  one extra row and removes an ordering dependency with the prop-batch repin.
- **OQ-5 (24ze).** Move D1 (`jscpd` in `gates.sh`) to V1+? Recommended: yes. It adds a Node tool to
  both gates and a whole-tree baseline, and the census already lists the duplicates by hand; the
  row text allows it.
- **OQ-6 (F-1).** Add a V1 row to make `bucket_perturb` record `format_error` on an unparseable
  date, as `date_shift` does, instead of keeping the source value? Recommended: yes. It is a fix to
  an existing feature, and a kept source value in a masking strategy's output meets the V1 leak
  bar.

Engineering calls made (not questions): G2 writes rows in `stamp_release.py` at release prep, not
in `cut-release.sh`, because the tagger must not change files; D6 engine and D2 extend their
existing sentry files so one file owns each concern; D10 becomes an AST walk because a regex cannot
see `code=` across lines.

## 17. Not verified

- No test was run (devbox rule). Each fail-before claim comes from reading the code at the bases.
  The builder confirms each on the branch before changing source.
- That `ScanContext.sources` is the row-aligned source for every route (read in
  `_pipeline_finalize.py`, not run).
- That the post-validation `ScanContext` can reach the run's provider registry, which
  `resolve_faker_pool_identity` needs. If it cannot, Z-E1 passes the resolved pool size through
  the plan seed's existing `pool_size` at compile, not a restated default; the builder confirms
  first.
- That no current advisory exists for a fifth certified pin. The four come from the 2026-11-11
  scan; the row limits the change to them. A new advisory is a new row.
- The counts behind each new baseline (12 engine environment-read lines, 11 `hmac.new` lines
  including `determinism/`, 26 files with inline Arrow text predicates, 33 CLI file-operation
  lines, 13 CLI stdout lines) are `git grep` counts, not walk results.
- Whether `ET:native/test_c5b_i_metadata_inventory.py` is the only other reader of the
  `path:line` shape.

## 18. Follow-ups outside this plan

- V2-LOG: `docs/native/draw-site-inventory.md` still cites draw sites by line; after G-E3 its
  references can move to the function form.
- V2-LOG, web lane: `decoy-web-docs` `concepts/keys-and-vault.mdx:90` repeats the collision-free
  claim; flag it to the web owner.

- New V1 row for finding F-1 if OQ-6 is accepted.
- The CLI `plan/certified-pin-cves` branch is superseded by section 4 for base numbers; its design
  stays the reference. No merge of that branch is needed.
- Roadmap row 24ze: record D3, D6 (CLI), D7 and D8 as done with the commits in section 5.
