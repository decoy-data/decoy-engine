# LOCATOR-CREDS: one recognizer and redactor for credentials in file locators

Status: plan

Risk tier: R2 (security and privacy logic, a new public package name the CLI consumes, cross-repo contract).
Gate: Dennis then Codex on this plan; Codex (and Dennis for E-S1 and C1) on each slice.

Rules consulted: 00-universal, risk-and-exceptions, development-loop, cross-cutting-concerns,
architecture, security, testing ("Test depth"), api-and-compatibility, reuse-first,
catalogs/recurring-defects. Memories: value-free class recurs (F31), best practice becomes a sentry,
root cause not patch, engine repin checklist, engine release bump freely pre-release.

Base: engine `origin/main` `393f0d47c`; CLI `origin/main` (pins engine 0.28.3).
Inputs: engine PR #808 at `b05773146` (`feat/code-set-native-s1`), CLI PR #412 at `c6f8d66d`
(`refactor/cli-split-preflight`), and their Codex reviews (808 delta-e, 412 delta-c, earlier rounds).

## 1. Problem and pinned guarantee

Two PRs failed Codex review on the same defect class. Each wrote its own parser for "does this
locator carry credentials, and how is it shown without them". There are now three copies of the
scheme and `@?#` grammar:

| Copy | Where | What it gets wrong |
|---|---|---|
| Engine locator scanner | #808 `src/decoy_engine/_locator.py` | Misses leading spaces (`  //svc:CANARY@host/key`) and one-letter schemes (`x://svc:CANARY@host/key`). Flags clean `//host/key?`, `//host/key#` and `\\?\UNC\server\share\x.parquet`. Rewrites backslashes outside the secret. |
| Engine name and provenance marks | #808 `plan/checks/_code_set_locator.py:20` (`_NAME_MARKS`), `transforms/_codeset/_checks.py:278` (`_publishable`) | Plan check and runtime disagree: `study?token=CANARY` passes `CodeSetConfig.from_dict` and reaches `describe_loaded_corpus`, while compile rejects `ICD@2026`. Provenance publishes `https://files.example/s/CANARY` whole. Plan traversal skips tuples. |
| CLI display redactor | #412 `src/decoy/cli/io/_display.py` | `dsn=https://u:foo'CANARY@h/a` leaks after the quote; `https:\\u:CANARY@host\file` leaks; `C://foo@bar/data.csv` shows as `c://bar/data.csv`. `build_manifest` stores the credential-bearing source in `input_fingerprints` and `decoy report show` prints it (pre-existing on main). |

Guarantee, when the last slice merges:

1. Exactly one function in the two repos decides whether a locator carries credentials and what
   its display text is: `decoy_engine.safe_output.scan_locator`. Every surface in section 4 calls it.
   The plan check and every display read the same `LocatorScan`, so they cannot disagree.
2. Display text is the input with zero or more spans replaced by `<redacted>`. No character
   outside a replaced span changes: no case folding, no separator rewriting, no dropped text.
3. A sentry in each repo fails the build when new source code parses `://`, `@`, or URL userinfo
   outside the boundary, unless an allowlist row with a reason covers it. The allowlist only shrinks.
4. One case table (section 3) drives the unit tests of the recognizer and the surface tests in both
   repos.

Non-goals:
- No secret detection in free text beyond URL structure (no gitleaks-style keyword rules).
- No percent-decoding of the authority (section 3, row 23 records this as characterization).
- No change to `fileaccess.redact_locators` (pair replacement of a known locator in third-party
  text). It is a different job; its display side already comes from `fileaccess.shown`, which now
  calls the recognizer.
- No root `decoy_engine.__all__` addition (PROP-SURFACE). The public names live on the
  `decoy_engine.safe_output` package, which the CLI already imports (`yaml_error_text`,
  `validation_problems`).
- No platform edit (platform parked on engine 0.18.0).

## 2. Survey: how established tools recognise and redact credentials in URLs

| Source | Recognition rule | Redaction rule | What we take |
|---|---|---|---|
| RFC 3986 section 3.2, 3.2.1, 7.5 | `authority = [ userinfo "@" ] host [ ":" port ]`; authority ends at the next `/`, `?` or `#`. `user:password` in userinfo is deprecated. | 7.5: applications should not render the text after the first `:` in userinfo as clear text. | Authority ends at `/ ? #`. Userinfo is a credential. |
| WHATWG URL Standard (browsers) | Strips leading and trailing C0 control or space, removes tab and newline. For special schemes (http, https, ws, wss, ftp, file) `\` is a path separator like `/`. Userinfo ends at the last `@` in the authority. | n/a | Strip leading C0/space before classifying. Treat `\` as `/` after a scheme. Last `@` in the authority ends userinfo. |
| CPython `urllib.parse` | `urlsplit` netloc runs to the first `/?#`; `_userinfo` is `netloc.rpartition('@')`. Since the gh-102153 fix it strips leading C0/space (`_WHATWG_C0_CONTROL_OR_SPACE`) and removes `\t\r\n` (`_UNSAFE_URL_BYTES_TO_REMOVE`), verified in the local stdlib. | n/a | Same split; confirms last-`@` and leading-space handling. |
| pip `pip._internal.utils.misc.redact_auth_from_url` / `redact_netloc` | urllib split. | Password becomes `****`. A username with no password is also masked, because tokens are often sent as the username. | Mask the whole userinfo, user included. Visible mask, not silent removal. |
| SQLAlchemy `URL.render_as_string(hide_password=True)`, `URL.__repr__` | Own DSN parser (`dialect+driver://user:pass@host:port/db?query`). | Password becomes `***`; host, port and database kept. | DSNs with `+driver` schemes are URLs; keep host and path. |
| git `transport_anonymize_url()` (transport.c), `transfer.credentialsInUrl` (git 2.41) | Userinfo only when the `@` sits after `://` and before the first `/`. | Strips `user:pass@` from URLs it prints. `transfer.credentialsInUrl=die` refuses a configured URL with a plaintext password. | `@` after the authority is path text. Refusing at config time (our plan check) has precedent. |
| fsspec `fsspec.core.split_protocol` | `if len(protocol) > 1:  # excludes Windows paths`, verified in the installed source. | n/a (fsspec passes userinfo to the backend). | A one-letter "scheme" is a drive letter, not a URL. |
| rclone | Remotes are `name:path` or connection strings `:backend,key=value:path`; secrets live in config, not the path. `rclone config redacted` prints config with secrets replaced. | Redacts by known secret field, not by parsing. | Keep secrets out of locators; our plan check message says so. |
| W3C TAG "Good Practices for Capability URLs"; W3C Referrer Policy `strict-origin` | A capability URL carries its secret in the path. | Send only the origin to third parties. | Text a file supplies (provenance) is published as origin only. |
| Microsoft "File path formats on Windows systems" | `C:\`, UNC `\\server\share\`, DOS device paths `\\?\` and `\\.\` (including `\\?\UNC\server\share`). | n/a | `\\?\` and `\\.\` are a device prefix; their `?` and `.` are not a query or host. |

Pattern chosen: parse the authority the way RFC 3986, WHATWG and urllib agree on (authority ends at
the first `/ ? #`, and also `\` after a scheme of two or more characters; userinfo is everything
before the last `@` in the authority). Mask the whole userinfo and any non-empty query or fragment
with a visible `<redacted>`, as pip and SQLAlchemy do. Refuse a credential-bearing locator at plan
time, as git's `credentialsInUrl=die` does. Classify a one-letter scheme as a drive letter, as
fsspec does, with one refinement in section 3 (D7). Publish file-supplied URLs as origin only, as
Referrer Policy does.

## 3. The recognizer and redactor

### Placement

| Item | Path | Why |
|---|---|---|
| Grammar (stdlib only) | `src/decoy_engine/_locator.py` | A bottom-tier leaf, like `_canonical` and `_value_free`. `plan` must call it and the `policy-direction` import contract forbids `plan -> fileaccess`. A stdlib-only leaf adds no import cost to a capped worker. #808 already placed a leaf here and in `.importlinter`; E-S1 lands that placement on main with the new grammar. |
| Public face | `decoy_engine.safe_output.__all__` gains `scan_locator`, `LocatorScan`, `LocatorKind` | CODEMAP "Where things go": the safe output boundary is `safe_output/`. CLI consumers: preflight and validate findings, `build_manifest`, `report show`, `io/_layout.py` classification. No root export, so PROP-SURFACE is unaffected. |
| Case table | engine `tests/fixtures/locator_credentials/cases.json` (canonical); CLI `tests/fixtures/locator_credentials/cases.json` (vendored copy) | Section 3, "Case table". |

Engine modules import from `decoy_engine._locator` (engine-internal leaf, the pattern `_canonical`
uses). The CLI imports only `decoy_engine.safe_output`.

### Signature

```python
class LocatorKind(StrEnum):
    LOCAL = "local"      # POSIX or relative path, or free text with no URL at the start
    DRIVE = "drive"      # one letter, ':' then a separator: C:\x, C:/x, C://x
    DEVICE = "device"    # \\?\ or \\.\ (and //?/, //./), including \\?\UNC\server\share
    NETWORK = "network"  # leading // or \\ with no scheme: //host/key, \\server\share
    URL = "url"          # scheme of 2+ characters, ':' then a separator

@dataclass(frozen=True, slots=True)
class LocatorScan:
    kind: LocatorKind
    shown: str                 # display text; credential spans replaced by "<redacted>"
    carries_credentials: bool  # True exactly when shown != text
    origin: str | None         # "scheme://host[:port]" (URL) or "//host" (NETWORK), userinfo excluded

def scan_locator(text: str) -> LocatorScan: ...
```

One entry point, one result. The plan check reads `.carries_credentials`; displays read `.shown`;
classifiers read `.kind`; provenance reads `.origin`. `carries_credentials` is defined as
`shown != text`, so a detector that says "yes" while the redactor removes nothing (the #808
`//host/key?` defect) cannot happen by construction.

The function never raises on `str` input. It does no I/O, no decoding and no normalization.

### Decisions

D1. Leading whitespace. Classify after stripping leading C0 control or space (WHATWG, urllib).
The stripped prefix is kept in `shown`. `  //svc:CANARY@host/key` is NETWORK and shows
`  //<redacted>@host/key`.

D2. Scheme. `[A-Za-z][A-Za-z0-9+.-]+` followed by `:` and one or two of `/` or `\`. Two or more
characters. A scheme followed by `\\` is a URL (WHATWG special-scheme rule, applied to every
scheme): `https:\\u:CANARY@host\file` shows `https:\\<redacted>@host\file`. A known remote scheme
followed by one separator is also a URL, because `pathlib` folds `https://` to `https:/`. The
known set is the existing #808 list (`http(s)`, `s3(a)`, `gs`, `gcs`, `abfs(s)`, `az`, `wasb(s)`,
`ftp(s)`, `sftp`, `hdfs`, `webhdfs`, `smb`, `r2`, `oss`), held once in `_locator.py`.

D3. Authority and userinfo. The authority runs from after the separators to the first `/`, `?`,
`#` or `\`. Userinfo is everything before the last `@` in the authority (WHATWG, urllib). It is
replaced whole, user included (pip): `s3://AKIA:CANARY@bucket/k` shows `s3://<redacted>@bucket/k`.
Quotes, spaces and other characters inside the authority do not end it, so
`https://u:foo'CANARY@h/a` shows `https://<redacted>@h/a`.

D4. `@` after the authority. It is path text (RFC 3986, git): `s3://bucket/user@example.com/f.csv`
is unchanged. Exception, fail closed: when the authority is not a valid host (its port part is not
all digits, for example `u:pa` in `https://u:pa/ss@h/a`) and an `@` follows in the path, the
password held a `/`. Everything after the separators is replaced: `https://<redacted>`.

D5. Query and fragment. A non-empty query becomes `?<redacted>`; a non-empty fragment becomes
`#<redacted>`. An empty `?` or `#` is not a credential and is kept: `//host/key?` is unchanged and
`carries_credentials` is False.

D6. Bearer in path. Not detectable from structure. For a configured locator (one the user wrote)
the path is kept, because the user needs to know which file a message names and the same text is
already in their YAML. For file-supplied text (provenance fields), a URL or NETWORK value is
published as `origin + "/<redacted>"` when its path is non-empty, otherwise as `origin`
(Referrer Policy). Owner question O1 covers persisted evidence.

D7. Drive letters and one-letter schemes. One letter, `:`, then a separator is DRIVE (fsspec).
Nothing is rewritten: `C://foo@bar/data.csv` and `C:\foo@bar\data.csv` are unchanged. Refinement:
when the first segment after the separators contains `:` before an `@`, it is userinfo, because
`:` is not legal in a Windows directory name. `x://svc:CANARY@host/key` shows
`x://<redacted>@host/key`. A drive path with `@` and no `:` before it (`C://foo@bar`) is a legal
directory name and stays as written.

D8. DEVICE paths. `\\?\`, `\\.\`, `//?/` and `//./` prefixes are recognised first. Their `?` and
`.` are part of the prefix. The rest is read as a DRIVE or UNC path (`\\?\UNC\server\share\x`):
no query, no fragment, no userinfo. Always unchanged.

D9. NETWORK paths (`//` or `\\` with no scheme). The first segment is an authority under D3, D4
and D5, the same rule as a URL (the #808 behavior, kept). `\\server\share\x.parquet` is unchanged.

D10. Embedded URLs. A URL can start inside the value: after `=`, whitespace, a quote, `(`, `,`,
`;`, `<`, or a path separator. `dsn=https://u:foo'CANARY@h/a` is LOCAL and shows
`dsn=https://<redacted>@h/a`. After a path separator only a URL with two separators or a known
remote scheme counts, so `/tmp/a:/b@c/f?x=1` stays LOCAL and unchanged (#808 behavior, kept).
Inside a value an embedded URL runs to the end of the value; D3 to D5 apply to it.

D11. Separators and case. Only text inside a replaced span changes. Backslashes stay backslashes,
case stays as written. This replaces the #808 rewrite of `\` to `/` and the CLI lowercasing.

D12. Corpus names (`code_set`). A name is a label, not a locator. Recommended rule: a closed label
grammar `[A-Za-z0-9][A-Za-z0-9 _.:@+-]{0,127}` checked once in `validate_code_set_config` (so both
`CodeSetConfig.from_dict` and compile go through it), refusing `/ \ ? #`, controls and URLs.
`ICD@2026` passes; `study?token=CANARY` is refused with a value-free message. This narrows a
config contract that today says "arbitrary name", so it is owner question O2. Fallback if the owner
declines: names go through `scan_locator` like a locator and display `.shown`.

D13. Percent-encoding. Not decoded (urllib does not decode before splitting). `//svc%3ACANARY%40host/key`
has no literal `@`, so it is unchanged. Recorded as a characterization row; Codex rated it V2-LOG.

### Case table

`cases.json` is a list of rows `{id, input, kind, shown, carries, origin_shown, note}`.
`origin_shown` is what a provenance field publishes (D6). Inputs use the synthetic secret
`CANARY`; every row whose `carries` is true must not contain `CANARY` in `shown`.

| id | input | kind | shown | carries |
|---|---|---|---|---|
| url-plain | `s3://bucket/key.parquet` | url | unchanged | no |
| url-userinfo | `s3://AKIA:CANARY@bucket/key` | url | `s3://<redacted>@bucket/key` | yes |
| url-user-only | `https://CANARY@github.example/r.git` | url | `https://<redacted>@github.example/r.git` | yes |
| url-quote-in-pass | `https://u:foo'CANARY@h/a` | url | `https://<redacted>@h/a` | yes |
| embedded-dsn | `dsn=https://u:foo'CANARY@h/a` | local | `dsn=https://<redacted>@h/a` | yes |
| embedded-space | `see https://u:CANARY@h/a` | local | `see https://<redacted>@h/a` | yes |
| backslash-url | `https:\\u:CANARY@host\file` | url | `https:\\<redacted>@host\file` | yes |
| folded-url | `https:/u:CANARY@host/file` | url | `https:/<redacted>@host/file` | yes |
| folded-under-cwd | `/home/x/https:/u:CANARY@h/a` | local | `/home/x/https:/<redacted>@h/a` | yes |
| leading-space-net | `  //svc:CANARY@host/key` | network | `  //<redacted>@host/key` | yes |
| leading-tab-url | `\tx3://u:CANARY@h/k` | url | `\tx3://<redacted>@h/k` | yes |
| one-letter-creds | `x://svc:CANARY@host/key` | drive | `x://<redacted>@host/key` | yes |
| drive-at-dir | `C://foo@bar/data.csv` | drive | unchanged | no |
| drive-backslash-at | `C:\foo@bar\data.csv` | drive | unchanged | no |
| drive-plain | `C:/data/x.csv` | drive | unchanged | no |
| posix-colon-at | `/tmp/a:b@c/f?x=1` | local | unchanged | no |
| net-empty-query | `//host/key?` | network | unchanged | no |
| net-empty-fragment | `//host/key#` | network | unchanged | no |
| unc | `\\server\share\x.parquet` | network | unchanged | no |
| ext-unc | `\\?\UNC\server\share\corpus.parquet` | device | unchanged | no |
| ext-drive | `\\?\C:\data\x.csv` | device | unchanged | no |
| query-token | `https://h/a?token=CANARY` | url | `https://h/a?<redacted>` | yes |
| fragment-token | `https://h/a#access_token=CANARY` | url | `https://h/a#<redacted>` | yes |
| at-in-query | `https://h/a?x=u@CANARY` | url | `https://h/a?<redacted>` | yes |
| at-in-path | `s3://bucket/user@example.com/f.csv` | url | unchanged | no |
| slash-in-pass | `https://u:pa/CANARY@h/a` | url | `https://<redacted>` | yes |
| bearer-path | `https://files.example/s/CANARY` | url | unchanged (configured) | no; `origin_shown` = `https://files.example/<redacted>` |
| ipv6 | `https://u:CANARY@[::1]:8080/a` | url | `https://<redacted>@[::1]:8080/a` | yes |
| dsn-driver | `postgresql+psycopg://u:CANARY@db:5432/x` | url | `postgresql+psycopg://<redacted>@db:5432/x` | yes |
| file-url-at | `file:///tmp/a@b.csv` | url | unchanged | no |
| pct-encoded | `//svc%3ACANARY%40host/key` | network | unchanged (characterization, D13) | no |
| empty | `` | local | `` | no |

Builders may add rows; they may not change a row's expected value without a plan delta.
Two properties run over every row and over a Hypothesis strategy built from the row fragments:
(a) `shown` equals `input` with zero or more spans replaced by `<redacted>`; (b) idempotence:
`scan_locator(shown).shown == shown` and `scan_locator(shown).carries_credentials is False`.

Sharing with the CLI: the CLI vendors a byte-identical copy and pins its SHA-256 in
`tests/fixtures/locator_credentials/SHA256`. A CLI test fails when the copy does not match the pin.
The engine repin checklist gains one line: "copy `cases.json` from the new engine tag and update the
pin". If the engine grammar changes a row, the CLI surface tests on the new pin go red until the
copy is refreshed, which is the drift alarm. No CLI test imports engine test data or a private module.

## 4. Routing every surface

### Engine

| Surface | Today (#808 head) | After |
|---|---|---|
| Plan check `plan/checks/_code_set_locator.py` | Own `_values` walker (dict and list only); `locator_carries_credentials` or `_NAME_MARKS` | Walk with the config serializer's traversal in `plan/checks/_config_json.py` (dict, list, tuple, any non-str sequence). `corpus_source` refused when `scan_locator(text.removeprefix("customer:")).carries_credentials`. `code_set` names under D12. Imported through `plan.checks.__init__`, not the private module (Codex DESIGN finding). |
| `plan_to_yaml` | Copies the locator; protected only by the plan check | Unchanged code; protected by the fixed plan check. Surface test: no carries-true row reaches YAML through compile, `CodeSetConfig.from_dict`, or tuple `columns`. |
| `verify_corpus` (`path`, `problems`) | `_where` -> `fileaccess.shown` -> `without_url_credentials` | `fileaccess.shown` returns `scan_locator(locator).shown` under the ambient policy and the encoded field key otherwise. |
| Corpus error messages (`_where`, `corpus_stat_error`) | as above | as above |
| Provenance `provenance_summary` | `_publishable`: withhold whole on `@?#` | `_publishable(text)`: if `scan_locator(text).kind` is URL or NETWORK, publish the D6 origin form; else publish `scan_locator(text).shown`. |
| `describe_loaded_corpus` `code_set` | `_corpus_label` -> `fileaccess.shown` | Shipped name as is; other names were checked by D12 at the config boundary, so shown as is (fallback: `.shown`). |

Deleted in the engine: #808 `_locator.py` grammar functions `without_url_credentials` and
`locator_carries_credentials` (and the `fileaccess.__init__` export of `without_url_credentials`
that #808 adds), `_NAME_MARKS`, the `@?#` tuple in `_publishable`, and the `_values` walker in
`_code_set_locator.py`. Kept on purpose, listed in the sentry allowlist: `config/_targets.py:182`
(`_endpoint_identity`, an identity key built with `urlsplit`, never displayed),
`secret_providers/_types.py:180` (rejects a mount URL with `@` or `:`, a validation, never displayed),
and any other site the E-S1 walk finds, each with a reason.

### CLI

| Surface | Today | After |
|---|---|---|
| `validate` and `validate preflight` source findings, human and `--json` (`preflight/_checks.py:51` on #412; inline on main) | #412: `redact_url`; main: raw path | `scan_locator(str(src)).shown` in the one shared finding builder; both commands and both output modes use it. |
| `build_manifest` `input_fingerprints` (`evidence.py:287-300`) | Records `str(src_path_str)` for URLs, `_recorded(path)` for files; the `"://" in` test misses a `Path`-folded `https:/` | Classify the original spelling: `scan = scan_locator(str(src_path_str))`. URL or NETWORK: record `scan.shown`, no hash. Otherwise the current file branch, with `_recorded(...)` passed through `scan_locator(...).shown` as well (catches `folded-under-cwd`). |
| `decoy report show` (`evidence.py:759`) | Prints `info["path"]` | Prints `scan_locator(str(info.get("path", "?"))).shown`, so manifests written before C1 are shown safely too (read path matches write path). |
| `io/_layout.py:66` `_URL_PATH` | Own scheme regex | `scan_locator(raw).kind is LocatorKind.URL`. |

Deleted in the CLI: #412 `io/_display.py` (`_URL`, `_redact_text`, `redact_url`, `redact_urls`)
and its exports from `decoy.cli.io`, and `_layout._URL_PATH`. Kept on purpose, listed in the CLI
allowlist with reasons and a follow-up row to move them to `.kind`: `io/_run_outputs.py:126`,
`io/_placement.py:238`, `api.py:377`, `ci/contracts.py:171` (all "is this remote" classifiers);
`_outbound.py:179`, `notify.py:460`, `distribution/release_identity.py:76` (outbound endpoint
validation with `urlsplit`, never displayed).

## 5. Sentry

One sentry per repo, same rule:
- engine `tests/sentry/safe_output/test_locator_grammar_single_copy.py`, allowlist
  `tests/sentry/safe_output/locator_grammar_allowlist.toml`;
- CLI `tests/sentry/test_locator_grammar_single_copy.py`, allowlist
  `tests/sentry/locator_grammar_allowlist.toml`.

It walks every `.py` file under `src/` (the list comes from the walk, never a hand list) and flags:
1. a call to `re.compile`, `re.match`, `re.search`, `re.fullmatch`, `re.sub`, `re.subn`,
   `re.findall`, `re.finditer` or `re.split` whose pattern is a string literal containing `://`,
   `:/`, `:\\`, or `@` (including inside a character class);
2. a string literal `"://"`, `":/"`, `"@"` or `"\\\\"` as the first argument of `split`, `rsplit`,
   `partition`, `rpartition`, `find`, `rfind`, `index`, `rindex`, `startswith`, `endswith`, `count`
   or `replace`, or as the left operand of `in` / `not in`;
3. an attribute read of `.netloc`, `.username`, `.password` or `.hostname`;
4. a call to `urlsplit`, `urlparse` or `urllib3`/`yarl`/`furl`/`rfc3986` URL constructors.

Imports are resolved through aliases (`import re as r`, `from urllib.parse import urlsplit as u`)
with the engine's existing `tests/sentry/_call_resolution.py`; the CLI gets the same resolution in
its sentry helper. The boundary module `decoy_engine/_locator.py` is exempt. Every other hit needs
an allowlist row `(module, function, rule) -> count, reason`. Counts may only fall (existing
`_ratchet.py` in both repos). The CLI sentry also fails on any import of a private engine module
for this purpose (covered today by `test_engine_internal_boundary.py`; no new rule needed).

Mutations the gate runs on the sentry (seeded in a scratch module under `src/`, then removed):
- add `if "@" in text:` -> red;
- add `re.compile(r"[a-z]+://")` -> red;
- add `import re as r; r.sub(r"[^@]+@", "", t)` -> red (alias resolution);
- add `from urllib.parse import urlsplit as u; u(t).netloc` -> red;
- delete one allowlisted site -> the ratchet reports the lower count and fails until the row shrinks.

Surface canary tests (the runtime half): one parametrized test per repo runs every `carries=true`
row through every surface in section 4 and asserts `CANARY` is absent from the output (text, JSON,
YAML, report dict, manifest file, log records captured with `caplog`).

## 6. Slices

Order: E-S1, then engine release, then E-S2 (#808 rebased) and C1 in parallel. #412 is decided by O3.

### E-S1 (engine): the recognizer, the case table, the sentry (R2)

Branch `feat/locator-scan` off engine main. Allowed files: `src/decoy_engine/_locator.py` (new),
`src/decoy_engine/safe_output/__init__.py`, `src/decoy_engine/fileaccess/_read.py` (`shown`),
`.importlinter` and `tests/sentry/layout/test_import_layers.py` (add `_locator` to the bottom tier
and the snapshot), `tests/fixtures/locator_credentials/cases.json`, `tests/unit/safe_output/test_locator.py`,
the sentry and allowlist, `tests/unit/fileaccess/` test for `shown`, CODEMAP (safe output row and
bottom-tier leaf), `docs/security/file-access-policy.md` (one paragraph on `shown`),
`changelog.d/locator-scan.md`, compatibility contract note for the three new `safe_output` names.

Failure modes first:
- F1: a carries-true row leaks through `shown` (leading space, one-letter scheme, backslash URL,
  quote in password, embedded `dsn=`, folded scheme).
- F2: a clean row is flagged (`//host/key?`, `\\?\UNC\...`, `C://foo@bar`, `s3://b/user@x/f`), which
  would refuse a valid corpus at compile.
- F3: text outside a redacted span changes (case, separators, dropped directory text).
- F4: detector and redactor disagree (`carries_credentials` true with nothing removed).
- F5: the sentry misses an aliased or newly added copy.
- F6: `fileaccess.shown` under a strict policy starts returning locator text (it must still return
  the encoded field key).

Acceptance tests:
- AT-1 (F1, F2): table-driven over `cases.json`: `kind`, `shown`, `carries`, `origin_shown` per row.
- AT-2 (F3): span-replacement property over rows and Hypothesis inputs.
- AT-3 (F4): idempotence property; `carries_credentials == (shown != input)` for every generated input.
- AT-4 (F6): `shown` under ambient returns `.shown` for each row; under `RootedFileAccess` returns
  the encoded key for each row.
- AT-5 (F5): the sentry passes on the tree and fails on each seeded bypass in section 5.
- AT-6: `decoy_engine.__all__` unchanged (PROP-SURFACE guard green); `safe_output.__all__` gains
  exactly three names.

Required mutations (core redaction logic), each turns a named row red:
drop the leading-whitespace strip (`leading-space-net`); require 3+ scheme characters
(`leading-tab-url`) or allow 1 (`drive-at-dir`); end the authority at `'` (`url-quote-in-pass`);
use the first `@` instead of the last (`url-userinfo` variant with `@` in password, add row
`url-at-in-pass` `https://u:p@CANARY@h/a`); flag empty query (`net-empty-query`); read `?` in
`\\?\` as a query (`ext-unc`); drop backslash-after-scheme (`backslash-url`); lowercase output or
rewrite `\` (`drive-at-dir`, `unc`); drop D4's invalid-port rule (`slash-in-pass`); drop D7's
colon refinement (`one-letter-creds`).

Tests: T0 per edit through `~/bin/vm-run engine`; T1 per commit. Escalation trigger: a new public
package name (frozen-contract adjacent), so the gate runs the full engine suite once on the slice
head against the saved main baseline.

After merge: cut an engine patch release (pre-release, no per-release confirm needed) so the CLI
can pin it.

### E-S2 (engine): #808 rebased onto E-S1 (R2, already in flight)

#808 rebases onto main after E-S1. Changes on #808:
- delete its `_locator.py` grammar and the `fileaccess` export of `without_url_credentials`; import
  `scan_locator` from `decoy_engine._locator`;
- plan check: `_config_json` traversal (tuples), `scan_locator(...).carries_credentials`, import via
  `plan.checks` public names;
- D12 name rule in `validate_code_set_config` (or the O2 fallback);
- `_publishable` uses the D6 origin form; delete the `@?#` tuple;
- the existing `test_corpus_label_single_formatter.py` sentry stays and now also checks
  that `_publishable` and `_corpus_label` call `scan_locator`.

Failure modes and acceptance tests (one red-first test per Codex finding at `b05773146`):
- AT-808-1: `  //svc:CANARY@host/key` and `x://svc:CANARY@host/key` as `corpus_source`: compile
  refuses with `code_set_corpus_source_credentials`; `verify_corpus(...).path` has no `CANARY`.
- AT-808-2: the same fixture with `columns` as a tuple: compile refuses; `plan_to_yaml` never runs
  with `CANARY`.
- AT-808-3: `study?token=CANARY` refused by `CodeSetConfig.from_dict` and by compile with the same
  code (O2 default); `ICD@2026` accepted by both and shown as is by `describe_loaded_corpus`.
- AT-808-4: `//host/key?`, `//host/key#` and `\\?\UNC\server\share\corpus.parquet` compile.
- AT-808-5: provenance `source` `https://files.example/s/CANARY` publishes
  `https://files.example/<redacted>` in `report.provenance["source"]` and in evidence.
- AT-808-6: the canary surface test over every carries-true row through compile, `plan_to_yaml`,
  `verify_corpus`, `describe_loaded_corpus`, provenance and captured logs.
Mutations: route the plan check back to its own walker (AT-808-2 red); remove the D12 check from
`from_dict` but keep it in compile (AT-808-3 red); publish provenance via `.shown` instead of
origin (AT-808-5 red).

### C1 (CLI): consume the engine recognizer (R2)

Branch `fix/cli-locator-scan` off CLI main (after #412 merges, or stacked on it; see O3).
Repin the engine to the E-S1 release with the full engine repin checklist (compat, fences, FROZEN,
docs, `PIN_PREFIX`, Dockerfile ARG, catalog), plus the new `cases.json` copy and SHA-256 pin.
Route the four surfaces in section 4 and delete `io/_display.py` and `_layout._URL_PATH`.
Add the CLI sentry and allowlist.

Failure modes and acceptance tests (one red-first test per Codex finding at `c6f8d66d`):
- AT-C1-1: `dsn=https://u:foo'CANARY@h/a` and `https:\\u:CANARY@host\file` as a source path:
  `decoy validate` and `decoy validate preflight`, human and `--json`, contain no `CANARY`.
- AT-C1-2: `C://foo@bar/data.csv` is shown byte for byte; `C:\foo@bar\data.csv` and
  `/tmp/a:b@c/f` too.
- AT-C1-3: `build_manifest` with a source `https://u:CANARY@h/a.csv` (including the `Path`-folded
  spelling): `input_fingerprints[...]["path"]` has no `CANARY`; `decoy report show` on that manifest
  has none.
- AT-C1-4: `decoy report show` on a manifest written before C1 that holds a credential URL prints
  it redacted (read path).
- AT-C1-5: the canary surface test over every carries-true row from the vendored table, through all
  four surfaces.
- AT-C1-6: the vendored `cases.json` matches its SHA-256 pin.
- AT-C1-7: the CLI sentry passes and fails on each seeded bypass.
Mutations: record `str(src_path_str)` again in the URL branch (AT-C1-3 red); render
`info["path"]` raw in `report show` (AT-C1-4 red); change one byte of the vendored table (AT-C1-6 red).

Tests: T0/T1 via `~/bin/vm-run cli`. Escalation trigger: dependency pin change, so the gate runs the
full CLI suite (`gates.sh --full`) once on the slice head against the saved main baseline.

No CLI-local copy of the grammar at any point. Until the engine release is pinned, the CLI keeps
main's behavior.

### #412 (CLI split) handling

Recommended (O3 option A): #412 stays a behavior-identical refactor. It drops its redaction commits
(`f79cf7cc`, `d702a325`, `2c20943b`, `e2b595e0` and the `_display.py` parts of later commits) so the
split prints exactly what main prints, with golden parity. The pre-existing source-path leak is
recorded in the PR body as owned by C1, and C1 stacks on #412. Codex scope for #412's next round
names this split of responsibility.

Option B: #412 holds until the engine release, then takes C1's changes in the same PR.

## 7. Risks and open items

- The D7 refinement depends on `:` being illegal in Windows directory names. An NTFS alternate data
  stream (`file:stream`) is only legal in the last component, which is after the authority, so it
  cannot trigger D7.
- D4's invalid-port rule may redact a legal but unusual locator; the cost is a less readable message,
  never a leak.
- Bearer secrets in the path of a configured locator stay visible (D6). This is documented in
  `docs/security/file-access-policy.md`.
- Release sequencing: C1 depends on an engine release. If the release slips, the CLI leak (pre-existing
  on main) stays until it ships.

## 8. Owner questions

- O1. Persisted evidence (`input_fingerprints`, verify report `path`) for a remote URL: keep the path
  under D6 (recommended, the user's own artifact and config), or publish origin only like provenance?
- O2. Narrow `code_set` names to the closed label grammar in D12 (recommended, fail closed), or keep
  arbitrary names and show them through `scan_locator`?
- O3. #412: merge as a pure refactor with the pre-existing leak owned by C1 (recommended, option A), or
  hold #412 for the engine release (option B)?
