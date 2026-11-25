use super::validators::{iban_valid, icd10_valid, ipv4_valid, luhn_valid, npi_valid};
use super::*;

fn index_of(id: &str) -> usize {
    SUPPORTED_IDS.iter().position(|s| *s == id).unwrap()
}

#[test]
fn eligibility_marks_the_boundary() {
    assert!(is_eligible("plain 123-45-6789 a@b.com"));
    assert!(is_eligible(""));
    assert!(!is_eligible("café"));
    for sep in ['\u{1c}', '\u{1d}', '\u{1e}', '\u{1f}'] {
        assert!(!is_eligible(&format!("a{sep}b")));
    }
    // The code points bracketing 0x1c-0x1f stay eligible.
    assert!(is_eligible("a\u{1b}b"));
    assert!(is_eligible("a b"));
}

#[cfg(not(feature = "test-detector-offset-limit"))]
#[test]
fn the_production_offset_limit_is_u32_max() {
    assert_eq!(DETECTOR_OFFSET_LIMIT, u32::MAX as usize);
}

#[cfg(feature = "test-detector-offset-limit")]
#[test]
fn an_oversized_cell_is_ineligible_under_the_test_limit() {
    let at_limit = "a".repeat(DETECTOR_OFFSET_LIMIT);
    assert!(is_eligible(&at_limit));
    assert!(!is_eligible(&format!("{at_limit}a")));
}

#[test]
fn validators_match_the_reference_vectors() {
    assert!(luhn_valid("0000000000000"));
    assert!(luhn_valid("4111 1111 1111 1111"));
    assert!(!luhn_valid("000000000000")); // 12 digits < 13
    assert!(!luhn_valid("4111111111111112"));
    assert!(npi_valid("1234567893"));
    assert!(npi_valid("123-456-7893"));
    assert!(!npi_valid("1234567890"));
    assert!(ipv4_valid("001.002.003.004"));
    assert!(!ipv4_valid("256.1.1.1"));
    assert!(!ipv4_valid("1.2.3"));
    assert!(iban_valid("GB82WEST12345698765432"));
    assert!(iban_valid("GB82 WEST 1234 5698 7654 32"));
    assert!(!iban_valid("ZZ00INVALID1234567890"));
    assert!(!iban_valid("GB00WEST12345698765432"));
    assert!(!icd10_valid("F00"));
    assert!(icd10_valid("F01"));
    assert!(icd10_valid("D89"));
    assert!(!icd10_valid("D90"));
    assert!(icd10_valid("A00!!!!"));
}

#[test]
fn candidates_find_each_detector_in_order_with_scalar_offsets() {
    let text = "mail a@b.com ip 10.0.0.1 ok";
    let all: Vec<usize> = (0..SUPPORTED_IDS.len()).collect();
    let got = candidates_for_cell(text, &all);
    assert!(got.contains(&(index_of("email") as u32, 5, 12)));
    assert!(got.contains(&(index_of("ipv4") as u32, 16, 24)));
}

#[test]
fn a_rejected_validator_match_does_not_halt_finditer() {
    // Two ipv4-shaped tokens; the first fails the octet range, the second passes. finditer
    // advances past the rejected one, so the valid second match is still found.
    let text = "999.1.1.1 then 10.0.0.1";
    let got = candidates_for_cell(text, &[index_of("ipv4")]);
    assert_eq!(got, vec![(index_of("ipv4") as u32, 15, 23)]);
}

#[test]
fn requested_subset_runs_only_those_detectors() {
    let text = "a@b.com 10.0.0.1";
    let got = candidates_for_cell(text, &[index_of("ipv4")]);
    assert_eq!(got, vec![(index_of("ipv4") as u32, 8, 16)]);
}

// ── lookaround detectors (hand-written scanners) ────────────────────────────────────────

fn spans_of(text: &str, id: &str) -> Vec<(u32, u32)> {
    candidates_for_cell(text, &[index_of(id)])
        .into_iter()
        .map(|(_, s, e)| (s, e))
        .collect()
}

#[test]
fn ssn_honours_the_ssa_reserved_block_lookaheads() {
    // Hyphenated and bare nine-digit shapes both match; reserved area/group/serial blocks do
    // not, exactly as _SSN_RE's negative lookaheads require.
    assert_eq!(spans_of("x 123-45-6789 y", "ssn"), vec![(2, 13)]);
    assert_eq!(spans_of("123456789", "ssn"), vec![(0, 9)]);
    assert!(spans_of("000-45-6789", "ssn").is_empty()); // area 000
    assert!(spans_of("666-45-6789", "ssn").is_empty()); // area 666
    assert!(spans_of("900-45-6789", "ssn").is_empty()); // 9xx area
    assert!(spans_of("123-00-6789", "ssn").is_empty()); // group 00
    assert!(spans_of("123-45-0000", "ssn").is_empty()); // serial 0000
}

#[test]
fn us_zip_rejects_runs_embedded_in_word_or_number_tokens() {
    assert_eq!(spans_of("zip 12345 ok", "us_zip"), vec![(4, 9)]);
    assert_eq!(spans_of("90210-1234 here", "us_zip"), vec![(0, 10)]);
    assert!(spans_of("12345mg", "us_zip").is_empty()); // trailing word char
    assert!(spans_of("x12345", "us_zip").is_empty()); // leading word char
    assert!(spans_of("12345.6", "us_zip").is_empty()); // decimal number
    assert!(spans_of("123456", "us_zip").is_empty()); // six-digit run
}

fn one_match_text<'a>(text: &'a str, id: &str) -> &'a str {
    let spans = spans_of(text, id);
    assert_eq!(spans.len(), 1, "{text:?} should have exactly one {id} span");
    &text[spans[0].0 as usize..spans[0].1 as usize]
}

#[test]
fn street_address_anchors_on_a_house_number_and_usps_suffix() {
    // House number + 1-4 street-name words + a USPS Pub 28 suffix; the trailing lookahead
    // stops the span at the first boundary punctuation (asserted via the matched substring so
    // the exact offsets are checked without hand-counting).
    assert_eq!(
        one_match_text("at 12 Main Street, Springfield", "street_address"),
        "12 Main Street"
    );
    // The optional `\.?` after the suffix consumes a trailing period.
    assert_eq!(
        one_match_text("742 Evergreen Terrace.", "street_address"),
        "742 Evergreen Terrace."
    );
    // Case-insensitive suffix match on the abbreviated form.
    assert_eq!(
        one_match_text("100 oak AVE here", "street_address"),
        "100 oak AVE"
    );
    assert!(spans_of("just some prose here", "street_address").is_empty());
}
