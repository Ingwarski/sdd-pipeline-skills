#!/usr/bin/env bash

script_dir="$(CDPATH= cd -P -- "$(dirname "$0")" && pwd -P)"
"$script_dir/install.sh" "$@"
exit_status=$?

if [[ -t 0 ]]; then
  printf '\nPress Return to close this window.'
  read -r _
fi
exit "$exit_status"
