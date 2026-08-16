from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

import yaml
from clause_selection import (
    ClauseCatalog,
    ClauseSelection,
    DocumentData,
    Implementation,
    Provenance,
    SelectionInputs,
    select_clauses,
)
from project_defaults import DefaultsResolution, resolve_project_data
from selection_inputs import (
    JurisdictionLayer,
    ProjectEnvelope,
    ProjectTypeManifest,
    SelectionProjectError,
    SelectionRequestFile,
    digest,
    load_schema,
    load_yaml,
    resolve,
    validate_data,
)


@dataclass(frozen=True, slots=True)
class UnknownJurisdictionError(SelectionProjectError):
    jurisdiction: str

    @override
    def __str__(self) -> str:
        return f"project type does not declare jurisdiction: {self.jurisdiction}"


@dataclass(frozen=True, slots=True)
class UnknownTemplateError(SelectionProjectError):
    template: Path

    @override
    def __str__(self) -> str:
        return f"project type does not declare template: {self.template}"


@dataclass(frozen=True, slots=True)
class FragmentPathError(SelectionProjectError):
    clause: str
    fragment: Path | None

    @override
    def __str__(self) -> str:
        return f"candidate fragment is invalid for {self.clause}: {self.fragment}"


@dataclass(frozen=True, slots=True)
class SelectionBuildRequest:
    manifest: Path
    data: Path
    document: str


@dataclass(frozen=True, slots=True)
class PreparedSelection:
    data: DocumentData
    catalog: ClauseCatalog
    catalog_path: Path
    selection: ClauseSelection
    defaults: DefaultsResolution | None = None


def request_from_file(path: Path) -> SelectionBuildRequest:
    """Resolve a selection request file into absolute build inputs."""
    request = load_yaml(path, SelectionRequestFile)
    return SelectionBuildRequest(
        manifest=resolve(request.project_type, path.parent),
        data=resolve(request.data, path.parent),
        document=request.document,
    )


def request_for_template(
    manifest_path: Path,
    data_path: Path,
    template_path: Path,
) -> SelectionBuildRequest:
    """Resolve the declared document family for a package template."""
    manifest = load_yaml(manifest_path, ProjectTypeManifest)
    package = manifest_path.parent
    template = template_path.resolve()
    for document, definition in manifest.documents.items():
        if definition.template is None:
            continue
        if resolve(definition.template, package) == template:
            return SelectionBuildRequest(
                manifest=manifest_path.resolve(),
                data=data_path.resolve(),
                document=document,
            )
    raise UnknownTemplateError(template=template_path)


def build_selection(request: SelectionBuildRequest) -> PreparedSelection:
    """Validate project inputs and calculate their clause selection."""
    manifest = load_yaml(request.manifest, ProjectTypeManifest)
    resolved_data = resolve_project_data(
        request.manifest,
        request.data,
        document=request.document,
    )
    data = resolved_data.data

    project = ProjectEnvelope.model_validate(data.root).project

    try:
        jurisdiction_reference = manifest.jurisdictions[project.jurisdiction]
    except KeyError:
        raise UnknownJurisdictionError(jurisdiction=project.jurisdiction) from None

    package = request.manifest.parent
    schema_path = resolve(manifest.data_schema, package)
    catalog_path = resolve(manifest.clause_catalog, package)
    jurisdiction_path = resolve(jurisdiction_reference.layer, package)
    sources_path = resolve(jurisdiction_reference.sources, package)
    snapshot_path = resolve(jurisdiction_reference.legal_source_snapshot, package)
    schema = load_schema(schema_path)
    validate_data(data, schema)
    catalog = load_yaml(catalog_path, ClauseCatalog)
    jurisdiction = load_yaml(jurisdiction_path, JurisdictionLayer)
    selection = select_clauses(
        SelectionInputs(
            data=data,
            catalog=catalog,
            document=request.document,
            jurisdiction=jurisdiction.versioned_id,
            data_revision=project.data_revision,
            generation_checks=tuple(
                check.id for check in jurisdiction.generation_checks
            ),
            provenance=Provenance(
                data_sha256=digest(request.data),
                schema_sha256=digest(schema_path),
                catalog_sha256=digest(catalog_path),
                jurisdiction_sha256=digest(jurisdiction_path),
                sources_sha256=digest(sources_path),
                legal_source_snapshot_sha256=digest(snapshot_path),
            ),
        ),
    )
    return PreparedSelection(
        data=data,
        catalog=catalog,
        catalog_path=catalog_path,
        selection=selection,
        defaults=resolved_data.defaults,
    )


def candidate_fragment_paths(
    prepared: PreparedSelection,
    template_directory: Path,
) -> tuple[str, ...]:
    """Return package-relative Jinja paths for renderable candidates."""
    candidates = frozenset(prepared.selection.candidate_clauses)
    fragments: list[str] = []
    template_root = template_directory.resolve()
    for clause in prepared.catalog.clauses:
        if (
            clause.versioned_id not in candidates
            or clause.implementation is not Implementation.FRAGMENT_READY
        ):
            continue
        if clause.fragment is None:
            raise FragmentPathError(clause=clause.versioned_id, fragment=None)
        fragment = (prepared.catalog_path.parent / clause.fragment).resolve()
        try:
            fragments.append(fragment.relative_to(template_root).as_posix())
        except ValueError:
            raise FragmentPathError(
                clause=clause.versioned_id,
                fragment=fragment,
            ) from None
    return tuple(fragments)


def selection_yaml(selection: ClauseSelection) -> str:
    """Serialize a selection reproducibly for sidecar storage."""
    return yaml.safe_dump(
        selection.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )
