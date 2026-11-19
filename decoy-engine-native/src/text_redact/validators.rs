//! Validators ported from `pre-scan/_validators.py` (ASCII-input behavior).

// ── validators (ports of pre-scan/_validators.py; ASCII-input behavior) ────────────────────────

/// The whitespace set Python's `\s` strips on an eligible cell: `[ \t\n\x0b\x0c\r]`. 0x1c-0x1f
/// (which Python `\s` also matches) never appear in an eligible cell, so they are not listed.
#[inline]
fn is_strip_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | 0x0b | 0x0c | b'\r')
}

/// Luhn / mod-10 (`_luhn_valid`): strip `[\s-]`, require >= 13 pure digits, mod-10 checksum.
pub(super) fn luhn_valid(value: &str) -> bool {
    let digits: Vec<u8> = value
        .bytes()
        .filter(|b| !(is_strip_ws(*b) || *b == b'-'))
        .collect();
    if digits.len() < 13 || !digits.iter().all(u8::is_ascii_digit) {
        return false;
    }
    let mut total: u32 = 0;
    for (i, b) in digits.iter().rev().enumerate() {
        let mut d = (b - b'0') as u32;
        if i % 2 == 1 {
            d *= 2;
            if d > 9 {
                d -= 9;
            }
        }
        total += d;
    }
    total.is_multiple_of(10)
}

/// CMS NPI check digit (`_npi_valid`): strip `[\s-]`, require exactly 10 digits, prepend "80840"
/// to the 9-digit body, modified Luhn (even 0-indexed positions from the right doubled).
pub(super) fn npi_valid(value: &str) -> bool {
    let digits: Vec<u8> = value
        .bytes()
        .filter(|b| !(is_strip_ws(*b) || *b == b'-'))
        .collect();
    if digits.len() != 10 || !digits.iter().all(u8::is_ascii_digit) {
        return false;
    }
    let mut seq: Vec<u8> = Vec::with_capacity(14);
    seq.extend_from_slice(b"80840");
    seq.extend_from_slice(&digits[..9]);
    let mut total: u32 = 0;
    for (i, b) in seq.iter().rev().enumerate() {
        let mut d = (b - b'0') as u32;
        if i % 2 == 0 {
            d *= 2;
            if d > 9 {
                d -= 9;
            }
        }
        total += d;
    }
    (10 - total % 10) % 10 == (digits[9] - b'0') as u32
}

/// IPv4 dotted-quad (`_ipv4_valid`): exactly four `.`-separated parts, each 1-3 digits in 0-255.
pub(super) fn ipv4_valid(value: &str) -> bool {
    let parts: Vec<&str> = value.split('.').collect();
    if parts.len() != 4 {
        return false;
    }
    for p in parts {
        let pb = p.as_bytes();
        if pb.is_empty() || pb.len() > 3 || !pb.iter().all(u8::is_ascii_digit) {
            return false;
        }
        let n: u32 = p.parse().expect("1-3 ascii digits parse into u32");
        if n > 255 {
            return false;
        }
    }
    true
}

/// IBAN (`_iban_valid`): strip whitespace (not the hyphen) and uppercase, require length 15-34
/// with a country code and 2-digit check, require country-set membership, then verify ISO 13616
/// mod-97 computed incrementally (equal to `int(rearranged_as_digits) % 97`) equals 1.
pub(super) fn iban_valid(value: &str) -> bool {
    let cleaned: Vec<u8> = value
        .bytes()
        .filter(|b| !is_strip_ws(*b))
        .map(|b| b.to_ascii_uppercase())
        .collect();
    let n = cleaned.len();
    if !(15..=34).contains(&n) {
        return false;
    }
    if !(cleaned[0].is_ascii_alphabetic()
        && cleaned[1].is_ascii_alphabetic()
        && cleaned[2].is_ascii_digit()
        && cleaned[3].is_ascii_digit())
    {
        return false;
    }
    if !iban_country(cleaned[0], cleaned[1]) {
        return false;
    }
    let mut rem: u32 = 0;
    for &c in cleaned[4..].iter().chain(cleaned[..4].iter()) {
        if c.is_ascii_digit() {
            rem = (rem * 10 + (c - b'0') as u32) % 97;
        } else if c.is_ascii_uppercase() {
            // Letter -> ord(c) - 55 (A=10 .. Z=35), fed as its two decimal digits, matching
            // Python's `str(ord(c) - 55)` string join before the single big-integer mod.
            let v = (c - b'A') as u32 + 10;
            rem = (rem * 10 + v / 10) % 97;
            rem = (rem * 10 + v % 10) % 97;
        } else {
            return false;
        }
    }
    rem == 1
}

/// ICD-10-CM structural + chapter-range validity (`_icd10_valid`): strip surrounding whitespace,
/// drop dots, uppercase; require 3-7 chars with a chapter letter + 2-digit category in the
/// chapter's inclusive range.
pub(super) fn icd10_valid(value: &str) -> bool {
    let v: Vec<u8> = value
        .trim_matches(|c: char| is_strip_ws(c as u8) && c.is_ascii())
        .bytes()
        .filter(|b| *b != b'.')
        .map(|b| b.to_ascii_uppercase())
        .collect();
    if !(3..=7).contains(&v.len())
        || !v[0].is_ascii_alphabetic()
        || !v[1].is_ascii_digit()
        || !v[2].is_ascii_digit()
    {
        return false;
    }
    let cat = (v[1] - b'0') as u32 * 10 + (v[2] - b'0') as u32;
    match icd10_chapter_range(v[0]) {
        Some((lo, hi)) => cat >= lo && cat <= hi,
        None => false,
    }
}

/// ICD-10-CM chapter category ranges, mirroring `_ICD10_CHAPTERS`.
fn icd10_chapter_range(chapter: u8) -> Option<(u32, u32)> {
    let hi = match chapter {
        b'A' | b'B' | b'C' => 99,
        b'D' => 89,
        b'E' => 89,
        b'F' => return Some((1, 99)),
        b'G' => 99,
        b'H' => 95,
        b'I' | b'J' => 99,
        b'K' => 95,
        b'L' | b'M' | b'N' | b'O' => 99,
        b'P' => 96,
        b'Q' | b'R' | b'S' => 99,
        b'T' => 88,
        b'U' => 85,
        b'V' | b'W' | b'X' | b'Y' | b'Z' => 99,
        _ => return None,
    };
    Some((0, hi))
}

/// ISO 3166 alpha-2 codes of IBAN-issuing countries, mirroring `_IBAN_COUNTRIES` (SWIFT 2024).
fn iban_country(c0: u8, c1: u8) -> bool {
    const COUNTRIES: [&[u8; 2]; 78] = [
        b"AD", b"AE", b"AL", b"AT", b"AZ", b"BA", b"BE", b"BG", b"BH", b"BR", b"BY", b"CH", b"CR",
        b"CY", b"CZ", b"DE", b"DK", b"DO", b"EE", b"EG", b"ES", b"FI", b"FO", b"FR", b"GB", b"GE",
        b"GI", b"GL", b"GR", b"GT", b"HR", b"HU", b"IE", b"IL", b"IQ", b"IS", b"IT", b"JO", b"KW",
        b"KZ", b"LB", b"LC", b"LI", b"LT", b"LU", b"LV", b"MC", b"MD", b"ME", b"MK", b"MR", b"MT",
        b"MU", b"NL", b"NO", b"PK", b"PL", b"PS", b"PT", b"QA", b"RO", b"RS", b"RU", b"SA", b"SC",
        b"SE", b"SI", b"SK", b"SM", b"ST", b"SV", b"TL", b"TN", b"TR", b"UA", b"VA", b"VG", b"XK",
    ];
    COUNTRIES.iter().any(|cc| cc[0] == c0 && cc[1] == c1)
}
