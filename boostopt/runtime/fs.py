"""Small filesystem helpers shared across layers."""
from __future__ import annotations

import os
import threading


def unique_tmp(path, suffix: str = "tmp") -> str:
    """A process- AND thread-unique temp sibling of `path`, so concurrent apply/build
    (item #8) never collide on the same temp file. `os.getpid()` alone is not enough:
    a thread pool shares one pid."""
    return f"{path}.{os.getpid()}.{threading.get_ident()}.{suffix}"
