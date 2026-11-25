Status: plan (revision 5, 2026-11-25, Dennis rounds 1-2 and Codex rounds 1-2 folded, Codex round 3 GO; slice plan for S2a, S2b-core and S2b; anchored to PR #803 head `4819de8b2`, branch `feat/fpe-checksum-native-s1`)

# FPE-CHECKSUM-NATIVE slices S2a, S2b-core and S2b: check digits, the Rust batch path, then the keyword and ABI

Owner: Cam. Author: Opus (plan author). Roadmap row: FPE-CHECKSUM-NATIVE (group mask). Scope: decoy-engine and its Rust companion `decoy-engine-native/`. The CLI gets it with its next engine pin. Risk: R2 for all three slices (crypto output on a reversible strategy, a shared detector rule, a companion ABI bump).

Parent plan: `docs/plans/2026-11-22-fpe-checksum-native.md` revision 4 on branch `plan/fpe-checksum-native`. This file does not repeat the parent. It turns parent sections 5.4 to 5.8, 6, 9 and 10 into build steps for S2a, S2b-core and S2b, re-anchors line numbers to the S1 head and records what changed since the parent was written. Where this file and the parent disagree, this file wins for these slices. S3 (text_mask PAN and NPI spans) stays as the parent describes it.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `security.md`, `performance.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CONTRIBUTING.md` and `CODEMAP.md`.

Anchors: a Python path with no prefix is under `src/decoy_engine/`. Rust paths are named in full under `decoy-engine-native/`. All line numbers are read at `4819de8b2` (#803).

## Changes in revision 2 (Dennis round 1)

- HIGH: the new Rust modules and items are `pub`, as `fpe` and `text_redact` are (`lib.rs:34-48`). `pub(crate)` items cannot be reached from `tests/kat_checksum.rs` or `tests/kat_fpe.rs`, and a `pub fn` that takes a crate-private `Scheme` trips `private_interfaces`, which clippy `-D warnings` fails (`native-companion.yml:294`).
- MEDIUM: the full list of `fpe.rs` visibility changes is in section 5.2 and counted against the 700-line cap. `FPE_CHECKSUM_KAT` moves to `_fpe_ext.py` so `_crypto_ext.py` stays under 600 with TEXT-REDACT-RUST-SPLICE S1b.
- LOW: 13 test calls; translator line `_fpe_ext.py:52`; CI test commands; `arrow_ffi.rs` size; restated chunked mutation; per-scheme fixed prefixes; K6 carrier net +1.

## Changes in revision 5 (Codex round 2)

- V2-LOG: the `0IO` inverse vector pins `preserve_separators=True` and the batch row code `fpe_checksum_unsupported`; two reuse-inventory anchors corrected.

## Changes in revision 4 (Codex round 1)

- V1: the moved Luhn helper accumulates modulo 10, so a huge body cannot overflow `u32` before the FF1 length check (5.1, K1).
- DESIGN: the outer row transform in `fpe.rs` (outer charset, separators, empty selection, length check, reinsertion) is shared by both entries; checksum passes its own body function (5.2).
- DESIGN: K6 checks that the resolved scheme reaches `_fpe_fn(checksum=...)`, not only a read count (5.4).
- V2-LOG: K2 inverse-error fixture for the `0IO` VIN case; lowercase-body mutation moved to a core vector; S1 empty-registry tests and an integer orphan for K7; anchors.

## Changes in revision 3 (Dennis round 2)

- MEDIUM: the `fpe.rs` visibility table now matches the code: extract `ResolvedConfig::new` and a generic `run_rows` batch driver; `row_ranges` stays non-generic (5.2).
- LOW: `arrow_ffi.rs` line count, oracle line cite, CI command sentence, KAT vectors in two files logged as deferred.

## 1. Frame

State of the row on 2026-11-25:

| Slice | State |
|---|---|
| S1 one checksum decision, empty registry field, K6 sentry | PR #803, open, head `4819de8b2` |
| S2a shared check-digit arithmetic and K1 | planned here |
| S2b-core Rust checksum batch path and K2 | planned here |
| S2b FFI keyword, abi-4, registry schemes, one load probe, K3 to K8 | planned here |
| S3 text_mask PAN and NPI spans | parent plan, unchanged |

What S1 gives these slices, read at `4819de8b2`:

- `OperatorSpec.checksum_schemes: frozenset[str] = frozenset()` (`execution/_operator_registry.py:94`). The fpe spec at :282 leaves it empty, so every checksum column still declines.
- `fpe_checksum_rejection(column, scheme, resolved_charset, *, context)` (`execution/native/_operator_config_rejections.py:312`, registry read at :331) and the mapping adapter `fpe_checksum_config_rejection` (:339).
- The wrapper calls the decision in payload context and refuses before FFI (`execution/native/_fpe_ext.py:133-138`). The FFI call at :145 passes no checksum. The translator call is at :157.
- The FF1 load probe is inside `load_compiled_fpe_kernel` (`_fpe_ext.py:165`, probe at :205-219, `checksum is None` read at :219). Its copy is `_probe_fpe_kat` in `execution/native/_companion_status.py:224`, which imports `FPE_KAT` (:37) from `_crypto_ext.py:270`.

What the companion has today, read at the same head:

- `decoy-engine-native/src/fpe.rs` is 682 lines (cap 700). `luhn_check_digit` (:137) is private and used at :258 and in a test at :646. `ResolvedConfig` (:154), `permute` (:174), `fpe_pure_value` (:246), `fpe_one` (:269), `row_ranges` (:313), `fill_range` (:331), `pub fn fpe_transform_array` (:373, nine positional arguments). Thirteen unit-test calls to `fpe_transform_array` sit at :481-663.
- `decoy-engine-native/src/arrow_ffi.rs` calls `fpe_transform_array` once (:515) from `fpe_transform_batch_checked` (:491). The PyO3 entry `fpe_transform_batch` is at :556 and is registered at :613. The file is 615 lines at #803 (same as main) and 618 at #806 (TEXT-REDACT-RUST-SPLICE S1a).
- `decoy-engine-native/src/text_redact/validators.rs`: `luhn_valid` (:13) and `npi_valid` (:37-60). Both are used by `text_redact/detect.rs:47,51` and `text_redact/tests.rs`.
- `decoy-engine-native/src/lib.rs`: module lines at :33-47 and `ABI_VERSION = "decoy-native-abi-3"` at :57.
- `decoy-engine-native/tests/kat_fpe.rs:29-31` reads `format_version: u32` but never checks it (`#[allow(dead_code)]`).

### Change since the parent was written

- The parent's S2b-core adds a checksum parameter to `fpe_transform_array`. That changes fourteen test calls in `fpe.rs` and wraps some of them past the line width, which risks the 700-line cap. This plan keeps the `fpe_transform_array` signature and adds a separate checksum entry in `fpe_checksum.rs` that shares the batch driver (section 5.2).
- TEXT-REDACT-RUST-SPLICE S1a (#806) adds a fourteenth abi-3 pin site, `tests/native/text_splice/test_text_span_splice.py`. S2b computes the pin set at its merge base instead of using a fixed list (section 10).
- TEXT-REDACT-RUST-SPLICE S1b plans to turn `_translate_compiled_fpe_error` (`_fpe_ext.py:52` at #803, :50 at #806) into a delegate of the shared translator. The FPE behavior does not change, and `fpe_checksum_unknown_scheme` still passes through unchanged (section 5.4).

## 2. Established solutions

The parent section 2 holds the survey: products keep the check digit outside the FF1 domain, and the single-scheme Rust crates do not cover the NPI `80840` prefix rule or the engine's VIN fallback. Decision kept: one small pure Rust module per concern, each function citing its standard, locked by a KAT generated from python-stdnum and `decoy_engine.checksums`.

### Reuse inventory

- `fpe.rs::permute`, `ResolvedConfig` and the FF1 instance: the checksum path permutes the body through the same function and builds the config through a `ResolvedConfig::new` extracted from the struct literal in `fpe_transform_array` (`fpe.rs:407-418`).
- `fpe.rs::row_ranges`, `fill_range` and the rayon split, pool install and concatenation inline from :432: the one batch driver. S2b-core extracts it as a generic `run_rows` so the checksum entry does not copy it.
- `fpe.rs::luhn_check_digit` (:137): moves to `checksum.rs` as `pub`.
- `text_redact/validators.rs:13` and `:37-60`: keep their detector input rules and call `checksum::` for the arithmetic.
- `decoy-engine-native/vectors/generate_fpe_kat.py` and `fpe_ff1_kat.json`: the layout for the two new corpora.
- `_crypto_reference.py` `_ROW_ERROR_MESSAGES` (`execution/native/_crypto_reference.py:253`, `:256`): already maps `fpe_checksum_unsupported` and `fpe_checksum_invalid_source`. No new Python row codes.
- `fpe_checksum_rejection` (S1): the only admission decision. S2b changes the registry fact it reads and nothing in the function.
- The probe in `_fpe_ext.py:205-219` and `_companion_status.py:224`: S2b extracts one function both call.

## 3. Guarantee and non-goals

After S2a: one Rust copy of each check-digit rule. The NPI and Luhn detectors keep their acceptance rules. No masked value or detector result changes.

After S2b-core: the companion has a pure, KAT-locked checksum batch path. No Python code reaches it. The ABI stays abi-3 and every job behaves as today.

After S2b: the parent's guarantees 1 to 5 hold. An eligible string payload column with luhn, npi, ean13, gtin, isbn13 or vin runs native on all four routes, matches the oracle in values, nulls, order, schema and ordered row errors, and an abi-3 companion is refused at load.

Non-goals: iban; FK key checksum columns; non-string sources; Unicode normalization in Rust; text_mask spans (S3); any oracle change.

## 4. Enumerations

### 4.1 Exit paths (per value, Rust checksum path and oracle in the same order)

Parent section 4 is the full list. The oracle order is `_fpe_checksum_permute` (`src/decoy_engine/transforms/_fpe_checksum.py:68`, length rule at `:40`, called at `:172`). The Rust order in `fpe_checksum::checksum_one` matches it:

1. null: null out, no error.
2. empty string: `""` out, no error, before any charset check (the shared driver already does this, `decoy-engine-native/src/fpe.rs:348-352`).
3. outer charset check with the configured charset (non-preserve: any out-of-charset character; preserve: no in-charset character): existing codes.
4. `length_ok(scheme, n)` fails: `fpe_checksum_unsupported`.
5. forward only: `validate(scheme, chars)` fails: `fpe_checksum_invalid_source`. Inverse skips it.
6. FF1 config, domain floor, maximum body length and tweak length checks in `permute`: `fpe_unencryptable_domain` or `fpe_unencryptable_length`.
7. body character outside the permutation alphabet: `fpe_unencryptable_length`.
8. success: permuted body plus the recomputed check character, separators reinserted. Fixed parts per the parent: npi keeps `s[0]`, isbn13 keeps `s[:3]`, vin puts the check character at position 8 (section 5.2).

The batch returns every row error in input order.

### 4.2 Routes

- S2a and S2b-core: no route changes. Python never passes a scheme to the companion.
- S2b: unified slice, chunked native, sequential (non-key column) and out-of-core run the kernel when `fpe_checksum_rejection` passes. Full-frame pandas is unchanged. Companion absent or ABI mismatch keeps the existing companion-absent decline. Parent section 4 Routes table holds the before and after.

### 4.3 FK shapes

- Checksum on a sequential FK key (string or fixed-width integer) and REMAP orphan minting: Python, unchanged. S1's key context declines first. K7.
- Non-key checksum `fpe` column on an FK parent or child table: native on sequential and out-of-core after S2b. K4.

### 4.4 Fields

- `checksum`: the scheme, resolved by `config._resolve()` in the wrapper (`src/decoy_engine/execution/native/_fpe_ext.py:134`). S2b sends it to the companion as the keyword `checksum`.
- `charset`: decides admission (S1). Numeric schemes permute over canonical `0123456789`. vin filters the configured charset to the VIN alphabet in configured order, with the digits fallback.
- `validate_luhn`: ignored when `checksum` is set, on both paths. The Rust checksum entry does not take it.
- `preserve_separators`, `namespace`, `join_group`: unchanged.

### 4.5 Output surfaces

- Masked values and nulls.
- Per-row codes: `fpe_checksum_unsupported`, `fpe_checksum_invalid_source`, `fpe_unencryptable_length`, `fpe_unencryptable_domain`.
- Whole-call code from the companion: `fpe_checksum_unknown_scheme` (backstop; the plan check catches it first).
- Route evidence: `rust_companion` with positive kernel evidence on admitted columns.
- Load result and companion status record, both from the one probe after S2b.

### 4.6 Codes

No new reason code. `FPE_CHECKSUM_NOT_NATIVE` stays registered for key context and wide charsets. `fpe_checksum_unknown_scheme` is a Rust whole-call code string, not a registry reason. The FPE translator passes it through unchanged as a `ValueError`, which the wrapper then raises (K5 pins the code and the value-free text).

## 5. Design

### 5.1 S2a: `checksum.rs`

New `decoy-engine-native/src/checksum.rs`, pure, no PyO3, declared `pub mod checksum;` in `lib.rs`, matching `pub mod fpe;` and `pub mod text_redact;` (`lib.rs:34-48`). Every item below is `pub` so the integration test `tests/kat_checksum.rs` can call it:

- `pub enum Scheme { Luhn, Npi, Ean13, Gtin, Isbn13, Vin }` with `Scheme::parse(&str) -> Option<Scheme>` over exactly the six lower-case names.
- `pub fn length_ok(scheme, n) -> bool`: npi 10, isbn13 13, ean13 13, vin 17, gtin 8/12/13/14, luhn at least 2.
- `pub fn validate(scheme, &[char]) -> bool`: the whole value, exact length and every character. vin compares on an ASCII-uppercased copy.
- `pub fn check_digit(scheme, &[char]) -> char`.
- `pub fn luhn_check_digit(body: &str) -> char` (moved from `fpe.rs:137`). Today it sums in `u32`, which was safe behind the FF1 length bound. The forward validator now runs before that bound and luhn has no upper length, so a body of about 477 million nines would overflow (panic in a checked build, wrong `fpe_checksum_invalid_source` in release, where the oracle gives `fpe_unencryptable_length`). The moved helper reduces modulo 10 at each step, and so do the npi and gs1 sums. A unit test feeds the digit fold an iterator of nines long enough to pass `u32::MAX` without allocating the string. Then `npi_check_digit`, `gs1_check_digit` (shared by ean13, gtin and isbn13), `vin_check_char`.
- Doc comments cite the standard per function: python-stdnum `luhn`, GS1 General Specifications 7.9, ISO 2108, CMS NPI check digit, 49 CFR 565.15.

`fpe.rs` imports `luhn_check_digit` from `checksum` (net about -12 lines). `validators.rs` keeps its strip and length rules and replaces the mod-10 loop in `luhn_valid` and the `80840` prefix loop in `npi_valid` with calls into `checksum`. `text_redact/tests.rs` keeps its assertions unchanged, and adds `3234567899` (detector accepts it; FPE NPI `validate` rejects it).

Vectors: `decoy-engine-native/vectors/generate_checksum_kat.py` writes `checksum_kat.json` with `format_version: 1`, a provenance block (generator path, python-stdnum version, engine commit, seed) and at least 200 bodies per scheme. `decoy-engine-native/tests/kat_checksum.rs` rejects a missing or unknown `format_version` and checks `length_ok`, `validate` and `check_digit` on every row.

CODEMAP: add rows for the companion source, integration-test and vector directories with the first new file.

### 5.2 S2b-core: `fpe_checksum.rs` and the shared batch driver

New `decoy-engine-native/src/fpe_checksum.rs`, `pub mod fpe_checksum;` in `lib.rs`, with a `pub fn fpe_checksum_transform_array` that takes the `pub` `Scheme`, so `tests/kat_fpe.rs` can call it and clippy raises no `private_interfaces` warning:

- `pub fn fpe_checksum_transform_array(array, mask_key, namespace, tweak, charset, preserve_separators, scheme: Scheme, forward, threads) -> Result<FpeArrayResult, FpeKernelError>`.
- Per batch: prepare the permutation alphabet once (canonical digits for numeric schemes; configured-order VIN filtering with the oracle's digits fallback when fewer than two symbols remain). Build the symbol map, `ResolvedConfig` and FF1 with that alphabet and radix (33 for VIN under `ALPHANUM`). Derive the key once and build the cipher once.
- Per row: the outer row transform from `fpe.rs` (section 5.2 table) owns outer-charset membership, separator extraction, the empty-selection error, the output-length check and reinsertion, as `fpe_one` does today (`fpe.rs:269-307`). The checksum entry passes it a body function `checksum_body` that runs the scheme steps of section 4.1 and calls `fpe::permute` on the original body characters. The outer alphabet is the configured charset; for VIN the permutation alphabet is the filtered one, so the two are passed separately. The body split follows the parent's per-scheme rules: npi keeps `s[0]` fixed and permutes the rest of the body, isbn13 keeps the `978`/`979` prefix `s[:3]` fixed, and vin keeps position 8 (the check character) out of the permuted body and recomputes it there. The oracle split is at `_fpe_checksum.py:198-230` (npi :198, isbn13 :206, vin :213).

Visibility changes in `fpe.rs`, all `pub(crate)` because only `fpe_checksum.rs` in the same crate calls them (no `pub` signature exposes them):

| Item | Line | Change |
|---|---|---|
| `ResolvedConfig` | :154 | `pub(crate)` struct; extract `pub(crate) fn ResolvedConfig::new(...)` from the struct literal at :407-418, about +10 lines |
| outer row transform | `fpe_one` :269-307 | split into `pub(crate) fn outer_row<B>(value, outer, body: B)` plus the FF1 body closure; `fpe_one` becomes a call to it, about +6 lines |
| `permute` | :174 | `pub(crate)` |
| key derivation and FF1 construction helper | inside `fpe_transform_array` today | extract to `pub(crate) fn build_cipher(...)`, about +8 lines |
| `row_ranges` | :313 | unchanged, private (it takes no row function) |
| `fill_range` | :331 | private, generic over a row function `F: Fn(&str) -> Result<String, &'static str> + Sync` |
| batch driver | inline from :432 | extract `pub(crate) fn run_rows<F>(array, threads, f: F)` that owns `row_ranges`, the pool install and the per-range concatenation, about +12 lines |

`fpe_transform_array` keeps its nine-argument signature and passes its existing `fpe_one` closure. Line budget: 682, minus about 15 for the moved Luhn helper (S2a), plus about 8 for `build_cipher`, about 10 for `ResolvedConfig::new`, about 12 for `run_rows` and the generic bounds and about 6 for `outer_row`, gives about 703 before the extracted code replaces its inline copies, and about 695 after. This is close to the 700 cap, so S2b-core records the measured count in its PR body. If it is over 700, move `run_rows` and `fill_range` to a new `fpe_batch.rs`; the cap is not raised.

`arrow_ffi.rs` does not change in S2b-core. No Python caller reaches the new entry; it is proved only by Rust tests.

Vectors: the same generator writes `fpe_checksum_kat.json` (`format_version: 1`, provenance) with 50 valid identifiers per scheme, with and without separators, canonical and reversed digit charsets, VIN under `ALPHANUM` and `ZYXWVUTSRPNMLKJHGFEDCBA9876543210`, the lowercase check-slot case, a lowercase VIN body case (so the "uppercase VIN body before `permute`" mutation fails in S2b-core) and the `0IO` VIN fallback case. The `0IO` case is forward-only: the oracle's decrypt of its output (`03088129469621430` under the fixed synthetic key and tweak) with `preserve_separators=True` gives the batch row code `fpe_checksum_unsupported` (the Python exception behind it is `fpe.checksum_unsupported`; with `False` the code is `fpe_unencryptable_value`). The JSON row pins `preserve_separators=True` and the row code `fpe_checksum_unsupported`, which the Rust inverse must match. `kat_fpe.rs` gains a checksum section that rejects an unknown `format_version` for the new file and runs the full corpus through `fpe_checksum_transform_array` in both directions. The existing `fpe_ff1_kat.json` reader is left as it is.

### 5.3 S2b: FFI keyword and ABI

- `fpe_transform_batch` (`arrow_ffi.rs:556`) gains `checksum: Option<String>` as a keyword-only argument with PyO3 default `checksum=None` after `native_threads=None`. `fpe_transform_batch_checked` (:491) dispatches: `None` calls `fpe_transform_array` as today; `Some(name)` parses through `Scheme::parse` and calls `fpe_checksum_transform_array`; an unknown name returns the whole-call error `fpe_checksum_unknown_scheme` with no value in the text. About +12 lines; `arrow_ffi.rs` goes from 618 (with #806) to about 630 and stays under 700.
- `ABI_VERSION` moves to `decoy-native-abi-4` (`lib.rs:57`) and `_EXPECTED_ABI_VERSION` (`execution/native/_crypto_ext.py:359`) with it. Reason: PyO3 rejects an unknown keyword with `TypeError` at the first checksum batch. The bump moves that failure to a clean load-time decline.

### 5.4 S2b: Python wiring

1. Registry: the fpe spec (`_operator_registry.py:282`) sets `checksum_schemes=frozenset({"luhn", "npi", "ean13", "gtin", "isbn13", "vin"})`. This is the only admission change. All four routes and the wrapper read it through the S1 decision.
2. Wrapper: the FFI call at `_fpe_ext.py:145` forwards `checksum=checksum` (the already resolved scheme). K6's carrier set for `_CompiledFpeKernel.run` gains this forwarding use and nothing else. With the probe change in item 4 (one read removed, one forward added), the carrier read count is net +1. A count alone cannot prove the extra read is the forward: `test_fpe_checksum_one_rule.py:53` counts reads and `DELIVERIES` (:107) checks only delivery to the admission decision. So K6 gains an exact delivery check that the resolved scheme reaches `_fpe_fn(checksum=<resolved name>)`, keeps the decision check, and seeds a substitution (`checksum=None` at the FFI call with a branch on the read elsewhere) that must fail. The S2b PR body records the +1.
3. Translator: unchanged. `fpe_checksum_unknown_scheme` is not one of the two determinism codes, so `_translate_compiled_fpe_error` returns the `ValueError` unchanged. This holds both before and after TEXT-REDACT-RUST-SPLICE S1b turns it into a delegate.
4. One probe: extract `fpe_load_probe(kernel) -> ProbeResult` in `_fpe_ext.py`. It guards symbol lookup, vector setup, the call, unpacking and result inspection including `len(errors)`. It probes `FPE_KAT[0]` plus six checksum vectors (one per scheme) from a new `FPE_CHECKSUM_KAT` in `_fpe_ext.py` (not beside `FPE_KAT` at `_crypto_ext.py:270`: that file is 536 lines and TEXT-REDACT-RUST-SPLICE S1b adds about 20, so 45-50 more lines would pass 600). Success returns the tested callable. An exception gives `load-error` with the original exception. A completed mismatch gives `kat-corrupt`. `load_compiled_fpe_kernel` (:165) raises `CryptoExtensionUnavailableError` on either and chains the original exception when present. `_probe_fpe_kat` (`_companion_status.py:224`) becomes an adapter that keeps its `NativeCompanionCheckError` fields. The `checksum is None` read at :219 is replaced by forwarding the vector's scheme.
5. `FPE_CHECKSUM_KAT` entries are pinned to their rows in `fpe_checksum_kat.json` by a unit test, so the runtime probe and the Rust KAT cannot drift.

### 5.5 S2b: docs

- `docs/compatibility-contract.md` fpe native paragraph: eligible checksum payloads, and the corrected FK key and REMAP claim (parent section 5.8).
- `_fpe_ext.py` and `_text_mask_native_fpe.py` module docstrings.
- abi-3 to abi-4 in `docs/native/supported-matrix.md` (:44 and :110) and `docs/qa/15-execution-routes-native.md:22`. `CHANGELOG.md` and `docs/records/` are history and stay.
- Fragment `changelog.d/fpe-checksum-native.md` with the Breaking line in section 10. The S1 fragment `changelog.d/fpe-checksum-native-s1.md` stays.

## 6. Slices and size

Each slice is R2, merges separately and starts from the merged previous slice. Write the named tests first, run them on the slice base and record the expected failures. Code gate: Codex and Dennis. Test depth: T0 per edit, T1 impact selection per commit, T2 on the exact gate head. Each Rust slice runs `cargo clippy --all-targets -- -D warnings` (so integration tests are linted) and `cargo test --no-default-features`, the two commands CI runs (`.github/workflows/native-companion.yml:294,300`). A plain `cargo test` with the default `extension-module` feature can fail to link outside a Python build, so it is not a gate. Each Rust slice also records an arm64 build on the Mac. S2b hits the full-suite escalation triggers (version pin, frozen ABI contract), so its gate runs T3 on the merge head against the saved main baseline, on Linux and on the Mac.

| Slice | Depends on | Content | Size | Gate evidence |
|---|---|---|---|---|
| S2a | none (independent of S1) | `checksum.rs`, Luhn helper move, validators call the shared arithmetic, `3234567899` detector cases, generator, `checksum_kat.json`, `kat_checksum.rs`, CODEMAP rows | Rust about 180, generator and tests about 240; 1 day | K1, existing `tests/native/test_c6c_ii_text_redact_rust.py` suite, NPI-only redaction case. Mutations: npi prefix swap, full FPE validation in the detector, GS1 weight swap. |
| S2b-core | S2a | `fpe_checksum.rs`, generic batch driver, `fpe_checksum_kat.json`, `kat_fpe.rs` checksum section | Rust about 160, generator and tests about 130; 1 day | K2 both directions, K4b thread-count cell at Rust level (proptest extended to checksum configs). Mutations: outer VIN radix, drop VIN filtering, sort VIN charset, uppercase VIN body before `permute`, permute the npi `s[0]` or isbn13 `s[:3]` fixed prefix. |
| S2b | S1 (#803) and S2b-core | FFI keyword, abi-4 and pins, registry schemes, wrapper forwarding, one probe, docs, fragment, route test updates (parent section 6 list) | source about 70 net, tests about 300 plus pin and doc edits; 1 builder-day plus gate runs | K3, K4, K4b, K5, K6, K7, K8, performance runs. Mutations: skip forward validation, drop the native-charset clause, unsupported for the domain-floor case, re-add a chunked-only decline, drop one scheme from the registry set, keep abi-3, map an unknown scheme to luhn. |

**Activation boundary.** No job can reach the Rust checksum path before S2b: S2b-core has no FFI keyword and S1's registry set is empty. ABI exposure and admission land in the same S2b commit range and are gated together.

S2b updates the eligible payload expectations in `tests/native/test_c6a_fpe_chunked.py`, `tests/native/test_obs2_decline_records.py`, `tests/parity/test_phase_d_d2c_fpe_seq.py`, `tests/parity/test_ooc_fpe_native_routing.py` and `tests/physical/test_shadow_fpe.py:439`. Keep a wide-charset decline, unknown and IBAN refusals and both checksum-key decline tests. It updates the success fake at `tests/unit/execution/test_native_companion_status.py:103`. S1 tests that rely on an empty production registry (`test_fpe_checksum_decision.py:53, :57, :125, :150`) move to an explicit empty-registry fixture, and a new test pins the six production schemes. For K7 on integer keys, `test_phase_d_fpe_int_key_seq.py:531` supplies only a matched child; add an unmatched valid integer and compare its REMAP output and disposition with the oracle before counting it as an already-green guard.

Performance (S2b PR body): the audit probe (`fpe(checksum: npi)` at 120,000 rows) and a 1,000,000-row run, three runs each on the Dell through `vm-run`, before and after, wall time and peak RSS. Expected near the non-checksum 0.8 s per 120,000 rows.

## 7. Placement

| New or changed file | Directory | CODEMAP row | Size after |
|---|---|---|---|
| `checksum.rs` (S2a), `fpe_checksum.rs` (S2b-core) | `decoy-engine-native/src/` | new companion source row | about 180 and 200 |
| `fpe.rs` | same | existing | at or below 700 at every head |
| `arrow_ffi.rs` (S2b) | same | existing | about 630 |
| `kat_checksum.rs` | `decoy-engine-native/tests/` | new companion tests row | about 120 |
| `generate_checksum_kat.py`, `checksum_kat.json`, `fpe_checksum_kat.json` | `decoy-engine-native/vectors/` | new companion vectors row | generator about 250 |
| `test_fpe_checksum_native.py` (S2b) | `tests/parity/native/` | existing row | under 600; selected by `.github/workflows/native-companion.yml:402` |
| `fpe_load_probe`, `FPE_CHECKSUM_KAT` (S2b) | `execution/native/_fpe_ext.py` | existing | `_fpe_ext.py` about 350; `_crypto_ext.py` unchanged by this row (536, about 560 after TRS S1b) |
| `fpe-checksum-native.md` | `changelog.d/` | existing | n/a |

No new Python module in `execution/native/`, so the package fan-out stays at 55 (`tests/sentry/layout/test_package_fanout.py:36`).

## 8. Class table

| # | Class | Where it applies | Closing structure | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | Rust whole-call and row codes, probe failures | codes only; `fpe_checksum_unknown_scheme` text has no input; probe errors keep the existing reason fields | K5 asserts value-free text; existing value-free sentries | put the scheme string into the unknown-scheme message (K5 red) |
| 2 | Cleanup missing on an exit path | key material in the checksum batch | the checksum entry derives the key once and borrows one cipher per batch; no new key copy; the Python `del key` path is unchanged | review, existing zeroize tests | n/a: no new owned key buffer |
| 3 | State and concurrency | rayon row ranges in the generic driver | the row function is pure per value; batch-invariance proptest extended to checksum configs | K4b at one and four threads | share a mutable digit buffer across rows (proptest red) |
| 4 | Route parity and silent fallback | four routes after S2b, companion absent | one decision (S1); parity per route; companion absent keeps the decline | K4, K6 | re-add a chunked-only decline (K4 red) |
| 5 | Referential integrity | checksum FK keys and REMAP orphans | key context declines first (S1); parent and orphan mint stay on Python | K7 | pass payload context for a checksum key (K7 red) |
| 6 | Untrusted producer | hostile identifier values | the native-charset clause plus the exit order in section 4.1 | K3 hostile corpus through kernel and oracle | skip forward validation (K3 invalid-source cells red) |
| 7 | Check then use (TOCTOU) | load probe versus job call | the probe returns the tested callable and the wrapper calls that object, never a fresh attribute lookup | K5 swaps the module attribute after load and expects the tested callable | look the symbol up again per call (K5 red) |
| 8 | Weak tests | expected bytes for K1 and K2 | the generator fixes seed, key, tweak and row order and regenerates from the Python oracle; the gate compares every field with the committed files | regenerate-and-compare step in K1 and K2 | alter one committed expected byte with provenance intact (comparison red) |
| 9 | Refactor drift | Luhn helper move, validators, generic driver, probe extraction | existing `fpe.rs` unit tests and `text_redact/tests.rs` pass unchanged; both probe contracts pinned | slice test runs, K5 | make `luhn_valid` use FPE `validate` (detector test red) |
| 10 | Frozen contract drift | ABI tag, contract fpe paragraph, vector schemas | abi-4 with the pin set from section 10; fragment Breaking line; `format_version` checked by each new reader | K5, docs review | keep abi-3 with the new keyword (K5 red); drop the version check (seeded old-version fixture passes, red) |

Recurring-defect catalog checks: anchored validation (whole value and every charset symbol, never a prefix; K3 cells with a dash charset); strict wire types (`Option<String>` matched against a closed enum); versioned read models (both new JSON files); no hidden CI failures (clippy `--all-targets -D warnings` and `cargo test --no-default-features` as CI runs them, arm64 build recorded); no raised caps (`fpe.rs` at or below 700).

## 9. Acceptance tests

Each fails on its slice base unless marked already-green. IDs match the parent section 9, where each is described in full.

- **K1 check-digit KAT (S2a).** At least 200 bodies per scheme from the Python oracle and python-stdnum, edge bodies per the parent, `1234567893` and `1M8GDM9AXKP042788`. Regenerate and compare, then Rust checks every row. `3234567899`: `npi_valid` accepts it; NPI-only text redaction maps `id 3234567899 end` to `id <X> end` in `tests/native/test_c6c_ii_text_redact_rust.py`; FPE NPI `validate` rejects it.
- **K2 end-to-end FPE KAT (S2b-core).** 50 valid identifiers per scheme with recorded key, namespace, tweak framing, config, Python ciphertext and inverse. Both directions through `fpe_checksum_transform_array`, not the FF1 crate directly. Include the `0IO` VIN fallback and the lowercase check-slot case.
- **K3 hostile corpus (S2b).** Native and reference kernel values and ordered `(row, code)` vectors on mixed rows, forward and inverse, with the length, separator, domain-floor and VIN cases from the parent. Route declines for GTIN and EAN13 with `0123456789-` and NPI with `ALPHANUM`; direct wrapper calls refuse before FFI.
- **K4 and K4b route parity (S2b).** Per scheme on unified slice (2,000 rows), chunked (120,000 rows, at least three chunks), sequential and out-of-core two-table jobs. Positive companion evidence, exact Arrow table equality including schema, degenerate shapes, first-error parity on failing jobs, value-free public text, no publication. K4b at one and four threads.
- **K5 ABI, probe and codes (S2b).** Refuse abi-3. Unknown scheme gives a value-free coded `ValueError`. The plain call with the keyword omitted still works. Missing symbol, `errors=None`, and a fake that corrupts one checksum vector per scheme each refuse the FPE loader only and report `load-error` or `kat-corrupt`. Pin `FPE_CHECKSUM_KAT` to the JSON rows.
- **K6 one rule (S2b update).** The S1 sentry gains the wrapper's forwarding use and the probe's vector-scheme forwarding, and loses the `checksum is None` read. Seeded spellings still fail.
- **K7 FK key (S2b, already-green guard plus the eligible-without-checksum contrast).** `tests/parity/test_phase_d_fpe_key_seq.py:554` and `test_phase_d_fpe_int_key_seq.py:526` with valid checksum identifiers and a REMAP orphan: zero native calls, oracle outputs, `python_scalar`.
- **K8 inverse (S2b).** `_CompiledFpeKernel.decrypt_batch` against `reference_fpe().decrypt_batch` on K2 ciphertexts and K3 inverse inputs.

Named mutations are listed per slice in section 6. Run each alone against the passing tests, restore before the next, and record the head and the failing assertion. S2b reruns the full list on its final head.

## 10. Frozen contracts and byte changes

No masked value changes on any route (K4 compares against the unchanged oracle).

1. **B1 (S2b).** Eligible checksum payload columns move to native execution. Checksum FK keys stay on Python.
2. **B2 (S2b).** Companion ABI `decoy-native-abi-3` to `decoy-native-abi-4`.

Fragment first line: `Breaking: eligible string fpe payload columns with luhn, npi, ean13, gtin, isbn13 or vin checksums now run in the native companion. Checksum FK keys stay on Python. The companion ABI is now decoy-native-abi-4.`

ABI pin set: at the S2b merge base, run `git grep -l decoy-native-abi-3 -- . ':!docs/records' ':!docs/plans' ':!CHANGELOG.md'` and move every hit. At `4819de8b2` that gives `decoy-engine-native/src/lib.rs`, the 13 sites in parent section 10 and the two current docs. If TEXT-REDACT-RUST-SPLICE S1a (#806) merges first, `tests/native/text_splice/test_text_span_splice.py` is a fourteenth site. `tests/native/test_native_ext_abi.py:27` pins the tag as a literal and checks the built companion against it, so a missed test pin fails when the companion is built; a missed doc pin is caught only by the grep.

S2a and S2b-core change no frozen surface: no ABI change, no Python signature change, no byte change.

`SEED_PROTOCOL_VERSION`, plan serialization and digests do not change. No public Python signature changes (`tests/sentry/release/test_public_signatures.py`).

CLI follow-up (not this row): the CLI tests that hard-code abi-3 move with the pin bump that picks up S2b, through the engine repin checklist.

## 11. Pre-mortem

- A check digit differs on an edge. K1 and K2 regenerate from the oracle and Rust checks every row before merge; the runtime probe checks one vector per scheme.
- `fpe.rs` passes 700 lines. S2a removes the Luhn helper first; the checksum logic lives in `fpe_checksum.rs`; the generic driver change is about +5 lines.
- The generic driver changes plain FF1 bytes. Existing `fpe.rs` unit tests, `kat_fpe.rs` and the batch-invariance proptest run unchanged on S2b-core.
- The validators change detector acceptance. `text_redact/tests.rs` assertions stay as they are, and the NPI-only redaction case pins the detector rule against FPE validation.
- Another row bumps the ABI first. S2b then takes the next tag, recomputes the pin set and reruns K5. No tag is reused.
- TEXT-REDACT-RUST-SPLICE S1b and this row both edit `_fpe_ext.py`. S1b edits the translator at :52 (#803 numbering); S2b edits the call at :145 and the probe at :165-219. The hunks do not overlap. Rebase whichever merges second and rerun the FPE loader tests.
- Both rows add module lines to `lib.rs` (:33-47) and edit `arrow_ffi.rs`. The conflicts are adjacent lines only.

## 12. Owner questions and dependencies

- **OWNER CALL (taken: separate checksum entry instead of a new `fpe_transform_array` parameter).** Keeps the plain FF1 signature and the fourteen `fpe.rs` test calls unchanged and protects the 700-line cap. No behavior difference. Recommended and taken.
- **OWNER CALL (taken: abi-4 belongs to this row).** TEXT-REDACT-RUST-SPLICE stays on abi-3 through S1c. If abi-4 lands before that row's S2b, its skew test asserts a clean load refusal for an abi-3 wheel. Recorded in both plans.

Dependencies: S2a has none and can start now. S2b-core needs S2a merged. S2b needs S1 (#803) and S2b-core merged. S3 follows the S2b gate.

## 13. Deferred (V2-LOG)

Unchanged from the parent: native checksum fpe on `int64` sources; iban; charsets wider than the native alphabet. Added: KAT vectors live in two files (`FPE_KAT` in `_crypto_ext.py`, `FPE_CHECKSUM_KAT` in `_fpe_ext.py`); the JSON pin test limits drift, and the V2 structure pass decides one home.
