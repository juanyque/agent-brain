# Messaging tool
<!-- content-boundary: {"kind":"source-type","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

## What this covers

Channel- or thread-based messaging tools (chat platforms) where the user participates in
one or more channels, groups, or direct threads. Vendor-agnostic: this guide applies
regardless of which specific tool a source's descriptor names.

## What to look for

- Direct mentions of the user, or messages in a thread the user started or was tagged in.
- Direct messages or group DMs addressed to the user.
- Decisions or direction stated in a channel the descriptor names as relevant — not every
  channel the user happens to be a member of.
- A structured "submission" or "update" format the descriptor may define (a fixed set of
  fields such as what was done / what it achieved / how / links) can arrive through more
  than one path — a bot-posted entry and a manually-submitted one via a shortcut or form
  are the same signal type; treat them as one pattern, not two separate sources, when
  deduplicating.
- Thread reply count and reaction count are a cheap, capture-before-reading proxy for
  relevance or traction — worth recording alongside each entry even before deciding
  whether the thread body itself is worth summarizing.
- Capture the full body of a real entry (author, date, short title, complete text, links),
  not just a title — later triage needs the "how", not only the headline.
- A follow-up housekeeping message (a survey summary, an announcement of a new recurring
  format) can carry a genuine, tangential finding buried in a reply — worth a pass even
  when the parent message itself is administrative.
- Explicitly ignore: reactions/emoji-only messages, bot noise unrelated to the descriptor's
  defined submission format, channels not named in the descriptor.

## How to summarize

- Genuinely relevant: something requires a response, a decision was made that affects
  active work, or a question was asked directly of the user.
- Quiet `no_activity`: the source was reachable and checked, but nothing in the above
  categories occurred since the last check. This is a valid, expected outcome — most
  checks should be quiet.
- Diff new content against **both** the last captured snapshot **and** any downstream
  tracker's existing entries — an item counts as new only if absent from both. Never infer
  "nothing new" from the absence of a diff alone if the read didn't actually reach back to
  the last check date (see Failure signals).
- Membership/system events (joins, name changes) and obvious placeholder or test posts are
  noise, not findings — discard them explicitly rather than letting them pad the summary.
- A parent message that was deleted but survives only through orphaned replies should still
  be captured, flagged as reduced-context rather than presented as a normal, complete entry.

## Failure signals

- Authentication expired, access revoked, or the tool's API/MCP connection is unreachable
  → `degraded`, with a one-line reason. Never silently downgrade this to `no_activity`.
- A named channel or thread no longer exists or is inaccessible → `degraded`, naming which
  one, so config drift is visible rather than silently skipped.
- **Retention windows are the most important failure mode here.** Most messaging tools
  purge history after a fixed window. If a check is late enough that the window no longer
  reaches back to the previous check date, the gap is **permanent, unrecoverable data
  loss** — not merely "delayed work." Record it as an explicit, dated gap (name the exact
  boundary reached), never present it as a clean "no activity" diff.
- Before declaring anything in such a gap lost, try one independent second check (e.g. a
  full-text/global search across the tool, not just the channel's own paged history) — only
  call it unrecoverable once both the normal read and that second check come back empty.
- If the primary access method fails (an API/integration client errors or lacks permission),
  pause and ask the human before silently falling back to an alternate access path (e.g. a
  browser-driven session). An unannounced automatic fallback is not acceptable here.
- A companion surface that looks like a second, independent source but is actually fed by
  the same underlying workflow — and whose backing data isn't reachable through the
  investigating identity's normal access — should be documented as "same source, alternate
  surface," not chased as an extra scrape target.
- When several sources feed one combined view and access to one of them is missing, degrade
  that one source gracefully and report which was skipped — never produce a combined result
  that looks complete when a piece of it silently isn't.
- A known upstream rendering bug on links generated from the tool's own messages (a link
  that shows "not found" instead of its target) should be noted with its fix date, so
  entries captured before that date aren't mistaken for a capture-process error.
