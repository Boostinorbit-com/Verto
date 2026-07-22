"""VERTO CLI copy deck + presentation — all user-facing help prose in one place.

The single home for the CLI's *framing* text and its look: product tagline, each
command's summary, the usage/examples footers, and the (TTY-gated) styling. Per-flag
`help=` strings stay inline in cli.py so they can't drift; only voice + design live
here, so DX/marketing can tune the product's first impression without touching code.

Color is applied ONLY to CLI-display strings (tagline, epilogs). The command
summaries (*_DESC) stay plain because they are ALSO rendered into Docs/VERTO_Flags.md.

NOTE: the URLs below are launch placeholders — set the real ones at release.
"""
from __future__ import annotations

import os
import sys

WEBSITE = "https://verto.dev"
DOCS = "https://docs.verto.dev"

# --- styling: on only for an interactive terminal that hasn't opted out ---
_COLOR = (sys.stdout.isatty() and "NO_COLOR" not in os.environ
          and os.environ.get("TERM") != "dumb")


def _sgr(code: str):
    return (lambda t: f"\033[{code}m{t}\033[0m") if _COLOR else (lambda t: t)


_B, _D, _ACCENT = _sgr("1"), _sgr("2"), _sgr("36")   # bold, dim, cyan


def section(title: str) -> str:
    """Style an argparse group heading (bold + uppercase) — used by the formatter."""
    return _B(title.upper())


def _h(title: str) -> str:            # epilog section header, matches section() styling
    return _B(title.upper())


# --- product tagline (top of `verto --help`) ---
DESCRIPTION = (
    f"{_B('VERTO')}  ·  Verified Performance Optimizer for C++\n"
    f"{_D('Ship faster code with a guarantee: every change is proven correct AND faster — or rejected.')}"
)

# --- usage lines (rendered under a styled USAGE header; keep PLAIN) ---
USAGE_MAIN = "verto <command> [options]"
USAGE_OPTIMIZE = ("verto optimize <path> [options]\n"
                  "verto optimize -p <db> --all [options]")
USAGE_ANALYZE = ("verto analyze <path> [options]\n"
                 "verto analyze -p <db> --all [options]")
USAGE_SERVE = "verto serve [--stop]"

# --- one-line command summaries (command list + per-command help + the docs) — keep PLAIN ---
OPTIMIZE_DESC = "Find, verify, and apply performance improvements."
ANALYZE_DESC = "Inspect optimization opportunities without changing anything."
REPORT_DESC = "Review what's been accepted, rejected, and the gains so far."
SERVE_DESC = "Run a warm background daemon so repeated runs are fast."

# --- top-level footer ---
MAIN_EPILOG = f"""\
{_h('Getting started')}
  {_ACCENT('verto optimize src/hot.cpp --offline')}     optimize one file (no model needed)
  {_ACCENT('verto optimize -p build/ --all')}           optimize a whole codebase
  {_ACCENT('verto serve')}                              start the daemon for fast repeat runs

{_h('Common options')} {_D('(shared by analyze & optimize — run `verto optimize --help` for detail)')}
  {_B('Target')}    <path>                      source file (single-file mode)
            -p, --compile-commands DB   compilation database (a file or build dir)
            --all                       every translation unit in the database
  {_B('Policy')}    --min-rung N                correctness rung to accept (default 3)
            --fast                      skip the sanitizer — UNSOUND, labeled
            --offline                   deterministic rules, no model
            --model NAME                proposer model
  {_B('Output')}    --json                      machine-readable output
            --config-file FILE          project config (.verto.toml)
            --no-daemon                 run in-process, ignore the daemon
  {_D('Planned')}   {_D('--apply')}                     {_D('write changes to source (not yet implemented)')}
            {_D('--profile FILE')}              {_D('external profile input (not yet consumed)')}

{_h('Learn more')}
  {_ACCENT('verto <command> --help')}                   full, always-current help for a command
  {_ACCENT('Docs/VERTO_Flags.md')}                      generated flag reference (never drifts)
  Documentation                            {DOCS}
  Website                                  {WEBSITE}

{_D('The promise: VERTO keeps a change only when it is proven both correct and faster.')}
"""

# --- per-command footers ---
OPTIMIZE_EPILOG = f"""\
{_h('Examples')}
  {_D('# one self-contained file (deterministic, no model)')}
  {_ACCENT('verto optimize src/hot.cpp --offline')}

  {_D('# one file, using its real build flags from the project')}
  {_ACCENT('verto optimize src/hot.cpp -p build/')}

  {_D('# every translation unit in a codebase')}
  {_ACCENT('verto optimize -p build/ --all')}

  {_D('# machine-readable results for CI')}
  {_ACCENT('verto optimize -p build/ --all --json')}

{_h('Exit codes')}
  {_B('0')}  a verified improvement was found      {_B('2')}  error
  {_B('1')}  nothing to optimize                   {_B('3')}  candidates found, none passed

{_D(f'Docs: {DOCS}/optimize')}
"""

ANALYZE_EPILOG = f"""\
{_D('analyze runs the FULL verification (compile + sanitizer + benchmark) but writes')}
{_D('nothing and records nothing — the safe "what would you do?" command. Use optimize')}
{_D('when you want to keep the changes.')}

{_h('Examples')}
  {_ACCENT('verto analyze src/hot.cpp')}          {_D('inspect one file')}
  {_ACCENT('verto analyze -p build/ --all')}      {_D('inspect a whole codebase')}

{_D(f'Docs: {DOCS}/analyze')}
"""

SERVE_EPILOG = f"""\
{_D('The daemon loads Python + libclang once and keeps them warm, so later optimize/')}
{_D('analyze calls skip startup. Calls use it automatically; pass --no-daemon to opt out.')}

  {_ACCENT('verto serve')}          {_D('start the daemon (Ctrl-C to stop)')}
  {_ACCENT('verto serve --stop')}   {_D('stop a running daemon')}

{_D(f'Docs: {DOCS}/serve')}
"""
