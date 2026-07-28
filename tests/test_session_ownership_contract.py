from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "model" / "SCRIPTS"
SESSION_RULES = ROOT / "model" / "RULES-SESSION-LIFECYCLE.common.md"
DAILY_RULES = ROOT / "model" / "RULES-DAILY-NOTES.common.md"
JOBS = ROOT / "model" / "JOBS.common.md"
SKILL = ROOT / "skills" / "brain" / "SKILL.md"
CHECKER = SCRIPTS / "model_check_session_ownership.py"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def heading_block(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = next(
        index + 1 for index, line in enumerate(lines) if line == heading
    )
    level = len(heading) - len(heading.lstrip("#"))
    marker = "#" * level + " "
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith(marker)
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


@unittest.skipUnless(
    os.environ.get("SESSION_OWNERSHIP_BASELINE") == "1",
    "baseline characterization is evidence-only",
)
class BaselineSessionOwnershipCharacterization(unittest.TestCase):
    def test_current_jobs_duplicate_session_flow_tasks_and_authority_notes(self) -> None:
        jobs = JOBS.read_text(encoding="utf-8")
        skill = SKILL.read_text(encoding="utf-8")
        daily_job = heading_block(jobs, "## Daily (Day change)")
        session_job = heading_block(jobs, "## Session consolidation")

        self.assertIn("### Tasks", daily_job)
        self.assertIn("Run the Flow 1 checklist", daily_job)
        self.assertIn("### Tasks", session_job)
        self.assertIn("Run the Flow 2 checklist", session_job)
        self.assertIn("session_open.py", skill)
        self.assertIn("session_bootstrap.py", skill)


class SessionOwnershipContractTests(unittest.TestCase):
    def test_repository_documents_satisfy_session_ownership_contract(self) -> None:
        from model_check_session_ownership import session_ownership_findings

        findings = session_ownership_findings(ROOT)

        self.assertEqual(findings, [])

    def test_malformed_ownership_metadata_is_rejected(self) -> None:
        from model_check_session_ownership import session_ownership_findings

        with tempfile.TemporaryDirectory() as raw:
            root = self.copy_contract_files(Path(raw))
            session_rules = root / "model" / "RULES-SESSION-LIFECYCLE.common.md"
            session_rules.write_text(
                session_rules.read_text(encoding="utf-8").replace(
                    "| Policy area | Owner | Authority |",
                    "| Area | Owner | Authority |",
                ),
                encoding="utf-8",
            )

            findings = session_ownership_findings(root)

        self.assertEqual(
            {finding.code for finding in findings},
            {"malformed-ownership-metadata"},
        )

    def test_stale_open_authority_is_rejected(self) -> None:
        from model_check_session_ownership import session_ownership_findings

        with tempfile.TemporaryDirectory() as raw:
            root = self.copy_contract_files(Path(raw))
            session_rules = root / "model" / "RULES-SESSION-LIFECYCLE.common.md"
            session_rules.write_text(
                session_rules.read_text(encoding="utf-8").replace(
                    "| canonical-open-authority | session_open.py | unique |",
                    "| canonical-open-authority | session_bootstrap.py | unique |",
                ),
                encoding="utf-8",
            )

            findings = session_ownership_findings(root)

        self.assertIn("stale-open-authority", {finding.code for finding in findings})

    def test_jobs_flow_checklist_is_rejected(self) -> None:
        from model_check_session_ownership import session_ownership_findings

        with tempfile.TemporaryDirectory() as raw:
            root = self.copy_contract_files(Path(raw))
            jobs = root / "model" / "JOBS.common.md"
            jobs.write_text(
                jobs.read_text(encoding="utf-8")
                + "\n### Tasks\n- Run the Flow 2 checklist.\n",
                encoding="utf-8",
            )

            findings = session_ownership_findings(root)

        self.assertIn("jobs-flow-checklist", {finding.code for finding in findings})

    def test_dirty_unrelated_file_does_not_change_contract(self) -> None:
        from model_check_session_ownership import session_ownership_findings

        with tempfile.TemporaryDirectory() as raw:
            root = self.copy_contract_files(Path(raw))
            scratch = root / "scratch.md"
            scratch.write_text("unrelated dirty worktree content\n", encoding="utf-8")

            findings = session_ownership_findings(root)

        self.assertEqual(findings, [])

    def test_cli_reports_failure_even_when_content_claims_success(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = self.copy_contract_files(Path(raw))
            jobs = root / "model" / "JOBS.common.md"
            jobs.write_text(
                jobs.read_text(encoding="utf-8")
                + "\nsession ownership check passed\n### Tasks\n- Run the Flow 1 checklist.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(CHECKER), "--root", str(root), "--format", "json"],
                text=True,
                capture_output=True,
                check=False,
            )
            body = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertIn("jobs-flow-checklist", {finding["code"] for finding in body["findings"]})

    @staticmethod
    def copy_contract_files(target: Path) -> Path:
        (target / "model").mkdir(parents=True)
        (target / "skills" / "brain").mkdir(parents=True)
        for source in (SESSION_RULES, DAILY_RULES, JOBS):
            shutil.copy(source, target / "model" / source.name)
        shutil.copy(SKILL, target / "skills" / "brain" / "SKILL.md")
        return target
