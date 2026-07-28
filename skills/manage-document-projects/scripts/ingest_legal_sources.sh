#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_SOURCE_LIST="$SKILL_DIR/assets/project-types/residential-lease/jurisdictions/es-md-madrid/legal-sources/static-sources.tsv"
DEFAULT_OUTPUT_ROOT="$SKILL_DIR/assets/project-types/residential-lease/jurisdictions/es-md-madrid/legal-sources/snapshots"

APPLY=0
SNAPSHOT_DATE="$(date +%F)"
SOURCE_LIST="$DEFAULT_SOURCE_LIST"
OUTPUT_ROOT="$DEFAULT_OUTPUT_ROOT"

print_usage() {
  printf '%s\n' \
    'Usage:' \
    '  ingest_legal_sources.sh [options]' \
    '' \
    'Options:' \
    '  --apply                 download and normalize the configured sources' \
    '  --date YYYY-MM-DD       snapshot date; defaults to today' \
    '  --source-list PATH      tab-separated static source inventory' \
    '  --output-root PATH      parent directory for dated snapshots' \
    '  -h, --help              show this help' \
    '' \
    'The command is dry-run by default. Existing dated snapshots are never overwritten.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      ;;
    --date)
      [[ $# -ge 2 ]] || {
        printf 'ERROR: --date requires a value\n' >&2
        exit 2
      }
      SNAPSHOT_DATE="$2"
      shift
      ;;
    --source-list)
      [[ $# -ge 2 ]] || {
        printf 'ERROR: --source-list requires a path\n' >&2
        exit 2
      }
      SOURCE_LIST="$2"
      shift
      ;;
    --output-root)
      [[ $# -ge 2 ]] || {
        printf 'ERROR: --output-root requires a path\n' >&2
        exit 2
      }
      OUTPUT_ROOT="$2"
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      printf 'ERROR: unexpected argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
  shift
done

require_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'ERROR: required tool is missing: %s\n' "$1" >&2
    exit 2
  }
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

validate_source_id() {
  case "$1" in
    ""|*[!a-z0-9-]*)
      printf 'ERROR: invalid source id: %s\n' "$1" >&2
      exit 2
      ;;
  esac
}

require_tool curl
require_tool pandoc
require_tool python3
require_tool shasum

[[ -f "$SOURCE_LIST" ]] || {
  printf 'ERROR: source list not found: %s\n' "$SOURCE_LIST" >&2
  exit 2
}

python3 - "$SNAPSHOT_DATE" <<'PY'
from datetime import date
import sys

try:
    date.fromisoformat(sys.argv[1])
except ValueError as exc:
    raise SystemExit(f"ERROR: invalid snapshot date: {sys.argv[1]}") from exc
PY

source_count=0
pdf_required=0
while IFS=$'\t' read -r source_id title official_url source_format selector expected_marker extra; do
  [[ -z "$source_id" || "${source_id:0:1}" == "#" ]] && continue
  [[ -z "${extra:-}" ]] || {
    printf 'ERROR: too many fields for source %s\n' "$source_id" >&2
    exit 2
  }
  validate_source_id "$source_id"
  [[ -n "$title" && -n "$official_url" && -n "$source_format" && -n "$selector" && -n "$expected_marker" ]] || {
    printf 'ERROR: incomplete source row: %s\n' "$source_id" >&2
    exit 2
  }
  case "$official_url" in
    https://*) ;;
    *)
      printf 'ERROR: source URL must use HTTPS: %s\n' "$official_url" >&2
      exit 2
      ;;
  esac
  case "$source_format" in
    html)
      [[ "$selector" != "-" ]] || {
        printf 'ERROR: HTML source requires a container id: %s\n' "$source_id" >&2
        exit 2
      }
      ;;
    pdf)
      [[ "$selector" == "-" ]] || {
        printf 'ERROR: PDF source selector must be -: %s\n' "$source_id" >&2
        exit 2
      }
      pdf_required=1
      ;;
    *)
      printf 'ERROR: unsupported source format for %s: %s\n' "$source_id" "$source_format" >&2
      exit 2
      ;;
  esac
  source_count=$((source_count + 1))
done < "$SOURCE_LIST"

[[ $source_count -gt 0 ]] || {
  printf 'ERROR: source list is empty: %s\n' "$SOURCE_LIST" >&2
  exit 2
}

if [[ $pdf_required -eq 1 ]]; then
  require_tool pdftotext
fi

snapshot_dir="$OUTPUT_ROOT/$SNAPSHOT_DATE"

printf 'manage-document-projects legal source ingestion\n'
printf '  mode: %s\n' "$([[ $APPLY -eq 1 ]] && printf apply || printf dry-run)"
printf '  date: %s\n' "$SNAPSHOT_DATE"
printf '  sources: %s\n' "$source_count"
printf '  destination: %s\n' "$snapshot_dir"

if [[ -d "$snapshot_dir" ]]; then
  [[ -f "$snapshot_dir/snapshot-manifest.json" && -f "$snapshot_dir/SHA256SUMS" ]] || {
    printf 'ERROR: existing snapshot is incomplete and will not be overwritten: %s\n' "$snapshot_dir" >&2
    exit 1
  }
  (
    cd "$snapshot_dir"
    shasum -a 256 -c SHA256SUMS >/dev/null
  ) || {
    printf 'ERROR: existing snapshot failed hash verification: %s\n' "$snapshot_dir" >&2
    exit 1
  }
  printf 'SKIP  verified snapshot already exists; no changes made\n'
  exit 0
fi

while IFS=$'\t' read -r source_id title official_url source_format selector expected_marker extra; do
  [[ -z "$source_id" || "${source_id:0:1}" == "#" ]] && continue
  printf 'PLAN  %-38s %-4s %s\n' "$source_id" "$source_format" "$official_url"
done < "$SOURCE_LIST"

if [[ $APPLY -eq 0 ]]; then
  printf '\nNo changes made. Re-run with --apply to create the snapshot.\n'
  exit 0
fi

mkdir -p "$OUTPUT_ROOT"
staging_dir="$(mktemp -d "$OUTPUT_ROOT/.snapshot-$SNAPSHOT_DATE.XXXXXX")"
trap 'rm -rf "$staging_dir"' EXIT
mkdir -p "$staging_dir/raw" "$staging_dir/markdown"
records_path="$staging_dir/.records.tsv"
checksums_path="$staging_dir/SHA256SUMS"
: > "$records_path"
: > "$checksums_path"

created_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

while IFS=$'\t' read -r source_id title official_url source_format selector expected_marker extra; do
  [[ -z "$source_id" || "${source_id:0:1}" == "#" ]] && continue

  raw_relative="raw/$source_id.$source_format"
  markdown_relative="markdown/$source_id.md"
  raw_path="$staging_dir/$raw_relative"
  markdown_path="$staging_dir/$markdown_relative"
  body_path="$staging_dir/.body-$source_id.md"
  source_input_path="$staging_dir/.input-$source_id"
  curl_metadata="$staging_dir/.curl-$source_id.tsv"

  printf 'FETCH %-38s ' "$source_id"
  curl \
    --location \
    --fail \
    --silent \
    --show-error \
    --max-time 120 \
    --retry 2 \
    --retry-delay 1 \
    --output "$raw_path" \
    --write-out '%{url_effective}\t%{http_code}\t%{content_type}\n' \
    "$official_url" > "$curl_metadata"

  IFS=$'\t' read -r final_url http_status content_type < "$curl_metadata"
  [[ "$http_status" == "200" ]] || {
    printf 'ERROR HTTP %s\n' "$http_status" >&2
    exit 1
  }
  [[ -s "$raw_path" ]] || {
    printf 'ERROR empty response\n' >&2
    exit 1
  }

  if [[ "$source_format" == "html" ]]; then
    python3 - "$raw_path" "$selector" "$source_input_path" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import sys


class ElementExtractor(HTMLParser):
    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=False)
        self.target_id = target_id
        self.depth = 0
        self.parts: list[str] = []
        self.found = False

    @property
    def capturing(self) -> bool:
        return self.depth > 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.capturing and dict(attrs).get("id") == self.target_id:
            self.found = True
            self.depth = 1
            self.parts.append(self.get_starttag_text())
        elif self.capturing:
            self.depth += 1
            self.parts.append(self.get_starttag_text())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.capturing:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        if self.capturing:
            self.parts.append(f"</{tag}>")
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capturing:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.capturing:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.capturing:
            self.parts.append(f"&#{name};")


raw_path, target_id, output_path = sys.argv[1:]
parser = ElementExtractor(target_id)
parser.feed(Path(raw_path).read_text(encoding="utf-8", errors="replace"))
if not parser.found or len(parser.parts) < 3:
    raise SystemExit(f"ERROR: HTML container not found or empty: {target_id}")
Path(output_path).write_text("".join(parser.parts), encoding="utf-8")
PY
    pandoc \
      "$source_input_path" \
      --from=html \
      --to=gfm \
      --wrap=none \
      --output="$body_path"
  else
    pdftotext -layout "$raw_path" "$source_input_path"
    tr '\f' '\n' < "$source_input_path" > "$body_path"
  fi

  [[ "$(wc -c < "$body_path")" -ge 1000 ]] || {
    printf 'ERROR normalized document is unexpectedly small\n' >&2
    exit 1
  }
  if ! grep -Fq "$expected_marker" "$raw_path" && ! grep -Fq "$expected_marker" "$body_path"; then
    printf 'ERROR expected marker not found: %s\n' "$expected_marker" >&2
    exit 1
  fi

  raw_sha256="$(sha256_file "$raw_path")"
  {
    printf '%s\n' '---'
    printf 'snapshot_schema: "0.1.0"\n'
    printf 'source_id: "%s"\n' "$source_id"
    printf 'source_format: "%s"\n' "$source_format"
    python3 - "$title" <<'PY'
import json
import sys
print(f"title: {json.dumps(sys.argv[1], ensure_ascii=False)}")
PY
    python3 - "$official_url" <<'PY'
import json
import sys
print(f"official_url: {json.dumps(sys.argv[1], ensure_ascii=False)}")
PY
    python3 - "$final_url" <<'PY'
import json
import sys
print(f"resolved_url: {json.dumps(sys.argv[1], ensure_ascii=False)}")
PY
    printf 'retrieved_at: "%s"\n' "$created_at"
    printf 'raw_sha256: "%s"\n' "$raw_sha256"
    printf 'legal_review_status: pending-legal-review\n'
    printf '%s\n\n' '---'
    printf '> Instantánea técnica de una fuente oficial. No sustituye la consulta de la norma vigente ni una revisión jurídica.\n\n'
    printf '# %s\n\n' "$title"
    sed '/^[[:space:]]*$/N;/^\n$/D' "$body_path"
  } > "$markdown_path"

  markdown_sha256="$(sha256_file "$markdown_path")"
  printf '%s  %s\n' "$raw_sha256" "$raw_relative" >> "$checksums_path"
  printf '%s  %s\n' "$markdown_sha256" "$markdown_relative" >> "$checksums_path"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$source_id" \
    "$title" \
    "$official_url" \
    "$source_format" \
    "$final_url" \
    "$http_status" \
    "$content_type" \
    "$raw_relative" \
    "$raw_sha256" \
    "$markdown_relative" \
    "$markdown_sha256" >> "$records_path"
  printf 'OK\n'
done < "$SOURCE_LIST"

python3 - "$SNAPSHOT_DATE" "$created_at" "$SOURCE_LIST" "$records_path" "$staging_dir/snapshot-manifest.json" <<'PY'
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

snapshot_date, created_at, source_list, records_path, output_path = sys.argv[1:]
source_inventory_path = Path(source_list).resolve()
manifest_directory = Path(output_path).resolve().parent
fieldnames = [
    "id",
    "title",
    "official_url",
    "source_format",
    "resolved_url",
    "http_status",
    "content_type",
    "raw_path",
    "raw_sha256",
    "markdown_path",
    "markdown_sha256",
]
with Path(records_path).open(encoding="utf-8", newline="") as stream:
    sources = list(csv.DictReader(stream, fieldnames=fieldnames, delimiter="\t"))

manifest = {
    "snapshot_schema": "0.1.0",
    "snapshot_date": snapshot_date,
    "created_at": created_at,
    "source_inventory": os.path.relpath(source_inventory_path, manifest_directory),
    "source_inventory_sha256": hashlib.sha256(source_inventory_path.read_bytes()).hexdigest(),
    "policy": {
        "immutability": "append-only-by-date",
        "raw_format": "preserved-official-response-by-source",
        "normalized_format": "gfm-markdown-via-pandoc",
        "legal_review_status": "pending-legal-review",
    },
    "sources": sources,
}
Path(output_path).write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY

rm -f "$records_path" "$staging_dir"/.body-*.md "$staging_dir"/.curl-*.tsv "$staging_dir"/.input-*
(
  cd "$staging_dir"
  shasum -a 256 -c SHA256SUMS
)
mv "$staging_dir" "$snapshot_dir"
trap - EXIT

printf '\nCreated and verified snapshot: %s\n' "$snapshot_dir"
