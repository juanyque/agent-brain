from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
RELEASER = SKILL / "scripts" / "release_document.py"
TEMPLATE = PACKAGE / "templates" / "lease.md.j2"
DATA = PACKAGE / "examples" / "minimal-project.yaml"
CATALOG = PACKAGE / "clauses" / "catalog.yaml"
JURISDICTION = PACKAGE / "jurisdictions" / "es-md-madrid" / "jurisdiction.yaml"
SOURCES = PACKAGE / "jurisdictions" / "es-md-madrid" / "sources.yaml"
SNAPSHOT = (
    PACKAGE
    / "jurisdictions"
    / "es-md-madrid"
    / "legal-sources"
    / "snapshots"
    / "2026-07-23"
    / "snapshot-manifest.json"
)
SIGNER = "legal-reviewer@example.test"

CANDIDATES = (
    "lease.object-and-use@0.1.0",
    "lease.term-and-delivery@0.1.0",
    "lease.rent-and-payment@0.1.1",
    "lease.deposit-and-guarantee@0.1.0",
    "lease.rent-update@0.1.0",
    "lease.conservation-and-works@0.1.0",
    "lease.expenses-and-supplies@0.1.0",
    "lease.assignment-subletting-and-preemption@0.1.0",
    "lease.withdrawal-and-termination@0.1.0",
)
CHECKS = (
    "contract-effective-date",
    "landlord-capacity",
    "market-tension-status",
    "rent-update-regime",
    "security-deposit-filing",
)


@dataclass(frozen=True, slots=True)
class GovernanceFixtureSpec:
    status: str = "active"
    approved: tuple[str, ...] = CANDIDATES
    checks_valid_until: str = "2026-08-23"


DEFAULT_GOVERNANCE_FIXTURE: Final = GovernanceFixtureSpec()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_signed_governance(
    workspace: Path,
    spec: GovernanceFixtureSpec = DEFAULT_GOVERNANCE_FIXTURE,
) -> tuple[Path, ...]:
    approval = workspace / "approval.yaml"
    checks = workspace / "checks.yaml"
    ledger = workspace / "approval-ledger.yaml"
    _ = approval.write_text(
        yaml.safe_dump(
            {
                "approval_version": "0.1.0",
                "status": "approved",
                "catalog": "residential-lease-clauses@0.3.0",
                "jurisdiction": "es-md-madrid@0.1.0",
                "reviewed_on": "2026-07-24",
                "reviewer": {
                    "name": "Profesional jurídico de prueba",
                    "professional_id": "DEMO-REVIEWER",
                    "signer_identity": SIGNER,
                },
                "approved_clause_versions": list(spec.approved),
                "excluded_clause_versions": [
                    {
                        "id": "lease.notices-and-disputes@0.1.0",
                        "reason_code": "intentionally-excluded",
                    },
                ],
                "provenance": {
                    "catalog_sha256": digest(CATALOG),
                    "jurisdiction_sha256": digest(JURISDICTION),
                    "legal_source_snapshot_sha256": digest(SNAPSHOT),
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _ = checks.write_text(
        yaml.safe_dump(
            {
                "resolution_version": "0.1.0",
                "status": "complete",
                "jurisdiction": "es-md-madrid@0.1.0",
                "resolved_on": "2026-07-24",
                "valid_until": spec.checks_valid_until,
                "checks": [
                    {
                        "id": check_id,
                        "status": "passed",
                        "outcome_code": "synthetic-confirmed",
                        "evidence": [],
                    }
                    for check_id in CHECKS
                ],
                "provenance": {
                    "data_sha256": digest(DATA),
                    "jurisdiction_sha256": digest(JURISDICTION),
                    "sources_sha256": digest(SOURCES),
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _ = ledger.write_text(
        yaml.safe_dump(
            {
                "ledger_version": "0.1.0",
                "project_type": "residential-lease@0.1.0",
                "revision": 1,
                "issued_on": "2026-07-24",
                "valid_until": "2026-08-23",
                "signer_identity": SIGNER,
                "previous_ledger_sha256": None,
                "entries": [
                    {
                        "approval_sha256": digest(approval),
                        "status": spec.status,
                        "effective_on": "2026-07-24",
                        "replacement_approval_sha256": (
                            "1" * 64 if spec.status == "superseded" else None
                        ),
                        "reason_code": (
                            "review-withdrawn"
                            if spec.status == "withdrawn"
                            else None
                        ),
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    private_key = workspace / "signing-key"
    allowed_signers = workspace / "allowed-signers"
    _ = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private_key)],
        check=True,
    )
    public_key = private_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    _ = allowed_signers.write_text(
        f"{SIGNER} {public_key}\n",
        encoding="utf-8",
    )
    approval_signature = workspace / "approval.sig"
    ledger_signature = workspace / "approval-ledger.sig"
    for artifact, signature in (
        (approval, approval_signature),
        (ledger, ledger_signature),
    ):
        result = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(private_key),
                "-n",
                "manage-document-projects",
            ],
            input=artifact.read_bytes(),
            check=True,
            capture_output=True,
        )
        _ = signature.write_bytes(result.stdout)
    return (
        approval,
        approval_signature,
        ledger,
        ledger_signature,
        allowed_signers,
        checks,
    )

