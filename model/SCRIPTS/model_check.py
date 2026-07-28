#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from model_check_contract import (
    Contract,
    JsonValue,
    UsageError,
    default_model_path,
    parse_metadata,
    sorted_findings,
    text_lines_from_json,
)
from model_check_findings import code_findings
from model_check_reports import (
    brain_manifest,
    context_report,
    source_digest,
    source_report,
    stable_json,
)
from model_check_loading import loading_findings
from model_check_stale import scan_stale_references


STALE_REFERENCE_CODES = frozenset(
    {
        "missing-target",
        "review-archive-destination",
        "stale-architecture-reference",
    }
)


@dataclass(frozen=True, slots=True)
class Options:
    root: Path
    model: Path
    brain: Path | None
    only: tuple[str, ...]
    git_base: str | None
    strict: bool
    output_format: str
    mode: str


def split_only(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    selectors = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not selectors:
        raise UsageError("--only requires at least one selector")
    return selectors


def parse_args(argv: list[str]) -> Options:
    parser = argparse.ArgumentParser(description="Read-only operating-model contract checker")
    parser.add_argument("--root", default=".", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--brain", help="Path to a brain root for compatibility checks")
    parser.add_argument("--only", help="Comma-separated finding families or codes")
    parser.add_argument("--git-base", help="Base ref for committed REF...HEAD checks")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when error findings exist")
    parser.add_argument("--manifest-only", action="store_true", help="Emit brain manifest only")
    parser.add_argument("--source-digest", action="store_true", help="Emit source digest report")
    parser.add_argument("--context-report", action="store_true", help="Emit context scenario report")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    namespace = parser.parse_args(argv)
    root = Path(namespace.root).expanduser().resolve()
    modes = [
        name
        for name, enabled in (
            ("manifest", namespace.manifest_only),
            ("source", namespace.source_digest),
            ("context", namespace.context_report),
        )
        if enabled
    ]
    if len(modes) > 1:
        raise UsageError("choose only one report mode")
    mode = modes[0] if modes else "normal"
    model = Path(namespace.model).expanduser().resolve() if namespace.model else default_model_path(root)
    return Options(
        root=root,
        model=model,
        brain=Path(namespace.brain).expanduser().resolve() if namespace.brain else None,
        only=split_only(namespace.only),
        git_base=namespace.git_base,
        strict=namespace.strict,
        output_format=namespace.format,
        mode=mode,
    )


def selected_codes(options: Options, contract: Contract) -> tuple[str, ...]:
    if options.only:
        codes = contract.selected_codes(options.only)
    else:
        families = list(contract.defaults)
        if options.brain is not None:
            families.extend(contract.families_by_selection("brain"))
        codes = contract.selected_codes(tuple(families))
    needs_brain = any(code.selection == "brain" for code in codes)
    needs_git_base = any(code.selection == "committed" for code in codes)
    if needs_brain and options.brain is None:
        raise UsageError("brain-family selectors require --brain")
    if needs_git_base and options.git_base is None:
        raise UsageError("committed-family selectors require --git-base")
    if options.git_base is not None and not needs_git_base:
        raise UsageError("--git-base requires a selected committed family")
    return tuple(code.code for code in codes)


def validate_mode(options: Options, contract: Contract) -> None:
    if options.mode == "manifest":
        if options.brain is None:
            raise UsageError("--manifest-only requires --brain")
        if options.strict or options.only or options.git_base is not None:
            raise UsageError("--manifest-only rejects --strict, --only, and --git-base")
    if options.mode in {"source", "context"}:
        if (
            options.brain is not None
            or options.strict
            or options.only
            or options.git_base is not None
        ):
            raise UsageError(f"--{options.mode}-report rejects selectors and strict modes")
    if options.mode == "normal":
        selected_codes(options, contract)


def load_model(path: Path) -> dict[str, JsonValue]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise UsageError("metadata root must be an object")
    return raw


def normal_report(
    options: Options,
    contract: Contract,
    model: dict[str, JsonValue],
) -> tuple[int, dict[str, JsonValue]]:
    code_names = set(selected_codes(options, contract))
    findings = []
    stale_codes = code_names & STALE_REFERENCE_CODES
    if stale_codes:
        findings.extend(
            finding
            for finding in scan_stale_references(options.root, options.model)
            if finding.code in stale_codes
        )
        if "review-archive-destination" in stale_codes:
            from model_check_evidence_ownership import scan_evidence_ownership

            findings.extend(
                finding
                for finding in scan_evidence_ownership(options.root)
                if finding.code == "review-archive-destination"
            )
    for code in contract.codes:
        if code.code not in code_names:
            continue
        if code.code in STALE_REFERENCE_CODES:
            continue
        if code.family == "loading":
            findings.extend(loading_findings(options.root, model, code))
            continue
        findings.extend(
            code_findings(options.root, model, options.model, code, options.brain, options.git_base)
        )
    deduped = {}
    for finding in findings:
        deduped[(finding.code, finding.path, finding.target)] = finding
    ordered = sorted_findings(list(deduped.values()))
    exit_code = 1 if options.strict and any(item.severity == "error" for item in ordered) else 0
    return exit_code, {
        "source_digest": source_digest(options.root),
        "findings": [item.as_json() for item in ordered],
    }


def render(value: JsonValue, output_format: str) -> str:
    if output_format == "json":
        return stable_json(value) + "\n"
    return text_lines_from_json(value)


def run(argv: list[str]) -> tuple[int, str]:
    options = parse_args(argv)
    model = load_model(options.model)
    contract = parse_metadata(model)
    validate_mode(options, contract)
    match options.mode:
        case "normal":
            exit_code, report = normal_report(options, contract, model)
            return exit_code, render(report, options.output_format)
        case "manifest":
            if options.brain is None:
                raise UsageError("--manifest-only requires --brain")
            return 0, render(brain_manifest(options.brain, options.root / "model"), options.output_format)
        case "source":
            return 0, render(source_report(options.root), options.output_format)
        case "context":
            return 0, render(context_report(options.root, model), options.output_format)
        case _:
            raise UsageError("unknown report mode")


def main() -> int:
    try:
        exit_code, output = run(sys.argv[1:])
    except UsageError as exc:
        print(f"model_check usage/metadata error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"model_check metadata error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"model_check internal error: {exc}", file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
