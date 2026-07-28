from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from model_check_contract_schema import (
    CodeDef,
    Contract,
    JsonValue,
    UsageError,
    parse_metadata,
)


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    family: str
    severity: str
    path: str
    target: str
    message: str

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "family": self.family,
            "severity": self.severity,
            "path": self.path,
            "target": self.target,
            "message": self.message,
        }


def text_lines_from_json(value: JsonValue) -> str:
    match value:
        case {"findings": list(findings), "source_digest": str(source_digest)}:
            lines = [f"source_digest\t{source_digest}"]
            for raw in findings:
                match raw:
                    case {
                        "code": str(code),
                        "family": str(family),
                        "severity": str(severity),
                        "path": str(path),
                        "target": str(target),
                        "message": str(message),
                    }:
                        lines.append(
                            f"{severity}\t{family}\t{code}\t{path}\t{target}\t{message}"
                        )
                    case _:
                        raise UsageError("metadata output contains malformed finding")
            return "\n".join(lines) + "\n"
        case {"files": list(files), "source_digest": str(source_digest)}:
            lines = [f"source_digest\t{source_digest}"]
            for raw in files:
                match raw:
                    case {"path": str(path), "sha256": str(digest), "size": int(size)}:
                        lines.append(f"file\t{path}\t{size}\t{digest}")
                    case _:
                        raise UsageError("metadata output contains malformed source file")
            return "\n".join(lines) + "\n"
        case {"scenarios": list(scenarios), "source_digest": str(source_digest)}:
            lines = [f"source_digest\t{source_digest}"]
            for raw in scenarios:
                match raw:
                    case {"scenario_id": str(scenario), "route_id": str(route)}:
                        lines.append(f"scenario\t{scenario}\t{route}")
                    case _:
                        raise UsageError("metadata output contains malformed scenario")
            return "\n".join(lines) + "\n"
        case {"brain": str(brain), "state": str(state), "common": dict(common)}:
            match common:
                case {
                    "desired": str(desired),
                    "path": str(common_path),
                    "status": str(status),
                }:
                    return (
                        f"brain\t{brain}\n"
                        f"state\t{state}\n"
                        f"common.desired\t{desired}\n"
                        f"common.path\t{common_path}\n"
                        f"common.status\t{status}\n"
                    )
                case _:
                    raise UsageError("metadata output contains malformed manifest")
        case _:
            raise UsageError("metadata output cannot be rendered as text")


def severity_rank(severity: str) -> int:
    ranks = {"error": 0, "warning": 1, "info": 2}
    return ranks[severity]


def sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda item: (
            severity_rank(item.severity),
            item.code,
            item.path.encode(),
            item.target.encode(),
            item.message,
        ),
    )


def default_model_path(root: Path) -> Path:
    return root / "model" / "OPERATING-MODEL.json"
