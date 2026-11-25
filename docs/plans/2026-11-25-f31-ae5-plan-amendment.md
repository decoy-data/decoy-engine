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

Codex R2 on this plan was NO-GO. Each finding is fixed at the rule that let it through, not at
the named site:

- V1-1, `.as_py()` time zone leak: `read_config` covers read and materialization, and new
  sentry rule S6 bans materializers outside the `read=` callable (A8, N22).
- V1-2, list-valued name: `Name` and `Member` need `type(value) is str` before `approve_name`,
  and S2 flags `str()`, f-strings, `format` and `repr` inside them (A9, N17).
- V1-3, pass-through policy: `read_config` reuses `fileaccess.keeps_class` and takes the
  route's own `passes`, so the strict `FileAccessReadError` and `ENOSPC` contracts hold (A10,
  N18).
- V1-4, real route outcomes: B1 uses a per-route table (raise, `None`, `PinnedRead`, report),
  so a canary check cannot pass on a different refusal (N19, N20).
- Design 1, one checked factory form: builder output is a `Refusal`; `PlanCompileError` takes
  `r.key` and `r.detail`, a literal `path=` is a finding, and S2 runs wherever S1 accepts
  builder output (A5, N26).
- Design 2, occurrence counts: baseline entries carry `max`, using `_ratchet.max_raised`, and
  the PR body lists the head-minus-base inventory (B4 count cell, N21, N23).
- Design 4, closed Arrow label: `got_kind` takes a `Kind` member (A7, N24).
- Design 5, one bare-raise helper: `raise_bare` moves to `_error_base.py`, and every copy uses
  it (B3, N25).
- V2-LOG: the plan records no red runs or mutation results; the builder records them.

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
refusal in a loader module takes its text and its `path` key from it. The rules below are written
as properties of the boundary, not as fixes to the sites a review named (Codex R2).

```python
class Refusal:  # built only by config_refusal; `Refusal(...)` elsewhere is a sentry finding
    text: str    # "<position>: <detail>"
    detail: str  # the text with no position prefix
    key: str     # the joined position key
def config_position(*segments: str | int | Name | Member) -> ConfigPosition: ...
def config_refusal(
    position: ConfigPosition,
    problem: Problem,
    *,
    expected: Expected | None = None,
    got: object = _ABSENT,
    got_kind: Kind | None = None,
    choices: tuple[str, ...] | None = None,
    hint: str | None = None,
) -> Refusal: ...
def read_config(
    read: Callable[[], T],
    position: ConfigPosition,
    refuse: Callable[[Refusal], BaseException],
    *,
    passes: tuple[type[BaseException], ...] = (),
) -> T: ...
```

Imports (Dennis D1): `_config_text` uses the package facades, `from decoy_engine.reasons import
approve_name` and `from decoy_engine.fileaccess import position_key, keeps_class`, not the
private modules. B5 checks that neither facade pulls pyarrow on the final head.

Rules the builder applies at run time:

1. **Position.** A plain `str` segment is a field name and must be a literal (sentry rule S2).
   An `int` is an index, shown as `[i]`. `Name(value)` holds a supplied name such as a
   `detector_id`, and `Member(value)` a file name from a manifest. Both take the raw config
   object, never a converted one (Codex R2 V1-2). A name is shown only when `type(value) is str`
   and `approve_name(value)` accepts it; any other type is shown as `<name>` (or `<file>`), and
   the site refuses it with `Problem.WRONG_TYPE`. `Member` shows the bare name
   (`PurePosixPath(value).name`) after the same check. `config_position` joins the segments and
   calls `position_key`, so a refusal inside `at_position` binds the table and column with no
   extra call. `Refusal.key` is that joined key.
2. **Problem.** A closed enum: `MISSING`, `EMPTY`, `WRONG_TYPE`, `NOT_FOUND`, `UNREADABLE`,
   `UNPARSEABLE`, `DUPLICATE`, `MISMATCH`, `TOO_LARGE`, `NOT_ALLOWED`. Each member has one fixed
   phrase.
3. **Expected.** A closed enum of type phrases (`STRING`, `NON_EMPTY_STRING`, `INTEGER`,
   `RELEASE_ID`, `BOOLEAN`, `LIST`, `NON_EMPTY_LIST`, `MAPPING`, `FILE`, and the others the nine
   modules need). A new phrase is a new enum member in this one module.
4. **Got.** Either `got` (a Python value) or `got_kind` (a closed `Kind`), never both. For `got`
   the kind comes from a closed table keyed by exact type (`type(v) is X`). `bool` is checked
   before `int`. The table also covers `float`, `str`, `list`, `dict`, `None`, `date`,
   `datetime`, `bytes` and `set`. Any other type is `other`. It never reads `__name__` and never
   calls `repr`. `Kind` is a closed enum of column kinds (`INTEGER`, `FLOATING_POINT`, `DECIMAL`,
   `BOOLEAN`, `STRING`, `BINARY`, `TIMESTAMP`, `DATE`, `TIME`, `DURATION`, `DICTIONARY`,
   `NESTED`, `OTHER`). The Arrow classifier `_TYPE_KINDS` in `reference_tables/_loader.py:140`
   maps its predicates to `Kind` members instead of strings, so the builder renders `timestamp`
   with no file-authored time zone and `_config_text` never imports pyarrow (Codex R2 DESIGN 4).
5. **Choices.** An engine constant. Each entry goes through `approve_name`, and refused entries are
   dropped.
6. **Hint.** A literal (sentry rule S2).
7. **Text.** `detail` is `"<problem>[; expected <expected>][, got <kind>][. Allowed:
   <choices>][. <hint>]"` and `text` is `"<position>: <detail>"`.
8. **Which field goes where.** A class whose renderer already prints the path
   (`PlanCompileError`, `plan/_errors.py:36`, renders `[code] path: message`) takes `r.detail`
   as its message and `r.key` as its path, so the position is not printed twice. Every other
   refusal class takes `r.text` as its message. The per-class table in the sentry fixes this.

**One raise helper (Codex R2 DESIGN 5).** `secret_providers._errors.raise_bare`
(`src/decoy_engine/secret_providers/_errors.py:44`) is already the generic form: it takes any
`BaseException`, drops the old traceback, clears `__cause__` and `__context__`, sets
`__suppress_context__` and re-raises bare. Python sets `__context__` at the `raise` statement to
whatever exception is being handled, also one the caller handles in an outer `except`, so
clearing it before the raise is not enough (Dennis V1-3). The plan moves `raise_bare` unchanged
to the dependency-light leaf `src/decoy_engine/_error_base.py` (bottom tier of `.importlinter`,
no new root module) and makes every copy use it:

- `secret_providers/_errors.py`, `_types.py`, `_preflight.py`, and
  `verification/postmask/_route_guard.py` and `_blocked.py` import it from the new home;
- `fileaccess/_entry.py:35` `_unavailable` becomes `raise_bare(FileAccessUnavailable(message))`;
- `transforms/joint_mask.py:140` `_raise_without_chain` is deleted;
- `read_config` and every refusal raise in the nine modules use it. No `raise_refusal` is added.

A sentry cell (B3) flags a function outside `_error_base.py` that sets `__context__ = None` and
re-raises, so a new copy cannot appear. `fileaccess/_errors.py` sets `__suppress_context__` on
fresh objects it returns (`deny`, `read_error`) without a re-raise, so it is not a copy.

**`read_config` (Codex R2 V1-1, V1-3).** It is the one place where a loader turns file bytes into
Python values.

- The `read` callable covers reading AND materialization: every call that turns file content
  into Python values (`read_table`, `.as_py()`, `.to_pylist()`, `.to_pydict()`, `json.loads`,
  `yaml.safe_load`, `serial.*_load`, `CodeSetProvenance.from_parquet_metadata`) runs inside it.
  A failure while materializing (for example `UnknownTimeZoneError` from `.as_py()` on a
  timestamp column whose time zone is a file-authored string) is then a refusal, not a raw
  exception. In `_codeset_loader._read_corpus_record` the row loop at `:476` moves into the read
  callable; the schema check stays after it because it raises its own refusals.
- It catches `Exception` and lets an exception pass unchanged when any of these holds:
  `fileaccess.keeps_class(exc)` (the policy predicate, `fileaccess/_read.py:77`, which covers a
  policy decision, `FileAccessReadError`, `FileAccessUnavailable` and the memory and disk-full
  classes under a strict policy); `isinstance(exc, passes)`, the route's own explicit list, kept
  exactly as each route passes today (`load_table` passes `FileAccessDenied` and
  `FileAccessReadError`, `reference_tables/_loader.py:108`; the code-set loader passes
  `FileAccessDenied`); or `exc` is a builtin `MemoryError` (Dennis V1-4). There is no second
  hand-written list: the policy rule stays in `keeps_class`.
- From a caught exception it keeps only a position made of ints: the YAML mark's line and column
  (the `yaml_error_text` rule) or `json.JSONDecodeError.lineno` and `.colno`. An error with no
  position, such as the `!!int` `ValueError`, gives the text with no line or column (Dennis D2).
- It builds `refuse(refusal)` after the `except` block has closed and raises it with
  `raise_bare`.

`yaml_error_text` moves into `_config_text` and `safe_output` re-exports it, so the position rule
stays in one place.

### Sentry

`tests/sentry/defects/test_config_refusal_text.py` is an AST scan of `src/decoy_engine`. It reuses
the F31 tagger (`RISKY_NAMES`, `risky_in`) and `tests/sentry/_ratchet.py`. The zero set is the
nine AE5 modules, listed as a constant in the sentry.

**Refusal classes.** The roots are `PlanCompileError`, `NameHintLoaderError`,
`ModelPackLoadError`, `ProvenanceError`, `ConfigError` and `StatisticalSpecError`. The sentry finds
every subclass of a root with an AST walk of the class definitions in `src/decoy_engine`. A
per-class table in the sentry names where the message and the path are passed and which
`Refusal` field each takes:

| Class | Message argument | Path argument |
|---|---|---|
| `PlanCompileError` | third positional, or `message=`; takes `r.detail` | second positional, or `path=`; takes `r.key` |
| `PipelineValidationError` (`errors.py:39`, a `ConfigError` subclass) | first positional, or `message=`; takes `r.text` | second positional, or `path=`; takes `r.key` |
| `ConfigError`, `ConfigRuleError`, `NameHintLoaderError`, `ModelPackLoadError`, `ProvenanceError`, `StatisticalSpecError` | first positional, or `message=`; takes `r.text` | none |

A subclass with its own `__init__` and no table row is a finding, so a new signature cannot slip
past the table.

**Builder output (Codex R2 DESIGN 1).** One checked form: an expression is builder output when its
static origin is a `Refusal`. That is a name bound once in the function by
`r = config_refusal(...)`, or a parameter annotated exactly `Refusal`. Because `Refusal(...)`
outside `_config_text` is itself a finding, and mypy checks that only a `Refusal` reaches a
`Refusal` parameter, a factory such as `def _refuse(r: Refusal) -> PlanCompileError` passed as
`refuse=` to `read_config` is accepted with no special case.

- **S1 every construction (Dennis V1-2).** S1 checks every call that builds a refusal class, not
  only calls written directly after `raise`. That covers a helper that returns the exception, a
  value assigned to a name and raised later, and a call passed to `raise_bare`. The message
  argument must be a `str` constant or the table's field of builder output. The path argument
  must be the builder output's `.key`; a literal path is a finding (Codex R2 DESIGN 1, so N6 is
  caught), and `None` is allowed only for a class whose table row has no path. `raise <name>` is
  allowed, because the construction that bound the name is checked where it is built. The one
  named exemption is `_rebuild_load_error` (`profiling/model_pack/loader.py:78`), the pickle
  rebuild of a `ModelPackLoadError` from the text it already had. Any other function that builds
  a refusal from a parameter not annotated `Refusal` is a finding.
- **S2 builder arguments, everywhere S1 accepts builder output.** S2 runs on every
  `config_refusal` call that S1 accepts as a source, in or out of the zero set, so
  `config_refusal(..., hint=runtime_text).text` in a new module fails (Codex R2 DESIGN 2).
  `problem=` and `expected=` are `Problem.X` and `Expected.X` attributes; `got_kind=` is a
  `Kind.X` attribute or a call to the Arrow classifier. `choices=` is a module-level UPPER_CASE
  name. `hint=` is a `str` constant. Each `config_position` segment is a constant, an int, or a
  `Name(...)` or `Member(...)` call whose argument is a plain name, attribute or subscript: a
  `str()`, f-string, `format` or `repr` call inside `Name(...)` or `Member(...)` is a finding
  (Codex R2 V1-2), and so is an argument the tagger marks as risky.
- **S3 chaining, zero set only.** No `raise <call>` or `raise <name>` sits inside an `except`
  body, no `raise ... from` exists, and every refusal raise goes through `raise_bare`. A bare
  `raise` is allowed.
- **S4 except names, zero set only.** A name bound by `except ... as e` may appear only as the
  argument of `isinstance`, `type(e) is`, `safe_error_type` or `fileaccess.keeps_class`
  (Codex R2 V1-3; `plan/_generation.py:181` uses it today).
- **S1 for builtin errors, zero set only.** In the nine modules, the message of a builtin error
  (`ValueError`, `TypeError`, `KeyError` and the others) follows the S1 message rule.
- **S6 materialization, zero set only (Codex R2 V1-1).** A materializer call from the list under
  `read_config` may appear only inside a function or lambda passed as `read=` to `read_config`.
  The list is a constant in the sentry, and B3 seeds one case per entry.
- **S5 ratchet (Dennis V1-1).** Outside the zero set, the sentry applies S1 and S2 to the refusal
  classes only. Builtin errors, S3, S4 and S6 are not checked there. Chaining outside the zero
  set stays with the existing sentries `tests/sentry/defects/test_exception_context.py` and
  `tests/sentry/safe_output/test_exception_text_copy.py`. A site that breaks S1 or S2 needs an
  entry in `tests/sentry/baselines/config-refusal-text.json`, keyed
  `<file>::<qualname>::<digest>`. Zero-set modules may have no entries. The S1 scan covers
  every refusal construction in the tree, so a new module has no entry and fails. The earlier
  "config reader list" rule is dropped: it added nothing S1 does not already catch.
- **Occurrence counts (Codex R2 DESIGN 2).** Two identical constructions in one function share a
  key, so each entry carries `{"max": n}`, the number of constructions under that key on the
  merge base. The sentry compares the head count with `max`. The existing ratchet check
  `max_raised` (`tests/sentry/_ratchet.py:237`) refuses a raised or dropped `max`, and a lower
  head count lowers `max` in the same diff, so counts only shrink.
- **Baseline seed (Dennis V1-6).** The baseline is seeded only from the merge base: the builder
  runs the S1 and S2 scan on the merge-base sources (`git show <merge-base>:<path>`) and writes
  those findings with their counts. A site that this PR adds or changes cannot enter the
  baseline. The sentry id is not added to `REKEY_PER_SITE` (`tests/sentry/_ratchet.py:36`), so a
  changed message is new growth, not a re-key. The PR body states the seeded entry count and
  the total of all `max` values.

**Head-minus-base inventory (Codex R2 DESIGN 3).** Sites this PR already changed outside the nine
modules cannot be seeded, so they are migrated in AE5. A scan of
`git diff 9f7bb1f4a..da71c502e` (merge base to PR head) for refusal constructions with a
non-constant message on a changed line finds five:

| Site | Class | Commit |
|---|---|---|
| `generation/statistical/_snapshot_io.py:32` (`parse_snapshot_json`) | `StatisticalSpecError` | C2-snapshot: moves to `read_config`, which keeps the JSON line and column |
| `plan/_checks.py:386` (`check_statistical_columns`) | `PlanCompileError` | C2-checks |
| `plan/_checks_fpe.py:102`, `:113` | `PlanCompileError` | C2-checks |
| `plan/_serialize_declared.py:64` | `PlanCompileError` | C2-checks |

The scan matched changed lines only. In commit 1 the builder re-runs the sentry itself against
the merge-base seed and pastes the full finding list into the PR body. Each finding is assigned
to one commit before migration starts. A finding not in this table is added to it, not
baselined.

Guard mutation: put `f"... {version!r}"` back into `_codeset_config_checks.py`. S1 turns red.

## Class table

Classes from the plan contract catalog (`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes | `config_refusal`: closed problem, expected, kind and `Kind` tables; names only when `type is str` and approved; builder output is a `Refusal` built in one place | A1 to A5, A9, B1 (seeded canaries), B4 (sentry) | N1, N4, N5, N10, N17, N21 |
| 2 | cleanup on an exit path | yes, narrow: a read handle must close on a refusal | `read_config` runs inside the existing `try/finally` that closes the member | B2 cell: the handle is closed after a parse refusal | N2 |
| 3 | state and concurrency | yes, narrow: the ambient `at_position` context | `config_position` reads `position_key` once, when it is built | A5, B1 (property test runs each route inside `at_position`), B4 (S1 path rule) | N6 |
| 4 | route parity and fallback | yes: every loader entry, every policy (ambient, strict); fallback and report routes keep their outcome | one builder for all policies; the ambient display is removed; `read_config` passes what `keeps_class` and the route's `passes` keep | A2, A10, B1 per-route outcome table under both policies, B2 pass-through cells | N4, N16, N18, N19, N20 |
| 5 | referential integrity | N/A: no table data or FK shapes | | | |
| 6 | untrusted producer | yes: PyYAML constructors, `pyarrow` reads and `.as_py()` materialization, `json` exception text | `read_config` wraps read and materialization, catches `Exception` and keeps only an int line and column | A1, A6, A8, B3 (S6 cells) | N2, N3, N22 |
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
- Code-set loader materialization: `read_table` returns and the handle closes
  (`src/decoy_engine/transforms/_codeset_loader.py:455`, `:466`), then the row loop calls
  `.as_py()` (`:476`) outside any handler, so a file-authored time zone raises
  `UnknownTimeZoneError` with the zone name (Codex R2 V1-1).
- Statistical spec: `source_column` is converted with `str()` before lookup
  (`src/decoy_engine/generation/statistical/_spec.py:326`), so a list prints its items
  (Codex R2 V1-2).
- Non-raising exits that must keep their outcome: `load_with_fallback` returns `None`
  (`src/decoy_engine/profiling/model_pack/loader.py:220`), `read_pinned_artifact` returns a
  `PinnedRead` (`src/decoy_engine/plan/_generation.py:161`), `verify_corpus` returns a report
  (`src/decoy_engine/transforms/_codeset_loader.py:622`).
- Reference tables, model pack, DP provenance, statistical spec, code-set loader: their refusal
  raises, each counted by the sentry on the final head.

### Routes

Public entry points that reach the nine modules:

- `load_name_hint_terms` (`src/decoy_engine/detection/name_hints/loader.py:58`);
- `CodeSetConfig.from_dict` through `validate_code_set_config`
  (`src/decoy_engine/transforms/_codeset_config_checks.py:30`), `load_corpus` and
  `load_corpus_provenance` (`src/decoy_engine/transforms/_codeset_loader.py:140`, `:172`) and
  `verify_corpus` (`:622`);
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
  corpus names and URLs, version pins, manifest fields, recorded DP versions, Parquet column
  types (a timestamp time zone), and a name field given a non-string value (a list, a mapping).
- Non-exception surfaces a caller receives: the `load_with_fallback` warning record, the
  `PinnedRead` fields (`cause_type`, `oversize`), and the `CorpusVerifyReport.problems` strings.

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
- `is_text` (`src/decoy_engine/_arrow_types.py:21`) for the `_TYPE_KINDS` string row, and the
  existing `_TYPE_KINDS` classifier itself, retargeted to `Kind` members.
- `raise_bare` (`src/decoy_engine/secret_providers/_errors.py:44`), moved to `_error_base.py`
  and used by every copy.
- `fileaccess.keeps_class` (`src/decoy_engine/fileaccess/_read.py:77`) as the one pass-through
  policy in `read_config`.
- The ratchet's per-entry `max` and `max_raised` (`tests/sentry/_ratchet.py:237`) for occurrence
  counts.
- F31 tagger `tests/sentry/safe_output` and `tests/sentry/_ratchet.py` for the sentry.
- `scripts/dev/sentry_registry.toml` and `tests/sentry/test_baseline_registry.py` for the new
  baseline.

## Frozen contracts touched

None. Error classes, reason codes and public names stay the same. `path` keys are now always
`Refusal.key`. Outside `at_position` that is the same string as the old literal; inside
`at_position` it carries the bound table and column, as the joint-mask missing `reference` now
does like its two sibling refusals. `raise_bare` moves between private modules; it has no public
name. `_TYPE_KINDS` is private. Message text is not a frozen contract. The ambient CLI no longer prints the
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
| corpus Parquet with a timestamp column whose time zone is unknown | `UnknownTimeZoneError` with the zone name from `load_corpus`; `verify_corpus` raises it too | `load_corpus`: `PlanCompileError` `CODE_SET_CORPUS_READ_ERROR`, no zone name; `verify_corpus`: `ok=False` with that code in `problems` |
| statistical `source_column` given a list | `StatisticalSpecError` printing the list items | `StatisticalSpecError`: `<position>.source_column: wrong type; expected a string, got list` |
| `MemoryError` while reading under the ambient policy | translated to a read or parse refusal | passes unchanged (Dennis V1-4); under a strict policy `keeps_class` already passed it |
| snapshot JSON decode error | text holds the decoder message | text holds only the int line and column |

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
   `exc.path == "tables.orders.columns.zip.joint_masks.reference"` exactly, and
   `exc.message == "missing; expected <expected phrase>"` exactly (the `detail`, with no position
   prefix). A separate assertion pins the stock render:
   `str(exc) == "[<code>] tables.orders.columns.zip.joint_masks.reference: <message>"`, so the
   path is printed once (Codex R2 DESIGN 1).
6. A6 `test_loader_refusals_have_no_chain`: YAML syntax error, scalar conversion error, unreadable
   member, missing reference file. Each refusal has `__cause__` and `__context__` None and
   `__suppress_context__` True (the R3 V2-LOG item, now in scope because S3 covers it). Outer
   except cell (Dennis V1-3): each loader is called inside
   `try: raise RuntimeError("OUTERCANARY") except RuntimeError: <call loader>`, and the refusal
   still has `__context__` None, so no outer exception text reaches a traceback.
7. A7 `test_reference_type_kinds_use_is_text`: the string row of `_TYPE_KINDS` is
   `_arrow_types.is_text` itself, in `tests/unit/reference_tables/`. Second cell (Codex R2
   DESIGN 4): every `_TYPE_KINDS` row maps to a `Kind` member, and the kept regression
   `test_reference_id_type_names_the_kind_not_the_timezone` gets `timestamp` through
   `got_kind`, with no zone name.
8. The test file move: the moved file finds the source tree with
   `Path(decoy_engine.__file__).parent`, not `Path(__file__).parents[2]`
   (`tests/unit/test_f31_ae5_loader_text.py:189`), so its text-mask guard scans the engine
   package wherever the test file lives. A cell asserts the scanned directory holds
   `_config_text/__init__.py`, so a wrong root fails instead of scanning nothing.

Codex R2 repros, red on `da71c502e`:

9. A8 `test_corpus_materialization_is_value_free`: a corpus Parquet with a valid `code` column
   and a timestamp column whose time zone is `PRIVATE_ZONE_CANARY`. `load_corpus` raises
   `PlanCompileError` with code `CODE_SET_CORPUS_READ_ERROR` and no canary in any surface;
   `verify_corpus` returns `ok=False` with that code in `problems` and no canary. Both are
   public calls.
10. A9 `test_list_valued_name_is_not_shown`: `load_spec` with
    `source_column=["PRIVATE_RELEASE"]` raises `StatisticalSpecError` with
    `STATISTICAL_...` wrong-type text, `got list`, and no `PRIVATE_RELEASE`. A cell asserts
    `approve_name(str(["PRIVATE_RELEASE"]))` accepts the converted string, which proves the
    test depends on the type check and not on approval. A valid string `source_column` is still
    shown.
11. A10 `test_read_failures_keep_their_route`: under a strict policy, through real loaders:
    `load_table` with a `FileAccessReadError` from the read passes it unchanged; `load_table` and
    `read_pinned_artifact` with an `OSError(ENOSPC)` pass it unchanged (`keeps_class`); the same
    `ENOSPC` under the ambient policy gives the route's refusal or `PinnedRead`, as today.

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

12. B1 `test_every_loader_outcome_is_value_free` (Hypothesis): for each route in Routes, under
   both policies, plant a canary in each supplied slot listed under Fields. Each route has its
   own expected outcome, from one table in the test (Codex R2 V1-4):

   | Route | Expected outcome | Surface checked |
   |---|---|---|
   | raising loaders | the named refusal class and the exact reason code for the planted slot | `str`, `repr`, `args`, `str` attributes, `path`, chain |
   | `load_with_fallback` | returns `None` | the captured warning record (message and args) |
   | `read_pinned_artifact` | returns `PinnedRead` with `cause_type` or `oversize` set | every `PinnedRead` field |
   | `verify_corpus` | returns `ok=False` | every `problems` string |

   Non-vacuity check: each case first asserts the expected outcome, class and code, so an
   earlier unrelated refusal cannot satisfy the canary check. The slots split in two
   (Dennis V1-5):
   - Value slots (field values, pins, URLs, file contents): the canary is never shown. Assert it
     is absent from `str`, `repr`, `args`, every `str` attribute and `path`, and that the chain
     is empty.
   - Name slots (`Name(...)` and `Member(...)` segments): the canary is shaped so that
     `approve_name` refuses it (a path, a URL, or longer than the name limit). The case asserts
     `approve_name(canary)` refuses it, then asserts the canary is absent from the same surfaces
     and that `<name>` or the bare file name is shown in its place. An approved name may appear
     and is not a canary. A third kind of name canary is a non-string value (a list or a mapping
     holding the canary), which must show as `<name>` with `got list` or `got dict`.
13. B2 `tests/unit/config_text/test_config_refusal.py`. Cells:
    - the kind table, with `bool` before `int` and a `str` subclass shown as `other`;
    - `Name` with a URL, a path and a 200-character value, each shown as `<name>`;
    - `Member` with `../x` and `/etc/x`, each shown as the bare name;
    - refused choices are dropped;
    - `at_position` binding;
    - `read_config` with a `ValueError`, an `OSError` and a `yaml.YAMLError`, checking the text,
      that the chain is None and that the handle is closed;
    - `read_config` pass-through, each asserting the same object comes out (`is`): under a
      strict policy, every class `keeps_class` keeps (`FileAccessDenied`,
      `FileAccessReadError`, `FileAccessUnavailable`, `OSError(ENOSPC)`); under both policies,
      a class in the route's `passes` and a builtin `MemoryError` (Dennis V1-4); under the
      ambient policy, `OSError(ENOSPC)` becomes a refusal, as today;
    - `read_config` with a `json.JSONDecodeError` keeps only `lineno` and `colno`;
    - `read_config` with a `read` that fails while materializing (an `.as_py()` error) gives a
      refusal with no exception text;
    - `got` and `got_kind` together is a `TypeError`; `got_kind=Kind.TIMESTAMP` renders
      `timestamp`;
    - `Name(["x"])` and `Name({"x": 1})` show `<name>`; a `str` subclass shows `<name>`;
    - `PlanCompileError` built from `r.detail` and `r.key` renders the position once;
    - `raise_bare` (now in `_error_base.py`) clears `__cause__` and `__context__`, sets
      `__suppress_context__` and drops the old traceback, also when called inside an outer
      `except`. The existing `secret_providers` and postmask tests that cover it stay green.
14. B3 sentry self-test: S1 to S6 run on seeded source snippets. Each snippet must be flagged:
    - an f-string message;
    - `!r`;
    - `str(exc)`;
    - a raise inside `except`;
    - `from exc`;
    - a non-literal `path=`, and a literal `path=` (Codex R2 DESIGN 1);
    - a non-constant `choices=`;
    - a risky segment;
    - `Name(str(v))`, `Name(f"{v}")` and `Member(repr(v))` (Codex R2 V1-2);
    - `config_refusal(..., hint=runtime_text).text` in a module outside the zero set
      (Codex R2 DESIGN 2);
    - `Refusal("x", "x", "x")` outside `_config_text`;
    - a function outside `_error_base.py` that sets `__context__ = None` and re-raises;
    - in a zero-set snippet, one case per materializer in the S6 list called outside a
      `read=` callable (`.as_py()` in a row loop after `read_config` returns, among them).

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
    `raise_bare(err)`; the factory form `def _refuse(r: Refusal) -> PlanCompileError: return
    PlanCompileError(CODE, r.key, r.detail)` passed as `refuse=` to `read_config` (Codex R2
    DESIGN 1); `except OSError as e: if fileaccess.keeps_class(e): raise` (S4); `.as_py()` inside
    a lambda passed as `read=`; `_rebuild_load_error` in its real module; the same body under any
    other name is flagged; a refusal built inside an `except` outside the zero set (S3 and S4 do
    not apply there).
15. B4 `test_config_refusal_text` on the real tree: zero findings in the zero set, and the
    baseline holds under `_ratchet.check`. Merge-base cell (Dennis V1-6):
    `test_config_refusal_baseline_is_from_the_merge_base` runs the S1 and S2 scan on the
    merge-base sources and asserts every baseline entry's `<file>::<qualname>::<digest>` is in
    that set and its `max` equals the merge-base occurrence count or less. It also asserts the
    sentry id is not in `REKEY_PER_SITE`. When no merge base is reachable (a shallow clone), the
    cell fails, not skips. Count cell (Codex R2 DESIGN 2): a seeded tree that duplicates one
    baselined construction in the same function fails with the head count above `max`.
16. B5: the existing `test_dp_provenance_imports_neither_pandas_nor_pyarrow` stays green, which
    proves `_config_text` pulls no pyarrow.
17. B6: the existing import-layer snapshot (`tests/sentry/layout/test_import_layers.py`) is
    updated for `_config_text` and the `raise_bare` move and stays green.

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
| N8 | drop one materializer from the S6 list (Codex R2 DESIGN 2: the old reader-list mutation could not fail, since S1 already caught its case) | B3 (that materializer's S6 cell) |
| N9 | add a baseline entry for a zero-set module | B4 |
| N10 | `Name` skips `approve_name` | A4, B1, B2 |
| N11 | the `_TYPE_KINDS` string row uses its own checks again | A7 |
| N12 | S1 checks only calls written directly after `raise` (Dennis D4) | B3 (helper return, assign-then-raise cells) |
| N13 | S1 reads the first positional argument of `PlanCompileError` as the message (Dennis D4) | B3 (third positional cell) |
| N14 | `raise_bare` clears `__cause__` but not `__context__` (Dennis D4) | A6 (outer except cell), B2 |
| N15 | seed one baseline entry from the head instead of the merge base (Dennis D4) | B4 (merge-base cell) |
| N16 | `read_config` catches `FileAccessDenied` and turns it into a refusal (Dennis V1-4) | B2 (pass-through cell) |
| N17 | restore `str(col_cfg.get("source_column") or name)` before the lookup in `_spec.py` (Codex R2 V1-2) | A9, B1 (non-string name slot), B3 (`Name(str(v))` cell) |
| N18 | drop `keeps_class` from `read_config`'s pass-through test (Codex R2 V1-3) | A10 (`ENOSPC` and `FileAccessReadError` cells), B2 |
| N19 | `load_with_fallback` re-raises instead of returning `None` (Codex R2 V1-4) | B1 (fallback row) |
| N20 | `verify_corpus` lets the refusal propagate instead of returning a report (Codex R2 V1-4) | A8, B1 (report row) |
| N21 | S2 runs only inside the zero set (Codex R2 DESIGN 2) | B3 (runtime `hint=` outside the zero set) |
| N22 | move the `.as_py()` row loop out of the `read=` callable in `_codeset_loader.py` (Codex R2 V1-1) | A8, B4 (S6) |
| N23 | the sentry compares keys only, not counts (Codex R2 DESIGN 2) | B4 (count cell) |
| N24 | `_TYPE_KINDS` returns plain strings again and the reference loader passes `got=` (Codex R2 DESIGN 4) | A7 (second cell) |
| N25 | restore the local `_unavailable` copy in `fileaccess/_entry.py` (Codex R2 DESIGN 5) | B3 (raise-bare copy cell) |
| N26 | `PlanCompileError` takes `r.text` instead of `r.detail` | A5 (stock render cell), B2 |

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

`raise_bare` adds no file: it moves into the existing leaf `src/decoy_engine/_error_base.py`
(35 lines, standard library only, bottom tier of `.importlinter`), so `fileaccess`,
`secret_providers`, postmask and `_config_text` can import it without a cycle.

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
- Head-minus-base inventory (Codex R2 DESIGN 2). Sites added since merge base `9f7bb1f4a` that
  the merge-base baseline does not hold, each fixed in the zero set's commits, not baselined:
  `generation/statistical/_snapshot_io.py:32` (commit C2-snapshot); `plan/_checks.py:386`,
  `plan/_checks_fpe.py:102` and `:113`, `plan/_serialize_declared.py:64` (commit C2-checks). The PR body lists this
  inventory with the baseline entry count and the sum of `max` values.

The builder reports the measured size against these numbers before review.

## Slices

1. AE5 (this PR, #810, decoy-engine, `feat/f31-ae5`): `_config_text`, the sentry with the zero set
   and the baseline, the nine modules migrated, the R3 fixes and the test move. Size above.
2. AE5b (new, decoy-engine, `feat/f31-ae5b`): migrate the baselined sites (about 160) to
   `config_refusal` and shrink the baseline to zero. Separate PR, R2, after AE5 merges. Tracked
   in the F31 audit plan slice table (`docs/plans/2026-11-24-f31-audit.md`) and in the vault
   `BRANCH-LIST.md` (Dennis D3). Exit criterion: the baseline has zero entries.

Commit order inside AE5 (Dennis D5):

1. `raise_bare` moved to `_error_base.py`, with every copy switched to it (`fileaccess`
   `_entry._unavailable`, `joint_mask._raise_without_chain` deleted, `secret_providers`,
   postmask `_route_guard` and `_blocked`), and the import-layer snapshot.
2. `_config_text` (builder, enums, `Kind`, `read_config`) with its B2 tests, and the sentry with
   the merge-base baseline and counts. The zero set is red at this commit, and that is expected.
3. C2-snapshot and C2-checks: the head-minus-base sites in Size.
4. One commit per zero-set module, each turning that module green in the sentry. Each
   regression test (A1 to A10) and each snapshot update lands in the same commit as its fix.
   The builder first runs it on `da71c502e` and records the red result in the PR body.
5. The test move.

The PR body states the seeded baseline entry count and `max` total (Dennis V1-6). Mutations N1
to N26 run on the final recorded HEAD, and the PR body records that SHA.

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
8. A value leaks after the read, while materializing rows (`.as_py()`, `to_pylist`): S6, A8.
9. A non-string name is converted with `str()` and then approved: the `type is str` check, S2,
   A9.
10. A non-raising route returns a value that holds the canary: B1 per-route table.
11. A baselined site gains a second copy in the same function: B4 count cell.

## Docs and changelog

- The `_config_text` module docstring states the rule and cites the Pydantic pattern.
- The CODEMAP gets the new row.
- The CHANGELOG line says config loader errors name the field and expected type, not the
  supplied value or the file path.

## V2-LOG

- Hostile objects passed through the Python API whose `__eq__` or `__hash__` run during
  validation (V2 threat model).
- About 160 non-loader refusal sites until AE5b lands, held by the shrink-only baseline.
- No red runs on `da71c502e` and no mutation results are recorded in this plan yet (Codex R2
  V2-LOG). The builder records them in the PR body, with the HEAD each ran on. The JSON
  position item from Dennis R1 is closed: `read_config` keeps `lineno` and `colno` (B2).
