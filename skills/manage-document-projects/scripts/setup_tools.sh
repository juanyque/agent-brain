#!/usr/bin/env bash

has_tool() {
  PATH="$PROBE_PATH" command -v "$1" >/dev/null 2>&1
}

has_libreoffice() {
  has_tool soffice || has_tool libreoffice
}

brew_path() {
  PATH="$PROBE_PATH" command -v brew 2>/dev/null || command -v brew 2>/dev/null || true
}

install_formulae() {
  local package_manager="$1"
  shift
  if [[ $# -eq 0 ]]; then
    return
  fi
  if [[ $APPLY -eq 1 ]]; then
    printf 'INSTALL %s install %s\n' "$package_manager" "$*"
    "$package_manager" install "$@"
  else
    printf 'PLAN    brew install %s\n' "$*"
  fi
}

reconcile_core_tools() {
  local core_packages=()
  if ! has_tool python3; then
    core_packages+=("python")
  fi
  if ! has_tool uv; then
    core_packages+=("uv")
  fi
  if ! has_tool pandoc; then
    core_packages+=("pandoc")
  fi
  if [[ ${#core_packages[@]} -eq 0 ]]; then
    printf '\nCORE    required tools already installed\n'
    return
  fi
  local package_manager
  package_manager="$(brew_path)"
  if [[ -z "$package_manager" ]]; then
    printf '\nERROR: automatic setup currently requires Homebrew.\n' >&2
    printf 'Install the missing tools manually, then run setup.sh again.\n' >&2
    exit 2
  fi
  printf '\n'
  install_formulae "$package_manager" "${core_packages[@]}"
}

reconcile_optional_tools() {
  local weasyprint_choice="$1"
  local libreoffice_choice="$2"
  local openssh_choice="$3"
  local optional_packages=()
  local install_libreoffice=0

  if [[ "$weasyprint_choice" == "install" ]]; then
    if has_tool weasyprint; then
      printf 'SKIP    weasyprint already installed\n'
    else
      optional_packages+=("weasyprint")
    fi
  elif [[ -n "$weasyprint_choice" ]]; then
    printf 'SKIP    weasyprint declined in configuration\n'
  else
    printf 'OPTION  weasyprint: HTML and CSS to paginated PDF.\n'
  fi

  if [[ "$openssh_choice" == "install" ]]; then
    if has_tool ssh-keygen; then
      printf 'SKIP    openssh already installed\n'
    else
      optional_packages+=("openssh")
    fi
  elif [[ -n "$openssh_choice" ]]; then
    printf 'SKIP    openssh declined in configuration\n'
  else
    printf 'OPTION  openssh: sign and verify governed releases.\n'
  fi

  if [[ "$libreoffice_choice" == "install" ]]; then
    if has_libreoffice; then
      printf 'SKIP    libreoffice already installed\n'
    else
      install_libreoffice=1
    fi
  elif [[ -n "$libreoffice_choice" ]]; then
    printf 'SKIP    libreoffice declined in configuration\n'
  else
    printf 'OPTION  libreoffice: edit and convert Office documents.\n'
  fi

  if [[ ${#optional_packages[@]} -eq 0 && $install_libreoffice -eq 0 ]]; then
    return
  fi
  local package_manager
  package_manager="$(brew_path)"
  if [[ -z "$package_manager" ]]; then
    printf 'ERROR: automatic optional-tool setup requires Homebrew.\n' >&2
    exit 2
  fi
  if [[ ${#optional_packages[@]} -gt 0 ]]; then
    install_formulae "$package_manager" "${optional_packages[@]}"
  fi
  if [[ $install_libreoffice -eq 1 && $APPLY -eq 1 ]]; then
    printf 'INSTALL %s install --cask libreoffice\n' "$package_manager"
    "$package_manager" install --cask libreoffice
  elif [[ $install_libreoffice -eq 1 ]]; then
    printf 'PLAN    brew install --cask libreoffice\n'
  fi
}
