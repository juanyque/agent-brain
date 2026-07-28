from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

from selection_inputs import SelectionProjectError

SIGNATURE_NAMESPACE: Final = "manage-document-projects"


@dataclass(frozen=True, slots=True)
class SignatureVerificationError(SelectionProjectError):
    artifact: Path
    signer_identity: str
    reason: str

    @override
    def __str__(self) -> str:
        return (
            f"signature verification failed for {self.artifact} "
            f"as {self.signer_identity}: {self.reason}"
        )


@dataclass(frozen=True, slots=True)
class SignatureVerification:
    artifact: Path
    signature: Path
    allowed_signers: Path
    signer_identity: str


def sign_artifact(artifact: Path, private_key: Path) -> bytes:
    """Create an OpenSSH detached signature for exact artifact bytes."""
    result = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(private_key),
            "-n",
            SIGNATURE_NAMESPACE,
        ],
        input=artifact.read_bytes(),
        check=True,
        capture_output=True,
    )
    return result.stdout


def verify_signature(verification: SignatureVerification) -> None:
    """Verify an OpenSSH signature against an explicit trust file."""
    result = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "verify",
            "-f",
            str(verification.allowed_signers),
            "-I",
            verification.signer_identity,
            "-n",
            SIGNATURE_NAMESPACE,
            "-s",
            str(verification.signature),
        ],
        input=verification.artifact.read_bytes(),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        reason = result.stderr.decode("utf-8", errors="replace").strip()
        raise SignatureVerificationError(
            artifact=verification.artifact,
            signer_identity=verification.signer_identity,
            reason=reason,
        )
