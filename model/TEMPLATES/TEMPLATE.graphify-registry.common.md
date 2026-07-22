---
tags: [wip, graphify]
---
# Graphify registry

## Purpose

This registry lists only projects that the user explicitly enabled for Graphify in this
vault. `WIP/WIP.md` remains the activation and discovery surface.

## Projects

### <project-key>

- Status: enabled
- Repository root matcher: `<canonical-project-root>`
- Descriptor: `[[graphify.<project-or-graph>]]`
- Graph purpose: <one sentence explaining why the graph spans this corpus>

## Operating rules

- Match canonical repository roots exactly before loading a descriptor.
- Load only the descriptor for the current project.
- Do not treat CLI installation or directory presence as project opt-in.
- Keep generated graph assets outside the vault and project checkout.
