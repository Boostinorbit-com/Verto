"""VERTO CLI — the v0 surface (a thin client over the Engine API).

Mirrors VERTO_Surfaces §3. Commands: analyze / optimize / report / serve.
Exit codes: 0 verified change found · 1 nothing found · 2 error · 3 all rejected.

Split by concern: dispatch/entry (`main`), the argparse parser (`parser`), args→
Config (`config_build`), and output rendering (`render`). The public entry points
are re-exported here so callers use `...surfaces.cli.<name>`.
"""
from .main import handle_argv, main
from .parser import _parser

__all__ = ["main", "handle_argv", "_parser"]
