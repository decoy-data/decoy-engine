# Faker pool determinism harness

Slice 0 of the faker-pool widening program
(`docs/plans/plan_faker_determinism_harness_v2.md`). Certifies which
`(faker_type, locale)` pairs pool deterministically -- byte-identical
across fresh processes, fixed `PYTHONHASHSEED` values, and pinned
locale/timezone env -- so a later slice can widen
`POOL_ELIGIBLE_FAKER_TYPES` only onto pairs this harness actually proved
safe. This slice changes no production admission behavior: it does not
touch `pool_eligible` or `POOL_ELIGIBLE_FAKER_TYPES`.

## Files

- `digest_codec.py` -- `_pool_digest`: a versioned, type-tagged,
  length-framed byte encoding for a pool's values (not `repr()`). Callers
  SHA-256 the returned bytes.
- `pool_determinism_worker.py` -- one fresh-process build of one
  `(faker_type, locale, kwargs)` candidate. Calls the real production seam
  (`_faker_pool._build_and_sample_returning_pool`) exactly once, digests
  the returned pool and selected output, and prints one
  `POOL_DETERMINISM_JSON` line.
- `hash_order_probe_worker.py` -- the mandatory synthetic fail-control
  target: its digest is built from Python `set` iteration order over
  strings, which genuinely depends on `PYTHONHASHSEED`. Used only to prove
  the driver can report divergence, never for a real candidate.
- `check_determinism.py` -- the driver. Spawns K=8 fresh workers per
  candidate with pinned env, computes a per-candidate verdict, and
  writes `certified_pairs.json` + `determinism_report.json`. Also owns the
  candidate matrix (10 positive-control types + Tier 1/Tier 2 widening
  candidates from `faker_widening_research.md`, crossed with
  `en_US`/`en_GB`/`fr_FR`/`de_DE`/`es_ES`).
- `golden_digests.json` -- committed cross-time baseline. `--write-golden`
  records it explicitly (a reviewed baseline op, never automatic); the
  default mode asserts every already-recorded candidate's digest still
  matches, and fails loud on drift.
- `certified_pairs.json` -- the current run's certified `(type, locale,
  kwargs)` triples with their agreed digests. This is the input the
  addition slice consumes.

## Running it

```
# from the engine repo root, with the dev venv active
python scripts/faker-determinism/check_determinism.py                # assert against golden_digests.json
python scripts/faker-determinism/check_determinism.py --write-golden  # explicit baseline (re)write
python scripts/faker-determinism/check_determinism.py --types city,job_female --locales en_US --k 3  # a narrow, fast probe
```

`--jobs N` runs N candidates concurrently (each candidate still spawns its
own K sequential subprocesses); the default matrix at K=8 is a genuine
multi-minute run, which is why every determinism test that spawns the sweep
carries the `determinism_harness` marker and is excluded from the default
pytest loop (`pytest -m determinism_harness` runs them explicitly). The
default loop keeps only the version-independent codec, characterization, and
driver-unit tests (including the synthetic hash-order fail-control).

## Reading a candidate's status

- `certified` -- all K runs agreed on both digests, the type is available
  at that locale with no custom override, and the requested locale never
  fell back. This is the only status the addition slice may consume.
- `not_available` -- the Faker method does not exist for that locale.
  Expected and common; not a failure.
- `custom_override` -- a registered custom provider claims the type name
  (never happens for a real candidate in a fresh interpreter with no
  custom providers registered; present for completeness).
- `locale_fallback` -- `make_faker` silently substituted `en_US` for an
  invalid requested locale. Rejected so an accidental fallback can never
  masquerade as a certified pair for the locale that was actually asked
  for.
- `divergent` -- a genuine cross-process digest disagreement. This is the
  finding the harness exists to catch.
- `inconsistent` -- `exact_name_available`/`custom_override_present`/the
  resolved locale itself disagreed across K identical-input runs, a
  stronger signal than an ordinary non-certification.

Determinism-approved is not the same claim as reuse-safe: this harness
proves ONLY that a pool builds and selects identically across processes
and time. Whether reusing a value across rows is semantically acceptable
for a given type is a separate judgment the addition slice still owes.

## The Faker output lock

`output_lock.json` records what Faker gives the engine, for every Faker locale, on both
surfaces the engine uses: the reflected surface (`faker_type` columns: keyword-argument names, a
per-seed digest, a sequential-draw digest) and the adapter surface (the masking `faker` strategy:
a batch digest through `FakerAdapter.generate_batch`), plus a `raw` surface for the calls the
engine makes outside the reflected provider set: the text-mask calls (`text_mask.<detector>`, en_US
only, through `_mask_faker`, which returns the raw method output without the reflected provider's
newline joining) and the anchored date of birth (`dob_anchored`, every locale). An `argumented` surface runs a fixed grid of explicit-argument calls for every Faker method the formula helpers expose (`ARGUMENT_GRID` in `argument_grid.py`: `date_between`, `date_this_*`, `future_date`, `past_date`, `date_of_birth`), and stores each case's argument descriptor beside its digest, so a changed argument is a reviewed diff. A sentry derives the helper methods from `_formula_scope` and fails when one has no grid case. It holds digests and exception class names
only, never a generated value or exception text. A cell is a 64-hex digest, `unstable` (processes
disagree at one clock), or `raises:<Class>[/<Cause>]`. `calendar: true` marks a pair whose digest
differs between the two frozen clocks (2026-10-16 and 2027-11-20): it is stable only because the
clock is frozen.

- Write it: `python scripts/faker-determinism/output_lock.py --write`. This runs only under
  CPython 3.10.20 with the pinned Faker. Read the printed diff, which has seven kinds: changed,
  removed, added, newly reproducible, newly unstable, newly calendar-dependent, no longer
  calendar-dependent. Commit the file in the same PR as the pin change.
- Check it: `tests/sentry/dependencies/test_faker_output_lock.py`. The cells marked
  `faker_output_lock` spawn nine workers (clock A at hash seeds 0 to 7, clock B at seed 0). Each
  takes about 55 CPU seconds, so a full capture is about 170 to 185 seconds on four CPUs. The cells run
  them as two batches, so no cell holds more than about half. They are the required
  `faker-output-lock` CI job on CPython 3.10.20, 3.11.9 and 3.12.7. The reviewed lists in that
  file (`EXPECTED_UNSTABLE`, `EXPECTED_RAISES`, `EXPECTED_CALENDAR`, `ANCHORS`) must equal the
  lock; changing a list needs a reason in the same diff.
- After 1.0: a Faker bump may ship in a 1.x release only when the diff holds added providers or
  locales, newly reproducible pairs, or pairs that stop depending on the calendar. Anything else
  is a 2.0 change. See the compatibility contract, section 3.3.
