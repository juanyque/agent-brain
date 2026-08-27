---
tags: [wip, source-ingestion]
---
<!-- content-boundary: {"kind":"optional-capability","capability":"source-ingestion","startup":"excluded"} -->
<!-- content-boundary: {"kind":"template","template_id":"source-registry","rules":["model/RULES-OPTIONAL-CAPABILITIES.common.md"],"lifecycle_policy":false} -->
# Source registry

## Purpose

This registry lists only sources that the user explicitly enabled for source ingestion in
this vault. `WIP/WIP.md` remains the activation and discovery surface.

## Sources

### <source-slug>

- Status: enabled
- Type: <source-type, matching a `SOURCE_TYPES/<type>.common.md` guide>
- Repository root matcher: `<canonical-project-root>`
- Descriptor: `[[sources.<source-slug>]]`
- Purpose: <one sentence on why this source is worth checking automatically>

## Operating rules

- Match canonical repository roots exactly before loading a descriptor.
- Load only the descriptor for the current project.
- Do not treat tool installation or account access as source opt-in.
- Keep raw per-source capture in `INBOX/sources/<source-slug>/`, never in this registry.
