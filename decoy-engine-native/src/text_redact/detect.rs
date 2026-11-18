//! Per-cell eligibility and candidate detection over the requested detector indices.

use super::catalog::{compiled, validator_for, Validator, LOOKAROUND_FREE_COUNT};
use super::scanners::scan_lookaround;
use super::validators::{iban_valid, icd10_valid, ipv4_valid, luhn_valid, npi_valid};

/// A cell is eligible iff every code point is ASCII (`< 0x80`) AND none is in 0x1c-0x1f (plan
/// 2.1). A lone surrogate never reaches here: it cannot be decoded to a Rust `&str`, so the
/// caller already routes it to Python as ineligible.
pub fn is_eligible(text: &str) -> bool {
    text.is_ascii() && !text.bytes().any(|b| (0x1c..=0x1f).contains(&b))
}

/// The candidate list for one eligible cell over `indices` (catalog indices, in the oracle's
/// requested order among the eleven). Each detector contributes its `find_iter` matches, in order,
/// that pass its validator; finditer advancement is independent of the validator (a rejected
/// match still advances past its own span), exactly as the Python loop does. The lookaround-free
/// eight run on the `regex` crate; the three lookaround detectors run as hand-written scanners.
/// Offsets are code-point counts; on an ASCII cell byte offsets equal code-point offsets, so the
/// match's byte span is returned directly.
///
/// The lookaround-free eight run on the `regex` crate; the three lookaround detectors run as the
/// hand-written byte scanners above (no validator). Both are infallible on an eligible cell, so
/// this always returns a (possibly empty) candidate list.
pub fn candidates_for_cell(text: &str, indices: &[usize]) -> Vec<(u32, u32, u32)> {
    let regexes = compiled();
    let mut out: Vec<(u32, u32, u32)> = Vec::new();
    for &idx in indices {
        if idx < LOOKAROUND_FREE_COUNT {
            let validator = validator_for(idx);
            for m in regexes[idx].find_iter(text) {
                if validator != Validator::None && !run_validator(validator, m.as_str()) {
                    continue;
                }
                out.push((idx as u32, m.start() as u32, m.end() as u32));
            }
        } else {
            scan_lookaround(idx, text, &mut out);
        }
    }
    out
}

pub(super) fn run_validator(validator: Validator, matched: &str) -> bool {
    match validator {
        Validator::None => true,
        Validator::Luhn => luhn_valid(matched),
        Validator::Iban => iban_valid(matched),
        Validator::Ipv4 => ipv4_valid(matched),
        Validator::Icd10 => icd10_valid(matched),
        Validator::Npi => npi_valid(matched),
    }
}
