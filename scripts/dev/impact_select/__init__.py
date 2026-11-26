"""Impact-based test selection tooling (dev only, never packaged).

`scripts/dev/impact_map.py` builds the map; the selector reads it through `_select_map.load_map`.
Both sides take the environment fingerprint from `_select_env.fingerprint`. Stdlib only, so the
build venv's bootstrap and the gates venv can both import it.
"""
