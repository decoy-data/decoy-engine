Status: plan (revision 3, 2026-11-24; Dennis round 1 fixes applied; anchored to engine main `cb06f318e`)

# FPE-CHECKSUM-NATIVE: checksum-mode `fpe` runs in the Rust companion

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: FPE-CHECKSUM-NATIVE (group mask; V1 fast-path audit, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine and its Rust companion `decoy-engine-native/`. The CLI gets it through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/`; `native/` paths under `decoy-engine-native/` are named in full. Read at engine `origin/main` `cb06f318e`. Must stay consistent with `plan/route-label-truth`, `plan/per-column-routing`, `plan/native-threads-default`, `plan/when-reads-source` and `plan/text-redact-rust-splice`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (crypto output on a reversible strategy; a companion ABI bump; four admission copies fold into one). Plan review: Dennis, then Codex. Code gate per slice in section 6.

Owner direction (2026-11-22): every strategy runs its fastest path by default; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

Revision 3 changes (Dennis round 1): charset-alphabet clause in the one rule (H1); one predicate and a `(path, function)` sentry (H2); one shared load probe (H3); `npi_valid` reuses the shared NPI arithmetic (H4); exit paths corrected (M1); inverse proved at kernel level (M2); VIN charset order (M3); S2 split into S2a and S2b (M4); S3 uses the predicate (M5); LOW items 1 to 8.

## 1. Frame

Measured (audit, 2026-11-22): `fpe(..., checksum: npi)` takes 39.8 s per 120,000 rows on the pandas oracle. The same column without `checksum` takes 0.8 s on the native FF1 kernel. Every checksum column stays on Python because the kernel has no checksum path, and four places say so separately:

| Site | What it does |
|---|---|
| `execution/physical/_shadow_bindings.py:316-321` (`execution_binding_for_slice_node`) | leaves the unified-slice node unbound when `cfg.get("checksum")` |
| `execution/native/_real_type_admission.py:66-78` (`_fpe_checksum_decline`), used at `:154-157` | chunked decline `FPE_CHECKSUM_NOT_NATIVE` |
| `execution/_sequential_native_ops.py:253-257` (`_fpe_config_reason`) | sequential decline `fpe_checksum_not_native:<column>` |
| `execution/out_of_core/_fpe_native.py:46-51` (`decline_reason`) | out-of-core decline, same text |

Two more places depend on it: the kernel wrapper asserts no checksum reaches it (`execution/native/_fpe_ext.py:131-137`, `_CompiledFpeKernel.run`), and text_mask keeps its checksum detectors `pan` and `npi` off the kernel (`execution/native/_text_mask_native_fpe.py:44-50`, module-level `NATIVE_FPE_DETECTORS`, by tuple unpacking of `_FPE_CONFIG`).

The plumbing already carries the scheme to the kernel boundary: `FpeConfig.checksum` (`execution/native/_crypto_ext.py:151-189`), `FpeParams.checksum` (`execution/native/_operator_params.py:159`, `:263`) and `fpe_config_from_params` (`execution/native/_fpe_route.py:100-108`). The FFI entry `fpe_transform_batch` (`decoy-engine-native/src/arrow_ffi.rs:556-567`, which calls `fpe_transform_batch_checked` at `:491-502`) has no checksum argument. `arrow_ffi.rs` is 615 lines; the new argument adds about 6 lines and the checksum logic stays in the new modules.

Every other read of `checksum` under `execution/` carries the scheme and decides no route. Section 8 row 5 lists them by `(path, function)`.

The oracle (`transforms/_fpe_checksum.py:68-232`, `_fpe_checksum_permute`) runs, per value, after `_fpe_value` strips separators (`transforms/fpe.py:357-466`):

1. unknown scheme: `FpeChecksumError` (plan check `check_fpe_checksum_scheme`, `plan/_checks.py:457`, catches it at compile);
2. `iban`: `FpeChecksumError` (also caught at compile as `fpe_checksum_iban_unsupported`);
3. `_validate_scheme_length` (`transforms/_fpe_checksum.py:40`): exact lengths npi 10, isbn13 13, ean13 13, vin 17, gtin 8/12/13/14, luhn at least 2; else `fpe_checksum_unsupported`;
4. forward only: `checksums.validate(scheme, s)` (`checksums.py:351`); false gives `fpe_checksum_invalid_source`;
5. the scheme branch: luhn/ean13/gtin permute `s[:-1]` over digits and append the check digit; npi pins `s[0]`, permutes `s[1:9]`, appends the Luhn check over `"80840" + body9`; isbn13 pins `s[:3]`, permutes `s[3:12]`; vin filters the configured charset to the VIN alphabet and keeps the configured order (`_fpe_checksum.py:216`, `"".join(c for c in charset if c in _VIN_CHARSET)`; digits if fewer than 2 remain), permutes `s[:8] + s[9:]`, inserts the check character at position 8.

The filtered VIN charset order is a parity input: FF1 numerals are indexes into that string, so the Rust port filters the configured charset in its given order, never a sorted or canonical VIN alphabet.

The FF1 call inside every branch is the same `_permute` that the non-checksum path uses, and the Rust kernel already reproduces it exactly (`decoy-engine-native/src/fpe.rs:174-245`, KAT-locked by `decoy-engine-native/tests/kat_fpe.rs`). Only the check-digit arithmetic and the branch layout are new.

Check-digit sources (`checksums.py:61-322`): luhn, ean13, gtin and isbn13 delegate to python-stdnum (`pyproject.toml:109`, `python-stdnum>=2.2`); npi (CMS NPI standard, Luhn over the `80840` prefix) and vin (NHTSA 49 CFR 565 weights and transliteration) are hand-rolled because stdnum 2.2 has no module for either.

### Input normalization in the oracle

The oracle's `validate` normalizes before it checks. ean13, gtin and isbn13 call stdnum `compact` (`clean(number, ' -').strip()`, and `clean` maps Unicode digits to ASCII). vin runs `value.strip().upper()` with Python's Unicode upper (`'ſ'.upper() == 'S'`). npi uses `^\d{10}\Z` and `int(ch)`, so any Unicode decimal digit passes. The plan check accepts a charset that is a superset of the scheme alphabet (`plan/_checks.py:476-479`), so a wide charset can carry characters such as `-` or lowercase letters to `validate`.

Porting that normalization to Rust would need stdnum's Unicode digit table and Python's Unicode case mapping, kept in sync by hand. This plan does not port it. Section 5.2 admits the native path only when the resolved charset is inside an ASCII alphabet where every one of those normalizations is the identity or ASCII uppercase. Parity then holds by construction.

## 2. Established solutions

Search run: Rust crates for check digits (`luhn`, `luhn3`, `checkdigit`, `isbn`, `vin`), how python-stdnum structures `calc_check_digit`/`validate`, and how other FPE products handle checksum identifiers (Voltage SecureData and Protegrity "Luhn-preserving" tokens, NIST SP 800-38G rev1 remarks on format constraints).

- Products keep the check digit outside the FF1 domain: encrypt the body, recompute the check digit. The engine already does this; the port keeps the method.
- The crates each cover one scheme, carry their own input rules (for example accepting separators or lowercase), and none covers NPI's `80840` prefix rule or the engine's VIN fallback. Adding five dependencies to replace about 120 lines of fixed arithmetic would widen the supply chain for no gain, and the KAT, not the crate, is what proves parity. Decision: a small pure Rust module `checksum.rs` with one function pair per scheme, each citing its standard in the doc comment (stdnum algorithm, GS1 General Specifications 7.9 for EAN/GTIN mod-10, ISO 2108 for ISBN-13, CMS NPI check digit, 49 CFR 565.15 for VIN), KAT-locked against python-stdnum and `decoy_engine.checksums`.

### Reuse inventory

- `fpe.rs::permute`, `ResolvedConfig`, `fpe_one` and the per-row code channel: reused; the checksum branch calls `permute` with a digits (or filtered VIN) `ResolvedConfig` built once per batch.
- `fpe.rs::luhn_check_digit` (`:137`): moves into `checksum.rs` and is called from both places.
- `text_redact/validators.rs:13` `luhn_valid` and `:37-60` `npi_valid`: each keeps its detector input rules (strip whitespace and dashes; luhn at least 13 digits, npi exactly 10 digits), because those are the detector's contract. Their check-digit arithmetic (the mod-10 sum, and the `80840` prefix plus Luhn at `:44-59`) calls `checksum::` instead of its own copy. After S2a there is one Rust copy of each check-digit rule.
- The FFI shape, per-row `(row_index, code)` errors and the `_row_error` mapping (`execution/native/_crypto_reference.py:240-265`): reused. `fpe_checksum_unsupported` and `fpe_checksum_invalid_source` are already in `_ROW_ERROR_MESSAGES` (`:253-259`), and an unknown code already fails closed with a KeyError, so the Python side needs no new code.
- `FpeConfig.checksum`, `FpeParams.checksum`: already carried.
- `native/_operator_config_rejections.py`: the existing home for config-level declines; the one checksum rule and its predicate go there.
- The FF1 load probe in `_fpe_ext.py:200-237` (`load_compiled_fpe_kernel`) and its copy in `_companion_status.py:224-270` (`_probe_fpe_kat`): S2b extracts one probe function both call (section 5.7), instead of extending both.
- `tests/sentry/defects/_defect_scan.py` (`ModuleIndex`, `attr_chain`) and the `(path, function)` allow-set pattern of `tests/sentry/defects/test_group_by_single_reader.py`: reused by sentry K6.
- Vector tooling `decoy-engine-native/vectors/generate_fpe_kat.py` and `tests/kat_fpe.rs`: extended, not copied.

## 3. Guarantee and non-goals

After S2b:

1. A string `fpe` column with `checksum` in {luhn, npi, ean13, gtin, isbn13, vin} gets the same admission on every route as the same column without `checksum` (same namespace, key, type and `when:` rules), plus one added clause: its resolved charset is inside the scheme's native alphabet (section 5.2). A column that fails the clause declines with the existing `fpe_checksum_not_native:<column>` and runs on the oracle, as every checksum column does today.
2. On every admitting route the forward output equals the pandas oracle row for row, including nulls, and the row errors equal the oracle's (same row, same code, same order of checks). At kernel level, `decrypt_batch` equals `reference_fpe().decrypt_batch` on the same inputs (no production route calls native decrypt today; K8).
3. The check-digit arithmetic is proved by a KAT: every scheme against python-stdnum where stdnum has the scheme, and against `decoy_engine.checksums` plus published sample identifiers for npi and vin.
4. One admission rule: whether a checksum scheme is native is read from `OPERATORS["fpe"].checksum_schemes` by one predicate, `fpe_checksum_scheme_native`. The rule and the wrapper backstop both call it. A sentry proves no other function reads `checksum` to decide a route.
5. The companion refuses to load if its checksum KAT fails at import, through the one shared load probe (same fail-closed pattern as the FF1 KAT).

Non-goals: `iban` (the oracle refuses it, unchanged); non-string sources (an `int64` NPI column stays on its current route and type rules); a new scheme; Unicode normalization in Rust; text_mask `pan`/`npi` spans (S3, separate slice); changing the oracle.

## 4. Enumerations

### Exit paths (per value, kernel and oracle in the same order)

1. null: null out, no error.
2. empty string: passed through as `""`, no error, on every route (`fpe.rs:347-351`, `_crypto_reference.py:166-170`, the missing-data policy shared with the strategy). This check runs before every charset check. `fpe_unencryptable_domain` for an empty value (`transforms/fpe.py:398-406`) is transform-level behavior and is not reached at kernel scope.
3. non-preserve mode with an out-of-charset character, or preserve mode with no in-charset character: existing codes, unchanged.
4. length rule fails: `fpe_checksum_unsupported`.
5. forward only, `validate` false: `fpe_checksum_invalid_source`. Inverse skips `validate`.
6. a body character outside the scheme's permutation alphabet: `fpe_unencryptable_length` from `_permute` (`transforms/fpe.py:276-281`). Reachable in inverse mode with a wide charset (no validate runs), for example a letter in an npi body under `ALPHANUM`. Under the vin native alphabet the forward case is a lowercase VIN under a charset with lowercase letters: the oracle's `validate` uppercases and passes, then `_permute` sees the lowercase letter and returns this code. Rust does the same: ASCII uppercase inside `validate` only, the original characters into `permute`.
7. body too short for the FF1 domain (luhn with a 1-digit body): `fpe_unencryptable_domain` from the shared `permute` (`transforms/fpe.py:247-254`).
8. success: permuted body plus recomputed check digit, separators reinserted.

The per-row outcomes 4 to 7 become row errors on the native routes exactly as they are on the oracle (`execution/native/_crypto_reference.py:188-190`).

### Routes

| Route | Today | After |
|---|---|---|
| Unified slice | node unbound, table to full frame | bound, kernel (clause passes) |
| Chunked native | `FPE_CHECKSUM_NOT_NATIVE`, full frame | kernel (clause passes) |
| Sequential FK (non-key column) | `fpe_checksum_not_native`, Python | kernel (clause passes) |
| Out-of-core | `fpe_checksum_not_native`, Python | kernel (clause passes) |
| Any route, charset outside the native alphabet | as above | the existing decline, unchanged |
| Full-frame pandas | runs | unchanged |
| Companion missing or ABI mismatch | n/a | the existing companion-absent decline, unchanged |

### FK shapes

- `fpe` on an FK key column (parent, child or composite part): stays on Python on every route (`docs/compatibility-contract.md:768`); checksum does not change that. K7.
- Non-key `fpe` column on an FK parent or child table: native on sequential and out-of-core, as today without checksum. K4.

### Fields

- `checksum`: the scheme name; the only field whose native handling changes.
- `charset`: decides the native-alphabet clause; vin filters it to the VIN alphabet in configured order; the other schemes permute the body over digits.
- `preserve_separators`, `namespace`, `join_group`: unchanged.
- `validate_luhn`: ignored when `checksum` is set (`execution/native/_crypto_ext.py:183-189`, the digit-charset gate), on both paths.
- No new field.

### Output surfaces

- Masked values and their nulls.
- Row errors: `fpe_checksum_unsupported`, `fpe_checksum_invalid_source` and the existing unencryptable codes.
- The two fpe warnings (`fpe_join_group_active`, `fpe_partial_plaintext_disclosure`), computed in Python as today.
- Route evidence: `rust_companion` with `positive_kernel_evidence`.
- The companion load result (`execution/native/_fpe_ext.py:200-237`) and the companion status record (`execution/native/_companion_status.py:224-270`). Both call the one shared probe after S2b.

### Codes

No new route or runtime reason code. `FPE_CHECKSUM_NOT_NATIVE` (`reasons/route/_part1.py:128`) stays registered: it is the decline for a charset outside the native alphabet, and for any future scheme that lands declined first. The kernel returns the existing runtime codes `fpe_checksum_unsupported`, `fpe_checksum_invalid_source`, `fpe_unencryptable_length` and `fpe_unencryptable_domain` (`reasons/runtime/_part3.py:174`, `:384`) as per-row codes. The Rust code string constants get a pin test against the reason registry (K5).

## 5. Design

1. **Registry fact.** `OperatorSpec` gains `checksum_schemes: frozenset[str] = frozenset()`. The fpe spec (`execution/_operator_registry.py:277-301`) sets it to the six schemes in S2b. S1 leaves it empty.
2. **One predicate, one rule.** In `execution/native/_operator_config_rejections.py`:
   - `fpe_checksum_scheme_native(scheme: str) -> bool`: `scheme in OPERATORS["fpe"].checksum_schemes`. The only read of that field.
   - `fpe_checksum_native_charset(scheme: str, charset: str) -> bool`: every character of the resolved charset is in the scheme's native alphabet: ASCII `0-9` for luhn, npi, ean13, gtin and isbn13; ASCII `[0-9A-Za-z]` for vin. The charset is resolved through `FpeConfig._resolve()` so named charsets (`digits`, `ALPHANUM`) and custom strings take one path.
   - `fpe_checksum_rejection(column, cfg) -> str | None`: `None` when `cfg.get("checksum")` is falsy, or when both functions above are true; otherwise `fpe_checksum_not_native:<column>`.
   - The four sites in section 1 call `fpe_checksum_rejection`; `_shadow_bindings.py` keeps its `None` return when the rule rejects. The sequential gate order "checksum, namespace, config, source type" (`_sequential_native_ops.py:253`) is kept by calling the rule first.
   - Why the clause is safe: inside these ASCII alphabets, stdnum `compact`/`clean`, Python `.strip().upper()` and `\d`/`int()` are the identity or ASCII uppercase, so Rust needs no Unicode tables. Columns with a wider charset keep today's oracle route, so nothing regresses. A charset that cannot represent the scheme already fails at compile with `fpe_checksum_charset_incompatible`, so the clause only catches strict supersets (for example digits plus `-`).
3. **Wrapper.** `_fpe_ext.py:131-137` (`_CompiledFpeKernel.run`) becomes: pass `checksum` through to the kernel; the assertion is replaced by a call to `fpe_checksum_scheme_native` and `fpe_checksum_native_charset`. A caller that skips admission gets a coded whole-call error, never oracle-divergent output. No second read of the registry.
4. **FFI.** `fpe_transform_batch` gains `checksum: Option<String>` (last positional, before `native_threads`). An unknown scheme string returns a whole-call error `fpe_checksum_unknown_scheme` (the plan check catches it first; this is the backstop). `ABI_VERSION` moves to `decoy-native-abi-4` (`decoy-engine-native/src/lib.rs:57`) and `_EXPECTED_ABI_VERSION` (`execution/native/_crypto_ext.py:359`) with it. Rationale: PyO3 rejects an unknown keyword argument with a `TypeError`, so an old companion would fail at the first checksum batch, mid-run. The bump moves that failure to a clean load-time decline with the existing coded reason.
5. **Kernel (S2a, pure).** New `decoy-engine-native/src/checksum.rs` (pure, no PyO3): `validate(scheme, &[char]) -> bool`, `check_digit(scheme, &[char]) -> char`, `length_ok(scheme, n) -> bool`, plus the shared `luhn_check_digit` and `npi_check_digit`. `validate` checks the whole value (exact length, every char) and, for vin only, compares on an ASCII-uppercased copy.
6. **Kernel (S2b, dispatch).** New `decoy-engine-native/src/fpe_checksum.rs`: `checksum_permute(...)` with the oracle's steps in its order, calling `fpe::permute` on the original (not uppercased) body characters. The VIN `ResolvedConfig` is built from the configured charset filtered in configured order. `fpe_one` calls it instead of `fpe_pure_value` when a scheme is set. `fpe.rs` is 682 lines, so only the dispatch line lands there.
7. **One load probe (S2b).** Extract `fpe_load_probe(fpe_fn) -> Reason | None` in `_fpe_ext.py`. It runs `FPE_KAT[0]` and one `FPE_CHECKSUM_KAT` vector per scheme. `load_compiled_fpe_kernel` and `_companion_status.py::_probe_fpe_kat` both call it; the copied body in `_probe_fpe_kat` is removed. `FPE_CHECKSUM_KAT` lives next to `FPE_KAT` in `_crypto_ext.py`. A mismatch refuses the companion with the existing coded reason. Test `test_fpe_checksum_kat_constants_match_vectors` (in `tests/native/test_crypto_ext_loader.py`) pins every `FPE_CHECKSUM_KAT` entry to its row in `decoy-engine-native/vectors/fpe_checksum_kat.json`.
8. **Docs.** `docs/compatibility-contract.md` fpe native paragraph: checksum modes run native when the charset is inside the native alphabet. `_fpe_ext.py` and `_text_mask_native_fpe.py` module docstrings updated. abi-3 to abi-4 in `docs/native/supported-matrix.md` (lines 44 and 110) and `docs/qa/15-execution-routes-native.md:22`. Records under `docs/records/` are history and stay as written.

Design notes: one fact (the registry field), one predicate (its only reader), one rule (the rejection function), one load probe, one kernel path (the existing `permute`). Choke point: `fpe_checksum_rejection`; guard test K6; mutation that turns it red: a direct `cfg.get("checksum")` branch in `_shadow_bindings.py`.

## 6. Slices and size

| Slice | Content | Files | Lines (estimate) | Depends on | Size | Risk |
|---|---|---|---|---|---|---|
| S1 | Fold the four declines into `fpe_checksum_rejection`; add `checksum_schemes` (empty), `fpe_checksum_scheme_native` and `fpe_checksum_native_charset`; sentry K6. Behavior unchanged | `_operator_registry.py`, `_operator_config_rejections.py`, `_shadow_bindings.py`, `_real_type_admission.py`, `_sequential_native_ops.py`, `out_of_core/_fpe_native.py`, `tests/sentry/defects/test_fpe_checksum_one_rule.py`, unit tests | source about 40 net negative plus about 30 for the two functions, tests about 120 | none | 0.5 day | R1 |
| S2a | Pure Rust: `checksum.rs`, `luhn_check_digit` moved out of `fpe.rs`, `luhn_valid`/`npi_valid` call it; vector generator, `checksum_kat.json`, `kat_checksum.rs` (K1). No FFI change, no ABI bump, no Python change | `decoy-engine-native/src/{checksum.rs,fpe.rs,lib.rs (mod line),text_redact/validators.rs}`, `decoy-engine-native/vectors/{generate_checksum_kat.py,checksum_kat.json}`, `decoy-engine-native/tests/kat_checksum.rs` | Rust about 180, generator about 120, tests about 120 | none (parallel with S1) | 1 day | R1 (cargo-gated; arm64 build) |
| S2b | `fpe_checksum.rs`, FFI argument, abi-4 and the 13 pin sites, wrapper pass-through and backstop, the one load probe, registry set to six schemes, `fpe_checksum_kat.json`, K2 to K5, K7, K8, docs, changelog fragment | `decoy-engine-native/src/{fpe_checksum.rs,fpe.rs (dispatch line),arrow_ffi.rs,lib.rs}`, `decoy-engine-native/vectors/{generate_checksum_kat.py,fpe_checksum_kat.json}`, `decoy-engine-native/tests/kat_fpe.rs`, `execution/native/{_crypto_ext.py,_fpe_ext.py,_companion_status.py}`, `_operator_registry.py`, `tests/parity/test_fpe_checksum_native.py`, pin sites, docs, `changelog.d/fpe-checksum-native.md` | Rust about 160, Python about 50 net (the probe extraction removes about 40), tests about 300 | S1, S2a | 1 to 1.5 days | R2 |
| S3 (optional) | text_mask `pan` and `npi` detectors through the checksum kernel. `NATIVE_FPE_DETECTORS` decides from `fpe_checksum_scheme_native` and `fpe_checksum_native_charset`, not from the raw `checksum` element; drop the K6 allow entry for that site | `_text_mask_native_fpe.py`, `_kernels_scalar.py` caller, tests | source about 25, tests about 120 | S2b | 0.5 day | R2 |

Code gate: S1 and S2a Codex only (R1); S2b and S3 Codex and Dennis, security lens on the kernel diff.

Existing tests that assert a checksum decline flip in S2b (behavior change; names kept, each flip listed in the builder report): `tests/native/test_c6a_fpe_chunked.py`, `tests/native/test_obs2_decline_records.py` (keeps the code registered; the example becomes a digits-plus-dash charset), `tests/parity/test_phase_d_d2c_fpe_seq.py`, `tests/parity/test_phase_d_fpe_key_seq.py`, `tests/parity/test_phase_d_fpe_int_key_seq.py`, `tests/parity/test_ooc_fpe_native_routing.py`. The ABI bump and changed assertions are full-suite triggers, so S2b runs T3 on the merge head, on Linux and on the Mac (arm64 companion build). S2a runs `cargo test` (including `--no-default-features`, `native-companion.yml:298-300`) and the arm64 build.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `checksum.rs`, `fpe_checksum.rs` | `decoy-engine-native/src/` | "Native companion" (Rust kernels by concern) | `fpe.rs` |
| `kat_checksum.rs` | `decoy-engine-native/tests/` | companion tests | `kat_fpe.rs` |
| `generate_checksum_kat.py`, `checksum_kat.json`, `fpe_checksum_kat.json` | `decoy-engine-native/vectors/` | companion vectors | `generate_fpe_kat.py` |
| `test_fpe_checksum_native.py` | `tests/parity/` | cross-route parity tests | `test_ooc_fpe_native_routing.py` |
| `test_fpe_checksum_one_rule.py` | `tests/sentry/defects/` | "Sentry test" | `test_group_by_single_reader.py` |

The predicate, the charset function and the rule go into the existing `execution/native/_operator_config_rejections.py` (324 lines, room to spare). The shared probe goes into the existing `_fpe_ext.py`. No new Python source module.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | yes: scheme length, alphabet and native-charset checks | Rust checks the whole value (exact `len`, every char), never a prefix; the native-charset clause checks every charset character; K3 hostile cells | accept `n >= 10` for npi (K3 red); accept a charset when only its first character is in the alphabet (K3 dash-charset cell red) |
| 2 | Strict wire and stored types | the FFI `checksum` argument | `Option<String>` matched against a closed enum in Rust; unknown string is a coded error | map unknown to luhn (K5 red) |
| 3 | No exception context | the new coded errors | Rust codes carry no value. `_fpe_ext.py:157` raises `_translate_compiled_fpe_error(exc) from exc`: the cause chain carries the Rust `ValueError`, whose text is a code with no value, and is visible only in admin logs. Existing value-free sentries | interpolate the source value into the unknown-scheme message (sentry red) |
| 4 | Versioned read models | the vector files | each JSON file carries `schema_version` and a provenance block (generator, stdnum version, date); `kat_checksum.rs` refuses an unknown version | drop the version check (seeded old-version fixture passes, red) |
| 5 | Normalized guard scanners | sentry K6 | Built on `_defect_scan.py` (`ModuleIndex`, `attr_chain`). Scans `execution/` for any read of `checksum`: `.checksum` attribute, `["checksum"]`, `.get("checksum")`, `getattr(x, "checksum")`, and a tuple-unpack target named `checksum` (from `_resolve()` or `_FPE_CONFIG`). A target named `_checksum` or `_` is a discard, not a read. Class field declarations are not reads. Any read outside an allow set keyed by `(path, function)`, each entry with a reason, fails. The allow set belongs to this sentry only; no existing allowlist or baseline grows. Entries at `cb06f318e` after S1: the rule (`_operator_config_rejections.py` `fpe_checksum_rejection`); carriers to the kernel (`_crypto_ext.py` `FpeConfig.from_mapping`, `FpeConfig._resolve`; `_operator_params.py` `resolve_operator_params`; `_fpe_route.py` `fpe_config_from_params`; `_fpe_ext.py` `_CompiledFpeKernel.run` (backstop through the predicate), `load_compiled_fpe_kernel` (load probe; becomes `fpe_load_probe` in S2b)); carriers to the oracle (`_crypto_reference.py` `_ReferenceFpe._run`; `_strategies/_fpe.py` `FpeStrategyHandler.run`; `out_of_core/_mask_group_b.py` `fpe_array`); and `_text_mask_native_fpe.py` module level (detector table, removed by S3). The builder re-runs the scan at the slice head and lists any difference in the report | add `if cfg.get("checksum"):` to `_shadow_bindings.py` (red); the same with a `getattr` alias (red); add `_, _, _, checksum = config._resolve()` plus a branch in a new function (red) |
| 6 | No reaching into private modules | the generator and the Rust port | the generator and tests use the public `validate`/`calc_check_digit` only. `_fpe_checksum.py` imports `checksums._VIN_CHARSET`; the Rust port carries its own VIN alphabet, pinned by K1, and does not need that name | n/a |
| 7 | No hidden CI failures | Rust KAT and the Mac build | `cargo test` and `--no-default-features` run in the companion CI job; the gate records the arm64 build and `kat_checksum` result | n/a |
| 8 | One input, one trust class per entry point | `fpe_transform_batch` | one caller class (the engine wrapper); no new entry point | n/a |
| 9 | Mutations on the final head | named mutations below rerun after the last change | gate record | n/a |
| 10 | Allowlisted helpers still checked | sentry K6 allow set | each allowed `(path, function)` must still contain a read (a stale entry fails) | remove the read from `FpeConfig._resolve` (stale-entry red) |
| 11 | No raised caps | no cap raised; `fpe.rs` must not grow past its size | `fpe.rs` diff limited to the dispatch line (S2b) and the moved `luhn_check_digit` (S2a, net negative) | n/a |

### Harness defect classes (vault `30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | kernel errors and row errors | codes only, no value in any Rust or Python message | value-free sentries, K4 asserts error text | add the value to a Rust detail string (sentry red) |
| 2 | Cleanup missing on an exit path | key material in the checksum branch | the branch borrows the batch FF1 instance; no new key copy; Python `del key` path unchanged | review, existing zeroize tests | n/a |
| 3 | State and concurrency | rayon row ranges | the branch is per value and pure; batch-invariance proptest extended to checksum configs | K4b thread-count cell | share a mutable digit buffer across rows (proptest red) |
| 4 | Route parity and silent fallback | five routes, companion absent | one rule; parity per route; companion absent keeps the decline | K4, K6 | leave one old decline in place (K6 red) |
| 5 | Referential integrity | FK key fpe | stays Python | K7 | admit fpe on a key (K7 red) |
| 6 | Untrusted producer | source values (hostile identifiers) | native-charset clause plus K3 hostile corpus through kernel and oracle | K3 | skip forward validation (K3 invalid-source cells red) |
| 7 | Check then use | N/A: validation and permute run on the same in-memory value in one call | n/a | n/a | n/a |
| 8 | Weak tests | a KAT built from the kernel itself | vectors come from python-stdnum and `decoy_engine.checksums`, never from Rust output; generator refuses to run without stdnum | K1 provenance check | regenerate vectors from Rust output (provenance check red) |
| 9 | Refactor drift | S1 fold, S2a `validators.rs`, S2b probe extraction | S1 behavior-preserving (existing decline tests pass unchanged); S2a text_redact tests pass unchanged; S2b `_companion_status` tests pass unchanged | slice test runs | n/a |
| 10 | Frozen contract drift | contract fpe paragraph, ABI string | contract text, abi-4, changelog fragment `changelog.d/fpe-checksum-native.md` (format in `changelog.d/README.md`) | K5, docs review | keep abi-3 with the new argument (K5 red) |

## 9. Acceptance tests (each fails before its slice unless marked)

- **K1 check-digit KAT (S2a).** `vectors/generate_checksum_kat.py` writes, per scheme, at least 200 bodies (random, all-zero, all-nine, every leading digit, gtin at all four lengths, VIN with every letter of the VIN alphabet and lowercase variants, isbn13 with 978 and 979) with `calc_check_digit` and `validate` from python-stdnum (luhn, ean13, gtin, isbn13) or `decoy_engine.checksums` (npi, vin). npi and vin also carry published samples: the CMS example NPI `1234567893` and the NHTSA example VIN `1M8GDM9AXKP042788`. `kat_checksum.rs` asserts Rust equals every row. The existing `text_redact::tests::validators_match_the_reference_vectors` (`decoy-engine-native/src/text_redact/tests.rs:20-29`) must stay green and is the text_redact witness for the shared NPI and Luhn code. Fail-before: the module does not exist.
- **K2 end-to-end FPE KAT (S2b).** `fpe_checksum_kat.json` holds, per scheme, 50 valid identifiers with separators and without, masked forward and inverse by the Python oracle under a fixed key and tweak. VIN rows run under `ALPHANUM` and under a custom charset in non-sorted order (for example `"ZYXWVUTSRPNMLKJHGFEDCBA9876543210"`), so the filtered order is pinned. `kat_fpe.rs` and the shared load probe reproduce them. Fail-before: the FFI has no checksum argument.
- **K3 hostile corpus (S2b).** For each scheme, kernel and oracle on the same column, forward and inverse: wrong length by one each way, a bad check digit, a trailing newline, leading and trailing separators, empty string (passes through as `""`), null, a luhn value of 2 characters (domain floor), a VIN with I/O/Q, a lowercase VIN under `ALPHANUM` (both give `fpe_unencryptable_length`), an npi value with a leading digit other than 1 or 2, and inverse inputs with a letter in the body under `ALPHANUM` (both give `fpe_unencryptable_length`). Assert identical output and identical `(row, code)` row errors. Admission cells: gtin and ean13 with charset `"0123456789-"`, and npi with `ALPHANUM`, decline with `fpe_checksum_not_native:<column>` on every route and the output equals the oracle. Fail-before: no native path.
- **K4 route parity (S2b).** Each scheme, deterministic namespace, 2,000 rows (unified slice) and 120,000 rows in three or more chunks (chunked native), plus sequential and out-of-core two-table jobs on a non-key column: route evidence is the companion and the output equals the forced full-frame oracle as an Arrow table (schema included) and by output hash; row errors equal. K4b: `native_threads` 1 and 4 give the same bytes. Fail-before: declined.
- **K5 ABI, unknown scheme and codes (S2b).** A companion reporting abi-3 is refused with the existing reason; `fpe_transform_batch(..., checksum="ibna")` returns `fpe_checksum_unknown_scheme`; every Rust per-row code string is a registered runtime reason code (pin test against the reason registry). Fail-before: abi-3 accepted.
- **K6 one rule (S1).** Sentry `test_fpe_checksum_one_rule.py` (section 8 row 5), with seeded spellings as in `test_group_by_single_reader.py::test_seeded_spellings_are_found`. Fail-before: four decision reads exist.
- **K7 FK key (S2b).** `fpe(checksum: npi)` on an FK key column declines exactly as non-checksum fpe does. Unchanged-behavior control.
- **K8 inverse at kernel level (S2b).** `_CompiledFpeKernel.decrypt_batch` equals `reference_fpe().decrypt_batch` on the K2 outputs (returns the sources) and on the K3 inverse corpus (same values, same row errors). No production route calls native decrypt; this pins the kernel for when one does.

Named mutations (record the head): swap the npi prefix `80840` for `80804` (K1 red and `validators_match_the_reference_vectors` red); skip forward validation (K3 red); drop VIN charset filtering (K2 vin red); sort the filtered VIN charset (K2 custom-order vin red); uppercase the VIN body before `permute` (K3 lowercase-VIN cell red); drop the native-charset clause (K3 admission cells red); return `fpe_checksum_unsupported` for the domain-floor case (K3 red); leave the chunked decline in place (K6 and K4 red); keep abi-3 (K5 red).

Performance evidence (performance.md): the audit probe (`fpe(checksum: npi)` at 120,000 rows) and a 1,000,000-row run, three runs each on the Dell node through `vm-run`, before and after, wall time and peak RSS; expected close to the non-checksum 0.8 s per 120,000 rows. Numbers go in the S2b PR body.

## 10. Frozen contracts and byte changes

No masked value changes on any route (K4 compares against the unchanged oracle). Named changes:

1. **B1.** Checksum columns with a native-alphabet charset move from the full-frame oracle to the native routes, so on unified slice and chunked an empty or all-null column takes the native routes' type rules (the fpe `tokenizing` assembly, `execution/_operator_registry.py:287-291`) instead of the pandas one. Same reconciliation as non-checksum fpe today.
2. **B2.** Companion ABI `decoy-native-abi-3` to `decoy-native-abi-4`: an older companion wheel no longer loads with a newer engine (it never shipped separately; the CLI bundles both). abi-4 belongs to this row alone: TEXT-REDACT-RUST-SPLICE revision 2 (`12263071f`) does not bump the ABI.

Fragment first line: `Breaking: fpe with a checksum scheme (luhn, npi, ean13, gtin, isbn13, vin) now runs in the native companion on every route when its charset is ASCII digits (ASCII letters and digits for vin), and the companion ABI is now decoy-native-abi-4.`

`SEED_PROTOCOL_VERSION`, plan serialization and digests do not change.

Public signatures (engine #763 sentry, `tests/sentry/release/test_public_signatures.py`): no public Python signature changes. `OperatorSpec` is private and the new field has a default; the FFI is not a public Python surface. `tests/sentry/baselines/signature-exemptions.json` is not touched. The Breaking line above still goes in the fragment because of B1 and B2.

ABI pin sites S2b updates to the new tag (13 besides `lib.rs`): `decoy-engine-native/scripts/parity_smoke.py`, `execution/native/_crypto_ext.py`, `tests/native/{test_c6c_ii_text_redact_rust.py,test_crypto_ext_loader.py,test_group_key_ext.py,test_index_ext.py,test_native_ext_abi.py}`, `tests/parity/{test_ooc_fpe_native_real.py,test_ooc_text_redact_native_real.py,test_phase_d_d1a_hash_native.py,test_phase_d_d1b1_bucket_native.py,test_phase_d_d1b2_categorical_native.py,test_phase_d_dcomp_composite_ooc_real.py}`. Current docs: `docs/native/supported-matrix.md:44`, `:110`, `docs/qa/15-execution-routes-native.md:22`.

CLI follow-up (not this row): the CLI tests `tests/unit/test_distribution.py:266-267` and `tests/unit/test_distribution_acceptance.py:285-287` hard-code abi-3. The CLI pin bump that picks up S2b follows the engine repin checklist and updates them.

## 11. Pre-mortem

- A Rust check digit differs from stdnum on an edge (gtin-8 weights, ISBN-13 prefix). K1 covers every length and leading digit; a mismatch fails the companion at load, never output.
- VIN fallback: a charset with fewer than two VIN characters falls back to digits in the oracle. K2 includes a digits-only charset VIN.
- Oracle input normalization (stdnum `compact`, Unicode upper, `\d`). Handled by the native-charset clause (section 5.2), not by tests finding edge cases. K3 admission cells prove the clause declines a wider charset.
- A builder grows the K6 allow set to get green. The set is keyed by `(path, function)` with a reason per entry; the gate diffs it against section 8 row 5 and any new entry needs a stated reason in the PR.
- The arm64 Mac build fails on a new module. S2a builds on the Mac before merge.
- Another row bumps the ABI first. If any row merges abi-4 before S2b, S2b takes the next tag and updates the same pin sites; the builder merges main and re-runs K5 before the gate. No tag is reused.

## 12. Owner questions

None blocking. S3 (text_mask `pan`/`npi`) is in scope by default; say if it should wait.

## 13. Deferred (V2-LOG)

- **V2-LOG:** native checksum fpe on `int64` sources (needs a typed output contract).
- **V2-LOG:** `iban` FPE with per-country BBAN structure.
- **V2-LOG:** native checksum fpe for charsets wider than the native alphabet (needs a ported, KAT-locked Unicode normalization).
