Status: plan (revision 4, 2026-11-24; Codex round 1 fixes applied; anchored to engine main `cb06f318e`)

# FPE-CHECKSUM-NATIVE: checksum-mode `fpe` runs in the Rust companion

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: FPE-CHECKSUM-NATIVE (group mask; V1 fast-path audit, vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`). Engine and its Rust companion `decoy-engine-native/`. The CLI gets it through its next engine pin bump.

Anchors: a path with no prefix is under `src/decoy_engine/`; `native/` paths under `decoy-engine-native/` are named in full. Read at engine `origin/main` `cb06f318e`. Must stay consistent with `plan/route-label-truth`, `plan/per-column-routing`, `plan/native-threads-default`, `plan/when-reads-source` and `plan/text-redact-rust-splice`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: R2 (crypto output on a reversible strategy; a companion ABI bump; four admission copies fold into one). Plan review: Dennis, then Codex. Code gate per slice in section 6.

Owner direction (2026-11-22): every strategy runs its fastest path by default; faster and more robust wins even when bytes change, and every byte change is named; output stays deterministic per seed. Engine-gap deadline 2026-12-15.

Revision 3 changes (Dennis round 1): charset-alphabet clause in the one rule (H1); one predicate and a `(path, function)` sentry (H2); one shared load probe (H3); `npi_valid` reuses the shared NPI arithmetic (H4); exit paths corrected (M1); inverse proved at kernel level (M2); VIN charset order (M3); S2 split into S2a and S2b (M4); S3 uses the predicate (M5); LOW items 1 to 8.

Revision 4 changes (Codex round 1): payload-only admission, batch cipher radix, guarded load probe and span ABI. Split out the Rust batch slice. Pin rejection order, detector behavior, schema and oracle vectors.

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

The oracle's `validate` normalizes before it checks. ean13, gtin and isbn13 call stdnum `compact` (`clean(number, ' -').strip()`, and `clean` maps Unicode digits to ASCII). vin runs `value.strip().upper()` with Python's Unicode upper (`'ſ'.upper() == 'S'`). npi uses `^\d{10}\Z` and `int(ch)`, so the body can contain Unicode decimal digits. The leading 1 or 2 and the check digit must match ASCII. The plan check accepts a charset that is a superset of the scheme alphabet (`plan/_checks.py:476-479`), so a wide charset can carry characters such as `-` or lowercase letters to `validate`.

Porting that normalization to Rust would need stdnum's Unicode digit table and Python's Unicode case mapping, kept in sync by hand. This plan does not port it. Section 5.2 admits the native path only when the resolved charset is inside an ASCII alphabet where every one of those normalizations is the identity or ASCII uppercase. Parity then holds by construction.

## 2. Established solutions

Search run: Rust crates for check digits (`luhn`, `luhn3`, `checkdigit`, `isbn`, `vin`), how python-stdnum structures `calc_check_digit`/`validate`, and how other FPE products handle checksum identifiers (Voltage SecureData and Protegrity "Luhn-preserving" tokens, NIST SP 800-38G rev1 remarks on format constraints).

- Products keep the check digit outside the FF1 domain: encrypt the body, recompute the check digit. The engine already does this; the port keeps the method.
- The crates each cover one scheme, carry their own input rules (for example accepting separators or lowercase), and none covers NPI's `80840` prefix rule or the engine's VIN fallback. Adding five dependencies to replace about 120 lines of fixed arithmetic would widen the supply chain for no gain, and the KAT, not the crate, is what proves parity. Decision: a small pure Rust module `checksum.rs` with one function pair per scheme, each citing its standard in the doc comment (stdnum algorithm, GS1 General Specifications 7.9 for EAN/GTIN mod-10, ISO 2108 for ISBN-13, CMS NPI check digit, 49 CFR 565.15 for VIN), KAT-locked against python-stdnum and `decoy_engine.checksums`.

### Reuse inventory

- `fpe.rs::permute`, `ResolvedConfig`, `fpe_one` and the per-row code channel: reused; the checksum branch shares one permutation config and its matching FF1 instance across the batch. Section 5.6 pins the radix.
- `fpe.rs::luhn_check_digit` (`:137`): moves into `checksum.rs` and is called from both places.
- `text_redact/validators.rs:13` `luhn_valid` and `:37-60` `npi_valid`: each keeps its detector input rules (strip whitespace and dashes; luhn at least 13 digits, npi exactly 10 digits), because those are the detector's contract. Their check-digit arithmetic (the mod-10 sum, and the `80840` prefix plus Luhn at `:44-59`) calls `checksum::` instead of its own copy. After S2a there is one Rust copy of each check-digit rule.
- The FFI shape, per-row `(row_index, code)` errors and the `_row_error` mapping (`execution/native/_crypto_reference.py:240-265`): reused. `fpe_checksum_unsupported` and `fpe_checksum_invalid_source` are already in `_ROW_ERROR_MESSAGES` (`:253-259`), and an unknown code already fails closed with a KeyError, so the row-error mapping needs no new entries.
- `FpeConfig.checksum`, `FpeParams.checksum`: already carried.
- The checksum decision belongs with existing config-level declines in `execution/native/_operator_config_rejections.py`.
- The FF1 load probe in `_fpe_ext.py:200-237` (`load_compiled_fpe_kernel`) and its copy in `_companion_status.py:224-270` (`_probe_fpe_kat`): S2b extracts one probe function both call (section 5.7), instead of extending both.
- `tests/sentry/defects/_defect_scan.py` (`ModuleIndex`, `attr_chain`) and the `(path, function)` allow-set pattern of `tests/sentry/defects/test_group_by_single_reader.py`: reused by sentry K6.
- Follow the existing vector layout in `decoy-engine-native/vectors/generate_fpe_kat.py`. Use one generator for the two new corpora and extend `decoy-engine-native/tests/kat_fpe.rs` for batch vectors.

## 3. Guarantee and non-goals

After S2b:

1. An otherwise eligible string payload column runs native for luhn, npi, ean13, gtin, isbn13 or vin when its resolved charset passes section 5.2. Other route gates still apply. A checksum on an FK key or an unsupported checksum configuration retains the checksum decline.
2. Successful jobs match the pandas oracle in values, nulls, order and schema. A failing job raises the first row failure and publishes no failed table. At kernel level both directions match the reference values and ordered row errors (K3, K4, K8).
3. The check-digit arithmetic is proved by a KAT: every scheme against python-stdnum where stdnum has the scheme, and against `decoy_engine.checksums` plus published sample identifiers for npi and vin.
4. The four routes, the wrapper backstop and detector eligibility in S3 use the same checksum decision. Only that function reads the registry field. K6 checks its callers and the use of the scheme inside each carrier.
5. A failed FPE smoke vector makes the FPE loader refuse the kernel and the overall status report failure. Per-kernel availability still reports the other kernels independently.

Non-goals: `iban` (the oracle refuses it, unchanged); FK key checksum columns; non-string payload sources (an `int64` NPI column stays on its current route and type rules); a new scheme; Unicode normalization in Rust; text_mask `pan`/`npi` spans (S3, separate slice); changing the oracle.

## 4. Enumerations

### Exit paths (per value, kernel and oracle in the same order)

1. null: null out, no error.
2. empty string: passed through as `""`, no error, on every route (`fpe.rs:347-351`, `_crypto_reference.py:166-170`, the missing-data policy shared with the strategy). This check runs before every charset check. `fpe_unencryptable_domain` for an empty value (`transforms/fpe.py:398-406`) is transform-level behavior and is not reached at kernel scope.
3. non-preserve mode with an out-of-charset character, or preserve mode with no in-charset character: existing codes, unchanged.
4. length rule fails: `fpe_checksum_unsupported`.
5. Forward validation fails: `fpe_checksum_invalid_source`. Inverse skips validation.
6. FF1 checks the permutation config, then the domain floor, maximum body length and tweak length before body membership (`transforms/fpe.py:247-281`). A valid-check-digit Luhn input of total length 6 fails with `fpe_unencryptable_domain`. Lengths 7 and 257 succeed. Length 258 fails with `fpe_unencryptable_length`.
7. A body character outside the permutation alphabet gives `fpe_unencryptable_length`. Under VIN with `ALPHANUM`, a lowercase body letter can pass validation and fail permutation. Lowercase `x` in the check slot of `1M8GDM9AxKP042788` succeeds. The slot is excluded from permutation and recomputed. Inverse returns `1M8GDM9AXKP042788`.
8. success: permuted body plus recomputed check digit, separators reinserted.

The batch returns all row errors in input order. The job adapter raises the first error (K4).

### Routes

The native entries below assume an otherwise eligible string payload column. FK key handling follows the table.

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

- Sequential FPE can mask string and fixed-width integer FK keys and mint REMAP orphans using the parent config (`execution/_sequential_native_ops.py:280-298,542-552`). With checksum set, the key context keeps parent masking and orphan minting on Python. Matched children inherit parent tokens. K7 covers the disposition.
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

No new route or runtime reason code. `FPE_CHECKSUM_NOT_NATIVE` (`reasons/route/_part1.py:128`) stays registered: it is the decline for a checksum on a key, a charset outside the native alphabet, and for any future scheme that lands declined first. The kernel returns the existing runtime codes `fpe_checksum_unsupported`, `fpe_checksum_invalid_source`, `fpe_unencryptable_length` and `fpe_unencryptable_domain` (`reasons/runtime/_part3.py:174`, `:384`) as per-row codes. The Rust per-row code strings get a pin test against the keys of `_ROW_ERROR_MESSAGES` (`_crypto_reference.py:240-265`), the table the wrapper maps them through (K5).

## 5. Design

1. **Registry fact.** `OperatorSpec` gains `checksum_schemes: frozenset[str] = frozenset()`. The fpe spec (`execution/_operator_registry.py:277-301`) sets it to the six schemes in S2b. S1 leaves it empty.
2. **One checksum decision.** Put `fpe_checksum_rejection(column, scheme, resolved_charset, *, context) -> str | None` in `execution/native/_operator_config_rejections.py`. A thin mapping adapter, `fpe_checksum_config_rejection`, reads the scheme, resolves the charset and forwards both with the route context. Export the adapter through the native package for callers outside it.
   - An absent scheme passes. For a present scheme, decline a key context first. Then require membership in `OPERATORS["fpe"].checksum_schemes` and check every symbol in the resolved charset. Numeric schemes allow ASCII digits. VIN allows ASCII digits and letters. Return the existing `fpe_checksum_not_native:<column>` reason on rejection. This function owns all three checks.
   - Routes resolve the charset name or literal with the non-raising `transforms.fpe.resolve_fpe_charset` (default `digits`). Full config validation stays at its existing gate. The wrapper can pass the already resolved charset. Inside the admitted alphabets the oracle normalization needs only ASCII operations.
   - Replace the four checks in section 1 at their current positions. Keep the chunked coded decline and the unified unbound result. Pass payload or key context from `_fpe_admit` and `_fpe_key_admit` into `_fpe_config_reason`. REMAP uses the parent decision. Keep the other routes’ FK eligibility rules.
   - Pin sequential and out-of-core precedence: checksum rejection, missing namespace, invalid config, then source type. With Luhn, charset `aab`, no namespace and a bad type, return the checksum reason without raising. For a payload with duplicate digit charset `00123456789`, the missing namespace wins. Supply the namespace and the config error wins. A checksum key declines even with an eligible alphabet.
   - The text span context uses this decision in S3. Keep its detector-specific gates (digit preset, emitted detector, selected FPE strategy and ASCII span).
3. **Wrapper.** Replace the checksum assertion at `_CompiledFpeKernel.run:131` with the shared decision in payload context. On refusal raise a value-free whole-call error with the checksum decline code before FFI. On success forward the resolved scheme unchanged. A wrapper call has no FK identity. The key gate runs at route admission.
4. **FFI.** `fpe_transform_batch` gains `checksum: Option<String>` as a keyword-only argument with PyO3 default `checksum=None` after `native_threads=None`. Existing plain FF1 calls may omit it. In S3, `encrypt_spans` unpacks the charset and scheme from `_FPE_CONFIG[det_id]` and passes `checksum=scheme` to this raw call. An unknown scheme string returns a whole-call error `fpe_checksum_unknown_scheme` (the plan check catches it first; this is the backstop). `ABI_VERSION` moves to `decoy-native-abi-4` (`decoy-engine-native/src/lib.rs:57`) and `_EXPECTED_ABI_VERSION` (`execution/native/_crypto_ext.py:359`) with it. Rationale: PyO3 rejects an unknown keyword argument with a `TypeError`, so an old companion would fail at the first checksum batch, mid-run. The bump moves that failure to a clean load-time decline with the existing coded reason.
5. **Kernel (S2a, pure).** New `decoy-engine-native/src/checksum.rs` (pure, no PyO3): `validate(scheme, &[char]) -> bool`, `check_digit(scheme, &[char]) -> char`, `length_ok(scheme, n) -> bool`, plus the shared `luhn_check_digit` and `npi_check_digit`. `validate` checks the whole value (exact length, every char) and, for vin only, compares on an ASCII-uppercased copy.
6. **Kernel (S2b-core).** Keep separator extraction, strict outer membership and reinsertion on the configured charset. In `fpe_checksum.rs`, prepare the permutation alphabet for the batch: canonical `0123456789` for numeric schemes, or configured-order VIN filtering with the oracle fallback. Build the symbol map, `ResolvedConfig` and FF1 with that same alphabet and radix. For VIN under `ALPHANUM` the radix is 33. Derive the key once. Construct the cipher once per batch and borrow it in each row range. Pass original body characters to the existing `fpe::permute`. Wire this through `fpe_transform_array`, `fill_range` and `fpe_one`. Keep plain FF1 on its existing alphabet. Put checksum logic in `fpe_checksum.rs` and keep `fpe.rs` at or below 700 lines.
7. **One load probe (S2b).** Extract `fpe_load_probe(kernel)` in `_fpe_ext.py`. Guard symbol lookup, vector setup, invocation, unpacking and result inspection, including `len(errors)`. On success return the tested callable. On exception return `load-error` and the original exception. On a completed mismatch return `kat-corrupt`. The loader raises `CryptoExtensionUnavailableError` on either failure and chains the original exception when present. The status adapter preserves the exception for `load-error` and supplies its existing `NativeCompanionCheckError` with reason and ABI fields for a mismatch. Both status and per-kernel availability use this adapter. Pass the tested callable to the wrapper. Probe ordinary `FPE_KAT[0]` and six checksum vectors, one per scheme. Keep `FPE_CHECKSUM_KAT` beside `FPE_KAT`. Pin all six entries to their generated JSON rows and exercise both consumers (K5). Match a one-row Arrow string array, the exact ciphertext and an empty error sequence.
8. **Docs.** `docs/compatibility-contract.md` fpe native paragraph: document eligible checksum payloads and correct the FK key and REMAP claim at line 768 using section 4. `_fpe_ext.py` and `_text_mask_native_fpe.py` module docstrings updated. abi-3 to abi-4 in `docs/native/supported-matrix.md` (lines 44 and 110) and `docs/qa/15-execution-routes-native.md:22`. Records under `docs/records/` are history and stay as written.

Design notes: the registry owns the scheme set. The decision owns admission. Carrier code forwards the scheme. K6 fails on a private decision inside any carrier and on a second registry reader. Both loader contracts use one probe. Both FF1 paths use the existing permutation.

## 6. Slices and size

| Slice | Content | Files | Lines (estimate) | Depends on | Size | Risk |
|---|---|---|---|---|---|---|
| S1 | Fold four route checks and the wrapper backstop into the decision. Add the empty registry field and K6. Preserve current declines | registry, four sites in section 1, native facade, rejection module, wrapper, routing sentry and unit tests | source about 60, tests about 150 | none | 0.75 day | R1 |
| S2a | Share arithmetic in `checksum.rs`. Move the existing Luhn helper. Keep detector acceptance rules and exercise detector-only NPI redaction (K1) | companion `src/{checksum.rs,fpe.rs,lib.rs,text_redact/validators.rs,text_redact/tests.rs}`, existing native text-redact suite, CODEMAP, generator, `checksum_kat.json`, `kat_checksum.rs` | Rust about 180, generator and tests about 240 | none (independent of S1) | 1 day | R2 |
| S2b-core | Implement the pure batch path and both-direction K2 vectors. Keep Python admission closed and abi-3. Existing FFI passes no scheme to the Rust batch | companion `src/{fpe_checksum.rs,fpe.rs,lib.rs,arrow_ffi.rs}`, generator, `fpe_checksum_kat.json`, `tests/kat_fpe.rs` | Rust about 160, generator and tests about 130 | S2a | 1 day | R2 |
| S2b | Expose the keyword, bump ABI and pins, wire wrapper and probe, enable six schemes together. Run K3 to K8, T3 and performance gate | FFI, registry, wrappers, loader/status and route suites, new parity module, section 10 pins, contract and fragment | source about 70 net, tests about 300 plus pin and doc edits | S1, S2b-core | 1 builder-day plus gate runs | R2 |
| S3 | Enable PAN and NPI span masking. Derive detector eligibility through the decision. Forward the scheme to FFI. Replace exclusion assertions with exact oracle bytes and observed span counts | `_text_mask_native_fpe.py`, K6, `tests/native/test_c6b_ii_c_text_mask_fpe.py` | source about 25, tests about 100 | S2b | 0.5 day | R2 |

Code gate: S1 Codex (R1). S2a, S2b-core, S2b and S3 Codex and Dennis (R2). S2a changes shipped redaction. Run Rust tests with and without default features and the arm64 build on both Rust slices. S2b runs T3 on the Linux and Mac merge head. Gate ABI exposure and admission together.

S2b updates the eligible payload expectations in `tests/native/{test_c6a_fpe_chunked.py,test_obs2_decline_records.py}`, `tests/parity/{test_phase_d_d2c_fpe_seq.py,test_ooc_fpe_native_routing.py}` and `tests/physical/test_shadow_fpe.py:439`. Keep a wide-charset decline and the later type decline where applicable. Preserve unknown and IBAN refusal cases. Retain both checksum-key decline tests (K7). S3 updates the PAN/NPI exclusion and mixed-span tests at `tests/native/test_c6b_ii_c_text_mask_fpe.py:196-224`. Assert valid PAN/NPI spans run natively with zero Python fallback. Use one distinct valid PAN, NPI and plain phone span. Expect three accepted kernel rows and no fallback. Run NPI-only `3234567899` with the redact policy. Expect one attempted kernel row, zero accepted, one Python fallback, one notice and the oracle redaction. Check the oracle bytes and notices for both jobs.

## 7. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `checksum.rs`, `fpe_checksum.rs` | `decoy-engine-native/src/` | new companion source row | `fpe.rs` |
| `kat_checksum.rs` | `decoy-engine-native/tests/` | new companion tests row | `kat_fpe.rs` |
| `generate_checksum_kat.py`, `checksum_kat.json`, `fpe_checksum_kat.json` | `decoy-engine-native/vectors/` | new companion vectors row | `generate_fpe_kat.py` |
| `test_fpe_checksum_native.py` | existing `tests/parity/native/` | CODEMAP:164,306 | `test_keyed_hash_parity.py` |
| `__init__.py`, `test_fpe_checksum_one_rule.py` | new `tests/sentry/defects/routing/` | CODEMAP:295, recurring defects | parent guard `test_group_by_single_reader.py` |
| `fpe-checksum-native.md` | `changelog.d/` | CODEMAP:301 | `README.md` |

Add the Rust companion source, integration-test and vector directories to CODEMAP’s placement map with the first new files. The decision and probe extend existing modules. Run `pytest tests/sentry/defects/routing/test_fpe_checksum_one_rule.py` from S1 and `pytest tests/parity/native/test_fpe_checksum_native.py` with the companion from S2b. The companion-present CI selects `tests/parity/native/` at `.github/workflows/native-companion.yml:402`.

## 8. Class table (catalog `recurring-defects.md`)

| # | Class | Applies | Structure and proof | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Anchored validation | yes: scheme length, alphabet and native-charset checks | Rust checks the full scheme length rule and every character, never a prefix; the native-charset clause checks every charset character; K3 hostile cells | accept `n >= 10` for npi (K3 red); accept a charset when only its first character is in the alphabet (K3 dash-charset cell red) |
| 2 | Strict wire and stored types | the FFI `checksum` argument | `Option<String>` matched against a closed enum in Rust; unknown string is a coded error | map unknown to luhn (K5 red) |
| 3 | No exception context | the new coded errors | Rust codes carry no value. `_fpe_ext.py:157` raises `_translate_compiled_fpe_error(exc) from exc`: the cause chain carries the Rust `ValueError`, whose text is a code with no value, and is visible only in admin logs. Existing value-free sentries | interpolate the source value into the unknown-scheme message (sentry red) |
| 4 | Versioned read models | the vector files | both new JSON files carry a required schema version and provenance. Each Rust reader rejects a missing or unknown version | drop the version check (seeded old-version fixture passes, red) |
| 5 | Normalized guard scanners | K6 over `execution/` | Reuse `ModuleIndex` and `attr_chain`. Normalize import and local aliases, attribute, subscript, mapping get, literal `getattr`, and unpacking from `_resolve()` or `_FPE_CONFIG`. Follow the bound scheme into its uses. Ignore unused discards and field declarations. Pin exact reader and caller identities and allowed uses below | seed each spelling, a second registry read, a missing decision call and a branch inside a listed carrier |
| 6 | No reaching into private modules | the generator and the Rust port | the generator uses public checksum and FPE transforms for expected values. `_fpe_checksum.py` imports `checksums._VIN_CHARSET`; the Rust port carries its own VIN alphabet, pinned by K1, and does not need that name | n/a |
| 7 | No hidden CI failures | Rust KAT and the Mac build | `cargo test` and `--no-default-features` run in the companion CI job; the gate records the arm64 build and `kat_checksum` result | n/a |
| 8 | One input, one trust class per entry point | `fpe_transform_batch` | engine-controlled kernel arguments from column, probe and span callers; source text remains row input | K3, K5 and S3 |
| 9 | Mutations on the final head | named mutations below rerun after the last change | gate record | n/a |
| 10 | Allowlisted helpers still checked | K6 | Check callers of both the mapping adapter and the decision. Check each carrier forwards the same scheme to its declared destination. Fail on missing or extra uses, even inside a listed function | replace the forwarded scheme with `None` or branch on `params.checksum` in `fpe_config_from_params`; both fail |
| 11 | No raised caps | Rust batch wiring | Keep `fpe.rs` within 700 lines. Put the checksum preparation and permutation in `fpe_checksum.rs` | n/a |

K6 keys each entry by path and qualified function (module scope for the detector table). Check both missing and unexpected edges. Normalize imports through the native facade.

- Only `_operator_config_rejections.py::fpe_checksum_rejection` reads `checksum_schemes`. Its callers are the mapping adapter in that file, `_fpe_ext.py::_CompiledFpeKernel.run`, and the detector table in S3. Require each decision result to govern the existing decline, refusal or eligibility outcome.
- Only the four route sites in section 1 call the mapping adapter. Check that it forwards the input scheme and context unchanged. Pin the key and payload context at the two sequential callers.
- Kernel carriers are `_crypto_ext.py::FpeConfig.from_mapping` and `FpeConfig._resolve`, `_operator_params.py::resolve_operator_params`, `_fpe_route.py::fpe_config_from_params`, and `_fpe_ext.py::_CompiledFpeKernel.run`. Pin scheme delivery to the config, params, result tuple, decision and (from S2b) FFI keyword. Permit the existing absent-to-None default and the separate `validate_luhn` calculation. Reject added branches, substitutions or early exits on the scheme, including the old wrapper assertion.
- Oracle carriers are `_crypto_reference.py::_ReferenceFpe._run`, `_strategies/_fpe.py::FpeStrategyHandler.run` and `out_of_core/_mask_group_b.py::fpe_array`. Pin forwarding into their value transforms. The ordinary probe in `_fpe_ext.py::load_compiled_fpe_kernel` checks absence in S1. Replace that use in S2b with forwarding the vector scheme in `fpe_load_probe`.
- Until S3, pin the existing plain-digit restriction at module scope in `_text_mask_native_fpe.py`. In S3 replace its checksum test with the shared decision. Add exactly one forwarding read in `encrypt_spans` for the raw FFI keyword. Seed a direct `OPERATORS["fpe"].checksum_schemes` lookup, a carrier conditional, a skipped decision and an unexpected helper caller. Each must fail independently.

### Harness defect classes (vault `30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`)

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | kernel errors and row errors | codes only, no value in any Rust or Python message | value-free sentries, K4 asserts error text | add the value to a Rust detail string (sentry red) |
| 2 | Cleanup missing on an exit path | key material in the checksum branch | the branch borrows the FF1 instance for the batch permutation alphabet; no new key copy; Python `del key` path unchanged | review, existing zeroize tests | n/a |
| 3 | State and concurrency | rayon row ranges | the branch is per value and pure; batch-invariance proptest extended to checksum configs | K4b thread-count cell | share a mutable digit buffer across rows (proptest red) |
| 4 | Route parity and silent fallback | five routes, companion absent | one rule; parity per route; companion absent keeps the decline | K4, K6 | leave one old decline in place (K6 red) |
| 5 | Referential integrity | checksum FK keys | parent and REMAP mint stay on Python | K7 | pass payload context for a checksum key (K7 red) |
| 6 | Untrusted producer | source values (hostile identifiers) | native-charset clause plus K3 hostile corpus through kernel and oracle | K3 | skip forward validation (K3 invalid-source cells red) |
| 7 | Check then use | N/A: validation and permute run on the same in-memory value in one call | n/a | n/a | n/a |
| 8 | Weak tests | independent expected bytes | fix the generator seed, key, tweak inputs and row order. Regenerate both vector payloads from the Python oracle and compare every field of the vector rows with the committed files | K1 and K2 regenerate before Rust checks the complete corpora | alter a committed expected byte with provenance intact (comparison red) |
| 9 | Refactor drift | S1 fold, S2a `validators.rs`, S2b probe extraction | S1 behavior-preserving (existing decline tests pass unchanged); S2a pins both NPI outcomes. S2b updates the success fake and pins both probe contracts | slice test runs | n/a |
| 10 | Frozen contract drift | contract fpe paragraph, ABI string | contract text, abi-4, changelog fragment `changelog.d/fpe-checksum-native.md` (format in `changelog.d/README.md`) | K5, docs review | keep abi-3 with the new argument (K5 red) |

## 9. Acceptance tests (each fails before its slice unless marked)

- **K1 check-digit KAT (S2a).** Generate at least 200 bodies per scheme. Cover all-zero, all-nine, leading digits, all GTIN lengths, ISBN prefixes 978 and 979, and every VIN letter. Compute the VIN check character on an uppercase body before varying case in the validation input. Use the Python scheme oracle and stdnum where applicable. Include `1234567893` and `1M8GDM9AXKP042788`. Regenerate and compare the payloads as in section 8. Rust checks every row. Share the GS1 mod-10 routine across EAN, GTIN and ISBN. Keep the existing detector vectors and add `3234567899`: `npi_valid` accepts it, NPI-only native text redaction maps `id 3234567899 end` to `id <X> end` with token `<X>` in `tests/native/test_c6c_ii_text_redact_rust.py`, and FPE NPI validation rejects it. Mutating `npi_valid` to call the full FPE validator must fail the redaction test.
- **K2 end-to-end FPE KAT (S2b-core).** Generate 50 valid identifiers per scheme, with and without separators. Record the mask key, namespace, tweak framing, config, Python ciphertext and exact Python inverse. Use canonical and reversed digit charsets. Run VIN under `ALPHANUM` and `ZYXWVUTSRPNMLKJHGFEDCBA9876543210`. Include the lowercase check-slot case from section 4. Regenerate the payloads deterministically. In `kat_fpe.rs` run the full corpus through production `fpe_transform_array` in both directions. A direct call to the FF1 crate would miss a batch wiring error. The loader samples six forward rows in S2b.
- **K3 hostile corpus (S2b).** Compare native and reference kernel values and complete ordered `(row, code)` vectors on mixed success, null, empty and failing rows, forward and inverse. Exercise one below and above each fixed length, each GTIN length, Luhn lengths 1 and 2, bad check digits, trailing newline and leading and trailing separators with preservation on and off. Use valid Luhn checks at total lengths 6, 7, 257 and 258 (section 4). Include `3234567899` for forward NPI refusal. Under VIN `ALPHANUM`, test I/O/Q in the body and the lowercase body letter in `1m8GDM9AXKP042788` separately from the successful lowercase check slot. Inverse skips validation and still checks body membership. For GTIN/EAN13 with `0123456789-` and NPI with `ALPHANUM`, assert the four route declines in their own representations and oracle job output on valid data. Direct wrapper calls refuse the entire config before FFI.
- **K4 route parity (S2b).** For each scheme run 2,000 rows on unified slice, 120,000 rows in at least three native chunks, and sequential and out-of-core two-table jobs with a payload column. On successful populated jobs require positive companion evidence, matching output hash and exact Arrow table equality including schema. Extend `tests/physical/test_shadow_fpe.py:162-181` and `tests/native/test_c6a_fpe_chunked.py:113-142` to checksum configs. On the assembled unified and pandas legs, pin zero rows to float64, all-null to Arrow null and all-empty to string. Require schema equality on the chunked pair too. Compare the later null-typed chunk with the oracle. On failing jobs use distinct row failures and compare the first `StrategyError` code to the oracle. Assert value-free public exception text and no publication of the failed table. Check the full mixed-batch error vector at kernel level (K3). K4b runs with one and four threads and compares bytes and ordered errors.
- **K5 ABI, probe and codes (S2b).** Refuse abi-3. A raw call with an unknown scheme raises a value-free coded `ValueError`. Pin `fpe_checksum_unknown_scheme` and the Rust row codes against their existing tables. Exercise the old plain call with the new keyword omitted. Update the success fake at `tests/unit/execution/test_native_companion_status.py:103` to accept and use the keyword. With other kernels healthy, test a missing FPE symbol, `errors=None`, and an oracle fake that passes ordinary FF1 and corrupts only one checksum vector (parameterize by scheme). Each failure refuses the loader and yields FPE-only unavailability. Assert status `load-error` with the lookup or inspection exception, or `kat-corrupt` with the synthesized cause. The healthy fake passes all three surfaces.
- **K6 one rule (S1 through S3).** Run the routing sentry and seeded cases in section 8. Check the slice-specific caller and forwarding sets. A new route decision must fail even inside an already listed reader.
- **K7 FK key (S2b).** Retain `tests/parity/test_phase_d_fpe_key_seq.py:554` and `test_phase_d_fpe_int_key_seq.py:526`. Use valid checksum identifiers and a genuine REMAP orphan for string and fixed-width integer keys. Assert zero native calls, oracle outputs and `python_scalar` for both parent scalar and orphan mint. Pin reasons `fpe_checksum_not_native:<parent column>` and `fpe_remap_parent_stays_python:<parent column>`. Run the same eligible key shapes without checksum and observe `rust_companion` for both scalar and `fk_remap` with positive call counts.
- **K8 inverse at kernel level (S2b).** Compare `_CompiledFpeKernel.decrypt_batch` with `reference_fpe().decrypt_batch` on K2 ciphertexts and K3 inverse inputs. Compare the exact inverse values and ordered errors. Canonical valid identifiers return their sources. The lowercase VIN check-slot case returns the canonical uppercase check character.

Named mutations (record the head): use the outer VIN radix for FF1 (K2 red); call full FPE validation in the NPI detector (K1 red); swap the npi prefix `80840` for `80804` (K1 red and `validators_match_the_reference_vectors` red); skip forward validation (K3 red); drop VIN charset filtering (K2 vin red); sort the filtered VIN charset (K2 custom-order vin red); uppercase the VIN body before `permute` (K3 lowercase-VIN cell red); drop the native-charset clause (K3 admission cells red); return `fpe_checksum_unsupported` for the domain-floor case (K3 red); leave the chunked decline in place (K6 and K4 red); keep abi-3 (K5 red).

Performance evidence (performance.md): the audit probe (`fpe(checksum: npi)` at 120,000 rows) and a 1,000,000-row run, three runs each on the Dell node through `vm-run`, before and after, wall time and peak RSS; expected close to the non-checksum 0.8 s per 120,000 rows. Numbers go in the S2b PR body.

## 10. Frozen contracts and byte changes

No masked value changes on any route (K4 compares against the unchanged oracle). Named changes:

1. **B1.** Eligible checksum payloads move to native execution. The existing `tokenizing` assembly preserves the oracle schema, including degenerate shapes. K4 pins both legs. Checksum FK keys retain their Python disposition.
2. **B2.** Companion ABI `decoy-native-abi-3` to `decoy-native-abi-4`: an older companion wheel no longer loads with a newer engine (it never shipped separately; the CLI bundles both). abi-4 belongs to this row alone: TEXT-REDACT-RUST-SPLICE revision 2 (`12263071f`) does not bump the ABI.

Fragment first line: `Breaking: eligible string fpe payload columns with luhn, npi, ean13, gtin, isbn13 or vin checksums now run in the native companion. Checksum FK keys stay on Python. The companion ABI is now decoy-native-abi-4.`

`SEED_PROTOCOL_VERSION`, plan serialization and digests do not change.

Public signatures (engine #763 sentry, `tests/sentry/release/test_public_signatures.py`): no public Python signature changes. `OperatorSpec` is private and the new field has a default; the FFI is not a public Python surface. `tests/sentry/baselines/signature-exemptions.json` is not touched. The Breaking line above still goes in the fragment because of B1 and B2.

ABI pin sites S2b updates to the new tag (13 besides `lib.rs`): `decoy-engine-native/scripts/parity_smoke.py`, `execution/native/_crypto_ext.py`, `tests/native/{test_c6c_ii_text_redact_rust.py,test_crypto_ext_loader.py,test_group_key_ext.py,test_index_ext.py,test_native_ext_abi.py}`, `tests/parity/{test_ooc_fpe_native_real.py,test_ooc_text_redact_native_real.py,test_phase_d_d1a_hash_native.py,test_phase_d_d1b1_bucket_native.py,test_phase_d_d1b2_categorical_native.py,test_phase_d_dcomp_composite_ooc_real.py}`. Current docs: `docs/native/supported-matrix.md:44`, `:110`, `docs/qa/15-execution-routes-native.md:22`.

CLI follow-up (not this row): the CLI tests `tests/unit/test_distribution.py:266-267` and `tests/unit/test_distribution_acceptance.py:285-287` hard-code abi-3. The CLI pin bump that picks up S2b follows the engine repin checklist and updates them.

## 11. Pre-mortem

- A check digit differs on an edge. Rust checks all regenerated rows before merge. The loader checks ordinary FF1 and one checksum row per scheme at runtime.
- VIN fallback: use the kernel-only outer charset `0IO` with seventeen zeroes. Filtering retains just `0`, so the permutation must use canonical digits. Compare forward output with the oracle. A digits-only charset retains ten symbols and misses this branch. The plan compiler requires the full VIN alphabet (`plan/_checks.py:544-551`).
- Oracle input normalization (stdnum `compact`, Unicode upper, `\d`). Handled by the native-charset clause (section 5.2), not by tests finding edge cases. K3 admission cells prove the clause declines a wider charset.
- A builder grows the K6 allow set to get green. The set is keyed by `(path, function)` with a reason per entry; the gate checks it against the caller and carrier list in section 8 and any new entry needs a stated reason in the PR.
- The arm64 Mac build fails on a new module. S2a builds on the Mac before merge.
- Another row bumps the ABI first. If any row merges abi-4 before S2b, S2b takes the next tag and updates the same pin sites; the builder merges main and re-runs K5 before the gate. No tag is reused.

## 12. Owner questions

None. S3 follows the S2b gate.

## 13. Deferred (V2-LOG)

- **V2-LOG:** native checksum fpe on `int64` sources (needs a typed output contract).
- **V2-LOG:** `iban` FPE with per-country BBAN structure.
- **V2-LOG:** native checksum fpe for charsets wider than the native alphabet (needs a ported, KAT-locked Unicode normalization).
