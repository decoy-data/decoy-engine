"""The identifier and digest patterns every signed-evidence document shares, defined once."""

from __future__ import annotations

import re

__all__ = ["DIGEST", "DIGEST_PATTERN", "ID", "ID_PATTERN", "MEDIA", "MEDIA_PATTERN"]

ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
DIGEST_PATTERN = r"sha256:[0-9a-f]{64}"
MEDIA_PATTERN = r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}"

ID = re.compile(rf"^{ID_PATTERN}\Z")
DIGEST = re.compile(rf"^{DIGEST_PATTERN}\Z")
MEDIA = re.compile(rf"^{MEDIA_PATTERN}\Z")
