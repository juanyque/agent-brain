from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "brain" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from attachment_destinations import (  # noqa: E402
    AttachmentDestinationError,
    flat_attachment_shape,
    is_flat_attachment_destination,
    require_flat_attachment_destination,
)
from attachments_audit import (  # noqa: E402
    AttachmentReport,
    audit_folder,
    build_markdown_index,
    validate_destinations,
)


class FlatDestinationTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_table(self) -> None:
        cases = [
            ("WIP/ATTACHMENTS/flat.pdf", True),
            ("QUARANTINE/ATTACHMENTS/orphan.pdf", True),
            ("WIP/ATTACHMENTS/topic/one-level.pdf", False),
            ("WIP/ATTACHMENTS/topic/deeper/two-level.pdf", False),
            ("WIP/project/documents/ATTACHMENTS/note-local.pdf", True),
            ("WIP/no-attachment-dir/outside.pdf", False),
            ("WIP/ATTACHMENTS/topic/ATTACHMENTS/repeated.pdf", False),
            ("WIP/attachments/lowercase.pdf", False),
            ("WIP/ATTACHMENTS/../ATTACHMENTS/dotdot.pdf", False),
        ]
        for rel, expected in cases:
            with self.subTest(rel=rel):
                result = is_flat_attachment_destination(self.brain / rel)
                self.assertEqual(result, expected)

    def test_brain_root_containment_is_enforced(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        self.assertFalse(
            is_flat_attachment_destination(
                outside / "ATTACHMENTS" / "x.pdf", brain_root=self.brain
            )
        )
        self.assertTrue(
            is_flat_attachment_destination(
                self.brain / "WIP" / "ATTACHMENTS" / "x.pdf",
                brain_root=self.brain,
            )
        )

    def test_require_returns_resolved_path(self) -> None:
        destination = require_flat_attachment_destination(
            self.brain / "WIP" / "ATTACHMENTS" / "x.pdf"
        )
        self.assertEqual(
            destination, (self.brain / "WIP" / "ATTACHMENTS" / "x.pdf").resolve()
        )

    def test_require_raises_with_message(self) -> None:
        with self.assertRaises(AttachmentDestinationError):
            require_flat_attachment_destination(
                self.brain / "WIP" / "ATTACHMENTS" / "topic" / "x.pdf"
            )

    def test_unknown_user_expansion_returns_false(self) -> None:
        self.assertFalse(
            is_flat_attachment_destination("~definitely-no-such-user/ATTACHMENTS/x.pdf")
        )
        with self.assertRaises(AttachmentDestinationError):
            require_flat_attachment_destination(
                "~definitely-no-such-user/ATTACHMENTS/x.pdf"
            )

    def test_uninspectable_leaf_is_contracted_not_raised(self) -> None:
        with unittest.mock.patch.object(
            Path,
            "is_symlink",
            side_effect=PermissionError("denied"),
        ):
            self.assertFalse(
                is_flat_attachment_destination(
                    self.brain / "WIP" / "ATTACHMENTS" / "x.pdf"
                )
            )
            with self.assertRaises(AttachmentDestinationError):
                require_flat_attachment_destination(
                    self.brain / "WIP" / "ATTACHMENTS" / "x.pdf"
                )

    def test_dangling_symlink_destination_is_rejected_by_the_helper(self) -> None:
        destination = self.brain / "MEMORY" / "ATTACHMENTS" / "ghost.pdf"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(self.brain / "nowhere" / "missing.pdf")
        self.assertFalse(destination.exists())
        self.assertTrue(destination.is_symlink())
        self.assertFalse(is_flat_attachment_destination(destination))
        with self.assertRaises(AttachmentDestinationError):
            require_flat_attachment_destination(destination, brain_root=self.brain)

    def test_move_file_refuses_dangling_symlink_destination(self) -> None:
        destination = self.brain / "MEMORY" / "ATTACHMENTS" / "ghost.pdf"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(self.brain / "nowhere" / "missing.pdf")
        src = self.brain / "WIP" / "ATTACHMENTS" / "a.pdf"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"a")
        with self.assertRaises(AttachmentDestinationError):
            from attachments_audit import move_file

            move_file(src, destination, self.brain, use_git_mv=False)
        self.assertTrue(destination.is_symlink())

    def test_symlinked_brain_root_keeps_containment(self) -> None:
        alias = self.brain.parent / "brain-alias"
        alias.symlink_to(self.brain)
        self.addCleanup(alias.unlink)
        destination = self.brain / "WIP" / "ATTACHMENTS" / "x.pdf"
        resolved = require_flat_attachment_destination(
            destination, brain_root=alias
        )
        self.assertEqual(resolved.parent, (self.brain / "WIP" / "ATTACHMENTS").resolve())


class AuditorContractTests(unittest.TestCase):
    """The auditor never proposes a destination the helper rejects."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name).resolve()
        self.attachments = self.brain / "WIP" / "ATTACHMENTS"
        nested = self.attachments / "topic" / "deeper"
        nested.mkdir(parents=True)
        (self.attachments / "flat.pdf").write_bytes(b"flat")
        (self.attachments / "topic" / "one.pdf").write_bytes(b"one")
        (nested / "two.pdf").write_bytes(b"two")
        wip_note = self.brain / "WIP" / "owner.md"
        wip_note.write_text(
            "[[flat.pdf]] [[one.pdf]] [[two.pdf]]\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_every_proposed_destination_passes_the_helper(self) -> None:
        index = build_markdown_index(self.brain)
        reports = audit_folder(
            self.brain,
            self.attachments,
            self.brain / "QUARANTINE" / "ATTACHMENTS",
            index,
        )
        self.assertEqual(len(reports), 3)
        by_name = {r.attachment.name: r for r in reports}
        self.assertEqual(by_name["flat.pdf"].status, "KEEP_LOCAL")
        for report in reports:
            if report.proposed_destination is None:
                continue
            self.assertTrue(
                is_flat_attachment_destination(
                    report.proposed_destination, brain_root=self.brain
                ),
                msg=f"{report.attachment.name} -> {report.proposed_destination}",
            )
        for name in ("one.pdf", "two.pdf"):
            self.assertEqual(by_name[name].status, "RELOCATE_CANDIDATE")
            self.assertEqual(
                by_name[name].proposed_destination.parent,
                self.brain / "WIP" / "ATTACHMENTS",
            )

    def test_nested_sources_are_discovered_recursively(self) -> None:
        index = build_markdown_index(self.brain)
        reports = audit_folder(
            self.brain,
            self.attachments,
            self.brain / "QUARANTINE" / "ATTACHMENTS",
            index,
        )
        names = {r.attachment.name for r in reports}
        self.assertEqual(names, {"flat.pdf", "one.pdf", "two.pdf"})


class ValidateDestinationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name).resolve()
        self.attachments = self.brain / "WIP" / "ATTACHMENTS"
        self.attachments.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def report(
        self,
        name: str,
        status: str,
        source: Path,
        destination: Path | None,
    ) -> AttachmentReport:
        return AttachmentReport(
            attachment=source,
            status=status,
            references=[],
            proposed_destination=destination,
            note="",
        )

    def test_clean_batch_has_no_errors(self) -> None:
        src = self.attachments / "a.pdf"
        src.write_bytes(b"a")
        reports = [
            self.report(
                "a.pdf",
                "RELOCATE_CANDIDATE",
                src,
                self.brain / "MEMORY" / "ATTACHMENTS" / "a.pdf",
            )
        ]
        self.assertEqual(validate_destinations(reports, self.brain), [])

    def test_source_equal_destination_is_flagged(self) -> None:
        src = self.brain / "QUARANTINE" / "ATTACHMENTS" / "a.pdf"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"a")
        reports = [
            self.report(
                "a.pdf",
                "ORPHAN_CANDIDATE",
                src,
                src,
            )
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(any("no-op" in e for e in errors))

    def test_duplicate_destinations_across_reports_are_flagged(self) -> None:
        first = self.attachments / "a.pdf"
        second = self.brain / "MEMORY" / "ATTACHMENTS" / "a.pdf"
        second.parent.mkdir(parents=True)
        first.write_bytes(b"a")
        second.write_bytes(b"b")
        destination = self.brain / "JOURNAL" / "ATTACHMENTS" / "a.pdf"
        reports = [
            self.report("a.pdf", "RELOCATE_CANDIDATE", first, destination),
            self.report("a.pdf", "RELOCATE_CANDIDATE", second, destination),
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(any("collides" in e for e in errors))

    def test_existing_destination_is_flagged(self) -> None:
        src = self.attachments / "a.pdf"
        src.write_bytes(b"a")
        destination = self.brain / "MEMORY" / "ATTACHMENTS" / "a.pdf"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"existing")
        reports = [
            self.report("a.pdf", "RELOCATE_CANDIDATE", src, destination)
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(any("already exists" in e for e in errors))

    def test_destination_outside_brain_root_is_flagged(self) -> None:
        src = self.attachments / "a.pdf"
        src.write_bytes(b"a")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        reports = [
            self.report(
                "a.pdf",
                "RELOCATE_CANDIDATE",
                src,
                outside / "ATTACHMENTS" / "a.pdf",
            )
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(errors)

    def test_keep_local_outside_brain_root_is_not_flagged(self) -> None:
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        src = outside / "ATTACHMENTS" / "a.pdf"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"a")
        reports = [
            self.report("a.pdf", "KEEP_LOCAL", src, src)
        ]
        self.assertEqual(validate_destinations(reports, self.brain), [])

    def test_collision_detected_via_no_op_report(self) -> None:
        first_src = self.brain / "QUARANTINE" / "ATTACHMENTS" / "a.pdf"
        first_src.parent.mkdir(parents=True)
        first_src.write_bytes(b"a")
        destination = first_src
        second_src = self.attachments / "a.pdf"
        second_src.write_bytes(b"a")
        reports = [
            self.report("a.pdf", "ORPHAN_CANDIDATE", first_src, destination),
            self.report(
                "a.pdf",
                "RELOCATE_CANDIDATE",
                second_src,
                self.brain / "QUARANTINE" / "ATTACHMENTS" / "a.pdf",
            ),
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(any("no-op" in e for e in errors))
        self.assertTrue(any("collides" in e for e in errors))

    def test_case_variant_destinations_collide(self) -> None:
        first = self.attachments / "Report.pdf"
        second = self.brain / "MEMORY" / "ATTACHMENTS" / "report.pdf"
        second.parent.mkdir(parents=True)
        first.write_bytes(b"a")
        second.write_bytes(b"b")
        reports = [
            self.report(
                "Report.pdf",
                "RELOCATE_CANDIDATE",
                first,
                self.brain / "JOURNAL" / "ATTACHMENTS" / "Report.pdf",
            ),
            self.report(
                "report.pdf",
                "RELOCATE_CANDIDATE",
                second,
                self.brain / "JOURNAL" / "ATTACHMENTS" / "report.pdf",
            ),
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(any("collides" in e for e in errors))

    def test_case_variant_parent_spellings_collide(self) -> None:
        first = self.attachments / "a.pdf"
        first.write_bytes(b"a")
        second = self.attachments / "b.pdf"
        second.write_bytes(b"b")
        reports = [
            self.report(
                "a.pdf",
                "RELOCATE_CANDIDATE",
                first,
                self.brain / "JOURNAL" / "Day" / "ATTACHMENTS" / "x.pdf",
            ),
            self.report(
                "b.pdf",
                "RELOCATE_CANDIDATE",
                second,
                self.brain / "JOURNAL" / "day" / "ATTACHMENTS" / "x.pdf",
            ),
        ]
        errors = validate_destinations(reports, self.brain)
        self.assertTrue(any("collides" in e for e in errors))

    def test_keep_local_symlink_source_does_not_block(self) -> None:
        real_file = self.brain / "MEMORY" / "target.pdf"
        real_file.parent.mkdir(parents=True, exist_ok=True)
        real_file.write_bytes(b"real")
        symlink_source = self.attachments / "linked.pdf"
        symlink_source.symlink_to(real_file)
        (self.brain / "WIP" / "owner.md").write_text(
            "[[linked.pdf]]\n", encoding="utf-8"
        )
        index = build_markdown_index(self.brain)
        reports = audit_folder(
            self.brain,
            self.attachments,
            self.brain / "QUARANTINE" / "ATTACHMENTS",
            index,
        )
        by_name = {r.attachment.name: r for r in reports}
        self.assertEqual(by_name["linked.pdf"].status, "KEEP_LOCAL")
        self.assertEqual(validate_destinations(reports, self.brain), [])

    def test_keep_local_under_symlinked_attachments_dir_passes_shape(self) -> None:
        storage = self.brain / "MEMORY" / "storage"
        storage.mkdir(parents=True)
        (storage / "x.pdf").write_bytes(b"x")
        linked_dir = self.brain / "MEMORY" / "ATTACHMENTS"
        linked_dir.symlink_to(storage)
        destination = linked_dir / "x.pdf"
        self.assertTrue(flat_attachment_shape(destination))
        reports = [
            self.report("x.pdf", "KEEP_LOCAL", destination, destination)
        ]
        self.assertEqual(validate_destinations(reports, self.brain), [])


if __name__ == "__main__":
    unittest.main()
