"""BOOSTOPT CLI copy deck + presentation — all user-facing help prose in one place.

The single home for the CLI's *framing* text and its look: product tagline, each
command's summary, the usage/examples footers, and the (TTY-gated) styling. Per-flag
`help=` strings stay inline in cli.py so they can't drift; only voice + design live
here, so DX/marketing can tune the product's first impression without touching code.

Color is applied ONLY to CLI-display strings (tagline, epilogs). The command
summaries (*_DESC) stay plain because they are ALSO rendered into Docs/BOOSTOPT_Flags.md.

NOTE: the URLs below are launch placeholders — set the real ones at release.
"""
from __future__ import annotations

import os
import sys

WEBSITE = "https://boostopt.com"
DOCS = "https://boostopt.com/docs"

# --- styling: on only for an interactive terminal that hasn't opted out ---
_COLOR = (sys.stdout.isatty() and "NO_COLOR" not in os.environ
          and os.environ.get("TERM") != "dumb")


def _sgr(code: str):
    return (lambda t: f"\033[{code}m{t}\033[0m") if _COLOR else (lambda t: t)


_B, _D, _ACCENT = _sgr("1"), _sgr("2"), _sgr("36")   # bold, dim, cyan
bold, dim, accent = _B, _D, _ACCENT                  # public aliases (used by the cheat-sheet)


def section(title: str) -> str:
    """Style an argparse group heading (bold + uppercase) — used by the formatter."""
    return _B(title.upper())


def _h(title: str) -> str:            # epilog section header, matches section() styling
    return _B(title.upper())


# --- product tagline (top of `boostopt --help`) ---
DESCRIPTION = (
    f"{_B('BOOSTOPT')}  ·  Verified Performance Optimizer for C++\n"
    f"{_D('Ship faster code with a guarantee: every change is proven correct AND faster — or rejected.')}"
)

# --- usage lines (rendered under a styled USAGE header; keep PLAIN) ---
USAGE_MAIN = "boostopt <command> [options]"
USAGE_OPTIMIZE = ("boostopt optimize <path> [options]\n"
                  "boostopt optimize -p <db> --all [options]")
USAGE_ANALYZE = ("boostopt analyze <path> [options]\n"
                 "boostopt analyze -p <db> --all [options]")
USAGE_SERVE = "boostopt serve [--stop]"
USAGE_DEMO = "boostopt demo [--keep]"
USAGE_INIT = "boostopt init [--model NAME] [--pull] [--install-ollama] [--global]"


# --- one-line command summaries (command list + per-command help + the docs) — keep PLAIN ---
OPTIMIZE_DESC = "Find, verify, and apply performance improvements."
ANALYZE_DESC = "Inspect optimization opportunities without changing anything."
REPORT_DESC = "Review what's been accepted, rejected, and the gains so far."
SERVE_DESC = "Run a warm background daemon so repeated runs are fast."
DEMO_DESC = "Prove it on a bundled sample — real compile, sanitizers, benchmark. No setup."
INIT_DESC = "Set up the .boostopt/ performance workspace (like git init) and prepare the local model."

# --- top-level footer: the generated COMMON OPTIONS cheat-sheet (inserted by
#     cli._parser(), built from the parser so it can't drift) followed by TAIL. ---
MAIN_EPILOG_TAIL = f"""\
{_h('Learn more')}
  {_ACCENT('boostopt <command> --help')}                   full, always-current help for a command
  {_ACCENT('Docs/BOOSTOPT_Flags.md')}                      generated flag reference (never drifts)
  Documentation                            {DOCS}
  Website                                  {WEBSITE}

{_D('The promise: BOOSTOPT keeps a change only when it is proven both correct and faster.')}"""

# --- per-command footers ---
OPTIMIZE_EPILOG = _D(f"Docs: {DOCS}/optimize")

ANALYZE_EPILOG = f"""\
{_D('analyze runs the FULL verification (compile + sanitizer + benchmark) but writes')}
{_D('nothing and records nothing — the safe "what would you do?" command. Use optimize')}
{_D('when you want to keep the changes.')}

{_D(f'Docs: {DOCS}/analyze')}"""

SERVE_EPILOG = f"""\
{_D('The daemon loads Python + libclang once and keeps them warm, so later optimize/')}
{_D('analyze calls skip startup. Calls use it automatically; pass --no-daemon to opt out.')}

  {_ACCENT('boostopt serve')}          {_D('start the daemon (Ctrl-C to stop)')}
  {_ACCENT('boostopt serve --stop')}   {_D('stop a running daemon')}

{_D(f'Docs: {DOCS}/serve')}
"""
