#!/usr/bin/env bash
#
# skill_link.sh — symlink a skill into runtime skills dirs.
#
# For manual installation of non-brain skills (boyscout, etc.). The brain skill
# is installed automatically by bootstrap-zero.sh during home wiring.
#
# Usage:
#   skill_link.sh <skill_name_or_path> [runtime_home] [--apply]
#   skill_link.sh boyscout                       # agent-brain skill, all detected runtimes
#   skill_link.sh /path/to/skills/confold        # external skill, all detected runtimes
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
LOG_FILE="${SKILL_LINK_LOG_FILE:-$SCRIPT_DIR/skill_link.log}"
exec 3>"$LOG_FILE"

say() {
  printf '%s\n' "$*"
  printf '%s\n' "$*" >&3
}

say_error() {
  printf '%s\n' "$*" >&2
  printf '%s\n' "$*" >&3
}

sayf() {
  local format="$1"
  shift
  printf "$format" "$@"
  printf "$format" "$@" >&3
}

APPLY=0
SKILL_SPEC=""
RUNTIME_HOME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    -h|--help)
      help_text="$(grep '^#' "$0" | sed 's/^# \{0,1\}//')"
      say "$help_text"
      exit 0
      ;;
    *)
      if [[ -z "$SKILL_SPEC" ]]; then
        SKILL_SPEC="$1"; shift
      elif [[ -z "$RUNTIME_HOME" ]]; then
        RUNTIME_HOME="$1"; shift
      else
        say_error "ERROR: unexpected argument: $1"
        exit 2
      fi
      ;;
  esac
done

[[ -n "$SKILL_SPEC" ]] || { say_error "ERROR: skill name or source path required"; exit 2; }

if [[ "$SKILL_SPEC" == */* || -d "$SKILL_SPEC" ]]; then
  SOURCE="${SKILL_SPEC/#\~/$HOME}"
  if [[ ! -d "$SOURCE" ]]; then
    say_error "ERROR: skill source not found: $SOURCE"
    exit 2
  fi
  SOURCE="$(cd "$SOURCE" && pwd -P)"
  SKILL="$(basename "$SOURCE")"
else
  SKILL="$SKILL_SPEC"
  SOURCE="$REPO_ROOT/skills/$SKILL"
fi

if [[ ! -d "$SOURCE" ]]; then
  say_error "ERROR: skill source not found: $SOURCE"
  say_error "  (expected a directory at \$REPO_ROOT/skills/$SKILL)"
  exit 2
fi
if [[ ! "$SKILL" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  say_error "ERROR: invalid skill directory name: $SKILL"
  exit 2
fi
if [[ ! -f "$SOURCE/SKILL.md" ]]; then
  say_error "ERROR: skill source has no SKILL.md: $SOURCE"
  exit 2
fi

mode() { [[ $APPLY -eq 1 ]] && echo "apply" || echo "dry-run (pass --apply to execute)"; }

say "skill_link: $SKILL"
say "  source: $SOURCE"
say "  mode:   $(mode)"
say

link_into() {
  local rt_home="$1"
  local skills_dir="$rt_home/skills"
  local link="$skills_dir/$SKILL"

  if [[ -L "$link" && "$(readlink "$link")" == "$SOURCE" ]]; then
    sayf '  OK      %s\n' "$link"
    return
  fi

  if [[ -e "$link" || -L "$link" ]]; then
    local backup="$link.backup-$(date +%Y%m%d-%H%M%S)"
    sayf '  BACKUP  %s -> %s\n' "$link" "$(basename "$backup")"
    [[ $APPLY -eq 1 ]] && mv "$link" "$backup"
  fi

  sayf '  LINK    %s -> %s\n' "$link" "$SOURCE"
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
      say "-- runtime: $home --"
      link_into "$home"
    fi
  done
  [[ $found -eq 0 ]] && say_error "  (no runtime homes detected — pass a runtime_home explicitly)"
fi

say
[[ $APPLY -eq 0 ]] && say "(dry-run — re-run with --apply to execute)"
say "Done."
