### Added (Gaussian copula model and numerical parts, V2-4.2/4.3 part A, 2026-11-19)

V2 track, built ahead, opt-in by import only. New package `decoy_engine.generation.copula` with the
copula model artifact: `GaussianCopulaModel` (snapshot marginals plus a latent correlation matrix
released at 3 decimals, with the variables a disclosure floor suppressed listed) and its strict JSON
form `decoy-gaussian-copula/v1` (`to_dict`, `from_dict`, which never repairs and whose errors carry
no value), the disclosure floors as named constants, vectorized Cody and AS241 normal functions and
Higham's nearest correlation matrix with structural zeros held. Fitting and sampling follow in part
B. No config key, strategy, catalog row, run behaviour, reason code or dependency changes.
