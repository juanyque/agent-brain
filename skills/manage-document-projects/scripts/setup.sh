#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCTOR="$SCRIPT_DIR/doctor.sh"
CONFIGURATOR="$SCRIPT_DIR/configure_workspace.py"
LINK_SCRIPT="$SCRIPT_DIR/skill_link.sh"
PROBE_PATH="${DOCUMENT_PROJECT_PROBE_PATH:-$PATH}"
source "$SCRIPT_DIR/setup_tools.sh"
APPLY=0
INTERACTIVE=1
PROFILE="${DOCUMENT_PROJECT_PROFILE:-}"
WORKSPACE_ROOT="${DOCUMENT_PROJECT_WORKSPACE_ROOT:-}"
PROJECTS_DIR="${DOCUMENT_PROJECT_PROJECTS_DIR:-}"
DELIVERABLES_DIR="${DOCUMENT_PROJECT_DELIVERABLES_DIR:-}"
INCOMING_DIR="${DOCUMENT_PROJECT_INCOMING_DIR:-}"
GIT_VISIBILITY="${DOCUMENT_PROJECT_GIT_VISIBILITY:-}"
WEASYPRINT_CHOICE="${DOCUMENT_PROJECT_WEASYPRINT_CHOICE:-}"
LIBREOFFICE_CHOICE="${DOCUMENT_PROJECT_LIBREOFFICE_CHOICE:-}"
OPENSSH_CHOICE="${DOCUMENT_PROJECT_OPENSSH_CHOICE:-}"

print_usage() {
  printf '%s\n' \
    'Usage:' \
    '  setup.sh [options]' \
    '' \
    'Workspace options:' \
    '  --profile NAME            configure NAME; default is the active profile' \
    '  --workspace-root PATH     absolute workspace root' \
    '  --projects-dir PATH       project sources below the workspace root' \
    '  --deliverables-dir PATH   printable outputs below the workspace root' \
    '  --incoming-dir PATH       incoming documents below the workspace root' \
    '  --git-visibility POLICY   required or unrestricted' \
    '' \
    'Tool options:' \
    '  --with-weasyprint         install CSS-to-PDF support' \
    '  --without-weasyprint      persistently decline CSS-to-PDF support' \
    '  --with-libreoffice        install Office editing and conversion support' \
    '  --without-libreoffice     persistently decline Office support' \
    '  --with-openssh            install governed-release signature support' \
    '  --without-openssh         persistently decline signature support' \
    '  --with-all-optional       install every optional tool' \
    '' \
    'Execution options:' \
    '  --apply                   converge tools, configuration, and skill links' \
    '  --non-interactive         require values instead of prompting'
}

require_value() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "$value" ]]; then
    printf 'ERROR: %s requires a value\n' "$option" >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      shift
      ;;
    --non-interactive)
      INTERACTIVE=0
      shift
      ;;
    --profile)
      require_value "$1" "${2:-}"
      PROFILE="$2"
      shift 2
      ;;
    --workspace-root)
      require_value "$1" "${2:-}"
      WORKSPACE_ROOT="$2"
      shift 2
      ;;
    --projects-dir)
      require_value "$1" "${2:-}"
      PROJECTS_DIR="$2"
      shift 2
      ;;
    --deliverables-dir)
      require_value "$1" "${2:-}"
      DELIVERABLES_DIR="$2"
      shift 2
      ;;
    --incoming-dir)
      require_value "$1" "${2:-}"
      INCOMING_DIR="$2"
      shift 2
      ;;
    --git-visibility)
      require_value "$1" "${2:-}"
      GIT_VISIBILITY="$2"
      shift 2
      ;;
    --with-weasyprint)
      WEASYPRINT_CHOICE="install"
      shift
      ;;
    --without-weasyprint)
      WEASYPRINT_CHOICE="decline"
      shift
      ;;
    --with-libreoffice)
      LIBREOFFICE_CHOICE="install"
      shift
      ;;
    --without-libreoffice)
      LIBREOFFICE_CHOICE="decline"
      shift
      ;;
    --with-openssh)
      OPENSSH_CHOICE="install"
      shift
      ;;
    --without-openssh)
      OPENSSH_CHOICE="decline"
      shift
      ;;
    --with-all-optional)
      WEASYPRINT_CHOICE="install"
      LIBREOFFICE_CHOICE="install"
      OPENSSH_CHOICE="install"
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
done

export_override() {
  local name="$1"
  local value="$2"
  if [[ -n "$value" ]]; then
    export "$name=$value"
  fi
}

printf 'manage-document-projects setup\n'
if [[ $APPLY -eq 1 ]]; then
  printf '  mode: apply\n\n'
else
  printf '  mode: dry-run\n\n'
fi

set +e
bash "$DOCTOR"
doctor_status=$?
set -e

reconcile_core_tools

export_override DOCUMENT_PROJECT_PROFILE "$PROFILE"
export_override DOCUMENT_PROJECT_WORKSPACE_ROOT "$WORKSPACE_ROOT"
export_override DOCUMENT_PROJECT_PROJECTS_DIR "$PROJECTS_DIR"
export_override DOCUMENT_PROJECT_DELIVERABLES_DIR "$DELIVERABLES_DIR"
export_override DOCUMENT_PROJECT_INCOMING_DIR "$INCOMING_DIR"
export_override DOCUMENT_PROJECT_GIT_VISIBILITY "$GIT_VISIBILITY"
export_override DOCUMENT_PROJECT_WEASYPRINT_CHOICE "$WEASYPRINT_CHOICE"
export_override DOCUMENT_PROJECT_LIBREOFFICE_CHOICE "$LIBREOFFICE_CHOICE"
export_override DOCUMENT_PROJECT_OPENSSH_CHOICE "$OPENSSH_CHOICE"

runtime_uv="$(PATH="$PROBE_PATH" command -v uv 2>/dev/null || command -v uv 2>/dev/null || true)"
if [[ -z "$runtime_uv" ]]; then
  printf 'PLAN    configure workspace after uv is installed\n'
else
  config_log="$(mktemp)"
  trap 'rm -f "$config_log"' EXIT
  configure_command=("$runtime_uv" run --script "$CONFIGURATOR")
  if [[ $APPLY -eq 1 ]]; then
    configure_command+=("--apply")
  fi
  if [[ $INTERACTIVE -eq 0 ]]; then
    configure_command+=("--non-interactive")
  fi
  "${configure_command[@]}" | tee "$config_log"
  optional_line="$(grep '^OPTIONAL_TOOLS ' "$config_log" | tail -1)"
  read -r _ weasyprint_setting libreoffice_setting openssh_setting <<< "$optional_line"
  WEASYPRINT_CHOICE="${weasyprint_setting#*=}"
  LIBREOFFICE_CHOICE="${libreoffice_setting#*=}"
  OPENSSH_CHOICE="${openssh_setting#*=}"
fi

reconcile_optional_tools \
  "$WEASYPRINT_CHOICE" \
  "$LIBREOFFICE_CHOICE" \
  "$OPENSSH_CHOICE"

printf '\n'
if [[ $APPLY -eq 1 ]]; then
  bash "$LINK_SCRIPT" --apply
  printf '\nPost-install doctor\n'
  bash "$DOCTOR"
  exit $?
fi

bash "$LINK_SCRIPT"
printf '\nNo changes made. Re-run with --apply to execute the plan.\n'
if [[ $doctor_status -eq 0 ]]; then
  printf 'Core environment is already ready.\n'
fi
