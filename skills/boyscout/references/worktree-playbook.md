# Worktree playbook (Step 4A)

Never touch the current working tree. All fixes happen in a separate worktree on a fresh branch from the
up-to-date base — or, for the in-review case, on the open PR's own branch.

The fragile git/gh ceremony (locale-safe base detection, remote-collision pre-flight, branch-name
verification, PR-state guard, commit/push, PR creation) is owned by **`scripts/fix-ceremony.sh`**. The
agent applies the fix to the working tree, then calls the script for its mode. Read the script header for
the exact flags.

## Mode → step mapping

| Finding situation | Subagent isolation | fix-ceremony mode | Invocation (after the fix is in the working tree) |
|---|---|---|---|
| Standard finding, same repo as the primary task | `isolation: "worktree"` (isolated copy at HEAD) | `new-branch` | `scripts/fix-ceremony.sh --mode new-branch <slug> [<base>] --title "<one-liner>" --body-file <path>` |
| `skill-gap` finding, **different** repo | regular subagent — **never** `worktree` (would clone the wrong repo) | `skill-gap` | `scripts/fix-ceremony.sh --mode skill-gap <repo-path> <slug> [<base>] --title … --body-file <path>` |
| Finding targets a file in the PR currently under review (PR is `OPEN`) | regular subagent | `into-pr` | `scripts/fix-ceremony.sh --mode into-pr <pr-number> --title "<commit one-liner>"` |

What the script does per mode, and its guards (collision pre-flight exits 3; branch-name verify exits 5;
PR-not-OPEN exits 4), are documented in the script header. On a non-zero exit, surface the message to the
user and decide (new slug, retry, or abort) — do not auto-delete branches; commits/branches left behind
are intact.

## Subagent brief (every variant)

The script handles the ceremony; the brief handles the *fix*. Brief the subagent with:

- A self-contained description of the fix — exact file paths, line numbers, and what to change.
- The success criterion (what "done" looks like).
- The list of files touched by the primary task — **do not modify any of them**.
- For `skill-gap`: the target skill's repo path and SKILL.md location.
- The PR slug and a one-line title; for `into-pr`, the PR number.

Report when done: `"Fixed [summary] — PR: <URL>"` (or, for into-pr, `"… in existing PR branch <branch>"`).

If the subagent reports it lacks Bash/Read/Glob permissions, handle the fix directly in the parent session
using the same `fix-ceremony.sh` invocation.

## PR body — PII rule

The PR body states what the fix is and the context it was found in, e.g.:

```
Boyscout fix: <one-line summary>

Found while: <ticket code or brief description — no raw error output, code snippets, or stack traces>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Write it to a file and pass `--body-file`. Never paste raw error output, code, or stack traces into the
body (leakage guard, consistent with deep-mode's PII rules).
