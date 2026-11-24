//! Native splice for `text_mask` (C6b-ii slice b): the redact / passthrough case.
//!
//! The Python oracle (`transforms/_text_mask_splice.py::splice_spans` over `_mask_span`) rebuilds
//! a cell from its resolved spans: each unmatched gap takes the `unmatched_span_policy`, each
//! span becomes the redact token (strategy `redact`) or its own text (strategy `passthrough`).
//! This module is that rebuild for cells whose every span strategy is one of those two and whose
//! unmatched policy is `redact` or `passthrough`, so the per-span Python dispatch and string
//! joins leave the hot path. Anything it cannot reproduce byte-for-byte returns `None` and the
//! caller runs the Python splice.
//!
//! Two entry points share one `splice_cell`:
//! - `text_mask_splice_spans` takes the caller's RESOLVED MERGED spans (so Python-detected
//!   lookaround spans such as `ssn` are included) and only splices.
//! - `text_mask_detect_splice` runs detection, the oracle's merge (stable sort by
//!   `(start, -(end - start))`, then a leftmost-longest sweep), and the splice in one call. It is
//!   used only when every requested detector is one of the Rust-supported detectors (all eleven
//!   since the lookaround port -- `ssn`/`us_zip`/`street_address` included), so no Python-detected
//!   span can be missed. A requested detector outside that set still forces the splice-spans path.
//!
//! Gap rule (`apply_unmatched`): an empty gap emits nothing under any policy, so two adjacent
//! spans never gain a stray token between them; a non-empty gap is the token (`redact`) or
//! itself (`passthrough`). The gap token and the span token are the same string only because the
//! caller passes one `token`; they stay separate decisions here.
//!
//! Established methodology: no new algorithm. Detection is `text_redact::candidates_for_cell`
//! (the `regex` crate for the lookaround-free eight, hand-written ASCII byte scanners for the
//! three lookaround ones); the merge is the stable-sort plus sweep that `merge_text_redact_spans`
//! uses. Cells are ASCII-only by construction, where byte offsets equal the code-point offsets
//! Python slices with.

use crate::text_redact::{candidates_for_cell, is_eligible, CATALOG_LEN};

#[cfg(feature = "extension-module")]
use crate::text_redact::{CATALOG_VERSION, SUPPORTED_IDS};
#[cfg(feature = "extension-module")]
use pyo3::exceptions::PyValueError;
#[cfg(feature = "extension-module")]
use pyo3::prelude::*;
#[cfg(feature = "extension-module")]
use pyo3::types::{PyList, PyString};

/// One resolved span: byte range plus whether it is kept verbatim (`passthrough`) or replaced by
/// the redact token (`redact`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SpliceSpan {
    pub start: usize,
    pub end: usize,
    pub verbatim: bool,
}

/// The outcome the legacy exports derive from one token and a verbatim flag.
fn legacy_out(token: &str, verbatim: bool) -> SpanOut<'_> {
    if verbatim {
        SpanOut::Verbatim
    } else {
        SpanOut::Replace(token)
    }
}

/// Rebuild `text` from start-ordered, non-overlapping `spans`. Returns `None` when the input is
/// not what the splice can prove byte-exact (non-ASCII text, or spans out of order / out of
/// range), so the caller falls back to the Python splice instead of emitting a guess.
pub fn splice_cell(
    text: &str,
    spans: &[SpliceSpan],
    token: &str,
    passthrough_unmatched: bool,
) -> Option<String> {
    if !text.is_ascii() {
        return None;
    }
    if text.is_empty() {
        return Some(String::new());
    }
    let outcomes: Vec<(usize, usize, SpanOut<'_>)> = spans
        .iter()
        .map(|s| (s.start, s.end, legacy_out(token, s.verbatim)))
        .collect();
    let mut out = String::with_capacity(text.len());
    splice_out(
        text,
        &outcomes,
        legacy_out(token, passthrough_unmatched),
        &mut out,
    )
    .then_some(out)
}

/// Detection + the oracle's merge + the splice for one eligible cell. `indices` are catalog
/// indices in the oracle's requested order (duplicates preserved: a repeated id re-emits its
/// spans and the sweep collapses them, as the Python replay does); `verbatim[i]` is the strategy
/// for catalog index `i`. `None` means the cell is outside the ASCII-safe domain, so the caller
/// runs the Python path.
pub fn detect_splice_cell(
    text: &str,
    indices: &[usize],
    verbatim: &[bool; CATALOG_LEN],
    token: &str,
    passthrough_unmatched: bool,
) -> Option<String> {
    let outs: [SpanOut<'_>; CATALOG_LEN] = std::array::from_fn(|i| legacy_out(token, verbatim[i]));
    let mut out = eligible_buffer(text)?;
    matches!(
        detect_splice_cell_out(
            text,
            indices,
            &outs,
            legacy_out(token, passthrough_unmatched),
            usize::MAX,
            &mut out,
        ),
        CellOutcome::Written
    )
    .then_some(out)
}

/// An output buffer sized for `text`, or `None` when the cell is ineligible. Allocation waits for
/// eligibility so a declined cell (non-ASCII, oversized) never reserves memory.
fn eligible_buffer(text: &str) -> Option<String> {
    is_eligible(text).then(|| String::with_capacity(text.len()))
}

/// The outcome for one resolved span or gap: keep the text, or replace it with a literal. The
/// legacy exports build it from one token and a verbatim flag; the additive Arrow entry carries
/// one literal per detector and an independent gap outcome.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SpanOut<'a> {
    Verbatim,
    Replace(&'a str),
}

/// Hand `emit` the text one non-empty piece resolves to under its outcome; an empty piece emits
/// nothing (an empty replacement literal on a span is a removal and also emits nothing).
fn emit_piece<'t>(piece: &'t str, outcome: SpanOut<'t>, emit: &mut impl FnMut(&'t str)) {
    if piece.is_empty() {
        return;
    }
    match outcome {
        SpanOut::Verbatim => emit(piece),
        SpanOut::Replace(literal) => emit(literal),
    }
}

/// The one walker behind every splice entry. Visit, in order, each non-empty gap piece (under
/// `gap_out`) and each span piece (under its outcome), handing the text each one resolves to
/// to `emit`. Returns false when a span is out of order, out of range or not on a character
/// boundary, so the caller declines instead of emitting a guess.
fn walk_splice<'t>(
    text: &'t str,
    spans: &'t [(usize, usize, SpanOut<'t>)],
    gap_out: SpanOut<'t>,
    mut emit: impl FnMut(&'t str),
) -> bool {
    let mut cursor = 0usize;
    for &(start, end, outcome) in spans {
        if start < cursor || end < start {
            return false;
        }
        let (Some(gap), Some(span)) = (text.get(cursor..start), text.get(start..end)) else {
            return false;
        };
        emit_piece(gap, gap_out, &mut emit);
        emit_piece(span, outcome, &mut emit);
        cursor = end;
    }
    match text.get(cursor..) {
        Some(tail) => {
            emit_piece(tail, gap_out, &mut emit);
            true
        }
        None => false,
    }
}

/// Rebuild `text` from start-ordered, non-overlapping `spans` into `out`, each span written per
/// its outcome and each non-empty gap per `gap_out`. Returns false (leaving `out` unspecified)
/// when the spans are unusable, as `walk_splice` defines.
pub fn splice_out(
    text: &str,
    spans: &[(usize, usize, SpanOut<'_>)],
    gap_out: SpanOut<'_>,
    out: &mut String,
) -> bool {
    walk_splice(text, spans, gap_out, |piece| out.push_str(piece))
}

/// The byte length `splice_out` would write, by checked arithmetic and without writing.
/// `Ok(None)` when the spans are unusable; `Err(())` when the length overflows `usize`.
fn splice_len(
    text: &str,
    spans: &[(usize, usize, SpanOut<'_>)],
    gap_out: SpanOut<'_>,
) -> Result<Option<usize>, ()> {
    let mut total = Some(0usize);
    let usable = walk_splice(text, spans, gap_out, |piece| {
        total = total.and_then(|n| n.checked_add(piece.len()));
    });
    match (usable, total) {
        (false, _) => Ok(None),
        (true, Some(n)) => Ok(Some(n)),
        (true, None) => Err(()),
    }
}

/// Detect the requested detectors in one cell and resolve overlaps with the oracle's sweep:
/// stable sort by `(start, -length)` (an exact tie keeps request order), then keep each span
/// that starts at or after the previous end. Returns `(catalog index, start, end)`.
fn resolve_spans(text: &str, indices: &[usize]) -> Vec<(usize, usize, usize)> {
    let mut cands = candidates_for_cell(text, indices);
    cands.sort_by(|a, b| a.1.cmp(&b.1).then((b.2 - b.1).cmp(&(a.2 - a.1))));
    let mut spans = Vec::with_capacity(cands.len());
    let mut last_end: i64 = -1;
    for (idx, start, end) in cands {
        if i64::from(start) >= last_end {
            spans.push((idx as usize, start as usize, end as usize));
            last_end = i64::from(end);
        }
    }
    spans
}

/// What `detect_splice_cell_out` did with one cell.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CellOutcome {
    /// The cell is not eligible or its spans are unusable; `out` is untouched.
    Declined,
    /// The resolved cell would exceed `limit` bytes; `out` is untouched.
    TooLarge,
    /// The resolved cell was appended to `out`.
    Written,
}

/// Detection, overlap resolution and the splice for one cell into `out`, with one outcome per
/// catalog index (`outs`) and an independent gap outcome. The resolved byte length is computed
/// first with checked arithmetic, so a cell over `limit` is refused before any byte is written.
/// A declined cell is repaired on the Python path. An empty cell writes nothing.
pub fn detect_splice_cell_out(
    text: &str,
    indices: &[usize],
    outs: &[SpanOut<'_>; CATALOG_LEN],
    gap_out: SpanOut<'_>,
    limit: usize,
    out: &mut String,
) -> CellOutcome {
    if !is_eligible(text) {
        return CellOutcome::Declined;
    }
    let spans: Vec<(usize, usize, SpanOut<'_>)> = resolve_spans(text, indices)
        .into_iter()
        .map(|(idx, start, end)| (start, end, outs[idx]))
        .collect();
    match splice_len(text, &spans, gap_out) {
        Ok(None) => CellOutcome::Declined,
        Err(()) => CellOutcome::TooLarge,
        Ok(Some(n)) if n > limit => CellOutcome::TooLarge,
        Ok(Some(_)) => {
            if splice_out(text, &spans, gap_out, out) {
                CellOutcome::Written
            } else {
                CellOutcome::Declined
            }
        }
    }
}

// ── PyO3 boundary ───────────────────────────────────────────────────────────────────────────

/// The cell as `&str`, or `None` for a null, a non-string, or a lone-surrogate string.
#[cfg(feature = "extension-module")]
fn cell_str<'a>(item: &'a Bound<'_, PyAny>) -> Option<&'a str> {
    item.cast::<PyString>().ok()?.to_str().ok()
}

#[cfg(feature = "extension-module")]
fn push_result(out: &Bound<'_, PyList>, py: Python<'_>, value: Option<String>) -> PyResult<()> {
    match value {
        Some(s) => out.append(PyString::new(py, &s)),
        None => out.append(py.None()),
    }
}

/// `text_mask_splice_spans(values, spans, token, passthrough_unmatched) -> list[str | None]`
///
/// `spans[i]` is the resolved merged span list `[(start, end, verbatim), ...]` for `values[i]`.
/// A result of `None` means "decline": the cell is not a string, is non-ASCII, or its spans are
/// not usable; the caller runs the Python splice for it.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_mask_splice_spans(
    py: Python<'_>,
    values: &Bound<'_, PyAny>,
    spans: &Bound<'_, PyAny>,
    token: &str,
    passthrough_unmatched: bool,
) -> PyResult<Py<PyAny>> {
    let out = PyList::empty(py);
    let mut span_iter = spans.try_iter()?;
    for item in values.try_iter()? {
        let item = item?;
        let cell_spans = span_iter
            .next()
            .ok_or_else(|| PyValueError::new_err("spans_shorter_than_values"))??;
        let Some(text) = cell_str(&item) else {
            out.append(py.None())?;
            continue;
        };
        let mut parsed: Vec<SpliceSpan> = Vec::new();
        for s in cell_spans.try_iter()? {
            let (start, end, verbatim): (usize, usize, bool) = s?.extract()?;
            parsed.push(SpliceSpan {
                start,
                end,
                verbatim,
            });
        }
        push_result(
            &out,
            py,
            splice_cell(text, &parsed, token, passthrough_unmatched),
        )?;
    }
    Ok(out.into_any().unbind())
}

/// `text_mask_detect_splice(values, detector_ids, verbatim, token, passthrough_unmatched,
/// catalog_version) -> list[str | None]`
///
/// `detector_ids` are Rust-supported ids in the oracle's requested order (duplicates kept);
/// `verbatim[i]` says whether `detector_ids[i]` is `passthrough` (true) or `redact` (false). A
/// result of `None` means the cell is ineligible (non-ASCII, 0x1c-0x1f, non-string) or the value
/// was null; the caller tells those apart from its own input and runs the Python path.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_mask_detect_splice(
    py: Python<'_>,
    values: &Bound<'_, PyAny>,
    detector_ids: Vec<String>,
    verbatim: Vec<bool>,
    token: &str,
    passthrough_unmatched: bool,
    catalog_version: i64,
) -> PyResult<Py<PyAny>> {
    if catalog_version != CATALOG_VERSION {
        return Err(PyValueError::new_err(format!(
            "catalog_version_mismatch: caller sent {catalog_version}, kernel is {CATALOG_VERSION}"
        )));
    }
    if detector_ids.len() != verbatim.len() {
        return Err(PyValueError::new_err("verbatim_length_mismatch"));
    }
    let mut indices = Vec::with_capacity(detector_ids.len());
    let mut verbatim_by_index = [false; CATALOG_LEN];
    for (id, v) in detector_ids.iter().zip(&verbatim) {
        let Some(i) = SUPPORTED_IDS.iter().position(|s| s == id) else {
            return Err(PyValueError::new_err(format!(
                "unknown_detector_id: {id:?} is not a Rust-supported text_redact detector"
            )));
        };
        indices.push(i);
        verbatim_by_index[i] = *v;
    }
    let out = PyList::empty(py);
    for item in values.try_iter()? {
        let item = item?;
        let result = cell_str(&item).and_then(|text| {
            detect_splice_cell(
                text,
                &indices,
                &verbatim_by_index,
                token,
                passthrough_unmatched,
            )
        });
        push_result(&out, py, result)?;
    }
    Ok(out.into_any().unbind())
}

#[cfg(feature = "extension-module")]
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(text_mask_splice_spans, m)?)?;
    m.add_function(wrap_pyfunction!(text_mask_detect_splice, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sp(start: usize, end: usize, verbatim: bool) -> SpliceSpan {
        SpliceSpan {
            start,
            end,
            verbatim,
        }
    }

    #[test]
    fn empty_gap_emits_nothing_between_adjacent_spans() {
        let got = splice_cell("abcd", &[sp(0, 2, false), sp(2, 4, false)], "[X]", false);
        assert_eq!(got.as_deref(), Some("[X][X]"));
    }

    #[test]
    fn gap_policy_and_span_strategy_are_independent() {
        // gap redact + span verbatim, and the reverse.
        assert_eq!(
            splice_cell("a b c", &[sp(2, 3, true)], "[X]", false).as_deref(),
            Some("[X]b[X]")
        );
        assert_eq!(
            splice_cell("a b c", &[sp(2, 3, false)], "[X]", true).as_deref(),
            Some("a [X] c")
        );
    }

    #[test]
    fn zero_span_cell_is_one_gap() {
        assert_eq!(
            splice_cell("hello", &[], "[X]", false).as_deref(),
            Some("[X]")
        );
        assert_eq!(
            splice_cell("hello", &[], "[X]", true).as_deref(),
            Some("hello")
        );
        assert_eq!(splice_cell("", &[], "[X]", false).as_deref(), Some(""));
    }

    #[test]
    fn unusable_input_declines() {
        assert_eq!(splice_cell("café", &[], "[X]", false), None);
        assert_eq!(splice_cell("abc", &[sp(2, 9, false)], "[X]", false), None);
        assert_eq!(
            splice_cell("abcd", &[sp(2, 3, false), sp(1, 2, false)], "[X]", false),
            None
        );
    }

    #[test]
    fn detect_splice_merges_like_the_oracle() {
        let verbatim = [false; crate::text_redact::CATALOG_LEN];
        let email = 0usize;
        let got = detect_splice_cell("mail a@b.com now", &[email], &verbatim, "[X]", true);
        assert_eq!(got.as_deref(), Some("mail [X] now"));
        // A duplicated id re-emits the same span; the sweep keeps one.
        let dup = detect_splice_cell("a@b.com", &[email, email], &verbatim, "[X]", false);
        assert_eq!(dup.as_deref(), Some("[X]"));
        assert_eq!(
            detect_splice_cell("café a@b.com", &[email], &verbatim, "[X]", false),
            None
        );
    }

    #[test]
    fn same_start_keeps_the_longest_and_adjacent_spans_both_survive() {
        let (email, ipv4) = (0usize, 4usize);
        let redact = [false; crate::text_redact::CATALOG_LEN];
        // email and ipv4 both start at 0; the longer email wins and swallows the ipv4.
        let tie = detect_splice_cell("10.0.0.1a@b.com", &[email, ipv4], &redact, "[X]", true);
        assert_eq!(tie.as_deref(), Some("[X]"));
        // Requested order must not decide it: longest-first holds with ipv4 listed first too.
        let reversed = detect_splice_cell("10.0.0.1a@b.com", &[ipv4, email], &redact, "[X]", true);
        assert_eq!(reversed.as_deref(), Some("[X]"));
        // Adjacent, not overlapping: start == previous end must keep the second span.
        let adjacent = detect_splice_cell("a@b.com10.0.0.1", &[email, ipv4], &redact, "[X]", true);
        assert_eq!(adjacent.as_deref(), Some("[X][X]"));
    }

    #[test]
    fn verbatim_flag_is_per_detector() {
        let mut verbatim = [false; crate::text_redact::CATALOG_LEN];
        verbatim[0] = true; // email passes through, ipv4 is redacted
        let got = detect_splice_cell("a@b.com 10.0.0.1", &[0, 4], &verbatim, "[X]", true);
        assert_eq!(got.as_deref(), Some("a@b.com [X]"));
    }

    #[test]
    fn an_over_limit_cell_is_refused_before_any_byte_is_written() {
        // V1-1: three emails at a 64 byte literal resolve to 192 bytes; the limit is 100.
        let literal = "L".repeat(64);
        let outs: [SpanOut<'_>; CATALOG_LEN] = [SpanOut::Replace(&literal); CATALOG_LEN];
        let mut out = String::new();
        let got = detect_splice_cell_out(
            "a@b.com c@d.com e@f.com",
            &[0],
            &outs,
            SpanOut::Verbatim,
            100,
            &mut out,
        );
        assert_eq!(got, CellOutcome::TooLarge);
        assert!(out.is_empty(), "nothing may be written before the check");
        let got = detect_splice_cell_out(
            "a@b.com c@d.com e@f.com",
            &[0],
            &outs,
            SpanOut::Verbatim,
            192 + 2,
            &mut out,
        );
        assert_eq!(got, CellOutcome::Written);
        assert_eq!(out.len(), 192 + 2);
    }

    #[test]
    fn splice_len_matches_the_written_bytes_and_flags_overflow() {
        let spans = [(0usize, 3usize, SpanOut::Replace("xyz!"))];
        let mut written = String::new();
        assert!(splice_out(
            "abc def",
            &spans,
            SpanOut::Verbatim,
            &mut written
        ));
        assert_eq!(
            splice_len("abc def", &spans, SpanOut::Verbatim),
            Ok(Some(written.len()))
        );
        assert_eq!(
            splice_len("abc", &[(2, 9, SpanOut::Verbatim)], SpanOut::Verbatim),
            Ok(None)
        );
    }

    #[test]
    fn an_ineligible_cell_reserves_no_output_buffer() {
        // V1-3: S0 declined non-ASCII and oversized cells before allocating.
        assert!(eligible_buffer("café").is_none());
        let buf = eligible_buffer("a@b.com").expect("eligible");
        assert!(buf.capacity() >= 7);
    }
}
