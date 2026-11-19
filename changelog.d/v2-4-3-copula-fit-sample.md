### Added (Gaussian copula fit and sample, V2-4.2/4.3 part B, 2026-11-19)

V2 track, built ahead, opt-in by import only. `decoy_engine.generation.copula` gains
`fit_gaussian_copula(frame, snapshot, seed=...)`, which keeps the frame's `distribution-snapshot/v1`
marginals (checked against a recomputed snapshot) and adds a latent correlation matrix (rank-based
normal scores for numeric columns, frequency intervals for categorical columns, null as its own
state), repaired to the nearest correlation matrix and released at 3 decimals under disclosure
floors (at least 100 rows; sparse, near-constant or finely binned variables are suppressed whole and
listed in the model), and `sample_gaussian_copula(model, n, seed=..., start=...)`, which draws rows
that keep pairwise dependence; a window equals the same rows of a full draw. Both take caller seed
bytes and drop them as soon as the stream is derived. The model is not differentially private and
holds the snapshot's real bin edges and category labels. Datetime and freetext columns are refused.
No config key, strategy, catalog row, run behaviour, reason code or dependency changes.
