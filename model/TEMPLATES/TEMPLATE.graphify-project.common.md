---
tags: [wip, graphify]
---
# Graphify: <project-or-graph>

## Summary

- Project key: `<project-key>`
- Status: planned
- Purpose: <questions and relationships this graph should help answer>
- Repository root: `<canonical-project-root>`

Allowed status values: `planned`, `building`, `ready`, `stale`, `disabled`, `failed`.

## Corpus

### Included roots

- `<project-relative-root>`

### Exclusions

- <generated, vendored, cached, binary, or sensitive paths>

Explain why several roots share one graph when cross-root imports or dependencies are
material to the intended queries.

## External storage

- Graph directory: `<absolute-external-directory>`
- Graph file: `<absolute-external-directory>/graphify-out/graph.json`
- Report: `<absolute-external-directory>/graphify-out/GRAPH_REPORT.md`

## Freshness

- Graphify version: not generated
- Generated at: not generated
- Source revision: not generated
- Working tree state: not recorded
- Last verified: not verified

## Operation

- Query: `graphify query "<question>" --graph "<absolute-graph-file>"`
- Refresh: `<explicit reviewed refresh command>`
- Health check: `graphify diagnose multigraph --graph "<absolute-graph-file>"`

Never execute placeholder commands. A refresh must preserve the storage boundary and must
not create Graphify artifacts inside the project or vault.

## Current findings

- None yet.

## Next step

- <smallest useful action>
