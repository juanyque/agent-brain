#!/usr/bin/env bash

set -u

PROBE_PATH="${DOCUMENT_PROJECT_PROBE_PATH:-$PATH}"
required_missing=0

find_tool() {
  PATH="$PROBE_PATH" command -v "$1" 2>/dev/null || true
}

first_line() {
  local output
  output="$("$1" --version 2>&1 || true)"
  printf '%s' "${output%%$'\n'*}"
}

report_tool() {
  local name="$1"
  local requirement="$2"
  local path
  path="$(find_tool "$name")"

  if [[ -n "$path" ]]; then
    printf 'PASS  %-12s %s (%s)\n' "$name" "$path" "$(first_line "$path")"
    return 0
  fi

  if [[ "$requirement" == "required" ]]; then
    printf 'FAIL  %-12s missing, required\n' "$name"
    required_missing=1
  else
    printf 'WARN  %-12s missing, optional\n' "$name"
  fi
  return 1
}

printf 'manage-document-projects environment\n\n'

if report_tool python3 required; then
  python_ready=0
else
  python_ready=1
fi
if report_tool uv required; then
  uv_ready=0
else
  uv_ready=1
fi
if report_tool pandoc required; then
  pandoc_ready=0
else
  pandoc_ready=1
fi

soffice_path="$(find_tool soffice)"
if [[ -z "$soffice_path" ]]; then
  soffice_path="$(find_tool libreoffice)"
fi
if [[ -n "$soffice_path" ]]; then
  printf 'PASS  %-12s %s (%s)\n' "soffice" "$soffice_path" "$(first_line "$soffice_path")"
  office_ready=0
else
  printf 'WARN  %-12s missing, optional for office-based PDF conversion\n' "soffice"
  office_ready=1
fi

if report_tool weasyprint optional; then
  weasyprint_ready=0
else
  weasyprint_ready=1
fi
if report_tool ssh-keygen optional; then
  authentic_release_ready=0
else
  authentic_release_ready=1
fi

printf '\nCapabilities\n'
if [[ $python_ready -eq 0 && $uv_ready -eq 0 ]]; then
  printf 'TEMPLATE_RENDER=yes\n'
else
  printf 'TEMPLATE_RENDER=no\n'
fi
if [[ $pandoc_ready -eq 0 ]]; then
  printf 'MARKDOWN_EXPORT=yes\n'
else
  printf 'MARKDOWN_EXPORT=no\n'
fi
if [[ $pandoc_ready -eq 0 && $weasyprint_ready -eq 0 ]]; then
  printf 'CSS_PDF=yes\n'
else
  printf 'CSS_PDF=no\n'
fi
if [[ $pandoc_ready -eq 0 && $office_ready -eq 0 ]]; then
  printf 'OFFICE_PDF=yes\n'
else
  printf 'OFFICE_PDF=no\n'
fi
if [[ $authentic_release_ready -eq 0 ]]; then
  printf 'AUTHENTIC_RELEASE=yes\n'
else
  printf 'AUTHENTIC_RELEASE=no\n'
fi

printf '\nJinja2 is resolved in an isolated uv environment by the renderer.\n'

if [[ $required_missing -eq 0 ]]; then
  printf 'manage-document-projects doctor: READY\n'
  exit 0
fi

printf 'manage-document-projects doctor: NEEDS SETUP\n'
exit 1
