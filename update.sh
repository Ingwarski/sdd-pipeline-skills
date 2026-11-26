#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -P -- "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
channel=stable
installer_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --channel)
      [[ $# -ge 2 && ( "$2" == main || "$2" == stable ) ]] || {
        printf 'Channel must be main or stable.\n' >&2
        exit 2
      }
      channel=$2
      shift 2
      ;;
    --help|-h)
      printf '%s\n' 'Update the verified standalone checkout and repair its selected registrations.'
      printf '%s\n' 'Usage: ./update.sh [--channel stable|main] [--all|--codex|--claude] [registration and evidence options]'
      exit 0
      ;;
    --uninstall|--retire-only|--cleanup-dir|--retired-source|--check-locations-only)
      printf 'Use install.sh for %s; update stopped.\n' "$1" >&2
      exit 2
      ;;
    *)
      installer_args+=("$1")
      shift
      ;;
  esac
done

# Preflight uses the installer's own option parser and complete mutation plan.
# Do not change Git state or retire a single entry until every root is eligible.
set -- ${installer_args[@]+"${installer_args[@]}"}
bash "$repo_root/install.sh" --check-locations-only --repair "$@"
python3 -B "$repo_root/scripts/install_location.py" advance --source "$repo_root" --channel "$channel"
exec bash "$repo_root/install.sh" --repair "$@"
