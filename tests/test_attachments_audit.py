from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
SCRIPT = SCRIPTS_DIR / "attachments_audit.py"
sys.path.insert(0, str(SCRIPTS_DIR))

from attachments_audit import (
    apply_reports,
    audit_folder,
    build_markdown_index,
    find_attachment_dirs,
)


class AttachmentsAuditTests(unittest.TestCase):
    def test_cli_dry_run_audits_one_nested_project_without_moving_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = brain / "WIP" / "project" / "documents" / "contract.md"
            note.parent.mkdir(parents=True)
            note.write_text("![[inventory-photo.jpg]]\n", encoding="utf-8")
            nested = brain / "WIP" / "ATTACHMENTS" / "project" / "inventory-photo.jpg"
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b"photo")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--brain-root",
                    str(brain),
                    "--scope-root",
                    "WIP/ATTACHMENTS/project",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status: RELOCATE_CANDIDATE", result.stdout)
            self.assertIn("WIP/project/documents/ATTACHMENTS/inventory-photo.jpg", result.stdout)
            self.assertTrue(nested.is_file())

    def test_nested_attachment_roots_are_audited_once_from_the_outer_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            scope = Path(raw) / "WIP"
            outer = scope / "ATTACHMENTS"
            (outer / "project" / "ATTACHMENTS").mkdir(parents=True)

            roots = find_attachment_dirs(scope)

        self.assertEqual(roots, [outer])

    def test_attachment_subtree_can_be_selected_as_the_narrow_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            subtree = Path(raw) / "WIP" / "ATTACHMENTS" / "active-project"
            subtree.mkdir(parents=True)

            roots = find_attachment_dirs(subtree)

        self.assertEqual(roots, [subtree])

    def test_nested_attachment_is_relocated_to_owning_notes_flat_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = brain / "WIP" / "project" / "documents" / "contract.md"
            note.parent.mkdir(parents=True)
            note.write_text("![[inventory-photo.jpg]]\n", encoding="utf-8")
            attachment_root = brain / "WIP" / "ATTACHMENTS"
            nested = attachment_root / "project" / "inventory" / "inventory-photo.jpg"
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b"photo")

            reports = audit_folder(
                brain,
                attachment_root,
                brain / "QUARANTINE" / "ATTACHMENTS",
                build_markdown_index(brain),
            )

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].status, "RELOCATE_CANDIDATE")
        self.assertEqual(
            reports[0].proposed_destination,
            brain / "WIP" / "project" / "documents" / "ATTACHMENTS" / "inventory-photo.jpg",
        )

    def test_apply_removes_empty_nested_attachment_structure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = brain / "WIP" / "project" / "documents" / "contract.md"
            note.parent.mkdir(parents=True)
            note.write_text("![[inventory-photo.jpg]]\n", encoding="utf-8")
            attachment_root = brain / "WIP" / "ATTACHMENTS"
            nested = attachment_root / "project" / "inventory" / "inventory-photo.jpg"
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b"photo")
            reports = audit_folder(
                brain,
                attachment_root,
                brain / "QUARANTINE" / "ATTACHMENTS",
                build_markdown_index(brain),
            )

            apply_reports(reports, brain, use_git_mv=False)

            destination = note.parent / "ATTACHMENTS" / nested.name
            self.assertTrue(destination.is_file())
            self.assertFalse(attachment_root.exists())

    def test_duplicate_nested_basenames_are_never_automatic_move_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            brain = Path(raw)
            note = brain / "WIP" / "project" / "note.md"
            note.parent.mkdir(parents=True)
            note.write_text("![[photo.jpg]]\n", encoding="utf-8")
            attachment_root = brain / "WIP" / "ATTACHMENTS"
            for group in ("first", "second"):
                attachment = attachment_root / group / "photo.jpg"
                attachment.parent.mkdir(parents=True, exist_ok=True)
                attachment.write_bytes(group.encode())

            reports = audit_folder(
                brain,
                attachment_root,
                brain / "QUARANTINE" / "ATTACHMENTS",
                build_markdown_index(brain),
            )

        self.assertEqual(len(reports), 2)
        self.assertEqual(
            {report.status for report in reports},
            {"CONFLICT_DUPLICATE_BASENAME"},
        )
        self.assertTrue(all(report.proposed_destination is None for report in reports))


if __name__ == "__main__":
    unittest.main()
