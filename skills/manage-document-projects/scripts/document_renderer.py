from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import override

from clause_selection import ClauseSelection, DocumentData
from document_provenance import (
    GovernancePaths,
    ProvenanceRequest,
    build_provenance,
    provenance_yaml,
)
from document_publication import PublicationSpec, governed_selection
from document_template import render_markdown
from project_defaults import DefaultsResolution, require_publication_ready
from selection_inputs import SelectionProjectError, load_yaml
from selection_project import (
    PreparedSelection,
    build_selection,
    candidate_fragment_paths,
    request_for_template,
    selection_yaml,
)


@dataclass(frozen=True, slots=True)
class RenderRequest:
    template: Path
    data: Path
    pdf: Path
    publication: PublicationSpec | None = None

    @property
    def markdown(self) -> Path:
        return self.pdf.with_suffix(".md")

    @property
    def selection(self) -> Path:
        return self.pdf.with_suffix(".selection.yaml")

    @property
    def provenance(self) -> Path:
        return self.pdf.with_suffix(".provenance.yaml")


@dataclass(frozen=True, slots=True)
class _RenderInputs:
    data: DocumentData
    selection: ClauseSelection | None
    fragment_paths: tuple[str, ...] = ()
    defaults: DefaultsResolution | None = None


@dataclass(frozen=True, slots=True)
class OutputExistsError(SelectionProjectError):
    path: Path

    @override
    def __str__(self) -> str:
        return f"output already exists: {self.path}"


@dataclass(frozen=True, slots=True)
class PublicationPackageError(SelectionProjectError):
    template: Path

    @override
    def __str__(self) -> str:
        return f"publication requires a project-type package: {self.template}"


def _find_project_manifest(template: Path) -> Path | None:
    for directory in (template.parent, *template.parent.parents):
        manifest = directory / "project-type.yaml"
        if manifest.is_file():
            return manifest
    return None


def _prepare_inputs(request: RenderRequest) -> _RenderInputs:
    manifest_path = _find_project_manifest(request.template)
    if manifest_path is None:
        if request.publication is not None:
            raise PublicationPackageError(template=request.template)
        return _RenderInputs(
            data=load_yaml(request.data, DocumentData),
            selection=None,
        )

    prepared = build_selection(
        request_for_template(
            manifest_path=manifest_path,
            data_path=request.data,
            template_path=request.template,
        ),
    )
    if request.publication is not None:
        require_publication_ready(prepared.data, prepared.selection.document)
    selection = (
        prepared.selection
        if request.publication is None
        else governed_selection(prepared, request.publication)
    )
    governed = PreparedSelection(
        data=prepared.data,
        catalog=prepared.catalog,
        catalog_path=prepared.catalog_path,
        selection=selection,
        defaults=prepared.defaults,
    )
    return _RenderInputs(
        data=prepared.data,
        selection=selection,
        fragment_paths=candidate_fragment_paths(
            governed,
            template_directory=request.template.parent,
        ),
        defaults=prepared.defaults,
    )


def render_document(request: RenderRequest) -> Path | None:
    """Create canonical Markdown, governance sidecar, and CSS-styled PDF."""
    existing = next(
        (
            path
            for path in (
                request.pdf,
                request.markdown,
                request.selection,
                request.provenance,
            )
            if path.exists()
        ),
        None,
    )
    if existing is not None:
        raise OutputExistsError(path=existing)

    inputs = _prepare_inputs(request)
    status = (
        inputs.selection.status
        if inputs.selection is not None
        else "draft-not-for-signature"
    )
    markdown = render_markdown(
        template=request.template,
        data=inputs.data,
        release_status=status,
        fragment_paths=inputs.fragment_paths,
    )
    _ = request.pdf.parent.mkdir(parents=True, exist_ok=True)
    _ = request.markdown.write_text(markdown, encoding="utf-8")
    if inputs.selection is not None:
        _ = request.selection.write_text(
            selection_yaml(inputs.selection),
            encoding="utf-8",
        )

    css = Path(__file__).resolve().parents[1] / "assets/profiles/css-pdf/document.css"
    _ = subprocess.run(
        [
            "pandoc",
            str(request.markdown),
            "--standalone",
            "--from=markdown+raw_html",
            "--to=html5",
            f"--css={css}",
            "--pdf-engine=weasyprint",
            f"--resource-path={request.template.parent}",
            f"--output={request.pdf}",
        ],
        check=True,
    )
    governance_paths = (
        None
        if request.publication is None
        else GovernancePaths(
            approval=request.publication.approval,
            approval_signature=request.publication.approval_signature,
            approval_ledger=request.publication.approval_ledger,
            approval_ledger_signature=request.publication.approval_ledger_signature,
            allowed_signers=request.publication.allowed_signers,
            jurisdiction_checks=request.publication.jurisdiction_checks,
        )
    )
    _ = request.provenance.write_text(
        provenance_yaml(
            build_provenance(
                ProvenanceRequest(
                    template=request.template,
                    data=request.data,
                    selection=(
                        request.selection if inputs.selection is not None else None
                    ),
                    profile=css,
                    markdown=request.markdown,
                    pdf=request.pdf,
                    document_status=status,
                    governance=governance_paths,
                    defaults=inputs.defaults,
                ),
            ),
        ),
        encoding="utf-8",
    )
    return request.selection if inputs.selection is not None else None
