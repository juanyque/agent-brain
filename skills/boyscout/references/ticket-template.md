# Ticket template (Step 4B)

## Determine project / parent

1. Check current git branch name for a ticket code (e.g. `PROJ-174_...`).
2. If found, use that project key for the ticket.
3. If not found, ask:
   > "What ticket or project should I file this under?"

## Body template

```
Summary: [concise one-liner]

Context:
  Found while working on: [current task / ticket / PR]
  Location: [file(s), line(s), module(s)]
  Type: [flaky-test | dead-code | docs-gap | skill-gap | ...]
  Estimated effort: [XS / S / M / L]

Description:
  [What is wrong or suboptimal. Specific enough that someone can pick it up cold.
   Include relevant code snippets, error messages, or test output.]

Analysis:
  [Root cause or hypothesis. What conditions trigger the issue.]

Suggested fix:
  [Approach, affected files, rough implementation notes.]

Acceptance criteria:
  - [ ] [Verifiable condition 1]
  - [ ] [Verifiable condition 2]
```

## Create

Use the provider selected by the active environment profile. When no profile is active, ask for
the backend if the repository context does not make it unambiguous.

- **GitHub Issues:** see [ticket-github.md](ticket-github.md).
- **Jira:** see [ticket-jira.md](ticket-jira.md).
- **GitLab Issues:** see [ticket-gitlab.md](ticket-gitlab.md).

The public skill does not pre-authorize any provider write. Creating a ticket must pass through
the runtime's normal consent flow unless a private environment overlay explicitly grants a
narrower permission.

On failure, report the error and ask the user whether to retry or skip. On success, report:
> "Created [TICKET-123]: [summary] — [URL]"

All ticket content must be in English, regardless of conversation language.
