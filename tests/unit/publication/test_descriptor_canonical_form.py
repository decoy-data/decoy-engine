"""The descriptor and its `result_id` use the engine's one canonical JSON form (D3).

`decoy_engine._canonical.canonical_json_bytes` writes text as-is (UTF-8, not `\\u` escapes), so a
non-ASCII artifact path is where the stored bytes and the digest input show which form is used.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json

from decoy_engine._canonical import canonical_json_bytes
from decoy_engine.publication import _descriptor as codec
from tests.sentry.defects.test_canonical_json_choke_point import sorted_dump_sites

NON_ASCII = "données/tëst.parquet"


def _built() -> codec.Descriptor:
    arts = [
        codec.Artifact(role="table", path="accounts.parquet", size=512, sha256="1" * 64, rows=2),
        codec.Artifact(role="table", path=NON_ASCII, size=1, sha256="4" * 64, rows=0),
    ]
    return codec.build_descriptor(operation_id="op-1", artifacts=arts, vault=None)


def test_descriptor_bytes_and_result_id_are_the_canonical_form() -> None:
    built = _built()
    raw = codec.encode_descriptor(built)
    document = json.loads(raw.decode("utf-8"))
    ascii_form = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    # non-vacuity: for this document the two forms differ, so equality below picks one
    assert canonical_json_bytes(document) != ascii_form.encode("ascii")
    assert raw == canonical_json_bytes(document)
    assert NON_ASCII.encode("utf-8") in raw
    listed = document["artifacts"]
    expected = hashlib.sha256(codec.RESULT_DOMAIN + canonical_json_bytes(listed)).hexdigest()
    assert built.result_id == expected
    assert codec.decode_descriptor(raw) == built


def test_descriptor_module_has_no_sorted_key_dump_of_its_own() -> None:
    tree = ast.parse(inspect.getsource(codec))
    assert sorted_dump_sites(tree) == []
