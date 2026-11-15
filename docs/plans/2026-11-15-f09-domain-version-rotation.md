Status: plan

# F09: domain-version object, rotation and remap (engine); authenticated, versioned vault header (roadmap row 79)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-15. Revision 3 (Dennis r1 and r2 GO-WITH-FIXES fixes applied in place; resolution lists in section 17). Scope: engine slices E0 to E5, then one CLI slice C1. V1 (row 79, `V1*` reduced scope).

Rules consulted: `dev-rules/README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1/R2 tiers), `development-loop.md` (PLAN: guarantee, design notes, choke point, Placement, Established solutions), `feature-dev.md`, `cross-cutting-concerns.md`, `security.md`, `api-and-compatibility.md` (vault and run-result formats), `architecture.md` (Layout), `testing.md` (Test depth, full-suite triggers), `documentation.md`, `workspace-and-vcs.md` (Commit messages), `reuse-first.md`, `exploration.md`, `scope-discipline.md`, `verification.md`, `observability-and-resilience.md`, `config-secrets-and-supply-chain.md`, `catalogs/recurring-defects.md` (classes 1 to 11); engine `CODEMAP.md` "Where Things Go" (`CODEMAP.md:232-276`), `src/decoy_engine/_MAP.md`, `.importlinter`; engine `docs/compatibility-contract.md` section 3.2 (the vault is forever-readable once one exists in the wild; pre-GA hard cuts are legal) and section 3.1 (optional fields under `decoy-run-result/v1`); engine `docs/security/token-vault.md`; the V1 bar (only a function break, data loss, a non-admin value leak or cascading design blocks V1); the V1 threat model (accidental leaks only).

Base: engine `main` at `dcc4bcb3`, the exact tree used for this revision. The B-6 vault core merged as `c86ca58d` (#559) and ships from engine 0.24.0.

Sources: CLI roadmap row 79 (`docs/ROADMAP.md:406`); row detail "F09 (row 79)" in CLI `docs/roadmap/row-detail.md:155-159`; findings register G9 (CLI `docs/roadmap/findings-register.md:33`); review finding 11.8 (platform archive `docs/archive/audits-completed/cross-model-reviews/11-engine-crypto-determinism.md:63-66`); the F09 contract in the vault note `MASTER-Decoy-Feature-Specification.md` section F09; the QA readiness map (CLI `docs/records/2026-11-14-qa-readiness-map.md:47,64-66`), which holds QA section
16 (VAULT-08, VAULT-10) and section 05 (KEY-13) until this row lands.

## 1. FRAME

### What and why

Decoy promises that equal identities get equal protected values across jobs, and that an operator can change keys on purpose. Today the engine has the primitive (namespace-scoped keyed derivation, `key_version` mixed into the mask root at `src/decoy_engine/keyprovider.py:168`) but no record of which key era and which transform produced an output. Nothing tells an operator what a key change will break, and nothing moves an existing output to a new key. Separately, review finding 11.8 (G9) found that the `decoy-vault/v2` file has a cleartext, unauthenticated header, and that its Fernet chunks are keyed the same for every vault under one mask key, so chunks can be reordered, dropped or spliced between vaults without detection.

Row 79 closes both:

1. **Domain-version object (engine).** An immutable, content-addressed record of one identity
   domain: input type, canonicalization, namespace, transform, key version, output format and
   collision policy. Its id changes when any of those change, so "an active version changed in
   place" cannot happen by construction.
2. **Rotation (engine).** Three modes: `preserve` (same logical key, new custody), `new_version`
   (activate a new key version) and `remap` (move named datasets to the new version). An impact
   preview names the affected fields, joins and counts and reads no data.
3. **Remap (engine).** A versioned, value-free remap manifest, and an apply step that moves
   selected columns of existing masked tables to the new version where the inputs can be
   recovered (fpe inverse, vault lookup). One-way columns without a vault are refused, never
   guessed.
4. **Authenticated, versioned vault header (engine format, CLI surface).** `decoy-vault/v3`: the
   header is bound into every chunk's authentication tag, chunks carry their position and a
   last-chunk flag, and each vault has its own random salt, so the 11.8 tamper, reorder,
   truncation and splice cases all fail closed.
5. **Evidence.** The run result records each keyed column's domain-version id and key version.

### Out of scope (non-goals)

- A domain registry, ownership or grants. Those are platform features (F09 contract, "Platform
  manages ownership and grants"); the platform is parked for CLI V1.
- CLI commands for rotation preview and remap. Owner question Q5 recommends a separate row.
- Rotation UI or approval workflow ("reduced scope defers the advanced UI", row detail).
- The SQLite tokenize store (`decoy tokenize --vault`). Owner question Q4.
- Remap of one-way columns without a vault, of `when`-conditioned columns, of composite-FK groups,
  of columns other columns derive from, of non-string source columns, of a selection that splits a
  domain version or an old vault, and on chunked or out-of-core routes. These are refused with a
  coded reason.
- Changing any masked output byte. No keyed derivation changes; the determinism goldens stay
  unchanged.
- Reading old `decoy-vault/v2` files (owner option A for B-6, 2026-11-13: hard cut). Q2 confirms
  the same rule for v3.
- Defending key check values against offline guessing of weak secrets (V2 threat model).

### The guarantee (pinned)

For every keyed column of a compiled plan, the engine computes exactly one domain version whose id is a pure function of the eight bound fields and every output-changing column field (the 4.3 bound/unbound table); any change to any of them (including the secret material) gives a new id, and no other input does. The impact preview is value-free and reads no source, output or vault. Remap output for a supported column is byte-identical to masking the original source under the new key, every other column is byte-identical to its input, row count and order are unchanged, and no domain version or old vault is left split across two keys; an unsupported, unverifiable, misaligned or incomplete remap returns nothing. A `decoy-vault/v3` file opens only when its header, every chunk, their order and their count are exactly what the writer produced under that key; every other case raises a coded error before any entry is returned.

## 2. Current behavior (engine `dcc4bcb3`)

- **Keyed columns** are classified by one registry: `ALWAYS_KEYED_STRATEGIES` and
  `column_is_keyed` (`src/decoy_engine/secret_providers/_requirements.py:173,210`), used for the
  config walk and for `secret_requirements_for_plan` (`_requirements.py:280`). `column_is_keyed` is
  not exported from the package.
- **Key version** is a non-secret label on every `KeyProvider`
  (`src/decoy_engine/keyprovider.py:116`), mixed into the mask root as HKDF info
  `decoy/mask/{key_version}` (`keyprovider.py:168`). Changing it changes every keyed output (QA
  KEY-13). The engine records it nowhere a user sees: the `Plan`
  (`src/decoy_engine/plan/_types.py:283`) carries no key version, and `decoy-run-result/v1`
  (`src/decoy_engine/run_result/_model.py:372`) has no key field. Only the resume fingerprint
  carries it (`src/decoy_engine/delivery/resume/_fingerprint.py:40`).
- **Namespaces** are bound per column (`ColumnSeed.namespace`) and listed on the plan
  (`NamespaceBinding`, `plan/_types.py:235`); relationships carry a namespace
  (`PlanRelationship.namespace`, `plan/_types.py:212`).
- **Vault file** `decoy-vault/v2`: magic `DCYVAULT2\n` (`src/decoy_engine/vault.py:112`), a
  length-prefixed cleartext JSON header written at `vault.py:356`, then independent Fernet tokens.
  The Fernet key is `derive(mask_key, "vault", b"vault-key/v1")` (`vault.py:106,177`), the same for
  every vault under one mask key. `load_vault` (`vault.py:474`) checks the header's `format` and
  `seed_protocol_version` (`vault.py:557`) and decrypts each frame in a loop (`vault.py:583`).
  Nothing binds the header, the chunk order or the chunk count.
- **Tokenize** (`src/decoy_engine/execution/_strategies/_tokenize.py:77`) derives under a
  vault-scoped subkey; existing tokens are reused, so a key rotation does not change a stored
  token.
- **Unmask** (`src/decoy_engine/unmask.py:223`) reverses fpe (unverified: FF1 is unauthenticated,
  so a wrong key gives wrong plaintext with no error) and vaulted one-way columns.
- `vault.py` is 600 lines; the engine root is at its 25-module fan-out cap
  (`tests/sentry/layout/test_package_fanout.py`); sub-packages do not count.

## 3. Established solutions (searched 2026-11-15)

Searches run: web search for "Tink streaming AEAD AES-GCM-HKDF segment nonce last segment flag header salt" and "key rotation tokenization re-tokenize key version key check value"; in-codebase search for `key_version`, `AESGCM`, `derive(`, the HKDF vectors, `derive_read` and the vault callers; qmd search of the wiki and repo docs for F09, "domain version rotation" and "token vault key rotation and remap".

| Problem | Established answer | Followed here |
|---|---|---|
| Authenticate a streamed, chunked ciphertext and its header | Online AEAD "STREAM" (Hoang, Reyhanitabar, Rogaway, Vizar, CRYPTO 2015), as shipped in Google Tink AES-GCM-HKDF streaming AEAD: random per-stream salt in the header, per-stream key = HKDF(key, salt), nonce = prefix, segment counter, last-segment flag | Yes. AES-256-GCM from `cryptography` (`AESGCM`, already an engine requirement shape at `secret_providers/_requirements.py:87`); key from the engine's own HKDF `derive`; the header digest as associated data of every segment; 4-byte counter and 1-byte last flag in the nonce |
| Keep Fernet and add a whole-file HMAC | Encrypt-then-MAC over the file | Rejected: Fernet cannot bind associated data, so position and the last-chunk flag would need a second hand-built layer |
| Identify a key era without exposing the key | Key check value (KCV), ANSI X9.24 practice; HashiCorp Vault Transform and Thales CT-V record the key version in the ciphertext header so the reader knows which key opens it | Yes: a 64-bit KCV derived by HKDF under its own label (`key-check/v1`) from the mask root, plus the existing `key_version` label |
| Rotate tokenization keys | Vault Transform: encode with the newest version, decode with any kept version; Thales CT-V: batch re-key; US patent 11381393: "data conversion" versus "application awareness" | Remap is data conversion for chosen datasets; new jobs encode with the new version; tokens already in a vault stay (the vault is authoritative) |
| Immutable versioned config object | Content addressing (Git objects, OCI digests): the id is the digest of a canonical serialization | Yes: id = SHA-256 of the engine's one canonical JSON form (`_canonical.canonical_json_bytes`) |
| Versioned value-free document with a tolerant reader | The engine's own `decoy-run-result/v1` pattern: strict write model, read model derived by `_value_free.derive_read` | Yes, for the domain-version and remap-manifest documents |

Custom code that remains: the per-strategy trait table (what canonicalization, output format and collision policy each keyed strategy has) is engine knowledge no library holds; the impact preview is a walk over the engine's own plan.

## 4. Behavior

### 4.1 Key check value (E1, used by E1 to E4)

`PreparedSecret.key_check_value() -> str` is the one KCV implementation: 16 lowercase hex characters, the first 8 bytes of `derive(<mask root>, "key-check", b"key-check/v1")`. The method derives from the existing `PreparedSecret` buffer without adding a raw-key parameter or local. Domain building and preview take admitted `PreparedSecret` objects, not newly unboxed key bytes. The vault factory calls the method while its existing admission scope is alive and passes the non-secret KCV into the writer. This reuses the secret-binding frames already covered by the secret-material census instead of creating a new boxed site. It refuses a prepared value that is not the 32-byte mask root (`weak_mask_secret`). Same secret and key version: same KCV. Different secret or different key version: different KCV because the key version is already inside the mask root.

### 4.2 Vault file `decoy-vault/v3` (E1)

Layout: magic `DCYVAULT3\n`, a length-prefixed header (canonical JSON, sorted keys), then length-prefixed segments. Header fields (closed set, all required):

| Field | Type | Meaning |
|---|---|---|
| `format` | `"decoy-vault/v3"` | version tag |
| `seed_protocol_version` | strict int | as v2 |
| `key_version` | label, `re.fullmatch` `[A-Za-z0-9._-]{1,64}` | the provider's key version |
| `key_check` | 16 lowercase hex, checked with `re.fullmatch` | KCV of the mask root |
| `vault_id` | 64 lowercase hex, checked with `re.fullmatch` | lowercase hex of 32 random bytes from `secrets.token_bytes`, the per-vault salt |
| `ambiguous_dropped` | strict int >= 0 | as v2 |
| `entry_count` | strict int >= 0 | rows across all segments |
| `segment_rows` | strict int > 0 | rows per segment |

Keys: decode the 64 hex characters to the original 32 `vault_id` bytes, then `K_vault = derive(mask_key, "vault", b"vault-key/v2" || uint32be(32) || vault_id_bytes)`, then AES-256-GCM. Segment `i` (0-based) nonce: 7 bytes from `derive(K_vault, "vault", b"vault-nonce/v1")`, then `i` as 4-byte big-endian, then `0x01` for the last segment and `0x00` otherwise. Associated data of every segment: SHA-256 of the exact framed header bytes. Each segment plaintext is the same Parquet chunk v2 writes. A vault with no entries writes one empty last segment, so its header is still authenticated.

Load order (each step refuses before the next runs, and no entry is returned on any refusal): key floor (`weak_mask_secret`), magic (`vault_unreadable`), header frame and strict header parse (`vault_unreadable`), `format` (`vault_format_unsupported`; a v2 file names the re-mask remedy), `seed_protocol_version` (`vault_protocol_version_mismatch`), KCV compare in constant time (`vault_key_mismatch`, the message names the header's `key_version`, never key bytes), then each segment decrypts in order; any tag failure, a missing last flag at end of file, data after the last segment, or a decoded row total that differs from `entry_count` is the new code `vault_tampered`.

Writer: `VaultWriter(prepared, *, file_access=None)` receives an admitted `PreparedSecret`, copies the already-derived mask root into the writer's existing secret-bearing state, and records `prepared.key_version` plus `prepared.key_check_value()`. `vault_writer_for_config` passes the admitted prepared object while its scope is alive. Publication (`_publish`) is unchanged.

One internal `vault/_load.py::_open_vault` owns file opening, strict header parsing, KCV checking, segment authentication and row-count checking and returns an internal authenticated-header plus entries result. `load_vault` and the new `read_vault_header` both call it, so the new reader cannot drift from the loader. `load_vault` keeps its existing compatibility signature and boxes its key in its already inventoried frame. `read_vault_header(path, prepared, *, vault=None, file_access=None)` accepts a redacted `PreparedSecret`, runs the full open, and discards entries. Both public functions have keyword-only `file_access=None` and `@fileaccess.entry_point`. The defining-module rows in `fileaccess.ENTRY_POINTS` are `decoy_engine.vault._load.load_vault` and `decoy_engine.vault._load.read_vault_header`. The writer row is `decoy_engine.vault._writer.vault_writer_for_config`; re-export names are not used because the file-access sentry normalizes them to defining modules (`tests/sentry/fa/resolve.py:85-102`).

### 4.3 Domain version (E2)

`DomainVersion` (frozen, slots) with eight bound fields (`key_version` and `key_check` are separate
wire fields):

| Field | Source |
|---|---|
| `input_type` | trait table, by strategy (for example `tokenize`: `string`; `date_shift`: `temporal`; `hash`: `canonical-any`) |
| `canon` | trait table label plus `SEED_PROTOCOL_VERSION`, for example `nfc-string/p2` |
| `namespace` | the column's resolved namespace; a keyed column without one gets the scope `column:<table>.<column>` |
| `transform` | strategy name plus `transform_digest`: SHA-256 of canonical JSON of every `ColumnSeed` field the bound/unbound table below marks bound, plus the explicit tokenize `token_vault_scope` digest where it applies |
| `key_version`, `key_check` | the admitted provider: label plus KCV (4.1) |
| `output_format` | trait table (for example `tok_hex32`, `ff1-charset`, `hex`) |
| `collision_policy` | trait table: `bijective`, `vault-authoritative`, `stateless-bounded`, `pooled-may-collide` or `permutation` |

`id` = `dv1_` plus the hex SHA-256 of the canonical JSON of the bound fields with `"schema": "decoy-domain-version/v1"`. Table and column names are not bound: two tables that use the same namespace and transform share one domain version (the CRM and billing example). `provider_config` values never leave the digest.

**Bound and unbound `ColumnSeed` fields** (`src/decoy_engine/plan/_types.py:67-138`). One table, `plan/domains/_traits.py:SEED_FIELD_BINDING`, classifies every field; a sentry (`tests/sentry/test_domain_seed_fields_classified.py`) compares it with `dataclasses.fields(ColumnSeed)` and fails on any field missing from the table, so a new output-changing field cannot be added without a decision.

| `ColumnSeed` field | Binding | Why |
|---|---|---|
| `namespace` | bound (own field) | scope of the keyed derivation |
| `strategy` | bound (`transform`) | selects the transform |
| `provider` | bound (digest) | faker provider changes output |
| `backend_type`, `backend_version` | bound (digest) | backend changes output |
| `cardinality_mode`, `deterministic` | bound (digest) | change the draw |
| `provider_config` | bound (digest) | parameters |
| `coherent_with` | bound (digest) | changes the derived value |
| `when` | bound (digest) | changes which rows are masked |
| `ner_model_version` | bound (digest) | changes `text_redact` spans |
| `pool_size`, `scale` | bound (digest) | change the generated value set |
| `vault` | bound (digest and collision policy) | changes reversibility, vault authority and the keyed contract |
| `technique_class`, `distribution_behavior` | unbound | display labels derived from the strategy; no output effect |

Every field marked bound is in the digest. The explicit tokenize `token_vault_scope` input is the runtime writer's `derivation_scope` (B-6 D2, `src/decoy_engine/execution/_adapter.py:103-112`) and is bound by its SHA-256 for tokenize domains only, because two vaults tokenize apart. The table is filled from the dataclass at E2 build time; the rows above are the classification at `dcc4bcb3`.

`domain_versions_for_plan(plan, prepared, *, token_vault_scope: bytes | None) -> DomainVersionSet`: one entry per keyed column in plan order. `prepared` is the admitted `PreparedSecret`. A plan with any `tokenize` column requires a 16 to 64 byte `token_vault_scope`; missing or malformed scope refuses with the existing `tokenize_vault_scope_required` code. A scope-unbound domain is not emitted because it would claim compatibility that the runtime token writer can disprove. A plan without `tokenize` requires no scope; a supplied scope is ignored and cannot affect unrelated domains. The keyed set comes from one walker: E2 factors the body of `secret_requirements_for_plan` (`_requirements.py:280`) into `_walk_keyed_plan_columns(plan)`, and both `secret_requirements_for_plan` and the new `keyed_columns_for_plan(plan)` call it, so there is one plan walk over `column_is_keyed`. The plan walk passes `deterministic=bool(seed.deterministic)` (`_requirements.py:288`) while the config walk also ORs `allow_collisions` (`_requirements.py:252`); DV-3 asserts the plan walk equals `keyed_columns_for_config` on a config that sets `allow_collisions`, and if they differ E2 makes the plan walk read the compiled equivalent (the divergence is fixed in the walker, never in the test). Each entry carries its table, column and domain version; composite-FK groups appear once per group with `transform` = the group's strategy. A namespace bound to two different transforms in one plan is reported in `DomainVersionSet.warnings` as `domain_namespace_shared`; runs are not changed.

`compare_domain_versions(recorded, current) -> DomainDrift`: per (table, column): `unchanged`, `new_version` (any bound field differs; the changed field names are listed), `added`, `removed`. `DomainVersion.to_dict` and `domain_version_from_dict` use a strict write model and a derived read model; the reader recomputes the id and refuses a document whose id does not match its fields (`domain_version_digest_mismatch`).

### 4.4 Rotation preview (E3)

`preview_rotation(plan, *, mode, current: PreparedSecret, target: PreparedSecret | None = None, token_vault_scope: bytes | None, datasets: Sequence[str] = ()) -> RotationPreview`. It passes `token_vault_scope` unchanged to every `domain_versions_for_plan` call. Reads no source, output or vault.

- `preserve`: `target` required. Refused with `rotation_key_not_preserved` unless the target's
  `key_version` equals the current one and the two KCVs match (constant time). On success every
  domain is `unchanged` and the preview lists zero affected fields.
- `new_version`: `target` required and its KCV must differ (`rotation_target_unchanged`
  otherwise). Every keyed column is affected: per column the from and to ids and changed fields;
  per relationship whose namespace is affected, a `join` entry (parent and child), flagged
  `breaks_against_old_outputs`; tokenize domains are marked `existing_tokens_stable`; counts of
  affected fields, domains, joins and tables.
- `remap`: as `new_version`, limited to the named `datasets` (table names; an unknown name is
  `rotation_dataset_unknown`), plus a `RemapManifest` (4.5) that records the `remap_domain_split`
  and `remap_vault_split` findings for the selection.

`RotationPreview.to_dict()` is value-free: names, ids, codes and counts only.

### 4.5 Remap manifest (E3) and apply (E4)

`RemapManifest` (`decoy-remap-manifest/v1`, strict write model, derived read model): `config_hash`, from and to key versions and KCVs, and per selected column: table, column, from id, to id, `method`, `status` and `reason`. `config_hash` has one producer: `plan.pipeline_config_hash` (the compiler's semantic config hash, `src/decoy_engine/plan/__init__.py:37`, exported as `decoy_engine.pipeline_config_hash`) applied to the validated config the preview compiled; no second hash is written.

One classifier exported by unmask, `unmask.reversal_method(column_cfg) -> ReversalDecision`, returns the base unmask branch, the stricter remap method, its expected report status and any unavailable reason. `unmask_pipeline` uses the base branch, so an existing undeclared string fpe column keeps its current unmask behavior. The manifest and the step-3 status check use the remap fields, which require a declared string type for fpe and vault lookup. This keeps the new remap eligibility rule in one descriptor without changing the older unmask contract. Guard cell RM-13 asserts both consumers follow the same decision for every strategy, vault flag and logical-type shape.

| Column kind | method | status |
|---|---|---|
| `fpe` | `fpe_inverse` | `planned` |
| one-way strategy with `vault: true` | `vault_lookup` | `planned` |
| `tokenize` | `vault_authoritative` | `no_change` |
| keyed one-way without vault | `none` | `unavailable` (`remap_source_unavailable`) |
| column with `when`, or a column another column derives from (`derived`, `formula`, `derived_aggregate` reference it) | `none` | `unavailable` (`remap_column_conditional`) |
| composite-FK group member | `none` | `unavailable` (`remap_composite_unsupported`) |
| fpe or `vault: true` column whose `ColumnConfig.logical_type` is absent or is not `string`, or whose input dtype in `masked` is not string | `none` | `unavailable` (`remap_source_type_unsupported`) |

Selection-level refusals (computed by `preview_rotation` for the manifest and again by `apply_remap`):

- `remap_domain_split`: the selection holds some but not all columns of an affected domain version
  (across all tables of the config). This replaces the old per-row `remap_join_split`: an FK side
  without its other side is the commonest split domain, and the domain rule also covers two
  unrelated tables that share a namespace. Remapping one side of a shared domain would leave two
  keys on one identity.
- `remap_vault_split`: a `vault: true` column the old vault covers is not selected, so the new
  vault would hold only part of the old one's columns.

Why non-string sources are refused (Q6): `unmask._decrypt_column` and `_vault_recover_column` return `pa.string()` (`src/decoy_engine/unmask.py:168,216`) and the vault stores `str`, while the mask path canonicalizes an int through `_encode_int` (`src/decoy_engine/generation/pool/_canonicalize.py:89`), so re-masking a recovered `"42"` would not equal masking the original `42`. `ColumnConfig.logical_type` defaults to `None` (`src/decoy_engine/config/_tables.py:141`), so a string dtype in `masked` cannot prove that the source was string. Undeclared is therefore refused exactly like a declared non-string type. Recording and restoring source types is deferred (V2-LOG).

`apply_remap(manifest, masked, *, config, current: PreparedSecret, target: PreparedSecret, vault=None, engine_version, file_access=None) -> RemapResult` is a file-access entry point (it may open the old vault): keyword-only `file_access`, `@fileaccess.entry_point`, a new `ENTRY_POINTS` row `"decoy_engine.domains._remap.apply_remap"`. The normalized registry names the defining module.

1. Refuse before reading any table: manifest version (`remap_manifest_unsupported`); any
   `unavailable` row (`remap_source_unavailable`, naming the column count, not values); a domain or
   vault split (`remap_domain_split`, `remap_vault_split`); the `current` provider's KCV not equal
   to the manifest's from KCV (`remap_key_mismatch`); the `target` provider's `key_version` and KCV
   not equal to the manifest's `to` pair (`remap_target_mismatch`); `pipeline_config_hash(config)`
   or the domain versions recomputed from `config` and `current` not equal to the manifest
   (`remap_manifest_stale`); a `vault_lookup` column without `vault` (`remap_vault_required`); a
   selected fpe or `vault_lookup` column whose declared `logical_type` is absent or not `string`,
   or whose dtype in `masked` is not string (`remap_source_type_unsupported`). The declaration
   check is repeated here even when a manifest row was edited to `planned`.
2. Build one `RemapProjection` from the validated config and selection, then recover with
   `unmask_pipeline(projection.config, masked, key_provider=current.key_provider(), vault=vault)`.
   The projected config keeps each selected column's original entry, makes every unselected column
   `passthrough`, and applies the step-4 allowlist. An unselected reversible column is therefore
   never decrypted and cannot poison the passthrough check.
3. Status check: for every selected column, `UnmaskColumnReport.status` must equal the status its
   method expects (via `reversal_method`): `reversed_unverified` for `fpe_inverse`;
   `vault_reversed` with `misses == 0` for `vault_lookup`. Anything else (`irreversible`,
   `untouched`, `vault_miss`, a partial miss, a nested fpe that unmask does not reverse) refuses
   the whole remap (`remap_source_unavailable`, a count only). So that "zero misses" is checked
   without parsing `detail`, `UnmaskColumnReport` (`unmask.py:80-86`) gains two additive integer
   fields, `hits: int = 0` and `misses: int = 0`, filled on the vault path; `status` and `detail`
   are unchanged.
4. Re-mask with `run_pipeline(projection.config, recovered, key_provider=target.key_provider(),
   execution_mode="full_frame", vault_writer=<a writer for target, when vault columns are
   selected>)`. `RemapProjection` is built once from an allowlist, not by editing a copy: it keeps
   `tables[].name`, the selected columns' entries, every other column as `passthrough`,
   `namespaces`, the `relationships` among kept columns and the keyed globals (seed protocol,
   secret reference). It drops `TableConfig.transforms` (filter, sort, limit, dedupe, derive,
   drop_column; `src/decoy_engine/config/_transforms.py:45-120`), `generate_columns`, `row_count`,
   `when`, casting, scans and delivery. A key not on the allowlist is dropped, so a new config key
   defaults to dropped (RM-10 names the dropped keys). Recovery and re-mask use this same
   projected object, so their column selection cannot drift.
5. Row alignment check: for every table, the re-masked row count equals the input row count and
   every passthrough column is byte-equal to its input column; otherwise
   `remap_row_alignment_failed` and nothing is returned. The pandas route can change a
   passthrough dtype while preserving displayed values, so this check may refuse a remap that
   looks value-equal. That is the safe result. Builders must not weaken the check to values-only,
   coerce dtypes, or compare through pandas to make such a case pass.
6. Splice: the result tables are the input masked tables with only the selected columns replaced.
   `RemapResult` carries the tables, a per-column report, the unwritten new vault writer and
   `domains` evidence in the E5 shape (`{table, column, domain_id, key_version}` for every keyed
   column of the output, selected or not). `docs/identity-domains.md` states that this evidence is
   the record of which key each output column uses. The caller writes the new vault before any
   output, the same B0 order `decoy run` follows. Nothing is returned on any refusal.

Plaintext lives only in memory between steps 2 and 5, as in `unmask_pipeline` today.

### 4.6 Evidence (E5)

`decoy-run-result/v1` gains an optional `domains` field: a tuple of `{table, column, domain_id, key_version}` (named value-free types; `key_check` is not repeated, it is inside the id). Left out of the dump when unset, so an old record keeps its wire form.

The evidence is computed inside `run_pipeline` from the exact compiled plan and the exact
`AdmittedKey.prepared` whose provider executes the run. `PipelineRunContext` gains an
`admitted_secret: PreparedSecret | None` reference and `build_run_context` assigns
`admitted.prepared`; the existing `AdmissionScope` remains its sole owner and closes it. A keyed
plan requires this field to be non-`None`; an unkeyed plan emits no domain evidence. No key bytes
are copied and no second secret-bearing wrapper is introduced. `_pipeline_context` passes the
already validated `token_vault_writer.derivation_scope`, or `None`, explicitly to
`plan.domains.domain_versions_for_plan`. The one final return in `execution/_pipeline.py` stamps
the resulting value-free domain evidence onto the additive `ExecutionResult.domains` field after
every resident, chunked, sequential and out-of-core route. No route constructs evidence and the
CLI never admits or reads the secret again. C1 only copies `ExecutionResult.domains` into the
run-result model. This prevents a secret rotation between execution and evidence from recording
the wrong domain id.

## 5. Failure modes

| # | Failure | Where it would come from | Closing structure | Cells |
|---|---|---|---|---|
| F1 | Vault header edited (for example `ambiguous_dropped` lowered) and still opens | 11.8: header not authenticated | header digest is associated data of every segment | VH-2, VH-9 |
| F2 | Segments reordered, dropped at the end, or spliced from another vault | Fernet keyed per mask key, no position | per-vault salt in the key; counter and last flag in the nonce | VH-3, VH-4, VH-5 |
| F3 | Ordinary wrong key reported only as generic tampering | one tag failure for both | KCV compare before any decrypt; an edit to the KCV field itself can still look like a wrong key (V2-LOG) | VH-6 |
| F4 | v2 file read silently, or read wrongly as v3 | format dispatch | magic and `format` checked; v2 refused with the remedy | VH-7 |
| F5 | Value in a header, error, log, preview or manifest | new documents and messages | closed header and document fields; value-free named types; canary scans | VH-8, DV-7, RP-3, RM-7 |
| F6 | Domain id unchanged after a real change (secret, parameter, protocol) | a bound field left out of the digest | id over all eight fields; per-field sensitivity cells | DV-4 |
| F7 | Domain id changes for a non-identity reason (table name, column order, dict order) | non-canonical serialization | canonical JSON choke point; names not bound | DV-1, DV-4b |
| F8 | A keyed strategy has no traits, or the builder's keyed set drifts from the secret classifier | a second strategy list | one registry (`column_is_keyed`) and a completeness sentry | DV-2, DV-3 |
| F9 | Preview reads data or has side effects | convenience reads | preview takes only plan, prepared secrets, token scope and dataset names | RP-3 |
| F10 | `preserve` accepted for a different secret under the same label | label-only compare | KCV compare | RP-2 |
| F11 | fpe remap under the wrong old key writes plausible wrong values | FF1 is unauthenticated | KCV of `current` against the manifest before any read | RM-3 |
| F12 | Partial remap returned (some columns or rows moved, some not) | per-column errors after partial work | all refusals before step 2; a miss refuses the whole result | RM-4, RM-5 |
| F13 | Remap breaks an FK join, splits a shared domain or an old vault, or leaves a derived column stale | one side remapped | `remap_domain_split`, `remap_vault_split`, `remap_column_conditional` | RM-6, RM-14, RP-5 |
| F14 | Stale manifest applied to a changed config | config edited after preview | ids recomputed, `remap_manifest_stale` | RM-8 |
| F15 | Old record unreadable after the run-result change | a required field | optional field, excluded when unset | EV-1, EV-2 |
| F16 | Error carries a path, value or OS text via exception context | `raise ... from exc` | raise after the `except` block; contexts asserted `None` for every error the new code raises (errors passed through from `unmask_pipeline` keep its existing value-free `__cause__`, V2-LOG item 4) | VH-10, RM-7 |
| F17 | Remapped int or date column differs from a fresh mask, including an undeclared source whose masked dtype is string | unmask returns `pa.string()`; int canonicalization differs; masked dtype cannot recover the missing declaration | declared `logical_type == "string"` and masked string dtype required before any read | RM-9, RM-9a |
| F18 | Remap output rows filtered, sorted or deduplicated, so other columns no longer line up | `TableConfig.transforms` kept in the projected config | allowlist-built `RemapProjection`; row count and passthrough byte-equality check (`remap_row_alignment_failed`) | RM-10 |
| F19 | A selected column unmask did not reverse (nested fpe, irreversible, partial miss) passes through and is re-masked from masked values | only vault misses checked | per-column status check against `reversal_method`; `hits`/`misses` fields | RM-5, RM-11, RM-13 |
| F20 | Remap writes under a target key other than the one previewed | target not checked against the manifest | `remap_target_mismatch` | RM-12 |
| F21 | A new output-changing `ColumnSeed` field leaves the domain id unchanged | field list in the digest written by hand | `SEED_FIELD_BINDING` table and its sentry | DV-9 |
| F22 | An unselected reversible column is decrypted, then fails passthrough equality or is returned under the wrong key | recovery uses the full config instead of the selection | one `RemapProjection` makes all unselected columns passthrough for both recovery and re-mask | RM-16 |
| F23 | Evidence names a different key or token scope from the one that produced the output | CLI re-admits after execution, or one execution route skips evidence | stamp once at the final `run_pipeline` return from the exact admitted secret and executing writer scope | EV-3, CV-4 |

## 6. Design notes and choke points

- **Principles.** One place per fact: the keyed-column rule stays in `column_is_keyed`; the KCV in
  `PreparedSecret.key_check_value`; canonical bytes in `_canonical`; per-strategy domain traits in
  `plan/domains/_traits.py`. Typed context objects (`DomainVersion`, `RotationPreview`,
  `RemapManifest`) instead of dicts. No flag arguments: the three rotation modes are a `Literal`
  with one handler each.
- **Choke point 1, keyed set.** `keyed_columns_for_plan` beside `secret_requirements_for_plan`
  (both on `_walk_keyed_plan_columns` over `column_is_keyed`). Guard: DV-3 compares the builder's
  set with `keyed_columns_for_config` for a mixed plan that sets `allow_collisions`. Mutation: give the builder its own `{"hash", "fpe", "tokenize"}` list (DV-3 red).
- **Choke point 2, traits.** `DOMAIN_TRAITS` keyed by strategy; the sentry
  `tests/sentry/test_domain_traits_complete.py` requires an entry for every member of
  `ALWAYS_KEYED_STRATEGIES` and for the generic keyed case (a `vault: true` or `deterministic`
  otherwise-unkeyed strategy). Mutation: delete the `tokenize` entry (sentry red).
- **Choke point 3, KCV.** Every KCV goes through `PreparedSecret.key_check_value`. Guard:
  `tests/sentry/defects/test_key_check_choke_point.py` fails on the `key-check/v1` label outside
  `secret_providers/_types.py`. Mutation: inline the derive in `vault/_format.py` (sentry red).
- **Choke point 4, vault format and open.** `vault/_format.py` owns the magic, header model,
  framing and segment AEAD. `vault/_load.py::_open_vault` is the sole read state machine used by
  both public readers. The route sentry `tests/sentry/test_vault_writer_routes.py` stays as is.
- **Choke point 5, reversal decision.** `unmask.reversal_method` returns the one descriptor of the
  base unmask branch and stricter remap eligibility; `unmask_pipeline`, the manifest builder and
  the remap status check consume its named fields. Guard: RM-13. Mutation: give the manifest
  builder its own `strategy == "fpe"` test that misses nested fpe and undeclared types (RM-13 red).
- **Choke point 6, keyed plan walk.** `_walk_keyed_plan_columns` is the one plan walk;
  `secret_requirements_for_plan` and `keyed_columns_for_plan` both call it (choke point 1 is its
  guard).
- **Choke point 7, seed field binding.** `SEED_FIELD_BINDING` decides which `ColumnSeed` fields
  enter the digest. Guard: DV-9 sentry. Mutation: remove the `when` row (sentry red).
- **Choke point 8, remap projection.** One `RemapProjection` builds the allowlisted config used by
  both recovery and re-mask. Guard: RM-10 and RM-16. Mutation: pass the full config to
  `unmask_pipeline` while keeping the projected config for re-mask (RM-16 red).
- **Choke point 9, execution evidence.** The final return in `execution/_pipeline.py` stamps
  domains produced from the context's compiled plan, admitted prepared secret and explicit token
  scope onto every route result. Guard: EV-3 walks the route matrix. Mutation: let one route
  return before the stamp, or re-admit the secret after execution (EV-3 red).

## 6a. Enumerations (from the code at `dcc4bcb3`)

### Exit paths

- `load_vault` and `read_vault_header`: key floor, magic, header frame, header parse, format,
  protocol, KCV, each segment, end of stream (4.2). Today's checks are at
  `src/decoy_engine/vault.py:557` and the decrypt loop at `src/decoy_engine/vault.py:583`; every
  refusal raises after its `except` closes.
- `VaultWriter.write`: crypto import, key floor, segment encryption, publish
  (`src/decoy_engine/vault.py:394` `_publish`, unchanged: `vault_exists`, `vault_commit_failed`).
- `preview_rotation`: mode and target checks (`rotation_key_not_preserved`,
  `rotation_target_unchanged`, `rotation_dataset_unknown`), then pure computation.
- `apply_remap`: the pre-read refusals of 4.5 step 1, then unmask errors (passed through
  unchanged), the status-check refusal (step 3), `run_pipeline` errors (passed through), then the
  row alignment refusal (step 5). The engine stages
  nothing, so there is no cleanup path; the caller writes the new vault.
- `domain_version_from_dict`, `remap_manifest_from_dict`: strict read refusals.

### Routes

- Vault write: only resident routes take a writer (`tests/sentry/test_vault_writer_routes.py`,
  `run_pipeline` at `src/decoy_engine/execution/_pipeline.py:115`); unchanged.
- Remap re-mask: `run_pipeline(..., execution_mode="full_frame")` only. Chunked, sequential and
  out-of-core are not used; a remap larger than the full-frame reject limit fails with that
  route's existing error before any work.
- Preview and domain building: no execution route.
- Unmask: `unmask_pipeline` (`src/decoy_engine/unmask.py:223`), full-frame.

### FK shapes

- Single-column FK, parent and child in one namespace: both sides share one domain version;
  remap of both together keeps the join (RM-6); one side alone is `remap_domain_split`.
- Single-column FK with `PlanRelationship.namespace` `None` (`src/decoy_engine/plan/_types.py:212`):
  the preview reports the join under the parent column's domain.
- Composite FK (seed `per_group`, keyed by `secret_requirements_for_plan` at
  `src/decoy_engine/secret_providers/_requirements.py:280`): one domain version per group; remap
  `remap_composite_unsupported`.
- fpe join groups (tweak scope `join_group`): same namespace, same transform, one domain; remap
  keeps the group because the derived config keeps the group's columns.

### Fields (every key this plan adds)

- `decoy-vault/v3` header: `format`, `seed_protocol_version`, `key_version`, `key_check`,
  `vault_id`, `ambiguous_dropped`, `entry_count`, `segment_rows` (4.2).
- `decoy-domain-version/v1`: `schema`, `input_type`, `canon`, `namespace`, `transform`
  (`strategy`, `transform_digest`), `key_version`, `key_check`, `output_format`,
  `collision_policy`, `id`.
- `decoy-remap-manifest/v1`: `schema`, `config_hash` (from `pipeline_config_hash`), `from` and
  `to` (`key_version`, `key_check`), `columns[]` (`table`, `column`, `from_id`, `to_id`, `method`,
  `status`, `reason`), `selection_refusals[]` (`code`, `domain_id`, `column_count`).
- `UnmaskColumnReport`: additive `hits`, `misses` (ints, default 0).
- `RemapResult.domains[]`: the E5 shape.
- `decoy-run-result/v1` optional `domains[]` (`table`, `column`, `domain_id`, `key_version`),
  beside `sample` at `src/decoy_engine/run_result/_model.py:392`.

### Output surfaces

- The vault file (only the header is cleartext; it holds labels, digests, counts and a random
  salt).
- `RotationPreview.to_dict()`, `DomainVersion.to_dict()`, `RemapManifest.to_dict()`: names, ids,
  codes, counts.
- `RemapResult.tables` (masked values only), its report, and the new vault writer.
- `decoy-run-result/v1` `domains`.
- Error messages and log lines from all of the above: codes, counts, table and column names, the
  vault's display path (as today), never a value, key byte or `provider_config` value.

## 7. Value-free rules

- Header, domain version, preview and manifest are closed models with value-free named types
  (`_value_free`), so a free string cannot ride in.
- `transform_digest` is the only trace of `provider_config` (which can hold literals such as a
  redact replacement or categorical values).
- Remap never logs per-row data; a miss reports a count.
- Errors follow defect class 3: the safe error is raised after the `except` block, with
  `__cause__` and `__context__` both `None`.

## 7a. Class table

| Class | Name | Where it can occur here | Closing structure | Sentry or property test | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | vault header, preview, manifest, domain JSON, remap errors | closed value-free models; `provider_config` only as a digest | VH-8, RP-3, RM-7, DV-7 canary scans | emit `provider_config` raw into `transform` (RP-3 red) |
| 2 | Cleanup missing on an exit path | `VaultWriter.write` stage | unchanged `_publish` stage handling; remap stages nothing | existing `tests/unit/test_vault_publish.py` | N/A: no new staged artifact, and the existing publish mutations stay |
| 3 | State machine and concurrency | vault segment order, last flag | counter and last flag in the nonce; end-of-stream check | VH-3, VH-4 | fix the counter at 0 (VH-3 red) |
| 4 | Route parity and silent fallback | remap on a non-resident route | remap pins `full_frame`; vault writer route sentry unchanged | RM-1, RM-2, `test_vault_writer_routes.py` | call `run_pipeline` with `auto` and a small chunk threshold (RM-2 red via `vault_requires_resident_output`) |
| 5 | Referential integrity | remap of one FK side or one table of a shared domain; row order changed by kept transforms; unselected reversible column decrypted | `remap_domain_split`; one projected config keeps relationships among selected columns, makes unselected columns passthrough and drops transforms; row alignment check | RM-6, RM-10, RM-14, RM-16 | drop the domain-split check (RM-6 red); recover with the full config (RM-16 red) |
| 6 | Untrusted producer | vault header, manifest and domain documents read back | strict readers; id recomputed; header authenticated | VH-2, VH-11, DV-6, DV-7, RP-6 | trust the stored domain id (DV-6 red) |
| 7 | Check then use (TOCTOU) | manifest checked, then config changes | `apply_remap` recomputes ids from the `config` it is given and uses only that config | RM-8 | compare the manifest's ids with themselves (RM-8 red) |
| 8 | Weak tests | remap tests that pass with any output | oracle is a fresh mask from source under the target key, byte-identical | RM-1, RM-2 | swap target and current in step 3 (RM-1 red) |
| 9 | Refactor drift | E0 move of `vault.py` into `vault/` | pure move checked by `scripts/check_pure_move.py`; tests change import paths of private names only | existing vault suite unchanged | N/A for E0: a pure move with no behavior to mutate, verified by the checker |
| 10 | Frozen contract drift | `decoy-vault`, labels, run-result v1, public API, reason registry | v3 new tag, v2 refused; run-result optional field; registry append-only | VH-7, VH-13, EV-1, EV-2, `test_public_api.py`, reason baseline sentry | write `"format": "decoy-vault/v2"` in v3 (VH-7 and the corpus cell red) |

## 8. Acceptance tests (red first)

Every cell is written before its slice's code and fails on the base tree (a missing name counts as red only where the cell also asserts behavior). Count: 56 cells, 50 engine (VH 13, DV 10 with DV-4b, RP 7, RM 17 with RM-9a, EV 3) and 6 CLI (CV). Revision 1 had 44 (39 engine, 5 CLI); its report's 46 was a miscount. "Mut" marks the cells whose closing structure gets a seeded mutation in the gate (`mutmut` or the hand mutation named in the cell).

### E1, vault v3 (`tests/unit/vault/test_v3_format.py`, `tests/unit/vault/test_v3_tamper.py`)

| Cell | Asserts | Failure it catches | Mut |
|---|---|---|---|
| VH-1 | write then load round-trips the mapping and `ambiguous_dropped`; the header has the eight fields with correct types; `key_version` equals the writer's | broken v3 writer or reader | |
| VH-2 | lower `ambiguous_dropped` in the header (re-framed) gives `vault_tampered` and no mapping | F1 | drop the associated data |
| VH-3 | two segments swapped (writer built with `segment_rows=2`) gives `vault_tampered` | F2 order | fix the counter at 0 |
| VH-4 | last segment removed gives `vault_tampered`; bytes after the last segment give `vault_tampered` | F2 truncation and extension | ignore the last flag |
| VH-5 | a segment from vault A (same key, same entries) put into vault B gives `vault_tampered` | F2 splice (11.8) | derive `K_vault` without `vault_id` |
| VH-6 | a wrong 32-byte key gives `vault_key_mismatch` with no AES call (spy); the message names the header key version and holds no key bytes | F3 | skip the KCV compare (the error becomes `vault_tampered`) |
| VH-7 | a v2 file (corpus fixture) gives `vault_format_unsupported` with the re-mask remedy; a v3 file whose header says `decoy-vault/v2` likewise | F4 | accept the `decoy-vault/v2` tag in the v3 reader |
| VH-8 | canary source values absent from the vault bytes; header keys are exactly the closed set (QA VAULT-10) | F5 | |
| VH-9 | an empty vault opens with zero entries; its header edited gives `vault_tampered` | F1 on the empty path | |
| VH-10 | every `VaultError` raised in VH-2 to VH-7 has `__cause__ is None` and `__context__ is None` | F16 | |
| VH-11 | strict header read: `True` or `"5"` for `entry_count`, `"v1\n"` for `key_version`, an extra key, a missing key: all `vault_unreadable` | defect classes 1, 2, 4 | |
| VH-12 | `PreparedSecret.key_check_value`: 16 hex; stable for one key; differs for a different secret and for a different `key_version`; refuses a short prepared mask root | KCV contract | truncate to 4 bytes (length assertion red) |
| VH-13 | compat corpus: `decoy-vault-v3__synthetic.vault` round-trips and its header tamper bite-test fires | F4 at format level | |

### E2, domain version (`tests/unit/contracts/test_domain_version.py`, `tests/unit/plan/domains/test_build.py`; sentry `tests/sentry/test_domain_traits_complete.py`)

| Cell | Asserts | Failure it catches | Mut |
|---|---|---|---|
| DV-1 | permanent golden vectors `tests/fixtures/domains/domain-version-v1-vectors.json`: fixed inputs give fixed canonical bytes and ids | F7 | serialize without sorted keys |
| DV-2 | every `ALWAYS_KEYED_STRATEGIES` member and the generic keyed case has traits (sentry) | F8 | delete the `tokenize` traits |
| DV-3 | for a config mixing keyed, unkeyed, `nested`, `vault: true` faker, `allow_collisions` and a composite FK, the builder's (table, column) set equals `keyed_columns_for_plan`, which equals `keyed_columns_for_config` on the source config; `secret_requirements_for_plan` and `keyed_columns_for_plan` both call `_walk_keyed_plan_columns` (spy) | F8 | builder-owned strategy list; a second plan walk without `allow_collisions` |
| DV-4 | changing each bound field alone (namespace, one `provider_config` key, `cardinality_mode`, `provider`, `pool_size`, `scale`, `coherent_with`, `when`, `ner_model_version`, `vault`, the explicit tokenize `token_vault_scope` bytes, key version, secret bytes, the canon label) changes the id; a tokenize plan with no scope or a malformed scope refuses with `tokenize_vault_scope_required`; changing `technique_class` or `distribution_behavior` does not | F6 and an unbound token domain | drop `key_check` from the digest; drop `when` from the digest; ignore `token_vault_scope` |
| DV-4b | two tables with the same namespace and transform give one id; renaming a table or reordering columns does not change it | F7, contract example 1 | |
| DV-5 | a namespace used by two transforms in one plan yields both versions and the `domain_namespace_shared` warning; the run output is unchanged | silent domain conflict | |
| DV-6 | `domain_version_from_dict` refuses a document whose `id` does not match its fields (`domain_version_digest_mismatch`) | untrusted producer | trust the stored id |
| DV-7 | strict reader cells: next major, missing `schema`, a bool for a string, free text for `collision_policy`, `"v1\n"`; a canary in `provider_config` never appears in `to_dict()` | F5, defect classes 1, 2, 4 | |
| DV-8 | `compare_domain_versions` classifies unchanged, new version (with changed field names), added, removed | drift report | |
| DV-9 | sentry: the keys of `SEED_FIELD_BINDING` equal `{f.name for f in dataclasses.fields(ColumnSeed)}`; a synthetic subclass with an extra field fails the check | F21 | remove the `when` row (sentry red) |

### E3, rotation preview and manifest (`tests/unit/domains/test_rotation.py`, `tests/unit/contracts/test_remap_manifest.py`)

| Cell | Asserts | Failure it catches | Mut |
|---|---|---|---|
| RP-1 | `new_version`: every keyed column affected; each relationship on an affected namespace listed as a join with `breaks_against_old_outputs`; counts match | wrong impact | |
| RP-2 | `preserve`: the same bytes through `env:` and `file:` providers under one label are preserved with zero affected; different bytes under the same label give `rotation_key_not_preserved` | F10 | compare labels only |
| RP-3 | the preview, with file access patched to raise on any open, still succeeds; its `to_dict()` holds no canary from `provider_config` or sources | F9, F5 | put raw `provider_config` in the output |
| RP-4 | tokenize columns are `existing_tokens_stable` | misleading preview | |
| RP-5 | `remap` manifest methods and statuses follow the 4.5 table for one plan holding every row kind, including a `derived` column that reads a selected column | wrong method, F13 | |
| RP-6 | manifest strict read cells (next major, missing tag, unknown `method`, bool for a count) and round trip | defect class 4 | |
| RP-7 | `new_version` with a target whose KCV equals current gives `rotation_target_unchanged`; an unknown dataset gives `rotation_dataset_unknown` | silent no-op rotation | |

### E4, remap (`tests/unit/domains/test_remap.py`)

| Cell | Asserts | Failure it catches | Mut |
|---|---|---|---|
| RM-1 | fpe column: the remapped column is byte-identical to `run_pipeline` on the source under `target`; other columns are byte-identical to the input | weak test, F12 | swap current and target |
| RM-2 | `vault: true` hash column: same oracle; the returned new vault, once written, opens under `target` and maps the new values; the old vault file is unchanged | vault path | |
| RM-3 | `current` with the wrong secret and the right label gives `remap_key_mismatch` before any table is read (spy on `unmask_pipeline`) | F11 | skip the KCV check |
| RM-4 | a manifest holding one `unavailable` column is refused with no tables and no `unmask_pipeline` call (spy) | F12 | skip the `unavailable`-row refusal |
| RM-5 | a vault missing one row of a selected column gives `remap_source_unavailable`, no tables, and a message holding a count only; the unmask report shows `hits = n - 1`, `misses = 1` | F12, F19 | accept a partial miss (check `status` only) |
| RM-6 | parent and child FK in one namespace remapped together still join; the child alone gives `remap_domain_split` | F13 | drop the domain-split check |
| RM-7 | canary source values absent from `caplog` and every raised message across RM-3 to RM-8; `__cause__` and `__context__` are `None` for every error `apply_remap` itself raises; an unmask error passed through keeps its existing value-free cause (unmask.py:296) | F5, F16 | |
| RM-8 | config edited after the preview (one `provider_config` key) gives `remap_manifest_stale`; an edit that only changes `pipeline_config_hash` (a non-keyed column) gives it too | F14, TOCTOU | compare the manifest ids with themselves |
| RM-9 | an fpe column declared `integer` and a `vault: true` hash column declared `date` are `remap_source_type_unsupported` in the manifest, and `apply_remap` refuses them before any read even when the manifest row is edited to `planned` | F17 | skip the declared-type check in `apply_remap` |
| RM-9a | a `vault: true` hash column with no `logical_type` over an integer source is `remap_source_type_unsupported` even though its masked input dtype is string; `apply_remap` still refuses after the manifest row is edited to `planned` | F17, the undeclared-type bypass | treat `logical_type is None` as string, or infer support only from the masked dtype |
| RM-10 | a table with `transforms` (filter, sort, dedupe) remaps with input row count and order kept and every non-selected column byte-equal; `RemapProjection.config` holds no `transforms`, `generate_columns`, `row_count`, casting, scans or delivery key; a `run_pipeline` stub that drops one row gives `remap_row_alignment_failed` and no tables | F18 | keep `transforms` in the projected config; skip the alignment check |
| RM-11 | a selected nested fpe column (unmask reports it `irreversible` at `unmask.py:386-394`) gives `remap_source_unavailable`, no tables | F19 | check `vault_miss` only |
| RM-12 | a `target` whose KCV or `key_version` differs from the manifest's `to` pair gives `remap_target_mismatch` before any read | F20 | skip the target check |
| RM-13 | guard: for every strategy in the strategy registry (plain, `vault: true`, nested), the manifest method from `reversal_method` matches the branch `unmask_pipeline` takes (reported status) | F19 | manifest-owned `strategy == "fpe"` test |
| RM-14 | two unrelated tables share one namespace and transform; selecting one gives `remap_domain_split`; selecting both succeeds and `RemapResult.domains` lists every keyed output column with its new id for selected columns and its old id for the rest | F13, evidence | drop the domain-split check; omit unselected columns from `domains` |
| RM-15 | two `vault: true` columns in one old vault; selecting one gives `remap_vault_split` | F13 | drop the vault-split check |
| RM-16 | two reversible string columns use different domains; selecting one leaves the other byte-identical and on its old domain, and the unmask report has no recovery row for the unselected column | F22 | pass the full config instead of `RemapProjection.config` to `unmask_pipeline` |

### E5, evidence (`tests/unit/run_result/test_model.py`, new cells)

| Cell | Asserts | Failure it catches | Mut |
|---|---|---|---|
| EV-1 | `domains` round-trips on the write and read models; a result without it dumps byte-identical to today's | F15 | make the field required |
| EV-2 | the existing `run-result-v1*.json` corpus samples still read; a sample with `domains` reads on the derived read model | F15 | |
| EV-3 | every `run_pipeline` route returns the same domain evidence for one compiled plan; tokenize evidence uses the executing writer's scope; a programmatic provider whose backing secret changes after admission cannot change the stamped id; the source provider is resolved once | F23 | return one route before the final stamp; re-admit after execution; read scope from a different writer |

### C1, CLI (`decoy` repo, outlined)

| Cell | Asserts |
|---|---|
| CV-1 | `decoy run --vault` writes `decoy-vault/v3`; `decoy unmask --vault` recovers it; QA VAULT-08 (truncate, bad magic) and VAULT-10 rewritten for v3 and passing |
| CV-2 | `decoy report vault` and `decoy explain vault` show format, key version, entry count and a short vault id from `read_vault_header`, never values or the KCV |
| CV-3 | `vault_tampered` maps to the runtime exit code with a value-free message and `--json` envelope |
| CV-4 | a keyed `decoy run` copies engine `ExecutionResult.domains` into its run result; a tokenize run matches the engine evidence from the executing writer's scope; the CLI performs no second secret-provider read; an unkeyed run omits `domains` |
| CV-5 | a v2 vault passed to `unmask` exits with the re-mask remedy |
| CV-6 | `decoy run --vault <path>` where `<path>` exists refuses with `vault_exists` and leaves the file byte-identical (the row FRAME "CLI refuses to overwrite an existing vault", already enforced by `_publish`, `src/decoy_engine/vault.py:332,394`; this cell pins it for v3) |

## 9. Goldens, pins and sentries that move

- Determinism goldens and masked-output snapshots: no change (no keyed derivation changes). A
  golden diff in any slice is a stop.
- Compat corpus: add `decoy-vault-v3__synthetic.vault` (E1), retain
  `decoy-vault-v2__synthetic.vault` as the negative fixture for VH-7, and update `manifest.json`
  and `regenerate.py`. A moved or added fixture is a full-suite trigger.
- Reason registry is append-only. E1 adds `vault_tampered`. E2 adds
  `domain_version_digest_mismatch` and `domain_namespace_shared`. E3 adds the codes its preview
  can emit: `rotation_key_not_preserved`, `rotation_target_unchanged`,
  `rotation_dataset_unknown`, `remap_source_unavailable`, `remap_column_conditional`,
  `remap_composite_unsupported`, `remap_domain_split`, `remap_vault_split` and
  `remap_source_type_unsupported`, plus `remap_manifest_unsupported` while the manifest stays in
  this row. E4 adds `remap_manifest_stale`, `remap_key_mismatch`,
  `remap_row_alignment_failed`, `remap_target_mismatch` and `remap_vault_required`.
  `remap_join_split` is not added because `remap_domain_split` covers it. If Q7 moves the
  manifest and apply work, its codes move with that work, but the split and unavailable-row codes
  stay in E3 because preview emits them. The registry version bumps by its own rule.
- `tests/unit/test_public_api.py`: new exports (`DomainVersion`, `domain_versions_for_plan`,
  `compare_domain_versions`, `preview_rotation`, `RemapManifest`, `apply_remap`,
  `read_vault_header`); `PreparedSecret` is already public.
- `.importlinter` and the `tests/sentry/layout/test_import_layers.py` snapshot: the new `domains`
  package in tier 1. No ignore line is added.
- E0 registries keyed by the `vault.py` path or module (a repeated grep of
  `vault\.py|decoy_engine\.vault` at `dcc4bcb3`, excluding
  `secret_providers/vault.py` rows). Each path-keyed inventory is re-keyed to the defining file;
  its reviewed site count does not grow:
  - `scripts/check_compat_preflight.py:31`: the frozen-path prefix `src/decoy_engine/vault.py`
    becomes `src/decoy_engine/vault/`; E2 adds `src/decoy_engine/domains/` and E1 adds
    `src/decoy_engine/secret_providers/_types.py` (KCV label) to the same list;
    `tests/unit/test_compat_preflight.py:29-30` follows.
  - `src/decoy_engine/_MAP.md:43` names the new `vault/` package. The prose references in
    `declared_casting/_quarantine_local.py:12`, `execution/_strategies/_tokenize.py:45` and
    `tests/unit/test_vault.py:482` name the relevant new defining module instead of `vault.py`.
  - `.semgrep/f13-secret-providers.yml:71`: replace `/src/decoy_engine/vault.py` with
    `/src/decoy_engine/vault/`; E2 adds `/src/decoy_engine/domains/` so direct provider
    resolution stays forbidden in the new package.
  - `src/decoy_engine/reason_adapter.py:76` `_CODED` changes unconditionally to
    `("decoy_engine.vault._format", "VaultError", "runtime")`, the defining module required by
    `tests/unit/reasons/test_classify_imports_nothing.py:101-103`.
  - `src/decoy_engine/fileaccess/__init__.py:111-112` `ENTRY_POINTS` changes to defining modules:
    `decoy_engine.vault._load.load_vault` and
    `decoy_engine.vault._writer.vault_writer_for_config`. E1 adds
    `decoy_engine.vault._load.read_vault_header`; E4 adds
    `decoy_engine.domains._remap.apply_remap`.
  - `tests/sentry/file_access_registry.toml:1446,1456`: the two `vault.py` entries move.
  - `tests/sentry/test_reason_registry.py:112`: `("vault.py", "VaultError.__init__")` moves to
    `vault/_format.py`.
  - `tests/sentry/defects/test_canonical_json_choke_point.py:32`: `("vault.py",
    "VaultWriter.write")` moves to `vault/_writer.py`.
  - `tests/sentry/baselines/gcs-call-kwargs.json:437-449`: five `decoy_engine/vault.py::` keys.
  - `tests/sentry/baselines/f29-producer-inventory.json` (9 rows) and
    `tests/fixtures/f29/producer-inventory.json` (12 rows): `file` and `line` regenerate by the
    inventory's own script; the code sets are unchanged.
  - `tests/sentry/secret_material_census.json:2255-2318` and
    `tests/sentry/baselines/secret-material-census.json:752-773` (8 rows each): keys move.
  - `tests/sentry/baselines/exception-context.json`: checked, holds no `decoy_engine/vault.py`
    rows (its vault rows are `secret_providers/vault.py`); unchanged.
  - `tests/sentry/test_exception_hierarchy.py:25`: keeps `decoy_engine.vault.VaultError`
    (re-exported).
  - `tests/fixtures/f29/reason-baseline.json:789-794`: the six existing VaultError identities
    keep the same namespace, code and owner, while each `sources` entry re-keys from
    `vault.py#kw:VaultError` to `vault/_format.py#kw:VaultError`. Then update only the
    `FROZEN_SHA256` constant in `tests/sentry/test_reason_baseline_frozen.py` to the SHA-256 of
    that exact six-row source move. Do not edit the separate `f29-reason-baseline` shrink-only
    identity ratchet: `_baseline_sources.py:132-135` keys it by namespace and code, not source.
  - The only remaining grep hits are the deliberately re-exported public name in
    `test_exception_hierarchy.py` and `secret_providers/vault.py` paths in the environment,
    file-access and GCS baselines; they do not refer to the split engine module.
  The E0 builder re-runs the grep on its head and adds any row this list missed; a registry found
  late is a stop-and-report, not a silent edit.
- Secret-material census, every slice: E1 (`PreparedSecret.key_check_value`, the shared
  `_open_vault`, and vault format key handling), E2 (`plan/domains/_build.py` takes a prepared secret,
  never key bytes), E3 and E4 (prepared `target` and `current`), and E5
  (`PipelineRunContext.admitted_secret` references the existing admitted object without copying
  bytes or taking ownership) each run
  `tests/sentry/test_secret_material_census.py` on the slice head. E0 re-keys existing vault sites
  by defining file. E1 is expected to shrink or preserve the per-site count because the KCV uses
  an existing `PreparedSecret` frame and both readers share `_open_vault`. If the scanner requires
  any genuinely new entry, the builder stops and adds an OWNER question naming the exact
  `file::function::name` and proposed verdict. It never silently grows the baseline.
- No ceiling, size cap or allowlist is raised. Path and digest re-keys above are reviewed moves,
  not new permitted sites.

## 10. Placement (checked against `CODEMAP.md:232-276`)

| File | Package | Map line | Beside | Why it fits the caps |
|---|---|---|---|---|
| `src/decoy_engine/vault/__init__.py` (new, about 40 lines, public re-exports) | `vault/` (was `vault.py`) | new row "Vault file format and writer" (a map change, stated here) | `unmask.py` | turning the module into a package removes one root module (25 to 24); sub-packages do not count |
| `src/decoy_engine/vault/_format.py` (about 260 after E1) | `vault/` | same | `_writer.py` | magic, header model, segment AEAD, key derivation: the format choke point |
| `src/decoy_engine/vault/_writer.py` (about 300) | `vault/` | same | `_format.py` | `VaultWriter`, `vault_writer_for_config`, entry collection, `_publish` |
| `src/decoy_engine/vault/_load.py` (about 190) | `vault/` | same | `_writer.py` | `load_vault`, `read_vault_header` |
| `src/decoy_engine/secret_providers/_types.py` (changed, 475 to about 490) | `secret_providers/` | "Secret providers, file access" row | `_preflight.py` | `PreparedSecret.key_check_value`; no new module or secret-binding frame |
| `src/decoy_engine/secret_providers/_requirements.py` (changed, 293 to about 320) and its `__init__.py` | `secret_providers/` | "Secret providers, file access" row | `_preflight.py` | `keyed_columns_for_plan`, export `column_is_keyed`; one registry |
| `src/decoy_engine/domains/__init__.py` (new, about 45) | `domains/` (new top-level package) | new row "Identity-domain rotation and remap orchestration" (a map change, stated here) | `unmask.py`, `vault/` | a sub-package, not a root module; it re-exports the public plan-domain API and owns only orchestration |
| `src/decoy_engine/plan/domains/__init__.py` (new, about 30) | `plan/domains/` (new named sub-package) | new row "Identity-domain plan traits and evidence" (a map change, stated here) | `plan/checks/` | `plan/` is frozen above its direct-module cap, so new files live in a named sub-package |
| `src/decoy_engine/plan/domains/_traits.py` (about 150) | `plan/domains/` | same | `_build.py` | per-strategy traits registry; the contract model lives in `contracts/domain_version.py` |
| `src/decoy_engine/contracts/domain_version.py` (about 220) | `contracts/` | CODEMAP "Versioned contracts" row (`CODEMAP.md:262`) | `declared_casting.py` | `decoy-domain-version/v1` write and read models and the id; a versioned document CLI and platform consume belongs in `contracts/` (tier 4, no execution imports), and the id needs only `_canonical`; `plan/domains/` keeps the logic that builds it |
| `src/decoy_engine/plan/domains/_build.py` (about 180) | `plan/domains/` | same | `_traits.py` | `domain_versions_for_plan`, `compare_domain_versions`; execution may import it through the sub-package public API without importing orchestration |
| `src/decoy_engine/domains/_rotation.py` (about 260) | `domains/` | same | `_remap.py` | `preview_rotation`, three mode handlers |
| `src/decoy_engine/contracts/remap_manifest.py` (about 180) | `contracts/` | CODEMAP "Versioned contracts" row | `domain_version.py` | `decoy-remap-manifest/v1` write and read models (moves with the manifest to the Q5 row if Q7 is answered as recommended) |
| `src/decoy_engine/domains/_remap.py` (about 280) | `domains/` | same | `_rotation.py` | `apply_remap` over `unmask_pipeline` and `run_pipeline`; imports `contracts/remap_manifest.py` |
| `src/decoy_engine/run_result/_model.py` (changed, 409 to about 445) and `_build.py` | `run_result/` | existing | `_build.py` | the optional `domains` field and its own `DomainEvidence` type, defined here (tier 4) and not imported from top-level `domains/` or the independent contract sibling; `_pipeline_context` converts the pure plan-domain result into it |
| `src/decoy_engine/unmask.py` (changed, about +40) | root | existing unmask row | `vault/` | `reversal_method` export, `hits`/`misses` on `UnmaskColumnReport`; no new root module |
| `src/decoy_engine/fileaccess/__init__.py` (changed, defining-module rows) | `fileaccess/` | existing | - | `_load.load_vault`, `_writer.vault_writer_for_config`, `_load.read_vault_header` and `_remap.apply_remap` |
| `src/decoy_engine/reasons/runtime/` part files | `reasons/` | "Reason codes" row | existing parts | appended codes; a new part file only if a part passes 600 lines |
| `src/decoy_engine/execution/_adapter.py`, `_pipeline_context.py`, `_pipeline.py` (changed) | `execution/` | existing pipeline spine row | each other | additive `ExecutionResult.domains`, exact-admission domain build and one final route stamp |
| `.importlinter` | root | "Layer contracts" row | `pyproject.toml` | top-level `domains` joins tier 1 and imports orchestration dependencies; pure `plan.domains` remains in the existing plan tier, so execution can consume it through its public API without a back import; no ignore line |
| `tests/unit/vault/test_v3_format.py`, `test_v3_tamper.py` | `tests/unit/vault/` (exists) | "Unit tests" row | `test_run_entries.py` | mirrors `src/` |
| `tests/unit/plan/domains/test_*.py`, `tests/unit/domains/test_rotation.py`, `test_remap.py`, `tests/unit/contracts/test_domain_version.py`, `test_remap_manifest.py` | mirrored unit-test packages | "Unit tests" row | - | mirrors the split between pure plan building, orchestration and wire contracts |
| `tests/sentry/test_domain_traits_complete.py`, `tests/sentry/test_domain_seed_fields_classified.py`, `tests/sentry/defects/test_key_check_choke_point.py` | `tests/sentry/`, `tests/sentry/defects/` | "Sentry test" row | `test_vault_writer_routes.py` | registered in `scripts/dev/sentry_registry.toml` |
| `tests/fixtures/domains/domain-version-v1-vectors.json` | `tests/fixtures/` | existing fixture tree | `tests/fixtures/hkdf/` | permanent golden vectors |
| `tests/integration/compat_corpus/decoy-vault-v3__synthetic.vault` | compat corpus | existing | the v2 artifact (now a negative fixture) | corpus scope already includes the vault |
| `docs/security/token-vault.md`, `docs/security/key-derivation.md`, `docs/compatibility-contract.md`, new `docs/identity-domains.md`, `docs/qa/05-keys-determinism-namespaces.md`, `docs/qa/16-vault-and-unmask.md`, `CODEMAP.md`, `src/decoy_engine/_MAP.md`, `changelog.d/<slice>.md` | docs | "Feature and contract docs", "QA checklists", "Changelog fragments" rows | - | - |

`execution/` gets no file. The root module count goes from 25 to 24 (E0) and stays there.

## 11. Reuse inventory

| Need | Reused | Not rebuilt |
|---|---|---|
| Key derivation and labels | `determinism.derive` (HKDF-SHA256, `SEED_PROTOCOL_VERSION` mixed in) | no new KDF |
| AEAD | `cryptography` `AESGCM` | no hand-rolled MAC or cipher |
| Canonical bytes for ids | `_canonical.canonical_json_bytes` | no second JSON canonicalizer |
| Versioned value-free documents | `_value_free` named types and `derive_read` (the `decoy-run-result/v1` pattern) | no second validator |
| Keyed-column rule | `secret_providers._requirements.column_is_keyed` | no second strategy list |
| Recovery | `unmask_pipeline` (fpe inverse, vault lookup) | no second inverse path |
| Re-mask | `run_pipeline(..., execution_mode="full_frame")` | no column-level masking shortcut |
| Publication | `vault._publish` and the `fileaccess` output policy | no new file writer |
| Secret binding and KCV | `PreparedSecret` plus the existing `load_vault` boxed entry | no new secret-bearing wrapper or per-reader key frame |
| Pure-move check (E0) | `scripts/check_pure_move.py` | - |

## 12. Frozen contracts touched

- `decoy-vault/v2` to `decoy-vault/v3`, and `vault-key/v1` to `vault-key/v2` plus the new labels
  `key-check/v1` and `vault-nonce/v1`: a pre-GA hard cut under compatibility contract section 3.2
  (no vault exists in the wild; owner option A for B-6; Q2). From the first in-the-wild v3 vault
  the v3 reader and these labels are permanent. The contract's GA-flip checklist is updated.
- `VaultWriter` takes an admitted `PreparedSecret` instead of raw mask bytes (breaking, pre-GA,
  no shim); `load_vault` keeps its signature and return shape; `read_vault_header` is added with a
  prepared-secret input.
- `decoy-run-result/v1`: one optional field (section 3.1 allows it).
- New contracts `decoy-domain-version/v1` and `decoy-remap-manifest/v1`, recorded in the contract's
  format table with their golden vectors.
- Reason registry: append-only codes.
- Masked output and the determinism envelope: unchanged.

## 13. Slices, gates and risk

Each slice is one PR to engine `main`. Test depth per `testing.md`: T0 per edit, T1 per commit, T2 at the gate on the exact head. A full suite (T3) runs on E0 (moved module, sentry registry entries), E1 (serialization, frozen contract, compat corpus move), E2 (import-layer contract) and E5 (frozen contract); E3 and E4 run T1 plus the T2 set.

| Slice | Content | Risk | Size (src + tests) | Depends on | Gate |
|---|---|---|---|---|---|
| E0 | `vault.py` to `vault/` package, pure move checked by `scripts/check_pure_move.py`; every registry in the section 9 E0 list; map rows | R1 | about 600 moved, +60 new; no new tests | - | Codex |
| E1 | `decoy-vault/v3`, `PreparedSecret.key_check_value`, shared `_open_vault`, `read_vault_header`, `vault_tampered`, corpus artifact; docs (token-vault, key-derivation, contract); QA 16 rows VAULT-08 and VAULT-10 rewritten | R2 | +300 src, +450 tests | E0 | Dennis then Codex |
| E2 | `plan/domains/` pure package: traits, `SEED_FIELD_BINDING`, `DomainVersion`, builder with explicit `token_vault_scope`, drift, golden vectors, traits, seed-field and KCV sentries, `_walk_keyed_plan_columns` and `keyed_columns_for_plan`; top-level `domains/` public facade and layer entries; `docs/identity-domains.md` | R2 | +660 src, +480 tests | E1 (KCV) | Dennis then Codex |
| E3 | `preview_rotation` (three modes, explicit `token_vault_scope`, split and unavailable-row findings and their reason codes) and `RemapManifest` (the manifest half moves to the Q5 row if Q7 is answered as recommended) | R2 | +460 src, +400 tests | E2 | Dennis then Codex |
| E4 | `apply_remap`, `unmask.reversal_method` descriptor, `UnmaskColumnReport.hits`/`misses`, one `RemapProjection` allowlist for recovery and re-mask, row alignment check; blocked on Q7 | R2 | +380 src, +620 tests | E3, Q7 | Dennis then Codex |
| E5 | additive `ExecutionResult.domains`, exact-admission stamp at the final `run_pipeline` return, run-result `domains` field and `_build` input | R2 (frozen contract and route evidence) | +70 src, +120 tests | E2 | Dennis then Codex |
| release | engine release train cut holding E0 to E5 | - | - | E5 | engine release rule |
| C1 | CLI: repin (repin checklist), copy engine `ExecutionResult.domains` into the run result without re-admitting a secret, `report vault` and `explain vault` from `read_vault_header`, exit mapping for `vault_tampered`, v2 remedy text, docs and CLI QA rows | R2 | about +150 src, +250 tests | release | Dennis then Codex |

E1 and E2 touch different files after E0, but E2 uses `PreparedSecret.key_check_value` from E1, so they run in order (one writer per worktree). E5 can run beside E3 in its own worktree.

Builder brief (each slice): read the rules listed at the top first; run the secret-material census on the slice head; write the slice's cells red first; name the class of each finding; attack your own diff and run the listed mutations; compare against a baseline from the same environment (`uv.lock`); never widen a threshold, loosen a test or skip one; stop and report if a catalogued class repeats. Commits: Conventional Commits subject, no body unless it explains why, final line `cam`.

## 14. Owner questions (recommended answer first)

- **Q1. Key check value in the domain version, the vault header and the remap manifest?**
  Recommended: yes. It makes a domain id change when the secret changes under the same label, it
  lets `preserve` be verified, and it stops an fpe remap under the wrong key from writing wrong
  values (FF1 cannot detect that). It is 64 bits of an HKDF output under its own label; any masked
  output already lets someone with one known source value test a guessed secret, so it adds no new
  oracle under the V1 threat model.
- **Q2. `decoy-vault/v3` as a hard cut with no v2 reader?** Recommended: yes, the same rule as B-6
  option A (2026-11-13), legal pre-GA under contract section 3.2; v2 files get
  `vault_format_unsupported` with the re-mask remedy.
- **Q3. Put `key_version` on the `Plan`?** Recommended: no. The plan is compiled before the secret
  is admitted, and a programmatic `key_provider` can differ from the config reference; the key
  version is recorded in the domain versions and in the run result (E5) instead. This replaces the
  FRAME note "key_version on the Plan" in the row detail; its "in evidence" half is kept.
- **Q4. Does "CLI token vault header" include the SQLite store of `decoy tokenize --vault`?**
  Recommended: no for row 79. G9 and 11.8 cite the `decoy-vault` file (`vault.py`), which this
  plan changes. The SQLite store is cleartext by design with `0600` files; an authenticated meta
  header for it is a recorded follow-up row.
- **Q5. CLI commands for rotation preview and remap?** Recommended: a new V1 row after row 79
  (`decoy domains preview`, `decoy remap`), so this row stays as written and the built capability
  still reaches customers before V1.
- **Q6. Remap limited to string-typed fpe and vaulted one-way columns, full-frame only?**
  Recommended: yes.
  One-way columns without a vault cannot be remapped (F09 contract: a remap "cannot reconstruct
  unavailable inputs from a one-way hash"); the operator re-runs the mask job from source under
  the new key. `when`-conditioned, derived-from, composite-FK and non-string-source remap are
  follow-ups. Coverage is narrow: because a selection must cover whole domains and whole vaults,
  any selected table that also holds a `date_shift`, `shuffle` or vault-less `hash` column in an
  affected domain refuses the whole remap, so in practice remap serves string fpe and vaulted
  columns in tables built around them, and most operators will re-run from source.
- **Q7. Build the E3 remap manifest and E4 `apply_remap` in row 79, or move them to the Q5 remap
  row?** E4 has no V1 consumer while the Q5 CLI commands are deferred. Recommended: move the
  `RemapManifest` half of E3 and all of E4 to the Q5 row, so they ship with the command that uses
  them and are gated against a real caller; row 79 keeps E0, E1, E2, the preview half of E3 (all
  three modes, with `remap` returning the affected set and the split findings but no manifest
  document) and E5. The plan keeps the E4 design and cells so the Q5 row starts from them. E4 does
  not start until Q7 is answered. If the owner accepts this answer, the same planning-doc change
  amends CLI `docs/ROADMAP.md` row 79 and `docs/roadmap/row-detail.md` F09 to say that remap apply
  moves to the new Q5 CLI remap row. The E3 split and unavailable-row reason codes stay with row
  79 because the retained preview emits them.

## 15. Pre-mortem

- **The derived passthrough config changes what other columns see.** A strategy that reads sibling
  columns could compute differently when siblings hold old masked values, and a derived column
  built from a remapped column would go stale. Mitigation: `when` columns and columns that other
  columns derive from are `remap_column_conditional` (RP-5); one `RemapProjection` is
  allowlist-built, makes every unselected column passthrough, and is used for both recovery and
  re-mask; it drops table transforms; step 5 checks row count and passthrough bytes at run time
  (RM-10, RM-16); RM-1 asserts the selected column equals the fresh-mask oracle.
- **Builders weaken the oracle.** RM-1 and RM-2 compare against a fresh mask from source; a gate
  diff that replaces the oracle with "values changed" is a stop.
- **The trait table goes stale when a strategy is added.** The traits sentry fails the PR that
  adds a keyed strategy without traits.
- **E0 is not a pure move.** The checker runs on the E0 diff; any behavior change moves to E1.
- **Associated data over header bytes breaks if the header is re-serialized.** The reader hashes
  the exact framed bytes, never a re-dump; VH-2 edits bytes, not the parsed dict.
- **A large remap hits the full-frame reject limit.** That route's existing error is raised before
  any work; recorded as a limit in `docs/identity-domains.md`.
- **Platform consumers of `VaultWriter`.** The platform is parked and pins an older engine; the
  repin checklist covers the `key_version` keyword when it moves.

## 16. Follow-ups (recorded, not in this row)

- An authenticated meta header for the CLI SQLite tokenize store (Q4).
- CLI rotation and remap commands (Q5).
- Remap of `when`-conditioned, derived-from and composite-FK columns, and on bounded routes.
- Remap of non-string sources by recording and restoring the source type.
- Domain registry, ownership, grants and revocation (platform, V1 paid).

## 17. Review record and deferred items

### Dennis r1 (GO-WITH-FIXES, 0 blocker, 4 V1, 10 DESIGN, 10 V2-LOG), resolved in revision 2

- V1-1 source type: refuse non-string sources, `remap_source_type_unsupported`, manifest and
  pre-read dtype check (4.5); RM-9 with int and date sources, mutation.
- V1-2 derived config: allowlist-built, transforms and the other named keys dropped; row count and
  passthrough byte check, `remap_row_alignment_failed` (4.5 steps 4 and 5); RM-10, mutations.
- V1-3 unmask status: per-column status must equal the method's expected status; additive
  `hits`/`misses` on `UnmaskColumnReport` (4.5 step 3); RM-5 extended, RM-11 nested fpe.
- V1-4 mixed keys: `remap_domain_split` (replaces `remap_join_split`) and `remap_vault_split`;
  `RemapResult.domains` in the E5 shape, documented as the key record; RM-6, RM-14, RM-15.
- D1 target check: `remap_target_mismatch` against the manifest's `to` pair; RM-12, mutation.
- D2 E0 registries: full grep-based list in section 9, pure-move checker path corrected to
  `scripts/check_pure_move.py`.
- D3 file-access entry points: `read_vault_header` (4.2) and `apply_remap` (4.5) take kw-only
  `file_access`, carry `@fileaccess.entry_point` and get `ENTRY_POINTS` rows.
- D4 census: `key_check_value` takes an `OpaqueBox` (4.1); census run per slice (section 9, builder
  brief).
- D5 one walker: `_walk_keyed_plan_columns` shared by both plan functions; DV-3 compares with
  `keyed_columns_for_config` including `allow_collisions` (4.3).
- D6 one reversal classifier: `unmask.reversal_method`, used by unmask, the manifest and the status
  check; RM-13 guard, choke point 5.
- D7 bound fields: `SEED_FIELD_BINDING` table over every `ColumnSeed` field plus tokenize
  `derivation_scope`; DV-4 extended, DV-9 sentry, choke point 7.
- D8 E4 consumer: owner question Q7 (recommend moving the manifest and E4 to the Q5 row); E4
  blocked until answered.
- D9 mutations: added for RM-4, RM-5, VH-7, RM-9 to RM-12, RM-14, RM-15.
- D10 `config_hash`: produced only by `pipeline_config_hash` on the validated config (4.5).
- Cell count: 44 in revision 1 (the earlier 46 was a miscount); revision 2 had 53 after CV-6
  (section 8).

### Dennis r2 (GO-WITH-FIXES), resolved in revision 3

- **V1-1:** remap eligibility now requires declared `logical_type == "string"` for both
  `fpe_inverse` and `vault_lookup`; absent is unsupported even when the masked dtype is string.
  RM-9a covers an undeclared integer source and mutates both unsafe fallbacks (4.5, section 8).
- **DESIGN-1:** every file-access row now names the defining module:
  `vault._load.load_vault`, `vault._writer.vault_writer_for_config`,
  `vault._load.read_vault_header` and `domains._remap.apply_remap`. `_CODED` unconditionally names
  `vault._format.VaultError` (4.2, 4.5 and section 9).
- **DESIGN-2:** E0 includes `.semgrep/f13-secret-providers.yml` and its new domains path. The six
  F29 reason sources re-key to `vault/_format.py`, with the frozen digest updated while the
  namespace-and-code ratchet keys stay fixed. The repeated `vault.py` grep found no other live
  path-keyed registry omitted from section 9.
- **DESIGN-3:** `domain_versions_for_plan` and `preview_rotation` take explicit
  `token_vault_scope`. A tokenize plan without a valid scope refuses with
  `tokenize_vault_scope_required`; DV-4 and EV-3 carry the executing writer's scope through the
  domain id and evidence (4.3, 4.4, 4.6).
- **DESIGN-4:** KCV derivation is a `PreparedSecret` method. `load_vault` and
  `read_vault_header` share one `_open_vault`; domain evidence uses the already admitted secret.
  The census is expected to shrink or re-key, never silently grow. Any unavoidable new entry is
  an OWNER question with its exact key and verdict (4.1, 4.2, section 9). This supersedes the r1
  boxed-helper proposal.
- **DESIGN-5:** Q7 now requires the roadmap row and row detail to move remap apply to the Q5 row
  if accepted. Split and unavailable-row codes land in E3 because preview emits them (sections 9
  and 14).
- **V2-LOG:** RM-11 now expects nested fpe to report `irreversible`; the section 10 `Beside`
  entries point at the modules that remain after contract models moved; `ColumnSeed.vault` is
  classified; the pandas dtype caveat forbids weakening passthrough byte equality.

### Revision 3 whole-plan self-review

- **V1, fixed:** recovery previously passed the full config to `unmask_pipeline`, which could
  decrypt an unselected reversible column and fail or corrupt the passthrough contract. One
  `RemapProjection` now drives recovery and re-mask; RM-16 mutates the old call (4.5).
- **V1, fixed:** CLI-side evidence could re-admit a rotated secret after execution. The exact
  admitted secret and executing token scope now produce evidence at the final engine return;
  EV-3 and CV-4 guard every route and the single provider read (4.6).
- **DESIGN, fixed:** pure plan-domain building lives in the named `plan/domains/` sub-package, so
  execution reaches it through a public lower-layer API while top-level `domains/` keeps only
  rotation and remap orchestration. The placement table and import-layer change describe the
  split (section 10).
- **V1:** none remaining.
- **DESIGN:** none remaining that this plan creates.
- **V2-LOG:** the hand-written plan is 877 lines, inside the owner-defined 800 to 900 cleanup
  band. This does not affect the verdict.

### Deferred (V2-LOG), Dennis r1

1. Key-label and value domain overlap: `derive(mask_key, ns, label)` shares input space with the
   hash strategy's `derive(mask_key, ns, canonical(value))`, so a hash column in namespace `vault`
   over the value `"vault-key/v1"` outputs the v2 Fernet key, and over `"ff1-key/v1"` in an fpe
   namespace outputs the FF1 key. The v3 `vault_id` closes it for the vault key. Follow-up:
   reserved internal namespaces. Hostile-input class, V2 threat model.
2. `K_vault` is both the AES key and the input that derives the nonce prefix. Follow-up: derive
   the prefix from `mask_key` plus `vault_id` under its own label, or store a random prefix in the
   header as Tink does.
3. The domain id in run results lets someone test a guessed weak secret offline, the same as any
   masked output. V2 threat model (with the KCV item in FRAME non-goals).
4. `unmask_pipeline` re-raises `VaultError` `from exc` (`src/decoy_engine/unmask.py:296`), so
   errors `apply_remap` passes through carry a value-free `__cause__`. RM-7 and F16 now scope the
   `None` assertion to errors the new code raises; cleaning the unmask re-raise is a follow-up.
5. Folded in: the domain-version and remap-manifest document models live in `contracts/` per the
   CODEMAP "Versioned contracts" row (section 10).
6. Folded in: the E5 `DomainEvidence` type is defined in `run_result` (tier 4) and `domains/`
   converts into it (section 10).
7. Folded in: the row FRAME "CLI refuses to overwrite an existing vault" is cited (`_publish`,
   `vault_exists`) and pinned by CV-6.
8. Folded in: Q6 now tells the owner how narrow remap coverage is.
9. Cell count: fixed in revision 2 (section 8).
10. Pure-move checker path: fixed in revision 2 (`scripts/check_pure_move.py`).
11. Editing only the cleartext `key_check` field is reported as `vault_key_mismatch` before header
    authentication can prove the edit. This is a diagnostic-code ambiguity, not an accepted read,
    value leak or data-integrity failure; every entry still stays behind successful AEAD checks.

Other limits this plan defers: remap of non-string sources, of `when`-conditioned, derived-from and composite-FK columns, and on bounded routes; an authenticated header for the SQLite tokenize store (Q4); reading `decoy-vault/v2` files (Q2); the platform domain registry, grants and revocation; rotation UI and approval.
