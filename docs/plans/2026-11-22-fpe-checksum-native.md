Status: plan (revision 2, 2026-11-24; re-anchored to engine main `cb06f318e`)

# FPE-CHECKSUM-NATIVE: checksum-mode `fpe` runs in the Rust companion

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: FPE-CHECKSUM-NATIVE (group mask; V1 fast-path audit, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine and its Rust companion `decoy-engine-native/`. The CLI gets it through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/`; `native/` paths under `decoy-engine-native/` are named in full. Read at engine `origin/main` `cb06f318e` (re-anchored 2026-11-24; revision 1 read `70881ad79`). Must stay consistent with `plan/route-label-truth`, `plan/per-column-routing`, `plan/native-threads-default` and `plan/when-reads-source`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (crypto output on a reversible strategy; a companion ABI bump; four admission copies fold into one). Plan review: Dennis, then Codex. Code gate: Codex and Dennis, security lens on the kernel diff.

Owner direction (2026-11-22): every strategy runs its fastest path by default; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

## 1. Frame

Measured (audit, 2026-11-22): `fpe(..., checksum: npi)` takes 39.8 s per 120,000 rows on the pandas oracle. The same column without `checksum` takes 0.8 s on the native FF1 kernel. Every checksum column stays on Python because the kernel has no checksum path, and four places say so separately:

| Site | What it does |
|---|---|
| `execution/physical/_shadow_bindings.py:316-321` | leaves the unified-slice node unbound when `cfg.get("checksum")` |
| `execution/native/_real_type_admission.py:66-78`, used at `:154-157` | chunked decline `FPE_CHECKSUM_NOT_NATIVE` |
| `execution/_sequential_native_ops.py:254-257` | sequential decline `fpe_checksum_not_native:<column>` |
| `execution/out_of_core/_fpe_native.py:46-51` | out-of-core decline, same text |

Two more places depend on it: the kernel wrapper asserts no checksum reaches it (`execution/native/_fpe_ext.py:131-137`), and text_mask keeps its checksum detectors `pan` and `npi` off the kernel (`execution/native/_text_mask_native_fpe.py:44-50`).

The plumbing already carries the scheme to the kernel boundary: `FpeConfig.checksum` (`execution/native/_crypto_ext.py:151-189`), `FpeParams.checksum` (`execution/native/_operator_params.py:159`, `:263`) and `fpe_config_from_params`. The FFI entry `fpe_transform_batch` (`decoy-engine-native/src/arrow_ffi.rs:556-567`, which calls `fpe_transform_batch_checked` at `:491-502`) has no checksum argument. `arrow_ffi.rs` is 615 lines; the new argument adds about 6 lines to it and the checksum logic stays in the new modules.

Two more modules read `checksum` but do not decide a route: the Python handlers that carry the scheme to the oracle, `execution/_strategies/_fpe.py:162` and `execution/out_of_core/_mask_group_b.py:145`. They are unchanged.

The oracle (`transforms/_fpe_checksum.py:68-232`, `_fpe_checksum_permute`) runs, per value, after `_fpe_value` strips separators (`transforms/fpe.py:357-466`):

1. unknown scheme: `FpeChecksumError` (plan check `check_fpe_checksum_scheme`, `plan/_checks.py:457`, catches it at compile);
2. `iban`: `FpeChecksumError` (also caught at compile as `fpe_checksum_iban_unsupported`);
3. `_validate_scheme_length` (`transforms/_fpe_checksum.py:40`): exact lengths npi 10, isbn13 13, ean13 13, vin 17, gtin 8/12/13/14, luhn at least 2; else `fpe_checksum_unsupported`;
4. forward only: `checksums.validate(scheme, s)` (`checksums.py:351`); false gives `fpe_checksum_invalid_source`;
5. the scheme branch: luhn/ean13/gtin permute `s[:-1]` over digits and append the check digit; npi pins `s[0]`, permutes `s[1:9]`, appends the Luhn check over `"80840" + body9`; isbn13 pins `s[:3]`, permutes `s[3:12]`; vin filters the configured charset to the VIN alphabet (digits if fewer than 2 remain), permutes `s[:8] + s[9:]`, inserts the check character at position 8.

The FF1 call inside every branch is the same `_permute` that the non-checksum path uses, and the Rust kernel already reproduces it exactly (`decoy-engine-native/src/fpe.rs:174-245`, KAT-locked by `decoy-engine-native/tests/kat_fpe.rs`). Only the check-digit arithmetic and the branch layout are new.

Check-digit sources (`checksums.py:61-322`): luhn, ean13, gtin and isbn13 delegate to python-stdnum (`pyproject.toml:109`, `python-stdnum>=2.2`); npi (CMS NPI standard, Luhn over the `80840` prefix) and vin (NHTSA 49 CFR 565 weights and transliteration) are hand-rolled because stdnum 2.2 has no module for either.

## 2. Established solutions

Search run: Rust crates for check digits (`luhn`, `luhn3`, `checkdigit`, `isbn`, `vin`), how python-stdnum structures `calc_check_digit`/`validate`, and how other FPE products handle checksum identifiers (Voltage SecureData and Protegrity "Luhn-preserving" tokens, NIST SP 800-38G rev1 remarks on format constraints).

- Products keep the check digit outside the FF1 domain: encrypt the body, recompute the check digit. The engine already does this; the port keeps the method.
- The crates each cover one scheme, carry their own input rules (for example accepting separators or lowercase), and none covers NPI's `80840` prefix rule or the engine's VIN fallback. Adding five dependencies to replace about 120 lines of fixed arithmetic would widen the supply chain for no gain, and the KAT, not the crate, is what proves parity. Decision: a small pure Rust module `checksum.rs` with one function pair per scheme, each citing its standard in the doc comment (stdnum algorithm, GS1 General Specifications 7.9 for EAN/GTIN mod-10, ISO 2108 for ISBN-13, CMS NPI check digit, 49 CFR 565.15 for VIN), KAT-locked against python-stdnum and `decoy_engine.checksums`.

### Reuse inventory

- `fpe.rs::permute`, `ResolvedConfig`, `fpe_one` and the per-row code channel: reused; the checksum branch calls `permute` with a digits (or VIN) `ResolvedConfig` built once per batch.
- `fpe.rs::luhn_check_digit` (`:137`): moves into `checksum.rs` and is called from both places; `text_redact/validators.rs:13` `luhn_valid` keeps its own looser input rules (strip whitespace and dashes, at least 13 digits) because those are the detector's contract, but its mod-10 sum calls the shared function.
- The FFI shape, per-row `(row_index, code)` errors and `_row_error` mapping in `execution/native/_fpe_ext.py:159`: reused; two new codes join the list.
- `FpeConfig.checksum`, `FpeParams.checksum`: already carried.
- `native/_operator_config_rejections.py`: the existing home for config-level declines; the one checksum rule moves there.
- Vector tooling `decoy-engine-native/vectors/generate_fpe_kat.py` and `tests/kat_fpe.rs`: extended, not copied.

## 3. Guarantee and non-goals

After S2:

1. A string `fpe` column with `checksum` in {luhn, npi, ean13, gtin, isbn13, vin} gets the same admission on every route as the same column without `checksum` (same namespace, key, type and `when:` rules).
2. On every admitting route its output equals the pandas oracle row for row, including nulls, and the row errors equal the oracle's (same row, same code, same order of checks), in both directions (`forward` mask and inverse).
3. The check-digit arithmetic is proved by a KAT: every scheme against python-stdnum where stdnum has the scheme, and against `decoy_engine.checksums` plus published sample identifiers for npi and vin.
4. One admission rule: whether a checksum scheme is native is read from `OPERATORS["fpe"].checksum_schemes` by one function. A sentry proves no other module reads `checksum` to decide a route.
5. The companion refuses to load if its checksum KAT fails at import (same fail-closed pattern as the FF1 KAT).

Non-goals: `iban` (the oracle refuses it, unchanged); non-string sources (an `int64` NPI column stays on its current route and type rules); a new scheme; text_mask `pan`/`npi` spans (S3, separate slice); changing the oracle.

## 4. Enumerations

### Exit paths (per value, kernel and oracle in the same order)

1. null: null out, no error.
2. non-preserve mode with an out-of-charset character, or preserve mode with no in-charset character: existing codes, unchanged.
3. empty string: `fpe_unencryptable_domain` (existing, `transforms/fpe.py:398-406`).
4. length rule fails: `fpe_checksum_unsupported`.
5. forward and `validate` false (including a non-digit character a wide charset let through): `fpe_checksum_invalid_source`.
6. body too short for the FF1 domain (luhn with a 1-digit body, gtin-8 body of 7 digits over radix 10 below the floor): `fpe_unencryptable_domain` from the shared `permute`.
7. success: permuted body plus recomputed check digit, separators reinserted.

The per-row outcomes 4 and 5 become row errors on the native routes exactly as they are on the oracle (`execution/native/_crypto_reference.py:188-190`).

### Routes

| Route | Today | After |
|---|---|---|
| Unified slice | node unbound, table to full frame | bound, kernel |
| Chunked native | `FPE_CHECKSUM_NOT_NATIVE`, full frame | kernel |
| Sequential FK (non-key column) | `fpe_checksum_not_native`, Python | kernel |
| Out-of-core | `fpe_checksum_not_native`, Python | kernel |
| Full-frame pandas | runs | unchanged |
| Companion missing or ABI mismatch | n/a | the existing companion-absent decline, unchanged |

### FK shapes

- `fpe` on an FK key column (parent, child or composite part): stays on Python on every route (`docs/compatibility-contract.md:768`); checksum does not change that. K7.
- Non-key `fpe` column on an FK parent or child table: native on sequential and out-of-core, as today without checksum. K4.

### Fields

- `checksum`: the scheme name; the only field whose native handling changes.
- `charset`: vin filters it to the VIN alphabet; the other schemes permute the body over digits.
- `preserve_separators`, `namespace`, `join_group`: unchanged.
- `validate_luhn`: ignored when `checksum` is set (`transforms/fpe.py:485`), on both paths.
- No new field.

### Output surfaces

- Masked values and their nulls.
- Row errors: `fpe_checksum_unsupported`, `fpe_checksum_invalid_source` and the existing unencryptable codes.
- The two fpe warnings (`fpe_join_group_active`, `fpe_partial_plaintext_disclosure`), computed in Python as today.
- Route evidence: `rust_companion` with `positive_kernel_evidence`.
- The companion status record (`execution/native/_companion_status.py:224-270`), which gains the checksum KAT probe.

### Codes

No new route or runtime reason code. `FPE_CHECKSUM_NOT_NATIVE` (`reasons/route/_part1.py:128`) stays registered for a scheme the registry does not list (none after S2; kept so a future scheme lands declined first). The kernel returns the existing runtime codes `fpe_checksum_unsupported` and `fpe_checksum_invalid_source` (`reasons/runtime/_part3.py:174`, `:384`) as per-row codes; `_fpe_ext.py` adds them to its known-code set so an unknown code still fails closed.

## 5. Design

1. **Registry fact.** `OperatorSpec` gains `checksum_schemes: frozenset[str] = frozenset()`. The fpe spec (`execution/_operator_registry.py:277-301`) sets it to the six schemes in S2. S1 leaves it empty.
2. **One rule.** `fpe_checksum_rejection(column, cfg) -> str | None` in `execution/native/_operator_config_rejections.py`: `None` when `cfg.get("checksum")` is falsy or in `OPERATORS["fpe"].checksum_schemes`; otherwise `fpe_checksum_not_native:<column>`. The four sites in section 1 call it; `_shadow_bindings.py` keeps its `None` return when the rule rejects. The sequential gate order "checksum, namespace, config, source type" (`_sequential_native_ops.py:253`) is kept by calling the rule first.
3. **Wrapper.** `_fpe_ext.py:131-137` becomes: pass `checksum` through to the kernel; the assertion is replaced by "scheme in `checksum_schemes`" so a caller that skips admission fails closed with a coded error, not wrong output.
4. **FFI.** `fpe_transform_batch` gains `checksum: Option<String>` (last positional, before `native_threads`). An unknown scheme string returns a whole-call error `fpe_checksum_unknown_scheme` (the plan check catches it first; this is the backstop). `ABI_VERSION` moves to `decoy-native-abi-4` (`decoy-engine-native/src/lib.rs:57`) and `_EXPECTED_ABI_VERSION` (`execution/native/_crypto_ext.py:359`) with it, so an old companion is refused instead of silently ignoring the argument.
5. **Kernel.** New `decoy-engine-native/src/checksum.rs` (pure, no PyO3): `validate(scheme, &[char]) -> bool`, `check_digit(scheme, &[char]) -> char`, `length_ok(scheme, n) -> bool`. New `decoy-engine-native/src/fpe_checksum.rs`: `checksum_permute(...)` with the five steps in the oracle's order, calling `fpe::permute`. `fpe_one` calls it instead of `fpe_pure_value` when a scheme is set. `fpe.rs` is 682 lines, so the branch must not grow it: only the dispatch line lands there.
6. **Load-time self-test.** `_crypto_ext.py` adds `FPE_CHECKSUM_KAT` (one vector per scheme from the generated file) to the load probe next to `FPE_KAT`; a mismatch refuses the companion with the existing coded reason.
7. **Docs.** `docs/compatibility-contract.md` fpe native paragraph: checksum modes run native. `_fpe_ext.py` and `_text_mask_native_fpe.py` module docstrings updated.

Design notes: one fact (the registry field), one rule (the rejection function), one kernel path (the existing `permute`). The sentry in section 9 enforces the second.

## 6. Slices and size

| Slice | Content | Files | Lines (estimate) | Depends on |
|---|---|---|---|---|
| S1 | Fold the four declines into `fpe_checksum_rejection`; add `checksum_schemes` (empty); sentry K6. Behavior unchanged | `_operator_registry.py`, `_operator_config_rejections.py`, `_shadow_bindings.py`, `_real_type_admission.py`, `_sequential_native_ops.py`, `out_of_core/_fpe_native.py`, tests | source about 40 net negative, tests about 90 | none |
| S2 | Rust `checksum.rs`, `fpe_checksum.rs`, FFI argument, abi-4, vector generator and KAT files, load probe, wrapper pass-through, registry set to six schemes, contract paragraph, changelog | `decoy-engine-native/src/{checksum.rs,fpe_checksum.rs,fpe.rs,arrow_ffi.rs,lib.rs,text_redact/validators.rs}`, `decoy-engine-native/vectors/generate_checksum_kat.py`, `decoy-engine-native/vectors/{checksum_kat.json,fpe_checksum_kat.json}`, `decoy-engine-native/tests/kat_checksum.rs`, `execution/native/_crypto_ext.py`, `_fpe_ext.py`, `_companion_status.py`, `_operator_registry.py`, docs, tests | Rust about 320, Python about 40, vectors generated, tests about 350 | S1 |
| S3 (optional) | text_mask `pan` and `npi` detectors through the checksum kernel: drop the exclusion at `_text_mask_native_fpe.py:44-50` and pass the scheme | `_text_mask_native_fpe.py`, `_kernels_scalar.py` caller, tests | source about 25, tests about 120 | S2 |

Existing tests that assert a checksum decline flip (behavior change; names kept, each flip listed in the builder report): `tests/native/test_c6a_fpe_chunked.py`, `tests/native/test_obs2_decline_records.py` (keeps the code registered, flips the example), `tests/parity/test_phase_d_d2c_fpe_seq.py`, `tests/parity/test_phase_d_fpe_key_seq.py`, `tests/parity/test_phase_d_fpe_int_key_seq.py`, `tests/parity/test_ooc_fpe_native_routing.py`. The ABI bump and changed assertions are full-suite triggers, so S2 runs T3 on the merge head, on Linux and on the Mac (arm64 companion build).

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `checksum.rs`, `fpe_checksum.rs` | `decoy-engine-native/src/` | "Native companion" (Rust kernels by concern) | `fpe.rs` |
| `kat_checksum.rs` | `decoy-engine-native/tests/` | companion tests | `kat_fpe.rs` |
| `generate_checksum_kat.py`, `checksum_kat.json`, `fpe_checksum_kat.json` | `decoy-engine-native/vectors/` | companion vectors | `generate_fpe_kat.py` |
| `test_fpe_checksum_native.py` | `tests/parity/` | cross-route parity tests | `test_ooc_fpe_native_routing.py` |
| `test_fpe_checksum_one_rule.py` | `tests/sentry/defects/` | "Sentry test" | other defect sentries |

`fpe_checksum_rejection` goes into the existing `execution/native/_operator_config_rejections.py` (324 lines, room to spare). No new Python module.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | yes: scheme length and alphabet checks | Rust checks the whole value (exact `len`, every char), never a prefix; K3 hostile cells (trailing newline, extra digit, Unicode digit `٣`) | accept `n >= 10` for npi (K3 red) |
| 2 | Strict wire and stored types | the FFI `checksum` argument | `Option<String>` matched against a closed enum in Rust; unknown string is a coded error | map unknown to luhn (K5 red) |
| 3 | No exception context | the new coded errors | Rust codes carry no value; `_fpe_ext.py` keeps `from None` and value-free messages; existing value-free sentries | interpolate the source value into the unknown-scheme message (sentry red) |
| 4 | Versioned read models | the vector files | each JSON file carries `schema_version` and a provenance block (generator, stdnum version, date); `kat_checksum.rs` refuses an unknown version | drop the version check (seeded old-version fixture passes, red) |
| 5 | Normalized guard scanners | sentry K6 | parses the AST of `execution/` for any `.get("checksum")` or `["checksum"]` read outside a five-module allow set that belongs to this new sentry only (no existing allowlist or baseline grows): `_operator_config_rejections.py` (the rule), `_operator_params.py` and `_crypto_ext.py` (carry the scheme to the kernel), `_strategies/_fpe.py` and `out_of_core/_mask_group_b.py` (carry it to the oracle); catches attribute, subscript and `get` forms | add `if cfg.get("checksum"):` to `_shadow_bindings.py` (red); add it with a `getattr` alias (red) |
| 6 | No reaching into private modules | tests read `checksums._VALIDATORS` | the generator and tests use the public `validate`/`calc_check_digit` only | n/a |
| 7 | No hidden CI failures | Rust KAT and the Mac build | `cargo test` runs in the companion CI job; the gate records the arm64 build and `kat_checksum` result | n/a |
| 8 | One input, one trust class per entry point | `fpe_transform_batch` | one caller class (the engine wrapper); no new entry point | n/a |
| 9 | Mutations on the final head | named mutations below rerun after the last change | gate record | n/a |
| 10 | Allowlisted helpers still checked | sentry K6 own allow set of five modules | each allowed module must actually read `checksum` (a stale entry fails) | remove the read from `_crypto_ext.py` (sentry red on stale entry) |
| 11 | No raised caps | no cap raised; `fpe.rs` must not grow past its size | review; `fpe.rs` diff limited to the dispatch line | n/a |

### Harness defect classes (`docs/handoffs/DEFECT-CATALOG.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | kernel errors and row errors | codes only, no value in any Rust or Python message | value-free sentries, K4 asserts error text | add the value to a Rust detail string (sentry red) |
| 2 | Cleanup missing on an exit path | key material in the checksum branch | the branch borrows the batch FF1 instance; no new key copy; Python `del key` path unchanged | review, existing zeroize tests | n/a |
| 3 | State and concurrency | rayon row ranges | the branch is per value and pure; batch-invariance proptest extended to checksum configs | K4b thread-count cell | share a mutable digit buffer across rows (proptest red) |
| 4 | Route parity and silent fallback | five routes, companion absent | one rule; parity per route; companion absent keeps the decline | K4, K6 | leave one old decline in place (K6 red) |
| 5 | Referential integrity | FK key fpe | stays Python | K7 | admit fpe on a key (K7 red) |
| 6 | Untrusted producer | source values (hostile identifiers) | K3 hostile corpus through kernel and oracle | K3 | skip forward validation (K3 invalid-source cells red) |
| 7 | Check then use | N/A: validation and permute run on the same in-memory value in one call | n/a | n/a | n/a |
| 8 | Weak tests | a KAT built from the kernel itself | vectors come from python-stdnum and `decoy_engine.checksums`, never from Rust output; generator refuses to run without stdnum | K1 provenance check | regenerate vectors from Rust output (provenance check red) |
| 9 | Refactor drift | S1 fold | S1 is behavior-preserving; existing decline tests pass unchanged on S1 | S1 test run | n/a |
| 10 | Frozen contract drift | contract fpe paragraph, ABI string | contract text, abi-4, changelog fragment `changelog.d/fpe-checksum-native.md` (format in `changelog.d/README.md`) | K5, docs review | keep abi-3 with the new argument (K5 red) |

## 9. Acceptance tests (each fails before its slice unless marked)

- **K1 check-digit KAT (S2).** `vectors/generate_checksum_kat.py` writes, per scheme, at least 200 bodies (random, all-zero, all-nine, every leading digit, gtin at all four lengths, VIN with every letter of the VIN alphabet, isbn13 with 978 and 979) with `calc_check_digit` and `validate` from python-stdnum (luhn, ean13, gtin, isbn13) or `decoy_engine.checksums` (npi, vin). npi and vin also carry published samples: the CMS example NPI `1234567893` and the NHTSA example VIN `1M8GDM9AXKP042788`. `kat_checksum.rs` asserts Rust equals every row. Fail-before: the module does not exist.
- **K2 end-to-end FPE KAT (S2).** `fpe_checksum_kat.json` holds, per scheme, 50 valid identifiers with separators and without, masked forward and inverse by the Python oracle under a fixed key and tweak. `kat_fpe.rs` and the load probe reproduce them. Fail-before: the FFI has no checksum argument.
- **K3 hostile corpus (S2).** For each scheme, kernel and oracle on the same column: wrong length by one each way, a bad check digit, a non-digit in a wide charset, a Unicode digit, a trailing newline, leading and trailing separators, empty string, null, a luhn value of 2 characters (domain floor), a VIN with I/O/Q. Assert identical output and identical `(row, code)` row errors. Fail-before: no native path.
- **K4 route parity (S2).** Each scheme, deterministic namespace, 2,000 rows (unified slice) and 120,000 rows in three or more chunks (chunked native), plus sequential and out-of-core two-table jobs on a non-key column: route evidence is the companion and the output equals the forced full-frame oracle as an Arrow table (schema included) and by output hash; row errors equal. K4b: `native_threads` 1 and 4 give the same bytes. Fail-before: declined.
- **K5 ABI and unknown scheme (S2).** A companion reporting abi-3 is refused with the existing reason; `fpe_transform_batch(..., checksum="ibna")` returns `fpe_checksum_unknown_scheme`. Fail-before: abi-3 accepted.
- **K6 one rule (S1).** Sentry `test_fpe_checksum_one_rule.py` (section 8 row 5). Fail-before: four reads exist.
- **K7 FK key (S2).** `fpe(checksum: npi)` on an FK key column declines exactly as non-checksum fpe does. Unchanged-behavior control.
- **K8 inverse (S2).** Inverse mode over K2 outputs returns the sources on the native route.

Named mutations (record the head): swap the npi prefix `80840` for `80804` (K1 red); skip forward validation (K3 red); drop VIN charset filtering (K2 vin red); return `fpe_checksum_unsupported` for the domain-floor case (K3 red); leave the chunked decline in place (K6 and K4 red); keep abi-3 (K5 red).

Performance evidence (performance.md): the audit probe (`fpe(checksum: npi)` at 120,000 rows) and a 1,000,000-row run, three runs each on the Dell node through `vm-run`, before and after, wall time and peak RSS; expected close to the non-checksum 0.8 s per 120,000 rows. Numbers go in the PR body.

## 10. Frozen contracts and byte changes

No masked value changes on any route (K4 compares against the unchanged oracle). Named changes:

1. **B1.** Checksum columns move from the full-frame oracle to the native routes, so on unified slice and chunked an empty or all-null column takes the native routes' type rules (the fpe `tokenizing` assembly, `execution/_operator_registry.py:287-291`) instead of the pandas one. Same reconciliation as non-checksum fpe today.
2. **B2.** Companion ABI `decoy-native-abi-3` to `decoy-native-abi-4`: an older companion wheel no longer loads with a newer engine (it never shipped separately; the CLI bundles both).

Fragment first line: `Breaking: fpe with a checksum scheme (luhn, npi, ean13, gtin, isbn13, vin) now runs in the native companion on every route, and the companion ABI is now decoy-native-abi-4.`

`SEED_PROTOCOL_VERSION`, plan serialization and digests do not change.

Public signatures (engine #763 sentry, `tests/sentry/release/test_public_signatures.py`): no public Python signature changes. `OperatorSpec` is private and the new field has a default; the FFI is not a public Python surface. `tests/sentry/baselines/signature-exemptions.json` is not touched. The Breaking line above still goes in the fragment because of B1 and B2.

ABI pin sites S2 updates to the new tag (13 besides `lib.rs`): `decoy-engine-native/scripts/parity_smoke.py`, `execution/native/_crypto_ext.py`, `tests/native/{test_c6c_ii_text_redact_rust.py,test_crypto_ext_loader.py,test_group_key_ext.py,test_index_ext.py,test_native_ext_abi.py}`, `tests/parity/{test_ooc_fpe_native_real.py,test_ooc_text_redact_native_real.py,test_phase_d_d1a_hash_native.py,test_phase_d_d1b1_bucket_native.py,test_phase_d_d1b2_categorical_native.py,test_phase_d_dcomp_composite_ooc_real.py}`.

## 11. Pre-mortem

- A Rust check digit differs from stdnum on an edge (gtin-8 weights, ISBN-13 prefix). K1 covers every length and leading digit; a mismatch fails the companion at load, never output.
- VIN fallback: a charset with fewer than two VIN characters falls back to digits in the oracle. K2 includes a digits-only charset VIN.
- The oracle's `validate` uses stdnum's input rules (it may strip spaces). Separators are stripped before it in both paths; K3's separator cells prove the kernel matches.
- The arm64 Mac build fails on a new module. S2 gate builds on the Mac before merge.
- Two rows bump the ABI. TEXT-REDACT-RUST-SPLICE also plans an ABI bump. Whichever S2 merges second takes the next tag (`abi-5`) and updates the same pin sites; the second builder merges main and re-runs K5 before its gate. Neither plan reuses a tag.

## 12. Owner questions

None blocking. S3 (text_mask `pan`/`npi`) is in scope by default; say if it should wait.

## 13. Deferred (V2-LOG)

- **V2-LOG:** native checksum fpe on `int64` sources (needs a typed output contract).
- **V2-LOG:** `iban` FPE with per-country BBAN structure.
