#!/usr/bin/env bash
#
# bootstrap-zero.sh — agent-brain setup orchestrator for a brain (D21).
#
# Thin orchestrator: resolves the brain path, git-snapshots for rollback,
# then DELEGATES to home_setup (structure) and runtime_manager (runtime).
# Does NOT create _COMMON, _STAGING, or symlinks itself.
#
# Usage:
#   bootstrap-zero.sh --home <brain_path> [--apply] [--update] [--runtime claude,opencode]
#     --home      the brain path (if omitted, prompts interactively)
#     --apply     execute (default: dry-run plan only)
#     --update    git-pull the agent-brain repo before wiring
#     --runtime   restrict to a comma-separated subset of runtimes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODEL_DIR="$REPO_ROOT/model"
FIND_HOME="$REPO_ROOT/skills/brain/scripts/find_home.py"

BRAIN_PATH=""
APPLY=0
UPDATE=0
RUNTIME_FILTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --home) BRAIN_PATH="${2:-}"; shift 2 ;;  # --brain alias
    --brain) BRAIN_PATH="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --update) UPDATE=1; shift ;;
    --runtime) RUNTIME_FILTER="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

run() { if [[ $APPLY -eq 1 ]]; then "$@"; else printf '  (dry-run) %s\n' "$*"; fi; }
mode() { [[ $APPLY -eq 1 ]] && echo "apply" || echo "dry-run (pass --apply to execute)"; }

# --- Step 0: resolve brain path ------------------------------------------------
if [[ -z "$BRAIN_PATH" ]]; then
  echo "== Brain resolution =="
  if [[ -f "$FIND_HOME" ]] && command -v python3 >/dev/null 2>&1; then
    echo "  Detected brain candidates:"
    python3 "$FIND_HOME" "$HOME" 2>/dev/null | python3 -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
for h in d.get("homes", []):
    print(f"    [{h[\"notes_mode\"]:8}] {h[\"path\"]}")' || true
  fi
  echo "  (enter a path: existing notes folder/vault, or a new empty dir to create)"
  read -r -p "Brain path: " BRAIN_PATH
fi
if [[ ! -d "$BRAIN_PATH" ]]; then
  echo "  path does not exist: $BRAIN_PATH"
  read -r -p "Create it? [y/N] " mk
  [[ "$mk" =~ ^[Yy]$ ]] || { echo "ERROR: aborting"; exit 2; }
  run mkdir -p "$BRAIN_PATH"
fi
BRAIN_PATH="$(cd "$BRAIN_PATH" && pwd)"
echo "BRAIN = $BRAIN_PATH  (mode: $(mode))"
echo

# --- Step 1: git-snapshot (rollback anchor) ------------------------------------
echo "== git-snapshot =="
cd "$BRAIN_PATH"
if [[ ! -d ".git" ]]; then
  echo "  no git repo -> init + commit everything (rollback anchor)"
  run git init -q
  run git add -A
  run git -c user.email="agent-brain@local" -c user.name="agent-brain" commit -q -m "agent-brain: pre-bootstrap snapshot" || true
elif [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo "  ERROR: brain is a git repo with a dirty working tree." >&2
  echo "  Commit or stash first — agent-brain never commits uncommitted user work." >&2
  exit 3
else
  TS="$(date +%Y%m%d-%H%M%S)"
  echo "  clean repo -> tag pre-bootstrap-$TS"
  run git tag "pre-bootstrap-$TS"
fi
echo

# --- Step 2: ensure agent-brain repo -------------------------------------------
echo "== agent-brain repo =="
if [[ ! -d "$REPO_ROOT/.git" ]]; then
  echo "  ERROR: cannot locate agent-brain repo at $REPO_ROOT" >&2
  exit 4
fi
if [[ $UPDATE -eq 1 ]]; then echo "  updating (git pull --ff-only)..."; run git -C "$REPO_ROOT" pull --ff-only; fi
echo "  repo: $REPO_ROOT"
echo

# --- Step 3: home_setup (structure: _COMMON, wrappers, templates, staging) -----
echo "== home_setup (structure) =="
HOME_SETUP_ARGS=(--brain "$BRAIN_PATH" --common "$MODEL_DIR")
[[ $APPLY -eq 1 ]] && HOME_SETUP_ARGS+=(--apply)
python3 "$SCRIPT_DIR/home_setup.py" "${HOME_SETUP_ARGS[@]}"
echo

# --- Step 4: runtime_manager (runtime config + skill link) --------------------
echo "== runtime_manager (runtime) =="
RT_ARGS=(--brain "$BRAIN_PATH" --common "$MODEL_DIR")
[[ $APPLY -eq 1 ]] && RT_ARGS+=(--apply)
if [[ -n "$RUNTIME_FILTER" ]]; then
  IFS=',' read -ra RTS <<< "$RUNTIME_FILTER"
  for rt in "${RTS[@]}"; do RT_ARGS+=(--runtime "$rt"); done
fi
python3 "$SCRIPT_DIR/runtime_manager.py" "${RT_ARGS[@]}"
echo

# --- Step 5: health-check ------------------------------------------------------
echo "== health-check =="
if [[ $APPLY -eq 0 ]]; then
  echo "  (dry-run — apply, then health-check verifies: _COMMON resolves, model/SCRIPTS,"
  echo "   skills/brain, and per-runtime symlinks)"
else
  fail=0
  check() { local label="$1" path="$2"; if [[ -e "$path" || -L "$path" ]]; then echo "  OK   $label"; else echo "  FAIL $label ($path)"; fail=1; fi; }
  check "_COMMON resolves" "$BRAIN_PATH/_COMMON"
  check "model/SCRIPTS present" "$MODEL_DIR/SCRIPTS"
  check "skills/brain present" "$REPO_ROOT/skills/brain"
  echo
  [[ $fail -eq 0 ]] && echo "✅ health-check passed" || echo "⚠️  health-check has failures (see above)"
fi
[[ $APPLY -eq 0 ]] && echo "(dry-run — re-run with --apply to execute)"
