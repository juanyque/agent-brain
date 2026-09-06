#!/usr/bin/env bash
#
# bootstrap-zero.sh (root entry point)
#
# curl -fsSL https://raw.githubusercontent.com/juanyque/agent-brain/main/bootstrap-zero.sh | bash
#
# Ensures the agent-brain repo is cloned to a canonical location, then dispatches to the
# real orchestrator at model/SCRIPTS/bootstrap-zero.sh. All flags after '--' (or any flags)
# are forwarded to the orchestrator.

set -euo pipefail

CANONICAL="${AGENT_BRAIN_HOME:-$HOME/.local/share/agent-brain}"
REPO_URL="https://github.com/juanyque/agent-brain.git"

COLOR_STDOUT=0
COLOR_STDERR=0
if [[ -z "${NO_COLOR+x}" ]]; then
  [[ -t 1 ]] && COLOR_STDOUT=1
  [[ -t 2 ]] && COLOR_STDERR=1
fi

RESET=$'\033[0m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BLUE=$'\033[34m'
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
info() { color_stdout "$BLUE" "$*"; }
ok() { color_stdout "$GREEN" "$*"; }
warning() { color_stderr "$ORANGE" "$*"; }
print_command() {
  local rendered=""
  local quoted
  local arg
  for arg in "$@"; do
    printf -v quoted '%q' "$arg"
    rendered="${rendered}${rendered:+ }${quoted}"
  done
  color_stdout "$YELLOW" "COMMAND: $rendered"
}

ensure_repo() {
  if [[ ! -d "$CANONICAL/.git" ]]; then
    info "Cloning agent-brain into $CANONICAL ..."
    print_command mkdir -p "$CANONICAL"
    mkdir -p "$CANONICAL"
    print_command git clone --depth 1 "$REPO_URL" "$CANONICAL"
    git clone --depth 1 "$REPO_URL" "$CANONICAL"
    ok "OK: agent-brain cloned"
    return 0
  fi
  info "agent-brain already present at $CANONICAL — updating ..."
  if [[ -f "$CANONICAL/.git/shallow" ]]; then
    info "Shallow clone detected — fetching full history (one-time) ..."
    print_command git -C "$CANONICAL" fetch --unshallow
    if ! git -C "$CANONICAL" fetch --unshallow; then
      warning "WARNING: unshallow fetch failed — trying update anyway"
    fi
  fi
  print_command git -C "$CANONICAL" pull --ff-only
  if git -C "$CANONICAL" pull --ff-only; then
    ok "OK: agent-brain updated"
    return 0
  fi
  warning "WARNING: update failed — the local agent-brain copy may be stale or diverged."
  warning "Recover with one of (brains are never touched by these):"
  warning "  git -C \"$CANONICAL\" stash push -u && git -C \"$CANONICAL\" pull --ff-only  # local changes in the way"
  warning "  git -C \"$CANONICAL\" fetch origin && git -C \"$CANONICAL\" reset --hard origin/main  # discard local divergence"
  warning "  mv \"$CANONICAL\" \"${CANONICAL}.old-$(date +%Y%m%d%H%M%S)\" && re-run bootstrap-zero.sh  # start fresh, keeps the old copy"
  return 0
}

_bootstrap_source="${BASH_SOURCE[0]:-}"
if [[ -z "$_bootstrap_source" || "$_bootstrap_source" == "$0" ]]; then
  ensure_repo
  print_command bash "$CANONICAL/model/SCRIPTS/bootstrap-zero.sh" "$@"
  exec bash "$CANONICAL/model/SCRIPTS/bootstrap-zero.sh" "$@"
fi
