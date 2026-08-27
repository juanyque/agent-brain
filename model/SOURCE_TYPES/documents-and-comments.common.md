# Documents and their comments
<!-- content-boundary: {"kind":"source-type","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

## What this covers

A hosted document (a shared doc, spec, or design) together with its existing comment
threads. Vendor-agnostic: this guide applies regardless of which specific document platform
the brain's environment profile resolves the source's capability to (Google Docs is a common
example, not the only one; the descriptor itself never names a provider — see "Access" in
`RULES-OPTIONAL-CAPABILITIES.common.md`).

This is a deliberately narrower job than a general "review this document" skill: the
periodic-ingestion loop below covers **verification and freshness** only. Purpose-fit or
generative feedback ("does this document even serve its audience", "here's a new section it
should have") is a distinct, human-in-the-loop extension — see "Generative feedback" below —
and does not belong in an unattended check.

## What to look for

- The document's revision identifier and a content hash of the last-seen snapshot, not just
  a timestamp — staleness is verified by comparing revisions/hashes against the live
  document, never assumed from "it's probably still current."
- Existing unresolved comment threads, including ones that were reopened or pushed back on.
- Any claim in the document that references external ground truth (code, data, another
  document) should be checked against that ground truth directly — never accept the
  document's or a commenter's framing without checking.
- A reopened or pushed-back comment deserves an adversarial check: verify the pushback
  against ground truth before accepting it, and report "confirmed" / "partially confirmed" /
  "not confirmed" rather than simply agreeing.

## How to summarize

- Use an explicit keep/merge/drop rubric for candidate findings, with a short recorded
  reason for anything dropped — never silently discard a finding with no trace of why.
- Genuinely relevant: a verification finding survives the freshness re-check and the
  ground-truth check.
- Quiet `no_activity`: checked, nothing changed since the last snapshot, no unresolved
  threads worth a finding.

## Generative feedback (human-in-the-loop extension, not part of the unattended loop)

A real-world motivation for splitting this out: on at least one occasion, verification
feedback landed cleanly as document comments, but purpose-fit and generative feedback
("this document should also cover X") leaked into a chat channel and working notes instead
of the document — exactly the gap this split is meant to close, by giving that kind of
feedback a document-native home. Because it requires judgment calls about audience and
scope, this half always needs an explicit dialogue with the user before drafting anything,
and is triggered on request, not on every check.

## Failure signals

- A "list existing comments" capability can be unreliable or platform-blocked even when it
  looks supported (e.g. only readable through a workaround that can't see *resolved*
  threads) — verify it actually works and report the limitation rather than presenting
  partial comment coverage as complete.
- Authentication expired, access revoked, or the document is unreachable → `degraded`, with
  a one-line reason. Never silently downgrade this to `no_activity`.

## Publishing

Never publish a comment or edit directly. The strongest form of this guarantee is removing
the write capability entirely rather than relying on a prose instruction not to use it — the
subagent produces a draft file for the human to review and paste in themselves.
