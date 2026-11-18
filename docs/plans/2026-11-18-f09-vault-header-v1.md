Status: plan (revision 1, 2026-11-18; not yet reviewed)

# F09 1.0 cut: authenticated, versioned vault header (roadmap row 79) and the F29 close-out (row 66)

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18.

Roadmap row 79 (F09) was split by the 1.0 scope triage on 2026-11-18 (`C:docs/records/2026-11-18-1.0-scope-triage.md`, row 79): "1.0: the authenticated, versioned token vault header (freeze: the vault format). 1.1+: domain versions, rotation, remap." This plan is the 1.0 half only. The full F09 plan (`E:plan/f09-domain-version`, revision 3, base `dcc4bcb3`, 2026-11-15) stays the source for 1.1+. That plan was written before F22 b1 (#607) and b2 (#622) moved the vault adopt path into `publication/_vault_order.py`, so its E0 and E1 cannot be built as written. This plan re-cuts and re-anchors them.

Row 66 (F29 remainder) is batched here because only its docs slice is left: C0 merged (engine #367), C1 shipped as CLI #229 ("one engine reason in the --json failure envelope"), and P1 and P2 are platform slices, parked with the platform. E7 (a "Consumers" section in `docs/reasons.md`) is about 60 lines and touches no vault file, so it rides as its own small slice.

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1 for the pure move, R2 for crypto and a frozen format; the exception record in section 2.1), `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `security.md` (vetted crypto, no custom protocol, secrets out of errors), `api-and-compatibility.md` (frozen format, public signature change before GA), `data-and-migrations.md` (format version, no reader for the old version, recovery), `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation), `refactoring.md` (pure move first, named steps), `reuse-first.md`, `testing.md` (T0 to T2, mutations), `proportionality.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Risk: R2 overall. E1 changes a frozen on-disk format and the crypto of the most sensitive artifact the engine writes. E0 is R1 (pure move). E7 is R0 (docs plus one doc test). C1 is R2 (a frozen `--json` shape gets new keys, and error text changes). Approver: Cam (owner) for the plan and the section 2.1 exception; Dennis then Codex for the plan gate.

Why 1.0: row 79's 1.0 test is "freeze". `decoy-vault/v2` becomes permanent at the first real v2 vault under the compatibility contract (section 3.2, pre-GA vault key floor note). After 1.0 a header change costs a second hard cut and a reader kept forever. It must merge before the D-4 engine freeze after the 2026-12-04 build target.

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. A vault written by this engine is `decoy-vault/v3`. Its header is bound to every encrypted segment. Any change to a header field, any reordering, dropping, duplication or truncation of segments, and any bytes after the last segment make `load_vault` refuse with the new code `vault_tampered`. No partial mapping is returned.
2. Each vault has its own key. `vault_id` is 32 random bytes in the header, and the segment key is `derive(mask_key, "vault", b"vault-key/v2" + uint32be(32) + vault_id)`. Two vaults written under the same secret never share a key or a nonce.
3. The header carries a key check value (`key_check`). A wrong secret is refused with `vault_key_mismatch` before any segment is decrypted, and the message names the vault's recorded `key_version` label. A right secret with a damaged file gives `vault_tampered`, not `vault_key_mismatch`. The two causes have different remedies, so the user is told which one it is.
4. The header records `key_version` (the provider's non-secret label) and `entry_count`. `decoy report vault` shows the format, the key version and a short vault id, and its `--json` gains `format`, `key_version` and `vault_id`.
5. A `decoy-vault/v2` file is refused with `vault_format_unsupported` and a remedy: re-run the mask with `--vault` under this version. There is no v2 reader (hard cut, owner Q2).
6. Every existing guarantee holds: the 32-byte key floor (`weak_mask_secret` before any file is read), `vault_crypto_not_installed`, `vault_protocol_version_mismatch`, no key in any traceback frame (`_opaque` rules and the secret-material census), no value and no path in error text, F22 adopt-or-refuse (`adopt_vault`, `issue_commit` as the only `VaultCommit` issuer), and the existing public names.
7. The CLI renders every `VaultError` from one function, so `decoy unmask` and `decoy report vault` give the same text and hint for the same code.
8. Row 66: `docs/reasons.md` names every consumer of the reason registry and the limits of each.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- Domain-version objects, rotation, remap, preview and evidence (full F09 E2 to E5). Later, on `E:plan/f09-domain-version`.
- The SQLite token store that `decoy tokenize --vault` writes (`C:src/decoy/cli/_token_vault.py`). Owner Q4: out of scope.
- A v2 reader, a migration tool or a `decoy vault upgrade` command. Owner Q2: hard cut. Recovery for a user with a v2 vault is to re-run the mask with `--vault`; the source data is the recovery path, as for the B-6 cut.
- Streaming reads of very large vaults. `load_vault` still reads the whole file, as today.
- Byte-reproducible vault files. The file was never reproducible (Fernet had a random IV and a timestamp); v3 has a random `vault_id`.
- Hostile in-process attackers (V1 threat model: accidental leaks only). The tamper check guards against a damaged or edited file at rest, not against code that runs inside the engine.
- Platform consumers of reasons (F29 P1, P2). Parked with the platform.

## 2. Established solutions

| Need | Established solution | What we take | What we do not take, and why |
|---|---|---|---|
| Encrypt a long plaintext in segments so that reorder, drop and truncation are detected | The STREAM construction (Hoang, Reyhanitabar, Rogaway, Vizar, "Online Authenticated-Encryption and its Nonce-Reuse Misuse-Resistance", CRYPTO 2015); Google Tink Streaming AEAD `AES256_GCM_HKDF_*` (per-file random salt into HKDF, nonce = prefix, 32-bit segment counter, last-segment flag); the age v1 payload format (64 KiB chunks, counter nonce, last-chunk flag) | Per-file key from a random salt, nonce = 7-byte prefix, 4-byte big-endian counter, 1-byte last flag; the last segment must carry the flag and nothing may follow it | The Tink Python library itself (see 2.1) |
| The AEAD primitive | AES-256-GCM, NIST SP 800-38D; RFC 5116 interface; `cryptography.hazmat.primitives.ciphers.aead.AESGCM` | 32-byte key, 12-byte nonce, associated data | Fernet (today): AES-128, a token per chunk with no binding between chunks and no header authentication. ChaCha20-Poly1305: fine, but AES-GCM matches Tink and FIPS reviews |
| Bind the header to the ciphertext | AEAD associated data (RFC 5116 section 3) | `ad = SHA-256(magic + framed header bytes)` on every segment | A separate header MAC: a second key and a second check for what AD already gives |
| Nonce safety | SP 800-38D section 8 (unique nonce per key; at most 2^32 invocations with a counter nonce) | A fresh key per vault makes nonce reuse across vaults impossible; the counter makes it impossible inside one vault | Random 96-bit nonces per segment: safe, but the counter is also what detects reordering |
| Key derivation | RFC 5869 HKDF, already the engine's `derive` (HMAC-SHA256 over an HKDF-expanded key, `determinism/_derive.py:260`) | New labels `vault-key/v2`, `vault-nonce/v1`, `key-check/v1` under the existing `derive` | A second KDF |
| Tell a wrong key from a damaged file | Key check value (PKCS#11 `CKA_CHECK_VALUE`; payment-industry KCV) | A KCV derived with its own label: the first 8 bytes of `derive(mask_key, "key-check", b"key-check/v1")`, 16 lowercase hex characters | The "encrypt a zero block" KCV form: it uses the data key itself; an HKDF label keeps the KCV independent of the segment key |
| Format versioning and hard cut | The engine's frozen-surface rule (`docs/frozen-surfaces.md`), compatibility contract section 1 (pre-GA changes allowed with a Breaking fragment) and the B-6 owner decision (2026-11-13, no old-vault reader) | New magic `DCYVAULT3\n` and `format: decoy-vault/v3`; a v2 file is recognized and refused with a remedy | A version-negotiating reader |

### 2.1 Exception record: segment framing on `cryptography` instead of Tink

`security.md` says: do not create custom cryptographic primitives or protocols. This plan builds no primitive (AES-256-GCM and HKDF come from `cryptography` and the existing `derive`), but the segment framing is a protocol written in the engine.

- Policy domain: security, "no custom cryptographic protocols".
- Scope: `vault/_format.py` segment framing only.
- Risk: R2.
- Rationale: Tink Python (`tink`) pulls in a protobuf runtime and a C++ extension for one function, on a release path that ships signed bundles for Linux, macOS and Windows. Its streaming file format also has its own header, so it would replace the vault header this row exists to define. The framing here copies Tink's published AES-GCM-HKDF streaming layout field for field (salt-derived key, 7-byte prefix, 4-byte counter, 1-byte last flag), with the header as AD added on top. Nothing in it is new.
- Compensating controls: each security property has its own acceptance test and a named mutation (AT-V3 to AT-V10); AT-V18 keeps the AEAD import in one module; the slice gets Dennis and Codex with a crypto-focused brief; the security doc records the construction and its sources.
- Residual risk: a framing bug that the listed tests do not reach. Low, because the decode path is small (one loop) and every failure ends in one refusal.
- Approver: Cam (owner question Q-B). Follow-up: none, unless Q-B is answered "use Tink"; then E1 replaces `_format.py` segment code with `tink.streaming_aead` and the header stays as designed (the header becomes Tink's associated data).

## 3. Reuse inventory

- `determinism.derive` for all three labels. No new KDF code.
- `_opaque.OpaqueBox` and the existing `_key_size` and `_require_vault_key` floor: the key stays boxed; the derived key is never a local (`_opaque` rule; secret-material census entries move with E0 and gain the new functions in E1).
- `_frame` and `_read_frame` (length-prefixed framing) stay as the outer framing.
- Parquet per segment, `_SCHEMA`, `_fold` (sort, fold duplicates, drop ambiguous) stay as they are.
- `keyprovider.is_key_version_label` and `KEY_VERSION_PATTERN` validate the recorded label (one rule, already used by the resume store and the runtime lock).
- F22: `publication/_vault_order.py` (`read_vault_leaf`, `BytesHandle`, `same_rows`, `adopt_vault`) and `issue_commit` are used unchanged. They call `serialize`, `reads_as_own` and `load_vault`, whose signatures and return types do not change.
- CLI: `emit_error` (`C:src/decoy/ui/output.py`), `exit_code_for` (`C:src/decoy/cli/exit_codes.py`), `_mask_secret.admitted_key_provider`, `_mask_secret_guidance`.

## 4. Behaviour

### 4.1 File layout (`decoy-vault/v3`)

```
magic            b"DCYVAULT3\n"
frame(header)    uint32be length + canonical JSON (sort_keys, separators (",", ":"), UTF-8), at most 4096 bytes
frame(segment_0) uint32be length + AES-256-GCM ciphertext and tag
...
frame(segment_n) the last segment; its nonce carries last = 0x01; nothing follows it
```

Header, a closed field set (any other key, a missing key or a wrong type is `vault_unreadable`):

| Field | Type and rule |
|---|---|
| `format` | `"decoy-vault/v3"` |
| `seed_protocol_version` | int, equal to `SEED_PROTOCOL_VERSION` |
| `key_version` | str, `is_key_version_label` true |
| `key_check` | 16 lowercase hex characters |
| `vault_id` | 64 lowercase hex characters (32 random bytes from `os.urandom`) |
| `ambiguous_dropped` | int, at least 0 (not bool) |
| `entry_count` | int, at least 0 (not bool) |
| `segment_rows` | int, from 1 to 1,048,576 |

Keys and nonces:

- `K_vault = derive(mask_key, "vault", b"vault-key/v2" + (32).to_bytes(4, "big") + vault_id_bytes)`. It stays inside the call that builds the `AESGCM` object (never a local; `_opaque`).
- `prefix = derive(K_vault, "vault", b"vault-nonce/v1")[:7]`, computed in the same call.
- `nonce_i = prefix + i.to_bytes(4, "big") + (b"\x01" if last else b"\x00")`.
- `ad = sha256(magic + frame(header)).digest()`, the same for every segment.
- Segment `i` plaintext: a Parquet table of at most `segment_rows` sorted rows. A vault with no entries writes one last segment holding an empty table, so a file with no segment is always a truncation.

### 4.2 Read order (`_open_vault`, the one reader)

1. Key floor (`weak_mask_secret`) and crypto import (`vault_crypto_not_installed`), before the file is read. Unchanged order.
2. Read the bytes (`vault_unreadable` on an OS error, as today).
3. Magic. `DCYVAULT2\n` gives `vault_format_unsupported` with the re-mask remedy. Any other magic gives `vault_unreadable`.
4. Header frame and JSON, closed field set and types: `vault_unreadable`.
5. `format` other than v3: `vault_format_unsupported`. `seed_protocol_version` other than the engine's: `vault_protocol_version_mismatch` (text unchanged).
6. KCV: `hmac.compare_digest(key_check, key_check_value(mask_key))` false gives `vault_key_mismatch`; the message says "this vault was written under key version '<label>'". No segment is decrypted.
7. Segments in order. From here on, any framing error, a GCM tag failure, a missing last flag, bytes after the last segment, a counter past 2^32 - 1, a row total that differs from `entry_count`, or a malformed or duplicate row gives `vault_tampered`. The mapping built so far is dropped; nothing is returned.

Rule for users: before the header is understood, a bad file is "unreadable"; after the header is understood and the key is right, any damage is "tampered".

### 4.3 Engine API

- `VaultWriter(mask_key, *, key_version, file_access=None)`. `key_version` is a new required keyword. A label that fails `is_key_version_label` raises `ValueError` with a fixed text at construction, before any file work. In production the label comes from an already-validated provider, so this is a caller-bug guard. Breaking, pre-GA, with a Breaking fragment (compatibility contract section 1).
- `vault_writer_for_config` passes `provider.key_version`.
- `open_vault(path, mask_key, *, vault=None, file_access=None) -> OpenedVault`, new. `OpenedVault` is a frozen dataclass: `mapping`, `ambiguous_dropped`, `header: VaultHeader`. `VaultHeader` is a frozen dataclass of the non-secret fields: format, key_version, vault_id, entry_count, ambiguous_dropped, segment_rows. `key_check` is not exposed. Registered in `fileaccess.ENTRY_POINTS`.
- `load_vault(...)` keeps its signature and return `(mapping, ambiguous_dropped)` and is `open_vault` minus the header. F22 code and every current caller keep working.
- `serialize`, `publish`, `reads_as_own`, `issue_commit`, `assert_vault_writer_keyed`, `collect_vault_entries`: same signatures and meaning.
- `VAULT_FORMAT_VERSION = "decoy-vault/v3"`. `VAULT_KEY_LABEL = b"vault-key/v2"`. Both stay public.
- `keyprovider.key_check_value(mask_key: bytes) -> str`, new, beside `is_key_version_label`. The one KCV function; F09 1.1+ domain versions reuse it.
- Reason `runtime.VAULT_TAMPERED` (`vault_tampered`), `since=UNRELEASED`, kind `failure`, outcome as the other vault input refusals. Summary: "The vault file was changed or cut short after it was written."

### 4.4 CLI

- New sub-package `C:src/decoy/cli/vault/` (the flat `cli/` folder is frozen at 30 modules):
  - `_errors.py`: `vault_error_text(exc: VaultError) -> tuple[str, str | None]`, the one mapping from a vault code to the message and hint. Codes: `vault_key_mismatch` (use the run's mask secret; the engine message already names the key version), `vault_tampered` (the file was changed or cut short; restore the copy you stored), `vault_format_unsupported` (written by an older Decoy; re-run `decoy run --vault` with this version), `vault_protocol_version_mismatch` (today's text, moved), anything else (code and message, no hint).
  - `_report.py`: the `report vault` command body and its epilog, moved out of `C:src/decoy/cli/report.py` (about lines 2124 to 2280 at `920ea13c`). It calls `open_vault` and prints `format`, `key version` and `vault id` (first 12 hex characters plus an ellipsis in text mode; the full id in `--json`).
- `C:src/decoy/cli/report.py` keeps only the registration line for `vault`. The file shrinks by about 150 lines (it is oversize at 2299 and must not grow).
- `C:src/decoy/cli/unmask.py`: its `except VaultError` branch calls `vault_error_text`. Exit codes do not change: every vault refusal stays `EXIT_USAGE` (1); `VAULT_EXISTS` on `decoy run` keeps its mapping in `exit_codes.py`.
- `report vault --json` success keys: `command`, `status`, `vault`, `entries`, `namespaces`, `ambiguous_dropped` (unchanged) plus `format`, `key_version`, `vault_id` (additive). Error envelope unchanged in shape.
- `C:docs/cli-reference.md` `report vault` section and the `decoy explain vault` topic: one line each on the v3 format and the tamper check.

Coordination: row 24zw (REPORT-VAULT-HELP, `E:plan/v1-fix-batch-24zo` C1) edits the same help and epilog. C1 starts only after 24zw C1 has merged, and moves the fixed text. Otherwise the move would fork the text.

### 4.5 Row 66 E7

`docs/reasons.md` gets a "Consumers" section: the CLI `--json` failure envelope `reason` field (CLI #229, `C:src/decoy/cli/run/_errors.py` `_failure_reason`), which codes reach it and which CLI-owned refusals carry no `reason` (C-T5 and C-T7 of the F29 plan); `APPROVED_ERROR_MESSAGES` in `error_projection.py` (including `keyed_strategy_requires_secret` and `weak_mask_secret`); the platform consumers (F29 P1, P2) recorded as parked with the platform. One doc test pins it. With E7 merged, row 66 has no 1.0 work left.

## 5. Enumerations

### 5.1 Callers of the vault API (engine `ad36687a6`)

| Caller | Uses | Change |
|---|---|---|
| `vault.vault_writer_for_config` | `VaultWriter(...)` (the only construction in `src/`) | passes `key_version` |
| `publication/_vault_order.py` | `serialize`, `reads_as_own`, `load_vault` via `reads_as_own`, `issue_commit` | none |
| `publication/_publish.py`, `publication/_types.py` | `VaultCommit`, `VaultWriter` types | none |
| `unmask.py:292-295` | `load_vault` | none |
| execution modules | `assert_vault_writer_keyed`, `collect_vault_entries` | none (import path kept by the package `__init__`) |
| `__init__.py:335` | exports `VaultError`, `VaultWriter`, `load_vault`, `vault_writer_for_config` | adds `open_vault`, `OpenedVault`, `VaultHeader` |
| `fileaccess/__init__.py:126-127` | `ENTRY_POINTS` names | E0 renames to the new module paths; E1 adds `open_vault` |
| CLI `report.py:2228` | `load_vault` | moves to `cli/vault/_report.py`, uses `open_vault` |
| CLI `unmask.py` | `VaultError` via `unmask_pipeline` | uses `vault_error_text` |
| CLI `run/_prepare.py:562-564` | `vault_writer_for_config` | none |
| Tests: 25 files construct `VaultWriter(key)` directly | | E1 routes them through one helper `tests/unit/vault/_support.py::writer(key)` that passes `key_version="v1"` |
| Tests that monkeypatch module attributes (`tests/fileaccess/publication/_vault_support.py:66`, `tests/fileaccess/test_secret_material_frames.py:134,155`, `tests/unit/publication/test_publish_vault_order.py:242`) | | E0 points them at the module that now owns the attribute |

### 5.2 Exit paths

Engine (`_open_vault`; every refusal is a `VaultError` unless named):

- `weak_mask_secret`: key not the 32-byte mask root, before the file is read (AT-V11).
- `vault_crypto_not_installed`: `cryptography` missing, before the file is read (AT-V11).
- `vault_unreadable`: OS error, unknown magic, bad header frame, JSON or field set (AT-V2).
- `vault_format_unsupported`: v2 magic or another `format` (AT-V9).
- `vault_protocol_version_mismatch`: other `SEED_PROTOCOL_VERSION` (existing test).
- `vault_key_mismatch`: KCV differs (AT-V7, AT-V8).
- `vault_tampered`: any failure after the KCV (AT-V3 to AT-V6, AT-V10).
- `FileAccessUnavailable`: path string under a non-ambient policy (unchanged, existing test).
- `ValueError`: invalid `key_version` label at `VaultWriter` construction (AT-V12).
- Success: `OpenedVault` or the `(mapping, ambiguous_dropped)` tuple.

CLI (`decoy report vault`, `decoy unmask`): exit 0 on success; exit 1 (`EXIT_USAGE`) for every vault refusal above, as today; `decoy run --vault` keeps `vault_exists` at exit 1 through `exit_codes.py` (FM-8). No exit code changes.

### 5.3 Routes

Every route writes the vault through one `VaultWriter`, so the format change reaches all of them through `serialize`:

- Plain `decoy run --vault` (resident `run_pipeline`): `vault_writer_for_config` in `C:src/decoy/cli/run/_prepare.py:562-564`, published by F22 `publish_unit` after `adopt_vault`.
- Chunked, streaming and out-of-core routes: they collect entries with `collect_vault_entries` into the same writer (`tests/sentry/test_vault_writer_routes.py` already pins that); `decoy run --chunked --vault` stays refused by the CLI (`_ChunkedVaultError`).
- `unmask_pipeline` (`unmask.py:292-295`): reads through `load_vault`.
- `decoy report vault`: reads through `open_vault` (C1).
- Direct API callers of `VaultWriter`: must pass `key_version` (Breaking fragment).

### 5.4 FK shapes

N/A: the vault stores `(namespace, masked, source)` triples per vaulted column. FK columns that are vaulted are stored like any other column; this change does not touch FK handling.

### 5.5 Fields

- Header: the closed set of eight fields in 4.1.
- `VaultHeader`: six of them (not `key_check`, not `seed_protocol_version`).
- `report vault --json`: three added keys, `format`, `key_version`, `vault_id` (4.4).
- Segment Parquet schema: `namespace`, `masked`, `source`, all string, no nulls; unchanged.

### 5.6 Output surfaces

- The vault file (format change, section 6).
- `VaultError` messages and codes (one new code).
- `report vault` text and `--json` (C1).
- `unmask` and `report vault` stderr hints (C1, one renderer).
- Docs: `docs/security/token-vault.md`, `docs/qa/16-vault-and-unmask.md`, `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`, `docs/reasons.md`, `C:docs/cli-reference.md`, `decoy explain vault`.
- No log line, no progress event and no run-result field changes.

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Vault format | `decoy-vault/v2`, `DCYVAULT2\n` | `decoy-vault/v3`, `DCYVAULT3\n` | `docs/frozen-surfaces.md` row 22 |
| Vault key label | `vault-key/v1` | `vault-key/v2` (with `vault_id`) | `docs/frozen-surfaces.md` row 23 |
| New labels | none | `vault-nonce/v1`, `key-check/v1` | new rows in `docs/frozen-surfaces.md` |
| Compat corpus | `decoy-vault-v2__synthetic.vault` | `decoy-vault-v3__synthetic.vault` (via `regenerate.py`); the v2 file moves to `tests/unit/vault/fixtures/decoy-vault-v2__retired.vault` as a refusal fixture | `tests/integration/compat_corpus/manifest.json` |
| `VaultWriter` signature | `(mask_key, *, file_access=None)` | adds required keyword `key_version` | Breaking fragment; `docs/compatibility-contract.md` pre-GA note |
| Reason registry | | `runtime.vault_tampered` | changelog fragment; registry version per the release stamp |
| CLI `report vault --json` | 6 keys | 9 keys (additive) | `C:docs/cli-reference.md`, CLI CHANGELOG |

The compatibility contract's pre-GA vault note (2026-11-12) says the v2 freeze starts at the first real v2 vault. This change lands before 1.0, so the freeze moves to the first real v3 vault. E1 updates that note.

## 7. Failure modes and partial failure

| Id | Situation | Behaviour | Test |
|---|---|---|---|
| FM-1 | Wrong secret | `vault_key_mismatch` before any decrypt; names the recorded key version | AT-V7 |
| FM-2 | Header field edited (for example `ambiguous_dropped`) | `vault_tampered` (AD mismatch) | AT-V3 |
| FM-3 | `key_check` edited | `vault_key_mismatch`. Accepted: no data comes out either way, and the remedy text covers both | AT-V8 |
| FM-4 | Segments reordered, dropped or duplicated | `vault_tampered` | AT-V4 |
| FM-5 | Truncated at a segment boundary, inside a frame, or extra bytes after the last segment | `vault_tampered` | AT-V5 |
| FM-6 | Empty vault | one last segment; round-trips; with that segment removed, `vault_tampered` | AT-V6 |
| FM-7 | v2 file passed to `load_vault`, `unmask`, `report vault` | `vault_format_unsupported` with the re-mask remedy | AT-V9, CV-3 |
| FM-8 | v2 or damaged file already at the vault path on `decoy run --vault` | `reads_as_own` is False, `adopt_vault` returns `VaultConflict`, the run refuses with `vault_exists`; the file is not overwritten | AT-V14 |
| FM-9 | Header over 4096 bytes, not JSON, or an extra key | `vault_unreadable`, no JSON parse past the cap | AT-V2 |
| FM-10 | `os.urandom` fails | the OS error propagates from `serialize`; nothing is written (publish has not started) | none (not reachable in tests; noted) |
| FM-11 | Invalid `key_version` label passed to `VaultWriter` | `ValueError` at construction, fixed text | AT-V12 |
| FM-12 | Error text | no source value, no masked value, no key, no KCV; the vault is named only by its handle display | AT-V17 |
| FM-13 | Partial write | unchanged: `publish` is the F22 atomic publish; a failed publish leaves no vault leaf and no `VaultCommit` | existing F22 tests |
| FM-14 | Same secret, two runs | two different `vault_id`s, two different keys and nonce prefixes | AT-V10 |

## 8. Acceptance tests (red first)

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the final slice head.

### 8.1 Engine

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-E0 | `scripts/check_pure_move.py` over the E0 diff; `from decoy_engine.vault import <each name in the old module's public set>` resolves; the `fileaccess` entry-point sentry passes with the new module paths | no package | leave one `ENTRY_POINTS` name on `decoy_engine.vault.load_vault` | E0 |
| AT-V1 | `tests/unit/vault/test_v3_format.py::test_round_trip_and_header`: write rows with one ambiguous pair; `open_vault` returns the mapping, `ambiguous_dropped == 1`, header `format == "decoy-vault/v3"`, `key_version == "v1"`, 64-hex `vault_id`, `entry_count == len(mapping)`; the file starts with `DCYVAULT3\n` | v2 writer | drop `entry_count` from the header | E1 |
| AT-V2 | `test_v3_format.py::test_header_closed_set` (cells: extra key, missing key, bool `entry_count`, 4097-byte header, non-JSON) | no closed-set check | accept unknown keys | E1 |
| AT-V3 | `tests/unit/vault/test_v3_tamper.py::test_header_edit_is_tampered`: rewrite `ambiguous_dropped` 0 to 5 and re-frame | Fernet ignores the header | pass `None` as associated data to encrypt and decrypt | E1 |
| AT-V4 | `test_v3_tamper.py::test_segment_order` (cells: swap segments 0 and 1, drop segment 1, repeat segment 0), with `segment_rows` patched to 2 and 5 rows | Fernet tokens are independent | build the nonce without the counter | E1 |
| AT-V5 | `test_v3_tamper.py::test_truncation` (cells: drop the last segment, cut inside a frame, append one byte) | v2 reads to the end | ignore the last flag on read | E1 |
| AT-V6 | `test_v3_tamper.py::test_empty_vault` (round-trip; then remove the only segment) | v2 writes no chunk for no rows | write zero segments when there are no rows | E1 |
| AT-V7 | `test_v3_tamper.py::test_wrong_key_is_key_mismatch`: second 32-byte key; code `vault_key_mismatch`; message holds `"v1"`; a spy on `AESGCM.decrypt` saw no call | v2 has no KCV | skip the KCV compare (the code becomes `vault_tampered`) | E1 |
| AT-V8 | `test_v3_tamper.py::test_kcv_edit_is_key_mismatch` | no KCV | treat a KCV mismatch as tampered | E1 |
| AT-V9 | `test_v3_format.py::test_v2_refused_with_remedy`: the retired fixture; code `vault_format_unsupported`; message holds "re-run" and "--vault" | v2 opens | drop the v2-magic branch (the code becomes `vault_unreadable`) | E1 |
| AT-V10 | `test_v3_format.py::test_per_vault_key`: same key and rows, two writes: different `vault_id`; first segments differ; a segment spliced from vault A into vault B gives `vault_tampered`; the key-derivation input differs for two ids | one key per secret | drop `vault_id` from the key label | E1 |
| AT-V11 | existing key-floor and crypto-missing tests in `tests/unit/test_vault.py` pass with v3 | n/a (guard) | move the floor check after the file read | E1 |
| AT-V12 | `test_v3_format.py::test_key_version_required` (no keyword: `TypeError`; `"bad label"`, `"v1\n"`: `ValueError`) | no keyword | use `re.match` instead of `is_key_version_label` | E1 |
| AT-V13 | `tests/unit/vault/test_v3_config.py`: `vault_writer_for_config` with a provider whose `key_version` is `"v7"` writes header `key_version == "v7"` | no stamp | hard-code `"v1"` | E1 |
| AT-V14 | `tests/fileaccess/publication/test_vault_adopt.py` new cells: a v2 file and a tampered v3 file at the leaf give `VaultConflict` and the file bytes are unchanged; the existing adopt cells pass | v2 cell: on the base a v2 file at the leaf adopts | return True from `reads_as_own` on `vault_format_unsupported` | E1 |
| AT-V15 | compat corpus: the v3 synthetic artifact round-trips; `test_harness_bites_on_corruption` asserts `vault_tampered` | corpus holds v2 | flip the asserted code in the meta-test | E1 |
| AT-V16 | secret-material census and frame tests (`tests/fileaccess/test_secret_material_frames.py`) cover `_open_vault`, the segment encrypt and decrypt helpers and `key_check_value`: no 32-byte key or derived key is a local in any failing frame | new functions not in the census | bind `K_vault` to a local in the decrypt helper | E1 |
| AT-V17 | `test_v3_tamper.py::test_no_values_in_errors`: for every refusal cell above, `str(exc)` and the chained causes hold no source value, no masked value and no KCV | n/a | put the KCV in the mismatch message | E1 |
| AT-V18 | `tests/sentry/test_vault_crypto_choke_point.py` (AST walk of `src/`, resolving aliases and re-exports): `cryptography.hazmat.primitives.ciphers.aead` is imported only in `vault/_format.py` (allowlist of one; any existing importer found by the walk is listed by name with a reason); the bytes `b"key-check/v1"` and `b"vault-nonce/v1"` appear once in `src/`; seeded cells fail | no sentry | add an `AESGCM` import to `vault/_reader.py` | E1 |
| AT-R1 | reason tests: `runtime.VAULT_TAMPERED` registered, `since=UNRELEASED`; the changelog fragment passes `tests/unit/scripts/test_check_fragment.py` | no reason | remove the fragment | E1 |
| AT-D1 | `tests/unit/reasons/test_reasons_doc_consumers.py`: `docs/reasons.md` has a "Consumers" heading; every `reasons.<ns>.<NAME>` symbol it names resolves in the registry; it names `APPROVED_ERROR_MESSAGES` | no section | rename one symbol in the doc to a name that does not exist | E7 |

### 8.2 CLI

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| CV-1 | `C:tests/e2e/vault/test_report_vault_v3.py`: `decoy run --vault` then `decoy report vault --json`: the 9 keys, `format == "decoy-vault/v3"`, `key_version == "v1"`, 64-hex `vault_id`; text mode shows `format`, `key version` and 12 hex characters of the id | 6 keys | drop `key_version` from the JSON | C1 |
| CV-2 | `test_report_vault_v3.py::test_tampered`: flip one byte in the last segment: exit 1, stderr `vault_tampered` and the tamper hint; no row value on stdout or stderr | v2 engine | route `vault_tampered` to the fallback branch (no hint) | C1 |
| CV-3 | `test_report_vault_v3.py::test_v2_refused`: the retired v2 fixture: exit 1, `vault_format_unsupported` and the re-mask hint | v2 opens | drop the remedy hint | C1 |
| CV-5 | `C:tests/e2e/vault/test_vault_error_parity.py`: for `vault_tampered`, `vault_key_mismatch`, `vault_format_unsupported`, `decoy unmask` and `decoy report vault` give the same message and hint | unmask has its own branch | restore unmask's own `except VaultError` text | C1 |
| CV-6 | `test_report_vault_v3.py::test_wrong_secret`: a second secret: exit 1, `vault_key_mismatch`, the message holds the key version | v2 text | swap the hints of `vault_key_mismatch` and `vault_tampered` | C1 |
| CV-7 | `C:tests/sentry/test_vault_error_one_renderer.py` (AST walk): in `src/decoy/cli`, every `except VaultError` handler calls `vault_error_text`; `run/_errors.py` and `exit_codes.py` (classifiers that print no text) are the listed exceptions; seeded cell fails | no sentry | add a handler that formats `exc.code` itself | C1 |

F09 CV-4 (domain versions in the report) is Later and not in this plan.

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"; the package root is at its fan-out cap, and turning `vault.py` into `vault/` keeps the root count the same):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/vault/__init__.py` | new (E0): docstring and public re-exports, same names as `vault.py` | Public API; a sub-package because the root is at its fan-out cap, as `_canonical/` and `_nested_json/` | `publication/` |
| `src/decoy_engine/vault/_format.py` | new (E0 move of framing and Fernet helpers; E1 replaces them with the v3 header and segment encrypt and decrypt) | same; the one crypto and layout module | |
| `src/decoy_engine/vault/_writer.py` | new (E0 move): `VaultWriter`, `VaultCommit`, `issue_commit`, `_publish` | same | |
| `src/decoy_engine/vault/_reader.py` | new (E0 move): `load_vault`; E1 adds `_open_vault`, `open_vault`, `OpenedVault`, `VaultHeader` | same | |
| `src/decoy_engine/vault/_config.py` | new (E0 move): `vault_writer_for_config`, `assert_vault_writer_keyed` | same | |
| `src/decoy_engine/vault.py` | deleted (E0) | | |
| `src/decoy_engine/keyprovider.py` | changed (E1, about +15): `key_check_value` | Foundation (keys) | `is_key_version_label` |
| `src/decoy_engine/reasons/runtime/_part3.py` | changed (E1, about +8): `VAULT_TAMPERED` | Reason codes | the other `VAULT_*` entries |
| `src/decoy_engine/fileaccess/__init__.py` | changed: `ENTRY_POINTS` names (E0), `open_vault` (E1) | Secret providers, file access | |
| `src/decoy_engine/__init__.py` | changed (E1): three exports | Public API | line 335 |
| `CODEMAP.md` | changed (E0): a "Token vault" row | | |
| `.importlinter` | changed only if a contract names `decoy_engine.vault` in a way a package breaks (E0 checks; a package keeps the name) | Layer contracts | |
| `tests/unit/vault/test_v3_format.py`, `test_v3_tamper.py`, `test_v3_config.py`, `_support.py`, `fixtures/decoy-vault-v2__retired.vault` | new (E1) | Unit tests (mirrors `vault/`) | `tests/unit/vault/test_run_entries.py` |
| `tests/sentry/test_vault_crypto_choke_point.py` | new (E1) | Sentry test | `tests/sentry/test_vault_writer_routes.py` |
| `tests/integration/compat_corpus/` | changed (E1) | compat corpus | |
| `tests/unit/reasons/test_reasons_doc_consumers.py` | new (E7) | Unit tests | reason tests |
| `docs/security/token-vault.md`, `docs/qa/16-vault-and-unmask.md`, `docs/frozen-surfaces.md`, `docs/compatibility-contract.md` | changed (E1) | Feature and contract docs; QA checklists | |
| `docs/reasons.md` | changed (E7) | Feature and contract docs | |
| `changelog.d/vault-v3-header.md` | new (E1, Breaking and Added) | Changelog fragments | |

CLI (rows of `C:CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `C:src/decoy/cli/vault/__init__.py`, `_errors.py`, `_report.py` | new | Command-private helpers: a named sub-package below `src/decoy/cli/` (the flat folder is frozen) | `cli/run/`, `cli/library/` |
| `C:src/decoy/cli/report.py` | changed (about -150): registration line only for `vault` | Command module | |
| `C:src/decoy/cli/unmask.py` | changed (about -15) | Command module | |
| `C:tests/e2e/vault/` | new | E2E tests | `tests/e2e/dup_freeze/` |
| `C:tests/sentry/test_vault_error_one_renderer.py` | new | Sentry test | |
| `C:docs/cli-reference.md`, `C:src/decoy/cli/explain.py` (vault topic text), `C:CHANGELOG.md`, `C:CODEMAP.md` | changed | docs | |

## 10. Design notes

- Choke points.
  - Engine format and crypto: `vault/_format.py` is the only module that knows the magic, the header fields, the nonce layout and the AEAD. The writer and the reader call only its encode and decode functions. Guard: AT-V18. Mutation: an `AESGCM` import in `vault/_reader.py`.
  - Engine KCV: `keyprovider.key_check_value` is the only KCV. Guard: AT-V18 (label appears once).
  - Engine read path: `_open_vault` is the only reader; `load_vault`, `open_vault` and `reads_as_own` call it.
  - CLI: `decoy.cli.vault._errors.vault_error_text` is the only vault error renderer. Guard: CV-7. Mutation: a second handler that formats the code itself.
- E0 is a named refactoring: Move Module (Fowler, Move Function applied to a whole module), with no body change. A pure move first is needed because `vault.py` is 596 lines on main and E1 adds about 250 net: 850 lines in one module is past the 800 rule and the census ceiling of 700. `check_pure_move.py` proves E0, and E1's diff is then behaviour only.
- Why `key_version` is required, not defaulted: a default of `"v1"` would write a false label for any provider with another label. The 25 test constructors go through one helper, so the cost is one line per file.
- Why `load_vault` keeps its tuple: F22 (`reads_as_own`), `unmask.py` and the compat corpus call it. `open_vault` adds the header without a second read of the file (a second read could see a different file).
- Why a KCV in the header (owner Q1, recommended yes): without it, a wrong key and a damaged file both fail the first GCM tag, and the user gets one message for two problems with different fixes. The KCV is 64 bits from its own HKDF label; the mask root is 32 random bytes (floor enforced), so the KCV gives no useful offline guess.
- The nonce prefix is derived, not random: `K_vault` is already unique per vault, so a derived prefix is safe and keeps the header smaller. Tink stores a random prefix in its own header; the effect (unique nonces per key) is the same.
- `segment_rows` stays 65536 (today's `_CHUNK_ROWS`). The F13 rule (no single plaintext blob before encryption) holds.
- Logs: no new log lines. Error text carries codes, the key version label and the handle display, never values (log hygiene).

## 11. Size

| Slice | Src lines | Test lines | Docs lines | Files touched |
|---|---|---|---|---|
| E0 | about 620 moved, about +40 net (package init, entry-point names) | about 40 (import paths, monkeypatch targets) | 5 (CODEMAP row) | about 12 |
| E1 | about +260 net | about +520 | about +90 | src 6, tests about 30 (25 one-line helper edits), docs 4, fixtures 3 |
| E7 | 0 | about +40 | about +60 | 2 |
| C1 | about +170 new, about -165 moved out | about +260 | about +30 | src 5, tests 4, docs 4 |

Every slice is under 800 changed lines of product code. `report.py` shrinks; no file in the plan crosses its size ceiling.

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| E0 | engine | Move Module: `git mv` of `vault.py` into `vault/` (four private modules plus the facade), body unchanged; `ENTRY_POINTS` names; secret census paths; monkeypatch targets in tests; CODEMAP row; `docs/frozen-surfaces.md` path column | R1 (pure move) | AT-E0 | none | T1 impact set (vault, fileaccess, publication, unmask, sentry); `check_pure_move.py`; Codex review |
| E1 | engine | v3 format, KCV, `open_vault`, `vault_tampered`, required `key_version`, corpus swap, retired v2 fixture, sentry, docs, Breaking fragment | R2 (crypto, frozen format) | AT-V1 to AT-V18, AT-R1 | E0 | T1 on the head plus T2: each named mutation on `vault/_format.py`, `vault/_reader.py` and `key_check_value`; compat corpus; secret census. Dennis then Codex, crypto brief |
| E7 | engine | `docs/reasons.md` "Consumers"; the doc test | R0 | AT-D1 | none | T0 |
| C1 | CLI | `cli/vault/` sub-package, `report vault` move and new fields, one error renderer, `unmask` uses it, sentry, docs | R2 (frozen `--json` additive, error text) | CV-1, CV-2, CV-3, CV-5, CV-6, CV-7 | the engine release that carries E1, the CLI repin to it, and row 24zw C1 merged | T1 (`tests/e2e/vault/`, unmask and report e2e, sentries) plus T2 on the head; Codex, plus Dennis if the gate asks |

Order and timing: E0 and E7 can start now. E1 follows E0 and should merge in time for the last daily engine release before D-4; target 2026-11-27 (CST) so that C1 has a week before 2026-12-04. C1 rides the repin that follows that release. It is not part of the 0.28.0 repin.

Open PRs that touch the same files (checked 2026-11-18 about 14:00 CST):

- `vault.py` and `keyprovider.py`: E#333, a parked draft ("do not merge alone"), not a 1.0 row. It re-anchors after E0.
- `reasons/runtime/_part3.py`: E#684, E#691, E#661.
- `docs/frozen-surfaces.md`: E#685, E#662, E#643.
- `docs/reasons.md`: E#647, E#661, E#561, E#557, E#555, E#546, E#523.
- Compat corpus: E#686.
- CLI `report.py`: C#301, C#68. CLI `unmask.py`: C#68.

The engine files are ledger-style; keep both sides on rebase. C1 rebases after the CLI PRs that merge first; the move takes the text as it is on main.

## 13. Recurring-defect class check

- Value-free errors (F31 class): every new refusal has fixed text plus non-secret fields only; AT-V17.
- Secret in a traceback frame: new functions join the census; AT-V16.
- Two copies of a central mechanism: one crypto module, one KCV, one reader, one CLI renderer, each with a guard test.
- A test weakened to pass: the existing vault tests keep their assertions; only constructor calls and v2-specific header assertions (`chunk_rows`, `chunk_count`) change, and the gate diff-checks them.
- A frozen surface changed without its records: `docs/frozen-surfaces.md`, the compat corpus, the compatibility contract note and the Breaking fragment move together in E1.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (source or masked values, the key, the KCV in error text or tracebacks) | fixed messages with codes and the key version label only; raise outside `except`; key boxed and derived keys never locals | AT-V16, AT-V17, CV-2 | put the KCV in the mismatch message; bind `K_vault` to a local | E1, C1 |
| 2 | Cleanup on every exit | no new resource: the file is read into memory once and the handle closes in the existing `finally`; a refused read returns nothing; the publish path is F22's | existing `load_vault` handle tests; AT-V14 (file bytes unchanged on refusal) | return the partial mapping on a tamper | E1 |
| 3 | State completeness (every read outcome covered) | the read order in 4.2 is one ordered list; each step has its own code and its own cell | AT-V2 to AT-V12 (one cell per exit path in 5.2) | merge `vault_tampered` into `vault_unreadable` | E1 |
| 4 | Route coverage | one writer for all routes (5.3); `tests/sentry/test_vault_writer_routes.py` keeps every route on it | existing route sentry plus AT-V13 | build a second writer in a route | E1 |
| 5 | Referential integrity | N/A: no FK or cross-table state changes (5.4) | none | none | none |
| 6 | Untrusted input (the vault file is read from disk) | magic, a 4096-byte header cap, a closed field set with strict types before any parse result is used; AEAD over every segment | AT-V2, AT-V3, AT-V5 | lift the header cap | E1 |
| 7 | TOCTOU (header read and data read seeing different files) | one read of the file into memory; `open_vault` returns the header and the mapping from the same bytes | AT-V1 (header and mapping from one call) | read the header in a second `read_all` | E1 |
| 8 | Weak proof (a wrong key reported as damage, or damage accepted) | KCV before decrypt; AEAD tag, counter, last flag and `entry_count` all checked | AT-V4 to AT-V8 | skip the `entry_count` check | E1 |
| 9 | Refactor drift (behaviour change hidden in the move) | E0 is a pure move proven by `check_pure_move.py`; behaviour lands only in E1 | AT-E0 | change one line inside a moved body | E0 |
| 10 | Frozen contract drift | format, labels, corpus, contract note and fragment change together; `--json` change is additive | AT-V15, CV-1, `docs/frozen-surfaces.md` rows | keep `decoy-vault/v2` in the frozen-surface row | E1, C1 |

## 14. Pre-mortem

- "E1 broke F22 adopt." Guard: AT-V14 plus the unchanged F22 suites in the T1 set; `serialize`, `reads_as_own` and `load_vault` keep their contracts.
- "A builder hand-rolled a cipher." Guard: section 2 names `AESGCM`; AT-V18 pins the import to one module.
- "A wrong key now says tampered and users delete good vaults." Guard: AT-V7 and CV-6.
- "The move to `cli/vault/` lost the 24zw help fix." Guard: C1 depends on 24zw C1.
- "The vault format changes again after 1.0 for domain versions." The 1.1+ domain-version work adds fields in a later format version on top of this one. The header is a closed set so that change is explicit. This plan does not pre-add 1.1+ fields.

## 15. Owner questions (taken on the recommended answer; owner to confirm)

| Id | Question | Recommended | Source |
|---|---|---|---|
| Q1 | Put a key check value in the header? | Yes | F09 Q1 |
| Q2 | Hard cut from v2, no v2 reader? | Yes (matches the B-6 decision of 2026-11-13 and the pre-GA rule) | F09 Q2 |
| Q4 | Leave the SQLite `decoy tokenize --vault` store out? | Yes | F09 Q4 |
| Q-A | Show 12 hex characters of `vault_id` in text mode, the full id in `--json`? | Yes | new |
| Q-B | Segment framing on `cryptography` following Tink's layout (section 2.1), not the `tink` library? | Yes | new (security exception) |

F09 Q3 and Q5 to Q7 are about domain versions and stay with the 1.1+ plan.

## 16. Unresolved

None for the build. If the owner answers Q2 "keep a v2 reader", E1 grows by a read-only v2 path (about 120 lines) and AT-V9 inverts; the rest of the plan is unchanged. If Q-B is answered "use Tink", see section 2.1.
