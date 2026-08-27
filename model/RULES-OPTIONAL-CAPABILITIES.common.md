# Optional capabilities
<!-- content-boundary: {"kind":"policy-owner","policy_id":"policy.optional-capabilities","owner":"model/RULES-OPTIONAL-CAPABILITIES.common.md"} -->
<!-- content-boundary: {"kind":"optional-capability","capability":"graphify","startup":"excluded"} -->
<!-- content-boundary: {"kind":"optional-capability","capability":"source-ingestion","startup":"excluded"} -->

Use this rule when a project's active WIP context references an optional tool or
capability that is not part of the base brain model.

## Activation and discovery

- Optional capabilities are disabled by default. Their CLI, runtime skill, or local
  installation does not opt a vault or project in.
- `WIP/WIP.md` is the activation and discovery surface. A capability is active for a
  project only when that project's dashboard entry links directly to its registry or
  descriptor.
- Put the link under a project-specific heading that matches the working-directory
  vocabulary. Session startup filters the WIP digest by the current directory, so a
  generic capability-only heading is not sufficient.
- A directory or note that exists without an active dashboard link is dormant. Do not
  infer activation from filesystem presence alone.
- Load the linked registry first, then only the descriptor that matches the current
  project's canonical root. Do not load every registered project.
- If the match is missing, ambiguous, disabled, invalid, or stale, fail closed: do not
  use the capability and explain the condition briefly.
- Registration is explicit per project. Never enroll a repository, install a tool,
  generate data, or add project hooks merely because the capability is available.

Every active registry and descriptor under `WIP/` must also be linked directly from
`WIP/WIP.md`, following the normal WIP dashboard invariant.

## Graphify

Graphify is an optional code-knowledge capability. It turns a selected corpus into a
persistent graph that agents can query across sessions.

### Vault layout

When a vault opts in, use these Obsidian-safe names by convention:

```text
WIP/
└── GRAPHIFY/
    ├── graphify.registry.md
    └── graphify.<project-or-graph>.md
```

- `graphify.registry.md` is the compact project-to-descriptor index.
- `graphify.<project-or-graph>.md` describes one generated graph. Several modules,
  packages, repositories, or deployables may share one descriptor when cross-boundary
  relationships are the reason for building the graph.
- Use one descriptor per graph, not automatically one descriptor per directory.

Use the common templates in `TEMPLATES/TEMPLATE.graphify-registry.common.md` and
`TEMPLATES/TEMPLATE.graphify-project.common.md` when creating these notes.

### Storage boundary

- Keep generated graphs, caches, reports, visualizations, and extracted corpora outside
  both the project checkout and the brain. They are large, regenerable operational
  assets, not durable Markdown knowledge.
- The project descriptor stores the external graph path, source roots, exclusions,
  Graphify version, source revision, freshness evidence, and exact query and refresh
  commands.
- Do not copy secrets, generated credentials, runtime dumps, or sensitive configuration
  into a Graphify corpus. Record exclusions without listing secret values.
- Project repositories stay unchanged unless the user separately authorizes a native
  Graphify integration such as a Git hook or an `AGENTS.md` / `CLAUDE.md` section.

### Query behavior

For a matching descriptor:

1. Verify that the descriptor status is `ready` and that its graph file exists.
2. Compare the recorded source revision or freshness evidence with the current checkout.
3. If the graph is usable, query it before doing broad codebase exploration.
4. Treat graph answers as structural evidence, not as proof beyond their recorded source
   files and revision.
5. If the graph is absent or stale, report that fact and offer the descriptor's refresh
   procedure. Do not rebuild automatically unless the user requested it.

### Installation

Model setup may report whether the Graphify CLI and runtime skill are available and may
offer an explicit installation command. It must not install Graphify, create
`WIP/GRAPHIFY/`, register projects, or generate graphs by default. Runtime skill linking
and package installation remain separate from vault and project activation.

## Source ingestion

Source ingestion is an optional capability that checks external sources (a task tracker,
a messaging tool, a git server, a calendar, a knowledge base, a document store, and
similar — never a hardcoded vendor) for what changed since the last check, without the
user asking each time.

### Vault layout

When a vault opts in, use these Obsidian-safe names by convention:

```text
WIP/
└── SOURCES/
    ├── sources.registry.md
    └── sources.<source-slug>.md
```

- `sources.registry.md` is the compact source-to-descriptor index.
- `sources.<source-slug>.md` describes one source: its type, what to look for, its
  check cadence, and the script-owned watermark (`Last checked:`).
- Use one descriptor per source, not one per account or per channel within a source.

Use the common templates in `TEMPLATES/TEMPLATE.source-registry.common.md` and
`TEMPLATES/TEMPLATE.source-descriptor.common.md` when creating these notes.

### Source types

`SOURCE_TYPES/SOURCE_TYPES.common.md` is a compact index of source types (messaging tool,
email, task tracker, knowledge base, documents and their comments, review-request
traceability, and similar). Each descriptor names its type; deep-read the matching
`SOURCE_TYPES/<type>.common.md` guide before investigating a source of that type. A type
without a written guide yet is not investigated until one exists — do not improvise.

### Due-ness and the watermark

- `skills/brain/scripts/source_scheduler.py` decides deterministically, from each
  descriptor's `Last checked:` field and cadence, whether a source is due. The agent never
  guesses this.
- A descriptor may set `Check cadence (days): always` instead of a number. This is for
  source types that are inherently time-sensitive per session rather than "changed since
  last check" (a calendar is the reference case — see `SOURCE_TYPES/calendar.common.md`):
  such a source is always due, every session, regardless of `Last checked`.
- `session_open.py`'s digest surfaces only sources that are actually due, quiet otherwise.
- After investigating a due source, update its watermark with
  `source_scheduler.py mark-checked` — never edit `Last checked:` by hand.

### Investigation behavior

For each source the digest lists as due:

1. Spawn one subagent per source using the runtime's subagent mechanism when available and
   permitted by the active instructions; otherwise investigate sequentially in the parent.
2. Each subagent reads that source's descriptor and matching `SOURCE_TYPES/` guide for what
   to look for, and reports back only if something is genuinely relevant — never a false
   "nothing happened" account, and never noise for its own sake.
3. Raw capture lands in `INBOX/sources/<source-slug>/<date>.md`, one file per source per
   day — a central, not-yet-classified capture area, not a durable record. Triage into
   `WIP/`, `BACKLOG/`, or `MEMORY/` happens later, on request (`/brain revisar fuentes`) or
   during ordinary session work.
4. A subagent's failure (timeout, missing permission, error) is logged as a one-line note
   and skipped — it never blocks the rest of the sources or the session start.

### Installation

Model setup must not enable a source, install a tool, or generate capture files by
default. Activation is explicit per project, following the general rule above.
