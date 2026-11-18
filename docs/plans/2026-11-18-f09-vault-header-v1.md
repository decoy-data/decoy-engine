Status: plan (revision 2.1, 2026-11-18; Dennis round 1 and Codex plan gate folded; owner answers of 2026-11-18 recorded)

# F09 1.0 cut: authenticated, versioned vault header (roadmap row 79) and the F29 close-out (row 66)

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-18, revision 2 the same day.

Roadmap row 79 (F09) was split by the 1.0 scope triage on 2026-11-18 (`C:docs/records/2026-11-18-1.0-scope-triage.md`, row 79): "1.0: the authenticated, versioned token vault header (freeze: the vault format). 1.1+: domain versions, rotation, remap." This plan is the 1.0 half only. The full F09 plan (`E:plan/f09-domain-version`, revision 3, base `dcc4bcb3`, 2026-11-15) stays the source for 1.1+. That plan was written before F22 b1 (#607) and b2 (#622) moved the vault adopt path into `publication/_vault_order.py`, so its E0 and E1 cannot be built as written. This plan re-cuts and re-anchors them.

Row 66 (F29 remainder) is batched here because only its docs slice is left: C0 merged (engine #367), C1 shipped as CLI #229 ("one engine reason in the --json failure envelope"), and P1 and P2 are platform slices, parked with the platform. E7 (a "Consumers" section in `docs/reasons.md`) is about 60 lines and touches no vault file, so it rides as its own small slice.

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI repository (decoy). Engine `origin/main` `ad36687a6`; CLI `origin/main` `920ea13c`.

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, non-goals, size, design notes, choke point, placement, established solutions, acceptance tests first), `security.md` (vetted crypto, no custom protocol, secrets out of errors), `config-secrets-and-supply-chain.md` (a new pinned dependency), `api-and-compatibility.md`, `data-and-migrations.md`, `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation), `refactoring.md` (pure move first), `reuse-first.md`, `testing.md` (T0 to T2, escalation triggers, mutations), `proportionality.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`.

Risk: R2 overall. E1 changes a frozen on-disk format and the crypto of the most sensitive artifact the engine writes. E-DEP adds a base dependency (a dependency-lock change, so a full-suite escalation trigger). E0 is R1 (pure move). E7 is R0 (docs plus one doc test). C1 is R2 (a frozen `--json` shape gets new keys, error text changes, and the certified dependency set moves). Approver: Cam (owner). Plan gate: Dennis round 1 (GO-WITH-FIXES) and Codex (GO-WITH-FIXES on `fe357ec37`) both folded here. Build gates for E-DEP, E1 and C1: Dennis then Codex.

Why 1.0: row 79's 1.0 test is "freeze". `decoy-vault/v2` becomes permanent at the first real v2 vault under the compatibility contract (section 3.2, pre-GA vault key floor note). After 1.0 a header change costs a second hard cut and a reader kept forever. The 1.0 build target is 2026-12-04 and the D-4 engine freeze follows it; this plan targets the E1 merge for 2026-11-27 (section 12) so that C1 lands before the build target.

## Owner decisions (2026-11-18)

- Decision 2026-11-18 (Q-B, framing): C. The segment stream is libsodium `crypto_secretstream_xchacha20poly1305` through PyNaCl. Not our own AES-GCM framing, not Tink. The security exception record of revision 1 is dropped: no framing code of ours remains. PyNaCl becomes a pinned base dependency (section 2.2).
- Decision 2026-11-18 (Q2, v2 reader): approved. Hard cut of `decoy-vault/v2`, with no v2 reader. No real v2 vault exists outside Decoy's own machines. This is the PO review that the compatibility contract section 3.2 and its section 5 decision table ("Any change to vault read/write") ask for.
- Decision 2026-11-18 (census growth, Dennis H3): the recommended design. Key material reaches the new code only through `PreparedSecret` and key-source callables, so E1 adds no key-bearing frame and the census baseline does not grow.
- Decision 2026-11-18 (Q1, KCV binding): the recommended design. The KCV is bound to `vault_id`, so each vault's check value is unique and does not link vaults written under one secret.
- Decision 2026-11-18 (M6, `VaultWriter` signature): the recommended design for the census, `VaultWriter(prepared)`, the `PreparedSecret` signature of F09 revision 3.

Q4 and Q-A (section 15) are still open, each with a recommendation. Neither blocks a slice.

## Revision 2 changes

Dennis round 1 on `ecbfe65ab`: GO-WITH-FIXES (0 BLOCKER, 4 HIGH, 8 MEDIUM, 7 LOW). Each finding and the owner answers are folded as below.

| Finding | Change in this revision | Where |
|---|---|---|
| H1 engine `unmask.py:294-297` re-raises every `VaultError` as `ExecutionError(code=exc.code)`, and the CLI catches `(ExecutionError, ConfigError)` (`C:src/decoy/cli/unmask.py:245`) before `except VaultError` (`:248`) | `vault_error_text` takes `(code, message)`. The CLI routes any exception whose `code` is in one vault code set (the engine's `VAULT_REFUSAL_CODES`, built from `reasons.runtime` constants), whatever its class. CV-5 runs the real `unmask` path. CV-7 fails on vault-code text built anywhere outside `cli/vault/_errors.py`, inside `ExecutionError` branches too | 4.4, 8.2 |
| H2 a KCV already exists in `delivery/resume/_fingerprint.py:28,109-118` | One function `key_check_value(key_source, label, context="")` in `internal/crypto.py` with one label table. Resume moves onto it byte for byte (its store is frozen). A sentry fails on any other KCV construction. Why a key-source callable and not raw bytes or a `PreparedSecret` method: section 10 | 4.3, 8.1 AT-K1 to AT-K3, 10 |
| H3 the secret-material census is shrink-only | Owner chose the no-growth design. Section 6.1 names every census, registry and frozen-surface key that moves, shrinks or is added. AT-V16 fails on any added census entry that is not a `moved_from` rehome | 6.1, 8.1 |
| H4 two named mutations could not turn red | A `_format` test seam (`_open_stream`, `_push_segment`, the `_HEADER` declaration) lets tests build authenticated but inconsistent files. AT-V5b and AT-V5c cover "no final tag" and "entry_count off by one". "Ignore the final tag" is defined precisely | 8 |
| M1 the framing record overstated "copies Tink" | Superseded by owner decision Q-B C: libsodium secretstream does the framing. Section 2 cites the libsodium documentation; section 2.1 lists only what Decoy adds around the stream. Known-answer test AT-V19. `vault/_format.py` registered in `docs/methodology-registry.yaml` with a `Pattern:` line | 2, 2.1, 8.1, 9 |
| M2 no byte cap per segment | Plaintext cap of 64 MiB per segment (secretstream allows about 256 GB per message, so the cap bounds memory, not the cipher). The writer halves a row window that is too big. One entry over the cap gives `vault_entry_too_large`. The reader refuses a frame longer than the cap plus 17 bytes before it decrypts. AT-V20 | 4.1, 4.2, 8.1 |
| M3 `vault_id` lifetime | Drawn fresh in every `serialize()` call, never cached. AT-V21 | 4.1, 8.1 |
| M4 adopt conflict code | The refusal is `publication_vault_conflict` (`publication/_publish.py:315-318`), not `vault_exists` | 5.2, 7 FM-8, AT-V14 |
| M5 magic and header model | Any `DCYVAULT<n>\n` other than 3 is `vault_format_unsupported`; `format` is checked before the closed set; one header model for writer and reader; bool and numeric-string cells; fullmatch cells for hex fields | 4.1, 4.2, AT-V2 |
| M6 `VaultWriter` signature | Decided: `VaultWriter(prepared)` | 4.3 |
| M7 Q2 status | Decided 2026-11-18 (approved), recorded as the contract 3.2 PO review, with the B-6 difference stated | Owner decisions, 6 |
| M8 C1 gate | Dennis is required at the C1 gate | 12 |
| L1 | The KCV is bound to `vault_id` (decision Q1), so it does not link vaults. The "32 random bytes" claim is fixed: the mask root is an HKDF output of the secret, and the KCV is an offline check of that secret (FM-17) | 4.1, 7 |
| L2 | "Recorded key_version" in the message; the hint covers both causes | 4.2, 4.4 |
| L3 | Additional data over the magic and header frame bytes as read; duplicate JSON keys refused | 4.2 |
| L4 | The existing `cryptography` AESGCM import at `secret_providers/_requirements.py:91` stays and is out of this change. CV-7 lists the spellings it catches. C1 compares with reason constants | 8.2 |
| L5 | "FIPS" dropped | 2 |
| L6 | Namespace reservation recorded as a follow-up | 17 |
| L7 | AT-V17 asserts `__cause__` and `__context__` are None | 8.1 |

## Revision 2.1 changes

Codex plan gate on `fe357ec37`: GO-WITH-FIXES (3 V1, 1 DESIGN, 3 V2-LOG). It confirmed the core crypto design. Each finding is folded:

| Finding | Change | Where |
|---|---|---|
| V1 DP certification in the wrong slice: promoting PyNaCl to the base closure changes the engine DP lock fingerprint when E-DEP lands, and `tests/sentry/test_dp_lock_row.py:71` requires `_CERTIFIED_STACKS` to move in the same lock change | E-DEP adds the new engine-profile row to `quality/dp_provenance.py` `_CERTIFIED_STACKS` (released rows kept). Before the engine release that carries E1, release prep adds the projected CLI runtime row (new engine version plus PyNaCl). C1 pins the matching `requirements-certified.txt` header. AT-P3 | 2.2, 8.1, 12 |
| V1 the tamper guarantee contradicted the reader: with the right secret, an edited `key_check` or `vault_id` fails the KCV check first and gives `vault_key_mismatch` | Guarantee 1 and 3, read step 6 and FM-3 now say so. A KCV mismatch means a different secret or an edited `key_check` or `vault_id`; the engine cannot tell these apart, and the hint names both fields. New cell AT-V8b for a `vault_id` edit | 1.1, 4.2, 7, 8.1 |
| DESIGN `_VaultHeaderModel` plus `object_pairs_hook` copied the central strict-record machinery | The header is one `ObjectSpec` declaration built from `decoy_engine._canonical` (`ExactSpec`, `VersionSpec`, `CountSpec`, `ShapedSpec`), read with `parse_or_token` and `attempt`, written with `canonical_json_bytes(spec.dump(...))`, as `delivery/resume/_records.py` does. Only the vault rules stay local: `format` first, `segment_rows != 0`, and the mapping from closed tokens to vault codes | 4.1, 4.2, 8, 9 |
| V1 AT-V19 could not exercise production: `_open_vault` returns rows decoded from Parquet, but the fixture used raw `b"segment-0"` | The fixture is a whole v3 vault file made once by the production writer, with real Parquet segments. The test asserts the mapping and header through `_open_vault`, and separately decrypts the same frames with raw PyNaCl bindings and reads the plaintexts with pyarrow. Stored bytes make the fixture independent of the pyarrow version that reads it | 8.1 |
| V2-LOG D-4 date | Line on why 1.0 corrected: build target 2026-12-04, E1 target 2026-11-27 | top |
| V2-LOG the wheel-tag check is not an install test | 2.2 says AT-P1 reads wheel tags only; a real Windows install, import and secretstream smoke belongs to WIN-FEAS (row 89) and WIN-RUNNER (row 6), recorded as a follow-up | 2.2, 17 |
| V2-LOG wording | 2.1 says "no custom cipher or AEAD construction" | 2.1 |

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. A vault written by this engine is `decoy-vault/v3`. Its segments are one libsodium secretstream, and the header is bound to every segment as additional data. Every change to the file is refused and no partial mapping is returned. With the right secret: an edited `key_check` or `vault_id` gives `vault_key_mismatch` (the KCV check runs first; see 3); an edited `format` gives `vault_format_unsupported`; an edited `seed_protocol_version` gives `vault_protocol_version_mismatch`; a header that breaks the field rules gives `vault_unreadable`; any other header edit that keeps the rules (`key_version`, `stream_header`, `ambiguous_dropped`, `entry_count`, `segment_rows`), any reordering, dropping, duplication or truncation of segments, a stream without its final tag, and any bytes after the final segment give the new code `vault_tampered`.
2. Each vault has its own key. `vault_id` is 32 bytes from `os.urandom`, drawn fresh in every `serialize()` call, and the stream key is `derive(mask_key, "vault", b"vault-key/v2" + uint32be(32) + vault_id)`. Two vaults written under the same secret never share a key.
3. The header carries a key check value (`key_check`) bound to `vault_id`. A KCV mismatch is refused with `vault_key_mismatch` before any segment is decrypted, and the message names the vault's recorded `key_version`. A mismatch has two possible causes that the engine cannot tell apart: a different secret, or an edited `key_check` or `vault_id` field. The hint names both, including both field names. Damage anywhere else, with the right secret, gives `vault_tampered`.
4. The header records `key_version` (the prepared secret's non-secret label) and `entry_count`. `decoy report vault` shows the format, the recorded key version and a short vault id, and its `--json` gains `format`, `key_version` and `vault_id`.
5. A file with any other vault magic (`DCYVAULT2\n` today) is refused with `vault_format_unsupported` and a remedy: re-run the mask with `--vault` under this version (decision Q2).
6. Every existing guarantee holds: the 32-byte key floor (`weak_mask_secret` before any file is read), `vault_crypto_not_installed` (now about PyNaCl), `vault_protocol_version_mismatch`, no key in any traceback frame (`_opaque` rules and the secret-material census, which does not grow), no value and no path in error text, F22 adopt-or-refuse (`adopt_vault`, `issue_commit` as the only `VaultCommit` issuer), and the existing public names other than the `VaultWriter` constructor.
7. The engine has one key check value function. The resume store's KCV moves onto it with byte-identical output.
8. The CLI renders every vault refusal from one function keyed on the reason code, whatever exception class carries it, so `decoy unmask` and `decoy report vault` give the same text and hint for the same code.
9. Row 66: `docs/reasons.md` names every consumer of the reason registry and the limits of each.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- Domain-version objects, rotation, remap, preview and evidence (full F09 E2 to E5). Later, on `E:plan/f09-domain-version`.
- The SQLite token store that `decoy tokenize --vault` writes (`C:src/decoy/cli/_token_vault.py`). Owner Q4 (open; recommended out).
- A v2 reader, a migration tool or a `decoy vault upgrade` command (decision Q2).
- Streaming reads of very large vaults. `load_vault` still reads the whole file, as today.
- Byte-reproducible vault files. The file was never reproducible (Fernet had a random IV and a timestamp); v3 has a random `vault_id` and a random secretstream header.
- Hostile in-process attackers (V1 threat model: accidental leaks only). The tamper check guards against a damaged or edited file at rest, not against code that runs inside the engine.
- Platform consumers of reasons (F29 P1, P2). Parked with the platform.
- Changing engine `unmask.py`'s `ExecutionError` wrapping of `VaultError`. The CLI keys on the code instead (H1).
- Moving FF1 or the `secret_providers` key-size probe off `cryptography`. Only the vault changes cipher.

## 2. Established solutions

| Need | Established solution | What we take | What we do not take, and why |
|---|---|---|---|
| Encrypt a long plaintext in segments so that modify, reorder, drop, duplicate and truncate are detected | libsodium `crypto_secretstream_xchacha20poly1305` ([libsodium documentation, "Encrypted streams and file encryption"](https://doc.libsodium.org/secret-key_cryptography/secretstream)), through PyNaCl 1.6.2 `nacl.bindings` | The whole stream: `init_push` and `init_pull` with a 24-byte header, `push` and `pull` per segment with additional data, `TAG_MESSAGE` for every segment but the last and `TAG_FINAL` for the last. libsodium: "Messages cannot be truncated, removed, reordered, duplicated or modified without this being detected by the decryption functions." Its own file example rejects a `TAG_FINAL` before the end of the file and an end of file without one; the reader does the same | `TAG_PUSH` and `TAG_REKEY` (never written; refused on read). Our own AES-GCM framing (revision 1) and Tink: owner decision Q-B |
| Limits | libsodium: at most `MESSAGEBYTES_MAX` (about 256 GB) per message; "There are no practical limits to the total length of the stream, or to the total number of individual messages"; "Rekeying happens automatically and transparently, before the internal counter of the underlying cipher wraps" | No message-count limit to enforce; a 64 MiB plaintext cap per segment for memory (M2) | |
| Header binding | Additional data in each `push` (libsodium: "Additional data ad of length adlen can be included in the computation of the authentication tag") | `ad = SHA-256(the magic and header frame bytes exactly as read)` on every segment | A separate header MAC |
| Per-vault key | RFC 5869 HKDF, already the engine's `derive` (`determinism/_derive.py:260`) | `vault-key/v2` with `vault_id` under the existing `derive` | A second KDF |
| Tell a wrong key from a damaged file | Key check value (PKCS#11 `CKA_CHECK_VALUE`; payment HSM practice), already used by the resume store (`delivery/resume/_fingerprint.py:3-5`) | The resume store's construction, `hmac_hex(key, label)[:16]`, moved to one function and reused with `vault_id` as context | A second construction (H2) |
| Precedent for a published construction behind a vetted library | `docs/security/de-01-ff1-adoption.md` (FF1 on `cryptography` with NIST vectors) | Same record shape: cite the source, pin known answers (AT-V19) | |
| Format versioning | `docs/frozen-surfaces.md`; compatibility contract sections 1, 3.2, 4.5 and the section 5 decision table | New magic `DCYVAULT3\n` and `format: decoy-vault/v3` | |

### 2.1 What Decoy adds around the stream, and why

libsodium does all segment encryption, nonces, counters, rekeying and the end-of-stream marker. Decoy adds only the parts the stream does not have:

| Added | Why |
|---|---|
| The magic and a JSON header in the file, bound as additional data on every segment | The reader must refuse old formats and show `key_version` before it decrypts anything |
| `vault_id` and a per-vault key from `derive` | The KCV must not link vaults (decision Q1), and a key per vault keeps the existing `derive` protocol-version binding (`SEED_PROTOCOL_VERSION`), so a cross-version file never decrypts |
| `key_check` | To tell a wrong secret from a damaged file before decrypting |
| `entry_count` and `segment_rows` | Rows are the unit the reader rebuilds; the count is a second check that the row set is whole |
| Length-prefix framing (`_frame`, existing) | secretstream ciphertexts carry no length of their own; the existing 4-byte frame is reused |

No security exception record is needed: there is no custom cipher or AEAD construction.

### 2.2 Dependency record (PyNaCl)

- Package: PyNaCl, Apache-2.0 (allowed by `scripts/dev/license_policy.json`). It bundles libsodium (ISC). Depends on `cffi`, which `cryptography` already pulls in as a base dependency.
- Pin: `"pynacl>=1.6.2,<2"` in `[project].dependencies`. The upper bound follows the engine's rule for crypto and canonicalization dependencies (as `joserfc` and `rfc8785`).
- Already in `uv.lock` at 1.6.2 as a dependency of `paramiko` (the `sftp` extra). It becomes a base dependency.
- Wheels at 1.6.2 (from `uv.lock`): `cp38-abi3` for `win_amd64`, `win32`, `win_arm64`, `macosx_10_10_universal2`, manylinux and musllinux on `x86_64` and `aarch64`. So it installs from a wheel on every platform the engine and the Windows row 89 target.
- Every place the pin moves (slice E-DEP, then the CLI repin):
  - engine `pyproject.toml` (base dependency with a comment) and `uv.lock` (`uv lock`; only the dependency edge moves, the version stays 1.6.2);
  - engine `NOTICE` regenerated with `scripts/dev/licenses_write.sh` (the `pynacl` line goes from `[extra: sftp]` to `[runtime]`; libsodium's ISC notice is in the PyNaCl wheel's license file);
  - engine `docs/license-policy.md` (no new exception; one line in the runtime list if the doc lists packages);
  - engine SBOM (`scripts/release/sbom.sh` reads the base profile from `uv.lock`, so PyNaCl appears with no script change; `tests/packaging/test_sbom.py` checks the count against the export);
  - a new wheel check `tests/packaging/test_base_wheels.py` (there is none today for third-party base dependencies): for each package in the base runtime closure of `uv.lock`, require a `py3-none-any` wheel or wheels for `win_amd64`, a macOS `arm64` or `universal2` tag, and manylinux `x86_64` and `aarch64`. Gaps that exist on main today go into an allowlist in the test with a reason each; PyNaCl may not be on it. This check reads wheel tags from the lock only. It does not install, import or run secretstream on Windows; that smoke belongs to WIN-FEAS (row 89) and WIN-RUNNER (row 6) (section 17);
  - engine DP certification, in E-DEP itself: the base closure changes, so the engine lock-profile fingerprint changes when E-DEP lands, and `tests/sentry/test_dp_lock_row.py:71` requires `quality/dp_provenance.py` `_CERTIFIED_STACKS` to hold the new row in the same lock change. E-DEP writes the new engine-profile row with `scripts/release/dp_rows.py` and keeps every released row (AT-P3);
  - CLI DP certification: before the engine release that carries E1, release prep adds the projected CLI runtime row to `_CERTIFIED_STACKS` (the new engine version plus PyNaCl). C1 then adds `pynacl==1.6.2` to `C:requirements-certified.txt` (the full third-party closure of the certified install; `cffi` is already there) and pins the matching fingerprint in its header (`C:tests/e2e/test_dp_provenance_certification.py`, `C:tests/sentry/test_ci_lock_installs.py`);
  - CLI SBOM: `C:scripts/release/sbom.sh` reads `requirements-certified.txt`, so no script change;
  - the engine repin checklist (compat, fences, FROZEN, docs, `PIN_PREFIX`, Dockerfile ARG, catalog): no extra item; the Dockerfile installs from wheels.

## 3. Reuse inventory

- libsodium secretstream through `nacl.bindings` for all segment crypto.
- `determinism.derive` for the per-vault key.
- `internal/crypto.hmac_hex`, through the new `key_check_value`, for the KCV.
- `PreparedSecret` (`secret_providers/_types.py:371`): `mask_key()`, `clone()`, `close()`, `key_version`. `prepare_legacy` (`secret_providers/_preflight.py:289`) to turn a programmatic `KeyProvider` into a `PreparedSecret`. `SecretBuffer.__del__` wipes on collection.
- `_opaque.OpaqueBox`, `_key_size`, `_require_vault_key` for the 32-byte floor.
- `_frame` and `_read_frame` (length-prefixed framing).
- Parquet per segment, `_SCHEMA`, `_fold` (sort, fold duplicates, drop ambiguous) stay as they are.
- `keyprovider.is_key_version_label` validates the recorded label.
- F22: `publication/_vault_order.py` and `issue_commit` are used unchanged. They call `serialize`, `reads_as_own` and `load_vault`, whose signatures and return types do not change.
- CLI: `emit_error`, `exit_code_for`, `_mask_secret.admitted_key_provider`, `_mask_secret_guidance`.

## 4. Behaviour

### 4.1 File layout (`decoy-vault/v3`)

```
magic            b"DCYVAULT3\n"
frame(header)    uint32be length + JSON (sort_keys, separators (",", ":"), UTF-8), at most 4096 bytes
frame(c_0)       uint32be length + secretstream push(segment 0, ad, TAG_MESSAGE)
...
frame(c_n)       the last segment, pushed with TAG_FINAL; nothing follows it
```

One header declaration in `vault/_format.py`, `_HEADER = ObjectSpec(_HeaderRecord, _HEADER_FIELDS)` built from `decoy_engine._canonical` (as `delivery/resume/_records.py`), reads and writes the header for both the writer and the reader. The writer emits `canonical_json_bytes(_HEADER.dump(record))`; the reader uses `parse_or_token` (strict JSON: duplicate keys, non-finite numbers and lone surrogates refused) and `attempt(_HEADER.load, parsed)`, so a refusal comes back as a closed token outside any handler. No parser or hook of its own. Fields (a closed set of nine; spec in brackets):

| Field | Type and rule |
|---|---|
| `format` | `"decoy-vault/v3"` [`ExactSpec`] |
| `seed_protocol_version` | int (not bool), equal to `SEED_PROTOCOL_VERSION` [`VersionSpec`] |
| `key_version` | str, `is_key_version_label` true [`ShapedSpec`] |
| `key_check` | str, fullmatch `[0-9a-f]{16}` [`ShapedSpec`] |
| `vault_id` | str, fullmatch `[0-9a-f]{64}` [`ShapedSpec`] |
| `stream_header` | str, fullmatch `[0-9a-f]{48}` (the 24-byte secretstream header) [`ShapedSpec`] |
| `ambiguous_dropped` | int (not bool, not a numeric string), at least 0 [`CountSpec`] |
| `entry_count` | int (not bool, not a numeric string), at least 0 [`CountSpec`] |
| `segment_rows` | int (not bool, not a numeric string), at most 1,048,576 [`CountSpec`], and not 0 (the one local check) |

Keys and segments:

- `vault_id`: 32 bytes from `os.urandom`, drawn inside `serialize()` on every call and never stored on the writer. `_vault_order.py:158` (adopt comparison) and `publish` each call `serialize()`, so their two blobs differ in `vault_id`, stream header and ciphertext. Adoption compares rows through `reads_as_own`, never bytes, so this is correct.
- Stream key: `derive(key_source(), "vault", b"vault-key/v2" + (32).to_bytes(4, "big") + vault_id_bytes)`, passed straight into `init_push` or `init_pull` inside one call expression. It is never bound to a name.
- `stream_header`: returned by `init_push` (libsodium draws its random nonce). Stored in the header, so it is inside the additional data too.
- `ad = sha256(magic + header frame bytes).digest()`, the same for every segment. The reader hashes the bytes it read, not a re-serialization.
- `key_check = key_check_value(key_source, VAULT_KEY_CHECK_LABEL, context=vault_id_hex)` (decision Q1).
- Segment `i` plaintext: a Parquet table of at most `segment_rows` sorted rows and at most `_SEGMENT_MAX_BYTES` (64 MiB). The writer serializes a window of `segment_rows` rows; if the bytes exceed the cap, it halves the window and tries again. One entry whose Parquet exceeds the cap on its own is refused with the new code `vault_entry_too_large` before any file is written.
- A vault with no entries writes one `TAG_FINAL` segment holding an empty table, so a file with no segment is always a truncation.

What the KCV reveals (L1): the mask root is an HKDF output of the user's secret, and the secret may be a weak passphrase. The KCV is then an offline check of a guessed secret, the same exposure the resume store's KCV already has. Binding it to `vault_id` stops it from linking vaults; it does not remove the offline check (FM-17).

### 4.2 Read order (`_open_vault`, the one reader)

1. Key floor (`weak_mask_secret`) and crypto import (`vault_crypto_not_installed`, which now names PyNaCl), before the file is read. Unchanged order.
2. Read the bytes (`vault_unreadable` on an OS error, as today).
3. Magic. `DCYVAULT3\n` continues. Any other match of `DCYVAULT[0-9]+\n` gives `vault_format_unsupported` with the re-mask remedy. Anything else gives `vault_unreadable`.
4. Header frame: length at most 4096, else `vault_unreadable`. `parse_or_token` (strict JSON, duplicate keys refused): any token gives `vault_unreadable`.
5. Local rule: if the parsed value is an object whose `format` is present and is not `"decoy-vault/v3"`, `vault_format_unsupported` (format is checked before the closed set, M5). Then `attempt(_HEADER.load, parsed)`. Token mapping, local to `vault/_format.py`: `schema_unknown` can now come only from `seed_protocol_version` (`format` already passed), so it gives `vault_protocol_version_mismatch` (text unchanged); every other token gives `vault_unreadable`. Then the local check `segment_rows != 0`, else `vault_unreadable`.
6. KCV: `hmac.compare_digest(key_check, expected_check)` false gives `vault_key_mismatch`. The message says "this vault records key version '<label>'; open it with the mask secret of the run that wrote it". The hint covers both causes, which the engine cannot tell apart: a different secret, or an edited `key_check` or `vault_id` field (restore the stored copy). No segment is decrypted.
7. `init_pull` with `stream_header`, then each frame in order. From here on, any framing error, a frame longer than the cap plus `ABYTES` (17), a `pull` failure, a tag other than `TAG_MESSAGE` or `TAG_FINAL`, a `TAG_FINAL` before the last frame, bytes after the `TAG_FINAL` frame, end of file without `TAG_FINAL`, a segment with more than `segment_rows` rows, a row total that differs from `entry_count`, or a malformed or duplicate row gives `vault_tampered`. The mapping built so far is dropped; nothing is returned. The refusal is raised after the `except` block, so it carries no context.

Rule for users: before the header is understood, a bad file is "unreadable"; after the header is understood and the key is right, any damage is "tampered".

### 4.3 Engine API

Key handling rule for every new function (decision on census growth): key bytes reach new code only as `PreparedSecret` or as a key source, a zero-argument callable that returns the key (`prepared.mask_key`, `provider.mask_key`, or a `lambda` over an existing `OpaqueBox`). The bytes are produced inside the call expression that consumes them (`derive(key_source(), ...)`, `hmac_hex(key_source(), ...)`) and are never bound to a name. The census derives bindings from bytes-annotated, secret-named parameters and from bound locals, so this adds no entry. Lambdas are outside the census by its own rule.

- `VaultWriter(prepared: PreparedSecret, *, file_access: FileAccess | None = None)` (decision M6). It keeps `prepared.clone()` and owns that clone. `key_version` comes from `prepared.key_version`; a label that fails `is_key_version_label` raises `ValueError` with a fixed text; a closed `PreparedSecret` raises `SecretClosedError`; any other type raises `TypeError`. The 32-byte floor is checked at construction as today. New `close()` and context-manager methods close the clone; `SecretBuffer.__del__` is the backstop. Breaking, pre-GA, with a Breaking fragment.
- `VaultWriter.assert_keyed_with(mask_key: bytes)` and `assert_vault_writer_keyed(vault_writer, mask_key: bytes)` keep their signatures (the execution callers at `execution/_pipeline_context.py:377`, `execution/_chunked_oracle.py:272` and `execution/out_of_core/_vault_collect.py:76` hold raw bytes). The compare becomes `hmac.compare_digest(self._prepared.mask_key(), mask_key)` inline.
- `vault_writer_for_config` takes the admitted `PreparedSecret` from its `AdmissionScope` (`AdmittedKey.prepared`), or `prepare_legacy(provider, (MASK_ROOT,))` when a programmatic provider was admitted without one, and passes it to `VaultWriter`, which clones it before the scope closes the original.
- `open_vault(path, prepared: PreparedSecret, *, vault=None, file_access=None) -> OpenedVault`, new public function, registered in `fileaccess.ENTRY_POINTS`. `OpenedVault` is a frozen dataclass: `mapping`, `ambiguous_dropped`, `header: VaultHeader`. `VaultHeader` is a frozen dataclass of the non-secret fields: format, key_version, vault_id, entry_count, ambiguous_dropped, segment_rows. `key_check` and `stream_header` are not exposed.
- `load_vault(path, mask_key, ...)` keeps its signature and return `(mapping, ambiguous_dropped)` (engine `unmask.py` and the compat corpus call it). It boxes the key as today and calls `_open_vault(blob, lambda: key.open()[0])`.
- `serialize`, `publish`, `reads_as_own`, `issue_commit`, `collect_vault_entries`: same signatures and meaning. `reads_as_own` calls `_open_vault` with `self._prepared.mask_key`.
- `VAULT_FORMAT_VERSION = "decoy-vault/v3"`. `VAULT_KEY_LABEL = b"vault-key/v2"`. Both stay public.
- `internal/crypto.key_check_value(key_source: Callable[[], bytes], label: str, context: str = "") -> str`: `hmac_hex(key_source(), label if not context else label + "\x1f" + context)[:16]`. Labels are constants in the same module: `RESUME_KEY_CHECK_LABEL = "decoy-resume-key-check/v1"` (moved from `delivery/resume/_fingerprint.py:28`, value unchanged) and `VAULT_KEY_CHECK_LABEL = "decoy-vault-key-check/v1"`. `_fingerprint.build_fingerprint` calls `key_check_value(lambda: mask_key_from_provider(key_provider, job_seed_for_config(config)), RESUME_KEY_CHECK_LABEL)` and gets the same 16 characters as today.
- Reasons, `since=UNRELEASED`, kind `failure`, outcome as the other vault input refusals: `runtime.VAULT_TAMPERED` (`vault_tampered`, "The vault file was changed or cut short after it was written.") and `runtime.VAULT_ENTRY_TOO_LARGE` (`vault_entry_too_large`, "One vault entry is larger than a vault segment can hold.").
- `vault.VAULT_REFUSAL_CODES`: a frozenset of the `reasons.runtime` constants that a vault read or write can raise. Public, so the CLI takes the set from the engine and keeps no copy.

### 4.4 CLI

Engine `unmask_pipeline` re-raises every `VaultError` as `ExecutionError(code=exc.code, message=exc.message)` (`unmask.py:294-297`), and `C:src/decoy/cli/unmask.py:245` catches `(ExecutionError, ConfigError)` before its `except VaultError` at `:248`. So the CLI keys on the code, not the class:

- New sub-package `C:src/decoy/cli/vault/` (the flat `cli/` folder is frozen at 30 modules):
  - `_errors.py`: `vault_error_text(code: str, message: str) -> tuple[str, str | None]`, the one mapping from a vault code to the printed message and hint, and `is_vault_code(code) -> bool` over `decoy_engine.vault.VAULT_REFUSAL_CODES`. Codes, compared with `reasons.runtime` constants, never string literals: `VAULT_KEY_MISMATCH` (use the mask secret of the run that wrote the vault; check the recorded key version), `VAULT_TAMPERED` (the file was changed or cut short; restore the copy you stored), `VAULT_FORMAT_UNSUPPORTED` (written by an older Decoy; re-run `decoy run --vault` with this version), `VAULT_PROTOCOL_VERSION_MISMATCH` (today's text, moved), `VAULT_ENTRY_TOO_LARGE`, `VAULT_CRYPTO_NOT_INSTALLED` (reinstall Decoy; PyNaCl is part of it), any other vault code (code and message, no hint).
  - `_report.py`: the `report vault` command body and its epilog, moved out of `C:src/decoy/cli/report.py` (about lines 2124 to 2280 at `920ea13c`). It gets a `PreparedSecret` inside the existing admission scope (a new `_mask_secret.admitted_prepared_secret(raw)` beside `admitted_key_provider`, yielding `AdmittedKey.prepared`), calls `open_vault`, and prints `format`, `key version` and `vault id` (first 12 hex characters plus an ellipsis in text mode; the full id in `--json`).
- `C:src/decoy/cli/unmask.py`: before the `(ExecutionError, ConfigError)` branch formats its text, an exception whose `code` passes `is_vault_code` goes through `vault_error_text`. The old `except VaultError` branch also calls it (a direct `VaultError` can still reach the CLI from other engine paths).
- `C:src/decoy/cli/run/_vault.py` `_commit_vault`: closes the writer in a `finally` after `write` (the writer now owns a secret clone).
- `C:src/decoy/cli/report.py` keeps only the registration line for `vault`. The file shrinks by about 150 lines (it is oversize at 2299 and must not grow).
- Exit codes do not change: every vault refusal stays `EXIT_USAGE` (1); `VAULT_EXISTS` on `decoy run` keeps its mapping in `exit_codes.py`.
- `report vault --json` success keys: `command`, `status`, `vault`, `entries`, `namespaces`, `ambiguous_dropped` (unchanged) plus `format`, `key_version`, `vault_id` (additive). Error envelope unchanged in shape.
- `C:requirements-certified.txt` gains `pynacl==1.6.2` with the repin (2.2).
- `C:docs/cli-reference.md` `report vault` section and the `decoy explain vault` topic: one line each on the v3 format and the tamper check.

Coordination: row 24zw (REPORT-VAULT-HELP, `E:plan/v1-fix-batch-24zo` C1) edits the same help and epilog. C1 starts only after 24zw C1 has merged, and moves the fixed text.

### 4.5 Row 66 E7

`docs/reasons.md` gets a "Consumers" section: the CLI `--json` failure envelope `reason` field (CLI #229, `C:src/decoy/cli/run/_errors.py` `_failure_reason`), which codes reach it and which CLI-owned refusals carry no `reason` (C-T5 and C-T7 of the F29 plan); `APPROVED_ERROR_MESSAGES` in `error_projection.py` (including `keyed_strategy_requires_secret` and `weak_mask_secret`); the platform consumers (F29 P1, P2) recorded as parked with the platform. One doc test pins it. With E7 merged, row 66 has no 1.0 work left.

## 5. Enumerations

### 5.1 Callers of the vault API (engine `ad36687a6`)

| Caller | Uses | Change |
|---|---|---|
| `vault.vault_writer_for_config` | `VaultWriter(...)` (the only construction in `src/`) | passes the admitted `PreparedSecret` |
| `publication/_vault_order.py:158` | `writer.serialize()` for the adopt comparison; `reads_as_own`; `issue_commit` | none; a fresh `vault_id` per call is correct (4.1) |
| `publication/_publish.py:308-320` | `publish`, `adopt_vault`, `PUBLICATION_VAULT_CONFLICT` | none |
| `publication/_types.py` | `VaultCommit`, `VaultWriter` types | none |
| `unmask.py:292-297` | `load_vault`, re-raises as `ExecutionError(code=...)` | none |
| `execution/_pipeline_context.py:377`, `execution/_chunked_oracle.py:272`, `execution/out_of_core/_vault_collect.py:76` | `assert_vault_writer_keyed(writer, bytes)` | none |
| `delivery/resume/_fingerprint.py:28,109-118` | its own KCV | calls `key_check_value`; output byte-identical |
| `__init__.py:335` | exports `VaultError`, `VaultWriter`, `load_vault`, `vault_writer_for_config` | adds `open_vault`, `OpenedVault`, `VaultHeader`, `VAULT_REFUSAL_CODES` |
| `fileaccess/__init__.py:126-127` | `ENTRY_POINTS` names | E0 renames to the new module paths; E1 adds `open_vault` |
| CLI `report.py:2228` | `load_vault` | moves to `cli/vault/_report.py`, uses `open_vault` |
| CLI `unmask.py:245,248` | `ExecutionError` and `VaultError` branches | route vault codes through `vault_error_text` |
| CLI `run/_prepare.py:562-564`, `run/_vault.py:59-71` | `vault_writer_for_config`, `write` | `_commit_vault` closes the writer |
| Tests: 27 files mention `VaultWriter(` | | E1 routes them through one helper `tests/unit/vault/_support.py::writer(key, key_version="v1")`, which builds a `PreparedSecret` |
| Tests that monkeypatch module attributes (`tests/fileaccess/publication/_vault_support.py:66`, `tests/fileaccess/test_secret_material_frames.py:134,155`, `tests/unit/publication/test_publish_vault_order.py:242`) | | E0 points them at the module that now owns the attribute |

### 5.2 Exit paths

Engine (`_open_vault` and the writer; every refusal is a `VaultError` unless named):

- `weak_mask_secret`: key not the 32-byte mask root, before the file is read (AT-V11).
- `vault_crypto_not_installed`: PyNaCl missing, before the file is read (AT-V11).
- `vault_unreadable`: OS error, magic that is not a vault magic, bad header frame, duplicate keys, JSON or field set (AT-V2).
- `vault_format_unsupported`: any `DCYVAULT<n>\n` other than 3, or another `format` (AT-V9).
- `vault_protocol_version_mismatch`: other `SEED_PROTOCOL_VERSION` (existing test).
- `vault_key_mismatch`: KCV differs: a different secret, or an edited `key_check` or `vault_id` (AT-V7, AT-V8, AT-V8b).
- `vault_tampered`: any failure after the KCV (AT-V3 to AT-V6, AT-V5b, AT-V5c, AT-V10, AT-V20).
- `vault_entry_too_large`: writer, one entry over the segment cap (AT-V20).
- `FileAccessUnavailable`: path string under a non-ambient policy (unchanged, existing test).
- `ValueError`, `SecretClosedError`, `TypeError`: bad `PreparedSecret` at `VaultWriter` construction (AT-V12).
- Engine `unmask_pipeline`: each of the codes above as `ExecutionError(code=...)` (unchanged).
- Publication: an existing leaf that is not this writer's vault gives the receipt refusal `publication_vault_conflict` (unchanged; AT-V14).
- Success: `OpenedVault` or the `(mapping, ambiguous_dropped)` tuple.

CLI (`decoy report vault`, `decoy unmask`): exit 0 on success; exit 1 (`EXIT_USAGE`) for every vault refusal above, as today. No exit code changes.

### 5.3 Routes

Every route writes the vault through one `VaultWriter`, so the format change reaches all of them through `serialize`:

- Plain `decoy run --vault` (resident `run_pipeline`): `vault_writer_for_config` in `C:src/decoy/cli/run/_prepare.py:562-564`, published by F22 after `adopt_vault`.
- Chunked, streaming and out-of-core routes: they collect entries with `collect_vault_entries` into the same writer (`tests/sentry/test_vault_writer_routes.py` already pins that); `decoy run --chunked --vault` stays refused by the CLI (`_ChunkedVaultError`).
- `unmask_pipeline` (`unmask.py:292-297`): reads through `load_vault`.
- `decoy report vault`: reads through `open_vault` (C1).
- Direct API callers of `VaultWriter`: the new constructor.

### 5.4 FK shapes

N/A: the vault stores `(namespace, masked, source)` triples per vaulted column. FK columns that are vaulted are stored like any other column; this change does not touch FK handling.

### 5.5 Fields

- Header: the closed set of nine fields in 4.1.
- `VaultHeader`: six of them (not `key_check`, `stream_header` or `seed_protocol_version`).
- `report vault --json`: three added keys, `format`, `key_version`, `vault_id` (4.4).
- Segment Parquet schema: `namespace`, `masked`, `source`, all string, no nulls; unchanged.
- Resume fingerprint `key_check`: unchanged value (AT-K2).

### 5.6 Output surfaces

- The vault file (format change, section 6).
- `VaultError` messages and codes (two new codes).
- `report vault` text and `--json` (C1).
- `unmask` and `report vault` stderr hints (C1, one renderer).
- Install surface: one new base dependency (2.2), `NOTICE`, SBOM, the CLI certified set.
- Docs: `docs/security/token-vault.md`, `docs/qa/16-vault-and-unmask.md`, `docs/frozen-surfaces.md`, `docs/compatibility-contract.md`, `docs/methodology-registry.yaml`, `docs/license-policy.md`, `docs/reasons.md`, `C:docs/cli-reference.md`, `decoy explain vault`.
- No log line, no progress event and no run-result field changes. The resume store's bytes do not change.

## 6. Frozen contracts

| Surface | Before | After | Where recorded |
|---|---|---|---|
| Vault format | `decoy-vault/v2`, `DCYVAULT2\n`, Fernet | `decoy-vault/v3`, `DCYVAULT3\n`, libsodium secretstream | `docs/frozen-surfaces.md` row 22 |
| Vault key label | `vault-key/v1` | `vault-key/v2` (with `vault_id`) | `docs/frozen-surfaces.md` row 23 |
| New label | none | `decoy-vault-key-check/v1` | new row in `docs/frozen-surfaces.md` |
| Resume KCV | `decoy-resume-key-check/v1` in `_fingerprint.py` | same value, constant moved to `internal/crypto.py` | the resume row of `docs/frozen-surfaces.md` (path column only) |
| Compat corpus | `decoy-vault-v2__synthetic.vault` | `decoy-vault-v3__synthetic.vault` (via `regenerate.py`); the v2 file moves to `tests/unit/vault/fixtures/decoy-vault-v2__retired.vault` as a refusal fixture | `tests/integration/compat_corpus/manifest.json` |
| `VaultWriter` constructor | `(mask_key, *, file_access=None)` | `(prepared, *, file_access=None)` plus `close()` | Breaking fragment; `docs/compatibility-contract.md` pre-GA note |
| Public names | `docs/frozen-surfaces.md:82` keys, secrets and vault row | adds `open_vault`, `OpenedVault`, `VaultHeader`, `VAULT_REFUSAL_CODES` | `docs/frozen-surfaces.md:82` |
| Reason registry | | `runtime.vault_tampered`, `runtime.vault_entry_too_large` | changelog fragment; registry version per the release stamp |
| Base dependencies | no PyNaCl | `pynacl>=1.6.2,<2` | `pyproject.toml`, `NOTICE`, SBOM (2.2) |
| CLI `report vault --json` | 6 keys | 9 keys (additive) | `C:docs/cli-reference.md`, CLI CHANGELOG |

v2 hard cut (decision Q2, 2026-11-18): the compatibility contract says a change to vault read or write needs a new version, a permanent prior-version reader and PO review (section 3.2, section 4.5 and the section 5 decision table). Its pre-GA rule (section 1) allows a hard delete before GA, and its pre-GA vault note (2026-11-12) moves the freeze to the first real vault. The owner approved the cut on 2026-11-18 as that PO review, because no real v2 vault exists outside Decoy's own machines. This differs from B-6 (2026-11-13): B-6 dropped seed-keyed vaults that the 32-byte key floor could no longer open; Q2 drops secret-keyed v2 vaults that open today. E1 records the decision, the date and this difference in the contract's pre-GA vault note.

### 6.1 Census, registry and baseline keys that move, shrink or are added

E0 (pure move; each entry rehomed with `moved_from`, no verdict change):

- `tests/sentry/secret_material_census.json`: the 8 entries under `decoy_engine/vault.py` (`VaultWriter.__init__::mask_key`, `VaultWriter.assert_keyed_with::mask_key`, `assert_vault_writer_keyed::key` and `::mask_key`, `load_vault::key`, `::mask_key` and `::token`, `vault_writer_for_config::key`) move to their new `vault/_*.py` files.
- `tests/sentry/file_access_registry.toml:1307` (`VaultWriter.serialize`, `pyarrow.parquet.write_table`) and `:1317` (`load_vault`, `pyarrow.parquet.read_table`): module path changes.
- `tests/sentry/file_access_modules.toml`: no vault engine row today (`:82` is `secret_providers/vault.py`, not touched); E0 adds rows only if the module sentry requires each new `vault/_*.py` file.
- `fileaccess/__init__.py` `ENTRY_POINTS`: two names change module path.
- `docs/frozen-surfaces.md` rows 22 and 23: path column.

E1 (no growth; decision on census growth):

- Census, removed: `VaultWriter.__init__::mask_key` (the parameter is now `prepared: PreparedSecret`, not bytes); `vault_writer_for_config::key` (no box of raw bytes; the prepared secret is passed); `load_vault::token` (the Fernet block local is gone; the reader's frame local is named `frame_bytes`, which is not secret-shaped).
- Census, kept: `VaultWriter.assert_keyed_with::mask_key`, `assert_vault_writer_keyed::key` and `::mask_key`, `load_vault::key` and `::mask_key`.
- Census, added: none. `key_check_value(key_source, ...)`, `_open_vault(blob, key_source)`, `_open_stream`, `_push_segment` and `open_vault(path, prepared)` take callables or `PreparedSecret`, never bytes, and bind no key to a name. New locals avoid secret-shaped names unless they hold no secret (`state`, `stream_header`, `frame_bytes`, `expected_check`).
- `file_access_registry.toml`: the `read_table` row moves from `load_vault` to `_open_vault`; the `write_table` row stays on `VaultWriter.serialize`.
- `fileaccess` `ENTRY_POINTS`: adds `decoy_engine.vault._reader.open_vault`.
- `docs/frozen-surfaces.md:82`: four public names.
- Resume: no census change.

## 7. Failure modes and partial failure

| Id | Situation | Behaviour | Test |
|---|---|---|---|
| FM-1 | Wrong secret | `vault_key_mismatch` before any decrypt; names the recorded key version | AT-V7 |
| FM-2 | Header field edited (for example `ambiguous_dropped`) | `vault_tampered` (additional data mismatch) | AT-V3 |
| FM-3 | `key_check` or `vault_id` edited, right secret | `vault_key_mismatch` (the KCV check runs before decrypting, and a mismatch cannot be told apart from a wrong secret); the hint names a different secret and both field names. No data comes out either way | AT-V8, AT-V8b |
| FM-4 | Segments reordered, dropped or duplicated | `vault_tampered` | AT-V4 |
| FM-5 | Truncated at a segment boundary, inside a frame, or extra bytes after the final segment | `vault_tampered` | AT-V5 |
| FM-5b | Authenticated segments with no `TAG_FINAL`; `TAG_FINAL` in the middle; a `TAG_PUSH` or `TAG_REKEY` segment; `entry_count` that does not match the rows | `vault_tampered` | AT-V5b, AT-V5c |
| FM-6 | Empty vault | one `TAG_FINAL` segment; round-trips; with that segment removed, `vault_tampered` | AT-V6 |
| FM-7 | A file with another vault magic passed to `load_vault`, `unmask`, `report vault` | `vault_format_unsupported` with the re-mask remedy | AT-V9, CV-3 |
| FM-8 | A v2 or damaged file already at the vault path on `decoy run --vault` | `publish` raises `vault_exists`; `adopt_vault` finds `reads_as_own` False and returns `VaultConflict`; the receipt refuses with `publication_vault_conflict`; the file is not overwritten | AT-V14 |
| FM-9 | Header over 4096 bytes, not JSON, duplicate keys, an extra key, a bool or numeric string in a count field, `segment_rows` 0, uppercase or short hex | `vault_unreadable` | AT-V2 |
| FM-10 | `os.urandom` or libsodium's random source fails | the error propagates from `serialize`; nothing is written | none (not reachable in tests; noted) |
| FM-11 | Bad `PreparedSecret` passed to `VaultWriter` | `ValueError`, `SecretClosedError` or `TypeError` at construction, fixed text | AT-V12 |
| FM-12 | Error text | no source value, no masked value, no key, no KCV; no exception context or cause | AT-V17 |
| FM-13 | Partial write | unchanged: the F22 atomic publish | existing F22 tests |
| FM-14 | Same secret, two runs, or two `serialize()` calls on one writer | different `vault_id`s, keys and stream headers | AT-V10, AT-V21 |
| FM-15 | One entry too big for a segment; a window too big | entry: `vault_entry_too_large` before any write; window: halved until it fits | AT-V20 |
| FM-16 | Same secret, many vaults | KCVs differ per vault (decision Q1) | AT-K3 |
| FM-17 | Weak (low-entropy) secret | the KCV is an offline check for a guessed secret, as the resume store's KCV already is. The floor is on length, not entropy; secret strength stays the user's job (`docs/security/token-vault.md` says so) | none (documented) |
| FM-18 | Writer secret lifetime | the writer owns a clone; `close()` wipes it; the CLI closes it after `write`; `SecretBuffer.__del__` is the backstop | AT-V12, CV-8 |
| FM-19 | PyNaCl missing from a broken install | `vault_crypto_not_installed` before the file is read, naming PyNaCl | AT-V11 |

## 8. Acceptance tests (red first)

Each test is written first and fails on the slice base for the stated reason, then passes on the slice head. Each named mutation must turn its test red on the final slice head.

Test seam (H4): `vault/_format.py` exposes the `_HEADER` declaration and `_HeaderRecord`, `_open_stream(key_source, vault_id) -> (state, stream_header)` and `_push_segment(state, plaintext, ad, final)`, the primitives the production writer loops over. Tests compose them with a real key to build files that are authenticated but inconsistent. To build a `TAG_PUSH` or `TAG_REKEY` cell, a test calls `nacl.bindings` `push` with that tag on the seam's state. Production code has no test-only parameter.

"Ignore the final tag" (the AT-V5b mutation) means: the reader accepts end of file after a `TAG_MESSAGE` frame.

### 8.1 Engine

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-E0 | `scripts/check_pure_move.py` over the E0 diff; `from decoy_engine.vault import <each name in the old module's public set>` resolves; the `fileaccess` entry-point sentry and the census pass with the rehomed paths | no package | leave one `ENTRY_POINTS` name on `decoy_engine.vault.load_vault` | E0 |
| AT-P1 | `tests/packaging/test_base_wheels.py`: every package of the base runtime closure in `uv.lock` has a `py3-none-any` wheel or wheels for `win_amd64`, macOS `arm64` or `universal2`, manylinux `x86_64` and `aarch64`; `pynacl` is in the base closure and not on the allowlist; a seeded lock with a Linux-only wheel fails | no PyNaCl in base; no test | add `pynacl` to the allowlist | E-DEP |
| AT-P2 | existing `tests/packaging/test_sbom.py` and the `NOTICE` check pass with `pynacl` marked `[runtime]` | `NOTICE` says `[extra: sftp]` | leave the old `NOTICE` | E-DEP |
| AT-P3 | existing `tests/sentry/test_dp_lock_row.py::test_lock_profile_is_a_certified_row` passes on the E-DEP head, with every previously released `_CERTIFIED_STACKS` row still present | the lock profile changed without a row | drop the new row from `_CERTIFIED_STACKS` | E-DEP |
| AT-K1 | `tests/unit/internal/test_key_check_value.py`: `key_check_value(lambda: k, L)` equals `hmac_hex(k, L)[:16]`; with context equals `hmac_hex(k, L + "\x1f" + C)[:16]`; 16 lowercase hex | no function | truncate to 15 | E1 |
| AT-K2 | `tests/unit/delivery/resume/test_fingerprint_kcv_frozen.py`: for a fixed key and config, `build_fingerprint(...).key_check` equals a pinned 16-character value computed on `ad36687a6` | n/a (guard; green on base, must stay green) | change `RESUME_KEY_CHECK_LABEL` by one character | E1 |
| AT-K3 | `tests/sentry/test_one_key_check.py` (AST walk of `src/`): a `[:16]` or `[:_KEY_CHECK_HEX]` slice of an `hmac_hex`, `hmac.new` or `derive` result appears only in `internal/crypto.py`; string constants containing `key-check` appear only there; seeded cells fail. Plus: two vaults under one key have different `key_check` | second construction possible | re-add `hmac_hex(...)[:16]` in `_fingerprint.py`; drop `context` from the vault call | E1 |
| AT-V1 | `tests/unit/vault/test_v3_format.py::test_round_trip_and_header`: write rows with one ambiguous pair; `open_vault` returns the mapping, `ambiguous_dropped == 1`, header `format == "decoy-vault/v3"`, `key_version == "v1"`, 64-hex `vault_id`, `entry_count == len(mapping)`; the file starts with `DCYVAULT3\n` | v2 writer | drop `entry_count` from the `_HEADER` declaration | E1 |
| AT-V2 | `test_v3_format.py::test_header_closed_set` (cells: extra key, missing key, duplicate key, `true` and `"5"` in `ambiguous_dropped`, `entry_count` and `segment_rows`, `segment_rows` 0, `true` in `seed_protocol_version` (gives `vault_protocol_version_mismatch`, the `VersionSpec` token), uppercase `vault_id`, 15-character `key_check`, 47-character `stream_header`, `vault_id` plus a trailing newline, 4097-byte header, non-JSON) | no closed-set check | replace a hex `fullmatch` with `match` | E1 |
| AT-V3 | `tests/unit/vault/test_v3_tamper.py::test_header_edit_is_tampered`: rewrite `ambiguous_dropped` 0 to 5 and re-frame | Fernet ignores the header | pass `None` as additional data | E1 |
| AT-V4 | `test_v3_tamper.py::test_segment_order` (cells: swap segments 0 and 1, drop segment 1, repeat segment 0), with `segment_rows` 2 and 5 rows | Fernet tokens are independent | create a fresh pull state per frame | E1 |
| AT-V5 | `test_v3_tamper.py::test_truncation` (cells: drop the final segment, cut inside a frame, append one byte, append a whole extra frame) | v2 reads to the end | stop at the first frame that fails to parse and return what was read | E1 |
| AT-V5b | `test_v3_tamper.py::test_final_tag` (cells built through the seam: k = 3 segments all `TAG_MESSAGE` with a matching `entry_count`; `TAG_FINAL` on segment 1 of 3; one `TAG_PUSH` segment; one `TAG_REKEY` segment) | no final tag | ignore the final tag; accept any tag | E1 |
| AT-V5c | `test_v3_tamper.py::test_entry_count_mismatch`: correct tags, header `entry_count` one more than the rows (and one less) | no count | skip the `entry_count` check | E1 |
| AT-V6 | `test_v3_tamper.py::test_empty_vault` (round-trip; then remove the only segment) | v2 writes no chunk for no rows | write zero segments when there are no rows | E1 |
| AT-V7 | `test_v3_tamper.py::test_wrong_key_is_key_mismatch`: second 32-byte key; code `vault_key_mismatch`; message holds `"v1"`; a spy on `init_pull` saw no call | v2 has no KCV | skip the KCV compare (the code becomes `vault_tampered`) | E1 |
| AT-V8 | `test_v3_tamper.py::test_kcv_edit_is_key_mismatch`: right secret, one hex digit of `key_check` changed and re-framed: `vault_key_mismatch`; the hint names both `key_check` and `vault_id` | no KCV | treat a KCV mismatch as tampered | E1 |
| AT-V8b | `test_v3_tamper.py::test_vault_id_edit_is_key_mismatch`: right secret, one hex digit of `vault_id` changed and re-framed: `vault_key_mismatch`, no `pull` call | no KCV | compute the KCV without the `vault_id` context (the cell then reaches `pull` and gives `vault_tampered`) | E1 |
| AT-V9 | `test_v3_format.py::test_other_magic_refused_with_remedy` (cells: the retired v2 fixture, a synthetic `DCYVAULT4\n`, `DCYVAULT\n`); code `vault_format_unsupported` for the first two, `vault_unreadable` for the third; message holds "re-run" and "--vault" | v2 opens | match only `DCYVAULT2\n` (the v4 cell becomes `vault_unreadable`) | E1 |
| AT-V10 | `test_v3_format.py::test_per_vault_key`: same key and rows, two writers: different `vault_id`; a segment frame spliced from vault A into vault B gives `vault_tampered`; the key-derivation input differs for two ids | one key per secret | drop `vault_id` from the key label | E1 |
| AT-V11 | existing key-floor and crypto-missing tests in `tests/unit/test_vault.py` pass with v3 (the crypto-missing cell hides `nacl`; the message names PyNaCl) | n/a (guard) | move the floor check after the file read | E1 |
| AT-V12 | `test_v3_format.py::test_writer_takes_prepared_secret` (cells: raw bytes give `TypeError`; a closed `PreparedSecret` gives `SecretClosedError`; key versions `"bad label"` and `"v1\n"` give `ValueError`; closing the caller's `PreparedSecret` after construction does not stop `serialize`; `writer.close()` then `serialize()` gives `SecretClosedError`) | old constructor | keep the caller's object instead of a clone | E1 |
| AT-V13 | `tests/unit/vault/test_v3_config.py`: `vault_writer_for_config` with a provider whose `key_version` is `"v7"` writes header `key_version == "v7"`; a programmatic provider goes through `prepare_legacy` | no stamp | hard-code `"v1"` | E1 |
| AT-V14 | `tests/fileaccess/publication/test_vault_adopt.py` and `tests/unit/publication/test_publish_vault_order.py` new cells: a v2 file and a tampered v3 file at the leaf give `VaultConflict` from `adopt_vault`, a receipt refused with `publication_vault_conflict`, and unchanged file bytes; the existing cells pass | v2 cell: on the base a v2 file at the leaf adopts | return True from `reads_as_own` on `vault_format_unsupported` | E1 |
| AT-V15 | compat corpus: the v3 synthetic artifact round-trips; `test_harness_bites_on_corruption` asserts `vault_tampered` | corpus holds v2 | flip the asserted code in the meta-test | E1 |
| AT-V16 | `tests/sentry/test_secret_material_census.py` passes, and a new cell compares the census with its E0-head copy: no entry is added except a `moved_from` rehome; the three removed entries in 6.1 are gone; `tests/fileaccess/test_secret_material_frames.py` covers `_open_vault`, `open_vault` and `key_check_value` (no 32-byte key or derived key is a local in any failing frame) | new code not in the census | bind the derived stream key to a local named `stream_key` in `_open_stream` | E1 |
| AT-V17 | `test_v3_tamper.py::test_no_values_in_errors`: for every refusal cell above, `str(exc)` holds no source value, no masked value and no KCV, and `exc.__cause__ is None` and `exc.__context__ is None` | n/a | raise `vault_tampered` inside the `except` block around `pull` | E1 |
| AT-V18 | `tests/sentry/test_vault_crypto_choke_point.py` (AST walk of `src/`, resolving aliases, `from` imports and `importlib` strings): `nacl` is imported only in `vault/_format.py`; the bytes `b"vault-key/v2"` appear once in `src/`; `cryptography.fernet` is imported nowhere; seeded cells fail | no sentry | add `import nacl.bindings` to `vault/_reader.py` | E1 |
| AT-V19 | `tests/unit/vault/test_v3_known_answer.py` over `tests/unit/vault/fixtures/v3_known_answer.vault`, a whole v3 vault file made once by the production writer under mask key 32 bytes of `0x01`, with `segment_rows` 1 and two entries, so it has two real Parquet segments (`TAG_MESSAGE` then `TAG_FINAL`). Stored bytes are read, never re-written, so the test does not depend on the pyarrow version. (a) For that key and the fixture's `vault_id`, the stream key equals a pinned hex value and `key_check` equals a pinned 16-hex value. (b) `_open_vault` on the fixture returns the pinned two-entry mapping, `ambiguous_dropped == 0` and the pinned header. (c) Independently of production code: the test splits the frames itself, computes the additional data from section 4.1, calls raw `nacl.bindings` `init_pull` and `pull` with the pinned stream key, checks the tags, and reads each plaintext with `pyarrow.parquet` to the same rows | no v3 | drop the length prefix from the key label | E1 |
| AT-V20 | `test_v3_format.py::test_segment_byte_cap` (cap patched to 4 KiB): rows whose window is over the cap round-trip in more segments; one entry over the cap gives `vault_entry_too_large` and no file; a crafted frame longer than the cap plus 17 gives `vault_tampered` and `pull` is not called | no cap | skip the halving | E1 |
| AT-V21 | `test_v3_format.py::test_vault_id_per_serialize`: two `serialize()` calls on one writer give different `vault_id`s and different first segment frames, and both load to the same rows | n/a | cache `vault_id` on the writer | E1 |
| AT-R1 | reason tests: `runtime.VAULT_TAMPERED` and `runtime.VAULT_ENTRY_TOO_LARGE` registered, `since=UNRELEASED`; `VAULT_REFUSAL_CODES` equals the set of `VAULT_*` runtime reasons that the vault package raises (walked from the source); the changelog fragment passes `tests/unit/scripts/test_check_fragment.py` | no reason | leave `VAULT_ENTRY_TOO_LARGE` out of `VAULT_REFUSAL_CODES` | E1 |
| AT-M1 | `tests/sentry/test_methodology_citations.py` (existing) passes with the new `vault/_format.py` registry entry and its `Pattern:` line citing libsodium secretstream | n/a | remove the `Pattern:` line | E1 |
| AT-D1 | `tests/unit/reasons/test_reasons_doc_consumers.py`: `docs/reasons.md` has a "Consumers" heading; every `reasons.<ns>.<NAME>` symbol it names resolves in the registry; it names `APPROVED_ERROR_MESSAGES` | no section | rename one symbol in the doc to a name that does not exist | E7 |

### 8.2 CLI

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| CV-1 | `C:tests/e2e/vault/test_report_vault_v3.py`: `decoy run --vault` then `decoy report vault --json`: the 9 keys, `format == "decoy-vault/v3"`, `key_version == "v1"`, 64-hex `vault_id`; text mode shows `format`, `key version` and 12 hex characters of the id | 6 keys | drop `key_version` from the JSON | C1 |
| CV-2 | `test_report_vault_v3.py::test_tampered`: flip one byte in the last segment: exit 1, stderr `vault_tampered` and the tamper hint; no row value on stdout or stderr | v2 engine | route `VAULT_TAMPERED` to the fallback branch (no hint) | C1 |
| CV-3 | `test_report_vault_v3.py::test_v2_refused`: the retired v2 fixture: exit 1, `vault_format_unsupported` and the re-mask hint | v2 opens | drop the remedy hint | C1 |
| CV-5 | `C:tests/e2e/vault/test_vault_error_parity.py`: for `vault_tampered`, `vault_key_mismatch` and `vault_format_unsupported`, the real `decoy unmask` path (engine `unmask_pipeline`, which raises `ExecutionError`) and `decoy report vault` print the same message and hint | the CLI `(ExecutionError, ConfigError)` branch prints its own text | remove the `is_vault_code` route from the `ExecutionError` branch | C1 |
| CV-6 | `test_report_vault_v3.py::test_wrong_secret`: a second secret: exit 1, `vault_key_mismatch`, the message holds the recorded key version, the hint names both causes | v2 text | swap the hints of `VAULT_KEY_MISMATCH` and `VAULT_TAMPERED` | C1 |
| CV-7 | `C:tests/sentry/test_vault_error_one_renderer.py` (AST walk of `src/decoy/cli`): outside `cli/vault/_errors.py`, no module may (a) compare a `.code` with a `reasons.runtime.VAULT_*` constant or a name imported from it, except `exit_codes.py` (`VAULT_EXISTS` exit class), `run/_errors.py` and `run/_vault.py` (classifiers and the CLI-owned vault refusals, which print no engine vault text); (b) hold a string literal starting with `vault_` that equals a registered vault reason code; (c) build text from `exc.code` inside an `except` whose body is reached by an engine vault code, unless it calls `vault_error_text`. Spellings caught: `exc.code == X`, `X == exc.code`, `exc.code in {...}`, `getattr(exc, "code", None) == X`, `match` on the code. Seeded cells for each spelling, including one inside an `except ExecutionError` branch, fail | no sentry | add an `except ExecutionError` branch that compares `getattr(exc, "code", None)` with `"vault_tampered"` | C1 |
| CV-8 | `C:tests/unit/run/test_commit_vault_closes.py`: `_commit_vault` closes the writer on success and when `write` raises | no close | drop the `finally` | C1 |
| CV-9 | the existing certified-set checks (`C:tests/e2e/test_dp_provenance_certification.py`, `C:tests/sentry/test_ci_lock_installs.py`) pass with `pynacl==1.6.2` in `requirements-certified.txt` and the new fingerprint row | no pin | remove the `pynacl` line | C1 (repin) |

F09 CV-4 (domain versions in the report) is Later and not in this plan.

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"; the package root is at its fan-out cap, and turning `vault.py` into `vault/` keeps the root count the same):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/vault/__init__.py` | new (E0): docstring and public re-exports, same names as `vault.py`; E1 adds `open_vault`, `OpenedVault`, `VaultHeader`, `VAULT_REFUSAL_CODES` | Public API; a sub-package because the root is at its fan-out cap, as `_canonical/` and `_nested_json/` | `publication/` |
| `src/decoy_engine/vault/_format.py` | new (E0 move of framing and Fernet helpers; E1 replaces them with the `_HEADER` declaration, `_open_stream`, `_push_segment`, `_pull_segments`; `Pattern:` docstring line citing libsodium secretstream) | same; the one crypto and layout module | |
| `src/decoy_engine/vault/_writer.py` | new (E0 move): `VaultWriter`, `VaultCommit`, `issue_commit`, `_publish` | same | |
| `src/decoy_engine/vault/_reader.py` | new (E0 move): `load_vault`; E1 adds `_open_vault`, `open_vault`, `OpenedVault`, `VaultHeader` | same | |
| `src/decoy_engine/vault/_config.py` | new (E0 move): `vault_writer_for_config`, `assert_vault_writer_keyed` | same | |
| `src/decoy_engine/vault.py` | deleted (E0) | | |
| `src/decoy_engine/internal/crypto.py` | changed (E1, about +25): `key_check_value`, the two label constants | Foundation (private leaves) | `hmac_hex` |
| `src/decoy_engine/delivery/resume/_fingerprint.py` | changed (E1, about -3) | owning package | |
| `src/decoy_engine/reasons/runtime/_part3.py` | changed (E1, about +14): two reasons | Reason codes | the other `VAULT_*` entries |
| `src/decoy_engine/fileaccess/__init__.py` | changed: `ENTRY_POINTS` names (E0), `open_vault` (E1) | Secret providers, file access | |
| `src/decoy_engine/__init__.py` | changed (E1): four exports | Public API | line 335 |
| `pyproject.toml`, `uv.lock`, `NOTICE`, `docs/license-policy.md` | changed (E-DEP) | Packaging | |
| `src/decoy_engine/quality/dp_provenance.py` | changed (E-DEP: the new engine-profile row; before the E1 release: the projected CLI runtime row) | DP provenance | `_CERTIFIED_STACKS` |
| `tests/packaging/test_base_wheels.py` | new (E-DEP) | Packaging tests | `tests/packaging/test_sbom.py` |
| `CODEMAP.md` | changed (E0): a "Token vault" row | | |
| `.importlinter` | changed only if a contract names `decoy_engine.vault` in a way a package breaks (E0 checks; a package keeps the name) | Layer contracts | |
| `docs/methodology-registry.yaml` | changed (E1): `vault/_format.py` entry | | |
| `tests/unit/vault/test_v3_format.py`, `test_v3_tamper.py`, `test_v3_config.py`, `test_v3_known_answer.py`, `_support.py`, `fixtures/decoy-vault-v2__retired.vault`, `fixtures/v3_known_answer.vault` | new (E1) | Unit tests (mirrors `vault/`) | `tests/unit/vault/test_run_entries.py` |
| `tests/unit/internal/test_key_check_value.py`, `tests/unit/delivery/resume/test_fingerprint_kcv_frozen.py` | new (E1) | Unit tests | |
| `tests/sentry/test_vault_crypto_choke_point.py`, `tests/sentry/test_one_key_check.py` | new (E1) | Sentry test | `tests/sentry/test_vault_writer_routes.py` |
| `tests/sentry/secret_material_census.json`, `tests/sentry/file_access_registry.toml` | changed (E0 rehome, E1 removals per 6.1) | Sentry baselines | |
| `tests/integration/compat_corpus/` | changed (E1) | compat corpus | |
| `tests/unit/reasons/test_reasons_doc_consumers.py` | new (E7) | Unit tests | reason tests |
| `docs/security/token-vault.md`, `docs/qa/16-vault-and-unmask.md`, `docs/frozen-surfaces.md`, `docs/compatibility-contract.md` | changed (E1) | Feature and contract docs; QA checklists | |
| `docs/reasons.md` | changed (E7) | Feature and contract docs | |
| `changelog.d/vault-v3-header.md` (E1, Breaking and Added); `changelog.d/pynacl-base-dependency.md` (E-DEP) | new | Changelog fragments | |

CLI (rows of `C:CODEMAP.md` "Where Things Go"):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `C:src/decoy/cli/vault/__init__.py`, `_errors.py`, `_report.py` | new | Command-private helpers: a named sub-package below `src/decoy/cli/` (the flat folder is frozen) | `cli/run/`, `cli/library/` |
| `C:src/decoy/cli/report.py` | changed (about -150): registration line only for `vault` | Command module | |
| `C:src/decoy/cli/unmask.py` | changed (about -15) | Command module | |
| `C:src/decoy/cli/run/_vault.py` | changed (about +3): close in `finally` | Command-private helpers | |
| `C:src/decoy/_mask_secret.py` | changed (about +15): `admitted_prepared_secret` | shared CLI helper | `admitted_key_provider` |
| `C:requirements-certified.txt` | changed (repin): `pynacl==1.6.2`, header fingerprint | Packaging | |
| `C:tests/e2e/vault/`, `C:tests/unit/run/test_commit_vault_closes.py` | new | E2E and unit tests | `tests/e2e/dup_freeze/` |
| `C:tests/sentry/test_vault_error_one_renderer.py` | new | Sentry test | |
| `C:docs/cli-reference.md`, `C:src/decoy/cli/explain.py` (vault topic text), `C:CHANGELOG.md`, `C:CODEMAP.md` | changed | docs | |

## 10. Design notes

- Choke points.
  - Engine format and crypto: `vault/_format.py` is the only module that imports `nacl` and knows the magic and the `_HEADER` declaration. Guard: AT-V18. Mutation: `import nacl.bindings` in `vault/_reader.py`.
  - Engine KCV: `internal/crypto.key_check_value` is the only KCV, for the resume store and the vault. Guard: AT-K3. Mutation: `hmac_hex(...)[:16]` re-added in `_fingerprint.py`.
  - Engine read path: `_open_vault` is the only reader; `load_vault`, `open_vault` and `reads_as_own` call it.
  - CLI: `decoy.cli.vault._errors.vault_error_text` is the only renderer of engine vault codes, keyed on the code. Guard: CV-7. Mutation: a vault-code comparison inside an `except ExecutionError` branch.
- Why a key source and not raw bytes or a `PreparedSecret` method for the KCV. The resume store reaches its key through `mask_key_from_provider(key_provider, job_seed)` and has no `PreparedSecret`, so a `PreparedSecret.key_check_value` method (F09 revision 3) would need a second implementation for resume, the second construction H2 forbids. A raw-bytes parameter is a new census entry, which the owner's census decision rules out. A zero-argument callable serves both callers, keeps one construction, and binds no key to a name.
- Why `VaultWriter(prepared)` (decision M6). It removes the raw-bytes constructor parameter and the bytes attribute, and the writer's secret lifetime follows the engine's existing `PreparedSecret` rules (clone, close, wipe on collection). `assert_keyed_with` keeps its bytes parameter because the execution callers hold bytes; changing them is outside 1.0.
- Why `vault_id` stays with secretstream. secretstream's random header already makes each stream's ciphertext distinct, but `vault_id` also makes the stream key per vault and binds the KCV to the vault (decision Q1). The owner asked to keep it.
- E0 is a named refactoring: Move Module (Fowler, Move Function applied to a whole module), with no body change. It is needed because `vault.py` is 596 lines on main and E1 adds about 280 net: one module of about 880 lines is past the 800 rule and the module-size ceiling of 700. `check_pure_move.py` proves E0, and E1's diff is then behaviour only.
- Why `load_vault` keeps its tuple: F22 (`reads_as_own`), engine `unmask.py` and the compat corpus call it. `open_vault` adds the header without a second read of the file (a second read could see a different file).
- E-DEP is its own slice because a dependency-lock change is a full-suite escalation trigger (`testing.md`); keeping it apart from the format change keeps E1's test selection normal.
- `segment_rows` stays 65536 (today's `_CHUNK_ROWS`). The F13 rule (no single plaintext blob before encryption) holds.
- Logs: no new log lines. Error text carries codes, the recorded key version and the handle display, never values (log hygiene).

## 11. Size

| Slice | Src lines | Test lines | Docs and packaging lines | Files touched |
|---|---|---|---|---|
| E0 | about 620 moved, about +40 net (package init, entry-point names) | about 60 (import paths, monkeypatch targets, census and registry rehomes) | 5 (CODEMAP row) | about 14 |
| E-DEP | 0 | about +90 | about +15 (pyproject, NOTICE, license doc, fragment) plus `uv.lock` | 5 |
| E1 | about +290 net | about +720 | about +110 | src 9, tests about 38 (27 one-line helper edits), docs 6, fixtures 3 |
| E7 | 0 | about +40 | about +60 | 2 |
| C1 | about +210 new, about -165 moved out | about +350 | about +30 | src 7, tests 5, docs 4 |

Every slice is under 800 changed lines of product code. E1's test lines are high because every security property has its own test; they are tests, not product code. `report.py` shrinks; no file in the plan crosses its size ceiling (`vault/_format.py` is the largest new module at about 250 lines).

## 12. Slices

| Slice | Repo | Content | Risk | Acceptance tests | Depends on | Test gate |
|---|---|---|---|---|---|---|
| E0 | engine | Move Module: `git mv` of `vault.py` into `vault/` (four private modules plus the facade), body unchanged; `ENTRY_POINTS` names; census and file-access registry rehomes with `moved_from`; monkeypatch targets in tests; CODEMAP row; `docs/frozen-surfaces.md` path column | R1 (pure move) | AT-E0 | none | T1 impact set (vault, fileaccess, publication, unmask, sentry); `check_pure_move.py`; Codex review |
| E-DEP | engine | PyNaCl base dependency: `pyproject.toml`, `uv.lock`, `NOTICE`, license doc, wheel check, the new engine-profile row in `_CERTIFIED_STACKS`, fragment. No import of `nacl` yet | R1 (dependency lock) | AT-P1, AT-P2, AT-P3 | none | full suite (dependency-lock escalation trigger) against the saved main baseline; Dennis then Codex |
| E1 | engine | v3 format on secretstream, `_HEADER` declaration, byte cap, KCV function and resume move, `VaultWriter(prepared)`, `open_vault`, two reasons, `VAULT_REFUSAL_CODES`, corpus swap, retired v2 fixture, known-answer fixture, sentries, census removals, methodology registry, docs, Breaking fragment | R2 (crypto, frozen format) | AT-K1 to AT-K3, AT-V1 to AT-V21 with AT-V5b and AT-V5c, AT-R1, AT-M1 | E0, E-DEP | T1 on the head plus T2: each named mutation on `vault/_format.py`, `vault/_reader.py`, `vault/_writer.py`, `internal/crypto.py` and `_fingerprint.py`; compat corpus; secret census; resume tests. Dennis then Codex, crypto brief |
| E7 | engine | `docs/reasons.md` "Consumers"; the doc test | R0 | AT-D1 | none | T0 |
| C1 | CLI | `cli/vault/` sub-package, `report vault` move and new fields, one code-keyed renderer, `unmask` routing, writer close, `admitted_prepared_secret`, certified-set pin, sentry, docs | R2 (frozen `--json` additive, error text, dependency set) | CV-1, CV-2, CV-3, CV-5 to CV-9 | the engine release that carries E1, the CLI repin to it, and row 24zw C1 merged | T1 (`tests/e2e/vault/`, unmask and report e2e, sentries, packaging) plus T2 on the head; full suite because the certified dependency set changes; Dennis then Codex (R2, required) |

Order and timing (dates in CST): E0, E-DEP and E7 can start now. E1 follows E0 and E-DEP; target merge 2026-11-27 so that C1 has a week before 2026-12-04. Release prep for the engine release that carries E1 adds the projected CLI runtime row to `_CERTIFIED_STACKS`. C1 rides the repin that follows that release. It is not part of the 0.28.0 repin.

Open PRs that touch the same files (checked 2026-11-18 about 14:00 CST):

- `vault.py` and `keyprovider.py`: E#333, a parked draft ("do not merge alone"), not a 1.0 row. It re-anchors after E0.
- `reasons/runtime/_part3.py`: E#684, E#691, E#661.
- `docs/frozen-surfaces.md`: E#685, E#662, E#643.
- `docs/reasons.md`: E#647, E#661, E#561, E#557, E#555, E#546, E#523.
- Compat corpus: E#686.
- CLI `report.py`: C#301, C#68. CLI `unmask.py`: C#68.

The engine files are ledger-style; keep both sides on rebase. `uv.lock` conflicts are resolved by re-running `uv lock` on the rebased base, never by hand. C1 rebases after the CLI PRs that merge first; the move takes the text as it is on main.

## 13. Recurring-defect class check

- Value-free errors (F31 class): every new refusal has fixed text plus non-secret fields only, with no exception context; AT-V17.
- Secret in a traceback frame: new code takes `PreparedSecret` or key sources and binds no key; the census does not grow; AT-V16.
- Two copies of a central mechanism: one crypto module, one KCV (shared with resume), one reader, one CLI renderer, each with a guard test.
- A test weakened to pass: the existing vault tests keep their assertions; only constructor calls and v2-specific header assertions (`chunk_rows`, `chunk_count`) change, and the gate diff-checks them. AT-K2 pins the resume KCV value from the base.
- A frozen surface changed without its records: section 6 and 6.1 list every record; they move together in E1.
- A dependency added in one place only: section 2.2 lists every pin location; AT-P1, AT-P2 and CV-9 check them.

### 13.1 Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (source or masked values, the key, the KCV in error text or tracebacks) | fixed messages with codes and the recorded key version only; raise outside `except`; keys reach new code only as `PreparedSecret` or key sources, never bound | AT-V16, AT-V17, CV-2 | raise inside the `except` around `pull`; bind the stream key to a local | E1, C1 |
| 2 | Cleanup on every exit | the writer owns a secret clone, closed by `close()` and by the CLI in a `finally`, wiped by `SecretBuffer.__del__` as backstop; the file is read into memory once; a refused read returns nothing; the publish path is F22's | AT-V12, CV-8, AT-V14 (file bytes unchanged on refusal) | drop the `finally` in `_commit_vault`; return the partial mapping on a tamper | E1, C1 |
| 3 | State completeness (every read outcome covered) | the read order in 4.2 is one ordered list; each step has its own code and its own cell | AT-V2 to AT-V12, AT-V5b, AT-V5c, AT-V20 | merge `vault_tampered` into `vault_unreadable` | E1 |
| 4 | Route coverage | one writer for all routes (5.3); the CLI routes by code whatever the exception class | existing route sentry, AT-V13, CV-5 | remove the `ExecutionError` route in CLI `unmask` | E1, C1 |
| 5 | Referential integrity | N/A: no FK or cross-table state changes (5.4) | none | none | none |
| 6 | Untrusted input (the vault file is read from disk) | magic, a 4096-byte header cap, the shared `_canonical` strict reader (duplicate keys refused, closed field set, strict types, fullmatch), `format` first, a frame-length cap before decrypting, an authenticated stream with a required final tag | AT-V2, AT-V3, AT-V5, AT-V5b, AT-V20 | lift the header cap | E1 |
| 7 | TOCTOU (header read and data read seeing different files) | one read of the file into memory; additional data over the bytes as read; `open_vault` returns the header and the mapping from the same bytes | AT-V1, AT-V3 | hash a re-serialized header for the additional data | E1 |
| 8 | Weak proof (a wrong key reported as damage, or damage accepted) | KCV before decrypt (a KCV-field edit is reported as a key mismatch with both causes named, never accepted); secretstream tag, order and final tag, plus `entry_count`, all checked; known-answer test through production and raw bindings | AT-V4 to AT-V8, AT-V8b, AT-V5b, AT-V5c, AT-V19 | skip the `entry_count` check | E1 |
| 9 | Refactor drift (behaviour change hidden in the move; resume KCV changed by the extraction) | E0 is a pure move proven by `check_pure_move.py`; the resume KCV value is pinned from the base | AT-E0, AT-K2 | change one line inside a moved body; change the resume label | E0, E1 |
| 10 | Frozen contract drift | format, labels, corpus, contract note, public names, dependency set and fragments change together; `--json` change is additive; resume bytes unchanged | AT-V15, AT-K2, AT-P1, CV-1, CV-9, `docs/frozen-surfaces.md` rows | keep `decoy-vault/v2` in the frozen-surface row | E-DEP, E1, C1 |

## 14. Pre-mortem

- "E1 broke F22 adopt." Guard: AT-V14 plus the unchanged F22 suites in the T1 set.
- "Someone wrote framing code next to libsodium." Guard: AT-V18 keeps `nacl` in one module; AT-V19 pins known answers; section 2.1 says what Decoy adds and nothing else.
- "PyNaCl did not install on a customer's Windows box." Guard: AT-P1 checks wheels for every target in the lock; 1.6.2 ships `win_amd64` and `win_arm64`.
- "The DP certified stack stopped matching." Guard: CV-9 and the per-release certification step move the `requirements-certified.txt` pins and the fingerprint row together.
- "A wrong key now says tampered and users delete good vaults." Guard: AT-V7 and CV-6.
- "`decoy unmask` still prints the old text." Guard: CV-5 runs the real engine path, which raises `ExecutionError`.
- "The resume store stopped resuming after the KCV move." Guard: AT-K2.
- "The writer's secret outlived the run." Guard: AT-V12, CV-8.
- "The move to `cli/vault/` lost the 24zw help fix." Guard: C1 depends on 24zw C1.
- "The vault format changes again after 1.0 for domain versions." The 1.1+ work adds fields in a later format version. The header is a closed set so that change is explicit.

## 15. Owner questions

| Id | Question | Options | Status |
|---|---|---|---|
| Q1 | How is the KCV bound? | A: per secret. B: bound to `vault_id` | Decided 2026-11-18: B |
| Q2 | Drop the v2 reader? | A: hard cut. B: keep a read-only v2 path | Decided 2026-11-18: A (approved; section 6) |
| Q-B | Segment framing | A: own framing on `cryptography`. B: Tink. C: libsodium secretstream via PyNaCl | Decided 2026-11-18: C |
| Q-C | Census growth | A: raw-bytes `open_vault`, about +4 entries. B: provider argument, about +3. No-growth design (`PreparedSecret` and key sources) | Decided 2026-11-18: the no-growth design |
| Q-D | `VaultWriter` signature | A: `(mask_key, *, key_version)`. B: `(prepared)` | Decided 2026-11-18: B |
| Q4 | Leave the SQLite `decoy tokenize --vault` store out? | A: out. B: in | Open; recommended A. Does not block any slice |
| Q-A | Vault id display | A: 12 hex characters in text mode, the full id in `--json`. B: the full id everywhere | Open; recommended A. C1 builds A unless told otherwise |

F09 Q3 and Q5 to Q7 are about domain versions and stay with the 1.1+ plan.

## 16. Unresolved

None that blocks a slice. If Q4 is answered B, the SQLite token store becomes a separate plan; it shares no file with this one.

## 17. Follow-ups (not 1.0 blockers)

- Reserve the derive namespaces `vault` and `key-check` in `NamespaceRegistry` so that no user column namespace can equal them (Dennis L6). Today `vault_id` makes a collision useless to an attacker, but the reservation states the rule.
- A real Windows install, import and secretstream round trip of the engine wheel set (AT-P1 only reads wheel tags). Owned by WIN-FEAS (row 89) and WIN-RUNNER (row 6).
- Move `assert_keyed_with` and the execution callers to `PreparedSecret` when the execution key path moves (would remove two more census entries).
