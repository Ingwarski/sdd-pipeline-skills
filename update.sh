#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

update_sdd() {
  local arg origin branch status top
  local channel=main
  local installer_args=()
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == --channel ]]; then
      [[ $# -ge 2 && ( "$2" == main || "$2" == stable ) ]] || { printf 'Channel must be main or stable.\n' >&2; return 2; }
      channel=$2
      shift 2
    else
      installer_args+=("$1")
      shift
    fi
  done
  set -- ${installer_args[@]+"${installer_args[@]}"}
  for arg in "$@"; do
    case "$arg" in
      --help|-h)
        printf '%s\n' 'Update a clean SDD main checkout, then repair/install and clean retired skills.'
        printf '%s\n' 'Usage: ./update.sh [--channel main|stable] [installer options, except --uninstall]'
        return 0
        ;;
      --uninstall) printf 'Use install.sh --uninstall instead.\n' >&2; return 2 ;;
    esac
  done
  source "$repo_root/scripts/retired-skills.sh"
  top=$(git -C "$repo_root" rev-parse --show-toplevel)
  [[ "$(retired_normalize "$top")" == "$repo_root" ]] || { printf 'Not the SDD clone root.\n' >&2; return 1; }
  origin=$(git -C "$repo_root" remote get-url origin)
  retired_known_sdd_origin "$origin" || { printf 'Origin is not the expected SDD GitHub repository; stopped.\n' >&2; return 1; }
  branch=$(git -C "$repo_root" symbolic-ref --quiet --short HEAD || true)
  [[ "$branch" == main ]] || { printf 'Update requires main; your current checkout is unchanged.\n' >&2; return 1; }
  # Delete only the retired names before checking unrelated local Git changes.
  bash "$repo_root/install.sh" --retire-only "$@"
  status=$(git -C "$repo_root" status --porcelain --untracked-files=normal)
  [[ -z "$status" ]] || { printf 'Local changes exist; commit or preserve them before updating.\n' >&2; return 1; }
  git -C "$repo_root" fetch --quiet origin "$channel"
  git -C "$repo_root" merge-base --is-ancestor HEAD FETCH_HEAD || {
    printf 'Local commits diverge from or are ahead of GitHub; stopped without replacing files.\n' >&2; return 1;
  }
  git -C "$repo_root" merge --ff-only FETCH_HEAD
  # Execute the freshly fetched installer, not a previously loaded copy.
  exec bash "$repo_root/install.sh" --repair "$@"
}

update_sdd "$@"
