"""One ambient guard for a caller-named directory tree that is then read only beneath its handle.

``open_ambient_tree`` is for a route that is handed a directory path (a signed evidence bundle) and
must read inside it without ever following a link below the named root. It refuses every policy but
the ambient one (``require_ambient``) before it opens anything, opens the named root once, and hands
back an ``FdDirHandle``. Every later open goes through that handle's confined, no-follow primitives,
so the one ambient open here is the only place a caller path is resolved.

The final component of the caller's path follows a symlink: the caller named it, as an ``open`` of a
directory path always did. Nothing beneath it does.

A refusal is one ``FileAccessDenied`` with a fixed field key and a closed ``kind``: ``absent`` for a
missing root, ``not_regular`` when the root is not a directory, ``unreadable`` for the rest. It is
raised outside the ``except`` block, so it holds no OS text, path or ``__context__``.
"""

from __future__ import annotations

import errno
import os
import stat as stat_mod
from os import open as open_fd  # a plain name: the GCS call-kwargs sentry matches methods by name

from decoy_engine.fileaccess._entry import require_ambient
from decoy_engine.fileaccess._errors import deny
from decoy_engine.fileaccess._rooted import FdDirHandle
from decoy_engine.fileaccess._types import DenialKind

__all__ = ["open_ambient_tree"]

_FIELD_KEY = "evidence directory"


def open_ambient_tree(path: str | os.PathLike[str]) -> FdDirHandle:
    """Open the directory ``path`` once and return a held handle over it. Ambient policy only."""
    require_ambient("an ambient directory tree")
    kind: DenialKind | None = None
    fd = -1
    try:
        fd = open_fd(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            kind = "absent"
        elif exc.errno == errno.ENOTDIR:
            kind = "not_regular"
        else:
            kind = "unreadable"
    except ValueError:
        kind = "unreadable"
    if fd >= 0:
        try:
            if not stat_mod.S_ISDIR(os.fstat(fd).st_mode):
                kind = "not_regular"
        except OSError:
            kind = "unreadable"
        if kind is not None:
            os.close(fd)
    if kind is not None:
        raise deny(_FIELD_KEY, kind=kind)
    return FdDirHandle(fd, _FIELD_KEY)
