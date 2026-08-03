#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from model_check_contract import (
    Finding,
    JsonValue,
    UsageError,
    sorted_findings,
    text_lines_from_json,
)
from model_check_brain_compat_paths import first_absolute_common_markdown_path
from model_check_brain_compat_symlinks import (
    template_findings,
    unmanaged_external_symlink_findings,
)
from model_check_no_follow import lstat_entry, readlink_text, symlinked_parent, walk_no_follow
from model_check_reports import stable_json


WRAPPERS = {
    "AGENTS.md": "AGENTS.common.md",
    "BRAIN.md": "BRAIN.common.md",
    "JOBS.md": "JOBS.common.md",
}
SECTION_REF = re.compile(r'^#{2,6}\s+(?:Adds to|Overrides in|Replaces)\s+"([^"]+)"\s*$')


def severity_by_code(model_path: Path) -> dict[str, str]:
    raw = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise UsageError("metadata root must be an object")
    match raw:
        case {"finding_contract": {"code_metadata": list(rows)}}:
            pass
        case _:
            raise UsageError("metadata schema missing finding_contract.code_metadata")
    severities: dict[str, str] = {}
    for row in rows:
        match row:
            case {"code": str(code), "severity": str(severity)}:
                severities[code] = severity
            case _:
                raise UsageError("metadata code entry is malformed")
    return severities


def normalize_section(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def common_sections(path: Path) -> set[str]:
    sections: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title:
                sections.add(normalize_section(title))
    return sections


def discover_wrappers(common: Path) -> dict[str, str]:
    wrappers = dict(WRAPPERS)
    for source in sorted(common.glob("RULES-*.common.md")):
        wrappers[source.name.removesuffix(".common.md") + ".md"] = source.name
    task_dir = common / "TASK_TYPES"
    if task_dir.is_dir():
        for source in sorted(task_dir.glob("*.common.md")):
            local = source.stem.removesuffix(".common") + ".md"
            wrappers[f"TASK_TYPES/{local}"] = f"TASK_TYPES/{source.name}"
    return wrappers


def add(
    findings: list[Finding],
    severities: dict[str, str],
    code: str,
    path: str,
    target: str,
    message: str,
) -> Finding:
    severity = severities.get(code)
    if severity is None:
        raise UsageError(f"metadata code missing for brain compatibility: {code}")
    findings.append(
        Finding(
            code=code,
            family="brain-compatibility",
            severity=severity,
            path=path,
            target=target,
            message=message,
        )
    )


def wrapper_findings(
    brain: Path,
    common: Path,
    severities: dict[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    for local_rel, common_rel in discover_wrappers(common).items():
        local_path = brain / local_rel
        escaped_parent = symlinked_parent(brain, local_path)
        if escaped_parent is not None:
            add(findings, severities, "brain-managed-path-escape", local_rel, str(escaped_parent), "managed wrapper parent is a symlink")
            continue
        entry = lstat_entry(local_path)
        expected = f"_COMMON/{common_rel}"
        if not entry.exists:
            add(findings, severities, "brain-wrapper-missing", local_rel, expected, "mandatory wrapper is missing")
            continue
        if entry.is_symlink:
            try:
                local_path.resolve(strict=True)
            except (OSError, RuntimeError):
                add(findings, severities, "brain-managed-entry-dangling", local_rel, readlink_text(local_path), "managed wrapper symlink target is missing")
                continue
        if not entry.is_file:
            add(findings, severities, "brain-wrapper-wrong-target", local_rel, expected, "mandatory wrapper is not a regular file")
            continue
        text = local_path.read_text(encoding="utf-8")
        if "VAULT.md" in text:
            add(findings, severities, "brain-wrapper-legacy-vault", local_rel, "VAULT.md", "wrapper references legacy vault model target")
            continue
        absolute_target = first_absolute_common_markdown_path(text)
        if absolute_target is not None:
            add(findings, severities, "brain-wrapper-wrong-target", local_rel, absolute_target, "wrapper embeds an absolute common-model Markdown path; leave the brain unchanged and replace it with a relative _COMMON link manually if desired")
            continue
        if expected not in text:
            add(findings, severities, "brain-wrapper-wrong-target", local_rel, expected, "mandatory wrapper does not reference its common target")
            continue
        common_names = common_sections(common / common_rel)
        refs = [
            match.group(1)
            for line in text.splitlines()
            if (match := SECTION_REF.match(line))
        ]
        missing = [name for name in refs if normalize_section(name) not in common_names]
        if missing:
            add(findings, severities, "brain-wrapper-missing-common-section", local_rel, missing[0], "wrapper references a missing common section")
            continue
        if refs:
            add(findings, severities, "brain-wrapper-customized", local_rel, expected, "wrapper has valid local customization")
    return findings


def scan_brain_compatibility(brain: Path, common: Path, model_path: Path) -> list[Finding]:
    severities = severity_by_code(model_path)
    findings = wrapper_findings(brain, common, severities)
    findings.extend(template_findings(brain, common, severities))
    findings.extend(unmanaged_external_symlink_findings(brain, severities))
    return sorted_findings(findings)


def brain_digest(brain: Path) -> str:
    rows: list[dict[str, JsonValue]] = []
    for path in walk_no_follow(brain):
        rel = path.relative_to(brain).as_posix()
        entry = lstat_entry(path)
        if entry.is_symlink:
            rows.append({"path": rel, "type": "symlink", "target": readlink_text(path)})
        elif entry.is_file:
            rows.append(
                {
                    "path": rel,
                    "type": "file",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return hashlib.sha256(stable_json({"entries": rows}).encode()).hexdigest()


def compatibility_report(
    brain: Path,
    common: Path,
    model_path: Path,
    strict: bool,
) -> tuple[int, dict[str, JsonValue]]:
    findings = scan_brain_compatibility(brain, common, model_path)
    exit_code = 1 if strict and any(item.severity == "error" for item in findings) else 0
    return exit_code, {
        "findings": [item.as_json() for item in findings],
        "source_digest": brain_digest(brain),
    }


def parse_args(argv: list[str]) -> tuple[Path, Path, Path, bool, str]:
    parser = argparse.ArgumentParser(description="Read-only brain compatibility checker")
    parser.add_argument("--brain", required=True)
    parser.add_argument("--common", default="model")
    parser.add_argument("--model")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    namespace = parser.parse_args(argv)
    common = Path(namespace.common).expanduser().resolve()
    model = (
        Path(namespace.model).expanduser().resolve()
        if namespace.model
        else common / "OPERATING-MODEL.json"
    )
    return (
        Path(namespace.brain).expanduser().resolve(),
        common,
        model,
        bool(namespace.strict),
        str(namespace.format),
    )


def run(argv: list[str]) -> tuple[int, str]:
    brain, common, model, strict, output_format = parse_args(argv)
    exit_code, payload = compatibility_report(brain, common, model, strict)
    if output_format == "json":
        return exit_code, stable_json(payload) + "\n"
    return exit_code, text_lines_from_json(payload)


def main() -> int:
    try:
        exit_code, output = run(sys.argv[1:])
    except UsageError as exc:
        print(f"model_check_brain_compat usage/metadata error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"model_check_brain_compat metadata error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
