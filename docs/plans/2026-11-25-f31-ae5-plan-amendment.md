# F31 AE5 plan amendment: one builder for config loader refusal text

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
REMEDIATE three-round stop), cross-cutting-concerns, architecture (placement), testing (test
depth), security, catalogs/recurring-defects.

Amends: `2026-11-24-f31-audit.md`, slice AE5 (loader text). PR: decoy-engine #810, head
`da71c502e`. The PR reached the 3-round review cap (Codex R3 NO-GO), so the plan changes before
more code. Risk stays R2 (value leaks in error text).

## Why the plan changes

Each round fixed the sites the review named, and the next round found the same leak at a site
next to them:

| Round | Findings | Patch |
|---|---|---|
| R1 | snapshot paths and exception text in plan and statistical refusals | per-site fixed text |
| R1 follow-up | locators in joint-mask, reference-table, code-set, model-pack and DP messages | per-site removal |
| R2 | Arrow time zone, version pins, manifest values, DP versions, name-hint terms, statistical values | per-site rewording, 23 single-site canaries |
| R3 | `!!int PRIVATEMARKER` reaches `str(exc)` as a `ValueError`; ambient directory in name-hint validation errors; list-valued pin `['PRIVATE_RELEASE']` and a credentialed corpus URL through `CodeSetConfig.from_dict`; joint-mask missing `reference` skips position binding; `_TYPE_KINDS` repeats `is_text`; loose test file; parser exception chained with `from exc` | none yet |

Dennis R1 on this plan was GO-WITH-FIXES with no redesign. Every finding is in the plan:
V1-1 (S5 scope), V1-2 (S1 on every construction, per-class table, one exemption), V1-3
(`raise_refusal`), V1-4 (`read_config` pass-through), V1-5 (B1 value and name slots), V1-6
(merge-base seed), D1 (facade imports), D2 (`!!int` has no position), D3 (AE5b tracking), D4
(mutations N12 to N15), D5 (commit order) and the JSON position V2-LOG item.

## Defect class

**Per-site message assembly in config loaders.** Each loader builds its own refusal text with
f-strings, `!r` and `type(x).__name__`. Every author must remember, at every site, that the value
in hand is supplied data. Each site misses a different case: a scalar converted by a non-YAML
error, the ambient directory path, a list pin under `!r`, a URL in `name!r`, a path written as a
literal instead of the bound position, a parser exception chained with `from exc`. On
`da71c502e`, 83 of the 98 refusal raises in the nine AE5 loader modules interpolate a runtime
value, and 246 of 279 config refusal raises across 62 engine files do. In the audit plan's class
table this is class 1 (value-bearing output); the chaining case is recurring defect 3 (`from
None` keeps `__context__`).

## Guarantee and non-goals

Guarantee: for the nine AE5 loader modules (Enumerations, Routes), every refusal the module
raises has text and a `path` key built only from:

- literal field names written in engine source;
- integer indexes;
- supplied names that pass `approve_name` (`reasons/_record.py:84`), else a fixed placeholder;
- a closed problem and a closed expected-type label;
- a closed type kind of the rejected value;
- engine-owned constant choice lists;
- literal hints.

No supplied value, path, URL or parser or library exception text reaches `str(exc)`,
`repr(exc)`, `exc.args` or `path`. Each refusal has `__cause__` and `__context__` None.

Non-goals:

- The other config refusal sites (about 160 outside the nine modules) are migrated in slice AE5b.
  The sentry holds them in a shrink-only baseline.
- Hostile objects passed through the Python API, not YAML or JSON (V2 threat model).
- Log lines. The F31 log filter (AE3) and `test_log_interpolation.py` cover them.

A finding outside this guarantee is a follow-up item, not a blocker for #810.

## Established solutions

Search run: Pydantic v2 error reporting (`ValidationError.errors(include_input=False,
include_url=False)`), the `jsonschema` `ValidationError` (`path`, `validator`), the OWASP Error
Handling Cheat Sheet and ASVS 7.4.1, CWE-209, and in this codebase
`safe_output/_validation.py` and `tests/sentry/defects/test_validation_sites.py`.

- Pydantic and `jsonschema` report a validation failure as a location (a tuple of field names and
  indexes) plus a closed error type with a message template. With `include_input=False` the
  supplied value is left out. This amendment follows that model: location plus problem plus
  expected type, built in one place.
- The engine already does this for Pydantic models: `validation_problems` reads only `loc`, the
  error type and allowlisted context keys, and `yaml_error_text`
  (`safe_output/_validation.py:258`) reads only the YAML mark's line and column. The builder
  reuses both rules.
- ASVS 7.4.1 and CWE-209: show a generic message, keep the detail out. The closed problem enum is
  that generic message.
- `test_validation_sites.py` already classifies raise messages with the F31 tagger
  (`tests/sentry/safe_output`) and pins them by AST digest. The new sentry reuses that tagger and
  the shared `tests/sentry/_ratchet.py`.

Remaining custom code: the builder (about 120 lines) and the sentry (about 250 lines). No library
builds refusal text for hand-written YAML loaders.

## Choke point

One builder, `config_refusal`, in a new private package `decoy_engine._config_text`. Every
refusal in a loader module takes its text and its `path` key from it.

```python
def config_position(*segments: str | int | Name | Member) -> ConfigPosition: ...
def config_refusal(
    position: ConfigPosition,
    problem: Problem,
    *,
    expected: Expected | None = None,
    got: object = _ABSENT,
    choices: tuple[str, ...] | None = None,
    hint: str | None = None,
) -> Refusal: ...  # Refusal(text: str, key: str)
def read_config(
    read: Callable[[], T],
    position: ConfigPosition,
    raise_as: Callable[[Refusal], BaseException],
) -> T: ...
def raise_refusal(exc: BaseException) -> NoReturn: ...
```

Imports (Dennis D1): `_config_text` uses the package facades, `from decoy_engine.reasons import
approve_name` and `from decoy_engine.fileaccess import position_key`, not the private modules.
B5 checks that neither facade pulls pyarrow on the final head.

Rules the builder applies at run time:

1. **Position.** A plain `str` segment is a field name and must be a literal (sentry rule S2).
   An `int` is an index, shown as `[i]`. `Name(value)` holds a supplied name such as a
   `detector_id`: it shows `approve_name(value)`, else `<name>`. `Member(value)` holds a file
   name from a manifest: it shows the bare name (`PurePosixPath(value).name`) after
   `approve_name`, else `<file>`. `config_position` joins the segments and calls
   `position_key`, so a refusal inside `at_position` binds the table and column with no extra
   call. `Refusal.key` is that joined key and is the only value passed as `path=`.
2. **Problem.** A closed enum: `MISSING`, `EMPTY`, `WRONG_TYPE`, `NOT_FOUND`, `UNREADABLE`,
   `UNPARSEABLE`, `DUPLICATE`, `MISMATCH`, `TOO_LARGE`, `NOT_ALLOWED`. Each member has one fixed
   phrase.
3. **Expected.** A closed enum of type phrases (`STRING`, `NON_EMPTY_STRING`, `INTEGER`,
   `RELEASE_ID`, `BOOLEAN`, `LIST`, `NON_EMPTY_LIST`, `MAPPING`, `FILE`, and the others the nine
   modules need). A new phrase is a new enum member in this one module.
4. **Got.** Only a type kind from a closed table keyed by exact type (`type(v) is X`). `bool` is
   checked before `int`. The table also covers `float`, `str`, `list`, `dict`, `None`, `date`,
   `datetime`, `bytes` and `set`. Any other type is `other`. It never reads `__name__` and never
   calls `repr`.
5. **Choices.** An engine constant. Each entry goes through `approve_name`, and refused entries are
   dropped.
6. **Hint.** A literal (sentry rule S2).
7. **Text.** `"<position>: <problem>[; expected <expected>][, got <kind>][. Allowed:
   <choices>][. <hint>]"`.

`raise_refusal(exc)` is the one way a zero-set module raises a refusal (Dennis V1-3). Python sets
`__context__` at the `raise` statement to whatever exception is being handled, also one the
caller is handling in an outer `except`, so clearing it before the raise is not enough. The
helper raises `exc`, catches it at once, sets `__cause__` and `__context__` to None and
`__suppress_context__` to True, and re-raises it with a bare `raise`, which does not chain
again. This catch-and-re-raise is the one `except` with a raise that the sentry allows, and only
inside `_config_text`. `read_config` uses it, and so does every raise in the nine modules. The
copy of this logic in `transforms/joint_mask.py` (the `except PlanCompileError as fresh` block
at `:147`) is deleted.

`read_config` is the one read-and-parse wrapper:

- It calls `read()` and catches `Exception`, not only `yaml.YAMLError`, so a `ValueError` from a
  YAML scalar constructor is caught.
- It does not catch, and lets pass unchanged (Dennis V1-4), `FileAccessDenied` and
  `FileAccessUnavailable` (`fileaccess/_types.py:92`, `:135`) and `MemoryError`. These are
  engine-owned results with value-free text that callers and the CLI already map to their own
  exit codes. Catching them would turn a policy denial or a memory failure into "could not be
  parsed".
- From a caught exception it keeps only the YAML mark's line and column (the `yaml_error_text`
  rule). An error with no mark, such as the `!!int` `ValueError`, gives the text with no line or
  column (Dennis D2).
- It builds `raise_as(refusal)` after the `except` block has closed and raises it through
  `raise_refusal`.

`yaml_error_text` moves into `_config_text` and `safe_output` re-exports it, so the line and
column rule stays in one place.

### Sentry

`tests/sentry/defects/test_config_refusal_text.py` is an AST scan of `src/decoy_engine`. It reuses
the F31 tagger (`RISKY_NAMES`, `risky_in`) and `tests/sentry/_ratchet.py`. The zero set is the
nine AE5 modules, listed as a constant in the sentry.

**Refusal classes.** The roots are `PlanCompileError`, `NameHintLoaderError`,
`ModelPackLoadError`, `ProvenanceError`, `ConfigError` and `StatisticalSpecError`. The sentry finds
every subclass of a root with an AST walk of the class definitions in `src/decoy_engine`. A
per-class table in the sentry names where the message and the path are passed:

| Class | Message argument | Path argument |
|---|---|---|
| `PlanCompileError` | third positional, or `message=` | second positional, or `path=` |
| `PipelineValidationError` (`errors.py:39`, a `ConfigError` subclass) | first positional, or `message=` | second positional, or `path=` |
| `ConfigError`, `ConfigRuleError`, `NameHintLoaderError`, `ModelPackLoadError`, `ProvenanceError`, `StatisticalSpecError` | first positional, or `message=` | none |

A subclass with its own `__init__` and no table row is a finding, so a new signature cannot slip
past the table.

- **S1 every construction (Dennis V1-2).** S1 checks every call that builds a refusal class, not
  only calls written directly after `raise`. That covers a helper that returns the exception, a
  value assigned to a name and raised later, and a call passed to `raise_refusal`. The message
  argument must be one of these:
  - a `str` constant;
  - `<config_refusal(...)>.text`;
  - `<r>.text`, where `r` is bound once in the same function by `r = config_refusal(...)`.

  The path argument must be a constant or `<r>.key`. `raise <name>` is allowed, because the
  construction that bound the name is checked where it is built. The one named exemption is
  `_rebuild_load_error` (`profiling/model_pack/loader.py:78`), the pickle rebuild of a
  `ModelPackLoadError` from the text it already had. Any other function that builds a refusal
  from a parameter is a finding.
- **S2 builder arguments.** `problem=` and `expected=` are `Problem.X` and `Expected.X`
  attributes. `choices=` is a module-level UPPER_CASE name. `hint=` is a `str` constant. Each
  `config_position` segment is a constant, an int, or a `Name(...)` or `Member(...)` call whose
  argument the tagger does not mark as risky.
- **S3 chaining, zero set only.** No `raise <call>` or `raise <name>` sits inside an `except`
  body, no `raise ... from` exists, and every refusal raise goes through `raise_refusal`. A bare
  `raise` is allowed.
- **S4 except names, zero set only.** A name bound by `except ... as e` may appear only as the
  argument of `isinstance`, `type(e) is`, or `safe_error_type`.
- **S1 for builtin errors, zero set only.** In the nine modules, the message of a builtin error
  (`ValueError`, `TypeError`, `KeyError` and the others) follows the S1 message rule.
- **S5 ratchet (Dennis V1-1).** Outside the zero set, the sentry applies only S1 and only to the
  refusal classes. Builtin errors, S3 and S4 are not checked there. Chaining outside the zero set
  stays with the existing sentries `tests/sentry/defects/test_exception_context.py` and
  `tests/sentry/safe_output/test_exception_text_copy.py`. A site that breaks S1 needs an entry in
  `tests/sentry/baselines/config-refusal-text.json`, keyed `<file>::<qualname>::<digest>`. The
  baseline may only shrink. Zero-set modules may have no entries. A new module that calls a
  config reader (`fileaccess` open, `serial.yaml_safe_load`, `serial.json_load`,
  `yaml.safe_load`, `json.load`, `pq.read_*`, `urlsplit`) and builds a refusal with a non-builder
  message has no baseline entry, so it fails.
- **Baseline seed (Dennis V1-6).** The baseline is seeded only from the merge base: the builder
  runs the S1 scan on the merge-base sources (`git show <merge-base>:<path>`) and writes those
  findings. A site that this PR adds or changes cannot enter the baseline. The sentry id is not
  added to `REKEY_PER_SITE` (`tests/sentry/_ratchet.py:36`), so a changed message is new growth,
  not a re-key. The PR body states the seeded entry count.

Guard mutation: put `f"... {version!r}"` back into `_codeset_config_checks.py`. S1 turns red.

## Class table

Classes from the plan contract catalog (`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes | `config_refusal`: closed problem, expected and kind tables; names through `approve_name` | A1 to A5, B1 (seeded canaries), B4 (sentry) | N1, N4, N5, N10 |
| 2 | cleanup on an exit path | yes, narrow: a read handle must close on a refusal | `read_config` runs inside the existing `try/finally` that closes the member | B2 cell: the handle is closed after a parse refusal | N2 |
| 3 | state and concurrency | yes, narrow: the ambient `at_position` context | `config_position` reads `position_key` once, when it is built | A5, B1 (property test runs each route inside `at_position`), B4 (S1 path rule) | N6 |
| 4 | route parity and fallback | yes: every loader entry, every policy (ambient, strict) | one builder for all policies; the ambient display is removed | A2, B1 under both policies | N4 |
| 5 | referential integrity | N/A: no table data or FK shapes | | | |
| 6 | untrusted producer | yes: PyYAML constructors, `pyarrow` and `json` exception text | `read_config` catches `Exception` and keeps only line and column | A1, A6 | N2, N3 |
| 7 | check then use on a path | N/A: no new path checks; reads keep their `fileaccess` handles | | | |
| 8 | weak tests and overclaimed evidence | yes: the R3 test removed `str(root)` before it checked the text | tests assert on the unmodified `str(exc)`, `repr(exc)`, `args` and `path`; each repro red on `da71c502e` | A2, the Acceptance tests section | |
| 9 | refactor drift | yes: about 98 sites change wording | snapshot tests that pin wording are updated in the same commit; reason codes and `path` keys stay the same except the A5 binding | the existing loader unit tests, green | N6 |
| 10 | frozen contract drift | N/A: no error class, reason code or public name changes (Frozen contracts touched) | | | |

## Enumerations

Read from `da71c502e`, the PR head.

### Exit paths

Each loader has four exits: success, read failure, parse failure, validation refusal.

- Name hints: missing or unreadable directory (`src/decoy_engine/detection/name_hints/loader.py:106`,
  `:113`); parse (`src/decoy_engine/detection/name_hints/loader.py:223`, which catches only
  `yaml.YAMLError` and chains `from exc` at `:227`); validation (`:120` to `:210`).
- Plan generation snapshot read: `src/decoy_engine/plan/_generation.py:179` (`OSError`), `:213`
  (decode), `:287` and `:462` (`StatisticalSpecError`).
- Joint mask: missing `reference` (`src/decoy_engine/transforms/joint_mask.py:200`, literal path),
  not found (`:213`), invalid (`:230`).
- Code-set config: wrong pin type (`src/decoy_engine/transforms/_codeset_config_checks.py:80`),
  reserved name (`:98`), unknown shipped corpus (`:109`).
- Reference tables, model pack, DP provenance, statistical spec, code-set loader: their refusal
  raises, each counted by the sentry on the final head.

### Routes

Public entry points that reach the nine modules:

- `load_name_hint_terms` (`src/decoy_engine/detection/name_hints/loader.py:58`);
- `CodeSetConfig.from_dict` through `validate_code_set_config`
  (`src/decoy_engine/transforms/_codeset_config_checks.py:30`), `load_corpus` and
  `load_corpus_provenance` (`src/decoy_engine/transforms/_codeset_loader.py:140`, `:172`);
- `JointMaskConfig.from_dict` and `validate_joint_mask_config`
  (`src/decoy_engine/transforms/joint_mask.py:110`, `:155`);
- `read_pinned_artifact` (`src/decoy_engine/plan/_generation.py:161`) and `load_spec`
  (`src/decoy_engine/generation/statistical/_spec.py:294`);
- `load_table` (`src/decoy_engine/reference_tables/_loader.py:46`);
- the model-pack loader and `load_with_fallback` (`src/decoy_engine/profiling/model_pack/loader.py`);
- the DP lockfile checks (`src/decoy_engine/quality/dp_provenance.py`).

Each route runs under the ambient CLI policy and the strict host policy. B1 runs both.

### FK shapes

N/A: the loaders read config files and reference tables. They do not handle FK relationships.

### Fields

- Exception fields a reader can see: `str(exc)`, `repr(exc)`, `exc.args`, `PlanCompileError.path`
  and `.code`, `__cause__`, `__context__`, `__traceback__`.
- Supplied slots planted with a canary by B1: scalar values, list items, mapping keys, YAML tagged
  scalars (`!!int`, `!!float`, `!!timestamp`), file names in a manifest, the directory name,
  corpus names and URLs, version pins, manifest fields, recorded DP versions.

### Output surfaces

- `str(exc)` and `repr(exc)`, printed by the CLI and by host programs.
- `PlanCompileError.path`, shown in plan reports and JSON output.
- The chained traceback, when a host prints it.
- Log records, which the AE3 filter covers (out of scope here).

## Reuse inventory

- `approve_name` (`src/decoy_engine/reasons/_record.py:84`) for supplied names and choices.
- `position_key` and `at_position` (`src/decoy_engine/fileaccess/_entry.py:186`, `:197`) for
  position binding.
- `yaml_error_text` rule (moved, re-exported).
- `safe_error_type` stays allowed where a module already uses it.
- `is_text` (`src/decoy_engine/_arrow_types.py:21`) for the `_TYPE_KINDS` string row.
- F31 tagger `tests/sentry/safe_output` and `tests/sentry/_ratchet.py` for the sentry.
- `scripts/dev/sentry_registry.toml` and `tests/sentry/test_baseline_registry.py` for the new
  baseline.

## Frozen contracts touched

None. Error classes, reason codes and public names stay the same. `path` keys stay the same,
except that the joint-mask missing `reference` now binds the ambient position like its two
sibling refusals. Message text is not a frozen contract. The ambient CLI no longer prints the
name-hint directory path. The position names the member file instead.

## Behavior changes from da71c502e

| Input | da71c502e | After |
|---|---|---|
| name-hint member with `!!int <text>` | `ValueError` with the text | `NameHintLoaderError`: `pre_scan.name_hints/<file>: could not be parsed`, with no line or column, because the constructor `ValueError` has no YAML mark (Dennis D2) |
| name-hint validation error, ambient policy | starts with the full directory path | starts with `pre_scan.name_hints/<file>` |
| list-valued `corpus_source_version` | `got ['…'] of type list` | `provider_config.corpus_source_version: wrong type; expected a string or integer release id, got list` |
| unknown shipped corpus given as a URL | the URL in `!r` | `provider_config.code_set: not found. Allowed: <shipped names>` |
| missing joint-mask `reference` in `at_position` | `joint_masks.reference` | `<position>.joint_masks.reference` |
| YAML syntax error | `__cause__` is the parser error | `__cause__` and `__context__` None |

## Acceptance tests

Written first. Each Codex R3 repro is a red test on `da71c502e`, shown red there before the fix,
and asserts on the unmodified `str(exc)`, `repr(exc)`, `exc.args` and `path`. Tests live in
`tests/unit/safe_output/test_loader_refusal_text.py` (moved from
`tests/unit/test_f31_ae5_loader_text.py`) unless stated.

Codex R3 repros, red on `da71c502e`:

1. A1 `test_yaml_scalar_conversion_error_is_value_free`: a name-hint member holding
   `!!int PRIVATEMARKER` raises `NameHintLoaderError`, with no `PRIVATEMARKER` anywhere and
   `__cause__` and `__context__` None. The text is exactly
   `pre_scan.name_hints/<file>: could not be parsed`, with no `line` and no `column`, because
   the `ValueError` carries no YAML mark (Dennis D2). Cells `!!float`, `!!timestamp`. A YAML
   syntax error cell keeps `at line L, column C`, so the two paths stay distinct.
2. A2 `test_name_hint_validation_omits_the_directory`: under the ambient policy, a directory whose
   name holds a canary and a member with a mapping in `patterns`. The unmodified `str(exc)` holds
   no canary and names `pre_scan.name_hints/<member>` and `list`. The same under the strict
   policy.
3. A3 `test_code_set_list_pin_is_value_free`: `CodeSetConfig.from_dict` with
   `corpus_source_version: ['PRIVATE_RELEASE']` raises `PlanCompileError` with no
   `PRIVATE_RELEASE`. The text names the field, the expected type and `list`.
4. A4 `test_code_set_url_corpus_is_value_free`: `code_set: "https://user:PRIVATEPW@host/x"` with a
   shipped source raises with no `PRIVATEPW`, no `user` and no `host`. The text lists the shipped
   corpus names.
5. A5 `test_joint_mask_missing_reference_binds_the_position`: inside
   `at_position("tables.orders.columns.zip")`, a missing `reference` gives
   `path == "tables.orders.columns.zip.joint_masks.reference"` and the text starts with it.
6. A6 `test_loader_refusals_have_no_chain`: YAML syntax error, scalar conversion error, unreadable
   member, missing reference file. Each refusal has `__cause__` and `__context__` None and
   `__suppress_context__` True (the R3 V2-LOG item, now in scope because S3 covers it). Outer
   except cell (Dennis V1-3): each loader is called inside
   `try: raise RuntimeError("OUTERCANARY") except RuntimeError: <call loader>`, and the refusal
   still has `__context__` None, so no outer exception text reaches a traceback.
7. A7 `test_reference_type_kinds_use_is_text`: the string row of `_TYPE_KINDS` is
   `_arrow_types.is_text` itself, in `tests/unit/reference_tables/`.
8. The test file move is checked in the PR diff, not by a test.

Earlier-round canaries, moved unchanged and kept green: the R1 snapshot cells (AT-6, e1_2, e1_5),
the fitted-reference and fingerprint canaries, and the R2 set:

- `test_reference_id_type_names_the_kind_not_the_timezone`;
- `test_joint_mask_invalid_reference_does_not_copy_the_loader_text`;
- `test_unknown_shipped_name_is_not_echoed_under_the_ambient_policy`;
- `test_code_set_version_pin_names_the_field_not_the_values`;
- `test_manifest_values_are_not_echoed`;
- `test_unexpected_fallback_error_logs_type_only`;
- `test_dp_lock_drift_names_distributions_without_versions`;
- `test_dp_duplicate_install_omits_both_versions`;
- `test_recorded_provenance_refusal_omits_recorded_values`;
- `test_name_hint_non_string_pattern_is_named_by_type`;
- `test_name_hint_yaml_parse_error_omits_the_directory`;
- `test_statistical_unknown_snapshot_kind_is_not_echoed`;
- `test_statistical_config_values_are_not_echoed`;
- `test_joint_mask_reference_refusal_binds_table_and_column`;
- `test_joint_mask_unsupported_mode_is_not_echoed`.

New guards:

9. B1 `test_every_loader_refusal_is_value_free` (Hypothesis): for each route in Routes, under
   both policies, plant a canary in each supplied slot listed under Fields. Non-vacuity check:
   each case first asserts that the call raised a refusal. The slots split in two (Dennis V1-5):
   - Value slots (field values, pins, URLs, file contents): the canary is never shown. Assert it
     is absent from `str`, `repr`, `args`, every `str` attribute and `path`, and that the chain
     is empty.
   - Name slots (`Name(...)` and `Member(...)` segments): the canary is shaped so that
     `approve_name` refuses it (a path, a URL, or longer than the name limit). The case asserts
     `approve_name(canary)` refuses it, then asserts the canary is absent from the same surfaces
     and that `<name>` or the bare file name is shown in its place. An approved name may appear
     and is not a canary.
10. B2 `tests/unit/config_text/test_config_refusal.py`. Cells:
    - the kind table, with `bool` before `int` and a `str` subclass shown as `other`;
    - `Name` with a URL, a path and a 200-character value, each shown as `<name>`;
    - `Member` with `../x` and `/etc/x`, each shown as the bare name;
    - refused choices are dropped;
    - `at_position` binding;
    - `read_config` with a `ValueError`, an `OSError` and a `yaml.YAMLError`, checking the text,
      that the chain is None and that the handle is closed;
    - `read_config` lets `FileAccessDenied`, `FileAccessUnavailable` and `MemoryError` pass
      unchanged (Dennis V1-4): `read` raises each one, and the test asserts the same object
      comes out (`is`), not a refusal class;
    - `raise_refusal` clears `__cause__` and `__context__` and sets `__suppress_context__`,
      also when called inside an outer `except`.
11. B3 sentry self-test: S1 to S5 run on seeded source snippets. Each snippet must be flagged:
    - an f-string message;
    - `!r`;
    - `str(exc)`;
    - a raise inside `except`;
    - `from exc`;
    - a non-literal `path=`;
    - a non-constant `choices=`;
    - a risky segment;
    - a new reader module outside the baseline.

    New S1 construction cells (Dennis V1-2), each flagged:
    - a helper `def _bad(v): return ConfigError(f"{v}")` that is never raised in that function;
    - `err = ProvenanceError(f"{v}")` followed later by `raise err`;
    - `PlanCompileError("code", "path", f"{v}")` (third positional argument);
    - `PlanCompileError("code", path=v, message=r.text)` (non-literal path);
    - a subclass of `StatisticalSpecError` defined in the snippet, built with an f-string;
    - a subclass with its own `__init__` and no row in the per-class table;
    - a builtin error with an f-string in a zero-set snippet; the same snippet outside the zero
      set is not flagged (V1-1).

    Cells that must pass: `err = ConfigError(r.text)` with `r = config_refusal(...)`, then
    `raise_refusal(err)`;
    `_rebuild_load_error` in its real module; the same body under any other name is flagged;
    a refusal built inside an `except` outside the zero set (S3 and S4 do not apply there).
12. B4 `test_config_refusal_text` on the real tree: zero findings in the zero set, and the
    baseline holds under `_ratchet.check`. Merge-base cell (Dennis V1-6):
    `test_config_refusal_baseline_is_from_the_merge_base` runs the S1 scan on the merge-base
    sources and asserts every baseline entry's `<file>::<qualname>::<digest>` is in that set. It
    also asserts the sentry id is not in `REKEY_PER_SITE`. When no merge base is reachable (a
    shallow clone), the cell fails, not skips.
13. B5: the existing `test_dp_provenance_imports_neither_pandas_nor_pyarrow` stays green, which
    proves `_config_text` pulls no pyarrow.
14. B6: the existing import-layer snapshot (`tests/sentry/layout/test_import_layers.py`) is
    updated for `_config_text` and stays green.

## Mutations

Each must turn at least one named test red on the final head (recurring defect 9: record the head
each mutation ran on). The builder records the results in the PR body.

| # | Mutation | Test that must fail |
|---|---|---|
| N1 | put a supplied value into one loader message with an f-string | B4 (S1), A3 |
| N2 | `read_config` catches only `yaml.YAMLError` | A1, B2 |
| N3 | raise inside the `except` block, or add `from exc` | A6, B2, B4 (S3) |
| N4 | bring back the ambient directory display | A2 |
| N5 | the builder renders `repr(got)` or `type(got).__name__` | B2, A3 |
| N6 | joint mask passes the literal `"joint_masks.reference"` as `path` | A5, B4 (S1) |
| N7 | build `choices` from a supplied list | B3, B4 (S2) |
| N8 | drop one reader from the sentry's reader list | B3 (new reader module case) |
| N9 | add a baseline entry for a zero-set module | B4 |
| N10 | `Name` skips `approve_name` | A4, B1, B2 |
| N11 | the `_TYPE_KINDS` string row uses its own checks again | A7 |
| N12 | S1 checks only calls written directly after `raise` (Dennis D4) | B3 (helper return, assign-then-raise cells) |
| N13 | S1 reads the first positional argument of `PlanCompileError` as the message (Dennis D4) | B3 (third positional cell) |
| N14 | `raise_refusal` clears `__cause__` but not `__context__` (Dennis D4) | A6 (outer except cell), B2 |
| N15 | seed one baseline entry from the head instead of the merge base (Dennis D4) | B4 (merge-base cell) |
| N16 | `read_config` catches `FileAccessDenied` and turns it into a refusal (Dennis V1-4) | B2 (pass-through cell) |

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| a refusal loses detail a user needed (the actual bad value) | user report; QA | the position and expected type name the field; the user reads the value in their own file |
| a new loader module adds its own message | S5: no baseline entry | route it through `config_refusal` |
| a supplied name looks like a field name and passes `approve_name` | by design: names are shown, values are not | accepted; `approve_name` refuses paths, URLs and long values |
| a builder phrase is missing for a new site | the enum has no member | add the member in `_config_text` |
| an existing snapshot test pins the old wording | T1 run | update the snapshot in the same commit, never weaken an assertion |

## Design notes

New structure: one private package with one builder, its enums and one read wrapper.

- Single responsibility and one place per fact. The refusal format, the problem phrases, the
  expected-type phrases, the kind table and the YAML line-and-column rule each live once, in
  `_config_text`.
- Open/closed. A new loader adds enum members at most. It adds no message format.
- The established pattern is the Pydantic location-plus-type report (Established solutions).
- House style: `Refusal` is a typed result, not a pair of strings, and there are no flag
  arguments.

## Placement

| New file | Directory | CODEMAP "Where Things Go" line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/_config_text/__init__.py` | engine root, as a sub-package | map change: a new row "Config refusal text foundation", worded like the `_canonical/` row (line 41 of the section): "a sub-package because the engine root is at its fan-out cap". It cannot go in `safe_output/`, because that package's `__init__` imports pyarrow and `dp_provenance` must not (B5) | `src/decoy_engine/_canonical/` |
| `tests/unit/config_text/test_config_refusal.py` | `tests/unit/config_text/` | "Unit tests: `tests/unit/<package>/` mirroring `src/`" (line 57) | `tests/unit/canonical/` |
| `tests/unit/safe_output/test_loader_refusal_text.py` (moved) | `tests/unit/safe_output/` | "Safe output boundary" row, tests in `tests/unit/safe_output/` (line 17) | `test_safe_error_type.py` |
| `tests/sentry/defects/test_config_refusal_text.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules in `tests/sentry/defects/` (line 45) | `test_validation_sites.py` |
| `tests/sentry/baselines/config-refusal-text.json` | `tests/sentry/baselines/` | the ratchet rows (line 46), registered in `scripts/dev/sentry_registry.toml` | `validation-name-messages.json` |

`.importlinter`: `_config_text` joins the tier of `safe_output` and `fileaccess` (it imports
the `decoy_engine.fileaccess` and `decoy_engine.reasons` facades only, Dennis D1). The layer snapshot test is updated in the same
commit.

## Size

- New: `_config_text` about 120 lines, sentry about 250 lines, builder unit tests about 150
  lines, B1 about 120 lines.
- Changed: about 98 raise sites in the nine modules. Net source lines go down, because the
  per-site f-strings get shorter.
- `transforms/_codeset_loader.py` (682 lines) and `generation/statistical/_spec.py` (591 lines)
  must not grow past their module-size ceilings.
- No new public names.

The builder reports the measured size against these numbers before review.

## Slices

1. AE5 (this PR, #810, decoy-engine, `feat/f31-ae5`): `_config_text`, the sentry with the zero set
   and the baseline, the nine modules migrated, the R3 fixes and the test move. Size above.
2. AE5b (new, decoy-engine, `feat/f31-ae5b`): migrate the baselined sites (about 160) to
   `config_refusal` and shrink the baseline to zero. Separate PR, R2, after AE5 merges. Tracked
   in the F31 audit plan slice table (`docs/plans/2026-11-24-f31-audit.md`) and in the vault
   `BRANCH-LIST.md` (Dennis D3). Exit criterion: the baseline has zero entries.

Commit order inside AE5 (Dennis D5):

1. `_config_text` (builder, enums, `read_config`, `raise_refusal`) with its B2 tests, and the
   sentry with the merge-base baseline. The zero set is red at this commit, and that is
   expected.
2. One commit per zero-set module, each turning that module green in the sentry.
3. The R3 red tests (A1 to A7), the test move, and the `joint_mask` copy deletion.

The PR body states the seeded baseline entry count (Dennis V1-6).

## Test depth

- T0 per edit: the touched module's tests.
- T1 per commit:
  - `tests/unit/safe_output/`, `tests/unit/config_text/`;
  - the nine modules' unit tests;
  - `tests/sentry/defects/test_config_refusal_text.py`, `tests/sentry/safe_output/`;
  - the module-size, baseline-registry, ratchet and import-layer sentries;
  - `tests/unit/quality/test_dp_provenance.py`;
  - ruff check, ruff format and mypy on changed files.
- Full-suite trigger: a new sentry baseline and an `.importlinter` change are test-config
  changes, so one full suite runs on the merge head (testing.md escalation list), diffed against
  the saved main baseline.

## Pre-mortem

Ways a gate reviewer could break the built change, each now a test or a recorded gap:

1. Another PyYAML constructor raises a non-YAML error (`!!binary`, `!!python/name` under safe
   load): `read_config` catches `Exception` (A1 cells, N2).
2. A site passes `str(exc)` as a `Name(...)` segment: S2 flags it with the tagger. At run time,
   `approve_name` refuses most exception text, but S2 is the guard.
3. A site builds the message in a helper function and passes the result: S1 accepts only the
   builder call or its bound result (B3 seeded helper case).
4. A refusal inside an `at_position` block uses a literal `path`: S1 path rule, A5.
5. The ambient display is restored in a different helper: A2 runs under the ambient policy on the
   unmodified text.
6. A choice list includes a customer corpus name: choices pass `approve_name`. Customer names are
   names, not values. Accepted.
7. `_config_text` pulls pyarrow later through a new import: B5.

## Docs and changelog

- The `_config_text` module docstring states the rule and cites the Pydantic pattern.
- The CODEMAP gets the new row.
- The CHANGELOG line says config loader errors name the field and expected type, not the
  supplied value or the file path.

## V2-LOG

- Hostile objects passed through the Python API whose `__eq__` or `__hash__` run during
  validation (V2 threat model).
- About 160 non-loader refusal sites until AE5b lands, held by the shrink-only baseline.
- JSON decode errors lose their line and column (Dennis V2-LOG): `read_config` keeps only a
  YAML mark, so a `json.JSONDecodeError` gives `could not be parsed` with no position. Keeping
  `lineno` and `colno` (ints, value-free) is a later change.
