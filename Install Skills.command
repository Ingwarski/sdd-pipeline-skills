#!/usr/bin/env bash

script_dir="$(cd "$(dirname "$0")" && pwd -P)"
"$script_dir/install.sh" --all "$@"
exit_status=$?

printf '\nPress Return to close this window.'
read -r _
exit "$exit_status"
