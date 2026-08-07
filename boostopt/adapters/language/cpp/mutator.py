"""C++ Mutator — apply a Transform to source -> Variant (source->source).

Mirrors BOOSTOPT_Architecture §16.2. Generic: it delegates the actual edit to the
transform's own `rewrite(source)` (each transform is self-contained). The
libclang source-location version (build step 5) makes edits robust.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from ....engine.config import Config
from ....engine.models import Target, Variant


class CppMutator:
    def __init__(self, config: Config) -> None:
        self._config = config

    def apply(self, target: Target, transform: object) -> Variant:
        source = Path(target.file).read_text(encoding="utf-8")
        result = transform.rewrite(source)
        if result is None:
            name = getattr(transform, "name", "?")
            raise ValueError(f"mutator: {name} could not rewrite {target.file}")
        new_source, _ = result           # the transform's cosmetic patch is discarded
        # a REAL unified diff — what `--apply` writes and the preview shows. Use a RELATIVE
        # path in the a/ b/ headers (codebase mode carries absolute paths from the compile DB,
        # which would render as `a//abs/path`); relative keeps it clean AND `git apply -p1`-able.
        rel = os.path.relpath(target.file)
        patch = "".join(difflib.unified_diff(
            source.splitlines(keepends=True), new_source.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}", n=2))
        return Variant(target=target, patch=patch, source_after=new_source)
