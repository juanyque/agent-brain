# profile_context.py

## Purpose

Resolve generic capabilities through the environment profile selected for a working directory.
The command is read-only and intended for skills that must choose an environment-specific
provider without embedding private server, project, or repository values in public workflows.

## Safety boundary

The output may contain private policy from the selected brain, but never returns provider URLs,
commands from runtime registries, headers, environment values, tokens, or raw discovery output.
A runtime invocation is a hint, not permission. Without a complete caller-supplied tool catalog,
exposure remains `unverified`.

## Usage

```bash
python3 profile_context.py \
  --brain-root /path/to/brain \
  --cwd /path/to/project \
  --runtime codex \
  --capability issues.create

python3 profile_context.py \
  --brain-root /path/to/brain \
  --cwd /path/to/project \
  --runtime claude \
  --live \
  --include-policy \
  --capability issues.create \
  --capability issues.read
```

When the active agent can enumerate its own tool names safely, pass names only and mark the
catalog complete:

```bash
python3 profile_context.py \
  --brain-root /path/to/brain \
  --runtime codex \
  --capability issues.create \
  --available-tool '<exact-tool-name>' \
  --tool-catalog-complete
```

An exact MCP invocation absent from a complete catalog fails resolution. An incomplete or omitted
catalog never claims exposure. CLI/manual capabilities are reported as `not-applicable` because
their readiness is checked at the provider boundary instead.

`--live` supports sanitized Codex registry discovery. It distinguishes enabled, disabled, and
authentication-required registrations but does not probe connectivity. Claude discovery is
explicitly refused because its official list command may rewrite runtime settings; Claude callers
must use the caller-supplied active tool-catalog verification above. Other unsupported runtimes
also fail explicitly rather than assuming provider availability.

Exit code `0` means every requested capability resolved. Exit code `2` means profile validation,
runtime discovery, or capability resolution failed.
