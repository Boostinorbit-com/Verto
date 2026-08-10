"""Ollama Modelfiles for BOOSTOPT's local models — embedded as source, not shipped as data.

They live here as Python strings rather than `.Modelfile` files on disk for one reason: the
distribution is compiled. A Nuitka `--module` build collapses the whole package into a single
`.so`, and `importlib.resources` then cannot see package data — verified: a compiled build
reported `has_bundled_modelfile() == False`, silently losing `boostopt init`'s ability to build
the model. Text that lives *in a module* is compiled into the binary along with everything else.

It also removes a packaging failure mode: no `[tool.setuptools.package-data]` glob to forget,
and nothing that can be present in a source checkout but missing from the wheel.

A Modelfile here is a re-tag recipe, not weights: `FROM <base>` plus BOOSTOPT's system prompt
and sampling. `ollama create` applies it in seconds against a base Ollama already has.
"""

_SYSTEM = (
    "You are BOOSTOPT's expert C++ performance engineer. Rewrite the given function to run"
    " MEASURABLY FASTER while keeping EXACTLY the same behavior and the same signature. Apply"
    " real optimizations: pre-size or reserve() containers to avoid repeated reallocation, hoist"
    " loop-invariant work, avoid unnecessary copies, and pick a cheaper algorithm where possible."
    " Do NOT just reformat or rename. Reply with ONLY the rewritten function inside a single"
    " ```cpp code block — no prose, no notes."
)

# tag family (the part before ':') -> Modelfile text.
MODELFILES: dict[str, str] = {
    "boostopt2.5-coder": f'''# boostopt2.5-coder — BOOSTOPT's C++ performance-optimizer model.
#
# PROVENANCE (Apache-2.0 attribution — do not remove):
#   Base model: qwen2.5-coder:7b  (Alibaba Cloud, "Qwen2.5-Coder", Apache-2.0).
#   This is a RE-TAGGED + CONFIGURED build of that model — BOOSTOPT's optimize
#   system prompt and sampling defaults baked in. It is NOT trained from scratch.
#   `ollama show --modelfile boostopt2.5-coder:7b` resolves FROM to a local blob
#   path and does NOT name the base, so the attribution lives here and in NOTICE.
#
# Built automatically by `boostopt init` (see boostopt/runtime/provision.py) — it
# pulls the base once, then re-tags.

FROM qwen2.5-coder:7b

SYSTEM """{_SYSTEM}"""

PARAMETER temperature 0.2
''',
}
