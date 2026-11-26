# Permanent retirement is restricted to these two names in known skill roots.
retired_policy="$repo_root/retired-skills.txt"
retired_names=(communications-audit issue-happypro-certificate)
retired_roots=()
retired_root_count=0
retired_backup_roots=()
retired_backup_root_count=0
retired_removed=0
retired_backups_removed=0

retired_normalize() {
  # Marker paths may have missing suffixes. Resolve links before interpreting "..".
  python3 -B -c 'import pathlib, sys
p = pathlib.Path(sys.argv[1])
if not p.is_absolute() or any(c in str(p) for c in "\r\n"):
    sys.exit(1)
print(p.resolve())' "$1"
}

retired_plan_root() {
  location_args+=("$1" "$2")
  retired_roots[retired_root_count]=$2
  retired_root_count=$((retired_root_count + 1))
}

retired_plan() {
  local root i
  retired_plan_root --source-root "$repo_root/skills"
  if [[ $want_codex -eq 1 ]]; then
    retired_plan_root --source-root "$repo_root/.agents/skills"
    retired_plan_root --source-root "$repo_root/.codex/skills"
  fi
  if [[ $want_claude -eq 1 ]]; then
    retired_plan_root --source-root "$repo_root/.claude/skills"
  fi

  # Extra cleanup is a separate request. A first install or ordinary update
  # touches only its verified checkout and the selected registration roots.
  [[ $retire_only -eq 1 ]] || return 0
  if [[ $want_codex -eq 1 && $codex_dir_explicit -eq 0 ]]; then
    retired_plan_root --personal-root "$HOME/.agents/skills"
    retired_plan_root --personal-root "$HOME/.codex/skills"
    [[ -z "${CODEX_HOME:-}" ]] || retired_plan_root --personal-root "$CODEX_HOME/skills"
  fi
  for ((i=0; i<retired_extra_count; i++)); do
    retired_plan_root --cleanup-dir "${retired_extra_roots[i]}"
  done
  for root in "$HOME/.sdd-pipeline/retired-skills" "${SDD_SKILL_BACKUP_DIR:-}"; do
    [[ -n "$root" ]] || continue
    location_args+=(--personal-root "$root")
    retired_backup_roots[retired_backup_root_count]=$root
    retired_backup_root_count=$((retired_backup_root_count + 1))
  done
}

# Consume the physical paths approved by the guard, in its documented role
# order (source cleanup, legacy personal, former backups, explicit cleanup).
retired_read_paths() {
  local i
  for ((i=0; i<retired_root_count-retired_extra_count; i++)); do
    IFS= read -r 'retired_roots[i]'
  done
  for ((i=0; i<retired_backup_root_count; i++)); do
    IFS= read -r 'retired_backup_roots[i]'
  done
  for ((i=retired_root_count-retired_extra_count; i<retired_root_count; i++)); do
    IFS= read -r 'retired_roots[i]'
  done
  if [[ $want_codex -eq 1 ]]; then
    retired_roots[retired_root_count]=$codex_dir
    retired_root_count=$((retired_root_count + 1))
  fi
  if [[ $want_claude -eq 1 ]]; then
    retired_roots[retired_root_count]=$claude_dir
    retired_root_count=$((retired_root_count + 1))
  fi
}

retired_prepare() {
  local name policy
  [[ -f "$retired_policy" && ! -L "$retired_policy" ]] || {
    printf 'Missing retirement policy.\n' >&2; return 1;
  }
  policy=$(sed 's/\r$//' "$retired_policy")
  [[ "$policy" == "$(printf '%s\n' "${retired_names[@]}")" ]] || {
    printf 'Invalid retirement policy: only the two retired skills are allowed.\n' >&2; return 1;
  }
  for name in "${retired_names[@]}"; do
    if manifest_entries | awk -F '|' -v name="$name" '$1==name {found=1} END {exit !found}'; then
      printf 'Retired skill is still active: %s\n' "$name" >&2; return 1
    fi
  done
}

retired_delete() {
  local root=$1 name=$2 path
  case "$name" in communications-audit|issue-happypro-certificate) ;; *) return 1 ;; esac
  [[ "$root" == /* && "$root" != / ]] || return 1
  path="$root/$name"
  [[ -e "$path" || -L "$path" ]] || return 0
  printf 'Retirement: permanently deleting %s\n' "$path"
  # Exact validated child path, no trailing slash: rm never follows nested links.
  rm -rf -- "$path" || { printf 'Retirement deletion failed: %s\n' "$path" >&2; return 1; }
  [[ ! -e "$path" && ! -L "$path" ]] || {
    printf 'Retired skill still exists: %s\n' "$path" >&2; return 1;
  }
  retired_removed=$((retired_removed + 1))
}

retired_purge_old_backups() {
  local base entry marker original name suffix i j matched
  for ((i=0; i<retired_backup_root_count; i++)); do
    base=${retired_backup_roots[i]}
    [[ -d "$base" ]] || continue
    for entry in "$base"/*; do
      [[ -d "$entry" && ! -L "$entry" ]] || continue
      marker="$entry/original-path.txt"
      [[ -f "$marker" && ! -L "$marker" ]] || continue
      original=$(sed -n '1{s/\r$//;p;}' "$marker")
      original=${original#$'\xEF\xBB\xBF'}
      original=$(retired_normalize "$original") || continue
      for name in "${retired_names[@]}"; do
        [[ "${entry##*/}" == "$name."* ]] || continue
        suffix=${entry##*/}; suffix=${suffix#"$name."}
        [[ "$suffix" =~ ^([[:alnum:]]{6}|[[:xdigit:]]{32})$ ]] || continue
        matched=0
        for ((j=0; j<retired_root_count; j++)); do
          [[ "$original" != "${retired_roots[j]}/$name" ]] || matched=1
        done
        [[ $matched -eq 1 ]] || continue
        if [[ -e "$entry/$name" || -L "$entry/$name" ]]; then
          retired_delete "$entry" "$name"
          retired_backups_removed=$((retired_backups_removed + 1))
        fi
        rm -- "$marker"
        rmdir "$entry" 2>/dev/null || true
      done
    done
  done
}

retired_apply() {
  local root name i
  for ((i=0; i<retired_root_count; i++)); do
    root=${retired_roots[i]}
    for name in "${retired_names[@]}"; do retired_delete "$root" "$name"; done
  done
  retired_purge_old_backups
  for ((i=0; i<retired_root_count; i++)); do
    for name in "${retired_names[@]}"; do
      root=${retired_roots[i]}
      [[ ! -e "$root/$name" && ! -L "$root/$name" ]] || {
        printf 'Retirement incomplete: %s\n' "$root/$name" >&2; return 1;
      }
    done
  done
  printf 'Retirement summary: permanently-deleted=%d former-backups-deleted=%d remaining=0 backups-created=0\n' \
    "$retired_removed" "$retired_backups_removed"
}
