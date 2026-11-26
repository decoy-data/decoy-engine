//! Check-digit KAT gate (FPE-CHECKSUM-NATIVE S2a, acceptance test K1): `checksum::length_ok`,
//! `validate` and `check_digit` must agree with the Python oracle `decoy_engine.checksums`
//! (python-stdnum, CMS NPPES, 49 CFR 565) on every row of `vectors/checksum_kat.json`, which
//! `vectors/generate_checksum_kat.py` writes from the live oracle.

use std::path::PathBuf;

use _kernel::checksum::{check_digit, length_ok, validate, Scheme};
use serde::Deserialize;

const SUPPORTED_FORMAT_VERSION: u32 = 1;

#[derive(Deserialize)]
struct Fixture {
    format_version: Option<u32>,
    bodies: Vec<BodyRow>,
    values: Vec<ValueRow>,
}

#[derive(Deserialize)]
struct BodyRow {
    scheme: String,
    body: String,
    check: String,
}

#[derive(Deserialize)]
struct ValueRow {
    scheme: String,
    value: String,
    length_ok: bool,
    valid: bool,
}

fn load() -> Fixture {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("vectors")
        .join("checksum_kat.json");
    let raw = std::fs::read_to_string(path).expect("read checksum_kat.json");
    parse(&raw)
}

fn parse(raw: &str) -> Fixture {
    let fixture: Fixture = serde_json::from_str(raw).expect("parse checksum_kat.json");
    assert_eq!(
        fixture.format_version,
        Some(SUPPORTED_FORMAT_VERSION),
        "checksum_kat.json has a missing or unknown format_version"
    );
    fixture
}

fn scheme(name: &str) -> Scheme {
    Scheme::parse(name).unwrap_or_else(|| panic!("unknown scheme {name}"))
}

#[test]
fn check_digit_matches_the_oracle_on_every_body() {
    let fixture = load();
    assert!(fixture.bodies.len() >= 6 * 200);
    for row in &fixture.bodies {
        let body: Vec<char> = row.body.chars().collect();
        let got = check_digit(scheme(&row.scheme), &body);
        assert_eq!(
            got.to_string(),
            row.check,
            "{} body {}",
            row.scheme,
            row.body
        );
    }
}

#[test]
fn length_and_validate_match_the_oracle_on_every_value() {
    let fixture = load();
    for row in &fixture.values {
        let chars: Vec<char> = row.value.chars().collect();
        let s = scheme(&row.scheme);
        assert_eq!(
            length_ok(s, chars.len()),
            row.length_ok,
            "{} {}",
            row.scheme,
            row.value
        );
        assert_eq!(
            validate(s, &chars),
            row.valid,
            "{} {}",
            row.scheme,
            row.value
        );
    }
}

#[test]
fn every_scheme_has_two_hundred_bodies_and_both_verdicts() {
    let fixture = load();
    for name in ["luhn", "npi", "ean13", "gtin", "isbn13", "vin"] {
        let bodies = fixture.bodies.iter().filter(|r| r.scheme == name).count();
        assert!(bodies >= 200, "{name} has {bodies} bodies");
        assert!(fixture.values.iter().any(|r| r.scheme == name && r.valid));
        assert!(fixture.values.iter().any(|r| r.scheme == name && !r.valid));
    }
}

#[test]
fn a_missing_or_unknown_format_version_is_rejected() {
    for raw in [
        r#"{"bodies":[],"values":[]}"#,
        r#"{"format_version":2,"bodies":[],"values":[]}"#,
    ] {
        assert!(std::panic::catch_unwind(|| parse(raw)).is_err(), "{raw}");
    }
}
