"""F9: the identifier sub-import re-exports the families from providers_v2.

The identifier validators/adapters/domains are not bound on the top-level
``decoy_engine`` module; their home is ``decoy_engine.identifiers``.
This guards that the sub-import resolves and stays in sync with the source
package's objects, and that the root no longer binds them.
"""

import decoy_engine.identifiers as identifiers
from decoy_engine.providers_v2 import identifiers as source


def test_subimport_exports_identifier_families():
    expected = {
        "EinAdapter",
        "EinDomain",
        "EinValidator",
        "IdentifierError",
        "IdentifierFormatError",
        "MrnAdapter",
        "MrnDomain",
        "MrnValidator",
        "NdcAdapter",
        "NdcDomain",
        "NdcValidator",
        "NpiAdapter",
        "NpiDomain",
        "NpiValidator",
        "SsnAdapter",
        "SsnDomain",
        "SsnValidator",
    }
    assert set(identifiers.__all__) == expected


def test_subimport_objects_are_the_source_objects():
    for name in identifiers.__all__:
        assert getattr(identifiers, name) is getattr(source, name)


def test_root_no_longer_binds_the_trimmed_names():
    import decoy_engine

    trimmed = [
        *identifiers.__all__,
        "BundlePool",
        "CompositeAddress",
        "PoolCache",
        "composite_city_state_zip",
    ]
    assert len(trimmed) == 21
    for name in trimmed:
        assert not hasattr(decoy_engine, name), name
        assert name not in decoy_engine.__all__
