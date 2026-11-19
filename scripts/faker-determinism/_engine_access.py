"""The one place `scripts/faker-determinism/` reaches engine-internal names.

The pool harness and the output lock both need production-private seams (the Faker pool builder,
the reflected provider set, the raw text-mask and date-of-birth call shapes). This module is the accepted same-repo dev-tool exception to the
public-import rule, not a public API; AT-L15 fails if another file here imports
`decoy_engine.internal` directly.
"""

from __future__ import annotations

from decoy_engine.generation import _faker_pool
from decoy_engine.generation._dob_anchor import anchored_date_of_birth
from decoy_engine.internal.faker_setup import get_faker_providers, make_faker, reflected_kwargs
from decoy_engine.transforms.text_mask import _mask_faker as mask_faker_span

__all__ = [
    "_faker_pool",
    "anchored_date_of_birth",
    "get_faker_providers",
    "make_faker",
    "mask_faker_span",
    "reflected_kwargs",
]
