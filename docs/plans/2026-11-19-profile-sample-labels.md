Status: plan

# PROFILE-SAMPLE-LABELS: every profile number says what it was counted over (1.0 row PROFILE-SAMPLE-LABELS)

Owner: Cam. Author: Decoy planner (Opus). Date: 2026-11-19. Revision 1, not yet reviewed.

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `profiles/local-operations.md`, `bugfix.md`, `cross-cutting-concerns.md` (one choke point plus a guard test and its mutation), `api-and-compatibility.md` (consumer inventory, explicit breaking changes), `proportionality.md`; also `architecture.md` (placement, fan-out), `testing.md` (T0 to T2), `reuse-first.md`, `documentation.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`; vault `30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`; engine `CODEMAP.md` ("Where Things Go"), `docs/compatibility-contract.md`, `docs/frozen-surfaces.md`; CLI `CODEMAP.md`, `docs/roadmap/groups/scan.md` (rows PROFILE-SAMPLE-LABELS, 24zm); the row 24zm plan (`origin/plan/profile-unflagged`, revision 5); the freeze-batch plan (`origin/plan/freeze-batch`, revision 3.2).

Anchors: a path with no prefix is in decoy-engine at `origin/main` `9e6547298`; a path with the prefix `C:` is in the CLI repository (decoy) at `origin/main` `ccc5540a`. The plan lives in the engine repo on branch `plan/profile-sample-labels` because the labels, the registry and the sentry are engine-owned.

Risk: R2 overall. E1 and C1 change the bytes of outputs that freeze at 1.0 (`scan-set/v1`, `profile_document`, `decoy scan --json`); `risk-and-exceptions.md` makes compatibility an R2 trigger. E2 is R1 unless a golden moves (then R2). Approver: Cam for the plan and the owner questions; Dennis then Codex for the plan gate. 1.0 bar: this row is a function break (a key claimed that is not a key, null counts shown as file-wide that are not) in an output that freezes; it is not a leak.

## 1. Frame

### 1.1 The row

"Sample numbers shown as whole-file numbers (found 2026-11-18): the default scan profiles the first 10,000 rows but prints the sample null and distinct counts beside the exact whole-file row count, and `key_candidates` can call a column a key from the sample alone. The chunked mask run profiles only its first chunk yet marks columns `sampled=False`, so the plan's `profile_hash` depends on chunk size. Fix before the freeze, because each changes output: label every sampled field (`basis`, `scanned_rows`), claim a key only from exact counts, and make the first-chunk profile say it is a sample (or keep its distribution fields out of the plan hash). Exact whole-file numbers stay a 1.x opt-in. V1 fix."

### 1.2 Evidence (probe on the Dell, `VMRUN_LINUX=1 ~/bin/vm-run engine`, engine `9e6547298`)

A 25,000-row CSV. Column `id` is `i % 12000` (unique in the first 10,000 rows, 12,000 distinct over the file). Column `n` has nulls only after row 10,000. Default `scan_sources` (head, cap 10,000):

```
core.row_count 28058 exact False strategy head cap 10000
key_candidates ['id']
field id null_count 0 null_rate 0.0 distinct 10000
field n null_count 0 null_rate 0.0 distinct 3
```

The core claims `id` is a key and reports 0 nulls for a column that has about 2,140, beside a source row count of 28,058. Nothing in the record says the field numbers cover 10,000 rows.

`first_chunk_profile` on two prefixes of one 4,000-row table (`id = i % 1500`):

```
chunk 1000 hash 21827d9f7369 [('id', 1000, 1000, False, True), ('v', 1000, 900, False, False)]
chunk 2000 hash 20e0d4b50d2c [('id', 2000, 1500, False, False), ('v', 2000, 900, False, False)]
```

Every column says `sampled=False`. With a 1,000-row chunk, `id` is flagged a candidate key, which the H6 invariant (`profile/_types.py:105`) exists to forbid for sampled data. `profile_hash` moves with the chunk size.

### 1.3 Root cause

There is no single rule that says what a profile number was counted over, and no field-level record of it.

1. `scan_set._read_and_profile` (`profiling/scan_set.py:274`) knows whether it read the whole source, but only `sample_strategy` and `sample_row_cap` reach the core (`profiling/_scan_core.py:86`). The number of rows read is not in the core, and a cap of 10,000 does not say whether the file was shorter.
2. `_table_scan` (`profiling/scan_set.py:356`) claims a key when `null_count == 0 and distinct_count == scanned`, with no check that `scanned` is the whole source.
3. `first_chunk_profile` (`execution/_chunked_profile.py:53`) walks the chunk with `sample_rows=None` (`execution/_chunked_profile.py:36`), so the walk believes the chunk is the table; `arrow_column_profile` hard-codes `sampled=False` and computes the key flag from the chunk (`execution/_chunked_profile.py:198`).
4. Each surface added its own partial label (`sample_strategy`, `row_count_exact`, `sampled`, relationship `exact` and `bounded`), so a new field lands with whatever label its author remembered. That is a class, so the fix is a registry plus a sentry, not three patches.

## 2. Guarantee and non-goals

- G1. Every number in a profile output that was counted over the scanned rows sits in a record that states its basis (`whole` or `sample`) and how many rows were scanned. `whole` is written only when the read proved it reached the end of the source.
- G2. A key is claimed only on a `whole` basis. On a `sample` basis `key_candidates` is empty and every surface that shows it says the check was not run.
- G3. A first-chunk profile says it is a sample: every column `sampled=True`, no column a candidate key. No masked byte changes.
- G4. Every field reachable from the profile output types has exactly one basis class in one registry. A new field without one fails the build (owner's rule: a class finding gets a construction sentry).
- G5. Old records stay readable. A `scan-set/v1` core written before this change reads as `basis: sample` (fail closed), never as `whole`.

Non-goals:

- Exact whole-file aggregates over a sampled scan (a streaming pass for exact null and distinct counts). That is the 1.x opt-in the row names. `decoy scan --rows 0` (a full read) already gives exact numbers today.
- The planner's capacity arithmetic that mixes a source `row_count` with a sample `null_count` (`plan/_checks.py:161`). It never reaches output; section 16 logs it for its own row.
- A per-field `basis` key on every field record (owner Q2).
- Changing the hash rules of `profile_hash` (owner Q1).

## 3. Established solutions

Searches run 2026-11-19 (web): DuckDB `SUMMARIZE` columns; Deequ `ApproxCountDistinct`, column profiler and constraint suggestion; Great Expectations `result_format` keys; ydata-profiling large-dataset guidance. In-codebase: the value registry and its sentry (`profiling/_value_redaction.py:108`, `tests/sentry/profiling/test_profile_value_registry.py`), the existing labels (`row_count_exact`, `sampled`, relationship `exact`/`bounded`).

| Tool | How it labels a sample | What we take |
|---|---|---|
| ydata-profiling | Statistics cover the DataFrame it is given. Its "Profiling large datasets" page recommends `minimal=True` or sampling first (`df.sample(10000)`), and suggests the user add a disclaimer to the report stating the sample size. The report itself does not record the sample. | The negative case: a profile that does not carry its basis reads as whole-data, and the label is left to the user. That is our current behaviour; we put the label in the output. |
| Great Expectations | A result carries `element_count` and `unexpected_count`; a capped list is named `partial_unexpected_list` (20 items by default), so the name says the list is partial. | Say "partial" where a number is partial. We keep the counts' names and put the basis beside them. |
| Deequ | The analyzer name carries the basis: `ApproxCountDistinct` (HyperLogLog++) against `CountDistinct`. Constraint suggestion profiles the data and proposes constraints, which a `VerificationSuite` then checks. | A key found on partial data is a suggestion until an exact check confirms it. We do not ship it as a claim; on a sample the key check is "not run". |
| DuckDB `SUMMARIZE` | One query over the whole relation. Approximate columns say so (`approx_unique`); the docs state the quantiles are approximate. | The basis is visible where the number is shown: the CLI column header says "(sample)". |

Synthesis: two patterns exist, basis in the name (Deequ, DuckDB) and basis in adjacent metadata or a "partial" marker (Great Expectations). Renaming `null_count` and `distinct_count` would break every reader of `scan-set/v1` and the profile document for no new information, so this plan uses adjacent metadata on the record that holds the numbers plus a display label, and takes Deequ's split between suggesting and verifying a key for G2. The only custom code is the basis rule and the registry, because the facts it needs (cap, rows read, strategy) exist only inside our reader.

## 4. Design

### 4.1 One basis rule and one registry: `profiling/_basis.py` (new, about 110 lines)

- `Basis = Literal["whole", "sample"]`.
- `read_basis(strategy: str, cap: int | None, scanned: int) -> Basis`: `whole` when `strategy == "full"` or `cap is None` or `scanned < cap`; else `sample`. A read that returned fewer rows than it asked for reached the end of the source. A read that returned exactly `cap` rows is `sample` (owner Q5).
- `claim_keys(profile) -> tuple[str, ...]`: the one key rule. Empty unless `profile.basis == "whole"`; otherwise the existing test (no nulls, distinct equals scanned rows).
- `BasisClass` enum:
  - `SCANNED`: counted over the scanned rows; its record's carrier applies (`null_count`, `distinct_count`, `null_rate`, `pii_score`, `top_values`, `reid_risk_score`, model hits).
  - `SOURCE`: a fact of the whole source with its own label (`TableCore.row_count` with `row_count_exact`; relationship facts with `exact` and `bounded`).
  - `CHECKED`: a claim that needs exact counts; empty or `False` unless the basis is `whole` (`key_candidates`, planner `is_candidate_key_sampled`).
  - `LABEL`: identity, configuration or metadata (`name`, `engine_version`, `sample_strategy`, `basis`, `scanned_rows`).
- `FIELD_BASIS: Mapping[tuple[str, str], BasisClass]`, keyed `(type name, field name)` like `VALUE_FIELDS`, over three roots:
  1. the profile document: every type `profile_types()` reaches from `profiling.types.ColumnProfile` (`profiling/_value_redaction.py:419`);
  2. the scan core: `ScanSetCore` and every pydantic model it nests (`profiling/_scan_core.py`);
  3. the planner profile: `Profile`, `TableProfile`, `ColumnProfile`, `Relationship` in `profile/_types.py`.
- `CARRIERS`: per root, the field that carries the basis (`profiling.ColumnProfile.basis`, `TableCore.basis`, planner `ColumnProfile.sampled`).

`_basis.py` names the planner types by string, so `profiling` gains no new import edge into `profile`. The sentry resolves the names.

### 4.2 E1: the scan path and the profile document

1. `profiling.types.ColumnProfile` gains `basis: Basis = "sample"` (fail-closed default for older constructors and loaded documents). `profile_columns` (`profiling/profiler.py:298`) sets it with `read_basis(sample_strategy, sample_row_cap, len(df))` at the one construction site (`profiling/profiler.py:454`). No new parameter on the frozen `profile_columns` signature.
2. `_value_redaction.py`: `("ColumnProfile", "basis")` joins `VALUE_FREE_FIELDS` (`profiling/_value_redaction.py:108`). `_checkable` and `_conforms` learn `Literal`: a value conforms when its type is exactly `str` and it is one of the literal's arguments. Without this the redactor drops the key from every plain document (today `_conforms` checks `isinstance(value, ())` for a `Literal` hint); with it a forged `basis` holding other text is dropped like any ill-typed value-free slot. About 5 lines; the module stays under 600.
3. `scan_set._read_and_profile` (`profiling/scan_set.py:294`): on a head read that returned fewer rows than the cap, the source total is the frame length and exact (`total, exact = len(frame), True`), not `max(estimate, len)`. A small CSV no longer reports an estimate for a file it read to the end.
4. `TableCore` (`profiling/_scan_core.py:86`) gains `basis: Basis = "sample"` and `scanned_rows: int | None = None`. The defaults keep old records readable through `ScanSetCoreRead` and read as `sample` (G5). A model validator on the write model: `scanned_rows` is set, `0 <= scanned_rows <= row_count`, and `basis == "whole"` implies `row_count_exact` and `scanned_rows == row_count`. `_table_core` fills both from `TableScan.profile`. The tag stays `scan-set/v1`: both members are additive with read defaults, which contract section 3.1 allows within a major.
5. `_table_scan` (`profiling/scan_set.py:356`) calls `claim_keys`. Nothing else computes a key.
6. `FieldCore` gains nothing (owner Q2): every `SCANNED` field in it takes its table's `basis`.

### 4.3 E2: the first-chunk profile

`first_chunk_profile` (`execution/_chunked_profile.py:53`) ends with one transform, `_as_chunk_sample(table_profile)`: every column `dataclasses.replace(c, sampled=True, is_candidate_key_sampled=False)`. It runs after the carried-column replacement, so columns built by `arrow_column_profile` are covered too. `walk_one_table` and `arrow_column_profile` stay unchanged, so their field-by-field parity test (test 20) still holds. `empty_input_profile` is unchanged: zero chunks means the source is empty, which is a whole read.

`TableProfile.row_count_exact` is not flipped for the chunk, because `execution/capacity.py:481` reads it. The docstring of `first_chunk_profile` says the table `row_count` is the chunk length.

Hash: the rules of `_data_shape_bytes` (`profile/_serialize.py:51`) do not change (owner Q1). A first-chunk hash moves once (`sampled` and the key flag are hashed) and still depends on chunk size. No route writes it: `Plan.profile_hash` reaches disk only through `plan_to_yaml` and the full-frame unified slice evidence (`execution/_unified_slice.py:338`), and neither runs on a first-chunk profile. AT-14 pins that.

### 4.4 C1: the CLI

1. `decoy scan` card (`C:src/decoy/cli/scanning/_multi.py:360`): "Rows scanned 10,000 of about 28,058 (sample, head)" on a sample; "Rows scanned 4,812 (whole file)" on a whole read. "Key candidates: not checked (sampled scan; --rows 0 reads every row)" on a sample (`C:src/decoy/cli/scanning/_multi.py:368`). The multi-table table gets the same cells (`C:src/decoy/cli/scanning/_multi.py:397`).
2. `--show-fields` table: "Null rate (sample)" and "Distinct (sample)" headers on a sample.
3. `--json` (`C:src/decoy/cli/scanning/_multi.py:252`): each table object gains `basis`, `scanned_rows` and `row_count_exact`, and `row_count` becomes the source row count, as in the core (owner Q3). The flat single-file payload the same.
4. `decoy scan show` (`C:src/decoy/cli/scan.py:794`): "Nulls 0 (in 10,000 scanned rows)" and "Distinct 10,000 (in 10,000 scanned rows)" on a sample; `--json` gains top-level `basis` and `scanned_rows` from the table. A saved scan with no `basis` shows "basis not recorded (read as a sample)". One label helper in `C:src/decoy/cli/scanning/_multi.py` builds every label; `scan.py` is a legacy module over the 800-line cap and may not grow.
5. Docs: the scan reference and `decoy scan --help` epilog say what `sample` means and that `--rows 0` gives whole-file numbers; roadmap row, shipped log, CHANGELOG `Breaking:` entry.

### 4.5 Design notes

- Principle: one place per fact (`architecture.md`). The basis rule, the key rule and the field classes each live once, in `_basis.py`; the CLI reads the engine's `basis` and never recomputes it. Change pain addressed: three surfaces each grew their own partial label.
- Pattern followed: the existing value registry (`VALUE_FIELDS`, `VALUE_FREE_FIELDS`) and its both-ways sentry. `FIELD_BASIS` has the same key shape and the same walk.
- No new abstraction beyond one enum, two functions and one mapping; no flag arguments; `read_basis` takes the three facts it needs.

## 5. Behaviour

| Input | Before | After |
|---|---|---|
| CSV, 25,000 rows, default scan | `row_count` 28,058 (estimate), field counts over 10,000 rows unlabeled, `key_candidates: ["id"]` | same counts; `basis: "sample"`, `scanned_rows: 10000`; `key_candidates: []`; card says not checked |
| CSV, 4,812 rows, default scan | `row_count` an estimate, `row_count_exact: false` | `row_count` 4,812, `row_count_exact: true`, `basis: "whole"`, keys claimed |
| Any file, `--rows 0` or `strategy="full"` | numbers exact, no label | `basis: "whole"`, `scanned_rows == row_count` |
| Exactly 10,000 rows, cap 10,000 | keys claimed | `basis: "sample"`, keys not claimed (owner Q5) |
| `decoy.scan(df)` then `profile_document` | no basis key | `"basis": "whole"` or `"sample"` |
| Chunked mask run | first-chunk columns `sampled=False`, possible key flag | `sampled=True`, no key flag; masked bytes unchanged |
| Saved scan from an older engine | read as-is | reads with `basis: "sample"`, `scanned_rows: null` |

## 6. Failure modes

1. A head read that returned exactly the cap is labeled `sample` although the file may hold exactly that many rows. Accepted (owner Q5); the cost is one unclaimed key.
2. A caller hands `profile_columns` a frame that is already a sample with `sample_strategy="full"`. The profile says `whole`. This is the caller's statement; the CLI and `scan_sources` never do it. Documented in the docstring.
3. A forged profile document carries `basis: "whole"`. A label is not a cell value, and no trust decision rests on it; the redactor keeps only the two literal values (AT-8).
4. A hand-edited `scan-set/v1` core claims `basis: "whole"` with `scanned_rows < row_count`. The write model refuses it; the read model ignores validators by design (contract 3.1), so the CLI shows what is written. Readers never infer a key; they read `key_candidates`.
5. A golden or parity capture pins a first-chunk plan hash. E2 moves it; the owning tool regenerates it and the build record lists each move (stop line 4).
6. A new profile field is added without a basis class. The sentry fails (AT-11).
7. `Literal` support in `_conforms` keeps more than it should. It accepts only the literal's own strings; AT-8 feeds near-miss strings, a bool and an int.
8. The CLI pins an engine release without E1. Every scan would show "not recorded". Stop line 6 forbids merging C1 before the repin.

### 6.1 Recurring-defect class table

| Class | Name | Where it could appear here | Closing structure | Sentry or test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the new `basis` key in a plain profile document, and the CLI labels | `basis` is a closed `Literal`, kept by the one redactor only when it is one of its two strings; CLI labels are fixed text plus integers | AT-8; the existing `tests/sentry/profiling/test_profile_value_registry.py` forces the new field's classification | type the field as `str` (AT-8 red: a cell-like string survives) |
| 2 | Cleanup on an exit path | N/A: no resource, file or staging directory is opened or created by this change | - | - | - |
| 3 | State machine and concurrency | N/A: profiles are frozen values built once per read; no shared state or lock is added | - | - | - |
| 4 | Route parity and silent fallback | head, random, full, DataFrame, first-chunk and empty-input routes must agree on the basis rule | one `read_basis`, one `claim_keys`, one `_as_chunk_sample` | AT-1 to AT-6, AT-13, AT-16 | derive basis from `strategy` alone (AT-5 red) |
| 5 | Referential integrity | relationship facts keep their own `exact` and `bounded` labels; the first-chunk profile has no relationships | `RelationshipFactsCore` fields are `SOURCE` in `FIELD_BASIS`; no FK path changes | AT-11; existing relationship cases in `tests/unit/profiling/test_scan_set.py` | drop the relationship entries from the registry (AT-11 red) |
| 6 | Untrusted producer | a loaded profile document or saved core with a forged `basis` or missing members | strict `Literal` conformance in the redactor; read defaults fail closed to `sample` | AT-8, AT-9, AT-C6 | default the read model to `whole` (AT-9 red) |
| 7 | Check then use on a path | N/A: no path is checked and later opened by this change | - | - | - |
| 8 | Weak tests and overclaimed evidence | a test that only checks a key exists, or a probe on a file shorter than the cap | hostile fixture: unique in the sample, duplicated after it, nulls only after it; probe output recorded in 1.2 | AT-2, AT-12 | build the fixture with unique ids throughout (AT-2 then passes for the wrong reason; the gate checks the fixture) |
| 9 | Behavior-preserving refactor drift | `claim_keys` and `_as_chunk_sample` move logic; masked output must not move | characterization: chunked output bytes and `PINNED_HASH` unchanged | AT-14, AT-15 | drop sampled columns' counts from the hash bytes (AT-15 red) |
| 10 | Frozen contract drift | `scan-set/v1`, `profile_document` and `decoy scan --json` gain members, and `key_candidates` changes meaning | additive members with read defaults; `Breaking:` entries; schema snapshots regenerated by their tools | AT-9, AT-10, AT-C2, `tests/unit/profiling/test_scan_core_move.py` | remove the read default for `basis` (older corpus samples fail to read) |

### 6.2 Field basis class table

Every field that can come from a sample, and every other field, gets one class. `SCANNED` fields take their record's carrier.

| Surface and type | `SCANNED` | `CHECKED` | `SOURCE` | `LABEL` |
|---|---|---|---|---|
| Profile document `ColumnProfile` | `reid_risk_columns`, `reid_risk_score`, `quasi_identifier_groups`, `k_anonymity` | - | - | `source_label`, `row_count` (rows scanned, `profiling/types.py:171`), `sample_strategy`, `sample_row_cap`, `basis` (new), `engine_version`, `generated_at`, `fields` |
| `FieldStats` | every count, rate, range, length, class and pattern field (`null_count`, `null_rate`, `distinct_count`, `unique_rate`, `is_likely_unique`, `inferred_type`, `min_value` to `distribution`, `pii_score`, `detection_trail`, `domain`, `top_values`, `sentinels`, `detector_matches`) | - | - | `name`, `row_count` (scanned), `dtype_raw` |
| `TopValue`, `Distribution`, `SentinelFlag`, `DetectorMatch`, `DetectionSignal` | every field | - | - | - |
| Scan core `TableCore` | `reid_risk_score`, `quasi_identifier_groups` | `key_candidates` | `row_count`, `row_count_exact` | `name`, `descriptor`, `sample_strategy`, `sample_row_cap`, `basis` (new), `scanned_rows` (new), `fields`, `warnings` |
| `FieldCore` | `dtype`, `null_count`, `null_rate`, `distinct_count`, `pii_score`, `pii_candidate`, `detector_hits`, `leading_zero_count`, `model_hits` | - | - | `name` |
| `ModelHitCore`, `ModelRefCore` | `band`, `rate_bucket` | - | - | `source`, `detector_id`, `model`, `id`, `version` |
| `RelationshipFactsCore`, `ChildFactsCore` | - | - | every count (own `exact`, `bounded` labels) | `parent`, `parent_columns`, `table`, `columns`, `status`, `exact`, `bounded`, `warnings` |
| `ScanSetCore`, detector run cores | - | - | - | `scan_schema`, `engine_version`, `scanned_at`, `tables`, `relationships`, `detectors`, `source`, `model` |
| Planner `ColumnProfile` | `dtype`, `null_count`, `distinct_count`, `avg_length`, `max_length` (carrier `sampled`) | `is_candidate_key_sampled` | `row_count` | `name`, `sampled`, `declared_pk`, `is_fk`, `fk_target`, `pii_class` |
| Planner `TableProfile`, `Profile`, `Relationship` | - | - | `row_count`, `row_count_exact` | every other field |

`dtype` and `inferred_type` are `SCANNED` because they are inferred from the scanned rows (a column empty in the first 10,000 rows reads as `object`). The builder fills this table into `FIELD_BASIS`; the sentry, not this table, is the authority, and any field the table missed fails it.

## 7. Enumerations

### 7.1 Exit paths

- `decoy scan` success (exit 0): labels added; no new exit code and no new reason code.
- `scan_sources` refusals (`PipelineConfigError` for a bad `sample_rows`, `profiling/scan_set.py:176`; `ScanSourceError`): unchanged.
- `ColumnProfile.__post_init__` (`profile/_types.py:105`): `_as_chunk_sample` sets `sampled=True` and the key flag `False` in one `replace`, so the H6 check never fires.
- `TableCore` write validator: a new `ValidationError` path, reachable only by an engine bug (AT-10).
- Chunked mask run: exit codes and reasons unchanged (AT-14).

### 7.2 Routes

- Scan head: `profiling/scan_set.py:294` (`reader.sample_frame`).
- Scan random and full: `profiling/scan_set.py:288` (`reader.to_frame`; random samples after the read).
- `decoy.scan()` and `profile_columns` on a DataFrame: `C:src/decoy/api.py:727`, `profiling/profiler.py:298`.
- Planner `profile_source` (default 10,000 rows): `profile/_walk.py:117` already sets `sampled`; unchanged.
- Chunked oracle lane: `execution/_chunked_oracle.py:240` and `execution/_chunked_oracle.py:250` (carried columns).
- Chunked legacy `auto_chunk` lane: `execution/_pipeline_auto_chunk.py:193`.
- Chunked native dispatcher: `execution/native/_dispatch.py:211` reads the same profile and no count from it.
- Empty chunked input: `execution/_chunked_profile.py:101` (`empty_input_profile`), unchanged.
- Fit snapshot: `profiling/_snapshot_values.py:584` profiles a head only to pick value-sensitive names; the snapshot covers the whole frame and is not changed.

### 7.3 FK shapes

- Declared relationships in a scan: `RelationshipFactsCore` already carries `exact` and `bounded` (`profiling/_scan_core.py:111`); classified `SOURCE`, not changed.
- Chunked runs: `first_chunk_profile` leaves `relationships` empty (`execution/native/_dispatch.py:211`), and FK tables reroute to the oracle; no FK path reads the changed flags.

### 7.4 Fields

- Section 6.2 classifies every field; the new ones are `profiling.ColumnProfile.basis` (`profiling/types.py:173`), `TableCore.basis` and `TableCore.scanned_rows` (`profiling/_scan_core.py:92`).
- `key_candidates` keeps its type and changes meaning on a sample (`profiling/scan_set.py:362`).

### 7.5 Output surfaces

- `scan-set/v1` core (`decoy scan --output`, `scan_set_to_dict(detail=False)`): two members and the key rule.
- `scan_set_to_dict(detail=True)` `detail` member: the nested profile dict gains `basis`.
- `profile_document` and `redact_profile_dict` (the demo `scan.json`, `decoy.scan()` saved through it): `basis`.
- `decoy scan` card, `--show-fields` table, `--json` flat and multi payloads (`C:src/decoy/cli/scanning/_multi.py:252`).
- `decoy scan show` card and `--json` (`C:src/decoy/cli/scan.py:794`).
- `decoy scan fields`: unchanged (PII scores and quasi-identifier membership only).
- Planner `profile_to_json` and `plan_to_yaml`: no new key; a first-chunk profile is never serialized by a route (AT-14).

## 8. Reuse inventory

| Need | Existing piece | Use |
|---|---|---|
| Walk every type a profile document reaches | `profile_types()` and `_walk` in `_value_redaction.py` | the sentry walks root 1 with it; no second walker |
| Registry-plus-sentry pattern | `VALUE_FIELDS`, `VALUE_FREE_FIELDS`, `tests/sentry/profiling/test_profile_value_registry.py` | `FIELD_BASIS` copies the key shape, the both-ways coverage test and the seeded extra-field mutation |
| Strict key retention in a loaded document | `_shape_keep`, `_conforms` | extended with `Literal`; no second retention check |
| Old-record read defaults | `ScanSetCoreRead` from `_relaxed` | defaults carry over; nothing new |
| H6 key invariant | `ColumnProfile.__post_init__` (`profile/_types.py:105`) | `_as_chunk_sample` satisfies it; no second check |
| Schema snapshot | `tests/unit/profiling/test_scan_core_move.py` with `tests/fixtures/f07/scan-set-core-schema.json` | regenerated, not hand-edited |
| CLI `--json` shape snapshot | `C:tests/e2e/release_freeze/write_shapes.py`, `C:tests/fixtures/release_freeze/json-shapes.json` | regenerated by its writer |

## 9. Acceptance tests (red first)

Each must fail on `origin/main`, except the characterization tests AT-14, AT-15 and AT-16, which pass before and after. The fixture `hostile_25k.csv` is built in the test: 25,000 rows, `id = i % 12000`, `n` null on every 7th row after row 10,000, `u` unique throughout.

| AT | What | Fails today because | Named mutation |
|---|---|---|---|
| AT-1 | Default head scan of `hostile_25k.csv`: table `basis == "sample"`, `scanned_rows == 10000`, `row_count >= 25000` | no members | hard-code `basis = "whole"` in `_table_core` |
| AT-2 | Same scan: `key_candidates == []`; with `sample_rows=None`: `key_candidates == ["u"]` (`id` is not a key over the file) | `["id", "u"]` today | delete the basis condition in `claim_keys` |
| AT-3 | Head scan of a 4,812-row CSV: `basis == "whole"`, `row_count == 4812`, `row_count_exact is True`, `scanned_rows == 4812` | estimate, not exact | keep `max(count.value, len(frame))` on the short read |
| AT-4 | Head scan of a CSV of exactly 10,000 rows, cap 10,000: `basis == "sample"`, no keys | keys claimed | `scanned <= cap` in `read_basis` |
| AT-5 | Random strategy: 25,000 rows, cap 10,000 gives `sample`; 4,812 rows gives `whole` | no members | derive basis from `strategy` alone |
| AT-6 | `strategy="full"`: `basis == "whole"`, `scanned_rows == row_count`, `sample_row_cap is None` | no members | treat `full` as a sample when a cap is passed |
| AT-7 | `profile_columns(df.head(100), sample_strategy="head", sample_row_cap=100)` on a 1,000-row frame gives `sample`; on a 50-row frame gives `whole`; `profile_document` keeps the key in both | no key | default `basis` to `"whole"` |
| AT-8 | `redact_profile_dict` on a loaded document with `basis` set to `"Jane Roe"`, `True`, `1`, `"WHOLE"`: the key is dropped; `"whole"` and `"sample"` survive | key unknown, always dropped | accept any `str` for a `Literal` hint |
| AT-9 | `read_scan_set` on a pre-change core (no `basis`, no `scanned_rows`): `basis == "sample"`, `scanned_rows is None`; the existing samples in `tests/integration/compat_corpus/` still read | members absent | read default `"whole"` |
| AT-10 | The `TableCore` write model refuses `basis="whole"` with `scanned_rows < row_count`, `basis="whole"` with `row_count_exact=False`, `scanned_rows > row_count`, and a missing `scanned_rows` | no validator | delete the model validator |
| AT-11 | Sentry `tests/sentry/profiling/test_field_basis_registry.py`: the fields reached from the three roots equal the keys of `FIELD_BASIS`, both ways; every type holding a `SCANNED` or `CHECKED` field sits under a carrier; seeded: `FieldStats`, `FieldCore` and planner `ColumnProfile` each rebuilt with one extra field fail it | no registry | remove one registry entry; make the walk skip pydantic models |
| AT-12 | Property, same sentry file: for every `CHECKED` field, `scan_sources` on `hostile_25k.csv` at caps 10, 1,000 and 10,000 yields empty or `False`, and no planner `ColumnProfile` holds `sampled=True` with a key flag | key claimed today | drop the basis condition, seen through the registry |
| AT-13 | `first_chunk_profile` on a 1,000-row slice with `id` unique in the slice, with and without `carried={"id"}`: every column `sampled is True`, `is_candidate_key_sampled is False` | `sampled=False`, key `True` | apply `_as_chunk_sample` before the carried replacement |
| AT-14 | Characterization: a chunked mask run (oracle and native lanes) of one source at chunk sizes 1,000 and 2,000 gives byte-identical output and identical route evidence; neither result, nor any file it writes, holds `profile_hash` or `plan_hash` | passes today; guards Q1 | add `plan.profile_hash` to the chunked route evidence |
| AT-15 | Characterization: `tests/unit/profile/test_hash_regression.py` `PINNED_HASH` and the `profile_source` hashes of its fixtures are unchanged | passes today | drop sampled columns' counts from `_data_shape_bytes` |
| AT-16 | Characterization: `empty_input_profile` and its compile are unchanged | passes today | apply `_as_chunk_sample` to the empty profile |
| AT-C1 | `decoy scan hostile_25k.csv --has-header`: card shows "of about" and "(sample, head)" and Key candidates "not checked"; the 4,812-row file shows "(whole file)" and the key | no labels | render `key_candidates` without reading `basis` |
| AT-C2 | `--json` flat payload: `basis`, `scanned_rows`, `row_count_exact`, and `row_count` equal to the core's source count; `json-shapes.json` regenerated | `row_count` is scanned rows | take `row_count` from `scan.profile.row_count` |
| AT-C3 | Two-file scan `--json`: each table carries the same four members | missing | drop `basis` from `_table_summary` |
| AT-C4 | `decoy scan show scan.json id` on a sampled saved scan: "(in 10,000 scanned rows)" on Nulls and Distinct; `--json` top-level `basis` and `scanned_rows` | no labels | drop the label helper call |
| AT-C5 | `--show-fields` headers read "(sample)" on a sample and plain on a whole read | no labels | always print plain headers |
| AT-C6 | `decoy scan show` on a saved core with no `basis`: "basis not recorded (read as a sample)" | no label | treat a missing `basis` as whole |
| AT-C7 | Sentry `C:tests/sentry/cli_text/test_scan_basis_labels.py`: in the regenerated `json-shapes.json`, every object holding `null_rate`, `null_count` or `distinct_count` has `basis` on itself or its nearest table object | no labels | remove `basis` from the multi payload |

## 10. Placement (against CODEMAP.md "Where Things Go")

| Path | New or changed | CODEMAP row | Sits beside, note |
|---|---|---|---|
| `src/decoy_engine/profiling/_basis.py` | new | "Detectors, profiling": by profiling concern | beside `_value_redaction.py`; `profiling/` has 23 counted modules, this makes 24 (cap 25, no allowlist entry); CODEMAP profiling row gains one clause |
| `src/decoy_engine/profiling/types.py`, `profiler.py`, `scan_set.py`, `_scan_core.py`, `_value_redaction.py` | changed | same row | `_value_redaction.py` 580 lines, ends near 586 (goal 600) |
| `src/decoy_engine/execution/_chunked_profile.py` | changed | `execution/` row ("the Arrow-native column profile lives in `_chunked_profile.py`") | no new module in `execution/` (fan-out frozen at 103) |
| `tests/sentry/profiling/test_field_basis_registry.py` | new | sentry tests | beside `test_profile_value_registry.py` |
| `tests/unit/profiling/test_scan_basis.py`, `tests/unit/execution/test_chunked_profile_basis.py` | new | owning package tests | - |
| `docs/compatibility-contract.md` (scan-set paragraph, section 1 pre-GA corrections), `CHANGELOG.d/` fragment, `docs/qa/03-pre-scan-profiling-detection.md`, `CODEMAP.md` | changed | docs | - |
| `C:src/decoy/cli/scanning/_multi.py` | changed | "`decoy scan` internals" | 512 lines, ends near 570 (cap 800) |
| `C:src/decoy/cli/scan.py` | changed | same row; `scan.py` keeps only the options | legacy over 800; net line change zero or negative |
| `C:tests/sentry/cli_text/test_scan_basis_labels.py` | new | "Sentry test" | registered in `C:tests/sentry/test_sentry_manifest.py` |
| `C:tests/fixtures/release_freeze/json-shapes.json` | regenerated | "Versioned schema artifacts" | by `write_shapes.py` only |
| `C:docs/` scan reference, `C:docs/roadmap/groups/scan.md`, `C:docs/RECENTLY-SHIPPED.md`, CLI CHANGELOG | changed | docs, roadmap | - |

Public names added: none. `ColumnProfile.basis` is a new attribute on a frozen class with a default.

## 11. Size budget

| Slice | Production lines | Test lines | Docs lines | Production files |
|---|---|---|---|---|
| E1 | about 190 (`_basis.py` 110, the rest under 20 each) | about 380 | about 40 | 6 |
| E2 | about 20 | about 120 | about 10 | 1 |
| C1 | about 70 | about 200 | about 60 | 2 |

Stop at 10 production files or 800 changed lines per slice. No module-size entry, fan-out entry or ceiling is added or raised in either repo.

## 12. Frozen contracts

- `scan-set/v1` (contract 3.1, `docs/frozen-surfaces.md:54`): two additive members with read defaults; `key_candidates` empty on a sample. Tag unchanged. Schema snapshot regenerated. `Breaking:` entry for the meaning of `key_candidates`.
- `profile_document`, `redact_profile_dict` and `ColumnProfile` (frozen names, `docs/frozen-surfaces.md:80`): one new key and one new dataclass field with a default; no signature change. `Breaking:` entry for the new key.
- `flagged-redacted/v2` marker: unchanged; row 24zm's floor rules are not touched.
- `profile_hash` and `plan_to_yaml`: no rule change (Q1). A first-chunk hash moves but is never written (AT-14).
- CLI `decoy scan --json` and `decoy scan show --json` (frozen at 1.0 by the freeze batch): new members, and `row_count` changes meaning in the CLI payload (Q3). `Breaking:` entry in the CLI CHANGELOG.
- After 1.0, `basis`, `scanned_rows` and the values `sample` and `whole` are frozen. A third value later (for example for the 1.x exact-aggregate opt-in) is a minor change only because readers treat an unknown value as `sample`; C1 does that and the contract paragraph says so.

## 13. Slices

| Slice | Content | Risk | Depends on | Tests at T1 | Gate |
|---|---|---|---|---|---|
| E1 | 4.1, 4.2: `_basis.py`, `basis` on the profile document, `TableCore` members and validator, short-read exact count, `claim_keys`, `Literal` conformance, sentry, contract paragraph, CHANGELOG fragment, QA checklist line, CODEMAP | R2 | 24zm E1b merged (it is, engine #665) | AT-1 to AT-12, `tests/unit/profiling/`, `tests/sentry/profiling/`, `tests/integration/compat_corpus/`, `tests/unit/test_public_api.py`, module size, fan-out | T2 on the exact head, plus the full engine suite against the saved main baseline (frozen-contract and serialization trigger); Dennis then Codex |
| E2 | 4.3: `_as_chunk_sample`, docstring, AT-13, AT-14, AT-16 | R1 (R2 if any golden moves) | none; merges before or after E1 | AT-13 to AT-16, chunked profile tests in `tests/unit/execution/`, chunked cases in `tests/parity/` | T2; Codex (Dennis too if a golden moves) |
| C1 | 4.4: card, fields table, `--json`, `scan show`, CLI sentry, docs, roadmap row, shipped log, CHANGELOG | R2 | E1 released and the CLI repinned (engine repin checklist) | AT-C1 to AT-C7, `C:tests/e2e/` scan tests, `C:tests/e2e/release_freeze/test_json_shapes.py`, `C:tests/sentry/` | T2; Dennis then Codex |

Engine first (E1 and E2 in parallel, separate worktrees), then the engine release and repin, then C1. Tests run on the Mac first, then `~/bin/vm-run`, never on the devbox.

### 13.1 Order against related work

- Row 24zm (PROFILE-UNFLAGGED-VALUES): E1a (#629) and E1b (#665) are merged. E1 here adds one `VALUE_FREE_FIELDS` entry and the `Literal` rule next to its registry and changes none of its floor rules. 24zm C1 (CLI docs and the demo `scan.json` test) is open; C1 here touches neighbouring CLI docs, so whichever merges second rebases. Both ride the same engine repin if E1 lands in time.
- Freeze batch (`origin/plan/freeze-batch`): E1 and E2 should merge before the freeze engine release so its one CLI repin carries them, and C1 must merge before REL-GATE G0 (2026-12-04). If E1 misses that cut, it ships in the next daily engine release and C1 follows its repin. This plan adds no public name and no `"<name>/vN"` tag, so the freeze batch's stability registry (X0) and tag census (S7) need no row. If E2 moves a golden, whichever of E2, FREEZE-OUTPUT O1 and O3, and FAKER-MIGRATE S2 lands later reruns the owning tools named in freeze-batch section 5.6 and requires a clean `git status`.
- Row 24f (fit redaction): merged. The fit snapshot is a whole-frame document (`profiling/_snapshot_values.py:584` only picks names from a head), so it needs no basis label; its types are outside the three roots.

## 14. Stop lines for builders

1. One basis rule (`read_basis`), one key rule (`claim_keys`), one chunk transform (`_as_chunk_sample`), one registry (`FIELD_BASIS`). The CLI reads `basis` from the engine's output and never recomputes it.
2. Do not change `_data_shape_bytes`, `PINNED_HASH`, `VALUE_FIELDS`, `PROFILE_FLOOR_FIELDS`, `PROFILE_FLOOR_KEEP` or the `flagged-redacted/v2` marker.
3. Do not add a parameter to `profile_columns`, `scan_sources` or `first_chunk_profile`, and add no public name.
4. A golden, parity capture or schema snapshot that moves is regenerated by its owning tool and listed in the build record; none is edited by hand. A moved masked-output golden is a stop: E2 must not change masked bytes.
5. `_value_redaction.py` stays at or under 600 lines and `C:src/decoy/cli/scan.py` must not grow; if either would, stop and report.
6. C1 does not merge before the CLI pins an engine release that holds E1.
7. Do not flip `TableProfile.row_count_exact` for the first chunk (`execution/capacity.py:481` reads it).
8. Write the acceptance tests first and show each red before the fix; attack your own diff with each named mutation. Never widen a threshold, skip a test or weaken an assertion; a red test outside the ones named here is a stop. Commits: Conventional Commits subject at most 72 characters, final line `cam`, no other trailers.

## 15. Owner questions

Recommended answer first in each.

1. First-chunk hash. (a) Label the chunk as a sample and keep the hash rules (recommended). The row allows it; (b) moves every sampled `profile_source` plan hash and `PINNED_HASH`, and no route writes a first-chunk hash (AT-14 keeps it so). (b) Hash a sampled column without its `null_count` and `distinct_count`. Choose (b) only if plan hashes must not depend on how much was read, because after the freeze that is a 2.0 change.
2. Where the label sits. (a) One `basis` and `scanned_rows` per table record, and `basis` on the profile document, with the registry deciding which fields each governs (recommended). Every field of a table comes from one read, so a per-field key repeats one fact in every record. (b) A `basis` key on every field record.
3. CLI `--json` `row_count`. (a) Make it the source row count, as in the saved core, and add `scanned_rows`, `basis` and `row_count_exact` (recommended). Today the same key means scanned rows in `--json` and source rows in the saved core, and after 1.0 that split is frozen. (b) Keep `row_count` as scanned rows and add `source_row_count`.
4. Keys on a sample. (a) `key_candidates` empty, and the card says "not checked (sampled scan; --rows 0 reads every row)" (recommended, Deequ's suggest-then-verify split). (b) Also add a `sample_unique_columns` list labeled as a hint, which freezes one more member holding a weak claim.
5. A head read that returns exactly the cap. (a) Call it a sample (recommended; no reader change, and the cost is one unclaimed key on a file of exactly 10,000 rows). (b) Read one extra row to tell, which needs a basis passed from `scan_set` into `profile_columns` and so a new parameter.

## 16. Unresolved and V2-LOG

- Found while planning, outside this row: the planner's unique-capacity check computes `row_count - null_count` from a source `row_count` and a sample `null_count` (`plan/_checks.py:161`), and the routing saturation guard reads sampled distincts (`execution/_pipeline_routing_signals.py:460`). Neither reaches output, and neither is a 1.0 break. Recommended: a new 1.x row; `FIELD_BASIS` gives that fix its input.
- The 1.x opt-in for exact whole-file aggregates over a sampled scan adds a basis value; section 12 says how it stays a minor change.
- Platform consumers of `ColumnProfile.to_dict()` (platform parked) read the new key with its default.

## 17. Pre-mortem

- Key claims disappear for every default scan of a large file and users read that as "no keys". Mitigation: the card says "not checked" and how to check; the docs say why.
- A reviewer finds a sample-derived field that section 6.2 missed. The sentry turns that into a build failure, not a review finding; the table is advice to the builder.
- `Literal` support in `_conforms` keeps a value it should drop. AT-8 feeds near-miss strings, a bool and an int.
- E2 moves a masked-output golden because some admitted strategy did read a profile count. AT-14 catches it; stop line 4 stops the slice and the finding goes back to the plan.
- C1 merges against an engine without E1 and every scan shows "not recorded". Stop line 6 and the repin checklist prevent it.
- The freeze release is cut without E1. C1 then waits for a daily release; the 2026-12-04 gate still holds if E1 merges by 2026-12-01.

## 18. Done when

- E1, E2 and C1 merged; the engine release holding E1 and E2 pinned by the CLI.
- The probe in 1.2, rerun on the merged engine, shows `basis: "sample"`, `scanned_rows: 10000`, `key_candidates: []`, and first-chunk columns with `sampled=True` and no key flag.
- Roadmap row PROFILE-SAMPLE-LABELS closed in `C:docs/roadmap/groups/scan.md` and the shipped log updated in the same CLI PR.
