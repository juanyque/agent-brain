from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

import yaml
from document_governance_fixtures import (
    PACKAGE,
    SIGNER,
    digest,
    write_signed_governance,
)
from pydantic import BaseModel, ConfigDict

UPDATER = (
    PACKAGE.parents[2]
    / "scripts"
    / "update_approval_status.py"
)
SIGNER_CLI = PACKAGE.parents[2] / "scripts" / "sign_governance.py"


class _Entry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")

    approval_sha256: str
    status: str
    replacement_approval_sha256: str | None


class _Ledger(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="allow")

    revision: int
    previous_ledger_sha256: str
    entries: tuple[_Entry, ...]


def test_status_cli_supersedes_an_active_approval_with_a_replacement() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        approval, _, previous, *_ = write_signed_governance(workspace)
        replacement = workspace / "replacement-approval.yaml"
        _ = replacement.write_text(
            approval.read_text(encoding="utf-8").replace(
                "DEMO-REVIEWER",
                "DEMO-REVIEWER-2",
            ),
            encoding="utf-8",
        )
        request = workspace / "status-update.yaml"
        output = workspace / "approval-ledger-v2.yaml"
        _ = request.write_text(
            yaml.safe_dump(
                {
                    "status_update_version": "0.1.0",
                    "project_type": "residential-lease@0.1.0",
                    "approval": str(approval),
                    "action": "superseded",
                    "effective_on": "2026-07-25",
                    "valid_until": "2026-08-23",
                    "signer_identity": SIGNER,
                    "previous_ledger": str(previous),
                    "replacement_approval": str(replacement),
                    "reason_code": "new-review-issued",
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        # When
        result = subprocess.run(
            ["uv", "run", "--script", str(UPDATER), str(request), str(output)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        ledger = _Ledger.model_validate(
            yaml.safe_load(output.read_text(encoding="utf-8")),
        )
        assert ledger.revision == 2
        assert ledger.previous_ledger_sha256 == digest(previous)
        assert ledger.entries == (
            _Entry(
                approval_sha256=digest(approval),
                status="superseded",
                replacement_approval_sha256=digest(replacement),
            ),
            _Entry(
                approval_sha256=digest(replacement),
                status="active",
                replacement_approval_sha256=None,
            ),
        )


def test_signing_cli_creates_a_verifiable_detached_signature() -> None:
    # Given
    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw)
        approval, *_ = write_signed_governance(workspace)
        private_key = workspace / "operator-key"
        signature = workspace / "operator.sig"
        allowed_signers = workspace / "operator-allowed-signers"
        _ = subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
            check=True,
        )
        public_key = private_key.with_suffix(".pub").read_text(
            encoding="utf-8",
        ).strip()
        _ = allowed_signers.write_text(
            f"{SIGNER} {public_key}\n",
            encoding="utf-8",
        )

        # When
        result = subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(SIGNER_CLI),
                str(approval),
                str(private_key),
                str(signature),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Then
        assert result.returncode == 0, result.stdout + result.stderr
        verification = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(allowed_signers),
                "-I",
                SIGNER,
                "-n",
                "manage-document-projects",
                "-s",
                str(signature),
            ],
            input=approval.read_bytes(),
            check=False,
            capture_output=True,
        )
        assert verification.returncode == 0, verification.stderr
