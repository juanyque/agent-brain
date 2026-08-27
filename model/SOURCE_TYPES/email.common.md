# Email
<!-- content-boundary: {"kind":"task-index-entry","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

## What this covers

A mailbox (personal or shared inbox) that can be searched and read via the runtime's
available access (an MCP server, a CLI, or similar). Vendor-agnostic: this guide applies
regardless of which specific mailbox provider a project's descriptor names.

## What to look for

- Recent messages, messages addressed directly to the user, and a dedicated search for
  urgent/actionable subjects covering a wide window (weeks, not just the newest handful) —
  urgency doesn't cluster only at the top of the inbox.
- The full thread of a conversation, not just one message in it — this is the only reliable
  way to tell whether a promised reply was actually sent or is still a draft.
- After the first full scan, later checks search only for what's new since the last check,
  but carry forward anything still open from earlier checks — open items accumulate, they
  don't reset with each pass.
- Total mailbox volume as scale context, to make explicit that a check is a targeted sample,
  not an exhaustive historical audit.

## How to summarize

- Infer "urgent/actionable" from a combination of content, recipients, and deadline dates —
  never from a single metadata flag (the provider's own "important"/"unread" markers are a
  partial signal, not the source of truth).
- A thread with a committed reply counts as closed only once the full thread confirms it was
  actually sent — while that can't be confirmed, keep treating it as open.
- An incremental check that finds no new actionable messages is a valid, quiet `no_activity`
  only if the search genuinely covered the date range since the last check. If the window
  covered was narrower than that, say so — it's a partial check, not "nothing happened."
- Don't re-read the whole history on every incremental check once a baseline snapshot
  exists — that's avoidable, redundant cost.

## Failure signals

- **Hard read-only guarantee**: never archive, label, mark-as-read, or delete during
  investigation. Any future write automation (drafting a reply, applying a label) needs
  separate testing and explicit, conservative agreement before it's ever turned on.
- If email is one of several sources feeding a combined view and it's unavailable at check
  time, the aggregator must report partial coverage explicitly rather than silently omitting
  it or failing the whole check.
- Authentication expired or the access method is unreachable → `degraded`, with a one-line
  reason. Never silently downgrade this to `no_activity`.
