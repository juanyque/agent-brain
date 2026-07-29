#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="$(basename "$SKILL_DIR")"
APPLY=0

if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
  shift
fi
if [[ $# -ne 0 ]]; then
  printf 'ERROR: unexpected argument: %s\n' "$1" >&2
  exit 2
fi

link_runtime() {
  local runtime_home="$1"
  local skills_dir="$runtime_home/skills"
  local target="$skills_dir/$SKILL_NAME"
  if [[ -L "$target" && "$(readlink "$target")" == "$SKILL_DIR" ]]; then
    printf '  OK      %s\n' "$target"
    return
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    local backup
    backup="$target.backup-$(date +%Y%m%d-%H%M%S)"
    printf '  BACKUP  %s -> %s\n' "$target" "$backup"
    if [[ $APPLY -eq 1 ]]; then
      mv "$target" "$backup"
    fi
  fi
  printf '  LINK    %s -> %s\n' "$target" "$SKILL_DIR"
  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$skills_dir"
    ln -s "$SKILL_DIR" "$target"
  fi
}

printf 'skill_link: %s\n' "$SKILL_NAME"
found=0
for runtime_home in \
  "$HOME/.agents" \
  "$HOME/.claude" \
  "$HOME/.codex" \
  "$HOME/.config/opencode"
do
  if [[ -d "$runtime_home" ]]; then
    found=1
    link_runtime "$runtime_home"
  fi
done
if [[ $found -eq 0 ]]; then
  printf '  No runtime homes found; the skill remains runnable from %s\n' "$SKILL_DIR"
fi
