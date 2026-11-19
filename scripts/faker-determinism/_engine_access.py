"""The one place `scripts/faker-determinism/` reaches engine-internal names.

The pool harness and the output lock both need production-private seams (the Faker pool builder,
the reflected provider set, the raw text-mask and date-of-birth call shapes). This module is the accepted same-repo dev-tool exception to the
public-import rule, not a public API; AT-L15 fails if another file here imports
`decoy_engine.internal` directly.
"""

from __future__ import annotations

import functools
import random
from types import SimpleNamespace

from decoy_engine.generation import _faker_pool
from decoy_engine.generation._dob_anchor import anchored_date_of_birth
from decoy_engine.generators._formula import _FormulaMixin
from decoy_engine.internal.faker_setup import get_faker_providers, make_faker, reflected_kwargs
from decoy_engine.providers_v2 import _faker_adapter, get_default_registry
from decoy_engine.transforms.text_mask import _mask_faker as mask_faker_span

faker_method_map = _faker_adapter._FAKER_METHOD_MAP
default_registry = get_default_registry


def dob_method(fake):
    """The anchored date-of-birth helper bound to `fake`, as the reflected wrapper binds it."""
    return functools.partial(anchored_date_of_birth, fake)


def formula_scope(fake):
    """The production formula callable table over a controlled Faker-backed object."""
    owner = SimpleNamespace(faker=fake, _reference_date=None)
    return _FormulaMixin._formula_scope(owner, 0, rng=random.Random(0))  # type: ignore[arg-type]


__all__ = [
    "_faker_pool",
    "anchored_date_of_birth",
    "default_registry",
    "dob_method",
    "faker_method_map",
    "formula_scope",
    "get_faker_providers",
    "make_faker",
    "mask_faker_span",
    "reflected_kwargs",
]
