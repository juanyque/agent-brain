from __future__ import annotations

import re
from typing import Final


ABSOLUTE_COMMON_MARKDOWN_PATH: Final = re.compile(
    r"(?<![\w.-])/(?:(?!\s)[^`'\"<>\])])+\.common\.md"
)


def first_absolute_common_markdown_path(text: str) -> str | None:
    matches = sorted({match.group(0) for match in ABSOLUTE_COMMON_MARKDOWN_PATH.finditer(text)})
    if not matches:
        return None
    return matches[0]
