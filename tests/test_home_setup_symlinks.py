from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "model" / "SCRIPTS"
sys.path.insert(0, str(SCRIPTS_DIR))

from _common import Reporter  # noqa: E402
from home_setup import TEMPLATE_SYMLINKS, WRAPPERS, apply  # noqa: E402


def create_common(root: Path) -> Path:
    common = root / "model"
    common.mkdir()
    for common_name in WRAPPERS.values():
        (common / common_name).write_text(f"# {common_name}\n", encoding="utf-8")
    for common_rel in TEMPLATE_SYMLINKS.values():
        path = common / common_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.name}\n", encoding="utf-8")
    return common


class HomeSetupSymlinkTests(unittest.TestCase):
    def test_attach_repairs_managed_template_symlinks_from_previous_model(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            brain = root / "brain"
            brain.mkdir()
            common = create_common(root)
            old_common = root / "old-model"
            (brain / "TEMPLATES").mkdir()
            (brain / "_COMMON").symlink_to(common)

            for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
                old_source = old_common / common_rel
                old_source.parent.mkdir(parents=True, exist_ok=True)
                old_source.write_text("# stale model\n", encoding="utf-8")
                (brain / local_rel).symlink_to(old_source)

            reporter = Reporter(root / "home-setup.log")
            with redirect_stdout(io.StringIO()):
                apply(brain, common, True, True, reporter)

            for local_rel, common_rel in TEMPLATE_SYMLINKS.items():
                local_path = brain / local_rel
                self.assertEqual(os.readlink(local_path), f"../_COMMON/{common_rel}")
                self.assertEqual(local_path.resolve(), (common / common_rel).resolve())


if __name__ == "__main__":
    unittest.main()
