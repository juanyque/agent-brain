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

if [[ ! -d "$CANONICAL/.git" ]]; then
  info "Cloning agent-brain into $CANONICAL ..."
  print_command mkdir -p "$CANONICAL"
  mkdir -p "$CANONICAL"
  print_command git clone --depth 1 "$REPO_URL" "$CANONICAL"
  git clone --depth 1 "$REPO_URL" "$CANONICAL"
  ok "OK: agent-brain cloned"
else
  info "agent-brain already present at $CANONICAL — updating (git pull --ff-only)..."
  print_command git -C "$CANONICAL" pull --ff-only
  if git -C "$CANONICAL" pull --ff-only; then
    ok "OK: agent-brain updated"
  else
    warning "WARNING: pull failed — continuing with local copy"
  fi
fi

print_command bash "$CANONICAL/model/SCRIPTS/bootstrap-zero.sh" "$@"
exec bash "$CANONICAL/model/SCRIPTS/bootstrap-zero.sh" "$@"
