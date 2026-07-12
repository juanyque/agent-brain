#!/usr/bin/env bash
#
# skill_link.sh — symlink a skill from the agent-brain repo into runtime skills dirs.
#
# For manual installation of non-brain skills (boyscout, etc.). The brain skill
# is installed automatically by bootstrap-zero.sh during home wiring.
#
# Usage:
#   skill_link.sh <skill_name> [runtime_home] [--apply]
#   skill_link.sh boyscout                       # link into all detected runtimes
#   skill_link.sh boyscout ~/.agents             # link into one runtime only
#   skill_link.sh boyscout ~/.agents --apply     # execute (default: dry-run)
#
# Idempotent: skips if the target is already the correct symlink.
# Safe: backs up an existing target to .backup-<ts> if it is not our symlink.
#
# Dry-run by default; pass --apply to execute.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

APPLY=0
SKILL=""
RUNTIME_HOME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)
      if [[ -z "$SKILL" ]]; then
        SKILL="$1"; shift
      elif [[ -z "$RUNTIME_HOME" ]]; then
        RUNTIME_HOME="$1"; shift
      else
        echo "ERROR: unexpected argument: $1" >&2
        exit 2
      fi
      ;;
  esac
done

[[ -n "$SKILL" ]] || { echo "ERROR: skill name required (e.g. boyscout)" >&2; exit 2; }

SOURCE="$REPO_ROOT/skills/$SKILL"
if [[ ! -d "$SOURCE" ]]; then
  echo "ERROR: skill source not found: $SOURCE" >&2
  echo "  (expected a directory at \$REPO_ROOT/skills/$SKILL)" >&2
  exit 2
fi

mode() { [[ $APPLY -eq 1 ]] && echo "apply" || echo "dry-run (pass --apply to execute)"; }

echo "skill_link: $SKILL"
echo "  source: $SOURCE"
echo "  mode:   $(mode)"
echo

link_into() {
  local rt_home="$1"
  local skills_dir="$rt_home/skills"
  local link="$skills_dir/$SKILL"

  if [[ -L "$link" && "$(readlink "$link")" == "$SOURCE" ]]; then
    printf '  OK      %s\n' "$link"
    return
  fi

  if [[ -e "$link" || -L "$link" ]]; then
    local backup="$link.backup-$(date +%Y%m%d-%H%M%S)"
    printf '  BACKUP  %s -> %s\n' "$link" "$(basename "$backup")"
    [[ $APPLY -eq 1 ]] && mv "$link" "$backup"
  fi

  printf '  LINK    %s -> %s\n' "$link" "$SOURCE"
  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$skills_dir"
    ln -s "$SOURCE" "$link"
  fi
}

if [[ -n "$RUNTIME_HOME" ]]; then
  RUNTIME_HOME="${RUNTIME_HOME/#\~/$HOME}"
  link_into "$RUNTIME_HOME"
else
  found=0
  for home in "$HOME/.agents" "$HOME/.claude" "$HOME/.codex" "$HOME/.config/opencode"; do
    if [[ -d "$home" ]]; then
      found=1
      echo "-- runtime: $home --"
      link_into "$home"
    fi
  done
  [[ $found -eq 0 ]] && echo "  (no runtime homes detected — pass a runtime_home explicitly)" >&2
fi

echo
[[ $APPLY -eq 0 ]] && echo "(dry-run — re-run with --apply to execute)"
echo "Done."
