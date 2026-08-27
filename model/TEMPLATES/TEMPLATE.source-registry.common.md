---
tags: [wip, source-ingestion]
---
<!-- content-boundary: {"kind":"optional-capability","capability":"source-ingestion","startup":"excluded"} -->
<!-- content-boundary: {"kind":"template","template_id":"source-registry","rules":["model/RULES-OPTIONAL-CAPABILITIES.common.md"],"lifecycle_policy":false} -->
# Source registry

## Purpose

This registry lists only sources that the user explicitly enabled for source ingestion in
this vault. `WIP/WIP.md` remains the activation and discovery surface. Source ingestion is
brain-scoped: every enabled source below is evaluated every session, regardless of which
project the session opens in.

## Sources

### <source-slug>

- Status: enabled
- Type: <source-type, matching a `SOURCE_TYPES/<type>.md` guide>
- Descriptor: `[[sources.<source-slug>]]`
- Purpose: <one sentence on why this source is worth checking automatically>

## Operating rules

- Load only the descriptor a registry entry names, never every note under `WIP/SOURCES/`.
- Do not treat tool installation or account access as source opt-in.
- Keep raw per-source capture in `INBOX/sources/<source-slug>/`, never in this registry.
