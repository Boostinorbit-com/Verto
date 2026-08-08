#!/bin/sh
# BOOSTOPT installer — https://boostopt.com/install.sh
#
#   curl -fsSL https://boostopt.com/install.sh | sh
#
# WHY THIS EXISTS. `pip install boostopt` is fully supported and is the right path for CI,
# containers, and anyone bringing their own model. But pip cannot deliver Ollama: a wheel runs
# no install-time code, and Ollama is a native binary plus a system service, not a Python
# package. So the "one command, working system" experience has to live in a script. This is it.
#
# WHAT IT DOES — in order, each step skipped if already satisfied:
#   1. check python3 >= 3.11 and clang++ (the one hard system dependency)
#   2. install boostopt into an isolated venv, linked onto PATH
#   3. install Ollama, if missing and you agree (needs sudo)
#   4. pull qwen2.5-coder:7b and build boostopt2.5-coder:7b from it
#
# FLAGS:
#   --yes         don't prompt (assume yes) — for automation
#   --no-ollama   install the tool only; skip the model entirely (pairs with `--offline`)
#   --prefix DIR  where to put the venv (default ~/.local/share/boostopt)
#
# REMOVING IT ALL:  boostopt-uninstall --yes --remove-ollama
set -eu

PREFIX="${BOOSTOPT_PREFIX:-$HOME/.local/share/boostopt}"
BINDIR="${BOOSTOPT_BINDIR:-$HOME/.local/bin}"
ASSUME_YES=0
WANT_OLLAMA=1

while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-ollama) WANT_OLLAMA=0 ;;
    --prefix) PREFIX="$2"; shift ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '%s\n' "$*"; }
step() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

# Prompts read from the TERMINAL, not stdin: under `curl … | sh` stdin IS the script, so a
# plain `read` would silently consume the script's own remaining bytes.
ask() {
  [ "$ASSUME_YES" = 1 ] && return 0
  [ -r /dev/tty ] || return 1          # non-interactive (CI, a pipe) → never assume yes
  printf '  %s [y/N] ' "$1"
  read -r reply < /dev/tty || return 1
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# --- 1. prerequisites -------------------------------------------------------
step "Checking prerequisites"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 &&
     "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || die "need Python 3.11+ — install it, then re-run"
say "  ✓ $("$PY" -V)"

if command -v clang++ >/dev/null 2>&1; then
  say "  ✓ $(clang++ --version | head -1)"
else
  # Not fatal here: the install still succeeds, but nothing can be VERIFIED without it, so be
  # loud rather than let the first `optimize` fail mysteriously.
  warn "clang++ not found — BOOSTOPT needs it (with sanitizers) to verify anything"
  warn "  Debian/Ubuntu:  sudo apt install clang"
  warn "  macOS:          xcode-select --install"
fi

# --- 2. the tool ------------------------------------------------------------
step "Installing boostopt"
"$PY" -m venv "$PREFIX/venv" 2>/dev/null || die "could not create a venv at $PREFIX/venv"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade boostopt \
  || die "pip install boostopt failed"

mkdir -p "$BINDIR"
for cmd in boostopt boostopt-uninstall; do
  ln -sf "$PREFIX/venv/bin/$cmd" "$BINDIR/$cmd"
done
say "  ✓ $("$PREFIX/venv/bin/boostopt" --version 2>/dev/null || echo boostopt) → $BINDIR/boostopt"

case ":$PATH:" in
  *":$BINDIR:"*) ;;
  *) warn "$BINDIR is not on your PATH — add it:"
     warn "  echo 'export PATH=\"\$PATH:$BINDIR\"' >> ~/.profile" ;;
esac

# --- 3 + 4. Ollama and the model -------------------------------------------
if [ "$WANT_OLLAMA" = 0 ]; then
  step "Skipping the local model (--no-ollama)"
  say "  use the deterministic proposer:  boostopt optimize <file> --offline"
else
  step "Setting up the local model"
  # `init` owns this: it detects Ollama, offers to install it (with its own confirmation),
  # pulls the base once, and re-tags it as boostopt2.5-coder:7b. Every check is idempotent,
  # so re-running this installer is safe.
  if [ "$ASSUME_YES" = 1 ] || ask "Install Ollama if missing, and download ~4GB for the model?"; then
    "$BINDIR/boostopt" init --pull --install-ollama || warn "model setup incomplete — re-run: boostopt init --pull"
  else
    "$BINDIR/boostopt" init || true
    say "  skipped the download — run \`boostopt init --pull\` when you want the local model"
  fi
fi

step "Done"
say "  try:     boostopt optimize <file.cpp> --offline"
say "  remove:  boostopt-uninstall --yes --remove-ollama"
say "  docs:    https://docs.boostopt.com"
