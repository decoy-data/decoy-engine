Status: plan (revision 2, 2026-11-22; Dennis round 1 applied)

# FIT-CODES-TEXT: `decoy fit` keeps zero-padded codes as text and generates them as digit strings

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: FIT-CODES-TEXT (group generate, 1.0), added by the owner on 2026-11-22 from the V2-to-V1 evaluation (vault `10_Projects/decoy/V2-TO-V1-EVALUATION-2026-11-22.md`, rank 3; backlog entry M4). One slice, landed as two PRs: engine first, then the CLI with the engine pin bump.

Anchors: a path with no prefix is in this repository (decoy-engine); `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3) and CLI `origin/main` `088bab88` (pins `decoy-engine==0.28.3`). Line numbers are at those heads.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `risk-and-exceptions.md`, `bugfix.md`, `feature-dev.md`, `api-and-compatibility.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `cross-cutting-concerns.md`, `security.md` (value-free snapshot members), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md`; CLI `CODEMAP.md` ("Where Things Go").

Risk: R2 (changes the output of `decoy fit` and adds a member to the `distribution-snapshot/v1` and `/v2` cell-format block, a frozen surface). Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

Evidence: CLI record `docs/records/2026-11-10-cli-qa-generation-distribution-models.md` (M4). A five-digit zero-padded ZIP column was fitted as numeric; 10.9% of generated values were shorter than five characters on the re-test (10.4% through a cell-format snapshot).

Inference site: `CLI:src/decoy/cli/gen/_fit.py:172`. The final read is `pd.read_csv(read_target, parse_dates=..., index_col=False)` with pandas type inference, so `02134` becomes the integer `2134` before the engine sees it. The engine's `_stats_for` (`src/decoy_engine/quality/snapshot.py:279`) then gives the column kind `numeric`, and the leading zeros are gone for good. Both `decoy fit` and `decoy init <csv> --preset generate` (`CLI:src/decoy/cli/gen/_scaffold.py:221`) go through this read. DP mode already reads every column as literal text (`CLI:src/decoy/cli/fit.py:577`), so it is not affected.

A second problem appears once the column is kept as text. A text column with more than 30 distinct values gets kind `freetext` (`src/decoy_engine/quality/snapshot.py:301`), and the sampler fills it with lorem words cut to the fitted length (`src/decoy_engine/generation/statistical/_sample.py:492`). So a text-only fix would turn ZIPs into strings like `lorem`. The fix needs an engine half so that a digit-only text column is generated as digit strings.

## 2. Established solutions

Search run: how CSV readers and synthetic-data tools treat numeric-looking codes (readr, pandas, DuckDB sniffer, SDV metadata and RDT, Faker); how SDV models id-like text columns.

- **Inference rule: readr.** readr's type guesser treats a number with a leading zero as text: "Numbers with leading zeros now default to being parsed as text, rather than as integers/doubles" (readr 0.2.2 NEWS, issue #266; `guess_parser`). The rule is per column: a column is a number only if every value parses as one, and a value with a leading zero does not. This plan follows it: a CSV column is kept as text when any non-null cell matches `^[+-]?0[0-9]` (a zero followed by another digit). `0`, `0.5` and `-0.25` stay numbers.
- pandas has no such rule; its documented answer is `dtype=str` per column, which is how the fix applies the rule (`read_csv(dtype={col: str})`).
- **Generation: SDV id columns.** SDV models an id-like text column as `sdtype: id` with a `regex_format` such as `[0-9]{5}` and generates matching strings (SDV metadata docs; RDT `RegexGenerator`). Faker does the same with `numerify("#####")`. This plan follows that pattern in the value-free form the engine's `cell_format` block already uses: a freetext column whose non-blank cells are all ASCII digits records `char_class: "digits"`, and the sampler draws digits at the fitted lengths in place of lorem words.
- **ASCII only.** Both tests use the explicit class `[0-9]`, never `\d` or `str.isdigit()`: Python's `\d` and `isdigit()` accept every Unicode decimal digit (`٣`, `５`) and `isdigit()` also accepts `²`. The engine test is `re.fullmatch("[0-9]+", cell)` (whole cell, so a trailing newline fails); the CLI rule is `re.match("[+-]?0[0-9]", cell)`.
- No custom parser: the rule is one regex over cells already read as text, and the sampler change reuses the existing length histogram and per-row seeding.

### Reuse inventory

- `CLI:src/decoy/cli/gen/_fit.py:44` `read_fit_csv`: the one CSV read of the fit path; the rule changes its arguments only.
- `src/decoy_engine/profiling/cell_format.py:68` `CELL_FORMAT_MEMBERS`: the one descriptor of allowed members per kind. The writer, the default-deny `scrub_cell_format` (`src/decoy_engine/profiling/cell_format.py:83`) and the strict decoder all read it, so one new entry reaches all three.
- `src/decoy_engine/profiling/cell_format.py:137` `learn_cell_format`: already learns `blank_count` for freetext.
- `src/decoy_engine/generation/statistical/_sample.py:184` `freetext_tables` and the per-row reseed: reused for the digit draw.

## 3. Guarantee and non-goals

After this slice:

1. `decoy fit` and `decoy init <csv> --preset generate` read a CSV column as text when any non-null cell starts with `0` followed by a digit, optionally after a sign (readr #266). The snapshot `dtype` of that column is the text dtype, not `int64` or `float64`. A column named in `--parse-dates` is not touched by the rule.
2. The engine writes `cell_format.char_class: "digits"` for a `freetext` column whose non-blank cells all pass `re.fullmatch("[0-9]+", cell)` (ASCII `0` to `9` only), and only then. A Unicode digit such as `٣` or `５`, or a superscript `²`, keeps the column without the member.
3. A `freetext` column with `char_class: "digits"` generates strings of ASCII digits only, with lengths from the fitted length histogram. A fitted column whose cells all have five digits generates five-digit strings only, leading zeros included.
4. A `categorical` code column (30 or fewer distinct values) keeps its exact labels, leading zeros included, as it does for any text column today.
5. The new member holds no source value: it is one fixed enum token. The redacted fit writes it for flagged columns as it writes `blank_count`.
6. A snapshot without `char_class` generates exactly as today, byte for byte.
7. Snapshot tags: `add_cell_format` has two callers, so both tags gain the member. `distribution-snapshot/v1` gets it from the raw writer and `--include-values` (`src/decoy_engine/quality/snapshot.py:216`); `distribution-snapshot/v2` gets it from the plain redacted writer's freetext path (`src/decoy_engine/profiling/_snapshot_values.py:449`). Readers: this engine and later accept the member under v1 and v2. An older engine refuses a snapshot that holds it with `statistical_cell_format_invalid` (its strict decoder refuses unknown members, `src/decoy_engine/generation/statistical/_cell_format.py:94`). It never misreads it.

Non-goals: keeping the numeric distribution of codes (for example ZIP regions); keeping uniqueness of an id-like code column (digits are drawn per row, so a fitted unique column can generate duplicates, the same as the lorem and numeric paths today; unique ids stay with the `unique:` generate path); other code shapes (`12345-6789`, letters and digits); M3 date shape and M5 fidelity inference (separate standby rows); DP mode (already reads text); type inference in `decoy scan`, the profiler or engine CSV reading (the engine CSV reader is all-text); a user flag to choose types per column (`--parse-dates` stays the only type flag).

## 4. Enumerations

### Exit paths

- A cell-format decode with `char_class` on a kind other than `freetext`, or a value other than `"digits"`: `StatisticalSpecError(statistical_cell_format_invalid)` through `_check_members` (`src/decoy_engine/generation/statistical/_cell_format.py:94`).
- The CLI read keeps its existing `could not read ... as a CSV` refusal (`CLI:src/decoy/cli/gen/_fit.py:106`) for both reads.

### Routes

- Exact fit, whole file: `CLI:src/decoy/cli/gen/_fit.py:172` reads the file. Taken only when the record count is at most `row_limit` (`CLI:src/decoy/cli/gen/_fit.py:128`).
- Exact fit, sampled file: the same read over the sampled records (`CLI:src/decoy/cli/gen/_fit.py:168`).
- `decoy init --preset generate`: the same function (`CLI:src/decoy/cli/gen/_scaffold.py:221`).
- Generation from a snapshot: in-memory and pinned plan routes both decode through `load_spec` and sample through `sample_column`.

### FK shapes

N/A: statistical columns have no FK; `condition_on` and joints are not changed.

### Fields

- Snapshot column entry `dtype` and `kind` for a code column.
- New `cell_format.char_class` on `freetext`.

### Output surfaces

- The snapshot JSON written by `decoy fit` (value-free when redacted).
- Generated rows of a statistical column.

## 5. Slices and size

One slice, two PRs.

- **Engine PR.** `profiling/cell_format.py` (one descriptor entry plus about 5 lines in `learn_cell_format`), `generation/statistical/_cell_format.py` (one field on `CellFormat` plus decode, about 6 lines), `generation/statistical/_sample.py` (a digit branch beside `_lorem_text`, about 12 lines; file is 513 lines, under the 600 aim). Tests, a changelog fragment, the snapshot reference doc. New public names: none. New snapshot member: `char_class`.
- **CLI PR.** `src/decoy/cli/gen/_fit.py` (one private helper `_code_columns(text_frame)` and a `dtype=` argument on the typed read, about 20 lines; the file is 208 lines). Both parses (text, to apply the rule; then typed, with `dtype={code columns: str}`) run on one in-memory copy of the file text, as the sampled route already does with its `StringIO`, so the rule and the typed frame see the same bytes. Memory: on the whole-file route this adds one copy of the file text to the peak (today pandas reads the path directly). The rule pass reads that copy with `dtype=str` in `_COUNT_CHUNK` chunks and keeps one flag per column, so it adds one chunk, not a second full frame. The whole-file route is only taken at or under `row_limit` records, so the extra copy is bounded by that limit; the sampled route already holds its `StringIO` and adds nothing. Tests, CHANGELOG, the engine pin bump to the release that holds the engine PR (follow the engine repin checklist). New public names: none.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_cell_format_char_class.py` | `tests/unit/generation/statistical/` | engine "Generation": the existing `statistical/` test subpackage (the flat `tests/unit/generation/` has 40 direct files) | existing cell-format tests |
| `test_fit_code_columns.py` | `CLI:tests/e2e/first_user/` | CLI "Generation CLI helpers": tests in `tests/e2e/first_user/` | `test_fit_rows.py` |

No new source files. The rule has one site (the fit read), so it gets no registry or sentry (cross-cutting rule: no registry for a rule with one site).

## 7. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the new member in a redacted snapshot | one enum token, accepted only through `CELL_FORMAT_MEMBERS`; scrub nulls anything else | E4 | let the member accept any string (E4 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no file is opened or staged beyond the existing read | n/a | n/a |
| 3 | State and concurrency | none | N/A: pure functions and per-row reseed | n/a | n/a |
| 4 | Route parity and silent fallback | whole-file and sampled fit; `init --preset generate`; in-memory and pinned generation | one read function; one decoder used by `load_spec` and `sample_column` | C1, C2, C3, E3 | apply the rule only on the whole-file route (C2 red) |
| 5 | Referential integrity | none | N/A: no keys | n/a | n/a |
| 6 | Untrusted producer | a hand-edited snapshot | strict decoder: `char_class` only on freetext, only `"digits"` | E5 | accept `char_class` on numeric (E5 red) |
| 7 | Check then use (TOCTOU) | the CSV read | the rule reads the same text the typed frame is parsed from | C2 | decide on a second disk read (a changed-file test goes red) |
| 8 | Weak tests | length-only checks would pass lorem text; `isdigit` would pass Unicode digits | assert every generated value matches `^[0-9]{5}$`, not only its length; E1 has Unicode-digit negatives | C1, E2, E1 | draw letters in the digit branch (E2 red); learn with `str.isdigit()` (E1 red) |
| 9 | Refactor drift | snapshots without the member | absent member means the lorem path, byte for byte | E6 | always draw digits (E6 red) |
| 10 | Frozen contract drift | `distribution-snapshot/v1` and `/v2` cell-format block; fit output | optional member on both tags; old snapshots unchanged; compatibility-contract entry names the tags and the old-reader refusal | E6, E7, compat corpus | write `char_class` on every freetext column (E1 negative case red) |

## 8. Acceptance tests (each fails before the change, except E6, an unchanged-behavior control that passes before and after)

Engine:

- **E1 learn.** A freetext series of 200 distinct five-digit strings (some with leading zeros) gives `cell_format == {"blank_count": 0, "char_class": "digits"}`. A freetext series with one cell `"12a45"`, or one cell `" 1234"`, gives no `char_class`. Unicode negatives: a series of five-character strings with one cell of Arabic-Indic digits (`٠٢١٣٤`), one of full-width digits (`０２１３４`) and one `12²45` gives no `char_class`. Fail-before: the member does not exist.
- **E2 sample.** A spec with `char_class: "digits"` and lengths all 5 gives 2,000 values that all match `^[0-9]{5}$`, and at least one starts with `0`. Fail-before: lorem text.
- **E3 routes.** The same holds through the pinned-plan route.
- **E4 redacted.** A flagged column in `distribution_snapshot_document` (no `--include-values`) carries `char_class: "digits"` and no cell value; a hand-edited block with `char_class: "02134"` is scrubbed to `None`.
- **E5 strict decode.** `char_class` on a `numeric` entry, or any value other than `"digits"`, raises `statistical_cell_format_invalid`; the message names the member, not the value.
- **E6 unchanged.** A snapshot without `char_class` generates the same bytes as before (existing freetext golden tests pass unchanged).
- **E7 both tags.** `compute_distribution_snapshot(..., cell_format=True)` (v1) and `distribution_snapshot_document(..., include_values=False)` (v2) both write the member for the E1 series, and `load_spec` accepts each. Fail-before: the member does not exist.

CLI (against the engine release that holds the engine PR):

- **C1 the M4 case.** Mode: plain `decoy fit` (redacted, `distribution-snapshot/v2`), and again with `--include-values` (v1). The QA fixture `zip` column (zero-padded five digits, 2,000 rows, not PII-flagged) gives `dtype` text and kind `freetext` with `char_class: "digits"`. Generating 20,000 rows gives 0% values shorter than 5 characters and 100% matching `^[0-9]{5}$`. Fail-before: kind `numeric`, about 10% short.
- **C1b PII-flagged zip.** Mode: plain `decoy fit`. A column named `zip_code` that the pre-scan flags as a postal code: the snapshot lists it in `redacted_columns`, its entry holds `char_class: "digits"` and no cell value, and every generated value is ASCII digits only. Fail-before: kind `numeric` and short values.
- **C2 sampled route.** The same file with the row limit set below its size gives the same kind and `dtype`.
- **C3 init.** `decoy init zips.csv --preset generate` writes a snapshot with the same column entry as `decoy fit`.
- **C4 rule edges.** Columns of `0`, `0.5`, `-0.25`, `10`, `100` stay numeric; a column with one `007` among numbers becomes text; a column with `-01` becomes text; a `--parse-dates` column with `01/02/2024` is still a date.
- **C5 small code sets.** Mode: plain `decoy fit` (v2, unflagged column, each label held by at least 10 rows) and `--include-values` (v1). A column of `001` to `020` becomes categorical with labels `001` to `020`. Fail-before: numeric 1 to 20.

## 9. Frozen contracts and compatibility

- `distribution-snapshot/v1` and `/v2`: one new optional member, `cell_format.char_class`, allowed on `freetext` only, value `"digits"` only. No new tag is minted. Old snapshots read and generate as before (E6).
- Old readers do not ignore it: the strict decoder refuses unknown members, so an engine older than this change refuses a new snapshot that holds the member with `statistical_cell_format_invalid`. The contract rule for additive fields (`docs/compatibility-contract.md:500`) assumes old readers ignore a new field, so this is a recorded exception. Minting v3 was considered and rejected: the old reader fails closed with a coded refusal rather than generating wrong data, nothing is frozen before 1.0, and a v3 would split every reader for one member. The engine changelog fragment has a `Breaking:` line.
- `docs/compatibility-contract.md` gets an entry beside the `distribution-snapshot/v2` paragraph (`docs/compatibility-contract.md:469`): the member, the two tags that carry it, the two writers, the reader behavior of this engine and of older engines, and that `scrub_cell_format` nulls any value other than `"digits"`.
- After 1.0 the member and its single value are frozen; a new value (for example letters and digits) is additive in 1.x and needs the same old-reader note.
- `decoy fit` output: code columns change from `numeric` to text kinds. This is the intended change, made now while nothing is frozen. The CLI CHANGELOG says so in plain words. Existing snapshot files are not rewritten; a user refits to get the fix.
- `decoy run` generate configs that point a statistical column at a refitted code column now get text values in place of numbers. A `formula` that read that column as a number would see text; the CHANGELOG names this.

## 10. Pre-mortem

- An account-number column of fixed width and no leading zeros stays numeric, as today. Accepted: the rule follows readr and does not guess from width.
- A file where only a sampled-out row has a leading zero: the sampled fit sees only its sample, so the column can stay numeric. Same as every other sampled fact; documented.
- A redacted categorical code column has its labels withheld today and still does after this change; out of scope.
- Digit strings drawn uniformly lose the source's digit distribution (for example ZIP regions). Accepted for V1; a numeric code with a pad width is a possible 1.x addition.
- Uniform draws do not keep id uniqueness: 20,000 draws over 100,000 five-digit values give many repeats. Same as the numeric and lorem paths today; a user who needs unique codes uses the `unique:` generate path.
- A user generates from a new snapshot with an older engine (for example a pinned CI image). It refuses with `statistical_cell_format_invalid`; the CHANGELOG tells the user to upgrade the engine or refit with the old CLI.

## 11. Open questions for the owner

None. The rule source (readr #266) and the generation form (SDV id with a digit regex) are both established; the only judgment call, generating digits in place of lorem words for a digit-only freetext column, is required for the fix to work at all.
