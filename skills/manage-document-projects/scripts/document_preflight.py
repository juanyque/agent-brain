from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, override

import yaml
from pydantic import JsonValue
from selection_inputs import ProjectTypeManifest, SelectionProjectError

Resolution = Literal["user-required"]
_DERIVATION_REQUIRED_DATA: Final = ("operation.lease.monthly_rent",)


@dataclass(frozen=True, slots=True)
class MissingDocumentField:
    path: str
    resolution: Resolution = "user-required"


@dataclass(frozen=True, slots=True)
class MissingDocumentDataError(SelectionProjectError):
    document: str
    data: Path
    missing_fields: tuple[MissingDocumentField, ...]

    @override
    def __str__(self) -> str:
        paths = ", ".join(field.path for field in self.missing_fields)
        return f"{self.document} requires project data: {paths}"


@dataclass(frozen=True, slots=True)
class DocumentPreflightRequest:
    root: dict[str, JsonValue]
    document: str
    data_path: Path
    required_paths: tuple[str, ...]


def _is_missing(root: dict[str, JsonValue], path: str) -> bool:
    current: JsonValue = root
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return True
        current = current[segment]
    return (
        current is None
        or current == ""
        or isinstance(current, list)
        and not current
    )


def required_paths(
    manifest: ProjectTypeManifest,
    document: str | None,
) -> tuple[str, ...]:
    return (
        _DERIVATION_REQUIRED_DATA
        if document is None
        else manifest.documents[document].required_data
    )


def require_document_data(request: DocumentPreflightRequest) -> None:
    missing = tuple(
        MissingDocumentField(path=path)
        for path in request.required_paths
        if _is_missing(request.root, path)
    )
    if missing:
        raise MissingDocumentDataError(
            document=request.document,
            data=request.data_path,
            missing_fields=missing,
        )


def missing_data_yaml(error: MissingDocumentDataError) -> str:
    return yaml.safe_dump(
        {
            "report_version": "0.1.0",
            "status": "incomplete",
            "document": error.document,
            "data": str(error.data),
            "missing_fields": [
                {
                    "path": field.path,
                    "resolution": field.resolution,
                }
                for field in error.missing_fields
            ],
            "next_action": "collect-confirmed-values-and-retry",
        },
        allow_unicode=True,
        sort_keys=False,
    )
