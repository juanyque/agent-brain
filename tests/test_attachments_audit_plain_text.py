from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from attachments_audit import (  # noqa: E402
    audit_folder,
    build_markdown_index,
    build_plain_mention_index,
    has_bounded_occurrence,
    with_plain_mentions,
)


class BoundedOccurrenceTests(unittest.TestCase):
    def test_spaced_mention_matches(self) -> None:
        self.assertTrue(has_bounded_occurrence("see acta_2024.pdf there", "acta_2024.pdf"))

    def test_longer_filename_does_not_match(self) -> None:
        self.assertFalse(has_bounded_occurrence("final-acta_2024.pdfx", "acta_2024.pdf"))

    def test_glued_word_does_not_match(self) -> None:
        self.assertFalse(has_bounded_occurrence("mifacta_2024.pdf", "acta_2024.pdf"))


class PlainMentionIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_note(self, rel: str, content: str) -> Path:
        path = self.brain / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_plain_mention_outside_wikilinks_is_indexed(self) -> None:
        plain = self.write_note("MEMORY/other.md", "consulta el acta_2024.pdf si doubt")
        self.write_note("WIP/note.md", "check [[acta_2024.pdf]] please")
        index = build_plain_mention_index(self.brain, {"acta_2024.pdf"})
        self.assertEqual(index["acta_2024.pdf"], (plain,))

    def test_wikilink_only_note_is_not_indexed(self) -> None:
        self.write_note("WIP/note.md", "check [[acta_2024.pdf]] please")
        index = build_plain_mention_index(self.brain, {"acta_2024.pdf"})
        self.assertEqual(index["acta_2024.pdf"], ())

    def test_longer_filename_mention_is_not_indexed(self) -> None:
        self.write_note("MEMORY/other.md", "backup at final-acta_2024.pdfx")
        index = build_plain_mention_index(self.brain, {"acta_2024.pdf"})
        self.assertEqual(index["acta_2024.pdf"], ())


class AuditFolderWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        self.attachments = self.brain / "JOURNAL" / "2026-06-01" / "ATTACHMENTS"
        self.attachments.mkdir(parents=True)
        (self.attachments / "acta_2024.pdf").write_bytes(b"%PDF-1.4")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _audit(self) -> list:
        index = build_markdown_index(self.brain)
        reports = audit_folder(
            self.brain,
            self.attachments,
            self.brain / "QUARANTINE" / "ATTACHMENTS",
            index,
        )
        candidate_names = {
            r.attachment.name for r in reports if r.status in {"ORPHAN_CANDIDATE", "RELOCATE_CANDIDATE"}
        }
        mention_index = build_plain_mention_index(self.brain, candidate_names)
        return with_plain_mentions(reports, mention_index)

    def test_relocate_candidate_carries_plain_mention_warning(self) -> None:
        trash_note = self.brain / "QUARANTINE" / "TRASH" / "old.md"
        trash_note.parent.mkdir(parents=True)
        trash_note.write_text("[[acta_2024.pdf]]\n", encoding="utf-8")
        live = self.brain / "WIP"
        live.mkdir()
        (live / "live.md").write_text(
            "consulta el acta_2024.pdf si hay dudas\n", encoding="utf-8"
        )
        reports = self._audit()
        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertEqual(report.status, "RELOCATE_CANDIDATE")
        self.assertEqual(
            [p.name for p in report.plain_mentions], ["live.md"]
        )

    def test_keep_local_has_no_plain_mention_scan(self) -> None:
        owner = self.brain / "JOURNAL" / "2026-06-01"
        (owner / "note.md").write_text(
            "[[acta_2024.pdf]]\n", encoding="utf-8"
        )
        (self.brain / "WIP").mkdir()
        (self.brain / "WIP" / "live.md").write_text(
            "consulta el acta_2024.pdf\n", encoding="utf-8"
        )
        reports = self._audit()
        self.assertEqual(reports[0].status, "KEEP_LOCAL")
        self.assertEqual(reports[0].plain_mentions, ())

    def test_orphan_candidate_carries_plain_mention_warning(self) -> None:
        (self.brain / "WIP").mkdir()
        (self.brain / "WIP" / "live.md").write_text(
            "guarda el acta_2024.pdf\n", encoding="utf-8"
        )
        reports = self._audit()
        self.assertEqual(reports[0].status, "ORPHAN_CANDIDATE")
        self.assertEqual(
            [p.name for p in reports[0].plain_mentions], ["live.md"]
        )


if __name__ == "__main__":
    unittest.main()
