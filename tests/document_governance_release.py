from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from document_governance_fixtures import DATA, RELEASER, TEMPLATE
from document_project_workspace import workspace_environment


def run_release(
    workspace: Path,
    governance: tuple[Path, ...],
) -> tuple[subprocess.CompletedProcess[str], Path]:
    approval, approval_signature, ledger, ledger_signature, allowed_signers, checks = (
        governance
    )
    output = workspace / "lease.pdf"
    request = workspace / "release.yaml"
    _ = request.write_text(
        yaml.safe_dump(
            {
                "release_version": "0.2.0",
                "template": str(TEMPLATE),
                "data": str(DATA),
                "approval": str(approval),
                "approval_signature": str(approval_signature),
                "approval_ledger": str(ledger),
                "approval_ledger_signature": str(ledger_signature),
                "allowed_signers": str(allowed_signers),
                "jurisdiction_checks": str(checks),
                "release_date": "2026-07-24",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "--script",
            str(RELEASER),
            str(request),
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=workspace_environment(workspace),
    )
    return result, output
