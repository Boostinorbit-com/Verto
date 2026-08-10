#!/usr/bin/env python3
"""Generate the CLI flag reference straight from the argparse parser.

The parser in boostopt/surfaces/cli.py is the single source of truth for what flags
actually exist. This walks it and writes a standalone Markdown reference of the
flags wired TODAY — so the reference can never claim a flag that isn't built (the
drift we hit when flag docs lived in the hand-written design doc).

Usage:
  python tools/gen_flags.py                       # print to stdout
  python tools/gen_flags.py --write Docs/BOOSTOPT_Flags.md   # (re)write the file
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boostopt.surfaces.cli import _parser  # noqa: E402

_NO_VALUE = (argparse._StoreTrueAction, argparse._StoreFalseAction,
             argparse._StoreConstAction, argparse._HelpAction,
             argparse._VersionAction)


def _spec(action) -> str:
    if not action.option_strings:                       # positional
        return f"`<{action.dest}>`"
    opts = ", ".join(action.option_strings)
    if isinstance(action, _NO_VALUE):
        return f"`{opts}`"
    mv = action.metavar or action.dest.upper()
    return f"`{opts} {mv}`"


def _subparsers(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices           # OrderedDict: name -> subparser
    return {}


def render() -> str:
    parser = _parser()
    out = [
        "# BOOSTOPT — CLI Flag Reference",
        "",
        "> **Auto-generated** from `boostopt --help` by `tools/gen_flags.py`. "
        "Do not edit by hand — regenerate with:",
        "> ```",
        "> python tools/gen_flags.py --write Docs/BOOSTOPT_Flags.md",
        "> ```",
        "> These are the flags **actually wired today**. The design roadmap "
        "(including planned flags) lives in `BOOSTOPT_Surfaces.md`.",
        "",
    ]
    glob = [a for a in parser._actions if a.option_strings
            and not isinstance(a, (argparse._HelpAction, argparse._SubParsersAction))]
    if glob:
        out.append("## `boostopt` (global)")
        out.append("\n**options**\n")
        out.append("| flag | description |")
        out.append("|---|---|")
        for ac in glob:
            h = (ac.help or "").replace("|", "\\|")
            out.append(f"| {_spec(ac)} | {h} |")
        out.append("")

    for name, sp in _subparsers(parser).items():
        groups = [(g.title, [a for a in g._group_actions
                             if not isinstance(a, argparse._HelpAction)])
                  for g in sp._action_groups]
        groups = [(t, acts) for t, acts in groups if acts]
        if not groups:
            continue
        out.append(f"## `boostopt {name}`")
        if sp.description:
            out.append(f"\n{sp.description}")
        for title, actions in groups:
            out.append(f"\n**{title}**\n")
            out.append("| flag | description |")
            out.append("|---|---|")
            for ac in actions:
                help_txt = (ac.help or "").replace("|", "\\|")
                out.append(f"| {_spec(ac)} | {help_txt} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="emit the boostopt CLI flag reference")
    ap.add_argument("--write", metavar="FILE", help="write the reference to this file")
    args = ap.parse_args(argv)
    doc = render()
    if args.write:
        Path(args.write).write_text(doc, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
