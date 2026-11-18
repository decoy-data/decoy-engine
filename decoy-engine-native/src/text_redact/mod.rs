//! Span-detection kernel for `text_redact` (C6c-ii + lookaround port), with per-cell ASCII-domain
//! routing.
//!
//! The eight lookaround-free detectors (`email`, `us_phone`, `pan`, `iban`, `ipv4`, `icd10`,
//! `npi`, `url`) run here as linear-time `regex` crate scans with explicit ASCII character
//! classes (`(?-u)` / `(?i-u)`), plus the five ported validators. The three lookaround/
//! backtracking detectors (`ssn`, `us_zip`, `street_address`) use Python lookahead/lookbehind and
//! ordered-alternation backtracking that the linear-time `regex` crate cannot express, so they run
//! as hand-written byte scanners (plan 2, "moving them to Rust via an explicit advancement search
//! is a possible later slice" -- this is that slice). `fancy-regex` was tried first and rejected:
//! its backtracking engine is 1.6-2.6x SLOWER than Python's C `re` on these patterns, which erases
//! the native win and fails the plan's latency floor on the lookaround-only workload (7.7); the
//! scanners instead beat Python. Every scanner reproduces its Python pattern's exact finditer
//! semantics (leftmost, non-overlapping, greedy with the same ordered-alternation precedence),
//! verified span-for-span against the oracle by a large differential corpus
//! (`tests/native/test_c6c_ii_text_redact_rust.py`, the byte-parity gate).
//!
//! All eleven run ONLY on cells in the ASCII-safe domain (every code point < 0x80 AND none in
//! 0x1c-0x1f). There Python's `\d`/`\s`/`\w`/`\b`/ASCII-case-fold constructs coincide with the
//! scanners' ASCII byte predicates: `\d` is `[0-9]`, `\w` is `[0-9A-Za-z_]`, `\b` is the
//! transition between them, ASCII case-fold is `A-Z`<->`a-z`, and `\s` is `[ \t\n\x0b\x0c\r]` --
//! Python `\s` would also include 0x1c-0x1f, the exact code points the predicate excludes (plan
//! 2.1/2.2; backed by the class-level enumeration in 7.4). So the Rust candidate list equals
//! Python's `finditer`+validator list span-for-span, and the full output stays byte-identical.
//!
//! Per cell the kernel returns either the candidate list `[(detector_index, start, end), ...]`
//! in `finditer` order with code-point (scalar-value) offsets, OR `None` meaning "ineligible,
//! Python must handle this cell" (non-ASCII, a 0x1c-0x1f separator, a lone surrogate, or a
//! non-string object). `None` is distinct from `[]` (eligible, no match).
//!
//! Established methodology: the `regex` crate's per-pattern `find_iter` (non-overlapping,
//! leftmost-first, matching Python's `re.finditer` on the lookaround-free patterns) and, for the
//! three lookaround patterns, hand scanners that replay Python `re`'s leftmost/greedy/ordered-
//! alternation advancement directly over ASCII bytes. Validators port the executable behavior of
//! `pre-scan/_validators.py` (the reference), not an idealized standard: Luhn (ISO/IEC 7812-1) with
//! the module's normalization, NPI (CMS Luhn over the 80840 prefix), ICD-10 chapter-range table,
//! IBAN (ISO 13616 incremental mod-97), IPv4 octet range.

mod catalog;
mod detect;
#[cfg(feature = "extension-module")]
mod pyboundary;
mod scanners;
mod validators;

#[cfg(test)]
mod tests;

pub use catalog::{CATALOG_LEN, CATALOG_VERSION, SUPPORTED_IDS};
pub use detect::{candidates_for_cell, is_eligible};
#[cfg(feature = "extension-module")]
pub(crate) use pyboundary::register;
