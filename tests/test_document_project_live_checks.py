from __future__ import annotations

import hashlib
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "manage-document-projects"
PACKAGE = SKILL / "assets" / "project-types" / "residential-lease"
RESOLVER = SKILL / "scripts" / "resolve_jurisdiction_checks.py"
DATA = PACKAGE / "examples" / "minimal-project.yaml"
JURISDICTION = PACKAGE / "jurisdictions" / "es-md-madrid" / "jurisdiction.yaml"


class _Evidence(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    source_id: str
    official_url: str
    resolved_url: str
    status_code: int
    content_sha256: str


class _Check(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    status: str
    outcome_code: str
    evidence: tuple[_Evidence, ...]


class _Resolution(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: str
    checks: tuple[_Check, ...]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = f"official-test:{self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    def log_message(self, format: str, *args: str) -> None:
        del format, args


def _write_request(workspace: Path, base_url: str) -> Path:
    sources = workspace / "sources.yaml"
    manifest = workspace / "project-type.yaml"
    request = workspace / "request.yaml"
    _ = sources.write_text(
        yaml.safe_dump(
            {
                "registry_version": "0.1.0",
                "jurisdiction": "es-md-madrid",
                "sources": [
                    {
                        "id": source_id,
                        "official_url": f"{base_url}/{source_id}",
                        "preservation": "resolve-live",
                    }
                    for source_id in (
                        "es-rental-reference-system",
                        "es-irav-ine",
                        "es-md-deposit-service",
                    )
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _ = manifest.write_text(
        yaml.safe_dump(
            {
                "data_schema": str(PACKAGE / "schemas" / "project-data.schema.json"),
                "clause_catalog": str(PACKAGE / "clauses" / "catalog.yaml"),
                "defaults_profiles": {
                    "residential-standard": str(
                        PACKAGE / "defaults" / "residential-standard.yaml",
                    ),
                },
                "jurisdictions": {
                    "es-md-madrid": {
                        "status": "pending-legal-review",
                        "layer": str(JURISDICTION),
                        "sources": str(sources),
                        "legal_source_snapshot": str(
                            PACKAGE
                            / "jurisdictions"
                            / "es-md-madrid"
                            / "legal-sources"
                            / "snapshots"
                            / "2026-07-23"
                            / "snapshot-manifest.json"
                        ),
                    },
                },
                "documents": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _ = request.write_text(
        yaml.safe_dump(
            {
                "request_version": "0.1.0",
                "project_type": str(manifest),
                "data": str(DATA),
                "resolved_on": "2026-07-24",
                "valid_until": "2026-08-23",
                "checks": [
                    {
                        "id": "contract-effective-date",
                        "outcome_code": "synthetic-confirmed",
                        "source_ids": [],
                    },
                    {
                        "id": "landlord-capacity",
                        "outcome_code": "synthetic-confirmed",
                        "source_ids": [],
                    },
                    {
                        "id": "market-tension-status",
                        "outcome_code": "synthetic-confirmed",
                        "source_ids": ["es-rental-reference-system"],
                    },
                    {
                        "id": "rent-update-regime",
                        "outcome_code": "synthetic-confirmed",
                        "source_ids": ["es-irav-ine"],
                    },
                    {
                        "id": "security-deposit-filing",
                        "outcome_code": "synthetic-confirmed",
                        "source_ids": ["es-md-deposit-service"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return request


def test_resolver_captures_live_official_evidence() -> None:
    # Given
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            request = _write_request(
                workspace,
                f"http://127.0.0.1:{server.server_port}",
            )
            output = workspace / "resolution.yaml"

            # When
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "--script",
                    str(RESOLVER),
                    str(request),
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Then
            assert result.returncode == 0, result.stdout + result.stderr
            resolution = _Resolution.model_validate(
                yaml.safe_load(output.read_text(encoding="utf-8")),
            )
            assert resolution.status == "complete"
            evidence = tuple(
                item
                for check in resolution.checks
                for item in check.evidence
            )
            assert tuple(item.source_id for item in evidence) == (
                "es-rental-reference-system",
                "es-irav-ine",
                "es-md-deposit-service",
            )
            assert all(item.status_code == 200 for item in evidence)
            assert all(len(item.content_sha256) == 64 for item in evidence)
            assert evidence[0].content_sha256 == hashlib.sha256(
                b"official-test:/es-rental-reference-system",
            ).hexdigest()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
