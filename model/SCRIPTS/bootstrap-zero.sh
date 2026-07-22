#!/usr/bin/env bash
#
# bootstrap-zero.sh — agent-brain setup orchestrator for a brain (D21).
#
# Thin orchestrator: resolves the brain path, git-snapshots for rollback,
# then DELEGATES to home_setup (structure) and runtime_manager (runtime).
# Does NOT create _COMMON, _STAGING, or symlinks itself.
#
# Usage:
#   bootstrap-zero.sh --home <brain_path> [--apply] [--update] [--runtime claude,opencode,agents,codex]
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
prompt_from_tty() {
  local prompt="$1"
  local target_var="$2"
  local answer
  if ! { exec 9</dev/tty; } 2>/dev/null; then
    echo "ERROR: interactive input requires a terminal; pass --brain <path>." >&2
    exit 2
  fi
  IFS= read -r -p "$prompt" answer <&9 || {
    exec 9<&-
    echo "ERROR: no interactive input received; pass --brain <path>." >&2
    exit 2
  }
  exec 9<&-
  printf -v "$target_var" '%s' "$answer"
}

# --- Step 0: resolve brain path ------------------------------------------------
if [[ -z "$BRAIN_PATH" ]]; then
  echo "== Brain resolution =="
  if [[ -f "$FIND_HOME" ]] && command -v python3 >/dev/null 2>&1; then
    echo "  Detected brain candidates:"
    python3 "$FIND_HOME" --candidates 2>/dev/null | python3 -c '
import json, sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
homes = d.get("homes", [])
high_confidence = [h for h in homes if h.get("notes_mode") == "obsidian" or h.get("has_agents_md") or h.get("has_common")]
for h in high_confidence or homes[:20]:
    print("    [{:<8}] {}".format(h.get("notes_mode", "unknown"), h.get("path", "")))' || true
  fi
  echo "  (enter a path: existing notes folder/vault, or a new empty dir to create)"
  prompt_from_tty "Brain path: " BRAIN_PATH
fi
if [[ ! -d "$BRAIN_PATH" ]]; then
  echo "  path does not exist: $BRAIN_PATH"
  prompt_from_tty "Create it? [y/N] " mk
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
  run git \
    -c user.email="agent-brain@local" \
    -c user.name="agent-brain" \
    -c commit.gpgSign=false \
    commit -q -m "agent-brain: pre-bootstrap snapshot" || true
elif [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo "  ERROR: brain is a git repo with a dirty working tree." >&2
  echo "  Commit or stash first — agent-brain never commits uncommitted user work." >&2
  exit 3
else
  TS="$(date +%Y%m%d-%H%M%S)"
  echo "  clean repo -> tag pre-bootstrap-$TS"
  run git \
    -c tag.gpgSign=false \
    tag --annotate --no-sign \
    --message "agent-brain: pre-bootstrap snapshot" \
    "pre-bootstrap-$TS"
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
HOME_SETUP_ARGS=(--brain "$BRAIN_PATH" --common "$MODEL_DIR" --switch-model)
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
  echo "  (dry-run — apply, then health-check verifies: _COMMON target, model/SCRIPTS,"
  echo "   the bundled brain skill, and detected runtime wiring)"
else
  fail=0
  check() { local label="$1" path="$2"; if [[ -e "$path" || -L "$path" ]]; then echo "  OK   $label"; else echo "  FAIL $label ($path)"; fail=1; fi; }
  if [[ -L "$BRAIN_PATH/_COMMON" ]] \
    && [[ "$(cd "$BRAIN_PATH/_COMMON" 2>/dev/null && pwd -P)" == "$(cd "$MODEL_DIR" && pwd -P)" ]]; then
    echo "  OK   _COMMON resolves to agent-brain model"
  else
    echo "  FAIL _COMMON does not resolve to $MODEL_DIR"
    fail=1
  fi
  check "model/SCRIPTS present" "$MODEL_DIR/SCRIPTS"
  check "skills/brain present" "$REPO_ROOT/skills/brain"
  check "runtime health checker present" "$SCRIPT_DIR/runtime_health.py"

  HEALTH_ARGS=(--brain "$BRAIN_PATH")
  if [[ -n "$RUNTIME_FILTER" ]]; then
    IFS=',' read -ra HEALTH_RUNTIMES <<< "$RUNTIME_FILTER"
    for rt in "${HEALTH_RUNTIMES[@]}"; do HEALTH_ARGS+=(--runtime "$rt"); done
  fi
  if [[ -f "$SCRIPT_DIR/runtime_health.py" ]]; then
    if ! python3 "$SCRIPT_DIR/runtime_health.py" "${HEALTH_ARGS[@]}"; then
      fail=1
    fi
  fi
  echo
  if [[ $fail -eq 0 ]]; then
    echo "✅ health-check passed"
  else
    echo "⚠️  health-check has failures (see above)" >&2
    exit 6
  fi
fi
[[ $APPLY -eq 0 ]] && echo "(dry-run — re-run with --apply to execute)"
exit 0
