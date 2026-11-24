"""The one no-clobber hard link and its errno map, a leaf under every caller that links.

Pattern: Maildir delivery and git `finalize_object_file`: `link(2)` places a finished file and the
file system decides whether the name is taken. `link_noclobber_at` is the descriptor form (two
validated components beneath held directories, never following a symlink). `raise_link_error` is
the one errno map: the ambient arm that has no descriptor form (Windows, or a backend whose
`os.link` takes no `dir_fd`) calls the plain two-path `os.link` itself and maps its errno here, so
both forms answer the same way. Errors keep only their errno.
"""

from __future__ import annotations

import errno
import os

from decoy_engine.fileaccess._component import validate_component
from decoy_engine.fileaccess._types import LinkUnsupported

__all__ = ["CREATOR_KEY", "link_noclobber_at", "raise_link_error"]

CREATOR_KEY = "fileaccess.stage"  # the denial key for a bad name given straight to a creator
# A link failing with one of these means the file system cannot hard-link here (EPERM: FAT and
# some FUSE and SMB mounts; EOPNOTSUPP and ENOTSUP: no link support; ENOSYS: no `linkat`; EXDEV:
# another device), not that the name is taken. Every caller maps them to `LinkUnsupported`.
LINK_UNSUPPORTED = frozenset(
    {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS, errno.EXDEV}
)


def raise_link_error(code: int) -> None:
    """Raise what a link that failed with `code` means; return when `code` is 0. Call it outside
    the `except` that caught the `OSError`, so no context rides along."""
    if code == errno.EEXIST:
        raise FileExistsError(errno.EEXIST, "output exists")
    if code in LINK_UNSUPPORTED:
        raise LinkUnsupported(code)
    if code:
        raise OSError(code, os.strerror(code))


def link_noclobber_at(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """Link `src_name` to `dst_name` without replacing it. Raises `FileExistsError` for a taken
    name, `LinkUnsupported` for `LINK_UNSUPPORTED` (or a backend whose `os.link` has no descriptor
    form) and an errno-only `OSError` for anything else."""
    validate_component(src_name, CREATOR_KEY)
    validate_component(dst_name, CREATOR_KEY)
    code = 0
    try:
        os.link(
            src_name, dst_name, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=False
        )
    except OSError as exc:
        code = exc.errno or errno.EIO
    except (NotImplementedError, TypeError):  # no descriptor or no-follow form on this backend
        code = errno.ENOSYS
    raise_link_error(code)
