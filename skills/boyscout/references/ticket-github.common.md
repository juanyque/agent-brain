# ticket-github — GitHub Issues backend (default)

Create tickets as GitHub Issues using the `gh` CLI.

## Prerequisites

- `gh` CLI installed and authenticated (`gh auth login`).
- The current repo must have a GitHub remote (check with `git remote -v`).

## Create issue

```bash
gh issue create \
  --title "<one-line summary from finding>" \
  --body-file /tmp/boyscout-ticket-body.md \
  --label "boyscout" \
  --label "<effort>:<risk>"
```

The body file is prepared from [ticket-template.common.md](ticket-template.common.md).

## Project key detection

GitHub Issues does not use project keys the way Jira does. Instead:
1. If the branch name contains a ticket pattern (e.g. `PROJ-123_*`), add it as a label.
2. Otherwise, create the issue without a project label — the repo itself is the namespace.

## After creation

Print the issue URL. The finding is removed from the backlog (GitHub is source of truth).
