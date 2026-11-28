# RATCHET-GROWTH moved keys and RATCHET-BURNDOWN: follow pure moves, then shrink the debt lists

Status: plan. OQ1 to OQ6 decided 2026-11-28.

Rows: RATCHET-GROWTH (the moved-keys widening, owner 2026-11-27) and RATCHET-BURNDOWN (new 1.0
health row, owner 2026-11-27). Both row texts come from CLI PR #427 (`docs/ratchet-rehome-and-burndown`),
which is open and not merged on 2026-11-28. Build waits on that merge (OQ1, decided: merge as is).

Repos: engine (decoy-data/decoy-engine) and CLI (decoy-data/decoy). Release: the engine half ships
in the next engine release after main 8414da35c; the CLI half ships with the CLI repin that follows
it. No product behavior changes except BD-E1 (file mode of one temporary spool) and BD-E4 (three
additive public accessors).

Rules consulted: /home/cam/dev-rules/00-universal.md, development-loop.md (PLAN),
risk-and-exceptions.md, testing.md (Test depth; escalation trigger "test tooling"),
refactoring.md, proportionality.md, reuse-first.md, cross-cutting-concerns.md,
catalogs/recurring-defects.md; engine CODEMAP "Where things go"; PLAYBOOK-decoy.md R2 plan
done-state; owner rule "Ratchet 1:1 re-home" (OWNER-OPEN-DECISIONS.md:55, 2026-11-15); owner
ratchet rule 2026-11-25 (lists grow only with sign-off).

Base: engine origin/main 8414da35c (#828, 2026-11-28); CLI origin/main 2ca3bbd4.

## 1. Frame

The sentry ratchet (`tests/sentry/_ratchet.py`) fails a slice whose baseline gains a key that was
not in the merge base. A code move renames keys without adding any site. Today only two sentries
(`secret-material-census`, `gcs-call-kwargs`) can follow a move, and only when the builder writes a
`moved_from` field (`tests/sentry/_ratchet.py:45`, `tests/sentry/_ratchet.py:534`). Every other
move needs a hand-written `approved_growth` row with an owner decision string. A11 distinguishes historical moves from approved new callers.

BD follows F31-AUDIT: identify a shared helper per guard, migrate the allowed sites and lower the baseline.

Open engine PRs #790, #778, #705, #685, #818, #808 and #670 edit baselines that MK infers on. Their
existing `moved_from` entries must stay valid: MK keeps the declared path for the two rehome
sentries unchanged except the stated relaxation (6.4), and A14 replays a declared entry of the
present form. Each of those PRs that merges before MK-E1 is in the A11 replay set.

Risk: R2 for merge-gate tooling and private-file handling. Section 8 gives each slice’s risk.

## 2. Guarantee and non-goals

Pinned guarantee (MK, OQ6b): inference requires a unique lost/grown pair in the same sentry,
one retained location component, unchanged bound, compatible entries, old-site absence and equal
normalized defs. File-only identities require a reported rename. An explicit engine `moved_from`
can pair changed defs across locations when the old qualified def is gone. The reviewer sees each
admission in gate stderr. Section 6.2 defines the bounds. The existing declared binding proof for
`secret-material-census` and `gcs-call-kwargs` and the CLI map contract (5.6) are carve-outs.

Pinned guarantee (BD): each debt guard named in the ledger (section 13) ends at or below its target
count, and each removed entry is routed through the guard's named owner helper. No baseline gains a
key and no allow-list gains an entry in any slice of this plan.

Non-goals:
- No change to growth rules: real growth still needs a dated owner row.
- No inferred split (one key into many) or merge (many into one). CLI `split_from` stays as is.
- No inferred move where both file and qualname change; that needs a declared `moved_from` plus
  the declared proof in 6.1.
- Preserve declared binding rehomes for `secret-material-census` and `gcs-call-kwargs`; strict def equality would break existing declarations.
- No inferred moves for `GUARD_KEYS` (`sentry-limits`) or `REKEY_PER_SITE`
  (`validation-name-messages`) (GUARD_KEYS at `_ratchet.py:52`, REKEY_PER_SITE at `:40`).
- Not the outbound-text burndown: engine-exception-text-copies, config-refusal-text, CLI
  one-error-emitter, engine-reason-code-copies stay with F31-AUDIT (AE5b, AC1, AC3).
- Not module-size (engine: STRUCTURE-REVIEW, "Not now"; CLI: CLI-SPLIT S2) (OQ3, decided: defer to 1.x).
- Not census burndown (f29-producer, f29-reason, f29-consumer, secret-material-census,
  serial-resources, gcs-call-kwargs, import-layers, platform-census, exception-context,
  win32-import-surface). They record inventory. Section 6.3 specifies which inventory keys can move.
- Not CLI lint-debt (its own tool and row).
- Not RG-E3, RG-C1a, RG-C1b (planned in
  `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`). Each MK slice waits for its repo dependencies in section 8.

## 3. Acceptance tests (red before their slice unless marked control)

MK-E1 (`tests/sentry/ratchet/test_moved_keys.py`, seeded git repos in `tmp_path`):
- A1 file move of one def-keyed entry, same qualname, same bound name, same `max`, def body
  unchanged, old file gone: passes with no `approved_growth`; one report line.
- A2 same move with `max` raised by 1: finding.
- A3 two lost keys and one grown key of the same identity: finding naming the tie (no tie-break).
- A4 old site still present (copy): finding.
- A5 bound name differs: finding.
- A6 move accepted and a second unrelated new key appears: the new key is a finding.
- A7 a `sentry-limits` key moves: finding (guard keys excluded).
- A8 a `validation-name-messages` move follows its existing re-key path, unchanged (control).
- A9 qualname rename in the same file (`_derive_pool_indices` to `derive_pool_indices`): passes.
- A10 `min` lowered on a move: finding. `category` changed: finding.
- A11 replay the parent and commit sources below in seeded repos, using the actual sentry key and
  entry pair. Use test fixtures only and remove approval for the tested key. For (b), add the declaration on that pair
  separately from the inference run. For the classifier move in #792 project the census onto the
  source pair: that commit changed code before the exception-text baseline recorded the move.

| Case | Commit | Expected verdict without approval (strict / recommended) | Reason |
|---|---|---|---|
| #775 f29 consumer, `derive_pool_indices` | `7db7ba243` | inferred / inferred | Same file and `exc.code`, only the def name changed. |
| PCR S0, `adapter_fk_safe_columns` | `12c7bd2a8` | growth / growth | File and qualname changed. The old `_oracle_masked._masked` def still exists after extraction. |
| `is_memory_failure` | `fd27afe3d` | growth / declared move | The helper calls and body changed. The old module now imports the function. Its local def is gone and the `str(exc)::assign` bound stays. |
| AE5, both `_yaml_mark` entries | `f43ece79e` | growth / growth | File and qualname changed and both `extra` bounds change from `assign` to `return`. |
| Vault parquet writer, `_encode_rows` | `152de2207` | growth / growth | The count and category stay, but the old `VaultWriter.serialize` def survives. |
| Arrow profiler, `observed_shape` | `34e52ddee` | growth / growth | File-level bound. Git reports modified old file and added destination, with no rename. |
| COLUMN-SHAPE-RULE E5, `classify_column` | `8414da35c` | growth / growth | Owner approved a new scan caller. No old key pays for it. |
| F33 signing-input entries | `ad36687a6` | growth / growth | New census sites. |
| Public Arrow facade | `7822182c5` | growth / growth | New file. |
| F26 publication stage entries | `bbb5c8337` | growth / growth | New stage modules. |
| Policy-to-I/O edges | `713c047db` | growth / growth | Import-layer edges have no site identity. |

- A12 the section 6.3 table equals the registry: every id is in `IDENTITY` or `NO_INFERENCE` with a
  reason, or is a guard; a new registry id with no row fails. Runtime unknown id = NO_INFERENCE.
- A13 malformed key (missing `::` on a delimited row, non-identifier qualname, lambda, unknown prefix): no inference, no
  exception.
- A14 declared `moved_from` of the present form on `secret-material-census` passes (control); on a
  non-rehome sentry (lossless-int) it passes with the declared proof; on `sentry-limits` it fails.
- A15 unrelated swap: site X deleted in file a, unrelated site Y with the same bound name added in
  file b, same qualname, different def body: finding (content proof fails).
- A16 bare-file key: delete file A, add unrelated file B under A's ceiling: finding (git reports no
  rename). A real `git mv` of A to B with the same ceiling: passes.
- A17 run the real `scripts/dev/gates.sh` sentry step in each repo on a seeded committed pair
  whose base checker supports moves. Capture the outer process stderr on success. Require
  `ratchet: <sid>: moved <old> -> <new>` with the inferred or declared proof. Remove the move
  filter and this test fails. Exercise both report forms and retain the failing-step exit status.
- A18 declared rehome of an entry with `max` (lifts `_rehome.py:109`): equal `max` passes, lower
  `max` passes, higher `max` fails.
- A19 `test_infer_moves_is_pure`: `infer_moves` called twice on deep-copied inputs returns equal
  results and leaves its inputs unchanged.
- A20 both file and qualname change, no declaration: finding. Same with declared `moved_from` and
  a changed def: passes only if the old qualified def is gone and the full bound stays.
- A21 compare docstrings differing only in indentation (pass), then change their text or another
  string literal (finding). A22 cover absence for bound-first, prefixed, ordinal, dotted and
  def-only keys in each root. Seed a surviving def, a ghost base, ambiguous defs and a bad read.
- A23 run the extracted base checker with head `layout/_moves.py` replaced by an admit-all stub
  and head `ratchet/_identity.py` misclassifying the key. Base still rejects A15. Seed each
  replacement separately so either accidental head import fails the test.
- P1 property (Hypothesis, fixed seed): over generated base and head baselines, whenever `check`
  passes for an existing, comparable debt baseline (exclude GUARD_KEYS, initial inventories and approved growth/raises), the head total of non-approved keys (sum of `max`, or 1 per entry without `max`) is at
  most the base total. This states total-not-grow as a redundant invariant; no extra code path.

Update the exact legacy stdout assertions in `test_ratchet_check.py:346` and `:536` from `re-homed` to `moved ... (declared`.
Existing engine tests in `tests/sentry/test_ratchet_check.py:386-420` and `:539`:
keep still-present and reused claims red. Split the numeric-max refusal into missing/raised
(red) and equal/lower (green). Split the non-allowlisted case into a registered eligible id
(green) and unknown `a` (red). The undeclared and ordinal fixtures change both file and def
name and stay red as written. Add same-qualname variants that now pass inference.

MK-C1 uses CLI `tests/sentry/ratchet/test_moved_keys.py` with shared `MOVE_CASES` for A1-A6,
A9-A10, A13, A15-A17 and A21-A23 using CLI shapes. CLI A12 compares the union of explicit
eligible and excluded ids to all 34 registry ids exactly. A missing or duplicate classification
fails the guard. Runtime unknown ids use NO_INFERENCE. Test declared precedence, lower max,
changed reason, changed rule, duplicate claims and split double spending under 5.6. Pin the vendor digest.

BD-E1:
- B1 under umask 022, the pool-quality spool file is created mode 0600 (stat inside the run).
- B2 private-file-sinks baseline drops the pool-quality entry and each entry now matched by the
  recognition rule (6.6); stale test green.
- B3 seeded: a recognized write is not a finding; seeded negatives are findings: a reassigned
  handle, an unlink then reopen of the precreated path, a handle passed through a helper, an alias
  (`h2 = h`), a plain `open()` handle, and a precreated COPY target with the literal
  `USE_TMP_FILE false` omitted, changed to true or supplied dynamically.

BD-E2:
- D1 golden bytes for the FK lane fixtures (single-column FK, composite FK, self-reference, nullable
  FK, int64 key over 2**53) are byte-identical before and after (control, must stay green).
- D2 lossless-int `ALLOWED` and baseline equal the target from BD-A0; a seeded direct ingestion
  site fails.

BD-E3:
- C1 `TRUTH_TEST_BASELINE` (`tests/sentry/test_table_kind_classifier.py:26`) drops to the target;
  `MUST_BE_ZERO` gains each module brought to zero.
- C2 seeded: a new inline truth test in a zeroed module fails.

BD-E4: E1 each accessor returns the same sorted names as the private registry; E2 compatibility
entry lists the three names as additive; E3 the frozen public surface snapshot updated in the
same commit.

BD-C1 and BD-C2: each guard's allow list equals its target; a seeded direct site still fails; the
engine-internal boundary sentry has no #2 to #4 entries.

## 4. Named mutations (each turns its named test red on the final head)

- M1 accept the first candidate on a tie (A3 red).
- M2 drop the `site_gone` call (A4 red).
- M3 compare `max` with `>=` instead of `<=` (A2, A18 red).
- M4 include `GUARD_KEYS` in inference (A7 red).
- M5 skip the def-content comparison (A15 red).
- M6 `open_private` back to `open(..., "wb")` in `_pool_quality.py` (B1 red).
- M7 restore one inline `.get("generate_columns")` truth test (C2 red).
- M8 swap the int64 ingestion helper for `to_pandas()` in one BD-E2 site (D1 red).
- M9 accept a bare-file move without the git rename check (A16 red).
- M10 infer a move where both file and qualname changed (A20 red).

## 5. Behavior and failure modes

MK, engine and CLI:
1. After the declared re-home step, every baseline not in `GUARD_KEYS` or `REKEY_PER_SITE`, and
   not in `NO_INFERENCE`, runs `infer_moves(lost, grown)`.
2. Each key is parsed by its sentry's row in the 6.3 table into a root prefix, location parts and
   a bound part. Identity is the bound part plus the location part that must stay equal.
3. A lost key and a grown key pair only when each is the only candidate of its identity on its side.
   A tie is a finding naming both candidates. There is no tie-break.
4. A pair is accepted only when the 6.1 rules hold and the entries match (6.2).
5. Print `<sid>: moved <old> -> <new> (<declared or inferred>; <proof>)` for each newly accepted pair.
6. Engine per-entry declarations use 6.1. CLI top-level `moved_from` keeps its existing scope
   (including NO_INFERENCE rows): a unique lost base key, absent from head entries, maps to
   one gained head key with equal `_rule_of` (last `::` segment, or None). Require exact typed
   JSON equality including reason except that an existing integer max may decrease. Keep the
   malformed-map, stale-declaration and duplicate-key checks. CLI declarations use baseline
   absence, as today. Validate `split_from` separately on split-enabled rows with existing sums,
   types, rule and overlap checks. Reserve all claimed old and new keys before inference;
   invalid claims remain findings. Emit one reviewed line per newly admitted move.

BD: each burn slice moves sites onto the named helper, lowers the inline allow-list and the JSON
baseline together, and adds one seeded case per guard that shows a new direct site still fails.

| # | Failure | Guard |
|---|---------|-------|
| F1 | a new site is laundered as a move of a deleted unrelated site with the same bound name | one location part kept, def-content proof, uniqueness, report line (A15, A3) |
| F2 | a move raises `max` | bounds check after pairing; `loosened_findings` unchanged (A2) |
| F3 | the old site is still live under the old key (copy, not move) | proof of absence; mirror test (A4) |
| F4 | two sites move at once and swap identities | uniqueness and content proof (A3, A15) |
| F5 | a `sentry-limits` key moves and hides a raised limit | excluded by `GUARD_KEYS` (A7) |
| F6 | CLI and engine checkers disagree on a move | one vendored `_moves.py`, digest pin, `MOVE_CASES` |
| F7 | a bare-file count is paid for by an unrelated new file | git rename check (A16) |
| F8 | a burn slice changes output bytes on the FK lane | BD-E2 byte goldens (D1) |
| F9 | a private write moves onto a handle the rule wrongly trusts | BD-E1 seeded negatives (B3) |
| F10 | the checker crashes on an odd key and passes the run | malformed keys are "not proven", never raise (A13) |

## 6. Design

### 6.1 Move rules

- Inference keeps either file or qualname, and compares the entire parsed bound including
  prefix, kind and ordinal. File-only candidates use the reported rename partner. Require unique partners in both directions across both candidate
  sets. A changed file and qualname together require an explicit declaration.
- Strict proof: find one enclosing def/class on each side, replace only its own name with a
  sentinel, apply `inspect.cleandoc` to actual docstring constants (including nested defs and
  classes), and compare `ast.dump(..., include_attributes=False)` within the same checker process. Keep decorators, signatures,
  ordinary string literals and docstring text. Missing or ambiguous source cannot prove a move.
- Use the parsed (root, file, qualname, bound) on both sides. Resolve paths through checked
  regular-file readers. For def proofs verify the qualified def exists at base and destination.
  At the old head location a checked missing file or absent qualified def proves absence.
  For inference on a name bound, the existing AST mention test can also prove the binding gone;
  for non-name bounds (digest, ordinal, expression, composite) require the qualified def absent.
  Read or parse failures never prove absence. Test missing and still-live sites for each shape (A22).
- Under OQ6b a declared engine def move needs the old qualified def gone, full bound kept,
  entry match and a reviewed move line. Both location parts may change and the dumps may differ.
  The two existing declared binding sentries retain the existing `_site_parts` rule: compare the
  binding name, ignoring an optional decimal ordinal, and prove no reference to it at the old
  location. Keep existing no-max cases; for counted pairs enforce 6.2 before admission. A declaration reserves both endpoints even when rejected.
- File-only and module-level pairs, including declarations on engine rows, require the exact
  old/new path pair in a checked `git diff -M --name-status -z <base>` against the checkout.
  Read NUL-separated status and path fields as bytes, decode paths with surrogateescape.
  Accept only R records, with git's default similarity threshold. A skipped inexact rename
  (rename limit), copy or absent record gives no rename proof. A failed diff fails the check.
  Compare baseline, old-site absence and new source against that same checkout using
  `open_input(Side("head", root), path)`. Base uses the resolved merge-base tree. Never mix
  checkout bytes with a commit-to-commit rename list. Test staged renames and a working-tree
  edit that breaks the strict proof. Untracked destinations without a rename record stay growth.

### 6.2 Entry match

For new engine moves and CLI inference, compare entries after removing declaration metadata.
The grown entry equals the lost entry except `reason` text and bounds; `max` is equal or lower,
`min` equal or higher, `category` equal, JSON types and bound field presence kept (bool is never an int). CLI declarations use 5.6. Total-not-grow follows from 1:1 pairing
plus bound checks plus "unpaired growth fails". It is a redundant invariant, checked by P1, with
approved keys excluded from both totals. No separate code path.

### 6.3 Registry table (61 ids at 8414da35c; A12 keeps it equal to `sentry_registry.toml`)

Shape notation: `F` file, `Q` qualname, `B` bound, `n` ordinal. Proof `def` is 6.1 content proof
plus `site_gone`; `rename` is the git rename check. Root is the prefix the file part is relative to.

| Id | Key shape | Location | Bound | Proof, root |
|----|-----------|----------|-------|-------------|
| f29-reason-baseline | `config::<code>` | none | code | NO_INFERENCE: a reason code, not a site |
| f29-producer-inventory | `F::Q::kind::B` | F, Q | kind, B | def, `src/decoy_engine/` |
| f29-consumer-inventory | `F::Q::B` | F, Q | B | def, `src/decoy_engine/` |
| secret-material-census | `F::Q::B` | F, Q | B | def, `src/` |
| module-size | `F` | F | none | rename, repo |
| public-import-boundary | `F` | F | none | rename, `src/decoy_engine/` |
| exception-hierarchy | `dotted.module::Class` | F, Q | none | def (class), `src/` dotted |
| file-access-entry-seams | `dotted.module.func` | F, Q | none | def, `src/` dotted |
| post-scan-route-exempt | `dotted.module.func` | F, Q | none | def, `src/` dotted |
| locator-waivers | `F::Q::B` | F, Q | B | def, `src/decoy_engine/` |
| log-interpolation | `F::Q::B` | F, Q | B | def, `src/decoy_engine/` |
| eval-sites | `F` | F | none | rename, `src/decoy_engine/` |
| phase-containment | bare name | none | name | NO_INFERENCE: no location part |
| validate-no-mutation | empty | none | none | NO_INFERENCE: empty baseline |
| physical-seam-connected | `F` | F | none | rename, `src/decoy_engine/` |
| wave-b-string-target-exempt | `testF::dotted.target` | testF | target | NO_INFERENCE: no def to compare; GA stub work owns it |
| wave-b-e0-test-files | `testF` | testF | none | rename, repo |
| handler-row-guard-exempt | `F` | F | none | rename, `src/decoy_engine/execution/` |
| private-file-sinks | `entry::F::Q::call::n` | F, Q | call, n | def, `src/` |
| gcs-call-kwargs | `F::Q::call::n` | F, Q | call, n | def, `src/` |
| serial-resources | `testF::test` | testF | test | def, repo |
| reason-policy-single-source | `F::func` | F, Q | none | def, repo |
| reason-unchecked-helpers | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| exception-context | `F::Q::n` | F, Q | n | def, `src/` |
| validation-name-messages | `permitted::F::Q::hash` | F, Q | hash | NO_INFERENCE: `REKEY_PER_SITE` path |
| package-fanout | directory | dir | none | NO_INFERENCE: git does not report directory renames |
| import-layers | `layers::a -> b` | none | edge | NO_INFERENCE: an edge, not a site |
| table-kind-truth-tests | `F` | F | none | rename, `src/decoy_engine/` |
| post-scan-blocking | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-pass-through | `F::Q::kind::n` | F, Q | kind, n | def, `src/` |
| post-scan-key-core | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-reason-identity | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-gate-applies | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-commit | `F::Q::kind::n` | F, Q | kind, n | def, `src/` |
| post-scan-model-predicate | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-readability | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-route-coverage | empty | none | none | NO_INFERENCE: empty baseline |
| strategy-docs-agree | prose line | none | text | NO_INFERENCE: the key is doc text |
| win32-import-surface | `F::kind` | F | kind | rename, `src/` |
| platform-census | `F` | F | none | rename, `src/` |
| dir-fd-readers | `F` | F | none | rename, `src/` |
| physical-seam-scoped | `F::NAME` (module level) | F | NAME | rename, repo |
| ci-write-scopes | `x.yml::` | F | none | NO_INFERENCE: workflow permissions need review on rename |
| canonical-json-choke-point | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| ner-mismatch-single-site | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| validation-route-allowlist | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| snapshot-parse-single-owner | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| parquet-intermediate-writers | `F::func` | F, Q | none | def, `src/` |
| metadata-carrier-allow | `F::func` | F, Q | none | def, `src/` |
| date-shift-window-reader | `F::func` or `F::None` | F, Q | none | def; `F::None` (module level) uses rename; `src/decoy_engine/` |
| group-by-single-reader | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| lossless-int-columns | `B::F::Q` (bound first) | F, Q | B | def, `src/decoy_engine/` |
| column-shape-classifier | `B::F` (bound first) | F | B | rename, `src/decoy_engine/` |
| bucketize-width-contract | `F` | F | none | rename, `src/decoy_engine/` |
| signature-exemptions | empty | none | none | NO_INFERENCE: empty baseline |
| output-assembly-one-path | `F::func` | F, Q | none | def, `src/decoy_engine/` |
| faker-pool-size-one-resolver | empty | none | none | NO_INFERENCE: empty baseline |
| faker-native-allowlist-total | provider name | none | name | NO_INFERENCE: no location part |
| config-refusal-text | `F::Q::hash` | F, Q | hash | def, `src/decoy_engine/` |
| engine-exception-text-copies | `audit::F::Q::B::kind` or `extra::F::Q::B::kind` | F, Q | B, kind | def, `src/decoy_engine/` |
| sentry-limits | `_ratchet.py::NAME` | none | NAME | NO_INFERENCE: `GUARD_KEYS` |

Treat func/test/class in a def-only key as Q with an empty bound, permitting a qualified rename.
For dotted module/class keys split at `::`; for dotted function keys split at the last dot.
Map identifier module segments below `src/` to a regular `.py` or package `__init__.py`;
require a unique resolution in the corresponding tree. Check old-head absence against the
base-resolved path, including package modules whose old file is gone. For date-shift parse literal `None`
before identifier validation as the module-level rename case. Otherwise resolve a function or
class qualname for def proof. Empty, unknown and malformed identities give NO_INFERENCE.

#### CLI identity table (2ca3bbd4, 34 ids)

Grouped ids share a parser. F is relative to `src/decoy/` unless another root is shown.
Q includes the full dotted qualname. Keep every listed bound token exactly. Unlisted = NO_INFERENCE.

| Registry ids | Identity and proof |
|---|---|
| atomic-writer-allow, canonical-json-allow, library-writer-allow | F, rename |
| module-size, old-org-refs | F, repo root, rename |
| engine-internal-allow, engine-reason-code-copies | F::symbol, retain symbol, rename |
| lint-debt | F::rule, repo root, retain rule, rename |
| scan-call-allow, csv-read-allow, target-writes-allow, output-placement-allow, run-exit-owners, run-exit-owners-io | F::Q, def |
| serial-resources, outbound-network-owners | F::Q, repo root, def |
| manifest-path-forward-allow | F::Q::symbol, repo root, def |
| exception-context | F::Q::n, src/ root, def |
| json-stdout-writes, config-load-allow | F::Q::n, def |
| one-error-emitter, banned-text-allow, config-route-allow | F::Q::token, def |
| env-reads, private-file-sinks | F::Q::token::n, def |
| gate-single-entry-allow | dotted.module::Q::rule, src/ root, def |
| root-help-omitted, readme-table-omitted, kind-canary-pending, config-field-readers | NO_INFERENCE, logical names |
| package-fanout, import-layers | NO_INFERENCE, directory or edge |
| output-name-allow, exit-code-owner | NO_INFERENCE, empty |

Non-identifier Q (including `<module>`) has no def proof. CLI A12 also samples the real
keys against their parser and root, plus a new id with no row.

### 6.4 Counted declarations at `_rehome.py:109`

The numeric-max veto is at `tests/sentry/ratchet/_rehome.py:109`. Compare bounds on the paired
entries before admission: missing, non-integer or raised max fails. The later same-key
`loosened_findings` check cannot compare different keys. A18 exercises the paired check.

### 6.5 Code layout and vendoring

- `tests/sentry/layout/_moves.py` (new, stdlib only, about 250 lines): key parsing from a passed-in
  identity table, pairing, entry match, def normalization. It takes the base reader, head reader
  and rename list as callables, so it has no repo imports. The engine is its source; the CLI
  copies it byte for byte, pinned by digest like `_ratchet_cases.py`.
- `tests/sentry/ratchet/_identity.py` (new, engine, about 120 lines): the 6.3 table and roots.
- Engine `ratchet/_rehome.py` wires readers, rename records and declarations. Move the AST
  walkers into the vendored proof implementation. Replace `_site_parts` and hardcoded `src/`
  for new rules with parsed identities. Keep the legacy declared checks in that same path.
- Generalize the by-path loader in `tests/sentry/_ratchet.py:60-74` for the two fixed subdirs.
  Resolve `layout/_moves.py` and `ratchet/_identity.py` relative to the running checker in both
  repos. Inject the loaded modules into the wiring. No checkout imports or sys.path fallback.
- `tests/sentry/layout/_ratchet_cases.py` (35 lines): adds a new repo-neutral `MOVE_CASES` table;
  `MAX_VALUE_CASES` and `REGISTRY_PATH_CASES` are unchanged. The A11 replay is engine-only and
  stays in `test_moved_keys.py`.
- MK-E1 updates the engine pin (`tests/sentry/layout/test_vendored_files.py:19`) and the vendored
  ledger rows. The CLI pin is one vendor behind today (CLI pins `038d0dff...`, engine is at
  `0305e162...`), so MK-C1 re-vendors across both changes.
- CLI `tests/sentry/ratchet/_move_check.py` (about 150 lines) owns the head checkout reader,
  base reader and checked git diff -M adapter using RG-C1a integrity helpers. Move the existing
  CLI map validation here from `_ratchet.py:273`, call it once with split claims before inference,
  and share typed comparison with the existing split validator. CLI `_ratchet.py` delegates and
  receives findings, admitted keys and report lines. Budget below 600 by relocating the map
  code, measuring after RG-C1b. Keep the existing check entry point and test callers working.

### 6.6 BD-E1 recognition rule

A write is routed when, in one function body: its sink argument is a `Name` bound exactly once,
by `with open_private(p) as h` or `h = open_private(p)`, and passed directly to `pq.write_table`,
`pq.ParquetWriter`, `pa.ipc.new_file` or `pa.ipc.new_stream`; or its path argument is a `Name`
bound exactly once by `precreate_private(p)` and passed directly to a duckdb `execute` COPY or an
ipc writer. COPY must explicitly specify the literal option `USE_TMP_FILE false` in its
options (including the resolved literal of the existing PRIVATE_COPY constant). Unknown or
conflicting options fail recognition. For either path writer require no `unlink`, `os.remove` or `open` of that name between. Not routed: a rebound
handle, an alias (`h2 = h`), a handle passed into another function (the callee is checked on its
own), an unlink then reopen. BD-A0 names one private-file owner: `fileaccess/_private.py`
(recommended) or `execution/out_of_core/_scratch.py`. The split of private helpers across those two
modules is recorded as a follow-up item, not V1 work.

### 6.7 Ordering and base-checker effect

MK-E1 starts after RG-E3 merges (hard dependency). RG-E3 makes the gate run the base checker
against the head, so a slice cannot use its own checker change to pass itself: inference applies to
PRs whose merge base includes MK-E1. MK-E1 itself carries no baseline moves. RG-E3 archives
`scripts/dev` and `tests/sentry`, which includes the two new helpers. Its plan at lines 669-672
requires a loaded-helper set for checker changes. RG-E3 is pending at the pinned base. MK-E1 and MK-C1 must verify that the actual
set includes `layout/_moves.py`, `ratchet/_identity.py` and the wiring helper, extending it if
needed. Guard the set against the loader's actual paths and run A23 from the extracted copy.
RG plan lines 689-690 forward only decision and waiver lines. The report printer at
`scripts/dev/ratchet_check.py:65` emits `ratchet: <sid>: moved ...`. MK-E1 adds this anchored
line shape to the engine `scripts/dev/gates.sh` filter and MK-C1 adds it to the CLI gate.
Forward declared and inferred lines on pass and failure. Preserve existing decision and waiver
lines and the step exit code when the filter finds no match. A17 exercises the installed filter.

### 6.8 Design notes and choke point

- Principles: open/closed for key shapes (a new sentry adds one table row); one place per fact
  (move rules only in `_moves.py`, shapes only in `_identity.py`). Pattern: git rename detection.
- Refactoring names: BD-E1 and BD-E3 are Substitute Algorithm at each call site; BD-E2 is Move
  Function plus Replace Inline Code with Function Call.
- Choke point: the `_ratchet._check` grown-key branch (`tests/sentry/_ratchet.py:534` to `:545`)
  is the one place a grown key becomes a finding. Inference runs inside it, before
  `approved = grown & approvals`. Guard test
  `test_moved_keys.py::test_every_grown_key_reaches_one_verdict`: each grown key ends as moved,
  approved, or finding, exactly once. Mutation: M2.

## 7. Established solutions

Search run (2026-11-28): git rename detection, SonarQube issue tracking across moves, PHPStan
baseline behavior on moved files, plus the in-codebase ratchet helpers in both repos.

- git rename detection (`diffcore-rename.c`): exact matches, then content similarity, with a
  basename heuristic added in 2021 (Elijah Newren, "Optimization batch 7").
  https://lore.kernel.org/git/pull.843.v3.git.1612970140.gitgitgadget@gmail.com/
  We take exact identity plus content proof and the rename report itself (`git diff -M`); we drop
  the basename guess.
- SonarQube issue tracking: the server detects a file rename before it matches issues, so issues
  follow the file; an unmatched new issue is new.
  https://docs.sonarsource.com/sonarqube-server/user-guide/issues/solution-overview
- PHPStan baseline: counts per (message, file), no move inference, so a moved file shows as one new
  and one fixed entry. That is today's failure.
- House mechanism: `site_gone` (`tests/sentry/ratchet/_rehome.py:59`), `rehomes`
  (`tests/sentry/ratchet/_rehome.py:84`), `BaseTree` (`_integrity.py`), CLI `moved_from` and
  `split_from` maps. MK generalizes these; no second mechanism.
- The RATCHET-GROWTH plan's list (PHPStan baseline, pest-ratchets, Catraca, JSON Schema
  `additionalProperties`, PurePosixPath, git archive) applies unchanged.

Why custom code remains: no maintained library ratchets per-site AST baselines across two repos.

### Reuse inventory

| Need | Reuse | New |
|------|-------|-----|
| old site gone | `_qualname_nodes`, `_mentions` in `_rehome.py:28-48`; existing `_site_parts` / `site_gone` at 51-81 accept only src-relative name keys | parsed identity, qualified-def absence for non-name bounds, A22 |
| base file bytes | `BaseTree.blob` (`_integrity.py:101`) | none |
| file renames | `git diff -M` | none |
| declared moves | `rehomes` (`_rehome.py:84`) | relaxation 6.4 |
| loosened bounds | `bounds.loosened_findings` (`ratchet/_bounds.py`) | none |
| stale entries | each sentry's stale test, `test_baseline_registry.py` mirror | none |
| private files | `open_private` (`execution/out_of_core/_scratch.py:25`), `precreate_private` (`:54`), `write_private` (`fileaccess/_private.py:21`) | none |
| table kind | `generate_columns_of` (`config/_tables.py:485`) | none |
| cross-repo sync | digest-pinned vendoring (`test_vendored_files.py`) | `_moves.py` added to it |

## 8. Placement and slices

| New file | Directory | CODEMAP line | Beside |
|----------|-----------|-------------|--------|
| `_moves.py` | `tests/sentry/layout/` | engine CODEMAP:309, layout helpers | `_ratchet_cases.py` |
| `_identity.py` | `tests/sentry/ratchet/` | engine CODEMAP:310 | `_rehome.py` |
| `test_moved_keys.py` | `tests/sentry/ratchet/` | engine CODEMAP:310 | `test_bounds.py` |
| ledger record | `docs/records/` (`YYYY-MM-DD-ratchet-burndown-ledger.md`, dated on BD-A0) | engine CODEMAP:314 | other records |
| CLI `_moves.py` | CLI `tests/sentry/layout/` | CLI CODEMAP:73, vendor | `_ratchet_cases.py` |
| CLI `_move_check.py`, `test_moved_keys.py` | CLI `tests/sentry/ratchet/` | RG-C1a ratchet row under CLI CODEMAP:73 | `_integrity.py` |
| CLI `_identity.py` | CLI `tests/sentry/ratchet/` | ported by RG-C1a | `_integrity.py` |

| Slice | Repo | What | Depends on | Risk | Size |
|-------|------|------|-----------|------|------|
| MK-E1 | engine | `_moves.py`, `_identity.py`, `MOVE_CASES`, rehome relaxation, A1 to A23, P1, gate filter | RG-E3 merged (hard), OQ1, OQ6 | R2 (test tooling: full suite) | 1.5 days |
| MK-C1 | CLI | vendor `_moves.py`, CLI identity table, checker wiring, gate filter, CLI A12/A17/A23 | MK-E1, RG-C1b | R2 (test tooling) | 0.5 day |
| BD-A0 | engine | ledger record: kind, owner helper, target, owning row, private-file owner | OQ1 | R0 (doc) | 0.5 day |
| BD-E1 | engine | recognition rule 6.6; pool-quality spool onto `open_private` | BD-A0 | R2 (private file class) | 0.5 day |
| BD-E2 | engine | lossless-int-columns sites call one ingestion helper | BD-A0, OQ5 | R2 (FK lane) | 1 day |
| BD-E3 | engine | inline `.get("generate_columns")` truth tests call `generate_columns_of` | BD-A0 | R1 | 0.5 day |
| BD-E4 | engine | public `list_mask_strategies`, `checksums.list_schemes`, `validators.list_validators` | OQ4 | R1 (additive API) | 0.5 day |
| BD-C1 | CLI | csv-read-allow, scan-call-allow, target-writes-allow, config-load-allow to their owners | BD-A0 | R1 | 0.5 day |
| BD-C2 | CLI | drop engine-internal-allow #2 to #4 after the repin with BD-E4 | BD-E4 release | R1 | 0.25 day |

Nine slices, about 5.75 build days. Further burn slices come by plan amendment after BD-A0 and OQ5.
Sizes after extraction: engine `_rehome.py` about 140, each `_identity.py` about 120,
vendored `_moves.py` about 250, engine and CLI move tests below 550 each, CLI wiring about 150.
Budget engine and CLI checker files at 590 each. Measure after dependencies merge and keep each
new module below 600. The replay belongs with the engine move tests. BD-E4 adds three public names.

Tests per slice: T0 per edit, T1 per commit. MK-E1 and MK-C1 hit the "test tooling" trigger, so
each runs the full suite once on its merge head against the saved main baseline (`decoy-vm-t3`
default mode). BD-E2 runs the FK companion suite. Builders follow TEST-RUNBOOK.md and do not run t1.

## 9. Class table

| # | Class | Where it can happen | Closing structure | Sentry or test | Mutation |
|---|-------|---------------------|-------------------|----------------|----------|
| 1 | value-bearing output | report lines, findings | report lines carry keys only (paths, qualnames, bound names), never data values | A1 asserts the exact line | N/A: keys hold no data values; no new value surface |
| 2 | cleanup on exit paths | pool-quality spool | `open_private` handle in `with`; existing `finally` unlink kept | B1 (mode 0600 under umask 022) | M6 (plain `open`) |
| 3 | state and concurrency | checker helpers | `infer_moves` is a pure function of its arguments; no module cache | A19 `test_infer_moves_is_pure` | N/A: no shared state is added; A19 guards purity |
| 4 | route parity, silent fallback | a move that cannot be proven | falls back to growth, which fails; never to pass | A3, A4, A13, A16 | M1, M2, M9 |
| 5 | referential integrity | BD-E2 FK ingestion | one helper per site; byte goldens | D1 (FK byte goldens) | M8 (`to_pandas()` swap) |
| 6 | untrusted producer | baseline JSON edited by a builder | base read through `BaseTree.blob`; inference cannot pass a raised bound | A2, A10, A18 | M3 |
| 7 | toctou / check-then-use | proof at head vs base | base proof uses one resolved commit; head content and rename detection both use the gate checkout | A15 (unrelated swap) | M5 (skip content compare) |
| 8 | weak tests | moves that look like growth | real-history replay, positive and negative | A11 replay set | M1 (tie accepted) |
| 9 | refactor drift | burn slices | no behavior change: goldens and existing sentries stay green | D1, C1 | M7 |
| 10 | frozen contract drift | BD-E4 public names; vendored helpers | compatibility entry, surface snapshot, digest pins | E2, E3, vendored pin tests | N/A for MK: no frozen contract touched |

Recurring defects: (1) anchored validation uses fullmatch including newline negatives;
(2) strict wire/stored types refuse bool and numeric strings for counts; (3) no exception
context on new value-free errors; (4) versioned read models: existing baseline schema;
(5) normalized guard scanners: aliases and COPY options in B3; (6) no private-module imports
across packages (BD-E4 public exports); (7) no hidden CI failures (A17 propagates exit);
(8) one trust class per entry point (base code loads its own helpers, A23); (9) repeat mutations
on final head; (10) keep allowlisted helpers checked (B3, C2); (11) no raised pins or caps.

## 10. Routes and surfaces

The grown-key branch admits declared moves, inferred moves and approved growth; unresolved keys
stay growth. Sections 5 and 6.3 enumerate routes, fields and exclusions. D1 enumerates FK shapes.
The observable surfaces are the checker report and gate stderr (A17), spool mode (B1) and CLI
`list strategies|checksums|validators` output (BD-E4). Gate output includes the proof for each move.

## 11. Frozen contracts and compatibility

- `scripts/dev/sentry_registry.toml` closed schema (`ROW_KEYS = {"id","baseline","approved_growth"}`):
  unchanged. The identity table lives in code.
- Baseline JSON schema unchanged; `moved_from` is an existing optional field.
- Vendored files (`_ratchet_cases.py`, new `_moves.py`): engine first, CLI re-vendors with new
  digests and ledger rows.
- BD-E4: compatibility entry as additive, CHANGELOG `Added:` line, surface snapshot updated.
- Product CLI output stays byte-identical. The developer gate gains move reports.

## 12. Pre-mortem

A11 and A15-A16 catch unrelated growth paid for by a deleted site. A14 preserves pending census
declarations. Shared cases and digest pins guard repo drift. BD-A0 records the signed targets;
D1 stops a burn that changes FK bytes. OQ1 gates the build on the tracker rows.

## 13. Guard ledger (input to BD-A0; counts at engine 8414da35c and CLI 2ca3bbd4)

| Guard | Count | Owner helper | Target | Slice |
|-------|-------|-------------|--------|-------|
| private-file-sinks (engine) | 17 | `open_private`, `precreate_private`, `write_private` | 6 or fewer | BD-E1 |
| table-kind-truth-tests | 26 | `generate_columns_of` | 1 (`config/_tables.py`) | BD-E3 |
| lossless-int-columns | 17 | `lossless_int_columns`, `to_pandas_fk_safe` | set in BD-A0 (OQ5) | BD-E2 |
| engine-internal-allow (CLI) | 10 | engine public API | 7 (logging #1 stays) | BD-E4, BD-C2 |
| csv-read, scan-call, target-writes, config-load allow (CLI) | 1, 1, 1, 11 | named in BD-A0 | set in BD-A0 | BD-C1 |
| canonical-json, snapshot-parse, group-by, date-shift | 12, 11, 6, 14 | `_canonical`, `parse_snapshot_json`, `group_by_sibling`, `shift_window` | amendment | later |
| metadata-carrier, parquet-intermediate-writers, column-shape | 14, 8, 6 | per BD-A0 | amendment | later |

Pool-quality spool today: written at the umask inside a temp dir that `connect_duckdb` restricts to
0700, unlinked in `finally`. No leak today; BD-E1 makes the file 0600 by construction.

Out of scope: census baselines and F31-owned lists, module-size (OQ3), CLI gate-single-entry-allow
(CONFIG-EXPLICIT C2), CLI private-file-sinks (WIN-FEAS).

## 14. Related plans

- `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md` (RG-E3, RG-C1a, RG-C1b).
- F31-AUDIT AE5b, AC1, AC3; CLI-SPLIT S2; EW2 to EW5; CONFIG-EXPLICIT C2.

## 15. Owner decisions (decided 2026-11-28)

Owner, 2026-11-28: "Go with recommended on all ratchet questions". All six questions are closed.

- OQ1. Decided: merge CLI PR #427 as is and build this plan. Build still waits on that merge.
- OQ2. Decided: inferred moves with a stderr line, plus declared `moved_from`.
- OQ3. Decided: defer the engine module-size burndown to STRUCTURE-REVIEW in 1.x.
- OQ4. Decided: BD-E4 adds the three public engine accessors in 1.0.
- OQ5. Decided: a reasoned floor per guard, signed in the BD-A0 ledger.
- OQ6. Decided: option (b). Keep strict inference and allow explicit engine declarations under
  6.1. Of the six historical moves this frees #775 automatically and #792 by declaration. PCR,
  AE5, vault and observed_shape still require owner review for growth.

## Appendix A. Options not chosen

- OQ1: (b) merge only the moved-keys widening and hold BURNDOWN for 1.x; (c) hold both.
- OQ2: (b) declared `moved_from` only, widened.
- OQ3: (b) `scripts/` entries only now; (c) all now.
- OQ4: (b) 1.x.
- OQ5: (b) zero for every debt guard; (c) only the three slices here for 1.0, rest 1.x.
- OQ6: (a) strict-only on declared paths; (c) drop MK and keep today's checker.
