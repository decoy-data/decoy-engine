//! Check-digit arithmetic for the structured-identifier schemes, in pure Rust.
//!
//! One copy of each rule, used by the FPE checksum path and by the text_redact detectors. It
//! mirrors `decoy_engine.checksums` (python-stdnum for luhn, GS1 and ISBN; CMS NPPES for npi;
//! 49 CFR 565 for vin) and is locked to it by `tests/kat_checksum.rs` over
//! `vectors/checksum_kat.json`.
//!
//! The functions take already-admitted characters. `check_digit` on a character outside the
//! scheme's body alphabet counts it as zero instead of panicking, because it runs on rayon
//! threads behind an FFI boundary; callers check the body alphabet first (`validate` does).

/// A supported check-digit scheme. `iban` is not native and has no variant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Scheme {
    Luhn,
    Npi,
    Ean13,
    Gtin,
    Isbn13,
    Vin,
}

impl Scheme {
    /// Parse the registry name. Only the six lower-case names match.
    pub fn parse(name: &str) -> Option<Scheme> {
        match name {
            "luhn" => Some(Scheme::Luhn),
            "npi" => Some(Scheme::Npi),
            "ean13" => Some(Scheme::Ean13),
            "gtin" => Some(Scheme::Gtin),
            "isbn13" => Some(Scheme::Isbn13),
            "vin" => Some(Scheme::Vin),
            _ => None,
        }
    }
}

/// Whether `n` characters is a legal length for the scheme (`_fpe_checksum._validate_scheme_length`).
pub fn length_ok(scheme: Scheme, n: usize) -> bool {
    match scheme {
        Scheme::Luhn => n >= 2,
        Scheme::Npi => n == 10,
        Scheme::Ean13 | Scheme::Isbn13 => n == 13,
        Scheme::Vin => n == 17,
        Scheme::Gtin => matches!(n, 8 | 12 | 13 | 14),
    }
}

/// Luhn digit sum of digits given right to left, reduced modulo 10 at every step so a body of any
/// length cannot overflow. `double_even` doubles the digits at even indices (the rightmost is
/// index 0), as a check digit computation does; `false` doubles the odd indices, as a full number
/// that already holds its check digit does.
pub fn luhn_digit_sum<I: Iterator<Item = u32>>(rev_digits: I, double_even: bool) -> u32 {
    let mut total = 0u32;
    for (i, mut n) in rev_digits.enumerate() {
        if (i % 2 == 0) == double_even {
            n *= 2;
            if n > 9 {
                n -= 9;
            }
        }
        total = (total + n) % 10;
    }
    total
}

/// Luhn check digit for a string of ASCII decimal digits (python-stdnum `luhn.calc_check_digit`).
pub fn luhn_check_digit(body: &str) -> char {
    luhn_check_char(body.chars().rev().map(digit_or_zero))
}

/// The one Luhn check character for body digits given right to left. Every adapter (the string
/// helper above and the `Scheme::Luhn` arm of `check_digit`) goes through it.
fn luhn_check_char<I: Iterator<Item = u32>>(rev_digits: I) -> char {
    digit_char((10 - luhn_digit_sum(rev_digits, true)) % 10)
}

/// Whether digits that include their final check digit pass the Luhn mod-10 test.
pub fn luhn_valid_digits<I: DoubleEndedIterator<Item = u32>>(digits: I) -> bool {
    luhn_digit_sum(digits.rev(), false) == 0
}

/// CMS NPPES NPI check digit value for a nine digit body: Luhn over "80840" followed by the body.
pub fn npi_check_value<I: DoubleEndedIterator<Item = u32>>(body: I) -> u32 {
    let prefixed = body.rev().chain([0u32, 4, 8, 0, 8]);
    (10 - luhn_digit_sum(prefixed, true)) % 10
}

/// GS1 General Specifications 7.9 check digit, shared by EAN-13, GTIN and ISBN-13 (ISO 2108):
/// weights 3 and 1 alternating from the rightmost body digit.
pub fn gs1_check_digit(body: &[char]) -> char {
    let mut total = 0u32;
    for (i, c) in body.iter().rev().enumerate() {
        let weight = if i % 2 == 0 { 3 } else { 1 };
        total = (total + weight * digit_or_zero(*c)) % 10;
    }
    digit_char((10 - total) % 10)
}

const VIN_WEIGHTS: [u32; 17] = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2];

/// Transliteration value of a VIN character (49 CFR 565.15 Appendix B). `None` for I, O, Q and
/// anything outside the VIN alphabet.
fn vin_value(c: char) -> Option<u32> {
    match c {
        '0'..='9' => c.to_digit(10),
        'A' | 'J' => Some(1),
        'B' | 'K' | 'S' => Some(2),
        'C' | 'L' | 'T' => Some(3),
        'D' | 'M' | 'U' => Some(4),
        'E' | 'N' | 'V' => Some(5),
        'F' | 'W' => Some(6),
        'G' | 'P' | 'X' => Some(7),
        'H' | 'Y' => Some(8),
        'R' | 'Z' => Some(9),
        _ => None,
    }
}

/// VIN check character for the 16 non-check characters (positions 0-7 and 9-16): `0`-`9` or `X`.
/// Position 8 has weight zero, so the full VIN is summed with a placeholder there.
pub fn vin_check_char(body: &[char]) -> char {
    let mut total = 0u32;
    let mut weights = VIN_WEIGHTS.iter();
    for (i, c) in body.iter().enumerate() {
        if i == 8 {
            weights.next();
        }
        let w = weights.next().copied().unwrap_or(0);
        total += vin_value(*c).unwrap_or(0) * w;
    }
    match total % 11 {
        10 => 'X',
        r => digit_char(r),
    }
}

/// Check character for `body`, the value without its check digit: nine digits for npi, twelve
/// for ean13 and isbn13, seven, eleven, twelve or thirteen for gtin, any digits for luhn, and
/// sixteen characters for vin.
pub fn check_digit(scheme: Scheme, body: &[char]) -> char {
    match scheme {
        Scheme::Luhn => luhn_check_char(body.iter().rev().map(|c| digit_or_zero(*c))),
        Scheme::Npi => digit_char(npi_check_value(body.iter().map(|c| digit_or_zero(*c)))),
        Scheme::Ean13 | Scheme::Gtin | Scheme::Isbn13 => gs1_check_digit(body),
        Scheme::Vin => vin_check_char(body),
    }
}

/// Whether the whole value is valid for the scheme: legal length, every character in the scheme's
/// alphabet and a matching check character. Like `checksums.validate`, vin compares on an ASCII
/// uppercased copy. npi also needs a leading 1 or 2 (NPPES), and isbn13 a 978 or 979 prefix.
pub fn validate(scheme: Scheme, value: &[char]) -> bool {
    if !length_ok(scheme, value.len()) {
        return false;
    }
    match scheme {
        Scheme::Vin => {
            let upper: Vec<char> = value.iter().map(char::to_ascii_uppercase).collect();
            if upper.iter().any(|c| vin_value(*c).is_none()) {
                return false;
            }
            let mut body = upper[..8].to_vec();
            body.extend_from_slice(&upper[9..]);
            vin_check_char(&body) == upper[8]
        }
        _ => {
            if !value.iter().all(char::is_ascii_digit) {
                return false;
            }
            let (body, last) = value.split_at(value.len() - 1);
            if scheme == Scheme::Npi && !matches!(value[0], '1' | '2') {
                return false;
            }
            if scheme == Scheme::Isbn13 && !matches!(value[..3], ['9', '7', '8' | '9']) {
                return false;
            }
            check_digit(scheme, body) == last[0]
        }
    }
}

fn digit_or_zero(c: char) -> u32 {
    c.to_digit(10).unwrap_or(0)
}

fn digit_char(d: u32) -> char {
    char::from_digit(d, 10).unwrap_or('0')
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chars(s: &str) -> Vec<char> {
        s.chars().collect()
    }

    #[test]
    fn parse_accepts_exactly_the_six_names() {
        for n in ["luhn", "npi", "ean13", "gtin", "isbn13", "vin"] {
            assert!(Scheme::parse(n).is_some(), "{n}");
        }
        for n in ["iban", "LUHN", "Npi", "", "luhn "] {
            assert!(Scheme::parse(n).is_none(), "{n}");
        }
    }

    #[test]
    fn length_rules_match_the_oracle() {
        assert!(!length_ok(Scheme::Luhn, 1) && length_ok(Scheme::Luhn, 2));
        assert!(length_ok(Scheme::Npi, 10) && !length_ok(Scheme::Npi, 9));
        assert!(length_ok(Scheme::Vin, 17) && !length_ok(Scheme::Vin, 16));
        for n in [8, 12, 13, 14] {
            assert!(length_ok(Scheme::Gtin, n));
        }
        assert!(!length_ok(Scheme::Gtin, 10));
    }

    #[test]
    fn known_values() {
        assert_eq!(luhn_check_digit("7992739871"), '3');
        assert!(validate(Scheme::Npi, &chars("1234567893")));
        assert!(!validate(Scheme::Npi, &chars("3234567899")));
        assert!(validate(Scheme::Vin, &chars("1M8GDM9AXKP042788")));
        assert!(validate(Scheme::Vin, &chars("1m8gdm9axkp042788")));
        assert!(validate(Scheme::Ean13, &chars("4006381333931")));
        assert!(validate(Scheme::Isbn13, &chars("9780306406157")));
        assert!(!validate(Scheme::Isbn13, &chars("4006381333931")));
    }

    #[test]
    fn luhn_digit_sum_cannot_overflow_on_a_huge_body() {
        // Each nine contributes nine, so 500 million of them pass u32::MAX unreduced.
        let nines = std::iter::repeat_n(9u32, 500_000_000);
        assert_eq!(luhn_digit_sum(nines, true), 0);
    }
}
