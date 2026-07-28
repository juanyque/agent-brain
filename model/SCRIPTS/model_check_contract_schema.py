from __future__ import annotations

from dataclasses import dataclass
from typing import Final


JsonScalar = str | int | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class UsageError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CodeDef:
    code: str
    family: str
    severity: str
    selection: str
    default: bool
    check: str


@dataclass(frozen=True, slots=True)
class Contract:
    defaults: tuple[str, ...]
    codes: tuple[CodeDef, ...]
    aliases: dict[str, tuple[str, ...]]

    def codes_by_family(self, family: str) -> tuple[CodeDef, ...]:
        return tuple(code for code in self.codes if code.family == family)

    def families_by_selection(self, selection: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(code.family for code in self.codes if code.selection == selection)
        )

    def selected_codes(self, selectors: tuple[str, ...]) -> tuple[CodeDef, ...]:
        selected: list[CodeDef] = []
        for selector in selectors:
            expanded = self.aliases.get(selector, (selector,))
            for name in expanded:
                family_codes = self.codes_by_family(name)
                if family_codes:
                    selected.extend(family_codes)
                    continue
                matched = tuple(code for code in self.codes if code.code == name)
                if not matched:
                    raise UsageError(f"unknown --only selector: {selector}")
                selected.extend(matched)
        deduped: dict[str, CodeDef] = {}
        for code in selected:
            deduped[code.code] = code
        return tuple(deduped.values())


SYNTHETIC_CODES = (
    CodeDef(
        code="git-authority-explicit",
        family="git-authority",
        severity="error",
        selection="default",
        default=False,
        check="git-authority-explicit",
    ),
)

REQUIRED_ROUTE_CODE_FAMILIES: Final[tuple[tuple[str, str], ...]] = (
    ("duplicate-route-id", "route-target"),
    ("malformed-route-metadata", "route-target"),
    ("missing-route-target", "route-target"),
    ("orphan-model-artifact", "route-target"),
    ("unmapped-cluster", "route-target"),
)


def _validate_route_contract(
    defaults: tuple[str, ...],
    family_memberships: dict[str, set[str]],
    metadata_families: dict[str, set[str]],
    metadata_defaults: dict[str, bool],
    metadata_severities: dict[str, str],
    severity_defaults: dict[str, JsonValue],
) -> None:
    missing = {
        code
        for code, family in REQUIRED_ROUTE_CODE_FAMILIES
        if (
            family_memberships.get(code) != {family}
            or metadata_families.get(code) != {family}
            or code not in severity_defaults
        )
    }
    if missing:
        names = ", ".join(sorted(missing))
        raise UsageError(
            f"metadata schema missing required route code contract entries: {names}"
        )
    if "route-target" not in defaults:
        raise UsageError("metadata route-target must be selected by default")
    disabled = {
        code
        for code, _family in REQUIRED_ROUTE_CODE_FAMILIES
        if metadata_defaults.get(code) is not True
    }
    if disabled:
        names = ", ".join(sorted(disabled))
        raise UsageError(f"metadata required route codes must default true: {names}")
    mismatched = {
        code
        for code, _family in REQUIRED_ROUTE_CODE_FAMILIES
        if severity_defaults.get(code) != metadata_severities.get(code)
    }
    if mismatched:
        names = ", ".join(sorted(mismatched))
        raise UsageError(f"metadata route severity declarations differ: {names}")


def parse_metadata(raw: JsonValue) -> Contract:
    match raw:
        case {"finding_contract": dict(finding_contract)}:
            pass
        case _:
            raise UsageError("metadata schema missing finding_contract")
    match finding_contract:
        case {
            "defaults": list(defaults),
            "families": list(families),
            "code_metadata": list(code_metadata),
            "severity_defaults": dict(severity_defaults),
        }:
            pass
        case _:
            raise UsageError("metadata schema has incomplete finding_contract")
    alias_rows = finding_contract.get("aliases", {})
    if not isinstance(alias_rows, dict):
        raise UsageError("metadata aliases must be an object")
    aliases: dict[str, tuple[str, ...]] = {}
    for key, value in alias_rows.items():
        if not isinstance(key, str) or not isinstance(value, list):
            raise UsageError("metadata alias entry is malformed")
        aliases[key] = tuple(item for item in value if isinstance(item, str))
        if len(aliases[key]) != len(value):
            raise UsageError("metadata alias target is malformed")
    family_selection: dict[str, str] = {}
    family_memberships: dict[str, set[str]] = {}
    for row in families:
        match row:
            case {"family": str(family), "selection": str(selection), "codes": list(codes)}:
                if not all(isinstance(code, str) for code in codes):
                    raise UsageError("metadata family codes are malformed")
                if selection not in {"default", "brain", "committed", "worktree"}:
                    raise UsageError(f"metadata has unknown family selection: {family}")
                if family in family_selection:
                    raise UsageError(f"metadata has duplicate family metadata: {family}")
                family_selection[family] = selection
                for code in codes:
                    family_memberships.setdefault(code, set()).add(family)
            case _:
                raise UsageError("metadata family entry is malformed")
    parsed_codes: list[CodeDef] = []
    metadata_families: dict[str, set[str]] = {}
    metadata_defaults: dict[str, bool] = {}
    metadata_severities: dict[str, str] = {}
    for row in code_metadata:
        match row:
            case {
                "code": str(code),
                "family": str(family),
                "severity": str(severity),
                "default": bool(default),
                "check": str(check),
            }:
                if family not in family_selection:
                    raise UsageError(f"metadata code has unknown family: {code}")
                if severity not in {"error", "warning", "info"}:
                    raise UsageError(f"metadata code has unknown severity: {code}")
                if code in metadata_families:
                    raise UsageError(f"metadata has duplicate code metadata: {code}")
                metadata_families.setdefault(code, set()).add(family)
                metadata_defaults[code] = default
                metadata_severities[code] = severity
                parsed_codes.append(
                    CodeDef(
                        code=code,
                        family=family,
                        severity=severity,
                        selection=family_selection[family],
                        default=default,
                        check=check,
                    )
                )
            case _:
                raise UsageError("metadata code entry is malformed")
    default_names = tuple(item for item in defaults if isinstance(item, str))
    if len(default_names) != len(defaults):
        raise UsageError("metadata defaults are malformed")
    _validate_route_contract(
        default_names,
        family_memberships,
        metadata_families,
        metadata_defaults,
        metadata_severities,
        severity_defaults,
    )
    family_codes = set(family_memberships)
    metadata_codes = {code.code for code in parsed_codes}
    if family_codes != metadata_codes:
        raise UsageError("metadata families and code definitions differ")
    for code in SYNTHETIC_CODES:
        if code.code not in metadata_codes:
            parsed_codes.append(code)
    return Contract(defaults=default_names, codes=tuple(parsed_codes), aliases=aliases)
