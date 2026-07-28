# Setup

## Contract

The setup is dry-run-first:

```bash
bash scripts/doctor.sh
bash scripts/setup.sh
bash scripts/setup.sh --apply
bash scripts/setup.sh --apply --with-weasyprint
bash scripts/setup.sh --apply --with-libreoffice
bash scripts/setup.sh --apply --with-openssh
```

`doctor.sh` is read-only. It reports:

- required commands: `python3`, `uv`, and `pandoc`;
- optional office conversion: `soffice` or `libreoffice`;
- optional CSS-based PDF: `weasyprint`;
- optional governed-release signatures: `ssh-keygen` from OpenSSH;
- resulting rendering and export capabilities.

`setup.sh` calls the doctor first. On macOS with Homebrew, it installs missing
required tools, links the skill through agent-brain's `skill_link.sh`, and
calls the doctor again. Without `--apply`, it only prints the proposed actions.

Missing optional tools are explained separately:

- WeasyPrint: PDF generated from HTML and CSS.
- LibreOffice: edit reference files and convert Office documents to PDF.
- OpenSSH: detached signatures and trust verification for governed releases.

With `--apply`, unspecified optional tools are offered interactively. Use
`--non-interactive` to decline unspecified options in automation. Select or
decline them explicitly with:

```bash
--with-weasyprint
--without-weasyprint
--with-libreoffice
--without-libreoffice
--with-openssh
--without-openssh
--with-all-optional
```

The setup is idempotent. Installed tools are skipped, existing skill links are
preserved, and rerunning it can add an optional tool declined previously.

Jinja2 and the Python JSON Schema validator are not installed globally.
Rendering scripts declare them as isolated dependencies resolved by `uv`.

ShellCheck is a development-only static analyzer. It validates the Bash
scripts but is not a runtime dependency and is not offered by the setup.

## Failure handling

- Exit `0`: requested check or dry-run completed.
- Exit `1`: the doctor found missing required tools.
- Exit `2`: invocation or automatic-install platform is unsupported.

If automatic installation is unsupported, install the reported commands using
the platform package manager and rerun the doctor.
