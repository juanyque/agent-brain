# Optional capabilities

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
