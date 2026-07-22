# profile_secrets.py

## Purpose

Check whether secret references declared by the selected environment profile are available
without reading, printing, serializing, diffing, or logging any secret value.

The preflight supports three reference kinds:

- `environment`: checks only whether the named variable contains a non-empty value;
- `keychain`: remains unresolved unless the metadata-only macOS adapter is selected;
- `runtime`: consumes a sanitized name-only catalog supplied by the active runtime adapter.

Required references must resolve to `available`; `missing`, `unavailable`, and `adapter-check`
produce a non-zero exit. Optional unresolved references are reported without failing.

## Usage

Static environment-reference preflight:

```bash
python3 profile_secrets.py --brain /path/to/brain
```

Include the macOS keychain metadata adapter:

```bash
python3 profile_secrets.py --brain /path/to/brain --keychain macos
```

Supply an authoritative runtime-native name catalog:

```bash
python3 profile_secrets.py \
  --brain /path/to/brain \
  --runtime-secret tracker-session \
  --runtime-catalog-complete
```

The macOS adapter executes `security find-generic-password -s <name>` with standard input,
standard output, and standard error connected to the null device. It never passes `-w`, never
captures command output, and times out after five seconds. Other platforms remain
`adapter-check` until a similarly metadata-only contract exists.

Runtime adapters must provide names only. They must not pass values, endpoints, headers, tokens,
or raw runtime configuration to this command.
