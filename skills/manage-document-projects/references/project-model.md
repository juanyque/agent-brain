# Project model

## Layers

Keep four layers distinct:

1. Engine: validation, rendering, conversion, verification, and provenance.
2. Project type: data schema, workflow, document family, and clause catalog.
3. Jurisdiction: applicable sources, scope, effective dates, and overrides.
4. Instance: parties, property or subject, operations, evidence, and history.

## Minimum instance contract

Create a PII-free `project.yaml` before materializing operation data. Validate
it against `assets/schemas/project-descriptor.schema.json`. The descriptor
declares:

```yaml
descriptor_version: "0.2.0"
project:
  id: stable-project-id
  status: planning
  property_ref: opaque-property-id
package:
  id: residential-lease
  version: "0.2.0"
  jurisdiction: es-md-madrid
  effective_date_policy: resolve-at-operation
governance:
  data_classification: restricted
  personal_data_location: secure-store-only
  signed_documents: immutable-revisions
  private_keys: external-to-project
references:
  workspace_ref: workspace://projects/stable-project-id
data_store:
  status: unselected
  store_id: stable-project-id-secure
activation_gate:
  status: blocked
  real_data_allowed: false
  checks:
    data_store_location: pending
    access_policy: pending
    backup: pending
    recovery_test: pending
    retention_matrix: pending
```

The descriptor accepts no names, identity numbers, bank accounts, contact
details, signatures, credentials, or filesystem paths. Keep those values in
the referenced project-data file. `data_store.status` may be `prototype` for
an explicitly accepted personal plaintext workflow in a private brain,
`selected` while a hardened backend is being chosen, or `configured` after
that backend has its credential-free locator and controls.

A prototype gate may allow real data after recording
`plaintext-personal-private-repository`; it still exposes pending backup,
recovery, retention, or hardening work. A ready gate requires every check to
be `passed`. Keep instance data, source documents, templates, and generated
outputs in separate directories. Generated documents must record the
input-data revision, template version, output profile, and generation
timestamp.

Keep each concrete Markdown document in the project instance and write
printable or shareable derivatives to the configured deliverables location.
Treat that directory as one-way egress. A document that returns from an
external workflow must enter through the configured incoming location and be
ingested normally; never promote or ingest it from deliverables.

## Project-type package contract

Keep reusable package assets below `assets/project-types/<type-id>/`:

```text
project-type.yaml
defaults/<profile-id>.yaml
schemas/project-data.schema.json
examples/minimal-project.yaml
examples/minimal-clause-selection.yaml
examples/minimal-clause-selection-request.yaml
examples/synthetic-clause-review-request.yaml
examples/synthetic-jurisdiction-check-request.yaml
clauses/catalog.yaml
jurisdictions/<jurisdiction-id>/jurisdiction.yaml
jurisdictions/<jurisdiction-id>/sources.yaml
templates/<document-type>.md.j2
templates/clauses/<document-type>/<clause-id>.md.j2
templates/partials/<shared-fragment>.md.j2
jurisdictions/<jurisdiction-id>/legal-sources/static-sources.tsv
jurisdictions/<jurisdiction-id>/legal-sources/snapshots/YYYY-MM-DD/
reviews/<document-id>-review.yaml
reviews/<document-id>-approval.yaml
reviews/<document-id>-approval.sig
reviews/<document-id>-approval-ledger.yaml
reviews/<document-id>-approval-ledger.sig
reviews/<document-id>-checks-request.yaml
reviews/<document-id>-checks.yaml
releases/<document-id>-release.yaml
```

The manifest declares package and manifest versions, supported document
families, defaults profiles, lifecycle states, jurisdictions, output profiles,
and governance status. Each available document links its Jinja template from
the manifest. All referenced defaults, schema, example, template, and
output-profile files must exist.

### Defaults and instance overrides

Defaults are versioned package inputs, not copied instance data. The instance
opts in through `project.defaults_profile`. The engine merges, in order:

1. `defaults/<profile-id>.yaml` from the skill;
2. `defaults.override.yaml` beside the project-data file, when present;
3. the project-data file.

Derived values such as a one-month deposit, a one-month additional guarantee,
annual-period dates, and first-rent proration are calculated after this merge.
The resolver uses `Decimal` and `ROUND_HALF_UP` for money. The local override
remains project-owned, is never discovered or overwritten by skill setup, and
is hashed into generated-document provenance.

Use JSON Schema Draft 2020-12 for instance data. Reject unknown fields so a
schema-version change is explicit. Keep legal prose in a versioned clause
catalog rather than accepting arbitrary clause text as project data.

## Clause catalog and jurisdiction layers

Give every clause a stable ID and an independent version. Record its document
family, applicability, required data, implementation state, fragment path, and
legal source references. `fragment-ready` means only that Jinja can render the
fragment; it does not mean that the wording has passed legal review.

Keep facts that select wording out of clause prose. A conditional clause must
list the facts needed to select it. Mark it `blocked-missing-data` when the
instance schema cannot yet supply those facts.

Each jurisdiction layer records:

- official sources and the date they were consulted;
- the dated snapshot manifest used for static legal texts;
- generation-time checks such as effective date, landlord capacity, market
  tension status, rent-update regime, and administrative filing;
- jurisdiction-specific overrides, if any;
- `pending-legal-review` until a qualified review approves exact versions.

Use a clause-selection artifact to record candidate and blocked clause
versions. An empty `approved_clause_versions` list means the result is not
ready for signature.

Run the deterministic selector from a request that references the
project-type manifest, data file, and document family. It validates the data
schema first, evaluates catalog applicability, and records:

- candidates whose applicability and required paths are resolved;
- clauses blocked by missing data or professional legal review;
- clauses made non-applicable by an explicit fact;
- hashes of every input that can change the decision.

Package rendering uses the same selection builder. It maps candidate versions
to `fragment-ready` catalog entries in catalog order, supplies those paths to
Jinja, and writes the exact selection as a sibling `.selection.yaml` artifact.
Blocked clauses, non-applicable clauses, and candidate entries without a
renderable fragment do not enter the document.

### Approval and release boundary

Keep review decisions outside project data and templates. The review request
identifies the reviewer and lists exact approved and excluded versions.
`approve_clauses.py` recalculates the selection and emits an approval artifact
bound to the catalog, jurisdiction, and static legal-source snapshot hashes.
It rejects incomplete decisions and any clause still blocked by missing data.

Keep dynamic conclusions in a separate jurisdiction-resolution artifact.
`resolve_jurisdiction_checks.py` requires all checks in jurisdiction order,
consults the declared `resolve-live` sources, records response metadata and
hashes, and binds the result to the data, jurisdiction, and source-registry
hashes. The operator supplies the conclusion code. Source availability never
implies a conclusion.

Draft rendering remains available through the three-path renderer.
`release_document.py` uses a release request and refuses publication unless:

- the approval and current-ledger signatures verify against the declared
  `allowed_signers` trust file;
- the approval is active in the signed ledger on the release date;
- approved versions exactly equal the current candidates;
- legal-review blockers exactly equal the justified exclusions;
- no missing-data blockers remain;
- all generation checks are present and passed;
- all approval and resolution hashes match current inputs;
- the release date falls within the resolution validity interval.

The resulting `reviewed-for-signature` status expresses that this mechanical
gate passed and that trusted keys signed the exact approval and status ledger.
It is not proof of professional qualification, legal correctness, consent,
signature of the contract, or document execution.

Every generated PDF receives a separate `.provenance.yaml` sidecar. It records
the generation timestamp, exact template and data paths and hashes, selection
hash, output-profile identifier and hash, Markdown and PDF hashes, and hashes
of every governed-release artifact.

The approval ledger is an offline revocation snapshot. Each revision binds the
previous ledger hash and has a short validity interval. It can represent active,
withdrawn, and superseded approvals, but it cannot prevent deliberate replay of
an older still-valid signed revision without an online transparency or
revocation service.

The bundled review and check requests are synthetic QA fixtures. Their reviewer,
credential, exclusions, and outcome codes are deliberately non-professional
and must never be reused as a real approval or legal conclusion.

Keep draft policy blocks optional at the outer lease level so incomplete
project data remains representable and its blockers can be reported. Once a
policy block is present, require its internal facts and reject inconsistent
variants. For example, a disabled rent update carries no index, while an
enabled update requires an explicit reference index.

## Legal source preservation

Separate static legal text from values and services that change at use time.

For static sources, retain an append-only dated snapshot with:

- the exact official response in its original HTML or PDF format;
- a diffable Markdown normalization;
- official and resolved URLs;
- retrieval timestamp, media type, and SHA-256 hashes;
- a manifest that maps stable source IDs to both artifacts.

Never overwrite a dated snapshot. A later review takes a new snapshot and
records which manifest it used. A snapshot proves what text was consulted; it
does not make the wording legally approved and does not replace checking the
currently applicable consolidated text.

Keep indexes, declarations, calculators, property-specific reference systems,
and administrative procedures as `resolve-live` sources. Record the value,
query facts, response date, and official endpoint in the generated-document
provenance when one of those sources affects a clause.

When rendering a package template, the renderer walks from the template
directory to the closest `project-type.yaml`, resolves `data_schema` relative
to that manifest, checks the schema, computes the clause selection, and
validates the YAML data before executing Jinja. It preserves the selection
beside the Markdown and PDF outputs. Templates outside a project-type package
retain standalone rendering without implicit schema discovery.

Validate a package before use:

```bash
uvx check-jsonschema --check-metaschema \
  assets/project-types/residential-lease/schemas/project-data.schema.json

uvx check-jsonschema \
  --schemafile assets/project-types/residential-lease/schemas/project-data.schema.json \
  assets/project-types/residential-lease/examples/minimal-project.yaml
```

The bundled `residential-lease` 0.2 package is a draft data contract. Its
synthetic example intentionally uses conspicuous fake names, identity numbers,
IBAN, address, dates, amounts, rooms, keys, and meter readings. A
jurisdiction marked `pending-legal-review` must not be presented as legally
approved.

## Document lifecycle

Use explicit states:

```text
draft -> reviewed -> approved -> signed -> superseded
```

Never regenerate over `signed` or `superseded` evidence. Produce a new derived
artifact and retain the relationship to the prior document.

Use stable filenames for revisions of the same draft and let Git preserve
their history. A new signed agreement, addendum, or superseding legal act is a
new document identity, not a `_v2` filename.

## Sensitive data

Define storage, encryption, version-control, backup, retention, and access
rules before adding personal identifiers, bank accounts, signatures, or signed
documents.
