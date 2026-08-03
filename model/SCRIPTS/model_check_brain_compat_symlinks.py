from __future__ import annotations

from pathlib import Path
from typing import Final

from model_check_contract import Finding, UsageError
from model_check_no_follow import lstat_entry, readlink_text, symlinked_parent, walk_no_follow


MANAGED_TEMPLATES: Final = {
    "TEMPLATES/WIP Template.md": "TEMPLATES/TEMPLATE.wip.common.md",
    "TEMPLATES/WIP Session Template.md": "TEMPLATES/TEMPLATE.wip-session.common.md",
    "TEMPLATES/Daily Note Template.md": "TEMPLATES/TEMPLATE.daily-note.common.md",
    "TEMPLATES/Issue Template.md": "TEMPLATES/TEMPLATE.issue.common.md",
}
INTENTIONAL_MODEL_SYMLINKS: Final = frozenset(("_COMMON", *MANAGED_TEMPLATES))


def _add(
    findings: list[Finding],
    severities: dict[str, str],
    code: str,
    path: str,
    target: str,
    message: str,
) -> None:
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


def conditional_templates(common: Path) -> dict[str, str]:
    templates: dict[str, str] = {}
    for source in sorted((common / "TEMPLATES").glob("TEMPLATE.*.common.md")):
        common_rel = f"TEMPLATES/{source.name}"
        if common_rel in MANAGED_TEMPLATES.values():
            continue
        name = source.name.removeprefix("TEMPLATE.").removesuffix(".common.md")
        templates[f"TEMPLATES/{name} Template.md"] = common_rel
    return templates


def template_findings(
    brain: Path,
    common: Path,
    severities: dict[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    for local_rel, common_rel in MANAGED_TEMPLATES.items():
        local_path = brain / local_rel
        escaped_parent = symlinked_parent(brain, local_path)
        if escaped_parent is not None:
            _add(findings, severities, "brain-managed-path-escape", local_rel, str(escaped_parent), "managed template parent is a symlink")
            continue
        entry = lstat_entry(local_path)
        if not entry.exists:
            _add(findings, severities, "brain-template-broken", local_rel, common_rel, "managed template symlink is missing")
            continue
        if not entry.is_symlink:
            _add(findings, severities, "brain-template-wrong-model", local_rel, common_rel, "managed template is not a symlink to this model")
            continue
        try:
            resolved = local_path.resolve(strict=True)
        except (OSError, RuntimeError):
            _add(findings, severities, "brain-template-broken", local_rel, readlink_text(local_path), "managed template symlink target is missing")
            continue
        expected = (common / common_rel).resolve()
        if resolved != expected:
            _add(findings, severities, "brain-template-wrong-model", local_rel, common_rel, "managed template resolves outside this model")
    for local_rel, common_rel in conditional_templates(common).items():
        if not lstat_entry(brain / local_rel).exists:
            _add(findings, severities, "brain-conditional-template-absent", local_rel, common_rel, "conditional template is not linked in this brain")
    return findings


def unmanaged_external_symlink_findings(
    brain: Path,
    severities: dict[str, str],
) -> list[Finding]:
    findings: list[Finding] = []
    brain_root = brain.resolve()
    for path in walk_no_follow(brain):
        local_rel = path.relative_to(brain).as_posix()
        if local_rel in INTENTIONAL_MODEL_SYMLINKS or not lstat_entry(path).is_symlink:
            continue
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_relative_to(brain_root):
            continue
        _add(
            findings,
            severities,
            "brain-unmanaged-external-symlink",
            local_rel,
            str(resolved),
            "unmanaged symlink resolves outside the brain; ingest its content or leave it user-managed",
        )
    return findings
