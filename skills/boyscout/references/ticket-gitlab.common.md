# ticket-gitlab — GitLab Issues backend (optional)

Create tickets as GitLab Issues using the `glab` CLI.

## Prerequisites

- `glab` CLI installed and authenticated.
- The current repo must have a GitLab remote.

## Create issue

```bash
glab issue create \
  --title "<one-line summary from finding>" \
  --description "$(cat /tmp/boyscout-ticket-body.md)" \
  --label "boyscout"
```

The body file is prepared from [ticket-template.common.md](ticket-template.common.md).

## After creation

Print the issue URL. The finding is removed from the backlog (GitLab is source of truth).
