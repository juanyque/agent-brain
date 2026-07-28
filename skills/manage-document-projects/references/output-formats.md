# Output formats

## Selection

| Output | Formatting mechanism | Best use |
| --- | --- | --- |
| HTML | CSS via `--css` | Browser review and web delivery |
| PDF from HTML | CSS plus `--pdf-engine=weasyprint` | Precise printable layouts using web styling |
| DOCX | `--reference-doc=reference.docx` | Editable Word delivery |
| ODT | `--reference-doc=reference.odt` | Editable LibreOffice delivery |
| PDF from LaTeX | Pandoc template and LaTeX variables | Traditional typesetting and complex numbering |
| PDF from Typst | Typst template and variables | Modern programmable typesetting |

Pandoc's `--css` styles HTML-family output. It does not style DOCX or ODT.
Those formats take paragraph, character, table, page, and numbering styles from
a reference document.

## PDF engine choice

Use WeasyPrint as the recommended optional engine when the project wants to
reuse HTML and CSS. It is open source, supports paged-media CSS, and keeps the
formatting profile approachable.

Consider Typst when precise typesetting, fast compilation, PDF/A, or PDF/UA is
more important than CSS reuse. It requires a separate Typst template.

Consider Paged.js only when browser-based paged-media behavior justifies adding
Node and a browser runtime. Avoid wkhtmltopdf for new profiles because its
upstream repository is archived. Treat Prince as a commercial option rather
than a portable default.

## CSS-based PDF

Use the HTML writer and an HTML PDF engine:

```bash
pandoc input.md \
  --standalone \
  --to=html5 \
  --css=document.css \
  --pdf-engine=weasyprint \
  --output=document.pdf
```

For the standard Jinja to Markdown to PDF circuit, use the skill renderer:

```bash
uv run scripts/render_document.py \
  template.md.j2 \
  document.yaml \
  generated/document.pdf
```

The rendered Markdown is kept beside the PDF. Missing Jinja variables fail
before either output is written, and an existing PDF is never overwritten.

Start from `assets/profiles/css-pdf/document.css`. Copy it into the project so
the project's output profile is versioned with its templates.

CSS is attractive for contracts because it controls page size, margins,
typography, page breaks, table behavior, and page counters. Always inspect the
result because CSS support differs between browsers and PDF engines.

## DOCX and ODT

Create reference documents from Pandoc's defaults, edit their named styles in
Word or LibreOffice, and keep the resulting files as versioned output-profile
assets:

```bash
pandoc --print-default-data-file reference.docx > reference.docx
pandoc --print-default-data-file reference.odt > reference.odt
pandoc input.md --reference-doc=reference.docx --output=document.docx
pandoc input.md --reference-doc=reference.odt --output=document.odt
```

Do not manually format each generated document. Modify the reference document
or canonical Markdown and regenerate.

## Sources

- [Pandoc User's Guide](https://pandoc.org/MANUAL.html)
- [WeasyPrint documentation](https://doc.courtbouillon.org/weasyprint/stable/)
- [Typst documentation](https://typst.app/docs/)
- [Paged.js](https://pagedjs.org/en/about/)
- [wkhtmltopdf archive](https://github.com/wkhtmltopdf/wkhtmltopdf)
