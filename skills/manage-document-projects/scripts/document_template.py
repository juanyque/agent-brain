from __future__ import annotations

from pathlib import Path

from clause_selection import DocumentData
from document_formatting import es_date, es_iban, es_money, es_number
from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment


def render_markdown(
    *,
    template: Path,
    data: DocumentData,
    release_status: str,
    fragment_paths: tuple[str, ...],
) -> str:
    environment = SandboxedEnvironment(
        loader=FileSystemLoader(template.parent),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    environment.filters.update(
        {
            "es_date": es_date,
            "es_iban": es_iban,
            "es_money": es_money,
            "es_number": es_number,
        },
    )
    context = {
        **data.root,
        "document_release_status": release_status,
        "selected_clause_fragments": list(fragment_paths),
    }
    return environment.get_template(template.name).render(context)
