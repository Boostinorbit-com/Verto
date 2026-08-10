# BOOSTOPT GitHub Action image (#18 step 4). Distinct from the top-level tool image:
# it also carries `git` (the action scopes to a PR's changed files via `git diff`)
# and bundles the action glue that isn't part of the Python package.
#
# BUILD FROM THE REPO ROOT (the context must see pyproject.toml + boostopt/):
#   docker build -f examples/github-action/Dockerfile -t ghcr.io/boostopt/action:v1 .
#
# Published to GHCR by .github/workflows/publish-action.yml; `runs.image` in
# action.yml must point at the same ref.
FROM python:3.12-slim

# clang++ carries the Rung-3 sanitizers; ccache speeds repeat runs; git powers --changed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends clang ccache git \
 && rm -rf /var/lib/apt/lists/*

# Install boostopt (the CLI the entrypoint drives). README/LICENSE/NOTICE are referenced
# by pyproject metadata, so they must be present for the build.
WORKDIR /boostopt
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY boostopt ./boostopt
RUN pip install --no-cache-dir .

# The action glue — entrypoint + the pure renderer + the GitHub poster. Not shipped
# in the pip package, so copy it in. entrypoint.py adds its own dir to sys.path, so
# `import comment` / `import gh` resolve at runtime.
COPY examples/github-action/entrypoint.py \
     examples/github-action/comment.py \
     examples/github-action/gh.py /action/

# GitHub runs the container with the checkout mounted and GITHUB_WORKSPACE/RUNNER_TEMP set;
# the entrypoint reads the INPUT_* env vars, runs `boostopt`, and re-emits its exit code.
ENTRYPOINT ["python", "/action/entrypoint.py"]
