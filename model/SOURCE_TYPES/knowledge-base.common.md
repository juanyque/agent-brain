# Knowledge base
<!-- content-boundary: {"kind":"source-type","owner":"model/SOURCE_TYPES/SOURCE_TYPES.common.md"} -->

## What this covers

A knowledge-base entry (a wiki page, a database entry, a reference doc) addressed by a URL.
Vendor-agnostic: this guide applies regardless of which specific knowledge-base platform a
source's descriptor names.

## Investigation approach

A knowledge-base entry is managed identically to [[documents-and-comments]] — snapshot and
revision/hash-based staleness detection, existing comments or discussion threads, a
ground-truth verification pass with a keep/merge/drop rubric, and an optional generative
"does this page still serve its purpose" pass as a separate, human-in-the-loop extension.
The only difference is what's linked: a knowledge-base page rather than a hosted document.

Deep-read `SOURCE_TYPES/documents-and-comments.md` for the full detail — what to look for,
how to summarize, failure signals, and the publishing guarantee are all the same.
