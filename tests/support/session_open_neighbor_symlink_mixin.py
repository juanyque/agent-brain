from __future__ import annotations

import tempfile
from pathlib import Path

from tests.support.session_open_test_support import (
    prepare_daily_note,
    snapshot_tree,
)


class SessionOpenNeighborSymlinkMixin:
    def test_prepare_daily_rejects_previous_neighbor_symlink_without_external_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            outside = root / "outside"
            brain.mkdir()
            outside.mkdir()
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.daily-note.common.md").write_text(
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n\n"
                "# Sessions\n\n# Actions\n",
                encoding="utf-8",
            )
            journal = brain / "JOURNAL"
            journal.mkdir()
            sentinel = outside / "previous.md"
            sentinel.write_text(
                "[[2026-07-14]] <- x -> [[2026-07-16]]\n",
                encoding="utf-8",
            )
            (journal / "2026-07-15.md").symlink_to(sentinel)
            today = journal / "2026-07-22.md"
            brain_before = snapshot_tree(brain)
            outside_before = sentinel.read_bytes()

            with self.assertRaisesRegex(OSError, "unsafe daily path"):
                prepare_daily_note(brain, today, "2026-07-22", apply=True)

            self.assertEqual(snapshot_tree(brain), brain_before)
            self.assertEqual(sentinel.read_bytes(), outside_before)
            self.assertFalse(today.exists())

    def test_prepare_daily_rejects_next_neighbor_symlink_without_external_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            outside = root / "outside"
            brain.mkdir()
            outside.mkdir()
            templates = brain / "TEMPLATES"
            templates.mkdir()
            (templates / "TEMPLATE.daily-note.common.md").write_text(
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n\n"
                "# Sessions\n\n# Actions\n",
                encoding="utf-8",
            )
            journal = brain / "JOURNAL"
            journal.mkdir()
            sentinel = outside / "next.md"
            sentinel.write_text(
                "[[2026-07-28]] <- x -> [[2026-07-30]]\n",
                encoding="utf-8",
            )
            (journal / "2026-07-29.md").symlink_to(sentinel)
            today = journal / "2026-07-22.md"
            brain_before = snapshot_tree(brain)
            outside_before = sentinel.read_bytes()

            with self.assertRaisesRegex(OSError, "unsafe daily path"):
                prepare_daily_note(brain, today, "2026-07-22", apply=True)

            self.assertEqual(snapshot_tree(brain), brain_before)
            self.assertEqual(sentinel.read_bytes(), outside_before)
            self.assertFalse(today.exists())
