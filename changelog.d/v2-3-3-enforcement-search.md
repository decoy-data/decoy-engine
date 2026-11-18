### Added (anonymity enforcement search, V2-3.3 Part B, 2026-11-12)

V2 track, built ahead, opt-in by import only. `decoy_engine.anonymize.search.search_lattice` finds the
node of a generalization `Lattice` with the least information loss (Iyengar loss metric by default;
discernibility or non-uniform entropy on request) whose classes meet every privacy model within a
record-suppression limit, and returns a frozen, value-free `SearchResult` (chosen node, the three loss
figures, rows suppressed, nodes evaluated). The search is optimal over lattices of up to 5,000 nodes
(larger ones are refused) and also when entropy l, recursive (c, l) or t-closeness are not monotone under
suppression. `apply_search` returns the generalized table with the suppressed rows removed, plus a row
mask. Every class comes from `quality.anonymity.FrequencySet`; the search groups nothing itself. No
config key, strategy, catalog row, planner check or reason code is added. Limits:
`docs/what-we-cannot-prove.md`.
