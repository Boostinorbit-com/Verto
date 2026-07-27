# VERTO GitHub Action — sample YAML

Two files, two audiences:

| File | Who uses it | What it is |
|---|---|---|
| **`verto.yml`** | **You** (a C++ team) | The **workflow** to copy into your repo at `.github/workflows/verto.yml`. Shows every input with its default. Start here. |
| **`action.yml`** | VERTO (the action author) | The **interface definition** — declares every `with:` input, every output, and how the action runs. This is the *schema* that `verto.yml`'s entries follow. |
| **`pr-comment.md`** | VERTO (the action author) | The **comment layout** — how a verified finding presents itself in the PR/MR review UI (summary comment, inline suggestion, prevent-mode). Renders on GitHub, so it also previews the design. |
| **`entrypoint.py` · `comment.py` · `gh.py`** | VERTO (the action author) | The **implementation.** `entrypoint.py` maps the `INPUT_*` env vars → the `verto` CLI and re-emits its exit code (so `fail-on` drives the check); `comment.py` renders the PR comment + suggestions; `gh.py` posts them. Bundled into the image by `Dockerfile`. |

**Quickest start:** copy `verto.yml` into your repo, make sure the build step generates a `compile_commands.json` (CMake: `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`), and you're done — VERTO will comment verified optimizations on each PR.

Full explanation of every concept: [`Docs/VERTO_CI_Action.md`](../../Docs/VERTO_CI_Action.md) (·[html](../../Docs/VERTO_CI_Action.html)).

> Note: `verto.yml` here is a **sample**, deliberately *not* placed in this repo's own `.github/workflows/` (that directory is for VERTO's own CI). Copy it into *your* project.

## Building & publishing the action image (maintainers)

The action runs as a **Docker action**, so its image must be pre-built and pushed to a registry that `action.yml`'s `runs.image` points at (`ghcr.io/verto/action:v1`).

```bash
# Build from the REPO ROOT (context must see pyproject.toml + verto/):
docker build -f examples/github-action/Dockerfile -t ghcr.io/verto/action:v1 .
```

Publishing is automated: [`.github/workflows/publish-action.yml`](../../.github/workflows/publish-action.yml) builds this Dockerfile and pushes `:vX.Y.Z`, `:vX`, and `:latest` to `ghcr.io/<owner>/action` on every version tag (`git tag v1.0.0 && git push --tags`). If you publish under a different owner/name, update `runs.image` in `action.yml` to match.

