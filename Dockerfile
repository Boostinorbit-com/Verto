# Zero-setup VERTO: bundles the one system dependency (clang++ with ASan/UBSan/TSan) so
# `docker run verto optimize foo.cpp` works on any machine with Docker.
#
#   docker build -t verto .
#   docker run --rm -v "$PWD:/src" -w /src verto optimize examples/packet_stats.cpp --offline
#
# Notes: bwrap sandboxing and a local Ollama aren't in the image, so isolation degrades to
# rlimits and `--offline` (deterministic rules) is the natural default here; point `--llm-url`
# at a reachable host for `--model frontier`.
FROM python:3.12-slim

# clang++ carries the Rung-3 sanitizers; ccache speeds up repeat runs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends clang ccache \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /verto
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY verto ./verto
COPY examples ./examples
RUN pip install --no-cache-dir .

# Work against the user's mounted source by default.
WORKDIR /src
ENTRYPOINT ["verto"]
CMD ["--help"]
