# ticket-jira — Jira backend (optional)

Create tickets through a Jira provider available in the active runtime.

## Prerequisites

- Jira MCP server configured in the agent runtime.
- A valid Jira project key.

## Project key detection

1. Branch matches `<PROJECT>-NNN_*` → use that project key.
2. No ticket prefix → ask the user for the Jira project key.
3. Non-git repo or `skill-gap` → ask the user for the project and optional parent epic.

## Create issue

Use the runtime's Jira create operation and the body format from [ticket-template.md](ticket-template.md).
Concrete operation names and pre-authorization belong to private environment configuration.

## After creation

Print the Jira URL. The finding is removed from the backlog (ticket tracker is source of truth).
