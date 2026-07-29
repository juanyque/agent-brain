---
name: manage-document-projects
description: Create and operate governed document projects from structured data and Markdown templates, then publish printable HTML, PDF, DOCX, or ODT outputs. Use when Codex needs to initialize a documentation project, model reusable project types such as residential leases, render Jinja2 templates, configure Pandoc output, preserve formatting profiles, validate document dependencies, or maintain traceability between source data and generated documents.
---

# Manage Document Projects

Manage document families as versioned projects. Keep Markdown and structured
data canonical; treat PDF, DOCX, ODT, and HTML as generated artifacts.

## Start safely

1. Run `bash scripts/doctor.sh`.
2. If required tools are missing, run `bash scripts/setup.sh` and review the
   dry-run.
3. Run `bash scripts/setup.sh --apply` only with explicit authorization to
   install packages and link the skill.
4. Run the doctor again after any toolchain or output-profile change.

Read [references/setup.md](references/setup.md) when installing, repairing, or
moving the skill.

## Build a document project

1. Identify the project instance, project type, jurisdiction, and effective
   date.
2. Separate instance data from reusable templates, clauses, and output
   profiles.
3. Record the project-type and template versions used by every generated
   document.
4. Render Jinja2 variables into canonical Markdown.
5. Reject unresolved variables and invalid data before conversion.
6. Select an output profile using
   [references/output-formats.md](references/output-formats.md).
7. In a brain, keep the concrete Markdown document in its project and place
   printable or shareable derivatives in the brain-root `OUTBOX/`.
   Never ingest from `OUTBOX/` or overwrite signed or externally reviewed
   documents.
8. Open the result in its real viewer and inspect pagination, headings,
   tables, images, signatures, and missing placeholders.

Read [references/project-model.md](references/project-model.md) before creating
or reorganizing a project.

Create a PII-free instance descriptor before adding real project data:

```bash
uvx check-jsonschema \
  --schemafile assets/schemas/project-descriptor.schema.json \
  /path/to/project.yaml
```

Start from `assets/examples/minimal-project-descriptor.yaml`. Keep only opaque
project, property, package, brain, and data-store references in this
descriptor. For an explicitly personal prototype in a private brain, the user
may choose `private-brain-plaintext`: set the gate to `prototype`, record the
risk acceptance, and keep future hardening visible. Use `blocked` until all
required storage decisions exist in other contexts; use `ready` only when
every declared check has passed.

The bundled draft residential package lives at
`assets/project-types/residential-lease/`. Validate its example against its
schema before copying it into a project. Its manifest links the reservation,
lease, inventory, and temporary early-access templates to their data
requirements. Treat its Madrid jurisdiction, early key delivery, and all legal
clauses as pending professional review. Read its `clauses/catalog.yaml` and
selected jurisdiction layer before adapting a contract; do not render clauses
whose required facts remain blocked.

Initialize a brain-local customization file without copying skill defaults:

```bash
uv run scripts/init_document_project.py /path/to/project
uv run scripts/init_document_project.py /path/to/project --apply
```

The command creates `data/defaults.override.yaml` only when explicitly applied
and never overwrites an existing file. A project opts in with
`project.defaults_profile`. Resolution order is the versioned skill profile,
then the sibling brain-local override, then instance data. The provenance
sidecar records the profile and override hashes.

## Preserve legal source snapshots

Keep the exact official text used during a contract review reproducible. For
the bundled Madrid residential package, first review the dry-run and then
create an append-only dated snapshot:

```bash
bash scripts/ingest_legal_sources.sh --date YYYY-MM-DD
bash scripts/ingest_legal_sources.sh --date YYYY-MM-DD --apply
```

The ingestor:

- reads the declared static-source inventory;
- preserves each official HTML or PDF response unchanged;
- isolates the legal body from configured HTML containers or extracts PDF
  text, then writes diffable Markdown;
- records retrieval time, resolved URL, media type, and SHA-256 hashes;
- verifies every preserved original and normalized document;
- refuses to overwrite an existing dated snapshot;
- treats a repeated `--apply` as a verified no-op.

`pdftotext` is required only when the inventory contains a PDF source. The
bundled Madrid inventory uses it for the consolidated regional deposit decree.

Do not snapshot changing values and administrative services as if they were
law. Resolve the current INE rent-update index, the state rental-reference
service, market-tension declarations, and the Madrid filing procedure when
generating or reviewing a document.

## Select clauses deterministically

Create a request that points to a project-type manifest, project data, and a
document family. Then generate the selection artifact:

```bash
uv run scripts/select_clauses.py \
  assets/project-types/residential-lease/examples/minimal-clause-selection-request.yaml \
  generated/clause-selection.yaml
```

The selector validates project data against the package schema before reading
facts. It then emits, in catalog order:

- candidate clause versions;
- blocked clause versions with machine-readable reasons and missing paths;
- non-applicable clause versions;
- required jurisdiction checks;
- SHA-256 hashes of data, schema, catalog, and jurisdiction inputs.

The same input bytes produce the same output bytes. The selector refuses to
overwrite an existing result. `candidate` means that applicability and required
data are resolved; it does not mean that a clause is legally approved or ready
for signature.

When rendering a package template, reuse this selection path rather than
maintaining a second set of Jinja conditions. Render only candidate clauses
whose catalog entry is `fragment-ready`; keep blocked and non-applicable
versions out of the document.

## Approve exact clause versions

A qualified reviewer records one decision for every applicable clause in a
review request. Build the immutable approval artifact from that request:

```bash
uv run scripts/approve_clauses.py \
  reviews/lease-review.yaml \
  reviews/lease-approval.yaml
```

The approver recalculates the selection and rejects missing data, omitted
candidates, unexpected versions, or exclusions that do not match the legal
review blockers. The output binds the reviewer identity, review date, exact
clause versions, catalog, jurisdiction, and static legal snapshot hashes.
The reviewer also declares the OpenSSH signer identity that publication will
look up in an explicit `allowed_signers` trust file.

Codex must not invent a reviewer, professional identifier, approval decision,
or exclusion. The approval file records a professional decision supplied by
the user or reviewer. Sign the immutable approval with a private key held
outside the document project:

```bash
uv run scripts/sign_governance.py \
  reviews/lease-approval.yaml \
  /secure/path/legal-reviewer-key \
  reviews/lease-approval.sig
```

The detached signature proves control of a trusted key. It does not
independently prove the reviewer's professional qualification.

## Activate, withdraw, or supersede an approval

Build an append-only approval-status revision from a typed request, then sign
that exact revision:

```bash
uv run scripts/update_approval_status.py \
  reviews/lease-status-update.yaml \
  reviews/lease-approval-ledger.yaml

uv run scripts/sign_governance.py \
  reviews/lease-approval-ledger.yaml \
  /secure/path/status-authority-key \
  reviews/lease-approval-ledger.sig
```

The first revision activates an approval. Later revisions name the previous
ledger hash and can withdraw it or supersede it with a replacement approval.
Publication accepts only an active approval in a valid signed ledger. Use a
short `valid_until`: this is an offline trust model, so deliberate replay of an
older still-valid signed ledger cannot be detected without an online revocation
or transparency service.

## Resolve generation-time jurisdiction checks

Record the operator's conclusions and the declared live sources in a resolution
request, then capture the official responses:

```bash
uv run scripts/resolve_jurisdiction_checks.py \
  reviews/lease-checks-request.yaml \
  reviews/lease-checks.yaml
```

The resolver requires every jurisdiction check in declared order, fetches each
`resolve-live` official URL, follows redirects, rejects HTTP failures, and
records the final URL, status, consultation time, and response SHA-256. It
binds the result to the project-data, jurisdiction, and source-registry hashes.

The operator remains responsible for `outcome_code`. HTTP availability and a
captured response are evidence of consultation, not proof that the legal
conclusion is correct. Use a short `valid_until` and resolve again when the
release date falls outside that interval.

## Publish a reviewed document

Keep draft rendering separate from publication. A release request points to
the template, data, signed approval, signed current approval ledger,
`allowed_signers` trust file, jurisdiction resolution, and explicit release
date:

```bash
uv run scripts/release_document.py \
  releases/lease-release.yaml \
  /path/to/brain/OUTBOX/project-id/lease-reviewed.pdf \
  --brain-root /path/to/brain
```

Publication fails before writing outputs unless both OpenSSH signatures are
trusted, the approval is active, every candidate version is approved, every
legal-review blocker is explicitly excluded, every generation check is
resolved, all hashes still match, and both time-limited evidence sets are valid
on the release date. A successful selection sidecar has status
`reviewed-for-signature`.

## Render the minimal PDF circuit

Use the bundled renderer after the doctor reports `CSS_PDF=yes`:

```bash
uv run scripts/render_document.py \
  templates/contract.md.j2 \
  data/document.yaml \
  /path/to/brain/OUTBOX/project-id/contract.pdf \
  --brain-root /path/to/brain \
  --markdown-output /path/to/brain/WIP/project-id/documents/contract.md
```

The renderer:

- parses YAML data into JSON-compatible values;
- discovers the closest `project-type.yaml` and validates the data against its
  referenced JSON Schema before rendering;
- calculates the package clause selection and writes
  `generated/contract.selection.yaml` beside package outputs;
- exposes only candidate `fragment-ready` paths to the package template in
  catalog order;
- preserves standalone rendering when the template does not belong to a
  project-type package;
- renders Jinja in a sandbox with strict undefined variables;
- exposes `es_date`, `es_money`, `es_number`, and `es_iban` filters;
- writes the requested persistent Markdown path, or a sibling Markdown
  intermediate when `--markdown-output` is omitted;
- writes a sibling provenance file with timestamp and hashes for the
  template, data, defaults profile, local override, selection, output profile,
  Markdown, PDF, and governed inputs;
- converts that Markdown to an A4 PDF through Pandoc and WeasyPrint;
- uses the bundled CSS profile and resolves images relative to the template;
- refuses to write printable brain outputs outside `OUTBOX/` or into an
  `OUTBOX/` ignored by Git;
- reports whether an existing artifact is committed, modified, untracked,
  ignored, or outside version control;
- replaces the stable output set only with `--replace`, after the user has
  authorized that replacement.

Use stable document names and Git history instead of `_v1`, `_v2`, or similar
suffixes. Run without `--replace` first. If the preflight reports an existing
untracked or modified artifact, ask before rerunning with `--replace`.
Do not add `OUTBOX/` contents to Git automatically. If an externally handled
document returns, ingest it from `INBOX/`, never from `OUTBOX/`.

## Choose the output format

- Use CSS for HTML and HTML-based PDF.
- Use `--reference-doc` for DOCX and ODT styles.
- Use a Pandoc template and engine-specific variables for LaTeX or Typst PDF.
- Prefer the bundled `assets/profiles/css-pdf/document.css` as the starting
  printable profile, then copy it into the project before customization.

Do not claim that one CSS file controls DOCX, ODT, and every PDF engine. The
format-specific mechanisms are intentionally different.

## Guardrails

- Keep personal data outside templates and public examples.
- Keep only conspicuously synthetic identities and accounts in bundled
  fixtures; checksum validation of DNI and IBAN remains a separate semantic
  validation concern.
- Do not commit DNI, IBAN, signatures, or signed documents without an explicit
  storage and access policy.
- Keep legal sources, jurisdiction, consultation date, and affected clauses
  traceable.
- Use a dated, hashed source snapshot for static legal text reviewed by a
  clause or contract.
- Treat `fragment-ready` as a technical state, never as legal approval.
- Treat `selector-ready` as resolved data and applicability metadata, never as
  renderable or legally approved wording.
- Preserve the selection sidecar with every generated package document.
- Preserve approval and jurisdiction-resolution artifacts with every reviewed
  release.
- Do not infer legal approval from a fragment appearing in a draft render.
- Do not infer an operator outcome from an HTTP response or source availability.
- Resolve time-sensitive jurisdiction facts from their official source at
  generation time rather than storing assumptions in the template.
- Present legal content as pending professional review when that review has not
  occurred.
- Preserve originals and signed outputs as immutable evidence.
- Treat brain-root `OUTBOX/` as a one-way delivery queue, never as an
  ingestion source or attachment store.
- Make installation and project mutations dry-run-first.

## Dependencies

| Resource | Read when |
| --- | --- |
| [references/setup.md](references/setup.md) | Installing or diagnosing dependencies |
| [references/project-model.md](references/project-model.md) | Creating a type or project instance |
| [references/output-formats.md](references/output-formats.md) | Selecting or modifying an output profile |
