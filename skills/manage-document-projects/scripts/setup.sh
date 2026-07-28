#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"
DOCTOR="$SCRIPT_DIR/doctor.sh"
LINK_SCRIPT="$REPO_ROOT/model/SCRIPTS/skill_link.sh"
PROBE_PATH="${DOCUMENT_PROJECT_PROBE_PATH:-$PATH}"
APPLY=0
INTERACTIVE=1
WEASYPRINT_CHOICE="ask"
LIBREOFFICE_CHOICE="ask"
OPENSSH_CHOICE="ask"

print_usage() {
  printf '%s\n' \
    'Usage:' \
    '  setup.sh [options]' \
    '' \
    'Options:' \
    '  --apply                 install selected tools and link the skill' \
    '  --with-weasyprint       install CSS-to-PDF support' \
    '  --without-weasyprint    decline CSS-to-PDF support' \
    '  --with-libreoffice      install Office editing and conversion support' \
    '  --without-libreoffice   decline Office support' \
    '  --with-openssh          install SSH signature support' \
    '  --without-openssh       decline SSH signature support' \
    '  --with-all-optional     install every missing optional tool' \
    '  --non-interactive       decline unspecified optional tools'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      ;;
    --with-weasyprint)
      WEASYPRINT_CHOICE="yes"
      ;;
    --without-weasyprint)
      WEASYPRINT_CHOICE="no"
      ;;
    --with-libreoffice)
      LIBREOFFICE_CHOICE="yes"
      ;;
    --without-libreoffice)
      LIBREOFFICE_CHOICE="no"
      ;;
    --with-openssh)
      OPENSSH_CHOICE="yes"
      ;;
    --without-openssh)
      OPENSSH_CHOICE="no"
      ;;
    --with-all-optional)
      WEASYPRINT_CHOICE="yes"
      LIBREOFFICE_CHOICE="yes"
      OPENSSH_CHOICE="yes"
      ;;
    --non-interactive)
      INTERACTIVE=0
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

has_tool() {
  PATH="$PROBE_PATH" command -v "$1" >/dev/null 2>&1
}

has_libreoffice() {
  has_tool soffice || has_tool libreoffice
}

ask_optional() {
  local name="$1"
  local purpose="$2"
  local answer
  printf 'Install %s? %s [y/N] ' "$name" "$purpose"
  read -r answer || answer=""
  case "$answer" in
    y|Y|yes|YES)
      OPTIONAL_ANSWER="yes"
      ;;
    *)
      OPTIONAL_ANSWER="no"
      ;;
  esac
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

core_packages=()
if ! has_tool python3; then
  core_packages+=("python")
fi
if ! has_tool uv; then
  core_packages+=("uv")
fi
if ! has_tool pandoc; then
  core_packages+=("pandoc")
fi

if [[ $APPLY -eq 1 && $INTERACTIVE -eq 1 ]]; then
  if ! has_tool weasyprint && [[ "$WEASYPRINT_CHOICE" == "ask" ]]; then
    ask_optional "WeasyPrint" "Useful for PDF generated from HTML and CSS."
    WEASYPRINT_CHOICE="$OPTIONAL_ANSWER"
  fi
  if ! has_libreoffice && [[ "$LIBREOFFICE_CHOICE" == "ask" ]]; then
    ask_optional "LibreOffice" "Useful for editing reference files and Office-to-PDF conversion."
    LIBREOFFICE_CHOICE="$OPTIONAL_ANSWER"
  fi
  if ! has_tool ssh-keygen && [[ "$OPENSSH_CHOICE" == "ask" ]]; then
    ask_optional "OpenSSH" "Required to sign and verify governed releases."
    OPENSSH_CHOICE="$OPTIONAL_ANSWER"
  fi
elif [[ $APPLY -eq 1 ]]; then
  if [[ "$WEASYPRINT_CHOICE" == "ask" ]]; then
    WEASYPRINT_CHOICE="no"
  fi
  if [[ "$LIBREOFFICE_CHOICE" == "ask" ]]; then
    LIBREOFFICE_CHOICE="no"
  fi
  if [[ "$OPENSSH_CHOICE" == "ask" ]]; then
    OPENSSH_CHOICE="no"
  fi
fi

formula_packages=()
if [[ ${#core_packages[@]} -gt 0 ]]; then
  formula_packages=("${core_packages[@]}")
fi
if has_tool weasyprint; then
  if [[ "$WEASYPRINT_CHOICE" == "yes" ]]; then
    printf '\nSKIP    weasyprint already installed\n'
  fi
elif [[ "$WEASYPRINT_CHOICE" == "yes" ]]; then
  formula_packages+=("weasyprint")
elif [[ "$WEASYPRINT_CHOICE" == "ask" ]]; then
  printf '\nOPTION  weasyprint: HTML and CSS to paginated PDF. Use --with-weasyprint.\n'
else
  printf '\nSKIP    weasyprint not selected\n'
fi
if has_tool ssh-keygen; then
  if [[ "$OPENSSH_CHOICE" == "yes" ]]; then
    printf 'SKIP    openssh already installed\n'
  fi
elif [[ "$OPENSSH_CHOICE" == "yes" ]]; then
  formula_packages+=("openssh")
elif [[ "$OPENSSH_CHOICE" == "ask" ]]; then
  printf 'OPTION  openssh: sign and verify governed releases. Use --with-openssh.\n'
else
  printf 'SKIP    openssh not selected\n'
fi

install_libreoffice=0
if has_libreoffice; then
  if [[ "$LIBREOFFICE_CHOICE" == "yes" ]]; then
    printf 'SKIP    libreoffice already installed\n'
  fi
elif [[ "$LIBREOFFICE_CHOICE" == "yes" ]]; then
  install_libreoffice=1
elif [[ "$LIBREOFFICE_CHOICE" == "ask" ]]; then
  printf 'OPTION  libreoffice: edit reference files and convert Office documents to PDF. Use --with-libreoffice.\n'
else
  printf 'SKIP    libreoffice not selected\n'
fi

if [[ ${#formula_packages[@]} -gt 0 || $install_libreoffice -eq 1 ]]; then
  brew_path="$(PATH="$PROBE_PATH" command -v brew 2>/dev/null || true)"
  if [[ -z "$brew_path" ]]; then
    printf '\nERROR: automatic setup currently requires Homebrew.\n' >&2
    printf 'Install the missing tools manually, then run doctor.sh again.\n' >&2
    exit 2
  fi

  if [[ ${#formula_packages[@]} -gt 0 && $APPLY -eq 1 ]]; then
    printf '\nINSTALL %s install %s\n' "$brew_path" "${formula_packages[*]}"
    "$brew_path" install "${formula_packages[@]}"
  elif [[ ${#formula_packages[@]} -gt 0 ]]; then
    printf '\nPLAN    brew install %s\n' "${formula_packages[*]}"
  fi
  if [[ $install_libreoffice -eq 1 && $APPLY -eq 1 ]]; then
    printf 'INSTALL %s install --cask libreoffice\n' "$brew_path"
    "$brew_path" install --cask libreoffice
  elif [[ $install_libreoffice -eq 1 ]]; then
    printf 'PLAN    brew install --cask libreoffice\n'
  fi
fi

if [[ ${#core_packages[@]} -eq 0 ]]; then
  printf '\nCORE    required tools already installed\n'
fi

printf '\n'
if [[ $APPLY -eq 1 ]]; then
  bash "$LINK_SCRIPT" "$SKILL_DIR" --apply
  printf '\nPost-install doctor\n'
  bash "$DOCTOR"
  exit $?
fi

bash "$LINK_SCRIPT" "$SKILL_DIR"
printf '\nNo changes made. Re-run with --apply to execute the plan.\n'
if [[ $doctor_status -eq 0 ]]; then
  printf 'Core environment is already ready.\n'
fi
