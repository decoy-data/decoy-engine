Status: plan

# ENGINE-EXPORT-REMOTE-PATH: no remote locator in a default library export

Row ENGINE-EXPORT-REMOTE-PATH, slice E1. Risk R2 (a credential and token leak in a written
artifact). Base: engine `origin/main` `550791eff`. Author: Architect, 2026-11-28.
Source of the acceptance criteria: CLI plan `docs/plans/2026-11-28-d6-manifest-display-boundary.md`
(worktree `wt-prop-shims-d6m`), section 8, with its rows 6, 36, 37, 51, 52 and 57 to 60.

Rules consulted: README (routing table), 00-universal, risk-and-exceptions, development-loop
(PLAN phase), profiles/local-operations, cross-cutting-concerns, security,
catalogs/recurring-defects (all 11 classes); engine CLAUDE.md (established methodology, 600/700
module rule, library does not know its callers) and CODEMAP.md ("Where things go", line 305 for
`_config_text`, line 25 for `records/`).

## 1. Problem

`decoy_engine.records.export_lines` without `keep_paths` promises "a record carries no raw path or
locator". It breaks that promise for remote values in three ways (code on `550791eff`):

1. `_export_rules.py:23` `file_name` keeps the last path segment. It runs before anything asks
   whether the value is a URL, so `https://h/hook/<token>` exports as `<token>` and
   `//id.example/callback?access_token=<token>` exports as `callback?access_token=<token>`.
   The same function reduces `labels.pipeline` (`_export.py:213`).
2. Only the path pointers are touched. Dict keys (`input_fingerprints`, `output_fingerprints`,
   `row_counts`) and other kept strings (`strategies[].table`, `timings[].column`, `key_label`)
   leave unchanged, so `https://u:<password>@h/x` as a table key is copied as is.
3. `_kinds.py:144` keeps a structured warning's `column` (it only empties `detail`), so a column
   named `https://u:<password>@h/x` is copied as is.

The engine has one more URL check, and it is too narrow: `_config_text/_refusal.py:155` `_is_url`
looks only for `://` or a leading `//`, so `Member("https:/h/hook/<token>").shown()` gives
`<token>` in a config refusal. Same class of leak, same missing rule.

### 1.1 Reuse inventory

Reused: `KindSpec.path_fields` and `pointer_rule` (which fields are paths), `_evidence_scrub`
(warning detail and layout), `_strip` and `export_lines` (digest, id and link rewriting, the
`unstripped` and `withheld_records` header fields), `urllib.parse.urlsplit` and `unquote`, and the
CLI plan's start rules S1 and S2. Searched and not reused: `fileaccess.position_key` (joins a config position, no URL logic);
`_config_text.passthrough` (classifies memory and disk failures); the `urlsplit` uses in
`config/_sources.py`, `config/_targets.py` and `secret_providers/_types.py` (they parse and
refuse config input, they do not display it). `reasons.approve_name` refuses `://` but not a
collapsed `scheme:/` or an encoded form.

## 2. Guarantee and non-goals

Guarantee. In the bytes of a default export (no `keep_paths`), no string value and no dict key of
any exported record holds the userinfo, path, query or fragment of a URL or of a `//` reference,
in plain, collapsed (`https:/`), mixed-case or percent-encoded form. A remote value is shown as
its origin (`scheme://host[:port]` or `//host[:port]`) or as `(remote location)`. Every map entry
survives with its original value. Every exported record decodes as a known record and its id and
payload digest verify. With `keep_paths` the output is unchanged from today.

The same rule holds for `Member.shown()` in config refusals: a remote value shows as `<file>`.

Non-goals:

- Free text inside a kept string is not scanned span by span. A kept string that holds a URL
  after other text becomes `(remote location)` as a whole (fail closed; names are not sentences).
- `manifest_hash` inside an exported evidence payload is not recomputed. It already stops
  matching once paths are reduced; that is today's behavior.
- The CLI display boundary (#416) is not changed or imported. See Q4.
- Hostile input (V1 threat model: accidental leaks only).
- The named limits in section 9.

## 3. Behavior

### 3.1 The one rule: `remote_form(value) -> str | None`

New module `src/decoy_engine/_config_text/_location.py`. It never raises. `None` means "not a
remote value"; any string is the shown form.

Terms. They are the same as the CLI plan section 1, so the two surfaces agree on whole values:

- S1: `://` with the run of `[A-Za-z0-9+.-]` just before it, or a collapsed
  `[A-Za-z][A-Za-z0-9+.-]+:/` (two or more characters, so `C:/` stays a drive).
- S2: a bare `//` followed by a character that is not whitespace or `/`, where the character
  before `//` is not a path character `[A-Za-z0-9._~/\-]` (start of text is allowed).
- A *marker* is an S1 or S2 match.
- The *decoded layers* of a value are the results of `urllib.parse.unquote` applied again and
  again until the text stops changing, at most 4 times.

Steps:

1. **No marker.** No marker in the raw value, none in any decoded layer, and the layers became
   stable within 4 decodes: return `None`.
2. **Hidden marker.** A marker only in a decoded layer, or no stable layer within 4 decodes:
   return `(remote location)`.
3. **Marker later in the value.** The first raw marker does not start at index 0: return
   `(remote location)`.
4. **Fail-closed characters.** The value holds whitespace (a line break included) or a
   backslash: return `(remote location)`.
5. **Scheme.** For S1 the scheme is the run, lower case. An empty run, or a run that does not
   start with a letter (`://x`, `12://x`): `(remote location)`. A collapsed `scheme:/` is read as
   `scheme://`. For S2 there is no scheme.
6. **Userinfo.** Let `rest` be the text after the separator and `at` the last `@` in `rest`.
   With an `@`, the userinfo is `U = rest[:at]`. A `U` that holds `/ ? #` means parsers disagree
   on where the password ends: `(remote location)`. The host part `H` is `rest[at + 1:]` up to
   the first `/ ? #`. Without an `@`, `H` is `rest` up to the first `/ ? #`.
7. **Host.** `H` empty, or `H` holding `%`: `(remote location)`. Otherwise parse
   `urlsplit("x://" + H)` and read `.hostname` and `.port`. A `ValueError` (bad port, bad IPv6)
   or no host: `(remote location)`. The `ValueError` is caught and dropped inside the function,
   and nothing is raised (recurring defect 3). An IPv6 host gets its brackets back.
8. **Shown form.** `scheme://host[:port]` for S1, `//host[:port]` for S2. The host is lower case,
   as `urlsplit` gives it.

`is_remote(value)` is `remote_form(value) is not None`. `REMOTE_LOCATION = "(remote location)"`.

Every shown form is a fixed point: `remote_form(out)` is `out` (host forms) or `None` (the
placeholder).

### 3.2 Uses of the rule

All in `records/_export_rules.py` and `records/_export.py`, plus one line in `_refusal.py`.

- **Path fields** (the kind's registered `path_fields` pointers): `export_name(value)` is
  `remote_form(value)` when it is not `None`, else today's file name. `file_name` becomes private
  (`_file_name`) and `export_name` is its only caller.
- **Every other kept string and every dict key** of the payload, at any depth, after the kind's
  rule ran (the walk, `retained`): `remote_form(value)` when it is not `None`, else unchanged.
  Path fields already reduced are fixed points, so the walk may pass over them.
- **Keys.** One key map per payload. Collect every dict key at every depth and sort by code
  point. A key whose `remote_form` is `None` or equal to itself keeps its name and reserves it.
  Then, in sorted order, each changed key takes its shown form if that name is free. Otherwise it
  takes `(remote location) (n)` with the smallest free `n >= 2`. A kept string that equals a
  changed raw key takes that key's mapped name, so `strategies[].table` still joins its row count.
- **Labels.** `labels.pipeline` goes through `export_name`. Every other label string goes through
  the walk rule.
- **Type fallback.** A shown form must still fit its field. After the walk, `_strip` validates the
  payload against the kind's write model, and `export_lines` validates the labels against
  `Labels`. If either refuses, that part is rebuilt by the same walk with every remote value set
  to `(remote location)`. The placeholder fits every name and path type in use (`SafeName`, the
  strict `RelPath`, the evidence `RelPath` and `Name`). If it still fails, the record is withheld
  and listed under `withheld_records`, as today for a payload that does not fit.
- **Header.** A record where the rule changed any value, key or label is listed under
  `unstripped` (`id` and `source_id`), as a dropped locator is today, and sets `paths_stripped`.
  The `UnstrippedRef` and `ExportHeader` docstrings say "a remote locator removed or reduced to
  its origin". The header schema does not change.
- **Ids.** The code path does not change: a changed payload gets a new `payload_digest`, a changed
  record a new `id`, and later links are rewritten through `id_map`.
- **`keep_paths`.** Unchanged. No rule runs; the claim rule still runs.
- **Config refusals.** `Member.shown()` calls `is_remote` in place of `_is_url`, and `_is_url` is
  deleted.
- **Logging.** None. The codec writes no log lines today and this change adds none.

### 3.3 Order inside `_strip`

1. Validate and project the payload (today).
2. Run the kind's `export_rule` (today: scrub, path fields now through `export_name`, locator
   drop).
3. Run the walk (`retained`) on the result. This is the choke point: it runs for every kind,
   including a future kind with a custom `export_rule`.
4. Validate against the write model. On failure, use the placeholder fallback. On a second
   failure, return `None` (withhold).
5. Return `(payload, changed, locator_removed or remote_changed)`.

## 4. Failure modes

1. The basename is taken before the remote check (today's bug, `_export_rules.py:23`).
2. Dict keys and kept names skip the rule (fingerprint maps, `row_counts`, warning `column`,
   `strategies`, `timings`, `key_label`).
3. A collapsed `https:/h/...` is not seen as a URL. `urlsplit` gives no host and the basename
   leaks.
4. A percent-encoded URL (`https%3A%2F%2F...`, double-encoded, lower-case escapes) passes the
   marker test.
5. A parser shows part of a password as host or port (`U` holding `/ ? #`, an `@` encoded as
   `%40`).
6. A backslash: `urlsplit("https://h\\x\\<token>").hostname` is `h\x\<token>` (checked on
   CPython 3.11.2).
7. Two keys show the same and one entry is silently lost.
8. A shown form does not fit its field type, so `read_export` gives a `BadLine` or `build`
   refuses.
9. The pipeline label is left out of the rule.
10. A changed payload or label is not rehashed, or a link is not rewritten (record corrupt).
11. `keep_paths` output changes, or the claim or withholding behavior changes.
12. A new kind with its own `export_rule` skips the walk.
13. A second URL detector (`_is_url`) drifts from the rule.
14. Over-redaction breaks local file names that work today.
15. The rule raises, and the exception text or its context holds the value (recurring defect 3).
16. A second export of an exported record changes it again (a shown form that is not a fixed
    point).

## 5. Acceptance tests

Red before green: rows U1 to U12, U16 to U18, U27, X1 to X8, X12, M1 and G1 fail on
`550791eff`. Builders may add tests. None of these may be weakened. The sentinel is the lowercase
word `marker`; every row also asserts it is absent from the output.

### 5.1 Unit table for the rule (`tests/unit/config_text/test_location.py`)

"Path" is `export_name(value)`. "Other" is the walk rule (`remote_form(value)`, or the value when
that is `None`). `P` is `(remote location)`.

| # | Shape | Input | Path | Other |
|---|---|---|---|---|
| U1 | userinfo | `https://u:marker@h/x` | `https://h` | `https://h` |
| U2 | userinfo, user only | `https://marker@h/x` | `https://h` | `https://h` |
| U3 | userinfo with port | `https://u:marker@h:8443/x` | `https://h:8443` | same |
| U4 | userinfo, collapsed scheme (CLI row 6) | `https:/u:marker@h/x` | `https://h` | same |
| U5 | webhook segment (CLI row 57) | `https://h/hook/marker` | `https://h` | same |
| U6 | webhook, deep path | `https://hooks.example/services/T0/B0/marker` | `https://hooks.example` | same |
| U7 | webhook, collapsed and upper case | `HTTPS:/H.Example/Hook/marker` | `https://h.example` | same |
| U8 | query token, `//` reference (CLI row 58) | `//id.example/callback?access_token=marker` | `//id.example` | same |
| U9 | query token, scheme | `https://h/cb?access_token=marker` | `https://h` | same |
| U10 | access_token case variants | `https://h/cb?ACCESS_TOKEN=marker`, `?Access_Token=marker`, `?x=1&aCCess_tOKen=marker`, `#access_token=marker`; `//id.example/cb#Access_Token=marker` | `https://h` each; `//id.example` | same |
| U11 | encoded query key | `https://h/cb?access%5Ftoken=marker` | `https://h` | same |
| U12 | encoded userinfo | `https://u%3Amarker@h/x` | `https://h` | same |
| U13 | fully encoded URL | `https%3A%2F%2Fh%2Fhook%2Fmarker`, `HTTPS%3a%2f%2fh%2fmarker` | `P` | `P` |
| U14 | encoded `//` reference | `%2F%2Fid.example%2Fcb%3Faccess_token%3Dmarker` | `P` | `P` |
| U15 | double encoded; five layers | `https%253A%252F%252Fh%252Fhook%252Fmarker`; the U13 text encoded five times | `P` | `P` |
| U16 | encoded `@` | `https://marker%40h/x`, `https://u:marker%40h/x` | `P` | `P` |
| U17 | IPv6 host with userinfo | `sftp://u:marker@[::1]:22/o.csv` | `sftp://[::1]:22` | same |
| U18 | IPv6 host, upper case, webhook | `https://[2001:DB8::1]/hook/marker` | `https://[2001:db8::1]` | same |
| U19 | IPv6, broken and zone id | `http://[::1/x?access_token=marker`, `https://[fe80::1%25eth0]/marker` | `P` | `P` |
| U20 | ambiguous password (CLI row 36) | `postgresql://admin:2024#Secret word@db.example/prod` | `P` | `P` |
| U21 | ambiguous password, `//` (CLI row 37) | `//u:12/ss@h/x` | `P` | `P` |
| U22 | backslash (CLI row 51) | `https://hooks.example\incoming\marker`, `https://u:marker@hooks.example\incoming\marker` | `P` | `P` |
| U23 | suspect `//` after text (CLI row 52) | `see //service account:marker@files.example/x today` | `P` | `P` |
| U24 | marker later in a path | `/project/https:/u:marker@h/in.csv`, `/data/a=//h/hook/marker` | `P` | `P` |
| U25 | no scheme, no host, bad port | `://u:marker@h/x`, `12://u:marker@h/x`, `file:///data/marker.csv`, `https://h:bad/marker` | `P` | `P` |
| U26 | line break | `https://h/x\nmarker` | `P` | `P` |
| U27 | object store (Q1) | `s3://bucket/prefix/marker.parquet` | `s3://bucket` | same |
| U28 | local path, kept | `/work/pipelines/claims.yaml`, `pipelines/claims.yaml` | `claims.yaml` | unchanged |
| U29 | `//` after a path character | `/var/run//deploy@prod/output.csv` | `output.csv` | unchanged |
| U30 | drive letter | `C:/Users/a@b/x.csv` | `x.csv` | unchanged |
| U31 | local names with `? # @` | `payroll?year=2026.csv`, `payroll#2026.csv`, `/tmp/x/payroll@2026.csv` | the file name | unchanged |
| U32 | Windows share | `\\server\share\f.csv` | `f.csv` | unchanged |
| U33 | encoded slash, no marker | `report%2F2026.csv` | unchanged | unchanged |
| U34 | values that must not move | a `sha256:` tag, `2026-11-08T12:00:00.123456+00:00`, `0.9.0`, `médecins`, `faker.name`, `P`, `(remote location) (2)` | unchanged | unchanged |

Properties in the same file:

- **U35 fixed point.** For every output above, `remote_form(out)` is `out` or `None`, and
  `export_name(out) == out` for every path output that is a shown form (failure mode 16).
- **U36 hypothesis.** Text = prefix + carrier + suffix, where the sentinel `S` sits on both sides
  of each delimiter. Carriers: `https://u:{S}@h/x`, `https://{S}:pw@h/x`, `https://h/hook/{S}`,
  `https://h/x?access_token={S}`, `//h/p#{S}`, `//u:{S}@h/p`, `https:/u:{S}@h/x`,
  `https:/h/hook/{S}`, `https://u:{S}#{S}@h/x`, `https://u:{S}/{S}@h/x`, `//u:{S}/{S}@h/x`,
  `sftp://u:{S}@[::1]:22/{S}`, `https://h\{S}`, and the percent-encoded form of each (encoded once
  and twice). S1 carriers get any prefix. S2 carriers get a prefix that ends at the start of
  text, at whitespace or at a non-path character. Assert `S` is absent from both `export_name` and
  the walk rule, the result is a fixed point, and the call does not raise (failure mode 15).
- **U37 no-op bound.** Hypothesis text with no `:/`, no `//` and no `%` gives `None` from
  `remote_form` (failure mode 14).

Config refusal row (`tests/unit/config_text/test_config_refusal.py`, extended):

- **M1.** `Member("https:/h/hook/marker").shown()` and `Member("https%3A%2F%2Fh%2Fmarker").shown()`
  are `<file>`. `Member("pipelines/claims.yaml").shown()` is `claims.yaml`.
  `Member("//h/x").shown()` stays `<file>`. `_is_url` no longer exists in `_refusal.py`.

### 5.2 Record rows (`tests/unit/records/test_export_remote.py`)

Real decoded records: the corpus `evidence-cli-local-1.json` payload, edited, then built with
`records.build` through the existing `make` and `raw_of` helpers, so each record decodes as known
before export. Labels are the ordinary valid `{"pipeline": "pipelines/claims.yaml", "tables":
["claims"]}` unless a row says otherwise, and do not depend on the payload keys. Each row exports
with `export_lines` and reads back with `read_export`.

| # | Edit to the record | Expected in the exported record |
|---|---|---|
| X1 | CLI row 57: `pipeline_path = https://h/hook/marker` | `pipeline_path == "https://h"` |
| X2 | CLI row 58: `input_fingerprints.claims.path = //id.example/callback?access_token=marker` | that path is `//id.example` |
| X3 | CLI row 59: the `claims` entry of `input_fingerprints`, `output_fingerprints` and `row_counts` re-keyed to `https://u:marker@h/x` | each map has key `https://h` with the original entry (fingerprint, method, size, format, layout) or count; no other key changed |
| X4 | CLI row 60: warning `{code: probe, provider: null, column: https://u:marker@h/x, detail: {"note": "marker"}}` | code `probe`, provider null, column `https://h`, detail `{}`; the bare text warning is gone (today) |
| X5 | CLI rows 6, 36, 37, 51, 52 as complete values of `scan_baseline.path`, `output_fingerprints.ledger.path`, `input_fingerprints.médecins.path`, `project_manifest` (with `path_base`) and a second record's `pipeline_path` | `https://h` for row 6, `(remote location)` for the others, each in its named field |
| X6 | `strategies[0].table` and the `row_counts` key both `https://u:marker@h/x`; `timings[0].column = https://h/hook/marker`; `key_label = //u:marker@h` | strategy table equals the mapped `row_counts` key; timing column `https://h`; key label `//h` |
| X7 | `row_counts` keys `https://a:marker@h/x` (1), `https://b:marker@h/y` (2), `https://c:marker@h/z` (3), `(remote location) (2)` (4); the a and b keys also in `input_fingerprints` | `row_counts` keys `(remote location) (2)`, `https://h`, `(remote location) (3)`, `(remote location) (4)`; values as a multiset `{1, 2, 3, 4}`; the a and b keys get the same names in `input_fingerprints` |
| X8 | label `pipeline = https:/h/hook/marker` (a valid `RelPath` today); a second record with label `https%3A%2F%2Fh%2Fhook%2Fmarker` | label `(remote location)` in both; the SEC-2 case (`proj/pipelines/claims.yaml` to `claims.yaml`) still passes |
| X9 | each of X1 to X8 | header `unstripped` lists `{id: <new>, source_id: <raw id>}`, `paths_stripped` true, `withheld_records == ()`, `record_count` correct; a record with local paths only is not in `unstripped` (today) |
| X10 | all of X1 to X8 in one export, with a sample-run record linked to the evidence record | zero `marker` in the joined default export bytes; every record line decodes as known; `record_id(raw) == id`; `payload_digest` matches; the sample-run link points at the new evidence id |
| X11 | X10 with `keep_paths=True` | each named field holds the exact original carrier; each record's canonical bytes equal its input; `unstripped == ()` |
| X12 | run-result record with `links.log.path = https:/h/hook/marker` (strict `RelPath`); sample-run record with `scratch_dir = https://u:marker@h/x` and a `table_rows` key `https%3A%2F%2Fh%2Fhook%2Fmarker` | run-result path `(remote location)` (type fallback) and the record decodes; sample-run `scratch_dir` `https://h`, key `(remote location)`; both listed in `unstripped` |

These existing tests stay green and unchanged: `test_export.py` (file names, ids, links, logs,
SEC-1 to SEC-3), `test_evidence_export.py` (warning text, layout withholding),
`test_scan_set_export.py` (claim rule and locator drop) and `test_corpus.py`. No corpus value is
URL shaped, so the stored export sample still reads whole.

### 5.3 Guard tests (`tests/sentry/test_record_export_rules.py`, extended)

- **G1 every kind, planted carriers.** A test-local builder per writable kind: the evidence
  corpus, `sample_payload`, the scan-set corpus, and a run-result built with the existing
  run-result test helpers. The test first asserts that the builder map covers
  `registered_kinds()` exactly, so a new kind without a builder is red. For each kind, plant each
  U36 carrier in every string leaf and every dict key that the write model still accepts with it.
  Each plant is validated alone; a refused plant is skipped and counted, and each kind must have
  at least one accepted plant. Export by default and assert zero sentinel bytes and that every
  record decodes as known.
- **G2 one parser, one caller.** AST walk of `src/decoy_engine/records/` and
  `src/decoy_engine/_config_text/`: `urllib.parse` is imported only by `_config_text/_location.py`;
  `_file_name` is referenced only inside `export_name`; `_strip` calls `retained`.

Seeded mutations. Each must turn the named guard red:

| Mutation | Red |
|---|---|
| Delete the `retained(...)` call in `_strip` | G1 (keys and warning column leak), G2 |
| `_reduce` calls `_file_name` in place of `export_name` | G1 (webhook segment leaks as a file name), G2 |
| `from urllib.parse import urlsplit` added to `_export_rules.py` | G2 |
| Step 2 of the rule deleted (no decoded layers) | G1 (encoded carriers), U13 to U15 |

The mutations run on the final head, and the head is recorded (recurring defect 9).

### 5.4 Test depth

T0 per edit, T1 per commit. The slice head runs the full suite, diffed against the saved main
baseline, because the change touches serialization (the export record bytes) and sentry tests.

### 5.5 Recurring defect classes

1 (anchored): the start rules use `re.search` positions and the "starts at index 0" test, not a
`$` anchor; U26 covers a trailing line break. 2 and 4 (strict types, read models): unchanged,
the export still validates with the strict write model and decodes with the derived read model.
3 (no context): section 3.1 step 7 and U36. 5 (normalized scanners): G2 matches `import` and
`from ... import` forms of `urllib.parse`. 6 (private imports): `records` imports the three names
from the `decoy_engine._config_text` package, not from `_location`. 7: no CI change. 8: local
names that worked before are rows U28 to U34. 9: section 5.3. 10: no allowlisted helper is added.
11: no cap or ratchet moves.

## 6. Established solutions

Search run on 2026-11-28: the CLI plan's survey (section 4 of the D6 plan; sources under
`~/scratch/d6m-survey/`: libpq `fe-connect.c`, git `transport.c` and `urlmatch.c`), plus CPython
3.11.2 `urllib.parse` run on this box against every leak shape in section 5.

- **Show the origin, built from parsed parts.** WHATWG URL Standard, "serialization of an origin"
  (`scheme://host[:port]`), and yarl `URL.origin()`. pip `redact_auth_from_url` and sentry-python
  `sanitize_url` keep the path and mask only the password or the query values. A path is not
  safe here: an incoming-webhook URL carries its secret in the path. So the design follows the
  origin pattern, and builds the shown form from parsed parts, never by deleting from raw text.
- **Userinfo split.** CPython `urllib.parse` splits userinfo at the last `@` in the authority
  (`netloc.rpartition("@")`). DSN parsers (libpq, SQLAlchemy) split at the first `@` and let
  `/ ? #` into the password. The rule takes the last `@` and refuses to show a host when `U` holds
  `/ ? #`, so no parser's reading can expose part of a password (CLI plan, step 3).
- **Query tokens.** RFC 6750 section 2.3 puts `access_token` in the URI query, and the OAuth 2.0
  implicit grant (RFC 6749 section 4.2.2) puts it in the fragment. RFC 3986 section 7.5 warns that
  URIs carry such data. Dropping the whole query and fragment needs no list of parameter names,
  so case variants cannot slip past (row U10).
- **Encoded input.** OWASP ESAPI `Encoder.canonicalize` decodes until stable and treats multiple
  encoding as an attack. The rule decodes only to look for a hidden marker and fails closed on
  one. It never shows a decoded value.
- **Parsing.** `urllib.parse.urlsplit` for host and port, with its `ValueError` caught. No new
  dependency.

Custom code that remains: the start rules S1 and S2 (no library finds a URL inside a path value
or reads a collapsed `https:/`), the backslash and whitespace refusals (the probe showed that
`urlsplit` keeps a backslash inside the host), and the key collision names.

## 7. Design notes

- **One rule, one place.** `remote_form` is the only remote-location rule in the engine.
  `Member.shown` and export both call it, and `_is_url` is deleted. Principle: single source of
  truth. The pain it removes is the drift that let `https:/` pass `_is_url`.
- **Choke point by construction.** The walk runs in `_strip` after any kind's rule, so a new kind
  cannot skip it (complete mediation). G1 walks the real registry, not a list in the test.
- **Type fallback.** It keeps the existing withholding path as the last resort and adds no new
  outcome.
- **No new abstraction.** Three functions (`remote_form`, `is_remote`, `export_name`) and one
  walk (`retained`). No flag argument: the fallback passes a different shown function to the same
  walk.
- **Placement in `_config_text`.** The rule must sit at or below the tier of `_config_text`
  (`Member`) and below `records`. `safe_output` is in the same tier, but its `__init__` imports
  pyarrow, which `_config_text` must not (see its package docstring). `reasons` would also work,
  but its job is the reason registry; `_config_text` already owns value display for refusals.

## 8. Files, placement and size

| File | Change | Lines now | Lines after |
|---|---|---|---|
| `src/decoy_engine/_config_text/_location.py` | new: `remote_form`, `is_remote`, `REMOTE_LOCATION`; docstring cites section 6 | 0 | ~140 |
| `src/decoy_engine/_config_text/__init__.py` | export the three names | 40 | ~46 |
| `src/decoy_engine/_config_text/_refusal.py` | `Member.shown` uses `is_remote`; delete `_is_url` | 275 | ~271 |
| `src/decoy_engine/records/_export_rules.py` | `_file_name`, `export_name`, `retained` (key map, kept strings); `_reduce` uses `export_name` | 91 | ~190 |
| `src/decoy_engine/records/_export.py` | `_strip` steps 3 to 5, label rule and fallback, `unstripped` for remote changes, docstrings | 325 | ~355 |
| `src/decoy_engine/records/_kinds.py` | none (the warning scrub stays; the walk covers `column`) | 147 | 147 |
| `tests/unit/config_text/test_location.py` | new: U1 to U37 | 0 | ~230 |
| `tests/unit/config_text/test_config_refusal.py` | M1 | - | +15 |
| `tests/unit/records/test_export_remote.py` | new: X1 to X12 | 0 | ~290 |
| `tests/sentry/test_record_export_rules.py` | G1, G2 | 57 | ~150 |
| `CHANGELOG.md` | `[Unreleased]`, Security: the default export leak and the refusal `<file>` change | - | +6 |
| `CODEMAP.md` | line 305: add `_location.py` (the one remote-location rule) to the `_config_text` row | - | 1 line |

Placement:

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `_location.py` | `src/decoy_engine/_config_text/` | 305, "Config refusal text foundation" (a map change: the row gains the module) | `_refusal.py` |
| `test_location.py` | `tests/unit/config_text/` | 305 (its tests column) | `test_config_refusal.py` |
| `test_export_remote.py` | `tests/unit/records/` | 174 (`unit/records/`) | `test_evidence_export.py` |

Every module stays under 600 lines. No new top-level package, so the import-layer contract and its
snapshot do not change. `records` importing `_config_text` goes down the tiers and needs no ignore
line. No new baseline, census, allow-list or ratchet row is added. No public name is added to
`decoy_engine.records.__all__`, so the compatibility contract surface does not change.

## 9. Named limits and over-redaction

Over-redacted on purpose (fail closed, recorded so review does not reopen them):

- A remote value with `@` in its path, `https://h/x@2026.csv`, gives `(remote location)`.
- `//server/share/payroll@2026.csv` gives `(remote location)`.
- A local name whose decoded form holds `scheme:/`, such as `report%3A%2F2026.csv`, gives
  `(remote location)`.
- A colliding key after the first loses its host (`(remote location) (n)`), so the output stays a
  fixed point.
- A host holding `%` (an IPv6 zone id, an encoded host) gives `(remote location)`.

Known limits (V2-LOG, the same as the CLI plan):

- A host path with no scheme and no `//` (`id.example/callback?access_token=T`) is read as a local
  path, and its file name `callback?access_token=T` is kept. A local file may hold `?`, so a rule
  here would break U31.
- A Windows share (`\\host\share\T`) is a local path, and its last segment is kept.
- `user:pw@host` with no scheme and no `//` is not seen as remote.

## 10. Slices

One engine slice, **E1**, R2: the rule, the export changes, the `Member` change, all tests,
CHANGELOG and the CODEMAP line. The parts carry the same risk and the same tests, so splitting
them would pay the fixed slice cost twice.

Review: risky tier (value leak), so Dennis then Codex on the plan and on the code. Gate: T1 plus
the full suite on the exact head, and the four seeded mutations on that head.

The row closes after E1 merges, with the engine release and the CLI repin under the engine-repin
checklist (CLI plan section 8). That close-out is release work, not a second slice of this plan.

## 11. Defect classes (plan contract catalog)

| # | Class | Closing structure | Proof (test) | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output (paths, tokens, userinfo in export bytes) | `remote_form` is the one rule; the walk runs in `_strip` for every kind | U1 to U36, X1 to X12, G1 seeded markers per kind | delete the `retained` call; `_reduce` back to `_file_name` |
| 2 | Cleanup on an exit path | N/A: the codec is pure, holds no resource and writes no file | none needed | none |
| 3 | State machine and concurrency | N/A: no shared state; `export_lines` builds local lists per call | none needed | none |
| 4 | Route parity and silent fallback | every writable kind passes the same walk; the type fallback ends in the existing withhold, listed in the header | G1 builder map equals `registered_kinds()`; X12 | delete the fallback: X12 gives a `BadLine` |
| 5 | Referential integrity | one key map per payload, so a changed key gets the same name in every map and in `strategies[].table` | X3, X6, X7 | build the map per dict: X7 red |
| 6 | Untrusted producer | `remote_form` never raises and never shows a decoded value; `urlsplit` errors caught | U36 hypothesis (no raise, no sentinel) | let the `ValueError` escape: U25 red |
| 7 | Check then use on a path (TOCTOU) | N/A: no file system access; the codec only reads strings | none needed | none |
| 8 | Weak tests and overclaimed evidence | red-first list in section 5; every row asserts the sentinel absent and a positive shown value | rows run red on `550791eff` before the build | the four seeded mutations in 5.3 |
| 9 | Behavior-preserving refactor drift | local file name behavior pinned by U28 to U34 and the existing export tests | `test_export.py`, `test_evidence_export.py` unchanged and green | change `_file_name` splitting: U28 red |
| 10 | Frozen contract drift | header schema and envelope schema unchanged; values only (section 13) | `test_corpus.py` export sample reads whole; frozen schema snapshots unchanged | add a header field: snapshot red |

## 12. Enumerations

### 12.1 Exit paths

- A record that fits after the walk: exported, changed or not (`_export.py:204` to `:221`).
- A record whose shown form does not fit: placeholder fallback, then exported.
- A record that still does not fit, or that has no rule: withheld (`_export.py:183` to `:186`).
- `keep_paths`: no rule runs; claim rule only (`_export.py:188` to `:193`).

### 12.2 Routes

- Default export through `_strip` and the kind's `export_rule` (`_export.py:127`).
- `keep_paths` export (`_export.py:188`).
- Config refusal display through `Member.shown` (`_config_text/_refusal.py:167`).

### 12.3 FK shapes

N/A: the change touches record export and refusal text only; no table data or keys are joined.

### 12.4 Fields

- Evidence path fields (`records/_kinds.py:118` to `:124`).
- Run-result and sample-run path fields (`records/_kinds.py:125` to `:126`).
- Scan-set descriptor path and locator fields (`records/_kinds.py:180` to `:181`).
- Every dict key and every other string leaf of each payload (the walk).
- `labels.pipeline` and `labels.tables` (`records/_envelope.py:54` to `:55`).

### 12.5 Output surfaces

- The record lines of a default export (canonical JSON bytes).
- The header line (`unstripped`, `withheld_records`, `refs`; ids only).
- Config refusal text and its `path` (`Member.shown`).
- Log lines of an export: never written without `keep_paths` (`_export.py:242` to `:245`).

## 13. Frozen contracts

- `decoy-library-export/v1` and `decoy-record/v1` are frozen tags
  (`docs/compatibility-contract.md`, section 3). The change keeps both schemas and every field;
  only the values a default export writes for remote paths and keys change. A reader of either
  version reads both outputs.
- `ExportHeader` keeps its fields. `unstripped` gains entries for records whose remote values
  were reduced, which its meaning (a lossy strip the reader should know about) already covers.
- `keep_paths` output is byte for byte unchanged (X11).
- `cli-local-1` and the other payload schemas do not change.

## 14. Pre-mortem

The ways a gate reviewer is likely to break the build, each closed by a row above:

1. A key re-keyed in only one of the three maps, so joins break: X3, X7.
2. A label reduced to `https://h`, which `RelPath` refuses on read: X8.
3. A strict `RelPath` field in another kind given a host form: X12.
4. An encoded URL that hides its marker: U13 to U15, G1 encoded carriers.
5. A webhook URL with a backslash that `urlsplit` reads as a host: U22.
6. A local file name that now becomes `(remote location)`: U28 to U34.
7. A second export that changes the first export's output: U35.
8. A new kind with its own rule that skips the walk: G1, the first G2 mutation.

## 15. Owner questions

**Q1. Object-store and other non-web remote paths.** A path field `s3://bucket/prefix/f.parquet`
exports today as `f.parquet`. With this rule it exports as `s3://bucket`. The scan-set kind
treats a bucket as a locator and removes it.
- A (recommended): one rule for every scheme, show `s3://bucket`. It matches the CLI display
  boundary and its rows 57 to 60, and the header lists the record as unstripped.
- B: show the origin only for `http` and `https`; every other scheme gives `(remote location)`.

**Q2. The `Member.shown` change.**
- A (recommended): fold it into E1. It is four lines, it deletes the second URL detector, and it
  closes the same leak in config refusals.
- B: track it as its own row.

**Q3. Collision names.**
- A (recommended): `(remote location) (n)` for every colliding key after the first. The output
  stays a fixed point, so a second export does not change it.
- B: the CLI's `https://h (n)`. It keeps the host, but `remote_form` turns it into
  `(remote location)` on a second export.

**Q4. One rule across both repos.** After the CLI repin, should the CLI's whole-value
`display_location` call the engine's `remote_form`, so there is one rule across the repos?
- A (recommended): record it as a 1.x follow-up after #416 and this row are both merged. The CLI
  scanner also handles spans inside free text, which the engine does not need.
- B: do it in the CLI repin for this row.
