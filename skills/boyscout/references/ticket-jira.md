# ticket-jira — Jira backend (optional)

Create tickets through the Jira provider selected by the active environment profile.

## Prerequisites

- `profile_context.py` resolved the required `issues.*` capabilities to a Jira MCP provider.
- Live discovery did not report the provider as missing, disabled, or unauthenticated.
- The returned runtime invocation hints are exposed in the active agent tool catalog.
- A valid project key from the selected profile policy or explicit user input.

## Project key detection

1. Match the branch against `issue_tracking.branch_patterns` returned by the resolver.
2. If there is no match, use `default_project` only when the profile defines it and its
   `parent_resolution.confirmation_required` gate is satisfied.
3. Otherwise ask the user for the project and optional parent epic.

## Create issue

Use the invocation returned for `issues.create`, with the profile's `default_issue_type` and the
body format from [ticket-template.md](ticket-template.md). Resolve the parent with the returned
`issues.read`/`issues.search` operations and `parent_resolution` policy.

When `description_write` is `create_then_update_markdown`, create with a minimal description and
then use the resolved `issues.update` operation with Markdown content. If any provider operation
is absent from the active tool catalog, stop before creation and keep the finding in the backlog.

## After creation

Print the Jira URL. The finding is removed from the backlog (ticket tracker is source of truth).

## Failure boundary

Profile declaration, runtime registration, authentication, tool exposure, and provider-call
success are separate checks. A failure at any boundary leaves the backlog unchanged. If creation
succeeds but a later update/removal fails, record the created issue before retrying so the resume
path cannot create a duplicate.
