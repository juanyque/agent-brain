#!/usr/bin/env bash
#
# fix-ceremony.sh — the deterministic git/gh ceremony around a boyscout fix.
#
# The fix itself (the code edit) is the agent's judgement and is applied to the
# working tree BEFORE calling this script. This script owns the fragile, bitten-
# before mechanics: locale-safe base detection, branch-name verification, remote
# collision pre-flight, PR-state guard, commit/push, and PR creation.
#
# Modes:
#   --mode new-branch <slug> [<base>]            (default) fix in the current repo's worktree
#   --mode skill-gap   <repo-path> <slug> [<base>]         fix in another repo (cd there first)
#   --mode into-pr     <pr-number>                         push the fix into an open PR's branch
#
# Required flags for branch modes: --title "<one-liner>" --body-file <path>
# For into-pr: --title "<commit one-liner>" (the PR already has a body).
#
# Options:
#   --dry-run   print mutating git/gh commands instead of running them
#               (read-only guards — base detection, ls-remote, gh pr view — still run)
#
# Exit codes: 0 ok · 2 usage error · 3 branch-collision pre-flight · 4 PR not OPEN ·
#             5 branch-name verification failed
set -euo pipefail

die()  { echo "fix-ceremony: $*" >&2; exit 2; }
note() { echo "fix-ceremony: $*" >&2; }

DRY_RUN=0
run() {  # run argv directly (no eval — args are passed literally, never shell-parsed), or print when --dry-run
  if [ "$DRY_RUN" -eq 1 ]; then printf 'DRY-RUN $ %s\n' "$*" >&2; else "$@"; fi
}

detect_base() {
  local b
  b=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || true)
  if [ -z "$b" ]; then
    b=$(git branch -r | grep -E 'origin/(main|master)$' | head -1 | sed 's@.*origin/@@' || true)
  fi
  [ -n "$b" ] || die "could not detect base branch (no origin/HEAD, no origin/main|master)"
  echo "$b"
}

validate_slug() {
  echo "$1" | grep -Eq '^[a-z0-9][a-z0-9-]*$' || die "invalid slug '$1' (use lowercase letters, digits, hyphens)"
}

require_body_file() {  # branch modes need a real PR body BEFORE any git mutation, so a
                       # missing file can't leave a pushed branch with no PR
  [ -n "$BODY_FILE" ] || die "branch modes require --body-file for the PR description"
  [ "$DRY_RUN" -eq 1 ] || [ -f "$BODY_FILE" ] || die "body file not found: $BODY_FILE"
}

# ---- parse args ----------------------------------------------------------
MODE="new-branch"; TITLE=""; BODY_FILE=""
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --mode)      MODE="${2:?--mode needs a value}"; shift 2 ;;
    --title)     TITLE="${2:?--title needs a value}"; shift 2 ;;
    --body-file) BODY_FILE="${2:?--body-file needs a value}"; shift 2 ;;
    --dry-run)   DRY_RUN=1; shift ;;
    -h|--help)   sed -n '2,30p' "$0"; exit 0 ;;
    --*)         die "unknown flag: $1" ;;
    *)           POSITIONAL+=("$1"); shift ;;
  esac
done

commit_and_push_new_branch() {  # $1=branch
  local branch="$1"
  if [ "$DRY_RUN" -eq 0 ]; then
    local actual; actual=$(git branch --show-current)
    [ "$actual" = "$branch" ] || { note "branch verification failed: on '$actual', expected '$branch'"; exit 5; }
  fi
  run git add -A
  run git commit -m "$TITLE"
  run git push -u origin "$branch"
  run gh pr create --title "$TITLE" --body-file "$BODY_FILE"
}

setup_branch() {  # $1=slug $2=base ; creates boyscout/fix/<slug>, carrying the working-tree fix
  # Side-effects only — does NOT echo the branch name. `git stash push/pop` write to
  # stdout, so capturing this function's stdout would corrupt the branch name; the
  # caller derives the branch deterministically as "boyscout/fix/<slug>" instead.
  local slug="$1" base="$2" branch="boyscout/fix/$1"
  validate_slug "$slug"
  note "base branch: $base ; target branch: $branch"
  # Pre-flight: remote collision
  if [ -n "$(git ls-remote --heads origin "$branch")" ]; then
    note "remote branch '$branch' already exists — pick a different slug or reuse it deliberately. Aborting."
    exit 3
  fi
  run git fetch origin
  local stashed=0
  if [ -n "$(git status --porcelain)" ]; then run git stash push -u -m boyscout-fix; stashed=1; fi
  run git switch -c "$branch" "origin/$base"
  if [ "$stashed" -eq 1 ]; then run git stash pop; fi
}

case "$MODE" in
  new-branch)
    [ "${#POSITIONAL[@]}" -ge 1 ] || die "new-branch needs <slug> [<base>]"
    SLUG="${POSITIONAL[0]}"; BASE="${POSITIONAL[1]:-$(detect_base)}"
    [ -n "$TITLE" ] || die "new-branch needs --title"
    require_body_file
    setup_branch "$SLUG" "$BASE"
    BRANCH="boyscout/fix/$SLUG"
    commit_and_push_new_branch "$BRANCH"
    note "done (new-branch). PR opened from $BRANCH."
    ;;
  skill-gap)
    [ "${#POSITIONAL[@]}" -ge 2 ] || die "skill-gap needs <repo-path> <slug> [<base>]"
    REPO="${POSITIONAL[0]}"; SLUG="${POSITIONAL[1]}"
    [ -d "$REPO" ] || die "repo path not found: $REPO"
    cd "$REPO"
    BASE="${POSITIONAL[2]:-$(detect_base)}"
    [ -n "$TITLE" ] || die "skill-gap needs --title"
    require_body_file
    setup_branch "$SLUG" "$BASE"
    BRANCH="boyscout/fix/$SLUG"
    commit_and_push_new_branch "$BRANCH"
    note "done (skill-gap in $REPO). PR opened from $BRANCH."
    ;;
  into-pr)
    [ "${#POSITIONAL[@]}" -ge 1 ] || die "into-pr needs <pr-number>"
    PR="${POSITIONAL[0]}"
    echo "$PR" | grep -Eq '^[0-9]+$' || die "invalid PR number: $PR"
    [ -n "$TITLE" ] || die "into-pr needs --title (commit one-liner)"
    # Capture with an explicit rc check — a process-substitution `read < <(gh ...)` would,
    # under `set -e`, abort with a bare exit 1 on a gh failure and skip this diagnostic.
    PR_INFO=$(gh pr view "$PR" --json state,headRefName --jq '"\(.state) \(.headRefName)"') \
      || die "gh pr view #$PR failed (PR missing, or auth/network issue)"
    read -r STATE PR_BRANCH <<< "$PR_INFO"
    note "PR #$PR state=$STATE branch=$PR_BRANCH"
    [ "$STATE" = "OPEN" ] || { note "PR #$PR is $STATE — cannot push to a merged/closed branch. Use new-branch mode."; exit 4; }
    run git fetch origin
    stashed=0
    if [ -n "$(git status --porcelain)" ]; then run git stash push -u -m boyscout-fix; stashed=1; fi
    run git switch --detach "origin/$PR_BRANCH"
    if [ "$stashed" -eq 1 ]; then run git stash pop; fi
    run git add -A
    run git commit -m "$TITLE"
    run git push origin "HEAD:$PR_BRANCH"
    note "done (into-pr). Fix pushed to existing PR branch $PR_BRANCH."
    ;;
  *)
    die "unknown mode: $MODE (expected new-branch | skill-gap | into-pr)"
    ;;
esac
