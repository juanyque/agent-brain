# Setup

## Contract

`setup.sh` is the single setup entry point. It checks required tools, resolves
optional-tool choices, creates or updates the workspace configuration, links
the skill into detected runtimes, and verifies the result. It is
dry-run-first:

```bash
bash scripts/setup.sh
bash scripts/setup.sh --apply
```

The configuration has one fixed location:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/manage-document-projects/config.yaml
```

There is no routine `--config` argument. `DOCUMENT_PROJECT_CONFIG_PATH` exists
for isolated tests and advanced embedding only. The same YAML file contains
`default_profile`, all workspace `profiles`, and the global `optional_tools`
choices:

```yaml
schema_version: manage-document-projects/config/v1
default_profile: default
optional_tools:
  weasyprint: install
  libreoffice: decline
  openssh: decline
profiles:
  default:
    workspace_root: /absolute/path/to/workspace
    locations:
      projects: projects
      deliverables: exports
      incoming: inbox
    policies:
      deliverables_git_visibility: unrestricted
      ingest_from_deliverables: forbidden
```

Omitting `--profile` always selects `default_profile`. A future multi-workspace
installation can add a named profile without changing command semantics.

`doctor.sh` remains available as a read-only diagnostic. It reports:

- required commands: `python3`, `uv`, and `pandoc`;
- optional office conversion: `soffice` or `libreoffice`;
- optional CSS-based PDF: `weasyprint`;
- optional governed-release signatures: `ssh-keygen` from OpenSSH;
- resulting rendering and export capabilities.

`setup.sh` calls the doctor first. On macOS with Homebrew, apply mode installs
missing required tools, writes only changed configuration, creates configured
directories, links the skill with its self-contained linker, and calls the
doctor again. Without `--apply`, it only prints the proposed actions.

Missing optional tools are explained separately:

- WeasyPrint: PDF generated from HTML and CSS.
- LibreOffice: edit reference files and convert Office documents to PDF.
- OpenSSH: detached signatures and trust verification for governed releases.

In an interactive terminal, current values are shown as defaults and missing
values are requested. A new standalone setup defaults to `projects`, `exports`,
and `inbox`; optional tools default to declined. Select or decline them
explicitly with:

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
preserved, unchanged YAML is not rewritten, and rerunning it can install an
optional tool declined previously. There is deliberately no
`--configure-only`: a configured but unusable installation is not a supported
state.

## Deterministic non-interactive setup

Automation supplies the same values either as arguments or environment
variables:

| Argument | Environment variable |
| --- | --- |
| `--profile` | `DOCUMENT_PROJECT_PROFILE` |
| `--workspace-root` | `DOCUMENT_PROJECT_WORKSPACE_ROOT` |
| `--projects-dir` | `DOCUMENT_PROJECT_PROJECTS_DIR` |
| `--deliverables-dir` | `DOCUMENT_PROJECT_DELIVERABLES_DIR` |
| `--incoming-dir` | `DOCUMENT_PROJECT_INCOMING_DIR` |
| `--git-visibility` | `DOCUMENT_PROJECT_GIT_VISIBILITY` |
| `--with-weasyprint` / `--without-weasyprint` | `DOCUMENT_PROJECT_WEASYPRINT_CHOICE=install\|decline` |
| `--with-libreoffice` / `--without-libreoffice` | `DOCUMENT_PROJECT_LIBREOFFICE_CHOICE=install\|decline` |
| `--with-openssh` / `--without-openssh` | `DOCUMENT_PROJECT_OPENSSH_CHOICE=install\|decline` |

An initial non-interactive setup requires an absolute workspace root. Existing
configuration values become defaults on later runs, so a repeated
`setup.sh --apply --non-interactive` is a no-op unless the environment or
machine state changed.

For an agent-brain workspace, use this deterministic mapping:

```bash
bash scripts/setup.sh --apply --non-interactive \
  --profile default \
  --workspace-root /path/to/brain \
  --projects-dir WIP \
  --deliverables-dir OUTBOX \
  --incoming-dir INBOX \
  --git-visibility required \
  --with-weasyprint \
  --without-libreoffice \
  --without-openssh
```

Change only the optional-tool choices the user has selected. OpenSSH is needed
for governed releases; LibreOffice is needed for editable Office workflows.
The brain adapter does not need a special code path or a second configuration
file.

`render_document.py` and `release_document.py` check for the fixed
configuration before resolving a profile. If it is missing, they run
`setup.sh --apply`. A non-interactive caller must set
`DOCUMENT_PROJECT_SETUP_NON_INTERACTIVE=1` and the setup variables above so
that bootstrap cannot depend on prompts.

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
