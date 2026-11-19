//! The detector catalog: ids, index order, regex patterns, and per-detector validators.

use regex::Regex;
use std::sync::OnceLock;

/// The detector-catalog contract id. Bumps when ANY detector's id, order, label, pattern,
/// validator, OR supported flag changes (plan 4.6). The Python mirror
/// (`_text_redact_kernel.CATALOG_VERSION`) must match, or the loader falls back to full Python.
/// v2 adds `ssn`/`us_zip`/`street_address` to the supported set (the lookaround port).
pub const CATALOG_VERSION: i64 = 2;

/// The eleven supported detector ids, in catalog order. The returned `detector_index` is a
/// position in this array; the Python merge maps it back to the id (and its `[REDACTED:<id>]`
/// label). The first eight are lookaround-free (`regex` crate); the last three are the
/// lookaround detectors (hand-written scanners), appended so the existing eight keep their
/// indices. Keep in sync with `_text_redact_kernel.SUPPORTED_IDS`.
pub const SUPPORTED_IDS: [&str; 11] = [
    "email",
    "us_phone",
    "pan",
    "iban",
    "ipv4",
    "icd10",
    "npi",
    "url",
    "ssn",
    "us_zip",
    "street_address",
];

/// The number of catalog entries, for fixed-size per-detector arrays (e.g. `text_mask`'s
/// per-index `verbatim` map). A const expression so those arrays track the catalog automatically.
pub const CATALOG_LEN: usize = SUPPORTED_IDS.len();

/// How many leading catalog entries are the lookaround-free `regex`-crate detectors; the rest are
/// the hand-written lookaround scanners. The split is an index boundary, not a reordering.
pub(super) const LOOKAROUND_FREE_COUNT: usize = 8;

/// The validator each detector applies to a candidate match (None = regex match is sufficient).
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Validator {
    None,
    Luhn,
    Iban,
    Ipv4,
    Icd10,
    Npi,
}

fn pattern_for(index: usize) -> &'static str {
    // ASCII-restricted translations of the Python `_*_RE` patterns. `(?-u)` turns `\d`/`\s` into
    // their ASCII classes; `(?i-u)` is ASCII case folding (icd10 only). email/url use only literal
    // character classes, so the Unicode flag is irrelevant and the pattern is copied verbatim.
    match index {
        0 => r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", // email
        1 => r"(?-u)(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?[2-9]\d{2}[\s.-]?\d{4}", // us_phone
        2 => r"(?-u)\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{1,7}",  // pan
        3 => r"(?-u)[A-Z]{2}\d{2}[\sA-Z0-9]{11,34}",            // iban
        4 => r"(?-u)(?:\d{1,3}\.){3}\d{1,3}",                   // ipv4
        5 => r"(?i-u)[A-Z]\d{2}(?:\.?[A-Z0-9]{1,4})?",          // icd10
        6 => r"(?-u)\d{10}",                                    // npi
        7 => r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]{4,}", // url
        _ => unreachable!("detector index out of range"),
    }
}

pub(super) fn validator_for(index: usize) -> Validator {
    match index {
        0 => Validator::None,  // email
        1 => Validator::None,  // us_phone
        2 => Validator::Luhn,  // pan
        3 => Validator::Iban,  // iban
        4 => Validator::Ipv4,  // ipv4
        5 => Validator::Icd10, // icd10
        6 => Validator::Npi,   // npi
        7 => Validator::None,  // url
        _ => unreachable!("detector index out of range"),
    }
}

/// The eight lookaround-free compiled detectors, built once. A compile failure is a build-time bug
/// in a pattern above, surfaced as a panic (caught at the PyO3 boundary) rather than a silent wrong
/// result.
pub(super) fn compiled() -> &'static [Regex; LOOKAROUND_FREE_COUNT] {
    static REGEXES: OnceLock<[Regex; LOOKAROUND_FREE_COUNT]> = OnceLock::new();
    REGEXES.get_or_init(|| {
        std::array::from_fn(|i| {
            Regex::new(pattern_for(i)).expect("text_redact pattern must compile")
        })
    })
}
