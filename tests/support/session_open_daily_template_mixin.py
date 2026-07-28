from __future__ import annotations

import tempfile
from pathlib import Path

from tests.support.session_open_test_support import instantiate_daily_template


class SessionOpenDailyTemplateMixin:
    def test_daily_template_is_prepared_with_empty_sessions_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            template = Path(raw) / "daily.md"
            template.write_text(
                "---\ntags: [daily]\n---\n"
                "[[<% tp.date.yesterday() %>]] <- x -> "
                "[[<% tp.date.tomorrow() %>]]\n"
                "<% tp.file.cursor() %>\n\n"
                "# Sessions\n"
                "- REPLACE WITH REAL SESSION_ID: placeholder\n"
                "- Example (Codex): `codex resume uuid`\n\n"
                "# Actions\n* [[WORK]]:\n",
                encoding="utf-8",
            )
            daily = instantiate_daily_template(template, "2026-07-21")
        self.assertIn("[[2026-07-20]] <- x -> [[2026-07-22]]", daily)
        self.assertIn("# Sessions\n\n# Actions", daily)
        self.assertNotIn("REPLACE WITH REAL", daily)
        self.assertNotIn("Example (Codex)", daily)
        self.assertNotIn("tp.file.cursor", daily)
