#!/usr/bin/env bash
#
# bootstrap-zero.sh — agent-brain setup orchestrator for a brain (D21).
#
# Thin orchestrator: resolves the brain path, git-snapshots for rollback,
# then DELEGATES to home_setup (structure) and runtime_manager (runtime).
# Does NOT create _COMMON, _STAGING, or symlinks itself.
#
# Usage:
#   bootstrap-zero.sh --home <brain_path> [--apply] [--update] [--runtime claude,opencode,agents,codex,antigravity] [--symlink-policy copy|keep]
#     --home      the brain path (if omitted, prompts interactively)
#     --apply     execute (default: dry-run plan only)
#     --update    git-pull the agent-brain repo before wiring
#     --runtime   restrict to a comma-separated subset of runtimes
#     --symlink-policy
#                 copy top-level link content into the brain (recommended), or
#                 keep non-canonical links at the brain root

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODEL_DIR="$REPO_ROOT/model"
FIND_HOME="$REPO_ROOT/skills/brain/scripts/find_home.py"
PUBLIC_BOOTSTRAP_URL="https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh"

BRAIN_PATH=""
APPLY=0
UPDATE=0
RUNTIME_FILTER=""
SYMLINK_POLICY=""

COLOR_STDOUT=0
COLOR_STDERR=0
if [[ -z "${NO_COLOR+x}" ]]; then
  [[ -t 1 ]] && COLOR_STDOUT=1
  [[ -t 2 ]] && COLOR_STDERR=1
fi

RESET=$'\033[0m'
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BLUE=$'\033[34m'
CYAN=$'\033[36m'
ORANGE=$'\033[38;5;208m'

color_stdout() {
  local color="$1"
  shift
  if [[ $COLOR_STDOUT -eq 1 ]]; then
    printf '%s%s%s\n' "$color" "$*" "$RESET"
  else
    printf '%s\n' "$*"
  fi
}
color_stderr() {
  local color="$1"
  shift
  if [[ $COLOR_STDERR -eq 1 ]]; then
    printf '%s%s%s\n' "$color" "$*" "$RESET" >&2
  else
    printf '%s\n' "$*" >&2
  fi
}
section() { color_stdout "$BLUE" "$*"; }
ok() { color_stdout "$GREEN" "$*"; }
error() { color_stderr "$RED" "$*"; }
warning() { color_stderr "$ORANGE" "$*"; }
print_command_with_label() {
  local label="$1"
  shift
  local rendered=""
  local quoted
  local arg
  for arg in "$@"; do
    printf -v quoted '%q' "$arg"
    rendered="${rendered}${rendered:+ }${quoted}"
  done
  color_stdout "$YELLOW" "$label $rendered"
}
print_command() { print_command_with_label "COMMAND:" "$@"; }
print_user_command() { color_stdout "$CYAN" "$*"; }
colorize_output() {
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      *ERROR:*|*FAIL*) color_stdout "$RED" "$line" ;;
      *WARNING:*|*WARN*) color_stdout "$ORANGE" "$line" ;;
      *OK*|*SUCCESS*) color_stdout "$GREEN" "$line" ;;
      *command:*) color_stdout "$YELLOW" "$line" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done
}
run_command() {
  print_command "$@"
  if [[ $COLOR_STDOUT -eq 1 ]]; then
    "$@" 2>&1 | colorize_output
  else
    "$@"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --home) BRAIN_PATH="${2:-}"; shift 2 ;;  # --brain alias
    --brain) BRAIN_PATH="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --update) UPDATE=1; shift ;;
    --runtime) RUNTIME_FILTER="${2:-}"; shift 2 ;;
    --symlink-policy) SYMLINK_POLICY="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) error "ERROR: unknown arg: $1"; exit 2 ;;
  esac
done

run() {
  if [[ $APPLY -eq 1 ]]; then
    print_command "$@"
    "$@"
  else
    print_command_with_label "COMMAND (dry-run):" "$@"
  fi
}
mode() { [[ $APPLY -eq 1 ]] && echo "apply" || echo "dry-run (pass --apply to execute)"; }
print_public_apply_command() {
  local apply_args=(--brain "$BRAIN_PATH")
  [[ -n "$RUNTIME_FILTER" ]] && apply_args+=(--runtime "$RUNTIME_FILTER")
  [[ -n "$SYMLINK_POLICY" ]] && apply_args+=(--symlink-policy "$SYMLINK_POLICY")
  apply_args+=(--apply)

  section "Next command:"
  print_user_command "curl -fsSL $PUBLIC_BOOTSTRAP_URL \\"
  local command_line="  | bash -s --"
  local quoted
  local arg
  for arg in "${apply_args[@]}"; do
    printf -v quoted '%q' "$arg"
    command_line="$command_line $quoted"
  done
  print_user_command "$command_line"
}
prompt_from_tty() {
  local prompt="$1"
  local target_var="$2"
  local answer
  if [[ ! -t 0 ]]; then
    error "ERROR: interactive input requires a terminal; pass --brain <path>."
    exit 2
  fi
  if ! { exec 9</dev/tty; } 2>/dev/null; then
    error "ERROR: interactive input requires a terminal; pass --brain <path>."
    exit 2
  fi
  IFS= read -r -p "$prompt" answer <&9 || {
    exec 9<&-
    error "ERROR: no interactive input received; pass --brain <path>."
    exit 2
  }
  exec 9<&-
  printf -v "$target_var" '%s' "$answer"
}

# --- Step 0: resolve brain path ------------------------------------------------
if [[ -z "$BRAIN_PATH" ]]; then
  section "== Brain resolution =="
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
  [[ "$mk" =~ ^[Yy]$ ]] || { error "ERROR: aborting"; exit 2; }
  run mkdir -p "$BRAIN_PATH"
fi
BRAIN_PATH="$(cd "$BRAIN_PATH" && pwd)"
echo "BRAIN = $BRAIN_PATH  (mode: $(mode))"
echo

# --- Step 1: git-snapshot (rollback anchor) ------------------------------------
section "== git-snapshot =="
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
  error "  ERROR: brain is a git repo with a dirty working tree."
  error "  Commit or stash first — agent-brain never commits uncommitted user work."
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
section "== agent-brain repo =="
if [[ ! -d "$REPO_ROOT/.git" ]]; then
  error "  ERROR: cannot locate agent-brain repo at $REPO_ROOT"
  exit 4
fi
if [[ $UPDATE -eq 1 ]]; then echo "  updating (git pull --ff-only)..."; run git -C "$REPO_ROOT" pull --ff-only; fi
echo "  repo: $REPO_ROOT"
echo

if [[ -z "${AGENT_BRAIN_LOG_DIR:-}" ]]; then
  AGENT_BRAIN_LOG_DIR="${HOME:-/tmp}/.agent-brain/bootstrap-logs"
  export AGENT_BRAIN_LOG_DIR
fi
echo "  logs: $AGENT_BRAIN_LOG_DIR"
echo

# --- Step 3: home_setup (structure: _COMMON, wrappers, templates, staging) -----
section "== home_setup (structure) =="
HOME_SETUP_ARGS=(--brain "$BRAIN_PATH" --common "$MODEL_DIR" --switch-model)
[[ $APPLY -eq 1 ]] && HOME_SETUP_ARGS+=(--apply)
if [[ -n "$SYMLINK_POLICY" ]]; then
  HOME_SETUP_ARGS+=(--symlink-policy "$SYMLINK_POLICY")
fi
run_command python3 "$SCRIPT_DIR/home_setup.py" "${HOME_SETUP_ARGS[@]}"
echo

# --- Step 4: runtime_manager (runtime config + skill link) --------------------
section "== runtime_manager (runtime) =="
RT_ARGS=(--brain "$BRAIN_PATH" --common "$MODEL_DIR")
[[ $APPLY -eq 1 ]] && RT_ARGS+=(--apply)
if [[ -n "$RUNTIME_FILTER" ]]; then
  IFS=',' read -ra RTS <<< "$RUNTIME_FILTER"
  for rt in "${RTS[@]}"; do RT_ARGS+=(--runtime "$rt"); done
fi
run_command python3 "$SCRIPT_DIR/runtime_manager.py" "${RT_ARGS[@]}"
echo

# --- Step 5: health-check ------------------------------------------------------
section "== health-check =="
if [[ $APPLY -eq 0 ]]; then
  echo "  (dry-run — apply, then health-check verifies: _COMMON target, model/SCRIPTS,"
  echo "   the bundled brain skill, and detected runtime wiring)"
else
  fail=0
  check() { local label="$1" path="$2"; if [[ -e "$path" || -L "$path" ]]; then ok "  OK   $label"; else color_stdout "$RED" "  FAIL $label ($path)"; fail=1; fi; }
  if [[ -L "$BRAIN_PATH/_COMMON" ]] \
    && [[ "$(cd "$BRAIN_PATH/_COMMON" 2>/dev/null && pwd -P)" == "$(cd "$MODEL_DIR" && pwd -P)" ]]; then
    ok "  OK   _COMMON resolves to agent-brain model"
  else
    color_stdout "$RED" "  FAIL _COMMON does not resolve to $MODEL_DIR"
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
    if ! run_command python3 "$SCRIPT_DIR/runtime_health.py" "${HEALTH_ARGS[@]}"; then
      fail=1
    fi
  fi
  echo
  if [[ $fail -eq 0 ]]; then
    ok "OK: health-check passed"
  else
    warning "WARNING: health-check has failures (see above)"
    exit 6
  fi
fi
if [[ $APPLY -eq 0 ]]; then
  echo "(dry-run — re-run with --apply to execute)"
  echo
  print_public_apply_command
fi
exit 0
