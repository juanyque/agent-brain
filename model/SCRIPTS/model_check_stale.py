#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import Finding, JsonValue, UsageError, sorted_findings, text_lines_from_json


def stable_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class StaleRule:
    code: str
    family: str
    severity: str
    pattern: str
    reason: str
    replacement: str


@dataclass(frozen=True, slots=True)
class AllowEntry:
    path: str
    patterns: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class Options:
    root: Path
    model: Path
    only: tuple[str, ...]
    strict: bool
    output_format: str


def default_model_path(root: Path) -> Path:
    return root / "model" / "OPERATING-MODEL.json"


def split_only(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    selectors = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not selectors:
        raise UsageError("--only requires at least one selector")
    return selectors


def parse_args(argv: list[str]) -> Options:
    parser = argparse.ArgumentParser(description="Read-only stale-reference checker")
    parser.add_argument("--root", default=".")
    parser.add_argument("--model")
    parser.add_argument("--only", help="Comma-separated finding families or codes")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when error findings exist")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    namespace = parser.parse_args(argv)
    root = Path(namespace.root).expanduser().resolve()
    return Options(
        root=root,
        model=Path(namespace.model).expanduser().resolve()
        if namespace.model
        else default_model_path(root),
        only=split_only(namespace.only),
        strict=namespace.strict,
        output_format=namespace.format,
    )


def code_for_class(class_id: str) -> tuple[str, str]:
    prefix = class_id.split(".", maxsplit=1)[0]
    match prefix:
        case "missing-target":
            return "missing-target", "target-existence"
        case "review-archive":
            return "review-archive-destination", "review-archive"
        case "stale-class":
            return "stale-architecture-reference", "stale-reference"
        case _:
            raise UsageError(f"unknown stale-reference class id: {class_id}")


def load_json_object(path: Path) -> dict[str, JsonValue]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise UsageError("metadata root must be an object")
    return raw


def severity_by_code(metadata: dict[str, JsonValue]) -> dict[str, str]:
    match metadata:
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


def load_rules(model_path: Path) -> tuple[tuple[StaleRule, ...], tuple[AllowEntry, ...]]:
    metadata = load_json_object(model_path)
    severities = severity_by_code(metadata)
    match metadata:
        case {"stale_reference_contract": {"classes": list(classes)}}:
            allowlist = metadata["stale_reference_contract"].get("allowlist", [])
        case _:
            raise UsageError("metadata schema missing stale_reference_contract.classes")
    if not isinstance(allowlist, list):
        raise UsageError("metadata stale allowlist is malformed")
    rules: list[StaleRule] = []
    for row in classes:
        match row:
            case {"id": str(class_id), "patterns": list(patterns), "replacement": str(replacement)}:
                reason = row.get("reason", class_id)
                if not isinstance(reason, str):
                    raise UsageError("metadata stale class reason is malformed")
                code, family = code_for_class(class_id)
                severity = severities.get(code)
                if severity is None:
                    raise UsageError(f"metadata code missing for stale class: {class_id}")
                for pattern in patterns:
                    if not isinstance(pattern, str):
                        raise UsageError("metadata stale pattern is malformed")
                    rules.append(
                        StaleRule(
                            code=code,
                            family=family,
                            severity=severity,
                            pattern=pattern,
                            reason=reason,
                            replacement=replacement,
                        )
                    )
            case _:
                raise UsageError("metadata stale class entry is malformed")
    allows: list[AllowEntry] = []
    for row in allowlist:
        match row:
            case {"path": str(path), "patterns": list(patterns), "reason": str(reason)}:
                if not all(isinstance(pattern, str) for pattern in patterns):
                    raise UsageError("metadata stale allowlist pattern is malformed")
                allows.append(AllowEntry(path=path, patterns=tuple(patterns), reason=reason))
            case _:
                raise UsageError("metadata stale allowlist entry is malformed")
    return tuple(rules), tuple(allows)


def is_allowed(path: str, pattern: str, allowlist: tuple[AllowEntry, ...]) -> bool:
    return any(entry.path == path and pattern in entry.patterns for entry in allowlist)


def is_allowlisted_inventory_line(path: str, line: str, allowlist: tuple[AllowEntry, ...]) -> bool:
    return any(
        entry.path == path and any(pattern in line for pattern in entry.patterns)
        for entry in allowlist
    )


def markdown_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(root.rglob("*.md"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )


def scan_stale_references(root: Path, model_path: Path) -> list[Finding]:
    rules, allowlist = load_rules(model_path)
    ordered_rules = tuple(sorted(rules, key=lambda rule: len(rule.pattern), reverse=True))
    findings: list[Finding] = []
    for path in markdown_files(root):
        rel_path = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if is_allowlisted_inventory_line(rel_path, line, allowlist):
                continue
            matched_spans: list[tuple[int, int]] = []
            for rule in ordered_rules:
                start = line.find(rule.pattern)
                if start < 0:
                    continue
                end = start + len(rule.pattern)
                if any(max(start, left) < min(end, right) for left, right in matched_spans):
                    continue
                matched_spans.append((start, end))
                if is_allowed(rel_path, rule.pattern, allowlist):
                    continue
                findings.append(
                    Finding(
                        code=rule.code,
                        family=rule.family,
                        severity=rule.severity,
                        path=rel_path,
                        target=rule.pattern,
                        message=(
                            f"line {line_number}: {rule.reason}; "
                            f"replace with {rule.replacement}"
                        ),
                    )
                )
    return sorted_findings(findings)


def known_selectors() -> set[str]:
    return {
        "missing-target",
        "review-archive",
        "review-archive-destination",
        "stale-architecture-reference",
        "stale-reference",
        "target-existence",
    }


def selected_findings(findings: list[Finding], selectors: tuple[str, ...]) -> list[Finding]:
    if not selectors:
        return findings
    unknown = tuple(selector for selector in selectors if selector not in known_selectors())
    if unknown:
        raise UsageError(f"unknown --only selector: {unknown[0]}")
    return [
        finding
        for finding in findings
        if finding.code in selectors or finding.family in selectors
    ]


def source_digest(root: Path) -> str:
    entries: list[dict[str, JsonValue]] = []
    for path in markdown_files(root):
        rel_path = path.relative_to(root).as_posix()
        entries.append(
            {
                "path": rel_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return hashlib.sha256(stable_json({"files": entries}).encode()).hexdigest()


def report(options: Options) -> tuple[int, dict[str, JsonValue]]:
    findings = selected_findings(scan_stale_references(options.root, options.model), options.only)
    exit_code = 1 if options.strict and any(finding.severity == "error" for finding in findings) else 0
    return exit_code, {
        "findings": [finding.as_json() for finding in findings],
        "source_digest": source_digest(options.root),
    }


def render(value: JsonValue, output_format: str) -> str:
    if output_format == "json":
        return stable_json(value) + "\n"
    return text_lines_from_json(value)


def run(argv: list[str]) -> tuple[int, str]:
    options = parse_args(argv)
    exit_code, value = report(options)
    return exit_code, render(value, options.output_format)


def main() -> int:
    try:
        exit_code, output = run(sys.argv[1:])
    except UsageError as exc:
        print(f"model_check_stale usage/metadata error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"model_check_stale metadata error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
