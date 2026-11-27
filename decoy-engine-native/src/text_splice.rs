//! The additive Arrow entry for text span splicing (TEXT-REDACT-RUST-SPLICE S1a).
//!
//! `text_span_splice` takes one Arrow string column, detects the requested built-in detectors per
//! eligible cell, resolves overlaps with the same leftmost-longest sweep as `text_mask`, and
//! writes each cell with one outcome per detector plus an independent outcome for unmatched gaps
//! (`text_mask::SpanOut`). It returns pieces of `(values, declined)`: a `StringArray` and a
//! `BooleanArray` mask that is true only for a non-null cell the kernel could not splice (the
//! caller repairs that cell on the Python path). Pieces are cut before the cumulative string
//! offsets would overflow, so one call never produces an unrepresentable column.
//!
//! The pure core (`build_plan`, `splice_array`) has no PyO3 dependency so cargo tests exercise it,
//! including the piece ceiling, which tests lower. Only the `#[pyfunction]` wrappers are gated
//! behind the boundary feature. Both legacy exports stay as they are; the new entry shares their
//! detector sweep and writer in `text_mask`.

use arrow_array::{Array, BooleanArray, LargeStringArray, StringArray};
use arrow_buffer::{BooleanBuffer, NullBuffer, OffsetBuffer, ScalarBuffer};

use crate::text_mask::{detect_splice_cell_out, CellOutcome, SpanOut};
use crate::text_redact::{CATALOG_LEN, SUPPORTED_IDS};

/// The wire contract of `text_span_splice`. Bumped only when its arguments or result change.
pub const SPLICE_CONTRACT_VERSION: i64 = 1;

/// The most string bytes one output piece carries before the next row starts a new piece: the
/// largest cumulative offset an Arrow `StringArray` can hold.
pub const PIECE_BYTE_CEILING: usize = i32::MAX as usize;

/// A fixed, value-free failure. The boundary maps each variant to one registered code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SpliceError {
    UnsupportedType,
    UnknownDetector,
    OutputInvalid,
}

/// An owned span or gap outcome from the wire.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OutBuf {
    Verbatim,
    Replace(String),
}

impl OutBuf {
    fn as_out(&self) -> SpanOut<'_> {
        match self {
            OutBuf::Verbatim => SpanOut::Verbatim,
            OutBuf::Replace(s) => SpanOut::Replace(s),
        }
    }

    fn from_wire(wire: &Option<String>) -> OutBuf {
        match wire {
            None => OutBuf::Verbatim,
            Some(s) => OutBuf::Replace(s.clone()),
        }
    }
}

/// The request resolved once per call: catalog indices in request order (repeats kept, the sweep
/// collapses them), one outcome per catalog index, and the gap outcome.
#[derive(Clone, Debug)]
pub struct SplicePlan {
    indices: Vec<usize>,
    outs: Vec<OutBuf>,
    gap: OutBuf,
}

/// Pair each requested id with its outcome. A repeated id needs the same outcome each time; a
/// conflict in either order, unequal list lengths, or an unknown id are fixed errors.
pub fn build_plan(
    ids: &[String],
    outs: &[Option<String>],
    gap_out: &Option<String>,
) -> Result<SplicePlan, SpliceError> {
    if ids.len() != outs.len() {
        return Err(SpliceError::OutputInvalid);
    }
    let mut by_index: Vec<Option<OutBuf>> = vec![None; CATALOG_LEN];
    let mut indices = Vec::with_capacity(ids.len());
    for (id, wire) in ids.iter().zip(outs) {
        let Some(i) = SUPPORTED_IDS.iter().position(|s| s == id) else {
            return Err(SpliceError::UnknownDetector);
        };
        let out = OutBuf::from_wire(wire);
        match &by_index[i] {
            Some(prev) if *prev != out => return Err(SpliceError::OutputInvalid),
            _ => by_index[i] = Some(out),
        }
        indices.push(i);
    }
    Ok(SplicePlan {
        indices,
        outs: by_index
            .into_iter()
            .map(|o| o.unwrap_or(OutBuf::Verbatim))
            .collect(),
        gap: OutBuf::from_wire(gap_out),
    })
}

/// One output piece: the spliced strings and the decline mask, row-aligned and equal in length.
#[derive(Debug)]
pub struct SplicePiece {
    pub values: StringArray,
    pub declined: BooleanArray,
}

/// Accumulates one piece. Offsets are i32 because the output is a `StringArray`.
struct PieceBuilder {
    data: Vec<u8>,
    offsets: Vec<i32>,
    valid: Vec<bool>,
    declined: Vec<bool>,
}

impl PieceBuilder {
    /// No up-front reservation: the buffer grows from accepted bytes only, so a declined cell
    /// (however large) never reserves output memory before its eligibility is known.
    fn new() -> Self {
        Self {
            data: Vec::new(),
            offsets: vec![0],
            valid: Vec::new(),
            declined: Vec::new(),
        }
    }

    fn rows(&self) -> usize {
        self.valid.len()
    }

    fn push_null(&mut self) {
        self.offsets.push(self.data.len() as i32);
        self.valid.push(false);
        self.declined.push(false);
    }

    fn push_declined(&mut self) {
        self.offsets.push(self.data.len() as i32);
        self.valid.push(false);
        self.declined.push(true);
    }

    fn push_value(&mut self, value: &str) {
        self.data.extend_from_slice(value.as_bytes());
        self.offsets.push(self.data.len() as i32);
        self.valid.push(true);
        self.declined.push(false);
    }

    fn finish(self) -> Result<SplicePiece, SpliceError> {
        let nulls = NullBuffer::new(BooleanBuffer::from(self.valid));
        let offsets = OffsetBuffer::new(ScalarBuffer::from(self.offsets));
        let values = StringArray::try_new(offsets, self.data.into(), Some(nulls))
            .map_err(|_| SpliceError::OutputInvalid)?;
        let declined = BooleanArray::new(BooleanBuffer::from(self.declined), None);
        Ok(SplicePiece { values, declined })
    }
}

/// True when `add` more bytes keep a piece holding `used` bytes within `ceiling`. The ceiling is
/// clamped to `PIECE_BYTE_CEILING` here, in the one place every entry point reaches, because the
/// piece offsets are i32 and a larger caller value would let them wrap.
fn piece_has_room(used: usize, add: usize, ceiling: usize) -> bool {
    used.checked_add(add)
        .is_some_and(|n| n <= ceiling.min(PIECE_BYTE_CEILING))
}

/// Splice every row of `rows`, cutting a new piece before a row that would push the current
/// piece past `ceiling` bytes (capped at `PIECE_BYTE_CEILING`). A row alone larger than `ceiling` takes its own piece; one larger
/// than the real offset domain is a fixed error. Always returns at least one piece.
pub fn splice_rows<'a, I>(
    rows: I,
    plan: &SplicePlan,
    ceiling: usize,
) -> Result<Vec<SplicePiece>, SpliceError>
where
    I: Iterator<Item = Option<&'a str>>,
{
    let outs: Vec<SpanOut<'_>> = plan.outs.iter().map(OutBuf::as_out).collect();
    let outs: [SpanOut<'_>; CATALOG_LEN] =
        outs.try_into().map_err(|_| SpliceError::OutputInvalid)?;
    let gap = plan.gap.as_out();
    let mut pieces = Vec::new();
    let mut current = PieceBuilder::new();
    let mut scratch = String::new();
    for row in rows {
        let Some(text) = row else {
            current.push_null();
            continue;
        };
        scratch.clear();
        match detect_splice_cell_out(
            text,
            &plan.indices,
            &outs,
            gap,
            PIECE_BYTE_CEILING,
            &mut scratch,
        ) {
            CellOutcome::Declined => {
                current.push_declined();
                continue;
            }
            CellOutcome::TooLarge => return Err(SpliceError::OutputInvalid),
            CellOutcome::Written => {}
        }
        let fits = piece_has_room(current.data.len(), scratch.len(), ceiling);
        if !fits && current.rows() > 0 && !scratch.is_empty() {
            let full = std::mem::replace(&mut current, PieceBuilder::new());
            pieces.push(full.finish()?);
        }
        current.push_value(&scratch);
    }
    pieces.push(current.finish()?);
    Ok(pieces)
}

/// Splice an imported Arrow column. Only `Utf8` and `LargeUtf8` are accepted.
pub fn splice_array(
    array: &dyn Array,
    plan: &SplicePlan,
    ceiling: usize,
) -> Result<Vec<SplicePiece>, SpliceError> {
    if let Some(a) = array.as_any().downcast_ref::<StringArray>() {
        return splice_rows(a.iter(), plan, ceiling);
    }
    if let Some(a) = array.as_any().downcast_ref::<LargeStringArray>() {
        return splice_rows(a.iter(), plan, ceiling);
    }
    Err(SpliceError::UnsupportedType)
}

#[cfg(feature = "extension-module")]
mod boundary {
    use std::panic::{catch_unwind, AssertUnwindSafe};

    use arrow_array::Array;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::{PyInt, PyList, PyString, PyTuple};

    use super::{
        build_plan, splice_array, SpliceError, PIECE_BYTE_CEILING, SPLICE_CONTRACT_VERSION,
    };
    use crate::arrow_ffi::{export_array_data, import_array};
    use crate::text_redact::CATALOG_VERSION;

    const CATALOG_MISMATCH: &str = "text_splice_catalog_mismatch: the detector catalog version \
         differs from this kernel";
    const CONTRACT_MISMATCH: &str = "text_splice_contract_mismatch: the splice contract version \
         differs from this kernel";
    const UNSUPPORTED_TYPE: &str = "text_splice_unsupported_type: the input is not a string or \
         large_string Arrow array";
    const UNKNOWN_DETECTOR: &str =
        "text_splice_unknown_detector: a requested detector is not in the kernel catalog";
    const OUTPUT_INVALID: &str = "text_splice_output_invalid: the splice request or result is \
         malformed";

    fn fail(message: &str) -> PyErr {
        PyValueError::new_err(message.to_string())
    }

    fn from_splice(err: SpliceError) -> PyErr {
        fail(match err {
            SpliceError::UnsupportedType => UNSUPPORTED_TYPE,
            SpliceError::UnknownDetector => UNKNOWN_DETECTOR,
            SpliceError::OutputInvalid => OUTPUT_INVALID,
        })
    }

    /// True only for an object whose exact type is `int` holding `expected`. A bool, an int
    /// subclass, a string or an out-of-range integer is not accepted.
    fn exact_int_is(value: &Bound<'_, PyAny>, expected: i64) -> bool {
        value.is_exact_instance_of::<PyInt>() && value.extract::<i64>().is_ok_and(|n| n == expected)
    }

    fn wire_outcome(item: &Bound<'_, PyAny>) -> PyResult<Option<String>> {
        if item.is_none() {
            return Ok(None);
        }
        if item.is_exact_instance_of::<PyString>() {
            return item
                .extract::<String>()
                .map(Some)
                .map_err(|_| fail(OUTPUT_INVALID));
        }
        Err(fail(OUTPUT_INVALID))
    }

    fn wire_list<'py>(items: &Bound<'py, PyAny>) -> PyResult<Vec<Bound<'py, PyAny>>> {
        let list = items.cast::<PyList>().map_err(|_| fail(OUTPUT_INVALID))?;
        Ok(list.iter().collect())
    }

    /// `text_span_splice(values, *, detector_ids, outs, gap_out, catalog_version,
    /// splice_contract_version, native_threads=None) -> list[(pa.StringArray, pa.BooleanArray)]`
    ///
    /// `outs[i]` is the outcome for `detector_ids[i]`: `None` keeps the span text, a string
    /// replaces it (an empty string removes it). `gap_out` is the independent outcome for each
    /// non-empty unmatched gap. Every failure raises a `ValueError` with a fixed, value-free
    /// `text_splice_*` message.
    #[pyfunction]
    #[pyo3(signature = (
        values, *, detector_ids, outs, gap_out, catalog_version, splice_contract_version,
        native_threads=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn text_span_splice(
        py: Python<'_>,
        values: &Bound<'_, PyAny>,
        detector_ids: &Bound<'_, PyAny>,
        outs: &Bound<'_, PyAny>,
        gap_out: &Bound<'_, PyAny>,
        catalog_version: &Bound<'_, PyAny>,
        splice_contract_version: &Bound<'_, PyAny>,
        native_threads: Option<i64>,
    ) -> PyResult<Py<PyAny>> {
        if !exact_int_is(catalog_version, CATALOG_VERSION) {
            return Err(fail(CATALOG_MISMATCH));
        }
        if !exact_int_is(splice_contract_version, SPLICE_CONTRACT_VERSION) {
            return Err(fail(CONTRACT_MISMATCH));
        }
        let ids: Vec<String> = wire_list(detector_ids)?
            .iter()
            .map(|i| {
                if i.is_exact_instance_of::<PyString>() {
                    i.extract::<String>().map_err(|_| fail(OUTPUT_INVALID))
                } else {
                    Err(fail(OUTPUT_INVALID))
                }
            })
            .collect::<PyResult<_>>()?;
        let wire_outs: Vec<Option<String>> = wire_list(outs)?
            .iter()
            .map(wire_outcome)
            .collect::<PyResult<_>>()?;
        let gap = wire_outcome(gap_out)?;
        let plan = build_plan(&ids, &wire_outs, &gap).map_err(from_splice)?;
        // The loop runs on one thread; the budget is still validated like every other kernel.
        crate::threads::NativeThreadBudget::resolve_on_host(native_threads)
            .map_err(|e| PyValueError::new_err(format!("{}: {}", e.code, e.detail)))?;
        let array = import_array(values).map_err(|_| fail(UNSUPPORTED_TYPE))?;
        let outcome = catch_unwind(AssertUnwindSafe(|| {
            py.detach(|| splice_array(array.as_ref(), &plan, PIECE_BYTE_CEILING))
        }));
        let pieces = match outcome {
            Ok(result) => result.map_err(from_splice)?,
            Err(_panic) => return Err(fail(OUTPUT_INVALID)),
        };
        let out = PyList::empty(py);
        for piece in pieces {
            let values = export_array_data(py, piece.values.into_data())?;
            let declined = export_array_data(py, piece.declined.into_data())?;
            out.append(PyTuple::new(py, [values, declined])?)?;
        }
        Ok(out.into_any().unbind())
    }

    /// The wire contract version this kernel implements, for the loader's agreement check.
    #[pyfunction]
    fn text_span_splice_contract_version() -> i64 {
        SPLICE_CONTRACT_VERSION
    }

    pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(text_span_splice, m)?)?;
        m.add_function(wrap_pyfunction!(text_span_splice_contract_version, m)?)?;
        Ok(())
    }
}

#[cfg(feature = "extension-module")]
pub(crate) use boundary::register;

#[cfg(test)]
mod tests;
