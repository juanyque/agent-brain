from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Protocol, TypeVar, override

import yaml
from clause_selection import DocumentData
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    TypeAdapter,
    ValidationError,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_JSON_VALUE_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class _FrozenModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class SelectionRequestFile(_FrozenModel):
    request_version: str
    project_type: Path
    data: Path
    document: str


class JurisdictionReference(_FrozenModel):
    status: str
    layer: Path
    sources: Path
    legal_source_snapshot: Path


class DocumentDefinition(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    status: str
    template: Path | None = None


class ProjectTypeManifest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    data_schema: Path
    clause_catalog: Path
    defaults_profiles: dict[str, Path] = Field(default_factory=dict)
    jurisdictions: dict[str, JurisdictionReference]
    documents: dict[str, DocumentDefinition]


class ProjectMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    jurisdiction: str
    data_revision: str
    defaults_profile: str | None = None


class ProjectEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    project: ProjectMetadata


class GenerationCheck(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    id: str
    status: str
    source_refs: tuple[str, ...] = ()


class JurisdictionLayer(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    id: str
    version: str
    generation_checks: tuple[GenerationCheck, ...]

    @property
    def versioned_id(self) -> str:
        return f"{self.id}@{self.version}"


class JsonSchema(RootModel[dict[str, JsonValue]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class _JsonSchemaIssue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    json_path: str
    message: str


class _YamlLoader(yaml.SafeLoader):
    pass


class _SchemaValidator(Protocol):
    def validate(self, instance: JsonValue) -> None: ...


def _validate_schema(validator: _SchemaValidator, instance: JsonValue) -> None:
    validator.validate(instance)


def _construct_timestamp_as_text(
    loader: _YamlLoader,
    node: yaml.nodes.ScalarNode,
) -> str:
    return loader.construct_scalar(node)


_ = _YamlLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    _construct_timestamp_as_text,
)


class SelectionProjectError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class InputError(SelectionProjectError):
    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot read {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class SchemaValidationError(SelectionProjectError):
    instance_path: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"data does not match schema at {self.instance_path}: {self.reason}"


def load_yaml(path: Path, model: type[_ModelT]) -> _ModelT:
    """Parse JSON-compatible YAML into a typed boundary model."""
    try:
        raw = _JSON_VALUE_ADAPTER.validate_python(
            yaml.load(
                path.read_text(encoding="utf-8"),
                Loader=_YamlLoader,
            ),
        )
        return model.model_validate(raw)
    except (OSError, ValidationError, yaml.YAMLError) as error:
        raise InputError(path=path, reason=str(error)) from None


def resolve(path: Path, base: Path) -> Path:
    """Resolve a manifest-relative path."""
    if path.is_absolute():
        return path
    return (base / path).resolve()


def digest(path: Path) -> str:
    """Calculate an input artifact digest."""
    return sha256(path.read_bytes()).hexdigest()


def load_schema(path: Path) -> JsonSchema:
    """Parse and verify a JSON Schema boundary."""
    try:
        schema = JsonSchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
        Draft202012Validator.check_schema(schema.root)
    except (OSError, json.JSONDecodeError, SchemaError, ValidationError) as error:
        raise InputError(path=path, reason=str(error)) from None
    return schema


def validate_data(data: DocumentData, schema: JsonSchema) -> None:
    """Reject project data that does not satisfy its package schema."""
    try:
        _validate_schema(Draft202012Validator(schema.root), data.root)
    except JsonSchemaValidationError as candidate:
        error = _JsonSchemaIssue.model_validate(candidate, from_attributes=True)
        raise SchemaValidationError(
            instance_path=error.json_path,
            reason=error.message,
        ) from None
