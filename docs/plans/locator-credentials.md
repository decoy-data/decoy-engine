# LOCATOR-CREDS: one recognizer and redactor for credentials in file locators

Status: plan

Risk tier: R2 (security and privacy logic, new public names the CLI consumes, cross-repo contract).
Gate: Dennis then Codex on this plan; Codex (and Dennis for E-S1 and C1) on each slice.

Rules consulted: 00-universal, risk-and-exceptions, development-loop, cross-cutting-concerns,
architecture, security, testing ("Test depth"), api-and-compatibility, reuse-first,
catalogs/recurring-defects (classes 5, 6, 10, 11). Memories: value-free class recurs (F31), best
practice becomes a sentry, root cause not patch, engine repin checklist, engine release bump freely
pre-release.

Base: engine `origin/main` `393f0d47c`; CLI `origin/main` (pins engine 0.28.3).
Inputs: engine PR #808 at `b05773146` (`feat/code-set-native-s1`), CLI PR #412 at `c6f8d66d`
(`refactor/cli-split-preflight`), their Codex reviews, and Dennis R1 on this plan
(PASS-WITH-FIXES: 4 HIGH, 6 MEDIUM, 5 LOW, all addressed in this revision).

Owner decisions (2026-11-25, recommended defaults taken):
- O1: persisted evidence keeps the configured path, shown through the recognizer (D6).
- O2: `code_set` names use the closed label grammar (D12).
- O3: #412 merges as a pure refactor; C1 owns the pre-existing CLI leak (section 7).

## 1. Problem and pinned guarantee

Two PRs failed Codex review on the same defect class. Each wrote its own parser for "does this
locator carry credentials, and how is it shown without them". There are now four copies of the
scheme and `@?#` grammar:

| Copy | Where | What it gets wrong |
|---|---|---|
| Engine locator scanner | #808 `src/decoy_engine/_locator.py` | Misses leading spaces (`  //svc:CANARY@host/key`) and one-letter schemes (`x://svc:CANARY@host/key`). Flags clean `//host/key?`, `//host/key#` and `\\?\UNC\server\share\x.parquet`. Rewrites backslashes outside the secret. |
| Engine name and provenance marks | #808 `plan/checks/_code_set_locator.py:20` (`_NAME_MARKS`), `transforms/_codeset/_checks.py:278` (`_publishable`) | Plan check and runtime disagree: `study?token=CANARY` passes `CodeSetConfig.from_dict` and reaches `describe_loaded_corpus`, while compile rejects `ICD@2026`. Provenance publishes `https://files.example/s/CANARY` whole. Plan traversal skips tuples. |
| Engine endpoint check | main `config/_sources.py:303` (`("@", "?", "#", "%40", "%3f", "%23")`), `:307` `urlsplit`, `:312` `.hostname` | Not a leak: it refuses an S3 `endpoint_url` with userinfo or a query. It is a separate marker set and stricter than the recognizer by design (section 4). |
| CLI display redactor | #412 `src/decoy/cli/io/_display.py` | `dsn=https://u:foo'CANARY@h/a` leaks after the quote; `https:\\u:CANARY@host\file` leaks; `C://foo@bar/data.csv` shows as `c://bar/data.csv`. On main, `build_manifest` stores the credential-bearing source in `input_fingerprints`, `decoy report show` prints it, and other CLI messages print the source path (section 4, C1 inventory). |

Guarantee, when the last slice merges:

1. Exactly one function in the two repos decides whether a locator carries credentials and what its
   display and publish text is: `decoy_engine.safe_output.scan_locator`. Every surface in section 4
   calls it, directly or through one CLI helper. The plan check and every display read the same
   `LocatorScan`, so they cannot disagree.
2. Display text is the input with zero or more spans replaced by `<redacted>`. No character outside
   a replaced span changes: no case folding, no separator rewriting, no dropped text.
3. A sentry in each repo is a tripwire for new parsing of `://`, `//`, `@`, or URL userinfo outside
   the boundary. It catches the forms listed in section 5 (the spellings a contributor writes by
   habit, per recurring-defects class 5); it is not a proof that no other form exists. Its runtime
   half is the canary surface tests, which run every credential row of the case table through every
   routed surface and assert the secret never appears.
4. One case table (section 3) drives the recognizer unit tests and the surface tests in both repos.

Non-goals:
- No secret detection in free text beyond URL structure (no gitleaks-style keyword rules).
- No percent-decoding for display (D13). The publish form fails closed on percent-encoded authorities.
- No change to `fileaccess.redact_locators` (pair replacement of a known locator in third-party
  text). Its display side already comes from `fileaccess.shown`, which now calls the recognizer.
- No root `decoy_engine.__all__` addition (PROP-SURFACE). The public names go on the
  `decoy_engine.safe_output` package, which the CLI already imports (`yaml_error_text`,
  `validation_problems`). The CLI consumers in section 4 justify them.
- No merge of the engine and CLI call-resolution helpers (section 5).
- Deliberate sentry evasion (`eval`, `getattr` with built strings, `codecs`) is V2-LOG.
- No platform edit (platform parked on engine 0.18.0).

## 2. Established solutions

Search run: RFC 3986 and the WHATWG URL Standard; the CPython `urllib.parse` source in the local
3.12 stdlib; pip, SQLAlchemy, git, fsspec, adlfs, OpenSSH and rclone documentation and source for how
each recognizes and redacts URL credentials; W3C TAG capability-URL guidance and Referrer Policy; the
Microsoft Windows path-format reference. In the codebase: the four copies above, `fileaccess.shown`,
`fileaccess.redact_locators`, `config/_targets.py`, `secret_providers/_types.py`, and the existing
sentry helpers (`tests/sentry/_ratchet.py`, `_call_resolution.py`, the CLI `_defect_scan.py`).

| Source | Recognition rule | Redaction rule | What we take |
|---|---|---|---|
| RFC 3986 section 3.2, 3.2.1, 3.2.3, 7.5 | `authority = [ userinfo "@" ] host [ ":" port ]`; authority ends at the next `/`, `?` or `#`; `port = *DIGIT`. `user:password` is deprecated. | 7.5: do not render the text after the first `:` in userinfo as clear text. | Authority ends at `/ ? #`. Userinfo is a credential. A non-digit port means the authority is not a host. |
| WHATWG URL Standard | Strips leading and trailing C0 control or space, removes tab and newline. For special schemes `\` is a path separator like `/`. Userinfo ends at the last `@` in the authority. | n/a | Strip leading C0/space before classifying. Treat `\` as `/` after a scheme. Last `@` ends userinfo. |
| CPython `urllib.parse` | `urlsplit` netloc runs to the first `/?#` and does not stop at `\`; `_userinfo` is `netloc.rpartition('@')`. Strips leading C0/space (`_WHATWG_C0_CONTROL_OR_SPACE`) and removes `\t\r\n` (`_UNSAFE_URL_BYTES_TO_REMOVE`), verified locally. | n/a | Same split. Because urllib and WHATWG disagree on `\`, D3 computes both and redacts the longer userinfo. |
| pip `redact_auth_from_url` / `redact_netloc` | urllib split. | Password becomes `****`. A username with no password is masked too, because tokens are often sent as the username. | Mask the whole userinfo by default, user included. Visible mask. |
| SQLAlchemy `URL.render_as_string(hide_password=True)`, `URL.__repr__` | Own DSN parser. | Password becomes `***`; host, port and database kept. | `+driver` schemes are URLs; keep host and path. |
| git `transport_anonymize_url()`, `transfer.credentialsInUrl` (2.41) | Userinfo only when the `@` sits after `://` and before the first `/`. | Strips `user:pass@`. `credentialsInUrl=die` refuses a configured URL with a plaintext password. | `@` after a valid authority is path text. Refusing at config time has precedent. |
| fsspec `split_protocol`; adlfs | `if len(protocol) > 1:  # excludes Windows paths`, verified in the installed source. adlfs reads `abfs://container@account...` with the container in the userinfo slot. | n/a | A one-letter scheme is a drive letter. Azure userinfo without `:` is a container name. |
| OpenSSH / paramiko | `sftp://user@host/path`: the user names the account; the secret is a key or agent. | n/a | sftp userinfo without `:` is an account name. |
| rclone | Secrets live in config, not the path. `rclone config redacted` redacts by known secret field. | By field. | Keep secrets out of locators; the plan check message says so. |
| W3C TAG "Good Practices for Capability URLs"; Referrer Policy `strict-origin` | A capability URL carries its secret in the path. | Send only the origin to third parties. | Third-party text (provenance) is published as origin only. |
| Microsoft "File path formats on Windows systems" | `C:\`, UNC `\\server\share\`, DOS device paths `\\?\` and `\\.\`. | n/a | `\\?\` and `\\.\` are a device prefix; their `?` and `.` are not a query or host. |

Pattern chosen: parse the authority the way RFC 3986, WHATWG and urllib agree; where they disagree
(`\`), take the reading that redacts more. Mask the whole userinfo and any non-empty query or
fragment with a visible `<redacted>`, as pip and SQLAlchemy do, except the account or container name
for the schemes in D3. Refuse a credential-bearing locator at plan time, as git's
`credentialsInUrl=die` does. Classify a one-letter scheme as a drive letter, as fsspec does, with the
D7 refinement. Publish third-party URLs as origin only, as Referrer Policy does, and withhold
third-party text that cannot be reduced to an origin.

Why custom code remains: no maintained library covers the input. `urllib.parse` splits one URL that
starts at character zero; it does not find URLs embedded in a value, does not know drive letters,
DOS device paths or UNC paths, does not treat `\` as WHATWG does, and raises on some malformed ports.
pip and SQLAlchemy redact only well-formed URLs and are not dependencies we would add for this. The
leaf uses `urllib.parse` reasoning (the same split points, last `@`) and adds only the classification
and span bookkeeping, about 250 lines of stdlib code.

## 3. The recognizer and redactor

### Placement

| Item | Path | CODEMAP line | Sits beside |
|---|---|---|---|
| Grammar (stdlib only) | `src/decoy_engine/_locator.py` | bottom-tier leaf modules (`_canonical`, `_value_free`); `.importlinter` tiers contract gains `_locator` | `_value_free.py` |
| Public face | `src/decoy_engine/safe_output/__init__.py` (`scan_locator`, `LocatorScan`, `LocatorKind` in `__all__`) | "safe output boundary is `src/decoy_engine/safe_output/_<output concern>.py`" (line 267) | `yaml_error_text`, `validation_problems` |
| Unit and property tests | `tests/unit/safe_output/test_locator.py` | safe output tests in `tests/unit/safe_output/` | existing safe_output tests |
| Case table | engine `tests/fixtures/locator_credentials/cases.json`; CLI `tests/fixtures/locator_credentials/cases.json` (vendored) plus `SHA256` | test fixtures | other fixture sets |
| Engine sentry | `tests/sentry/safe_output/test_locator_grammar_single_copy.py`, baseline `tests/sentry/baselines/locator-grammar.json`, row in `scripts/dev/sentry_registry.toml` | safe output sentries in `tests/sentry/safe_output/` | `_tagger.py` |
| CLI sentry | `tests/sentry/test_locator_grammar_single_copy.py`, baseline `tests/sentry/baselines/locator-grammar.json`, row in `scripts/dev/sentry_registry.toml` | CLI sentries | `test_engine_internal_boundary.py` |
| CLI helper | `src/decoy/cli/io/_locator_display.py` (`shown_locator`), exported from `decoy.cli.io` | CLI display helpers in `io/` | replaces `io/_display.py` |

`plan` must call the grammar and the `policy-direction` import contract forbids `plan -> fileaccess`,
so the grammar cannot live in `fileaccess`. A stdlib-only leaf adds no import cost to a capped
worker. Engine modules import from `decoy_engine._locator`; the CLI imports only
`decoy_engine.safe_output`.

### Signature

The engine supports Python 3.10 (`requires-python = ">=3.10,<3.13"`), so the enum is
`(str, Enum)`, not `StrEnum`.

```python
class LocatorKind(str, Enum):
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
    origin: str | None         # "scheme://host[:port]" or "//host" of the leading URL/NETWORK span;
                               # None for other kinds and when the authority is not a valid host
    published: str | None      # third-party publish form (D6); None means withhold the value

def scan_locator(text: str) -> LocatorScan: ...
```

One entry point, one result. The plan check reads `.carries_credentials`; displays read `.shown`;
classifiers read `.kind`; provenance reads `.published`. `carries_credentials` is defined as
`shown != text`, so a detector that says "yes" while the redactor removes nothing cannot happen by
construction. The function never raises on `str` input and does no I/O or decoding.

### Decisions

D1. Leading whitespace. Classify after stripping leading C0 control or space (WHATWG, urllib). The
stripped prefix is kept in `shown`.

D2. Scheme and URL starts. A scheme is `[A-Za-z][A-Za-z0-9+.-]+` (two or more characters) followed
by `:` and a separator (`/` or `\`). The scanner finds every URL start in the value, not only the
first:
- at the start of the value (after D1): any such scheme with one or two separators. One separator
  covers `pathlib` folding (`https://` becomes `https:/`) for every scheme, which also covers folded
  spellings in manifests written before C1;
- elsewhere: after whitespace, `=`, a quote, `(`, `,`, `;`, `<`, or a path separator. After a path
  separator only a scheme with two separators, or a known remote scheme with one, counts, so
  `/tmp/a:/b@c/f?x=1` stays LOCAL. The known remote set (`http(s)`, `s3(a)`, `gs`, `gcs`, `abfs(s)`,
  `az`, `wasb(s)`, `ftp(s)`, `sftp`, `hdfs`, `webhdfs`, `smb`, `r2`, `oss`) is held once in
  `_locator.py`.

Each URL start opens a span. The span's authority runs as in D3. After the authority the path ends
at whitespace or the next URL start; a query or fragment runs to the end of the value (fail closed).

D3. Authority and userinfo. The authority runs from after the separators to the first `/`, `?`, `#`
or `\` (WHATWG reading). Quotes and spaces do not end it. Userinfo is everything before the last `@`
in the authority. The scanner also computes the urllib reading, where `\` does not end the
authority, and redacts the longer of the two userinfo spans: `https://h\u:CANARY@x/a` shows
`https://<redacted>@x/a`. The cost is over-redaction of a URL with `\` and `@` in its path, which
the plan check then refuses; that is the safe direction.

Userinfo is replaced whole, user included (pip), with two exceptions where a userinfo without `:` is
an identifier, not a secret, and is kept:
- `abfs`, `abfss`, `wasb`, `wasbs`: the container name (`abfss://container@acct.dfs.core.windows.net/p`);
- `sftp`: the account name (`sftp://etl@files.example/in/a.csv`); the key is held in connection config.
A userinfo with `:` is redacted for every scheme. Every other scheme masks a user-only userinfo,
because tokens are sent as the username (`https://TOKEN@github.example`).

D4. Invalid authority, unconditional. After userinfo is removed, the rest of the authority must be a
host: a bracketed IP literal or a reg-name (`[A-Za-z0-9._~%!$&'()*+,;=-]*`), then optionally `:` and
digits only. If it is not, everything after the separators is replaced (`https://<redacted>` or
`//<redacted>`), and `origin` and `published` are None. The rule does not need a later `@`. It
closes a password that holds `/`, `?`, `#` or `\` (`https://u:pa#CANARY@h/a`,
`https://u:pa?CANARY@h/a`, `https://u:pa/CANARY@h/a`), a password with no `@` at all
(`https://u:CANARY`), and the NETWORK form (`//svc:CANARY/key`).

D5. Query and fragment. A non-empty query becomes `?<redacted>`; a non-empty fragment becomes
`#<redacted>`. An empty `?` or `#` is kept and does not set `carries_credentials`. Refusing every
non-empty query is deliberate, including harmless ones such as `s3://b/k.parquet?versionId=3`: the
recognizer cannot tell a version id from a token, and the plan check message tells the user to pass
the version through config instead.

D6. Bearer in path and the publish form.
- Configured locators (the user wrote them): `shown` keeps the path. The user needs to know which
  file a message names, and the text is already in their YAML. Owner decision O1: persisted evidence
  (`input_fingerprints`, verify report `path`) stores `shown`, path included.
- Third-party text (provenance fields read from a corpus file) uses `published`, which fails closed:
  - URL or NETWORK value: each URL span is replaced by its origin plus `/<redacted>` when anything
    follows the authority, otherwise by its origin. Text between spans other than whitespace makes
    the value withheld.
  - Withheld (`None`) when: any span has an invalid authority (D4); an authority contains `%`
    (percent-encoded userinfo, D13); the value is LOCAL or DRIVE and holds a URL span or redacted
    userinfo; or the value holds an `x:y@` userinfo shape anywhere (scp style
    `svc:CANARY@host:/data`, `/tmp/a:b@c/f`).
  - LOCAL, DRIVE or DEVICE text with none of these: `published == shown`.

D7. Drive letters and one-letter schemes. One letter, `:`, then a separator is DRIVE (fsspec).
Nothing is rewritten: `C://foo@bar/data.csv` and `C:\foo@bar\data.csv` are unchanged. Refinement:
when the first segment after the separators contains `:` before an `@`, it is userinfo, because `:`
is not legal in a Windows directory name. `x://svc:CANARY@host/key` shows `x://<redacted>@host/key`.

D8. DEVICE paths. `\\?\`, `\\.\`, `//?/` and `//./` prefixes are recognised first. Their `?` and `.`
belong to the prefix. The rest is a DRIVE or UNC path: no query, no fragment, no userinfo. Always
unchanged.

D9. NETWORK paths (`//` or `\\` with no scheme). The first segment is an authority under D3, D4 and
D5. `\\server\share\x.parquet` is unchanged.

D10. Embedded URLs. Covered by D2: every URL start in a value opens a span, so
`dsn=https://u:foo'CANARY@h/a` (LOCAL) shows `dsn=https://<redacted>@h/a`, and a value with two URLs
has both redacted.

D11. Separators and case. Only text inside a replaced span changes. Backslashes stay backslashes,
case stays as written. This replaces the #808 rewrite of `\` to `/` and the CLI lowercasing.

D12. Corpus names (`code_set`), owner decision O2. A name is a label, not a locator. Closed label
grammar `[A-Za-z0-9][A-Za-z0-9 _.:@+-]{0,127}` matched with `re.fullmatch` (recurring-defects
class 1), checked once in `validate_code_set_config`, so both `CodeSetConfig.from_dict` and compile
go through it. `:` and `@` are allowed on purpose (`ICD:10` and `ICD@2026` are real release labels).
`/`, `\`, `?`, `#`, controls and URLs are refused with a value-free message. A label cannot open a
URL span under D2 because `/` and `\` are refused.

D13. Percent-encoding. `shown` does not decode (urllib does not decode before splitting).
`//svc%3ACANARY%40host/key` has no literal `@`, so `shown` is unchanged; this is a characterization
row (Codex rated it V2-LOG). `published` withholds it (D6).

### Case table

`cases.json` is a list of rows `{id, input, kind, shown, carries, origin_shown, note}`.
`origin_shown` is the expected `published` value; `null` means withheld. Inputs use the synthetic
secret `CANARY`. The table has 47 rows at plan time; this is the only place the count is stated.

Invariants checked over every row: `CANARY` never appears in `origin_shown`; when `carries` is true,
`CANARY` does not appear in `shown`.

| id | input | kind | shown | carries | origin_shown |
|---|---|---|---|---|---|
| url-plain | `s3://bucket/key.parquet` | url | unchanged | no | `s3://bucket/<redacted>` |
| url-userinfo | `s3://AKIA:CANARY@bucket/key` | url | `s3://<redacted>@bucket/key` | yes | `s3://bucket/<redacted>` |
| url-user-only | `https://CANARY@github.example/r.git` | url | `https://<redacted>@github.example/r.git` | yes | `https://github.example/<redacted>` |
| url-at-in-pass | `https://u:p@CANARY@h/a` | url | `https://<redacted>@h/a` | yes | `https://h/<redacted>` |
| url-quote-in-pass | `https://u:foo'CANARY@h/a` | url | `https://<redacted>@h/a` | yes | `https://h/<redacted>` |
| embedded-dsn | `dsn=https://u:foo'CANARY@h/a` | local | `dsn=https://<redacted>@h/a` | yes | null |
| embedded-space | `see https://u:CANARY@h/a` | local | `see https://<redacted>@h/a` | yes | null |
| two-urls | `https://u:CANARY@h/a s3://k:CANARY@b/c` | url | `https://<redacted>@h/a s3://<redacted>@b/c` | yes | `https://h/<redacted> s3://b/<redacted>` |
| backslash-url | `https:\\u:CANARY@host\file` | url | `https:\\<redacted>@host\file` | yes | `https://host/<redacted>` |
| backslash-dual | `https://h\u:CANARY@x/a` | url | `https://<redacted>@x/a` | yes | `https://x/<redacted>` |
| folded-url | `https:/u:CANARY@host/file` | url | `https:/<redacted>@host/file` | yes | `https://host/<redacted>` |
| folded-any-scheme | `myfs:/u:CANARY@host/file` | url | `myfs:/<redacted>@host/file` | yes | `myfs://host/<redacted>` |
| folded-under-cwd | `/home/x/https:/u:CANARY@h/a` | local | `/home/x/https:/<redacted>@h/a` | yes | null |
| leading-space-net | `  //svc:CANARY@host/key` | network | `  //<redacted>@host/key` | yes | `//host/<redacted>` |
| leading-tab-url | `\tx3://u:CANARY@h/k` | url | `\tx3://<redacted>@h/k` | yes | `x3://h/<redacted>` |
| pass-hash | `https://u:pa#CANARY@h/a` | url | `https://<redacted>` | yes | null |
| pass-query | `https://u:pa?CANARY@h/a` | url | `https://<redacted>` | yes | null |
| slash-in-pass | `https://u:pa/CANARY@h/a` | url | `https://<redacted>` | yes | null |
| invalid-port-no-at | `https://u:CANARY` | url | `https://<redacted>` | yes | null |
| net-invalid-port | `//svc:CANARY/key` | network | `//<redacted>` | yes | null |
| one-letter-creds | `x://svc:CANARY@host/key` | drive | `x://<redacted>@host/key` | yes | null |
| drive-at-dir | `C://foo@bar/data.csv` | drive | unchanged | no | unchanged |
| drive-backslash-at | `C:\foo@bar\data.csv` | drive | unchanged | no | unchanged |
| drive-plain | `C:/data/x.csv` | drive | unchanged | no | unchanged |
| posix-colon-at | `/tmp/a:b@c/f?x=1` | local | unchanged | no | null |
| net-empty-query | `//host/key?` | network | unchanged | no | `//host/<redacted>` |
| net-empty-fragment | `//host/key#` | network | unchanged | no | `//host/<redacted>` |
| unc | `\\server\share\x.parquet` | network | unchanged | no | `//server/<redacted>` |
| ext-unc | `\\?\UNC\server\share\corpus.parquet` | device | unchanged | no | unchanged |
| ext-drive | `\\?\C:\data\x.csv` | device | unchanged | no | unchanged |
| query-token | `https://h/a?token=CANARY` | url | `https://h/a?<redacted>` | yes | `https://h/<redacted>` |
| version-query | `s3://b/k.parquet?versionId=3` | url | `s3://b/k.parquet?<redacted>` | yes | `s3://b/<redacted>` |
| fragment-token | `https://h/a#access_token=CANARY` | url | `https://h/a#<redacted>` | yes | `https://h/<redacted>` |
| at-in-query | `https://h/a?x=u@CANARY` | url | `https://h/a?<redacted>` | yes | `https://h/<redacted>` |
| at-in-path | `s3://bucket/user@example.com/f.csv` | url | unchanged | no | `s3://bucket/<redacted>` |
| bearer-path | `https://files.example/s/CANARY` | url | unchanged (D6 residual) | no | `https://files.example/<redacted>` |
| ipv6 | `https://u:CANARY@[::1]:8080/a` | url | `https://<redacted>@[::1]:8080/a` | yes | `https://[::1]:8080/<redacted>` |
| dsn-driver | `postgresql+psycopg://u:CANARY@db:5432/x` | url | `postgresql+psycopg://<redacted>@db:5432/x` | yes | `postgresql+psycopg://db:5432/<redacted>` |
| abfs-container | `abfss://container@acct.dfs.core.windows.net/p` | url | unchanged | no | `abfss://acct.dfs.core.windows.net/<redacted>` |
| abfs-key | `abfss://container:CANARY@acct.dfs.core.windows.net/p` | url | `abfss://<redacted>@acct.dfs.core.windows.net/p` | yes | `abfss://acct.dfs.core.windows.net/<redacted>` |
| sftp-user | `sftp://etl@files.example/in/a.csv` | url | unchanged | no | `sftp://files.example/<redacted>` |
| sftp-user-pass | `sftp://etl:CANARY@files.example/in/a.csv` | url | `sftp://<redacted>@files.example/in/a.csv` | yes | `sftp://files.example/<redacted>` |
| file-url-at | `file:///tmp/a@b.csv` | url | unchanged | no | `file:///<redacted>` |
| pct-encoded | `//svc%3ACANARY%40host/key` | network | unchanged (D13 characterization) | no | null |
| prov-embedded-bearer | `see https://files.example/s/CANARY` | local | unchanged | no | null |
| prov-scp-userinfo | `svc:CANARY@host:/data` | local | unchanged | no | null |
| empty | `` | local | `` | no | `` |

Builders may add rows; they may not change a row's expected value without a plan delta.

Properties, run over every row and over Hypothesis strategies built from row fragments (fixed seed,
failing examples pinned as rows):
- P1 span replacement: `shown` equals `input` with zero or more spans replaced by `<redacted>`.
- P2 idempotence: `scan_locator(shown).shown == shown` and `scan_locator(shown).carries_credentials is False`.
- P3 consistency: `carries_credentials == (shown != input)`.
- P4 secret composition: draw a secret `s` from text over an alphabet that includes
  `? # / \ ' @ :` and letters, prefixed by a fixed marker `CANARY`. Compose it into each credential
  template (`{scheme}://u:{s}@h/a`, `{scheme}://{s}@h/a`, `//svc:{s}@host/key`,
  `x://svc:{s}@host/key`, `dsn={scheme}://u:{s}@h/a`, `{scheme}://h/a?t={s}`, `{scheme}://h/a#{s}`)
  for schemes drawn from the known set and from random 2+ character schemes, excluding the D3
  identifier schemes for the user-only template. Assert `CANARY` is absent from `shown` and from
  `published`, and `carries_credentials` is True.

Sharing with the CLI: the CLI vendors a byte-identical copy and pins its SHA-256 in
`tests/fixtures/locator_credentials/SHA256`. A CLI test fails when the copy does not match the pin.
The engine repin checklist gains one line: "copy `cases.json` from the new engine tag and update the
pin". No CLI test imports engine test data or a private engine module.

### Design notes and size

- Choke point (cross-cutting-concerns): `scan_locator` is the one decision. Guard: the two sentries
  in section 5. The mutation that must turn each red: a module under `src/` with `if "@" in text:`.
- Deep module (Ousterhout): one function, one frozen result type, one enum; the grammar stays
  private. Callers never see spans or split points.
- One place per fact: the known remote scheme set, the D3 identifier schemes and the marker
  grammar exist only in `_locator.py`. The case table exists once and the CLI copy is hash-pinned.
- No flag arguments: the configured-versus-third-party difference is two fields on one result
  (`shown`, `published`), not a `mode=` parameter.
- Size: E-S1 adds about 250 lines in `_locator.py` (under the engine's 600-line target), about 10
  lines in `safe_output/__init__.py` and `fileaccess/_read.py`, about 350 lines of tests and sentry,
  and three public names on `decoy_engine.safe_output`. E-S2 removes more grammar than it adds. C1
  adds one CLI helper (about 20 lines) and deletes `io/_display.py`.

## 4. Routing every surface

### Engine

| Surface | Today (#808 head) | After |
|---|---|---|
| Plan check `plan/checks/_code_set_locator.py` | Own `_values` walker (dict and list only); `locator_carries_credentials` or `_NAME_MARKS` | Walk with the config traversal in `plan/checks/_config_json.py` (dict, list, tuple, any non-str sequence). `corpus_source` refused when `scan_locator(text.removeprefix("customer:")).carries_credentials`. `code_set` names under D12. Imported through `plan.checks.__init__`, not the private module. |
| `plan_to_yaml` | Copies the locator; protected only by the plan check | Unchanged code; protected by the fixed plan check. Surface test: no carries-true row reaches YAML through compile, `CodeSetConfig.from_dict`, or tuple `columns`. |
| `verify_corpus` (`path`, `problems`) | `_where` -> `fileaccess.shown` -> `without_url_credentials` | `fileaccess.shown` returns `scan_locator(locator).shown` under the ambient policy and the encoded field key otherwise. |
| Corpus error messages (`_where`, `corpus_stat_error`) | as above | as above |
| Provenance `provenance_summary` | `_publishable`: withhold whole on `@?#` | `_publishable(text)` returns `scan_locator(text).published`; `None` withholds the field. |
| `describe_loaded_corpus` `code_set` | `_corpus_label` -> `fileaccess.shown` | Shipped name as is; other names passed D12 at the config boundary, so shown as is. |
| S3 `endpoint_url` validator `config/_sources.py:303-312` | Own marker tuple, `urlsplit`, `.hostname` | Kept and allowlisted (decision below). |

Decision on `config/_sources.py:303-312`: allowlist, do not route. It is a validator, not a display,
and it is stricter than the recognizer: it refuses `%40`, `%3f` and `%23`, which D13 leaves alone in
`shown`, and it requires an http(s) scheme and a host. Routing it through `scan_locator` would weaken
it. E-S1 adds a test that pins the relation: every carries-true http(s) row is also refused by
`_endpoint_is_a_host`, so the validator can never become weaker than the recognizer.

Deleted in the engine: #808 `_locator.py` grammar functions `without_url_credentials` and
`locator_carries_credentials` (and the `fileaccess.__init__` export of `without_url_credentials`),
`_NAME_MARKS`, the `@?#` tuple in `_publishable`, and the `_values` walker in
`_code_set_locator.py`. Kept and allowlisted in the E-S1 baseline, each with a reason:
- `config/_sources.py` `_endpoint_is_a_host` (marker tuple at :303, `urlsplit` at :307, `.hostname`
  at :312): validator, stricter by design.
- `config/_targets.py:182` `_endpoint_identity`: identity key built with `urlsplit`, never displayed.
- `secret_providers/_types.py:180`: refuses a mount URL with `@` or `:`; validation, never displayed.
- `connectors/sftp.py:146-148` (`config.username` read, `"hostname"` and `"username"` dict keys):
  passes typed config fields to paramiko; no parsing of a locator.
- any other site the E-S1 walk finds, each with a reason. The first baseline is created in E-S1, so
  these entries are its starting content; any later addition needs an owner-dated `approved_growth`
  entry.

### CLI

C1 starts with an inventory step: find every site that formats a source or input path into user
output (console, JSON, files, exception text, logs). Method: walk `src/` for f-strings, `%` and
`.format` calls that interpolate a name bound from a source, input or path value (`source`, `src`,
`input`, `path`, `declared_path`, `source_str`, and names assigned from them), plus every `{exc}` or
`str(exc)` interpolation in a function that opens or stats a source; then read each hit. The
inventory is a table in the C1 PR body (file, line, what it prints, fix) and the list that AT-C1-5
parametrizes over. Sites known now:

| Site | What it prints |
|---|---|
| preflight source findings (`preflight/_checks.py:51` on #412; inline on main) | source path, human and `--json` |
| `preflight.py:253` (main numbering) | `{exc}` from opening the source, which repeats the path |
| `evidence.py:287-300` `build_manifest` | `input_fingerprints[...]["path"]` |
| `evidence.py:759` `report show` | `info["path"]` |
| `report/_integrity.py:164` | `--source {source_str} does not match pipeline input.path {declared_path}` |
| `fit/_command.py:405` | source path in a fit message |
| `gen/_fit.py:108` | source path in a generation-fit message |
| `report/_fidelity.py:294` | source path in the fidelity report |
| `project/_scaffold.py:94` | source path written into a scaffolded file |

Route: one CLI helper, `decoy.cli.io.shown_locator(value: object) -> str`, which returns
`scan_locator(str(value)).shown`. It is the only CLI caller of `scan_locator` for display and holds no
grammar. Every inventory site calls it. At `{exc}` sites C1 removes the exception text and prints the
exception type plus the shown locator, because exception text from fsspec, pyarrow or the OS can
repeat the raw locator in any spelling.

`build_manifest`: classify the original spelling before `Path()` folds it:
`scan = scan_locator(str(src_path_str))`. URL or NETWORK: record `scan.shown`, no hash. Otherwise the
current file branch, with `_recorded(...)` also passed through `shown_locator` (catches
`folded-under-cwd`). `report show` passes every stored path through `shown_locator`, so manifests
written before C1 are shown safely; D2 treats a value-start `scheme:/` as a URL for every scheme, so
folded spellings of any scheme in old manifests are covered.

Deleted in the CLI: #412 `io/_display.py` (`_URL`, `_redact_text`, `redact_url`, `redact_urls`) and
its exports from `decoy.cli.io`. Kept and allowlisted, each with a reason and a follow-up row to move
it to `scan_locator(...).kind`: `io/_layout.py:66` `_URL_PATH` (classifier; not rerouted in C1),
`io/_run_outputs.py:126`, `io/_placement.py:238`, `api.py:377`, `ci/contracts.py:171` (all "is this
remote" classifiers); `_outbound.py:179`, `notify.py:460`, `distribution/release_identity.py:76`
(outbound endpoint validation with `urlsplit`, never displayed).

## 5. Sentry

One sentry per repo, same rules:
- engine `tests/sentry/safe_output/test_locator_grammar_single_copy.py`;
- CLI `tests/sentry/test_locator_grammar_single_copy.py`.

Allowlist: the existing ratchet machinery in both repos, not a new file format. Each sentry gets a
JSON baseline under `tests/sentry/baselines/` (`{"sentry_id", "created_in", "entries": {key:
{"reason"}}}`), bound by one `[[sentry]]` row in `scripts/dev/sentry_registry.toml`, and checked by
`tests/sentry/_ratchet.py`. Keys are `<file>::<qualname>::<rule>`. Entries only shrink; a key the
merge base lacks needs an `approved_growth` entry with an owner-dated decision
(`owner YYYY-MM-DD ...`), which the ratchet already enforces (recurring-defects class 11).

Markers: `://`, `:/`, `:\`, `//`, `\\`, `@`.

The walk covers every `.py` file under `src/` (from the walk, never a hand list) and flags:
1. a regex call (`re.compile`, `match`, `search`, `fullmatch`, `sub`, `subn`, `findall`, `finditer`,
   `split`) whose pattern contains a marker, including inside a character class. The pattern may be
   a literal, a module-level `str` constant, or a concatenation or f-string of these; constants are
   resolved through the module constant table.
2. a marker used as text to compare or split on, with markers resolved through module constants as
   in rule 1:
   - the first argument of `split`, `rsplit`, `partition`, `rpartition`, `find`, `rfind`, `index`,
     `rindex`, `startswith`, `endswith`, `count` or `replace`, called bound (`x.split("@")`) or
     unbound (`str.split(x, "@")`);
   - an operand of `in`, `not in`, `==` or `!=`;
   - an element of a tuple, set or list literal (catches marker sets such as `("@", "?", "#")`).
3. an attribute read of `.netloc`, `.username`, `.password` or `.hostname`.
4. a call to `urlsplit`, `urlparse`, or a `urllib3`, `yarl`, `furl` or `rfc3986` URL constructor.

Alias resolution (`import re as r`, `from urllib.parse import urlsplit as u`) and constant resolution
reuse what each repo already has: the engine's `tests/sentry/_call_resolution.py`, and in the CLI the
`ModuleIndex` alias and constant tables in `tests/sentry/defects/_defect_scan.py`. The CLI table is a
known second copy of call resolution; this plan records it and does not add a third. The sentries
keep every rule listed here in both repos (recurring-defects class 5). `decoy_engine/_locator.py` is
exempt. The CLI helper `shown_locator` is not exempt: it holds no marker, so the sentry checks it
like any other module (class 10).

Seeded mutations the gate runs (each in a scratch module under `src/`, then removed); every one must
turn the sentry red:
- `if "@" in text:`
- `re.compile(r"[a-z]+://")`
- `_SEP = "://"` at module level, then `re.compile("[a-z]+" + _SEP)` (constant in rule 1)
- `import re as r; r.sub(r"[^@]+@", "", t)` (alias)
- `from urllib.parse import urlsplit as u; u(t).netloc` (alias, rule 3)
- `str.partition(t, "@")` (unbound method)
- `if t[:2] == "//":` (equality)
- `_MARKS = ("@", "?", "#")` (marker in a tuple literal)
- `any(m in t for m in {"://", "@"})` (marker in a set literal)
- `_AT = "@"` then `t.rpartition(_AT)` (constant in rule 2)
- delete one allowlisted site: the ratchet reports the stale key and fails until the entry goes.

Runtime half (guarantee 3): one parametrized canary test per repo runs every `carries=true` row
through every surface in section 4 and asserts `CANARY` is absent from the output (text, JSON, YAML,
report dict, manifest file, log records captured with `caplog`). In the engine, provenance is also
run over every row and must never contain `CANARY`.

## 6. Slices

Order: E-S1, then engine release, then E-S2 (#808 rebased) and C1 in parallel. #412 merges on its own
as a pure refactor (section 7).

### E-S1 (engine): the recognizer, the case table, the sentry (R2)

Branch `feat/locator-scan` off engine main. Allowed files: `src/decoy_engine/_locator.py` (new),
`src/decoy_engine/safe_output/__init__.py`, `src/decoy_engine/fileaccess/_read.py` (`shown`),
`.importlinter` and `tests/sentry/layout/test_import_layers.py` (add `_locator` to the bottom tier),
`tests/fixtures/locator_credentials/cases.json`, `tests/unit/safe_output/test_locator.py`, the sentry,
its baseline JSON and its `sentry_registry.toml` row, a `tests/unit/config/` test for the
endpoint-validator relation, a `tests/unit/fileaccess/` test for `shown`, CODEMAP (safe output row and
bottom-tier leaf), `docs/security/file-access-policy.md` (one paragraph on `shown` and the D6
residual), `changelog.d/locator-scan.md`, compatibility contract note for the three new names.

Behavior: `scan_locator` returns the table's values for every row; `fileaccess.shown` under the
ambient policy returns `.shown`. This is a visible change on main: engine messages that showed a
credential URL now show it redacted.

Failure modes:
- F1: a carries-true row leaks through `shown` (leading space, one-letter scheme, backslash URL,
  quote, `?`, `#` or `/` in a password, embedded `dsn=`, folded scheme, second URL in a value).
- F2: a clean row is flagged (`//host/key?`, `\\?\UNC\...`, `C://foo@bar`, `s3://b/user@x/f`,
  `abfss://container@acct`, `sftp://etl@host`), which would refuse a valid corpus at compile.
- F3: text outside a redacted span changes (case, separators, dropped directory text).
- F4: detector and redactor disagree.
- F5: `published` carries a secret (bearer path, embedded URL, scp shape, percent-encoded userinfo).
- F6: the sentry misses an aliased, hoisted or newly added copy.
- F7: `fileaccess.shown` under a strict policy starts returning locator text.
- F8: the endpoint validator becomes weaker than the recognizer.

Acceptance tests:
- AT-1 (F1, F2): table-driven over `cases.json`: `kind`, `shown`, `carries`, `origin_shown` per row.
- AT-2 (F3): P1 over rows and Hypothesis inputs.
- AT-3 (F4): P2 and P3.
- AT-4 (F1, F5): P4 secret composition.
- AT-5 (F7): `shown` under ambient returns `.shown` for each row; under `RootedFileAccess` returns the
  encoded key for each row.
- AT-6 (F6): the sentry passes on the tree and fails on each seeded mutation in section 5.
- AT-7 (F8): every carries-true http(s) row is refused by `_endpoint_is_a_host`.
- AT-8: `decoy_engine.__all__` unchanged (PROP-SURFACE guard green); `safe_output.__all__` gains
  exactly three names.

Required mutations (core redaction logic), each turns a named row red:
- drop the leading-whitespace strip (`leading-space-net`);
- require 3+ scheme characters (`leading-tab-url`), or allow 1 (`drive-at-dir`);
- end the authority at `'` (`url-quote-in-pass`);
- use the first `@` instead of the last (`url-at-in-pass`);
- make D4 conditional on a later `@` (`invalid-port-no-at`, `net-invalid-port`);
- drop the urllib reading in D3 (`backslash-dual`);
- stop after the first URL start (`two-urls`);
- flag an empty query (`net-empty-query`);
- read `?` in `\\?\` as a query (`ext-unc`);
- drop backslash-after-scheme (`backslash-url`);
- lowercase output or rewrite `\` (`drive-at-dir`, `unc`);
- drop D7's colon refinement (`one-letter-creds`);
- drop the D3 identifier exception (`abfs-container`, `sftp-user`), or apply it to userinfo with `:`
  (`abfs-key`, `sftp-user-pass`);
- drop the value-start single-separator rule for unknown schemes (`folded-any-scheme`);
- drop a D6 withhold rule (`prov-embedded-bearer`, `prov-scp-userinfo`, `pct-encoded`).

Tests: T0 per edit through `~/bin/vm-run engine`; T1 per commit. Escalation trigger: new public names
on a frozen-contract package, so the gate runs the full engine suite once on the slice head against
the saved main baseline.

After merge: cut an engine patch release so the CLI can pin it.

### E-S2 (engine): #808 rebased onto E-S1 (R2, already in flight)

#808 rebases onto main after E-S1. Changes on #808:
- delete its `_locator.py` grammar and the `fileaccess` export of `without_url_credentials`; import
  `scan_locator` from `decoy_engine._locator`;
- plan check: `_config_json` traversal (tuples), `scan_locator(...).carries_credentials`, import via
  `plan.checks` public names;
- D12 label grammar in `validate_code_set_config`;
- `_publishable` returns `scan_locator(text).published`; delete the `@?#` tuple;
- the existing `test_corpus_label_single_formatter.py` sentry also checks that `_publishable` and
  `_corpus_label` call `scan_locator`.

Label cases (D12, separate from the locator table): accepted `ICD@2026`, `ICD:10`, `icd10cm_2026`,
`ICD-10 CM`; refused `study?token=CANARY`, `a/b`, `a\b`, `x#y`, `https://h/a`, a 129-character name,
a name with a control character, `ICD\n`, the empty string.

Failure modes and acceptance tests (one red-first test per Codex finding at `b05773146`):
- AT-808-1: `  //svc:CANARY@host/key` and `x://svc:CANARY@host/key` as `corpus_source`: compile
  refuses with `code_set_corpus_source_credentials`; `verify_corpus(...).path` has no `CANARY`.
- AT-808-2: the same fixture with `columns` as a tuple: compile refuses; `plan_to_yaml` never runs
  with `CANARY`.
- AT-808-3: every refused label is refused by `CodeSetConfig.from_dict` and by compile with the same
  code; every accepted label is accepted by both and shown as is by `describe_loaded_corpus`.
- AT-808-4: `//host/key?`, `//host/key#` and `\\?\UNC\server\share\corpus.parquet` compile.
- AT-808-5: provenance fields set to each `cases.json` input publish exactly `origin_shown` (or are
  withheld when it is null) in `report.provenance` and in evidence. Includes `bearer-path`,
  `prov-embedded-bearer` and `prov-scp-userinfo`.
- AT-808-6: the canary surface test over every carries-true row through compile, `plan_to_yaml`,
  `verify_corpus`, `describe_loaded_corpus`, provenance and captured logs.
Mutations: route the plan check back to its own walker (AT-808-2 red); remove the D12 check from
`from_dict` but keep it in compile (AT-808-3 red); publish provenance via `.shown` instead of
`.published` (AT-808-5 red).

### C1 (CLI): consume the engine recognizer (R2)

Branch `fix/cli-locator-scan` off CLI main after #412 merges. Steps:
1. Repin the engine to the E-S1 release with the full engine repin checklist (compat, fences,
   FROZEN, docs, `PIN_PREFIX`, Dockerfile ARG, catalog), plus the new `cases.json` copy and its
   SHA-256 pin.
2. Inventory (section 4, CLI). Put the inventory table in the PR body before routing.
3. Add `shown_locator` and route every inventory site through it. Remove exception text at `{exc}`
   sites.
4. Delete `io/_display.py` and its exports.
5. Add the CLI sentry, baseline and registry row, with the allowlist entries listed in section 4.

Failure modes and acceptance tests (one red-first test per Codex finding at `c6f8d66d`):
- AT-C1-1: `dsn=https://u:foo'CANARY@h/a` and `https:\\u:CANARY@host\file` as a source path:
  `decoy validate` and `decoy validate preflight`, human and `--json`, contain no `CANARY`.
- AT-C1-2: `C://foo@bar/data.csv` is shown byte for byte; `C:\foo@bar\data.csv` and `/tmp/a:b@c/f`
  too.
- AT-C1-3: `build_manifest` with a source `https://u:CANARY@h/a.csv` (and its `Path`-folded spelling):
  `input_fingerprints[...]["path"]` has no `CANARY`; `decoy report show` on that manifest has none.
- AT-C1-4: `decoy report show` on a manifest written before C1 that holds a credential URL, in both
  `https://` and folded `myfs:/` spellings, prints it redacted.
- AT-C1-5: the canary surface test over every carries-true row from the vendored table, through every
  site in the C1 inventory (parametrized over the inventory list, not a hand subset), including a
  source whose open raises an exception that quotes the path.
- AT-C1-6: the vendored `cases.json` matches its SHA-256 pin.
- AT-C1-7: the CLI sentry passes and fails on each seeded mutation in section 5.
Mutations: record `str(src_path_str)` again in the URL branch (AT-C1-3 red); render `info["path"]` raw
in `report show` (AT-C1-4 red); restore `{exc}` at `preflight.py:253` (AT-C1-5 red); change one byte
of the vendored table (AT-C1-6 red).

Tests: T0/T1 via `~/bin/vm-run cli`. Escalation trigger: dependency pin change, so the gate runs the
full CLI suite (`gates.sh --full`) once on the slice head against the saved main baseline.

No CLI-local copy of the grammar at any point. Until the engine release is pinned, the CLI keeps
main's behavior.

## 7. #412 (CLI split), decided (O3 option A)

#412 stays a behavior-identical refactor. It drops its redaction commits (`f79cf7cc`, `d702a325`,
`2c20943b`, `e2b595e0` and the `_display.py` parts of later commits) so the split prints exactly what
main prints, with golden parity. The PR body records that the pre-existing source-path leak is owned
by C1. Codex scope for #412's next round names this split of responsibility.

## 8. Risks

- D7 depends on `:` being illegal in Windows directory names. An NTFS alternate data stream
  (`file:stream`) is only legal in the last component, after the authority, so it cannot trigger D7.
- D3's urllib reading and D4 over-redact some legal but unusual locators. The cost is a less readable
  message, or a plan check refusal the user fixes by moving the value into config; never a leak.
- D5 refuses `?versionId=` and similar harmless queries at plan time. Deliberate (section 3).
- Bearer secrets in the path of a configured locator stay visible in `shown` (D6). Documented in
  `docs/security/file-access-policy.md`.
- The sentry is a tripwire (guarantee 3). A parser written in a form outside section 5 passes it; the
  canary surface tests then catch a leak only on routed surfaces.
- Release sequencing: C1 depends on an engine release. If the release slips, the CLI leak
  (pre-existing on main) stays until it ships.

## 9. Owner questions

None open. O1 to O3 were decided on 2026-11-25 (see the header).
