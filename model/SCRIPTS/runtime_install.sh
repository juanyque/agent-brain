#!/usr/bin/env bash
#
# runtime_install.sh — symlink a runtime's config from HOME/_AGENTS/<runtime>/ into the
# runtime's local config dir (~/.claude, ~/.config/opencode, ...).
#
# Generalization of the per-runtime install.sh scripts (CLAUDE/install.sh, OPENCODE/install.sh).
# Direction: HOME is source of truth; local runtime dir gets symlinks pointing INTO the home.
#
# Idempotent. Dry-run by default; pass --apply to execute.
# Safe: if a local target exists and is not the correct symlink, it is backed up
# (.backup-<ts>) rather than clobbered. This also covers the atomic-write case where a
# runtime replaced our symlink with a real file.
#
# Usage:
#   runtime_install.sh <runtime> --brain <brain_path> [--apply]
#   runtime: claude | opencode   (codex: TBD)

set -euo pipefail

USAGE="Usage: $0 <runtime> --brain <brain_path> [--apply]"

RUNTIME=""
BRAIN_PATH=""
APPLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --brain) BRAIN_PATH="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) echo "$USAGE"; exit 0 ;;
    *) if [[ -z "$RUNTIME" ]]; then RUNTIME="$1"; shift; else echo "ERROR: unknown arg: $1" >&2; echo "$USAGE" >&2; exit 2; fi ;;
  esac
done

[[ -n "$RUNTIME" ]] || { echo "ERROR: runtime required (claude|opencode)" >&2; echo "$USAGE" >&2; exit 2; }
[[ -n "$BRAIN_PATH" ]] || { echo "ERROR: --brain required" >&2; echo "$USAGE" >&2; exit 2; }

BRAIN_PATH="${BRAIN_PATH%/}"

# --- Per-runtime config ------------------------------------------------------
declare -A TARGET_DIR
declare -a CLAUDE_MAP OPENCODE_MAP AGENTS_MAP

TARGET_DIR[claude]="$HOME/.claude"
CLAUDE_MAP=(
  "CLAUDE.runtime.claude.md:CLAUDE.md"
  "settings.json:settings.json"
  "memory:memory"
)

TARGET_DIR[opencode]="$HOME/.config/opencode"
OPENCODE_MAP=(
  "AGENTS.runtime.opencode.md:AGENTS.md"
  "opencode.json:opencode.json"
  "oh-my-openagent.json:oh-my-openagent.json"
)

TARGET_DIR[agents]="$HOME/.agents"
AGENTS_MAP=(
  "AGENTS.runtime.agents.md:AGENTS.md"
)

case "$RUNTIME" in
  claude)   SRC_DIR="$BRAIN_PATH/_AGENTS/CLAUDE";   MAP=("${CLAUDE_MAP[@]}")   ;;
  opencode) SRC_DIR="$BRAIN_PATH/_AGENTS/OPENCODE"; MAP=("${OPENCODE_MAP[@]}") ;;
  agents)   SRC_DIR="$BRAIN_PATH/_AGENTS/AGENTS";   MAP=("${AGENTS_MAP[@]}")   ;;
  *) echo "ERROR: unknown runtime '$RUNTIME' (supported: claude, opencode, agents)" >&2; exit 2 ;;
esac

TARGET="${TARGET_DIR[$RUNTIME]}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

# Source dir missing => HOME has no config for this runtime. Nothing to install;
# bootstrap's ingest step (Direction A) is what populates it from local. Report and exit 0.
if [[ ! -d "$SRC_DIR" ]]; then
  echo "SKIP runtime $RUNTIME: HOME has no _AGENTS/$RUNTIME at $SRC_DIR"
  echo "  (nothing to implant. To adopt existing local config into the home, use bootstrap ingest mode [TODO v2].)"
  exit 0
fi

echo "Installing $RUNTIME config symlinks"
echo "  source: $SRC_DIR"
echo "  target: $TARGET"
echo "  mode:   $( [[ $APPLY -eq 1 ]] && echo apply || echo 'dry-run (pass --apply to execute)' )"
echo

for mapping in "${MAP[@]}"; do
  src_rel="${mapping%%:*}"
  tgt_rel="${mapping##*:}"
  src_abs="$SRC_DIR/$src_rel"
  tgt_abs="$TARGET/$tgt_rel"

  if [[ ! -e "$src_abs" ]] && [[ ! -L "$src_abs" ]]; then
    printf 'SKIP    %-34s source missing: %s\n' "$tgt_rel" "$src_abs"
    continue
  fi

  if [[ -L "$tgt_abs" ]] && [[ "$(readlink "$tgt_abs")" == "$src_abs" ]]; then
    printf 'OK      %-34s already linked\n' "$tgt_rel"
    continue
  fi

  if [[ -e "$tgt_abs" ]] || [[ -L "$tgt_abs" ]]; then
    backup="$tgt_abs.backup-$TIMESTAMP"
    if [[ $APPLY -eq 1 ]]; then mv "$tgt_abs" "$backup"; fi
    printf 'BACKUP  %-34s -> %s\n' "$tgt_rel" "$(basename "$backup")"
  fi

  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$(dirname "$tgt_abs")"
    ln -s "$src_abs" "$tgt_abs"
  fi
  printf 'LINK    %-34s -> %s\n' "$tgt_rel" "$src_abs"
done

echo
echo "Done."
