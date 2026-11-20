"""Gaussian copula synthesis: synthetic rows that keep pairwise dependence between columns.

The model artifact (`GaussianCopulaModel`, strict `to_dict`/`from_dict`,
`decoy-gaussian-copula/v1`) and the disclosure floors its correlation release is held to. Library
only: no config key or strategy reaches this package, and the model is not differentially
private. It holds a snapshot's real bin edges and category labels, so treat it like the exact
snapshot.
"""

from decoy_engine.generation.copula._floors import (
    MAX_LATENT,
    MIN_DISTINGUISHED_ROWS,
    MIN_FIT_ROWS,
    MIN_PAIR_ROWS,
    ROWS_PER_BIN,
)
from decoy_engine.generation.copula._model import (
    COPULA_MODEL_SCHEMA_VERSION,
    ColumnMarginal,
    GaussianCopulaModel,
    Suppression,
)

__all__ = [
    "COPULA_MODEL_SCHEMA_VERSION",
    "MAX_LATENT",
    "MIN_DISTINGUISHED_ROWS",
    "MIN_FIT_ROWS",
    "MIN_PAIR_ROWS",
    "ROWS_PER_BIN",
    "ColumnMarginal",
    "GaussianCopulaModel",
    "Suppression",
]
