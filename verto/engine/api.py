"""The Engine API — the single contract every surface calls.

Mirrors VERTO_Architecture §5. analyze / optimize / report. Returns structured
data, never prints. The CLI/CI/IDE/SDK are thin clients over this.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import registry
from .apply_txn import ApplyError, ApplyTransaction
from .config import Config
from .ledger import JsonlLedger
from .models import Evidence, Target, Verdict
from .orchestrator import Orchestrator


class Engine:
    def __init__(self, config: Config | None = None) -> None:
        from . import workspace
        from .cache import RewriteCache
        self.config = config or Config()
        # Ledger lives in the `.verto/` workspace when one exists (post `verto init`),
        # else the legacy repo-root `ledger.jsonl` — so nothing breaks without init.
        self.ledger = JsonlLedger(workspace.ledger_path())
        # Best-so-far rewrite cache (workspace-scoped; None → recompute each run, no persistence).
        self.cache = RewriteCache(workspace.cache_path())

    def analyze(self, file: str, *, build: dict | None = None) -> list[Verdict]:
        """Non-destructive: run the loop, write nothing, don't pollute the Ledger."""
        return self._run(file, apply=False, persist=False, build=build)

    def optimize(self, file: str, *, apply: bool, build: dict | None = None,
                 backup: bool = False, force: bool = False) -> list[Verdict]:
        # persist=True even on a DRY RUN: the ledger is the record of what VERTO tried and
        # why it said no, which is most of its value on a file that yields no win. It used
        # to key on `apply`, so `verto optimize` without --apply wrote every verdict to
        # /dev/null. Safe: no proposer reads priors to SKIP work (see rules.py:30), so
        # recording rejects can't suppress a later attempt. `analyze()` stays silent.
        return self._run(file, apply=apply, persist=True, build=build,
                         backup=backup, force=force)

    def optimize_codebase(self, cc_path: str, *, apply: bool = False,
                          backup: bool = False, force: bool = False,
                          changed: str | None = None, jobs: int = 1,
                          on_done=None
                          ) -> list[tuple[str, list[Verdict], str | None, list]]:
        """Codebase mode: iterate every C++ translation unit in a
        compile_commands.json, in ONE process (startup + libclang amortized),
        parsing/compiling each with its real flags. Returns
        (file, verdicts, error, skips) per TU — `skips` are sites seen but not
        optimized, with reasons (item #4); a TU that blows up is recorded (error
        set), never aborts the run.

        Scale (item #8): `changed` (a git ref, or "" for the working tree) restricts
        the run to TUs git reports as modified vs that ref; `jobs` > 1 processes TUs
        in parallel (verification is subprocess-bound, so threads give real
        speedup — at some cost to benchmark precision under load)."""
        from ..adapters.language.cpp import compile_db, link
        tus = [tu for tu in compile_db.load(cc_path)
               if registry.language_of(tu.file) == "cpp"]
        if changed is not None:                          # item #8a: only git-changed TUs
            touched = _git_changed(cc_path, changed)
            tus = [tu for tu in tus if os.path.realpath(tu.file) in touched]
        ledger = self.ledger              # dry runs record too — see optimize()
        # item #9: ONE transaction for the whole codebase → all-or-nothing apply.
        txn = ApplyTransaction(backup=backup) if apply else None

        def _do(tu):
            try:
                adapters = registry.resolve(tu.file, self.config)
                # Phase-1 item #1: link the harness against the rest of the build so
                # a function that calls into other TUs can be verified (cached).
                archive = link.project_archive(tus, tu.file)
                target = Target(file=tu.file, symbol=Path(tu.file).stem, line=0,
                                language="cpp",
                                build={"parse_flags": tu.flags, "compile_flags": tu.flags,
                                       "opt_flags": tu.opt_flags,
                                       "link_inputs": [archive] if archive else []})
                orch = Orchestrator(adapters, ledger, config=self.config, cache=self.cache)
                verdicts = orch.run(target, apply=apply, backup=backup, force=force, txn=txn)
                return (tu.file, verdicts, None, orch.last_skips)
            except ApplyError:
                raise                                    # a write failure → roll back the whole batch
            except Exception as e:                       # one bad TU must not sink the batch
                return (tu.file, [], f"{type(e).__name__}: {e}", [])

        total = len(tus)

        def _tick(i, r):
            # live per-TU feedback (item #4 UX): fire the callback as each TU completes,
            # so a 43-TU run reports one line at a time instead of going silent for minutes.
            if on_done:
                on_done(i, total, *r)
            return r

        try:
            results = []
            if jobs and jobs > 1 and total > 1:          # item #8b: parallel TU processing
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=jobs) as ex:
                    for i, r in enumerate(ex.map(_do, tus), 1):   # yields in input order
                        results.append(_tick(i, r))
            else:
                for i, tu in enumerate(tus, 1):
                    results.append(_tick(i, _do(tu)))
        except BaseException:
            if txn is not None:
                txn.rollback()                           # never leave a half-edited codebase
            raise
        if txn is not None:
            txn.commit()
        return results

    def report(self) -> dict:
        priors = self.ledger.recall(_dummy_evidence())
        return {
            "accepted": len(priors.accepted_transforms),
            "rejected": len(priors.rejected_transforms),
            "accepted_transforms": priors.accepted_transforms,
        }

    # --- internal ---
    def _run(self, file: str, *, apply: bool, persist: bool, build: dict | None = None,
             backup: bool = False, force: bool = False) -> list[Verdict]:
        adapters = registry.resolve(file, self.config)
        language = registry.language_of(file)
        target = Target(file=file, symbol=Path(file).stem, line=0, language=language,
                        build=_own_include(file, build or {}) if language == "cpp" else (build or {}))
        ledger = self.ledger if persist else JsonlLedger(os.devnull)
        txn = ApplyTransaction(backup=backup) if apply else None    # item #9
        try:
            verdicts = Orchestrator(adapters, ledger, config=self.config, cache=self.cache).run(
                target, apply=apply, backup=backup, force=force, txn=txn)
        except BaseException:
            if txn is not None:
                txn.rollback()                                      # never leave a half-edited file
            raise
        if txn is not None:
            txn.commit()
        return verdicts


def _own_include(file: str, build: dict) -> dict:
    """Put the source file's OWN directory on the include path (single-file mode).

    The harness is a synthesized file compiled in a temp workdir, and a compiler
    resolves a quoted include (`#include "clist.h"`) relative to the INCLUDING file
    — i.e. the workdir, not the real source dir. So the ORIGINAL failed to build and
    every candidate in a file with a local header came back `skipped_unverifiable`,
    with nothing about the rewrite ever tested. Codebase mode already gets this from
    compile_db.load()'s `own`; single-file mode only got it via `-p`, if at all.
    """
    own = "-I" + (os.path.dirname(os.path.abspath(file)) or ".")
    out = dict(build)
    for key in ("parse_flags", "compile_flags"):
        flags = list(out.get(key) or ())
        out[key] = flags if own in flags else [*flags, own]
    return out


def _dummy_evidence() -> Evidence:
    return Evidence(target=Target(file="_", symbol="_", line=0, language="cpp"), source="")


def _git_changed(cc_path: str, ref: str) -> set[str]:
    """Absolute paths of files git reports as modified vs `ref` (empty string →
    the working tree vs HEAD), plus untracked files (so a brand-new .cpp is
    included). Item #8a. Best-effort: returns an empty set if git isn't available,
    which makes `--changed` match nothing rather than silently scan everything."""
    import subprocess
    from ..adapters.language.cpp import compile_db
    db = compile_db.find(cc_path)
    start = str(db.parent) if db is not None else cc_path
    try:
        root = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        root = ""
    if not root:
        return set()

    def _lines(args: list[str]) -> list[str]:
        try:
            r = subprocess.run(["git", "-C", root, *args], capture_output=True,
                               text=True, timeout=30)
            return r.stdout.splitlines() if r.returncode == 0 else []
        except Exception:
            return []

    out: set[str] = set()
    for ln in _lines(["diff", "--name-only", ref or "HEAD"]):
        out.add(os.path.realpath(os.path.join(root, ln.strip())))
    for ln in _lines(["ls-files", "--others", "--exclude-standard"]):   # untracked
        out.add(os.path.realpath(os.path.join(root, ln.strip())))
    return out
