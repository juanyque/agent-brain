#!/usr/bin/env python3
"""Load, validate, select, and diagnose agent-brain environment profiles.

The implementation is intentionally stdlib-only. It validates the JSON Schema
features used by the version 1 contracts and then applies cross-document
semantic checks that JSON Schema cannot express.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


SHARED_DIR = Path("_AGENTS/SHARED")
SELECTION_FILE = SHARED_DIR / "environment.json"
PROFILES_DIR = SHARED_DIR / "profiles"
PROFILE_ENV = "AGENT_BRAIN_PROFILE"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"
PROFILE_SCHEMA = SCHEMA_DIR / "environment-profile-v1.schema.json"
SELECTION_SCHEMA = SCHEMA_DIR / "profile-selection-v1.schema.json"


class ProfileError(ValueError):
    """Raised when profile configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class ResolvedProfile:
    profile_id: str
    source: str
    path: Path
    document: dict[str, Any]


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: str
    state: str
    required: bool
    detail: str


@dataclass(frozen=True)
class SecretStatus:
    provider_id: str
    kind: str
    name: str
    state: str
    required: bool
    detail: str


@dataclass(frozen=True)
class CapabilityResolution:
    capability: str
    provider_id: str
    kind: str
    service: str
    operation: str | None
    availability: str
    detail: str
    invocation: str | None


@dataclass(frozen=True)
class ToolExposure:
    capability: str
    invocation: str | None
    state: str
    detail: str


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
        )
    except OSError as exc:
        raise ProfileError(f"{path}: cannot read file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"{path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    except ProfileError as exc:
        raise ProfileError(f"{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"{path}: $: expected object")
    return value


def _json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ProfileError(f"unsupported schema reference: {ref}")
    node: Any = root_schema
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def validate_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    """Validate the JSON Schema subset used by the v1 profile contracts."""
    root_schema = root_schema or schema
    if "$ref" in schema:
        return validate_schema(
            value,
            _resolve_ref(root_schema, schema["$ref"]),
            root_schema=root_schema,
            path=path,
        )

    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type and not _json_type_matches(value, expected_type):
        return [f"{path}: expected {expected_type}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']!r}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is shorter than {schema['minLength']}")
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            errors.append(f"{path}: {value!r} does not match {pattern!r}")
        if schema.get("format") == "uri":
            parsed = urlparse(value)
            if not parsed.scheme:
                errors.append(f"{path}: {value!r} is not an absolute URI")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        if schema.get("uniqueItems"):
            seen: set[str] = set()
            for index, item in enumerate(value):
                marker = json.dumps(item, sort_keys=True, separators=(",", ":"))
                if marker in seen:
                    errors.append(f"{path}[{index}]: duplicate item")
                seen.add(marker)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(
                    validate_schema(
                        item,
                        item_schema,
                        root_schema=root_schema,
                        path=f"{path}[{index}]",
                    )
                )

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        if len(value) < schema.get("minProperties", 0):
            errors.append(
                f"{path}: expected at least {schema['minProperties']} properties"
            )
        name_schema = schema.get("propertyNames")
        if name_schema:
            for key in value:
                errors.extend(
                    validate_schema(
                        key,
                        name_schema,
                        root_schema=root_schema,
                        path=f"{path}.<property {key!r}>",
                    )
                )
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in properties:
                errors.extend(
                    validate_schema(
                        item,
                        properties[key],
                        root_schema=root_schema,
                        path=item_path,
                    )
                )
            elif additional is False:
                errors.append(f"{item_path}: unknown property")
            elif isinstance(additional, dict):
                errors.extend(
                    validate_schema(
                        item,
                        additional,
                        root_schema=root_schema,
                        path=item_path,
                    )
                )
    return errors


def _expanded_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve(strict=False)


def _semantic_errors(
    brain_root: Path,
    selection: dict[str, Any],
    profiles: Mapping[str, tuple[Path, dict[str, Any]]],
) -> list[str]:
    errors: list[str] = []
    referenced = {selection.get("default_profile")}
    referenced.update(rule.get("profile") for rule in selection.get("project_rules", []))
    for profile_id in sorted(item for item in referenced if isinstance(item, str)):
        if profile_id not in profiles:
            errors.append(f"selection: unknown profile {profile_id!r}")

    for profile_id, (path, profile) in profiles.items():
        if path.stem != profile_id or profile.get("id") != profile_id:
            errors.append(
                f"{path}: profile id {profile.get('id')!r} must match filename {path.stem!r}"
            )
        providers = profile.get("providers", {})
        for provider_id, provider in providers.items():
            kind = provider.get("kind")
            if kind == "mcp" and not provider.get("server"):
                errors.append(
                    f"{path}: $.providers.{provider_id}.server is required for MCP providers"
                )
            if kind == "cli" and not provider.get("command"):
                errors.append(
                    f"{path}: $.providers.{provider_id}.command is required for CLI providers"
                )
            if kind == "manual" and provider.get("required"):
                errors.append(
                    f"{path}: $.providers.{provider_id}.required must be false for manual providers"
                )
            seen_secrets: set[tuple[str, str]] = set()
            for secret_index, secret in enumerate(provider.get("secret_refs", [])):
                secret_key = (secret["kind"], secret["name"])
                if secret_key in seen_secrets:
                    errors.append(
                        f"{path}: $.providers.{provider_id}.secret_refs[{secret_index}] "
                        f"duplicates {secret['kind']} reference {secret['name']!r}"
                    )
                seen_secrets.add(secret_key)
                if secret["kind"] == "environment" and not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*", secret["name"]
                ):
                    errors.append(
                        f"{path}: $.providers.{provider_id}.secret_refs[{secret_index}].name "
                        "must be a valid environment variable name"
                    )
                if any(character in secret["name"] for character in "\r\n\t\x00"):
                    errors.append(
                        f"{path}: $.providers.{provider_id}.secret_refs[{secret_index}].name "
                        "must not contain control characters"
                    )
        for capability, route in profile.get("capability_routes", {}).items():
            for provider_id in route:
                provider = providers.get(provider_id)
                if provider is None:
                    errors.append(
                        f"{path}: $.capability_routes.{capability}: unknown provider {provider_id!r}"
                    )
                elif provider.get("kind") != "manual" and capability not in provider.get(
                    "operations", {}
                ):
                    errors.append(
                        f"{path}: provider {provider_id!r} does not implement {capability!r}"
                    )
        tracking = profile.get("issue_tracking")
        if tracking:
            if tracking["provider"] not in providers:
                errors.append(f"{path}: $.issue_tracking.provider is unknown")
            default_project = tracking.get("default_project")
            if default_project and default_project not in tracking["project_keys"]:
                errors.append(
                    f"{path}: $.issue_tracking.default_project must be in project_keys"
                )
        overlays = profile.get("runtime_overlays", [])
        for index, overlay in enumerate(overlays):
            raw = overlay["path"]
            candidate = Path(raw)
            if candidate.is_absolute() or ".." in candidate.parts or candidate == Path("."):
                errors.append(
                    f"{path}: $.runtime_overlays[{index}].path must be brain-relative"
                )
                continue
            resolved = (brain_root / candidate).resolve(strict=False)
            try:
                resolved.relative_to(brain_root.resolve())
            except ValueError:
                errors.append(
                    f"{path}: $.runtime_overlays[{index}].path escapes the brain"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"{path}: $.runtime_overlays[{index}].path does not exist: {raw!r}"
                )

            raw_target = overlay["target"]
            target = Path(raw_target)
            if target.is_absolute() or ".." in target.parts or target == Path("."):
                errors.append(
                    f"{path}: $.runtime_overlays[{index}].target must be relative"
                )

        for left_index, left in enumerate(overlays):
            for right_index in range(left_index + 1, len(overlays)):
                right = overlays[right_index]
                same_destination = (
                    left["kind"] == right["kind"]
                    and left["target"] == right["target"]
                )
                overlapping_runtime = (
                    left["runtime"] == right["runtime"]
                    or left["runtime"] == "*"
                    or right["runtime"] == "*"
                )
                if same_destination and overlapping_runtime:
                    errors.append(
                        f"{path}: $.runtime_overlays[{right_index}] duplicates target "
                        f"{right['target']!r} for overlapping runtime selectors"
                    )
    return errors


def load_profile_documents(
    brain_root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[Path, dict[str, Any]]]]:
    selection_path = brain_root / SELECTION_FILE
    profiles_dir = brain_root / PROFILES_DIR
    if not selection_path.is_file():
        raise ProfileError(f"profile selection file not found: {selection_path}")
    if not profiles_dir.is_dir():
        raise ProfileError(f"profiles directory not found: {profiles_dir}")

    selection = load_json(selection_path)
    profiles = {path.stem: (path, load_json(path)) for path in sorted(profiles_dir.glob("*.json"))}
    selection_schema = load_json(SELECTION_SCHEMA)
    profile_schema = load_json(PROFILE_SCHEMA)
    errors = validate_schema(selection, selection_schema)
    for _, (path, profile) in profiles.items():
        errors.extend(f"{path}: {error}" for error in validate_schema(profile, profile_schema))
    errors.extend(_semantic_errors(brain_root, selection, profiles))
    if errors:
        raise ProfileError("invalid environment profiles:\n- " + "\n- ".join(errors))
    return selection, profiles


def resolve_profile(
    brain_root: Path,
    *,
    explicit_profile: str | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ResolvedProfile:
    selection, profiles = load_profile_documents(brain_root)
    environment = environ if environ is not None else os.environ
    requested = explicit_profile or environment.get(PROFILE_ENV)
    source = "explicit --profile" if explicit_profile else f"environment {PROFILE_ENV}"

    if not requested:
        current = (cwd or Path.cwd()).expanduser().resolve(strict=False)
        matches: list[tuple[int, str, str]] = []
        for rule in selection["project_rules"]:
            prefix = _expanded_path(rule["path_prefix"])
            try:
                current.relative_to(prefix)
            except ValueError:
                continue
            matches.append((len(prefix.parts), rule["profile"], rule["path_prefix"]))
        if matches:
            longest = max(length for length, _, _ in matches)
            winners = {(profile, raw) for length, profile, raw in matches if length == longest}
            winner_profiles = {profile for profile, _ in winners}
            if len(winner_profiles) > 1:
                raise ProfileError(f"ambiguous project profile rules for {current}: {sorted(winners)!r}")
            requested, raw = next(iter(winners))
            source = f"project rule {raw}"
        else:
            requested = selection["default_profile"]
            source = "default_profile"

    if requested not in profiles:
        raise ProfileError(f"selected profile does not exist: {requested!r}")
    path, document = profiles[requested]
    return ResolvedProfile(requested, source, path, document)


def provider_statuses(
    profile: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    mcp_servers: Mapping[str, Any] | None = None,
    keychain_check: Callable[[str], tuple[str, str]] | None = None,
    runtime_secret_check: Callable[[str], tuple[str, str]] | None = None,
) -> list[ProviderStatus]:
    environment = environ if environ is not None else os.environ
    statuses: list[ProviderStatus] = []
    secrets = secret_statuses(
        profile,
        environ=environment,
        keychain_check=keychain_check,
        runtime_secret_check=runtime_secret_check,
    )
    for provider_id, provider in profile["providers"].items():
        kind = provider["kind"]
        required = provider["required"]
        if kind == "cli":
            command = provider["command"]
            found = which(command)
            state = "available" if found else "missing"
            detail = found or f"command not found: {command}"
        elif kind == "mcp":
            server = provider["server"]
            if mcp_servers is None:
                state = "adapter-check"
                detail = f"runtime adapter must verify MCP server {server!r}"
            elif server not in mcp_servers:
                state = "missing"
                detail = f"MCP server is not registered: {server}"
            else:
                discovered = mcp_servers[server]
                state = discovered.state
                detail = discovered.detail
        elif kind == "api":
            state = "adapter-check"
            detail = f"runtime adapter must verify API service {provider['service']!r}"
        else:
            state = "available"
            detail = "explicit manual fallback"

        provider_secrets = [
            secret for secret in secrets if secret.provider_id == provider_id
        ]
        missing_required_secret = any(
            secret.required and secret.state in {"missing", "unavailable"}
            for secret in provider_secrets
        )
        if missing_required_secret:
            state = "missing"
            detail = "required secret reference is unavailable"
        statuses.append(ProviderStatus(provider_id, state, required, detail))

        for secret in provider_secrets:
            statuses.append(
                ProviderStatus(
                    f"{provider_id}.secret.{secret.name}",
                    secret.state,
                    secret.required,
                    secret.detail,
                )
            )
    return statuses


def _adapter_secret_status(
    kind: str,
    name: str,
    check: Callable[[str], tuple[str, str]] | None,
) -> tuple[str, str]:
    if check is None:
        return "adapter-check", f"{kind} reference {name} requires an adapter"
    state, detail = check(name)
    if state not in {"available", "missing", "unavailable", "adapter-check"}:
        raise ProfileError(f"secret adapter returned invalid state: {state!r}")
    return state, detail


def secret_statuses(
    profile: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    keychain_check: Callable[[str], tuple[str, str]] | None = None,
    runtime_secret_check: Callable[[str], tuple[str, str]] | None = None,
) -> list[SecretStatus]:
    """Return secret-reference readiness without reading or returning any value."""
    environment = environ if environ is not None else os.environ
    statuses: list[SecretStatus] = []
    for provider_id, provider in profile["providers"].items():
        for secret in provider.get("secret_refs", []):
            kind = secret["kind"]
            name = secret["name"]
            if kind == "environment":
                state = "available" if environment.get(name) else "missing"
                detail = f"environment reference {name}"
            elif kind == "keychain":
                state, detail = _adapter_secret_status(
                    kind,
                    name,
                    keychain_check,
                )
            else:
                state, detail = _adapter_secret_status(
                    kind,
                    name,
                    runtime_secret_check,
                )
            statuses.append(
                SecretStatus(
                    provider_id=provider_id,
                    kind=kind,
                    name=name,
                    state=state,
                    required=secret["required"],
                    detail=detail,
                )
            )
    return statuses


def _invocation_hint(provider: Mapping[str, Any], operation: str | None, runtime: str) -> str | None:
    if operation is None:
        return None
    if provider["kind"] == "mcp" and runtime in {"claude", "codex"}:
        server = provider["server"].replace("-", "_")
        return f"mcp__{server}__{operation}"
    if provider["kind"] == "cli":
        return f"{provider['command']} {operation}".strip()
    return None


def resolve_capability(
    resolved: ResolvedProfile,
    capability: str,
    *,
    statuses: list[ProviderStatus] | None = None,
    runtime: str = "generic",
) -> CapabilityResolution:
    """Resolve the first usable provider in a profile capability route."""
    route = resolved.document["capability_routes"].get(capability)
    if not route:
        raise ProfileError(
            f"profile {resolved.profile_id!r} does not route capability {capability!r}"
        )
    status_map = {
        status.provider_id: status
        for status in (statuses or provider_statuses(resolved.document))
        if ".secret." not in status.provider_id
    }
    rejected: list[str] = []
    for provider_id in route:
        provider = resolved.document["providers"][provider_id]
        status = status_map[provider_id]
        if status.state in {"missing", "unavailable"}:
            rejected.append(f"{provider_id}: {status.detail}")
            continue
        operation = provider["operations"].get(capability)
        return CapabilityResolution(
            capability=capability,
            provider_id=provider_id,
            kind=provider["kind"],
            service=provider["service"],
            operation=operation,
            availability=status.state,
            detail=status.detail,
            invocation=_invocation_hint(provider, operation, runtime),
        )
    raise ProfileError(
        f"no usable provider for {capability!r}: " + "; ".join(rejected)
    )


def capability_tool_exposure(
    resolutions: list[CapabilityResolution],
    *,
    available_tools: set[str] | frozenset[str],
    catalog_complete: bool,
) -> list[ToolExposure]:
    """Compare MCP invocation hints with a sanitized active tool-name catalog."""
    exposure: list[ToolExposure] = []
    for resolution in resolutions:
        invocation = resolution.invocation
        if resolution.kind != "mcp" or invocation is None:
            state = "not-applicable"
            detail = "capability does not use an MCP tool invocation"
        elif invocation in available_tools:
            state = "available"
            detail = "exact invocation is exposed in the active tool catalog"
        elif catalog_complete:
            state = "missing"
            detail = "exact invocation is absent from the complete active tool catalog"
        else:
            state = "unverified"
            detail = "active tool catalog was not supplied as complete"
        exposure.append(
            ToolExposure(
                capability=resolution.capability,
                invocation=invocation,
                state=state,
                detail=detail,
            )
        )
    return exposure
