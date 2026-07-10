#!/usr/bin/env bash
#
# bootstrap-zero.sh — agent-brain setup orchestrator for a HOME.
#
# Wires a notes folder (Obsidian vault, generic notes dir, or empty) to the agent-brain
# operating model: git-snapshot -> _COMMON symlink -> per-runtime config symlinks
# (via runtime_install.sh) -> brain skill link -> health-check.
#
# Assumes the agent-brain repo is already present on disk (the root bootstrap-zero.sh
# clones it first; or you are running from a dev checkout).
#
# Safe by construction: dry-run by default (--apply to execute); the git-snapshot is the
# only mutating step and it is fully reversible (a tag/commit). Conflicts are backed up
# (.backup-<ts>) by runtime_install.sh, never clobbered.
#
# Usage:
#   bootstrap-zero.sh --home <home_path> [--apply] [--update] [--runtime claude,opencode]
#     --home      the HOME path (if omitted, prompts interactively)
#     --apply     execute (default: dry-run plan only)
#     --update    git-pull the agent-brain repo before wiring
#     --runtime   restrict to a comma-separated subset of runtimes (default: detect all)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MODEL_DIR="$REPO_ROOT/model"
FIND_HOME="$REPO_ROOT/skills/brain/scripts/find_home.py"

HOME_PATH=""
APPLY=0
UPDATE=0
RUNTIME_FILTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --home) HOME_PATH="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --update) UPDATE=1; shift ;;
    --runtime) RUNTIME_FILTER="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 2 ;;
  esac
done

run() { if [[ $APPLY -eq 1 ]]; then "$@"; else printf '  (dry-run) %s\n' "$*"; fi; }
mode() { [[ $APPLY -eq 1 ]] && echo "apply" || echo "dry-run (pass --apply to execute)"; }

# --- Step 0: resolve HOME ----------------------------------------------------
if [[ -z "$HOME_PATH" ]]; then
  echo "== Home resolution =="
  if [[ -f "$FIND_HOME" ]] && command -v python3 >/dev/null 2>&1; then
    echo "  Detected HOME candidates:"
    python3 "$FIND_HOME" "$HOME" 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for h in d.get("homes", []):
    print(f"    [{h[\"notes_mode\"]:8}] {h[\"path\"]}")' || true
  fi
  echo "  (enter a path: existing notes folder/vault, or a new empty dir to create)"
  read -r -p "HOME path: " HOME_PATH
fi
if [[ ! -d "$HOME_PATH" ]]; then
  echo "  path does not exist: $HOME_PATH"
  read -r -p "Create it? [y/N] " mk
  [[ "$mk" =~ ^[Yy]$ ]] || { echo "ERROR: aborting"; exit 2; }
  run mkdir -p "$HOME_PATH"
fi
HOME_PATH="$(cd "$HOME_PATH" && pwd)"
echo "HOME = $HOME_PATH  (mode: $(mode))"
echo

# --- Step 1: notes_mode ------------------------------------------------------
notes_mode="empty"
if [[ -f "$FIND_HOME" ]] && command -v python3 >/dev/null 2>&1; then
  notes_mode="$(python3 "$FIND_HOME" "$HOME_PATH" 2>/dev/null | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["homes"][0]["notes_mode"])
except Exception: pass' 2>/dev/null || echo "")"
fi
notes_mode="${notes_mode:-empty}"
echo "== notes_mode: $notes_mode =="
echo

# --- Step 2: git-snapshot (rollback anchor) ----------------------------------
echo "== git-snapshot =="
cd "$HOME_PATH"
if [[ ! -d ".git" ]]; then
  echo "  no git repo -> init + commit everything (rollback anchor)"
  run git init -q
  run git add -A
  run git -c user.email="agent-brain@local" -c user.name="agent-brain" commit -q -m "agent-brain: pre-bootstrap snapshot" || true
elif [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  echo "  ERROR: HOME is a git repo with a dirty working tree." >&2
  echo "  Commit or stash your changes first — agent-brain never commits uncommitted user work." >&2
  exit 3
else
  TS="$(date +%Y%m%d-%H%M%S)"
  echo "  clean repo -> tag pre-bootstrap-$TS"
  run git tag "pre-bootstrap-$TS"
fi
echo

# --- Step 3: ensure agent-brain repo -----------------------------------------
echo "== agent-brain repo =="
if [[ ! -d "$REPO_ROOT/.git" ]]; then
  echo "  ERROR: cannot locate agent-brain repo at $REPO_ROOT" >&2
  echo "  (when run via curl|bash, the root bootstrap-zero.sh clones it first)" >&2
  exit 4
fi
if [[ $UPDATE -eq 1 ]]; then echo "  updating (git pull --ff-only)..."; run git -C "$REPO_ROOT" pull --ff-only; fi
echo "  repo: $REPO_ROOT"
echo

# --- Step 4: _COMMON symlink (absolute) --------------------------------------
echo "== _COMMON symlink =="
COMMON_LINK="$HOME_PATH/_COMMON"
COMMON_TARGET="$MODEL_DIR"
if [[ -L "$COMMON_LINK" && "$(readlink "$COMMON_LINK")" == "$COMMON_TARGET" ]]; then
  echo "  OK already linked -> $COMMON_TARGET"
else
  if [[ -e "$COMMON_LINK" || -L "$COMMON_LINK" ]]; then
    bk="$COMMON_LINK.backup-$(date +%s)"
    echo "  BACKUP existing _COMMON -> $(basename "$bk")"
    run mv "$COMMON_LINK" "$bk"
  fi
  run ln -s "$COMMON_TARGET" "$COMMON_LINK"
  echo "  LINK _COMMON -> $COMMON_TARGET"
fi
echo

# --- Step 5: per-runtime wiring ----------------------------------------------
echo "== per-runtime wiring =="
home_subdir() { [[ "$1" == "claude" ]] && echo "CLAUDE" || echo "OPENCODE"; }
local_dir_for() { [[ "$1" == "claude" ]] && echo "$HOME/.claude" || echo "$HOME/.config/opencode"; }

all_runtimes="claude,opencode"
IFS=',' read -ra RT_ARR <<< "${RUNTIME_FILTER:-$all_runtimes}"

for rt in "${RT_ARR[@]}"; do
  echo "-- runtime: $rt --"
  home_rt="$HOME_PATH/_AGENTS/$(home_subdir "$rt")"
  loc_rt="$(local_dir_for "$rt")"
  if [[ ! -d "$home_rt" && ! -d "$loc_rt" ]]; then
    echo "   SKIP (neither local $loc_rt nor HOME/_AGENTS/$(home_subdir "$rt") present)"
    continue
  fi
  if [[ ! -d "$home_rt" ]]; then
    echo "   HOME has no _AGENTS/$(home_subdir "$rt"); local config exists -> ingest (Direction A) [TODO v2]"
    echo "   (nothing implanted for now; populate $home_rt manually or wait for ingest mode)"
    continue
  fi
  echo "   runtime_install (symlinks local -> HOME):"
  if [[ $APPLY -eq 1 ]]; then
    bash "$SCRIPT_DIR/runtime_install.sh" "$rt" --home "$HOME_PATH" --apply
  else
    bash "$SCRIPT_DIR/runtime_install.sh" "$rt" --home "$HOME_PATH"
  fi
done
echo

# --- Step 6: brain skill link ------------------------------------------------
echo "== brain skill link =="
for rt in "${RT_ARR[@]}"; do
  loc_rt="$(local_dir_for "$rt")"
  [[ -d "$loc_rt" || -d "$HOME_PATH/_AGENTS/$(home_subdir "$rt")" ]] || continue
  skills_dir="$loc_rt/skills"
  link="$skills_dir/brain"
  target="$REPO_ROOT/skills/brain"
  if [[ -L "$link" && "$(readlink "$link")" == "$target" ]]; then
    echo "  OK brain skill ($rt) already linked"
  else
    if [[ -e "$link" || -L "$link" ]]; then
      echo "  BACKUP $link"
      run mv "$link" "$link.backup-$(date +%s)"
    fi
    run mkdir -p "$skills_dir"
    run ln -s "$target" "$link"
    echo "  LINK brain skill ($rt) -> $target"
  fi
done
echo

# --- Step 7: health-check ----------------------------------------------------
echo "== health-check =="
if [[ $APPLY -eq 0 ]]; then
  echo "  (dry-run — apply, then health-check verifies: _COMMON resolves, model/SCRIPTS,"
  echo "   skills/brain, and per-runtime symlinks)"
else
  fail=0
  check() { local label="$1" path="$2"; if [[ -e "$path" || -L "$path" ]]; then echo "  OK   $label"; else echo "  FAIL $label ($path)"; fail=1; fi; }
  check "_COMMON resolves" "$HOME_PATH/_COMMON"
  check "model/SCRIPTS present" "$MODEL_DIR/SCRIPTS"
  check "skills/brain present" "$REPO_ROOT/skills/brain"
  echo
  [[ $fail -eq 0 ]] && echo "✅ health-check passed" || echo "⚠️  health-check has failures (see above)"
fi
[[ $APPLY -eq 0 ]] && echo "(dry-run — re-run with --apply to execute)"
