# SOURCE_TYPES
<!-- content-boundary: {"kind":"source-index","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

How-to-investigate guides for kinds of external source, used by source ingestion
(`RULES-OPTIONAL-CAPABILITIES.common.md` → "Source ingestion"). When a source descriptor
names a type below, deep-read the corresponding guide before investigating that source.

## Contract

`SOURCE_TYPES/` holds investigation guides organized by kind of external source (messaging
tool, task tracker, ...), never by vendor name. A guide describes what a subagent
investigating a source of that type should look for and how to summarize it — never how to
authenticate or which specific product to use. A source's own descriptor names only the
generic capability it needs and what to read within it (`RULES-OPTIONAL-CAPABILITIES.common.md`
→ "Access"); the concrete tool and endpoint live in the brain's environment profile,
resolved through that capability.

## Index

The index is intentionally compact: one line per source type, with a short description and
a wikilink to the guide, or a note that the guide does not exist yet.

## Guide shape

For a model maintainer adding a new type: each `model/SOURCE_TYPES/<type>.common.md` file
should include (a brain consumer never reads this path directly -- it reads the generated
local wrapper, `SOURCE_TYPES/<type>.md`):

- **What this covers** — the kind of source, in vendor-agnostic terms.
- **What to look for** — the concrete signals worth surfacing (e.g. "unclosed items
  assigned to the user"), and what to deliberately ignore.
- **How to summarize** — what makes a finding "genuinely relevant" enough to surface,
  versus quiet `no_activity`.
- **Failure signals** — what an unreachable or unauthenticated source looks like for this
  type, so it is reported as `degraded`, never a false `no_activity`.

## Entries

- [[messaging-tool]] — Channel- or thread-based messaging tools (chat platforms).
- [[task-tracker]] — Systems that track work items with a lifecycle, assignment, and
  dependency relationships (task trackers, issue trackers).
- [[email]] — A mailbox that can be searched and read via the runtime's available access.
- [[documents-and-comments]] — A hosted document together with its existing comment
  threads; verification/freshness only, generative feedback is a separate human-in-the-loop
  extension.
- [[knowledge-base]] — A knowledge-base entry addressed by a URL; same investigation shape
  as documents-and-comments.
- [[calendar]] — A personal or shared calendar. Special: always due every session, not
  checked for staleness like the other types.
- review-requests — not yet written.
