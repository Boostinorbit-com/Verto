"""Bundled Ollama Modelfiles — BOOSTOPT's local models, shipped inside the wheel.

These live *in the package* (not a repo-root `models/`) for one reason: `pip install boostopt`
must carry them, and setuptools can only ship data that sits under a package. `provision.py`
reads them from here via `importlib.resources`, so it works the same from a source checkout,
an installed wheel, or a zipimport.

A Modelfile here is a re-tag recipe, not weights: `FROM <base>` plus BOOSTOPT's system prompt
and sampling. `ollama create` applies it in seconds against a base Ollama already has.
"""
