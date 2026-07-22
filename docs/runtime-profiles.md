# Environment profiles

Environment profiles separate reusable agent behavior from the private details that make
that behavior useful in a particular organization or personal workspace.

This document defines the version 1 contract implemented by the public loader, diagnostics,
capability resolver, and standalone overlay projector.

## Goals

- Keep the public `agent-brain` checkout free of organization-specific project names,
  paths, providers, policies, and credentials.
- Let one private brain describe multiple environments without changing global runtime
  symlinks when the current working directory changes.
- Let skills request generic capabilities such as `issues.read` or `pull_requests.create`.
  The selected profile chooses a provider; the runtime adapter performs the invocation.
- Preserve the instruction precedence `core < profile < brain < project < explicit`.
- Fail closed on unknown fields, unsafe paths, missing required capabilities, and unavailable
  required providers.

## Non-goals for version 1

- Profiles do not install runtimes or rewrite monolithic runtime configuration.
- Profiles do not contain credentials or secret values.
- Profiles do not compose or inherit from other profiles. Exactly one profile is selected.
- Profiles do not override brain, project, or explicit user instructions.
- Profiles do not define provider-specific executable workflows. Skills continue to own the
  workflow, while adapters own provider invocation.

## Canonical layout

Profiles are private brain configuration and live under the runtime-neutral shared area:

```text
<brain>/_AGENTS/SHARED/
├── environment.json
└── profiles/
    ├── work.json
    └── personal.json
```

`environment.json` selects a profile. Each `<id>.json` is an environment profile conforming
to [`environment-profile-v1.schema.json`](schemas/environment-profile-v1.schema.json).

The public repository contains only sanitized examples under `examples/profiles/`.

## Profile selection

Resolve one profile in this order:

1. An explicit `--profile <id>` argument supplied to a profile-aware command.
2. The `AGENT_BRAIN_PROFILE` environment variable.
3. The matching `project_rules` entry whose expanded `path_prefix` is the longest prefix of
   the current working directory.
4. `default_profile` from `_AGENTS/SHARED/environment.json`.

Ties at the same path-prefix length are configuration errors. An unknown profile id is an
error. Version 1 never merges two profiles.

Profile selection changes resolved context only. It must not repoint `~/.claude`, `~/.codex`,
`~/.agents`, or another global runtime home.

## Precedence

Resolved values are advisory inputs at the profile layer:

```text
public core < selected profile < brain rules < project rules < explicit instruction
```

A profile may supply a default tracker project, for example, but a project-local instruction
or explicit user choice wins. A validator must reject a profile that claims a higher
precedence or attempts to replace protected instructions.

## Profile document

Every profile has these top-level fields:

| Field | Purpose |
|---|---|
| `schema_version` | Integer contract version. Version 1 requires `1`. |
| `id` | Stable lowercase profile identifier. |
| `display_name` | Human-readable label. |
| `providers` | Available MCP, CLI, API, or manual providers and their abstract operations. |
| `capability_routes` | Ordered provider fallbacks for each generic capability. |
| `issue_tracking` | Optional issue-key, branch, project, parent, and content conventions. |
| `projects` | Project/repository catalog with paths, aliases, relevance hints, and docs. |
| `runtime_overlays` | Optional references to private rules, skills, agents, or themes. |
| `operational_rules` | Short environment rules with an authoritative source reference. |

Unknown fields are errors. This makes typos and unsupported configuration visible instead of
silently ignored.

## Capabilities and providers

Skills request capabilities. They do not name a company tool or runtime-specific function.
Capability names use a dotted namespace, for example:

- `issues.read`, `issues.search`, `issues.create`, `issues.update`
- `repositories.read`
- `pull_requests.read`, `pull_requests.create`
- `documents.read`, `documents.write`
- `chat.search`
- `observability.read`

A provider declares its transport (`mcp`, `cli`, `api`, or `manual`), service identifier, and
the operations it supports. `capability_routes` orders the providers to try. Runtime adapters
translate the provider transport and abstract operation into the concrete tool available in
that runtime.

Providers may be retained as inventory entries with an empty operation map while their MCP is
known to be configured but no stable tool contract has been established. Such a provider must
not appear in a capability route until the routed operation is factual and validated.

For example, a profile can route `issues.create` to an MCP Jira provider while another routes
the same capability to a GitHub CLI provider. The skill workflow remains unchanged.

Required providers are checked during preflight. Static runtime health can prove local CLI and
environment-reference availability, but MCP and API availability is reported as
`adapter-check`: the runtime adapter must perform live tool discovery without exposing
credentials. Optional providers may fall through to the next configured provider. A manual
provider is an explicit fallback, not silent permission to invent a result.

## Issue-tracking conventions

`issue_tracking` captures environment policy that was previously embedded in skills:

- recognized project keys and issue-key patterns;
- branch naming patterns;
- default project and issue type;
- fields inherited from a current or template issue;
- parent lookup strategy;
- content language;
- provider-specific write behavior, such as create-then-update for Markdown bodies.

These values configure a generic issue workflow. The skill still owns confirmation,
idempotence, partial-state recovery, and backlog mutation.

## Project catalog

Each project entry may include:

- aliases and relevance keywords;
- one or more local path prefixes;
- repositories and their local paths/remotes;
- documentation locations in a brain, repository, or external URL.

Paths may use `~` and environment-variable references. They are expanded only for matching or
read-only discovery unless a separate workflow authorizes a mutation.

The project catalog helps select context. It does not grant access to repositories, services,
or infrastructure.

## Runtime overlays

Profiles and runtimes are independent axes. An overlay is a reference to a private resource,
not inline runtime configuration. Overlay paths must:

- be relative to the brain;
- remain inside the brain after resolution;
- reject `..`, absolute paths, and symlink escapes;
- identify the runtimes to which they apply, or `*` for runtime-neutral resources.

Every overlay also declares a `target` path relative to a target root supplied by the runtime
adapter. This keeps runtime filesystem conventions out of both the profile and the public
projector. For example:

```json
{
  "runtime": "*",
  "kind": "rule",
  "path": "_AGENTS/SHARED/profiles/work/rules/review-policy.md",
  "target": "review-policy.md"
}
```

`profile_overlays.py` projects these resources as symlinks. It is dry-run by default and
requires one explicit `--target-root KIND=PATH` for each selected resource kind. A conflicting
runtime target is moved to
`INBOX/_PROFILE_OVERLAYS/<runtime>/<profile>/<kind>/<target>` before the profile resource is
linked. Existing quarantine content is never overwritten, a failed link restores the original
target, and applying the same plan twice creates no drift.

The projector does not interpret resource contents, edit runtime config, stage brain files, or
grant tool permissions. Choosing factual target roots and activating the projected resource
remain runtime-adapter responsibilities.

## Secrets

Committed profiles contain references only. A `secret_refs` entry identifies an environment
variable, keychain item, or runtime-native secret name without including its value.

Preflight must:

1. Validate the reference kind and identifier.
2. Report whether a required reference is available.
3. Never print, serialize, diff, or log the resolved value.
4. Perform no provider call during a dry-run unless the user explicitly requested a live
   connectivity check.

`profile_secrets.py` implements the name-only readiness preflight. Environment references are
checked for a non-empty value without reading it into the result. Keychain references remain
`adapter-check` unless the metadata-only macOS adapter is selected; that adapter discards all
process streams, never requests the password value, and has a fixed timeout. Runtime-native
references consume only an explicit name catalog from the active adapter. An incomplete catalog
cannot claim a reference is missing.

Required references must be confirmed `available` for the dedicated preflight to pass. Static
runtime health may report an unavailable adapter as unresolved, but it never upgrades unresolved
state to available. No secret value is present in status objects, console output, or latest-run
logs.

## Validation

A profile-aware command must validate before use:

- JSON syntax and supported `schema_version`;
- schema conformance with unknown fields rejected;
- safe ids and paths;
- selection references to existing profiles;
- provider routes that reference known providers;
- routed capabilities implemented by the referenced providers;
- `issue_tracking.provider` and project defaults that exist in the profile;
- required provider and secret availability;
- runtime overlay compatibility with the active runtime.

Validation errors must name the JSON path, rejected value, and expected contract. Secret
values must never appear in errors.

## Public/private boundary

The public repository owns:

- schemas and the selection algorithm;
- capability vocabulary and provider transport types;
- validation, precedence, and safety rules;
- sanitized examples and tests;
- runtime adapter interfaces.

Public skills must not embed or pre-authorize concrete provider tool namespaces. A resolver may
derive an invocation hint from private profile data, but external writes use the runtime's normal
consent flow. Narrow pre-authorization belongs in an explicitly selected private runtime overlay,
never in public skill frontmatter.

The private brain owns:

- organization and project names;
- tracker project keys and naming rules;
- repository paths, aliases, and documentation homes;
- provider choices and availability expectations;
- concrete provider operation bindings and any narrowly scoped tool pre-authorization;
- private rules, skills, agents, themes, and secret references.

Project-local instructions remain in the project. Credentials remain in secret stores.

## Implementation status

Implemented:

1. This contract, schemas, sanitized examples, and a private factual profile.
2. A stdlib-only strict loader, schema/semantic validator, and deterministic selector.
3. Read-only profile diagnostics in runtime health without changing runtime symlinks.
4. Sanitized Codex MCP registry discovery with explicit registered, unavailable, and
   authentication-required states.
5. Skill-facing capability resolution through `profile_context.py`, including runtime invocation
   hints, optional issue-tracking policy, and exact name-only comparison against a complete active
   tool catalog supplied by the caller.
6. Boyscout issue creation as the first generic consumer. It resolves `issues.*` through the
   selected profile and refuses silent tracker fallback when live readiness fails.
7. Optional standalone overlay projection with dry-run, conflict quarantine, rollback on link
   failure, and double-apply idempotence.
8. Name-only secret preflight for environment, metadata-only macOS keychain, and sanitized
   runtime-native catalogs.
9. End-to-end temporary-`HOME` integration coverage, executed by CI on macOS and Linux, including
   conflict quarantine and second-apply no-drift verification.

Next:

1. Add native active-agent tool-catalog discovery only where a runtime exposes a proven
   non-mutating, name-only introspection API. Until then, callers pass their in-process catalog to
   `profile_context.py`; incomplete catalogs remain unverified.
2. Add safe Claude/OpenCode MCP discovery once their CLI contracts are proven non-mutating and
   tested.
3. Keep the cross-platform integration matrix green as additional runtimes add adapters.
