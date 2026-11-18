//! The PyO3 boundary: `#[pyfunction]` wrappers and `register` (extension-module feature only).

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyString, PyTuple};
use regex::Regex;

use super::catalog::{Validator, CATALOG_VERSION, SUPPORTED_IDS};
use super::detect::{candidates_for_cell, is_eligible, run_validator};
use super::scanners::{STREET_SUFFIXES, STREET_UNITS};

// ── test / class-equivalence helpers ────────────────────────────────────────────────────────

/// Members of an ASCII class, for the class-equivalence proof (plan 7.4). Returns the ASCII code
/// points (0-127) the named class matches under the exact flags the kernel uses. `"icd_ci"` is
/// the `(?i-u)[A-Z]` class the icd10 detector relies on.
#[cfg(feature = "extension-module")]
fn class_members(name: &str) -> Option<Vec<u32>> {
    let pat = match name {
        "d" => r"(?-u)^\d$",
        "s" => r"(?-u)^\s$",
        "w" => r"(?-u)^\w$",
        "icd_ci" => r"(?i-u)^[A-Z]$",
        _ => return None,
    };
    let re = Regex::new(pat).expect("class probe pattern must compile");
    let mut out = Vec::new();
    for cp in 0u32..128 {
        let ch = char::from_u32(cp).expect("0-127 is valid");
        let buf = ch.to_string();
        if re.is_match(&buf) {
            out.push(cp);
        }
    }
    Some(out)
}

// ── PyO3 boundary ───────────────────────────────────────────────────────────────────────────

#[cfg(feature = "extension-module")]
fn requested_indices(detector_ids: &Bound<'_, PyAny>) -> PyResult<Vec<usize>> {
    let mut indices = Vec::new();
    for item in detector_ids.try_iter()? {
        let id: String = item?.extract()?;
        match SUPPORTED_IDS.iter().position(|s| *s == id) {
            Some(i) => indices.push(i),
            None => {
                return Err(PyValueError::new_err(format!(
                    "unknown_detector_id: {id:?} is not a Rust-supported text_redact detector"
                )))
            }
        }
    }
    Ok(indices)
}

/// `text_redact_candidates(values, detector_ids, catalog_version) -> list[list[(int,int,int)] | None]`
///
/// Per cell: the eligible candidate list `[(detector_index, start, end), ...]` in finditer order,
/// or `None` (ineligible: non-ASCII, a 0x1c-0x1f separator, a lone surrogate, or a non-string).
/// `detector_ids` are the requested Rust-supported ids in the oracle's requested order; a mismatched
/// `catalog_version` raises `catalog_version_mismatch` so the loader can fall back to full Python.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_candidates(
    py: Python<'_>,
    values: &Bound<'_, PyAny>,
    detector_ids: &Bound<'_, PyAny>,
    catalog_version: i64,
) -> PyResult<Py<PyAny>> {
    if catalog_version != CATALOG_VERSION {
        return Err(PyValueError::new_err(format!(
            "catalog_version_mismatch: caller sent {catalog_version}, kernel is {CATALOG_VERSION}"
        )));
    }
    let indices = requested_indices(detector_ids)?;
    let out = PyList::empty(py);
    for item in values.try_iter()? {
        let item = item?;
        if item.is_none() {
            out.append(py.None())?;
            continue;
        }
        // A non-string, or a str carrying a lone surrogate (no UTF-8 view), is ineligible.
        let Ok(py_str) = item.cast::<PyString>() else {
            out.append(py.None())?;
            continue;
        };
        let Ok(text) = py_str.to_str() else {
            out.append(py.None())?;
            continue;
        };
        if !is_eligible(text) {
            out.append(py.None())?;
            continue;
        }
        let cands = candidates_for_cell(text, &indices);
        let cell = PyList::empty(py);
        for (idx, start, end) in cands {
            cell.append(PyTuple::new(py, [idx, start, end])?)?;
        }
        out.append(cell)?;
    }
    Ok(out.into_any().unbind())
}

/// The kernel's catalog version, for the loader's agreement check.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_catalog_version() -> i64 {
    CATALOG_VERSION
}

/// The kernel's Rust-supported detector ids, in catalog (index) order, for the agreement check.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_supported_ids() -> Vec<String> {
    SUPPORTED_IDS.iter().map(|s| (*s).to_string()).collect()
}

/// The scanner's hand-copied USPS street-suffix vocabulary, in ordered-alternation order, for the
/// vocabulary-agreement test (plan 7). Exposed so the test can assert ordered list-equality against
/// the Python oracle's `_USPS_STREET_SUFFIXES`; a one-sided edit (add "pike"/"run") then fails CI
/// instead of silently diverging on the native path.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_street_suffixes() -> Vec<String> {
    STREET_SUFFIXES.iter().map(|s| (*s).to_string()).collect()
}

/// The scanner's hand-copied secondary-unit designators (Pub 28 C2; `#` is a literal), in pattern
/// order, for the vocabulary-agreement test (plan 7). The oracle embeds these directly inside
/// `_STREET_ADDRESS_RE`, so the test ties this list back to that pattern body rather than to a
/// separately copied Python list.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_street_units() -> Vec<String> {
    STREET_UNITS.iter().map(|s| (*s).to_string()).collect()
}

/// Run one ported validator by name, for the validator KATs (plan 7.3).
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_validate(name: &str, value: &str) -> PyResult<bool> {
    let validator = match name {
        "luhn" => Validator::Luhn,
        "iban" => Validator::Iban,
        "ipv4" => Validator::Ipv4,
        "icd10" => Validator::Icd10,
        "npi" => Validator::Npi,
        _ => return Err(PyValueError::new_err(format!("unknown validator {name:?}"))),
    };
    Ok(run_validator(validator, value))
}

/// Whether a value is in the ASCII-safe domain (plan 2.1), for the routing-predicate test (7.1).
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_is_eligible(value: &Bound<'_, PyAny>) -> bool {
    let Ok(py_str) = value.cast::<PyString>() else {
        return false;
    };
    match py_str.to_str() {
        Ok(text) => is_eligible(text),
        Err(_) => false,
    }
}

/// The ASCII code points a named class matches under the kernel's flags, for the class-level
/// equivalence proof (plan 7.4). Names: `"d"`, `"s"`, `"w"`, `"icd_ci"`.
#[cfg(feature = "extension-module")]
#[pyfunction]
fn text_redact_class_members(name: &str) -> PyResult<Vec<u32>> {
    class_members(name).ok_or_else(|| PyValueError::new_err(format!("unknown class {name:?}")))
}

#[cfg(feature = "extension-module")]
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(text_redact_candidates, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_catalog_version, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_supported_ids, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_street_suffixes, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_street_units, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_validate, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_is_eligible, m)?)?;
    m.add_function(wrap_pyfunction!(text_redact_class_members, m)?)?;
    Ok(())
}
