# ticket-jira — Jira backend (optional)

Create tickets in Jira using the Jira MCP tools (`mcp__jira__createJiraIssue`, etc.).

## Prerequisites

- Jira MCP server configured in the agent runtime.
- A valid Jira project key.

## Project key detection

1. Branch matches `<PROJECT>-NNN_*` → use that project key.
2. No ticket prefix → ask the user for the Jira project key.
3. Non-git repo or `skill-gap` → ask the user for the project and optional parent epic.

## Create issue

Call `mcp__jira__createJiraIssue` with type `Task`, using the body format from [ticket-template.common.md](ticket-template.common.md). Resolve parent epic via `mcp__jira__getJiraIssue` if a ticket-prefixed branch was detected.

## After creation

Print the Jira URL. The finding is removed from the backlog (Jira is source of truth).
