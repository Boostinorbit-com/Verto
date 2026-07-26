#!/usr/bin/env bash
# Check how the VERTO GitHub Action behaves — locally, without GitHub.
#
# A Docker action is just: GitHub sets INPUT_* env vars, runs the entrypoint, then
# reads $GITHUB_OUTPUT and the exit code. This script reproduces that contract, so
# you see the whole pipeline (inputs -> verto -> outputs -> exit code -> the comment
# it WOULD post). The only thing it can't do locally is the actual PR post, which
# self-skips with no token — exactly as it would off a PR event.
#
# Usage:
#   examples/github-action/local-check.sh [COMPILE_DB] [FAIL_ON] [MODE]
# Defaults: examples/linked/compile_commands.json   any   suggest
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO"

DB="${1:-examples/linked/compile_commands.json}"
FAIL_ON="${2:-any}"
MODE="${3:-suggest}"

# Use an installed `verto`, else run the package in place.
if command -v verto >/dev/null 2>&1; then VERTO_BIN="verto";
else VERTO_BIN="python3 -m verto.surfaces.cli"; fi

TMP="$(mktemp -d)"; GH_OUT="$TMP/github_output.txt"; : > "$GH_OUT"
trap 'rm -rf "$TMP"' EXIT

echo "══ Simulating GitHub calling the Action ═════════════════════════════"
echo "   compile-commands = $DB"
echo "   fail-on = $FAIL_ON   mode = $MODE   model = rules"
echo "─────────────────────────────────────────────────────────────────────"

# `--changed` vs the git empty tree ⇒ every tracked TU counts as "changed",
# so the demo actually runs even with no real PR diff.
set +e
env \
  VERTO_BIN="$VERTO_BIN" \
  GITHUB_WORKSPACE="$REPO" \
  RUNNER_TEMP="$TMP" \
  GITHUB_OUTPUT="$GH_OUT" \
  "INPUT_COMPILE-COMMANDS=$DB" \
  "INPUT_BASE-REF=4b825dc642cb6eb9a060e54bf8d69288fbee4904" \
  "INPUT_MODEL=rules" \
  "INPUT_MODE=$MODE" \
  "INPUT_FAIL-ON=$FAIL_ON" \
  python3 "$HERE/entrypoint.py"
CODE=$?
set -e

echo "─────────────────────────────────────────────────────────────────────"
echo "   container exit code = $CODE   ($([ "$CODE" = 0 ] && echo 'check PASSES' || echo 'check goes RED'))"
echo
echo "══ Outputs handed back to GitHub (\$GITHUB_OUTPUT) ═══════════════════"
cat "$GH_OUT"
echo
echo "══ The PR comment it WOULD post (rendered from the report) ══════════"
REPORT="$(grep '^report-json=' "$GH_OUT" | cut -d= -f2-)"
BLOCK=$([ "$FAIL_ON" = any ] && echo True || echo False)
python3 - "$REPORT" "$REPO" "$BLOCK" <<'PY'
import importlib.util, json, os, sys
rep_path, root, blocking = sys.argv[1], sys.argv[2], sys.argv[3] == "True"
spec = importlib.util.spec_from_file_location("c", os.path.join(root, "examples/github-action/comment.py"))
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
rep = json.load(open(rep_path))
print(c.render_comment(rep, repo_root=root, blocking=blocking))
PY
