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
#   runtime: claude | opencode | agents | codex

set -euo pipefail

USAGE="Usage: $0 <runtime> --brain <brain_path> [--apply]"

RUNTIME=""
BRAIN_PATH=""
APPLY=0
ASSUME_TARGET_MISSING=":"
ASSUME_SOURCE_PRESENT=":"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --brain) BRAIN_PATH="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    # Internal dry-run aid used by runtime_manager after a planned quarantine.
    --assume-target-missing) ASSUME_TARGET_MISSING="${ASSUME_TARGET_MISSING}${2:-}:"; shift 2 ;;
    # Internal dry-run aid used by runtime_manager after a planned ingest.
    --assume-source-present) ASSUME_SOURCE_PRESENT="${ASSUME_SOURCE_PRESENT}${2:-}:"; shift 2 ;;
    -h|--help) echo "$USAGE"; exit 0 ;;
    *) if [[ -z "$RUNTIME" ]]; then RUNTIME="$1"; shift; else echo "ERROR: unknown arg: $1" >&2; echo "$USAGE" >&2; exit 2; fi ;;
  esac
done

[[ -n "$RUNTIME" ]] || { echo "ERROR: runtime required (claude|opencode)" >&2; echo "$USAGE" >&2; exit 2; }
[[ -n "$BRAIN_PATH" ]] || { echo "ERROR: --brain required" >&2; echo "$USAGE" >&2; exit 2; }

BRAIN_PATH="${BRAIN_PATH%/}"

# --- Per-runtime config ------------------------------------------------------
# Keep this compatible with the Bash 3.2 shipped by macOS: associative arrays
# (`declare -A`) are intentionally avoided.
declare -a CLAUDE_MAP OPENCODE_MAP AGENTS_MAP CODEX_MAP

CLAUDE_MAP=(
  "CLAUDE.runtime.claude.md:CLAUDE.md"
  "settings.json:settings.json"
  "memory:memory"
)

OPENCODE_MAP=(
  "AGENTS.runtime.opencode.md:AGENTS.md"
  "opencode.json:opencode.json"
  "oh-my-openagent.json:oh-my-openagent.json"
)

AGENTS_MAP=(
  "AGENTS.runtime.agents.md:AGENTS.md"
)

CODEX_MAP=(
  "AGENTS.runtime.codex.md:AGENTS.md"
  "config.toml:config.toml"
)

case "$RUNTIME" in
  claude)   SRC_DIR="$BRAIN_PATH/_AGENTS/CLAUDE";   TARGET="$HOME/.claude";          MAP=("${CLAUDE_MAP[@]}")   ;;
  opencode) SRC_DIR="$BRAIN_PATH/_AGENTS/OPENCODE"; TARGET="$HOME/.config/opencode"; MAP=("${OPENCODE_MAP[@]}") ;;
  agents)   SRC_DIR="$BRAIN_PATH/_AGENTS/AGENTS";   TARGET="$HOME/.agents";          MAP=("${AGENTS_MAP[@]}")   ;;
  codex)    SRC_DIR="$BRAIN_PATH/_AGENTS/CODEX";    TARGET="$HOME/.codex";           MAP=("${CODEX_MAP[@]}")    ;;
  *) echo "ERROR: unknown runtime '$RUNTIME' (supported: claude, opencode, agents, codex)" >&2; exit 2 ;;
esac

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

# Source dir missing => HOME has no config for this runtime. Nothing to install;
# bootstrap's ingest step (Direction A) is what populates it from local. Report and exit 0.
if [[ ! -d "$SRC_DIR" && "$ASSUME_SOURCE_PRESENT" == ":" ]]; then
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
  source_will_be_present=0
  [[ "$ASSUME_SOURCE_PRESENT" == *":$src_rel:"* ]] && source_will_be_present=1
  target_will_be_missing=0
  [[ "$ASSUME_TARGET_MISSING" == *":$tgt_rel:"* ]] && target_will_be_missing=1

  if [[ $source_will_be_present -eq 0 ]] && [[ ! -e "$src_abs" ]] && [[ ! -L "$src_abs" ]]; then
    printf 'SKIP    %-34s source missing: %s\n' "$tgt_rel" "$src_abs"
    continue
  fi

  if [[ "$RUNTIME" == "codex" && "$tgt_rel" == "config.toml" && $APPLY -eq 1 ]]; then
    chmod 600 "$src_abs"
  fi

  if [[ -L "$tgt_abs" ]] && [[ "$(readlink "$tgt_abs")" == "$src_abs" ]]; then
    printf 'OK      %-34s already linked\n' "$tgt_rel"
    continue
  fi

  if [[ $target_will_be_missing -eq 0 ]] && { [[ -e "$tgt_abs" ]] || [[ -L "$tgt_abs" ]]; }; then
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
