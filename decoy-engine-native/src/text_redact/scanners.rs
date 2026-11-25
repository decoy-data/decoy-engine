//! Hand-written ASCII byte scanners for the lookaround detectors (`ssn`, `us_zip`, `street_address`).

use super::detect::narrow_offset;

// ── lookaround detectors: hand-written ASCII byte scanners (plan 2) ───────────────────────────
//
// Each scanner runs ONLY on an eligible (all-ASCII, no 0x1c-0x1f) cell, so byte offsets equal
// code-point offsets and the ASCII predicates below coincide with Python's classes (module doc).
// They reproduce `re.finditer`: scan start positions left to right; at a position find the
// leftmost greedy/ordered match; on a match emit (start, end) and resume from end; else advance
// one. These patterns never match zero-width (ssn/zip need >=5 digits, street needs a house
// number), so advancement is always forward.

/// `\w` on ASCII: `[0-9A-Za-z_]`.
#[inline]
fn is_ascii_word(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

/// Python `\s` restricted to the ASCII-safe domain: `[ \t\n\x0b\x0c\r]`. 0x1c-0x1f (which Python
/// `\s` also matches) never appear in an eligible cell, so they are not listed.
#[inline]
fn is_ascii_space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | 0x0b | 0x0c | b'\r')
}

/// Case-insensitive ASCII equality of a byte slice against a lowercase literal (suffix / unit).
#[inline]
fn ascii_ci_eq(hay: &[u8], needle: &str) -> bool {
    let nb = needle.as_bytes();
    hay.len() == nb.len()
        && hay
            .iter()
            .zip(nb)
            .all(|(h, m)| h.to_ascii_lowercase() == *m)
}

/// Collect the lookaround detector `idx`'s spans into `out`, in finditer order.
pub(super) fn scan_lookaround(idx: usize, text: &str, out: &mut Vec<(u32, u32, u32)>) {
    let b = text.as_bytes();
    match idx {
        8 => scan_ssn(b, idx as u32, out),
        9 => scan_us_zip(b, idx as u32, out),
        10 => scan_street(b, idx as u32, out),
        _ => unreachable!("lookaround detector index out of range"),
    }
}

/// ssn: `(?!000|666|9\d{2})\d{3}-?(?!00)\d{2}-?(?!0000)\d{4}` (_SSN_RE). Fixed-shape with two
/// greedy optional hyphens; no backtracking changes the result (a hyphen, when present, must be
/// consumed because the following field is digits), so each start position is a direct test.
fn scan_ssn(b: &[u8], idx: u32, out: &mut Vec<(u32, u32, u32)>) {
    let n = b.len();
    let mut p = 0;
    while p < n {
        if let Some(end) = ssn_match_at(b, n, p) {
            out.push((idx, narrow_offset(p), narrow_offset(end)));
            p = end;
        } else {
            p += 1;
        }
    }
}

fn ssn_match_at(b: &[u8], n: usize, p: usize) -> Option<usize> {
    // area: three digits, not 000 / 666 / 9xx (the `9\d{2}` lookahead == a leading '9').
    if p + 3 > n
        || !b[p].is_ascii_digit()
        || !b[p + 1].is_ascii_digit()
        || !b[p + 2].is_ascii_digit()
    {
        return None;
    }
    let area = &b[p..p + 3];
    if area == b"000" || area == b"666" || area[0] == b'9' {
        return None;
    }
    let mut q = p + 3;
    if q < n && b[q] == b'-' {
        q += 1;
    }
    // group: two digits, not 00.
    if q + 2 > n || !b[q].is_ascii_digit() || !b[q + 1].is_ascii_digit() {
        return None;
    }
    if b[q] == b'0' && b[q + 1] == b'0' {
        return None;
    }
    q += 2;
    if q < n && b[q] == b'-' {
        q += 1;
    }
    // serial: four digits, not 0000.
    if q + 4 > n || !b[q..q + 4].iter().all(u8::is_ascii_digit) {
        return None;
    }
    if &b[q..q + 4] == b"0000" {
        return None;
    }
    Some(q + 4)
}

/// us_zip: `(?<!\w)\d{5}(?:-\d{4})?(?!\w)(?!\.\d)` (_US_ZIP_RE). The optional `-\d{4}` is greedy,
/// so the extension is tried first and the plain five-digit form is the backtrack fallback.
fn scan_us_zip(b: &[u8], idx: u32, out: &mut Vec<(u32, u32, u32)>) {
    let n = b.len();
    let mut p = 0;
    while p < n {
        if let Some(end) = zip_match_at(b, n, p) {
            out.push((idx, narrow_offset(p), narrow_offset(end)));
            p = end;
        } else {
            p += 1;
        }
    }
}

fn zip_match_at(b: &[u8], n: usize, p: usize) -> Option<usize> {
    // (?<!\w): start of string, or a non-word char precedes.
    if p > 0 && is_ascii_word(b[p - 1]) {
        return None;
    }
    if p + 5 > n || !b[p..p + 5].iter().all(u8::is_ascii_digit) {
        return None;
    }
    let base = p + 5;
    // Greedy `(?:-\d{4})?`: try the four-digit extension first.
    if base < n
        && b[base] == b'-'
        && base + 5 <= n
        && b[base + 1..base + 5].iter().all(u8::is_ascii_digit)
    {
        let ext = base + 5;
        if zip_trailing_ok(b, n, ext) {
            return Some(ext);
        }
    }
    if zip_trailing_ok(b, n, base) {
        return Some(base);
    }
    None
}

/// `(?!\w)(?!\.\d)` at `end`: not followed by a word char, and not by a decimal point + digit.
fn zip_trailing_ok(b: &[u8], n: usize, end: usize) -> bool {
    if end < n && is_ascii_word(b[end]) {
        return false;
    }
    if end < n && b[end] == b'.' && end + 1 < n && b[end + 1].is_ascii_digit() {
        return false;
    }
    true
}

/// The USPS Pub 28 C1 street-suffix vocabulary, in `_USPS_STREET_SUFFIXES` order (ordered
/// alternation: the first that lets the whole match complete wins, as Python's backtracking picks).
pub(super) const STREET_SUFFIXES: [&str; 47] = [
    "street",
    "st",
    "avenue",
    "ave",
    "boulevard",
    "blvd",
    "road",
    "rd",
    "drive",
    "dr",
    "lane",
    "ln",
    "court",
    "ct",
    "circle",
    "cir",
    "place",
    "pl",
    "terrace",
    "ter",
    "trail",
    "trl",
    "parkway",
    "pkwy",
    "highway",
    "hwy",
    "way",
    "plaza",
    "plz",
    "square",
    "sq",
    "expressway",
    "expy",
    "freeway",
    "fwy",
    "crossing",
    "xing",
    "loop",
    "alley",
    "aly",
    "bend",
    "cove",
    "cv",
    "point",
    "pt",
    "ridge",
    "rdg",
];

/// The Pub 28 C2 secondary-unit designators (`#` is a literal), in pattern order.
pub(super) const STREET_UNITS: [&str; 6] = ["apt", "apartment", "suite", "ste", "unit", "#"];

/// street_address: `\b\d{1,6}\s+(?:[A-Za-z0-9][A-Za-z0-9'.\-]*\s+){1,4}(?:SUFFIX)\.?`
/// `(?:\s+(?:UNIT)\.?\s*[\w\-]+)?(?=[\s,.;:!?)"']|$)` (_STREET_ADDRESS_RE, IGNORECASE). The greedy
/// `{1,4}` street-name repetition backtracks over the iteration count (most first), then the
/// suffix/dot/unit alternatives, exactly in Python's order.
fn scan_street(b: &[u8], idx: u32, out: &mut Vec<(u32, u32, u32)>) {
    let n = b.len();
    let mut p = 0;
    while p < n {
        if let Some(end) = street_match_at(b, n, p) {
            out.push((idx, narrow_offset(p), narrow_offset(end)));
            p = end;
        } else {
            p += 1;
        }
    }
}

fn street_match_at(b: &[u8], n: usize, p: usize) -> Option<usize> {
    // \b before the house number: start, or a non-word char precedes (the next char is a digit).
    if p > 0 && is_ascii_word(b[p - 1]) {
        return None;
    }
    // house number: `\d{1,6}\s+`. A digit run longer than 6 cannot be cut before whitespace (the
    // next char is still a digit), so it has no match; a 1-6 run must be followed by whitespace.
    let mut dr = 0;
    while p + dr < n && b[p + dr].is_ascii_digit() {
        dr += 1;
    }
    if dr == 0 || dr > 6 || p + dr >= n || !is_ascii_space(b[p + dr]) {
        return None;
    }
    let mut q = p + dr;
    while q < n && is_ascii_space(b[q]) {
        q += 1; // greedy \s+
    }
    // Greedy `(?:WORD \s+){1,4}`: record the end after each successful iteration (up to 4).
    let mut iter_ends: Vec<usize> = Vec::with_capacity(4);
    let mut pos = q;
    for _ in 0..4 {
        match street_word_iter(b, n, pos) {
            Some(next) => {
                iter_ends.push(next);
                pos = next;
            }
            None => break,
        }
    }
    // Most iterations first (greedy), require >= 1, take the first that completes the suffix tail.
    for &rest_start in iter_ends.iter().rev() {
        if let Some(end) = street_rest(b, n, rest_start) {
            return Some(end);
        }
    }
    None
}

/// One `[A-Za-z0-9][A-Za-z0-9'.\-]*\s+` iteration from `s`; returns the position after its `\s+`.
fn street_word_iter(b: &[u8], n: usize, s: usize) -> Option<usize> {
    if s >= n || !b[s].is_ascii_alphanumeric() {
        return None;
    }
    let mut w = s + 1;
    while w < n && (b[w].is_ascii_alphanumeric() || matches!(b[w], b'\'' | b'.' | b'-')) {
        w += 1; // greedy [A-Za-z0-9'.\-]*
    }
    if w >= n || !is_ascii_space(b[w]) {
        return None; // the trailing \s+ is required
    }
    let mut e = w;
    while e < n && is_ascii_space(b[e]) {
        e += 1;
    }
    Some(e)
}

/// `(?:SUFFIX)\.?(?:\s+(?:UNIT)\.?\s*[\w\-]+)?(?=[\s,.;:!?)"']|$)` from `q`. Suffix alternation,
/// then dot present-before-absent, then unit present-before-absent, mirroring Python's backtrack
/// order; returns the match end (the zero-width lookahead's position) of the first that completes.
fn street_rest(b: &[u8], n: usize, q: usize) -> Option<usize> {
    for suf in STREET_SUFFIXES {
        let slen = suf.len();
        if q + slen > n || !ascii_ci_eq(&b[q..q + slen], suf) {
            continue;
        }
        let after_suf = q + slen;
        for with_dot in [true, false] {
            let after_dot = if with_dot {
                if after_suf < n && b[after_suf] == b'.' {
                    after_suf + 1
                } else {
                    continue; // no dot to consume; the dot-absent branch below handles it
                }
            } else {
                after_suf
            };
            // Unit present first.
            if let Some(after_unit) = street_unit(b, n, after_dot) {
                if street_lookahead(b, n, after_unit) {
                    return Some(after_unit);
                }
            }
            // Unit absent.
            if street_lookahead(b, n, after_dot) {
                return Some(after_dot);
            }
        }
    }
    None
}

/// `\s+(?:UNIT)\.?\s*[\w\-]+` from `s`; returns the position after the `[\w\-]+` unit id, or None.
fn street_unit(b: &[u8], n: usize, s: usize) -> Option<usize> {
    if s >= n || !is_ascii_space(b[s]) {
        return None; // \s+
    }
    let mut u = s;
    while u < n && is_ascii_space(b[u]) {
        u += 1;
    }
    for un in STREET_UNITS {
        let ul = un.len();
        if u + ul > n || !ascii_ci_eq(&b[u..u + ul], un) {
            continue;
        }
        let after_un = u + ul;
        for with_dot in [true, false] {
            let after_dot = if with_dot {
                if after_un < n && b[after_un] == b'.' {
                    after_un + 1
                } else {
                    continue;
                }
            } else {
                after_un
            };
            let mut w = after_dot;
            while w < n && is_ascii_space(b[w]) {
                w += 1; // \s*
            }
            let mut e = w;
            while e < n && (is_ascii_word(b[e]) || b[e] == b'-') {
                e += 1; // [\w\-]+
            }
            if e > w {
                return Some(e);
            }
        }
    }
    None
}

/// `(?=[\s,.;:!?)"']|$)` at `pos`: end of string, or a boundary punctuation / whitespace char.
fn street_lookahead(b: &[u8], n: usize, pos: usize) -> bool {
    if pos >= n {
        return true; // $
    }
    let c = b[pos];
    is_ascii_space(c)
        || matches!(
            c,
            b',' | b'.' | b';' | b':' | b'!' | b'?' | b')' | b'"' | b'\''
        )
}
