"""`OpaqueBox.item` returns the carried value and the box still hides it from repr."""

from __future__ import annotations

from decoy_engine._opaque import OpaqueBox


def test_item_returns_the_carried_value_and_repr_hides_it() -> None:
    box = OpaqueBox(b"k-canary", "second")
    assert box.item(0) == b"k-canary"
    assert box.item(1) == "second"
    assert "canary" not in repr(box) and "canary" not in str(box)
