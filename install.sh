#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
manifest_path="$repo_root/skills-manifest.json"
receipt_name=".codex-sdd-skills-source"

want_codex=1
want_claude=1
platform_selected=0
repair=0
uninstall=0
retire_only=0
codex_dir=""
claude_dir=""
codex_dir_explicit=0
retired_sources=()
retired_source_count=0
retired_extra_roots=()
retired_extra_count=0

usage() {
  printf '%s\n' \
    "Install the SDD pipeline skills as directory symlinks to this clone." \
    "" \
    "Usage: ./install.sh [--all|--codex|--claude] [--repair|--uninstall|--retire-only]" \
    "                    [--codex-dir PATH] [--claude-dir PATH]" \
    "                    [--retired-source OLD_CLONE] [--cleanup-dir SKILL_ROOT]" \
    "" \
    "With no platform flag, both Codex and Claude Code are installed." \
    "Install/update permanently deletes communications-audit and issue-happypro-certificate." \
    "No backups are made. Other skills are not retired."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      want_codex=1
      want_claude=1
      platform_selected=1
      shift
      ;;
    --codex)
      if [[ $platform_selected -eq 0 ]]; then
        want_codex=0
        want_claude=0
        platform_selected=1
      fi
      want_codex=1
      shift
      ;;
    --claude)
      if [[ $platform_selected -eq 0 ]]; then
        want_codex=0
        want_claude=0
        platform_selected=1
      fi
      want_claude=1
      shift
      ;;
    --repair)
      repair=1
      shift
      ;;
    --uninstall)
      uninstall=1
      shift
      ;;
    --retire-only)
      retire_only=1
      shift
      ;;
    --codex-dir)
      [[ $# -ge 2 ]] || { printf 'Missing value for --codex-dir\n' >&2; exit 2; }
      codex_dir=$2
      codex_dir_explicit=1
      shift 2
      ;;
    --claude-dir)
      [[ $# -ge 2 ]] || { printf 'Missing value for --claude-dir\n' >&2; exit 2; }
      claude_dir=$2
      shift 2
      ;;
    --retired-source|--cleanup-dir)
      [[ $# -ge 2 && "$2" == /* ]] || { printf 'An absolute path is required for %s\n' "$1" >&2; exit 2; }
      if [[ "$1" == --retired-source ]]; then
        retired_sources[retired_source_count]=$2
        retired_source_count=$((retired_source_count + 1))
      else
        retired_extra_roots[retired_extra_count]=$2
        retired_extra_count=$((retired_extra_count + 1))
      fi
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ $repair -eq 1 && $uninstall -eq 1 ]]; then
  printf '%s\n' '--repair and --uninstall cannot be used together.' >&2
  exit 2
fi

if [[ $uninstall -eq 1 && ( $retire_only -eq 1 || $retired_source_count -gt 0 || $retired_extra_count -gt 0 ) ]]; then
  printf '%s\n' 'Retirement options apply to install/update, not --uninstall.' >&2
  exit 2
fi

if [[ ! -f "$manifest_path" ]]; then
  printf 'Missing manifest: %s\n' "$manifest_path" >&2
  exit 1
fi

if [[ -z "$codex_dir" ]]; then
  if [[ -n "${CODEX_SKILLS_DIR:-}" ]]; then
    codex_dir=$CODEX_SKILLS_DIR
    codex_dir_explicit=1
  elif [[ -n "${CODEX_HOME:-}" ]]; then
    codex_dir="$CODEX_HOME/skills"
  elif [[ -d "${HOME:?HOME is required}/.codex/skills" && ! -d "$HOME/.agents/skills" ]]; then
    codex_dir="$HOME/.codex/skills"
  else
    codex_dir="$HOME/.agents/skills"
  fi
fi

if [[ -z "$claude_dir" ]]; then
  claude_dir="${CLAUDE_SKILLS_DIR:-${HOME:?HOME is required}/.claude/skills}"
fi

manifest_entries() {
  printf '%s\n' "$validated_manifest_rows"
}

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  printf '%s\n' 'Python 3.9+ is required. Install Python 3, then rerun; no installation changes made.' >&2
  exit 1
fi
manifest_args=(--root "$repo_root")
[[ $retire_only -eq 0 ]] || manifest_args+=(--metadata-only)
# Capture success before using rows: process substitutions can hide parser errors.
validated_manifest_rows=$(python3 "$repo_root/scripts/install_manifest.py" "${manifest_args[@]}") || exit 1

if [[ $retire_only -eq 1 ]]; then
  source "$repo_root/scripts/retired-skills.sh"
  retired_prepare
  retired_apply
  exit 0
fi

printf 'Validated %d source skills and their shared references.\n' 13

if [[ $uninstall -eq 0 ]]; then
  source "$repo_root/scripts/retired-skills.sh"
  retired_prepare
  retired_apply
fi

link_raw_target() {
  readlink "$1" 2>/dev/null || true
}

link_points_to() {
  link_path=$1
  expected_path=$2
  [[ -L "$link_path" ]] || return 1
  raw_target=$(link_raw_target "$link_path")
  [[ "$raw_target" == "$expected_path" ]] && return 0
  case "$raw_target" in
    /*) candidate_target=$raw_target ;;
    *) candidate_target="$(dirname "$link_path")/$raw_target" ;;
  esac
  if [[ -d "$candidate_target" ]]; then
    candidate_target=$(cd "$candidate_target" && pwd -P)
    [[ "$candidate_target" == "$expected_path" ]]
    return
  fi
  return 1
}

receipt_root() {
  install_root=$1
  receipt_path="$install_root/$receipt_name"
  [[ -f "$receipt_path" ]] && sed -n '1p' "$receipt_path" || true
}

repair_authorized() {
  link_path=$1
  relative_path=$2
  prior_root=$3
  [[ $repair -eq 1 && -n "$prior_root" && -L "$link_path" ]] || return 1
  raw_target=$(link_raw_target "$link_path")
  [[ "$raw_target" == "$prior_root/$relative_path" ]]
}

destination_conflicts=0
preflight_destination_root() {
  install_root=$1
  prior_root=$(receipt_root "$install_root")
  while IFS='|' read -r skill_name relative_path legacy_name; do
    destination="$install_root/$skill_name"
    source_dir=$(cd "$repo_root/$relative_path" && pwd -P)
    if [[ -L "$destination" ]]; then
      if link_points_to "$destination" "$source_dir" || repair_authorized "$destination" "$relative_path" "$prior_root"; then
        continue
      fi
      printf '%-24s CONFLICT link points elsewhere: %s\n' "$skill_name" "$destination" >&2
      destination_conflicts=$((destination_conflicts + 1))
    elif [[ -e "$destination" ]]; then
      printf '%-24s CONFLICT real file/directory exists: %s\n' "$skill_name" "$destination" >&2
      destination_conflicts=$((destination_conflicts + 1))
    fi
  done < <(manifest_entries)
}

if [[ $uninstall -eq 0 ]]; then
  [[ $want_codex -eq 0 ]] || preflight_destination_root "$codex_dir"
  [[ $want_claude -eq 0 ]] || preflight_destination_root "$claude_dir"
  if [[ $destination_conflicts -ne 0 ]]; then
    printf 'Installation stopped before SDD link changes: %d conflict(s)\n' "$destination_conflicts" >&2
    exit 1
  fi
fi

created=0
already_installed=0
migrated=0
removed=0
post_failures=0

install_root() {
  install_root_path=$1
  tool_label=$2
  prior_root=$(receipt_root "$install_root_path")
  mkdir -p "$install_root_path"

  while IFS='|' read -r skill_name relative_path legacy_name; do
    source_dir=$(cd "$repo_root/$relative_path" && pwd -P)
    destination="$install_root_path/$skill_name"

    if [[ $uninstall -eq 1 ]]; then
      if link_points_to "$destination" "$source_dir" || repair_authorized "$destination" "$relative_path" "$prior_root"; then
        rm "$destination"
        removed=$((removed + 1))
        printf '%s %-24s removed\n' "$tool_label" "$skill_name"
      elif [[ -e "$destination" || -L "$destination" ]]; then
        printf '%s %-24s preserved unrelated destination\n' "$tool_label" "$skill_name"
      fi

      if [[ -n "$legacy_name" ]]; then
        legacy_destination="$install_root_path/$legacy_name"
        current_legacy_source="$repo_root/skills/$legacy_name"
        prior_legacy_source=""
        [[ -z "$prior_root" ]] || prior_legacy_source="$prior_root/skills/$legacy_name"
        if [[ -L "$legacy_destination" ]]; then
          raw_legacy_target=$(link_raw_target "$legacy_destination")
          if [[ "$raw_legacy_target" == "$current_legacy_source" || ( -n "$prior_legacy_source" && "$raw_legacy_target" == "$prior_legacy_source" ) ]]; then
            rm "$legacy_destination"
            removed=$((removed + 1))
            printf '%s %-24s removed legacy repository link\n' "$tool_label" "$legacy_name"
          else
            printf '%s %-24s preserved unrelated legacy skill\n' "$tool_label" "$legacy_name"
          fi
        elif [[ -e "$legacy_destination" ]]; then
          printf '%s %-24s preserved unrelated legacy skill\n' "$tool_label" "$legacy_name"
        fi
      fi
      continue
    fi

    if link_points_to "$destination" "$source_dir"; then
      already_installed=$((already_installed + 1))
      printf '%s %-24s already installed\n' "$tool_label" "$skill_name"
    else
      if [[ -L "$destination" ]] && repair_authorized "$destination" "$relative_path" "$prior_root"; then
        rm "$destination"
      fi
      ln -s "$source_dir" "$destination"
      created=$((created + 1))
      printf '%s %-24s linked\n' "$tool_label" "$skill_name"
    fi

    if [[ ! -r "$destination/SKILL.md" ]] || ! cmp -s "$source_dir/SKILL.md" "$destination/SKILL.md"; then
      printf '%s %-24s POST-INSTALL VALIDATION FAILED\n' "$tool_label" "$skill_name" >&2
      post_failures=$((post_failures + 1))
    fi

    if [[ -n "$legacy_name" ]]; then
      legacy_destination="$install_root_path/$legacy_name"
      current_legacy_source="$repo_root/skills/$legacy_name"
      prior_legacy_source=""
      [[ -z "$prior_root" ]] || prior_legacy_source="$prior_root/skills/$legacy_name"
      if [[ -L "$legacy_destination" ]]; then
        raw_legacy_target=$(link_raw_target "$legacy_destination")
        if [[ "$raw_legacy_target" == "$current_legacy_source" || ( -n "$prior_legacy_source" && "$raw_legacy_target" == "$prior_legacy_source" ) ]]; then
          rm "$legacy_destination"
          migrated=$((migrated + 1))
          printf '%s %-24s removed legacy repository link\n' "$tool_label" "$legacy_name"
        else
          printf '%s %-24s preserved unrelated legacy skill\n' "$tool_label" "$legacy_name"
        fi
      elif [[ -e "$legacy_destination" ]]; then
        printf '%s %-24s preserved unrelated legacy skill\n' "$tool_label" "$legacy_name"
      fi
    fi
  done < <(manifest_entries)

  receipt_path="$install_root_path/$receipt_name"
  if [[ $uninstall -eq 1 ]]; then
    if [[ -f "$receipt_path" ]]; then
      recorded_root=$(sed -n '1p' "$receipt_path")
      if [[ "$recorded_root" == "$repo_root" ]]; then
        rm "$receipt_path"
      fi
    fi
  elif [[ $post_failures -eq 0 ]]; then
    printf '%s\n' "$repo_root" > "$receipt_path"
  fi
}

if [[ $want_codex -eq 1 ]]; then
  install_root "$codex_dir" 'Codex      '
fi
if [[ $want_claude -eq 1 ]]; then
  install_root "$claude_dir" 'Claude Code'
fi

printf 'Summary: created=%d already-installed=%d migrated=%d removed=%d failed=%d\n' \
  "$created" "$already_installed" "$migrated" "$removed" "$post_failures"

if [[ $post_failures -ne 0 ]]; then
  exit 1
fi

if [[ $uninstall -eq 0 ]]; then
  printf '%s\n' 'Skills are linked to this clone. Use ./update.sh for updates and retirement cleanup.'
  printf '%s\n' 'Codex normally discovers new skills automatically. Restart only if they do not appear.'
  printf '%s\n' 'Claude Code reloads SKILL.md changes live; restart if its top-level skills directory was created during this session.'
fi
