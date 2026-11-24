use arrow_array::{Array, LargeStringArray, StringArray};

use super::*;

const EMAIL: usize = 0;
const IPV4: usize = 4;

fn ids(names: &[&str]) -> Vec<String> {
    names.iter().map(|s| (*s).to_string()).collect()
}

fn token_plan(names: &[&str], token: &str, gap: Option<&str>) -> SplicePlan {
    let outs: Vec<Option<String>> = names.iter().map(|_| Some(token.to_string())).collect();
    build_plan(&ids(names), &outs, &gap.map(str::to_string)).expect("plan")
}

fn rows(pieces: &[SplicePiece]) -> Vec<Option<String>> {
    pieces
        .iter()
        .flat_map(|p| p.values.iter().map(|v| v.map(str::to_string)))
        .collect()
}

fn mask(pieces: &[SplicePiece]) -> Vec<bool> {
    pieces
        .iter()
        .flat_map(|p| p.declined.iter().map(|b| b.expect("mask never null")))
        .collect()
}

fn run(values: &[Option<&str>], plan: &SplicePlan, ceiling: usize) -> Vec<SplicePiece> {
    let array = StringArray::from(values.to_vec());
    splice_array(&array, plan, ceiling).expect("splice")
}

fn s(v: &str) -> Option<String> {
    Some(v.to_string())
}

#[test]
fn replaces_each_span_and_keeps_verbatim_gaps() {
    let plan = token_plan(&["email"], "<X>", None);
    let got = run(&[Some("mail a@b.com now")], &plan, PIECE_BYTE_CEILING);
    assert_eq!(rows(&got), vec![s("mail <X> now")]);
    assert_eq!(mask(&got), vec![false]);
}

#[test]
fn passthrough_email_with_redacted_gaps_pins_the_text_mask_bytes() {
    // AT-4: the span keeps its text, each non-empty gap becomes the token.
    let plan = build_plan(&ids(&["email"]), &[None], &s("<X>")).expect("plan");
    let got = run(
        &[Some("before a@b.com after"), Some("plain"), Some("")],
        &plan,
        PIECE_BYTE_CEILING,
    );
    assert_eq!(rows(&got), vec![s("<X>a@b.com<X>"), s("<X>"), s("")]);
}

#[test]
fn an_empty_replacement_removes_the_span_to_a_valid_empty_string() {
    let plan = build_plan(&ids(&["email"]), &[s("")], &None).expect("plan");
    let got = run(&[Some("a@b.com")], &plan, PIECE_BYTE_CEILING);
    assert_eq!(rows(&got), vec![s("")]);
    assert_eq!(got[0].values.null_count(), 0);
}

#[test]
fn the_longer_span_wins_in_both_request_orders() {
    // AT-8: email and IPv4 start together on `10.0.0.1a@b.com`; the longer email wins.
    for names in [["email", "ipv4"], ["ipv4", "email"]] {
        let outs = names
            .iter()
            .map(|n| s(if *n == "email" { "<E>" } else { "<I>" }))
            .collect::<Vec<_>>();
        let plan = build_plan(&ids(&names), &outs, &None).expect("plan");
        let got = run(&[Some("10.0.0.1a@b.com")], &plan, PIECE_BYTE_CEILING);
        assert_eq!(rows(&got), vec![s("<E>")]);
    }
    let _ = (EMAIL, IPV4);
}

#[test]
fn an_exact_tie_takes_the_first_requested_detectors_literal() {
    // AT-8: npi and us_phone both match `2234567891`; request order breaks the tie, and the
    // winner's own literal is written (M2a uses the other detector's literal).
    for (names, winner) in [
        (["npi", "us_phone"], "<NPI>"),
        (["us_phone", "npi"], "<PHONE>"),
    ] {
        let outs = names
            .iter()
            .map(|n| s(if *n == "npi" { "<NPI>" } else { "<PHONE>" }))
            .collect::<Vec<_>>();
        let plan = build_plan(&ids(&names), &outs, &None).expect("plan");
        let got = run(&[Some("2234567891")], &plan, PIECE_BYTE_CEILING);
        assert_eq!(rows(&got), vec![s(winner)], "request order {names:?}");
    }
}

#[test]
fn adjacent_spans_both_survive_and_get_their_own_literals() {
    let outs = vec![s("<E>"), s("<I>")];
    let plan = build_plan(&ids(&["email", "ipv4"]), &outs, &s("-")).expect("plan");
    let got = run(&[Some("a@b.com10.0.0.1")], &plan, PIECE_BYTE_CEILING);
    assert_eq!(rows(&got), vec![s("<E><I>")]);
}

#[test]
fn nulls_stay_null_and_ineligible_cells_are_declined() {
    let plan = token_plan(&["email"], "<X>", None);
    let long = "x".repeat(10);
    let got = run(
        &[
            Some("a@b.com"),
            None,
            Some("café a@b.com"),
            Some("a\u{1f}b"),
            Some(long.as_str()),
        ],
        &plan,
        PIECE_BYTE_CEILING,
    );
    assert_eq!(rows(&got), vec![s("<X>"), None, None, None, s(&long)]);
    assert_eq!(mask(&got), vec![false, false, true, true, false]);
}

#[test]
fn large_string_input_and_offset_slices_match_the_plain_string_result() {
    let plan = token_plan(&["email"], "<X>", None);
    let big = LargeStringArray::from(vec![Some("skip a@b.com"), Some("mail a@b.com now"), None]);
    let sliced = big.slice(1, 2);
    let got = splice_array(&sliced, &plan, PIECE_BYTE_CEILING).expect("splice");
    assert_eq!(rows(&got), vec![s("mail <X> now"), None]);
    assert_eq!(got.len(), 1);
}

#[test]
fn zero_rows_and_all_null_input_give_one_typed_piece() {
    let plan = token_plan(&["email"], "<X>", None);
    let empty = run(&[], &plan, PIECE_BYTE_CEILING);
    assert_eq!(
        (empty.len(), empty[0].values.len(), empty[0].declined.len()),
        (1, 0, 0)
    );
    let nulls = run(&[None, None], &plan, PIECE_BYTE_CEILING);
    assert_eq!(rows(&nulls), vec![None, None]);
    assert_eq!(mask(&nulls), vec![false, false]);
}

#[test]
fn a_lowered_ceiling_splits_expanding_output_into_aligned_pieces() {
    // AT-3 (raw capacity): each email grows to a 12 byte literal, so a 30 byte ceiling holds two
    // rows per piece. Bytes, order, validity and mask stay complete across the cut.
    let plan = token_plan(&["email"], "<<<TOKEN>>>>", None);
    let input: Vec<Option<&str>> = vec![
        Some("a@b.com"),
        Some("c@d.com"),
        None,
        Some("e@f.com"),
        Some("café"),
        Some("g@h.com"),
    ];
    let got = run(&input, &plan, 30);
    assert!(got.len() > 1, "expected several pieces, got {}", got.len());
    for piece in &got {
        assert_eq!(piece.values.len(), piece.declined.len());
        assert!(piece.values.value_data().len() <= 30);
        assert_eq!(piece.values.offsets().first().copied(), Some(0));
    }
    let token = "<<<TOKEN>>>>";
    assert_eq!(
        rows(&got),
        vec![s(token), s(token), None, s(token), None, s(token)]
    );
    assert_eq!(mask(&got), vec![false, false, false, false, true, false]);
}

#[test]
fn a_single_row_larger_than_the_ceiling_takes_its_own_piece() {
    let plan = token_plan(&["email"], "<X>", Some("."));
    let wide = "word ".repeat(10);
    let got = run(
        &[Some("a@b.com"), Some(wide.as_str()), Some("a@b.com")],
        &plan,
        8,
    );
    assert_eq!(rows(&got), vec![s("<X>"), s("."), s("<X>")]);
    let wide_plan = build_plan(&ids(&["email"]), &[None], &None).expect("plan");
    let verbatim = run(&[Some("a@b.com"), Some(wide.as_str())], &wide_plan, 8);
    assert_eq!(rows(&verbatim), vec![s("a@b.com"), s(&wide)]);
    assert!(verbatim.iter().any(|p| p.values.value_data().len() > 8));
}

#[test]
fn a_non_string_array_is_unsupported() {
    let plan = token_plan(&["email"], "<X>", None);
    let ints = arrow_array::Int64Array::from(vec![1, 2]);
    assert_eq!(
        splice_array(&ints, &plan, PIECE_BYTE_CEILING).err(),
        Some(SpliceError::UnsupportedType)
    );
}

#[test]
fn plan_rejects_conflicting_duplicate_ids_in_both_orders() {
    let conflict = [s("<A>"), s("<B>")];
    assert_eq!(
        build_plan(&ids(&["email", "email"]), &conflict, &None).err(),
        Some(SpliceError::OutputInvalid)
    );
    let verbatim_then_token = [None, s("<B>")];
    assert_eq!(
        build_plan(&ids(&["email", "email"]), &verbatim_then_token, &None).err(),
        Some(SpliceError::OutputInvalid)
    );
    let token_then_verbatim = [s("<B>"), None];
    assert_eq!(
        build_plan(&ids(&["email", "email"]), &token_then_verbatim, &None).err(),
        Some(SpliceError::OutputInvalid)
    );
}

#[test]
fn plan_accepts_identical_duplicates_and_rejects_bad_lengths_and_ids() {
    let same = [s("<X>"), s("<X>")];
    let plan = build_plan(&ids(&["email", "email"]), &same, &None).expect("plan");
    let got = run(&[Some("a@b.com")], &plan, PIECE_BYTE_CEILING);
    assert_eq!(rows(&got), vec![s("<X>")]);
    let both_verbatim = build_plan(&ids(&["email", "email"]), &[None, None], &None).expect("plan");
    let kept = run(&[Some("a@b.com")], &both_verbatim, PIECE_BYTE_CEILING);
    assert_eq!(rows(&kept), vec![s("a@b.com")]);

    assert_eq!(
        build_plan(&ids(&["email"]), &[], &None).err(),
        Some(SpliceError::OutputInvalid)
    );
    assert_eq!(
        build_plan(&ids(&["email"]), &[s("a"), s("b")], &None).err(),
        Some(SpliceError::OutputInvalid)
    );
    assert_eq!(
        build_plan(&ids(&["nope"]), &[s("a")], &None).err(),
        Some(SpliceError::UnknownDetector)
    );
}
