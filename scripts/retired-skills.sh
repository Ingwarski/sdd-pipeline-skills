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
  local value=$1 ancestor suffix="" physical
  [[ "$value" == /* && "$value" != *$'\n'* && "$value" != *$'\r'* ]] || return 1
  if [[ -d "$value" ]]; then
    (cd "$value" && pwd -P)
  else
    value=$(printf '%s\n' "$value" | awk -F/ '{
      n=0
      for(i=1;i<=NF;i++) {
        if($i=="" || $i==".") continue
        if($i=="..") { if(n>0) n--; continue }
        parts[++n]=$i
      }
      if(n==0) { print "/"; next }
      for(i=1;i<=n;i++) printf "/%s",parts[i]
      printf "\n"
    }')
    ancestor=$value
    while [[ ! -d "$ancestor" && "$ancestor" != / ]]; do
      suffix="/${ancestor##*/}$suffix"
      ancestor=${ancestor%/*}
      [[ -n "$ancestor" ]] || ancestor=/
    done
    physical=$(cd "$ancestor" && pwd -P) || return 1
    value="${physical%/}$suffix"
    printf '%s\n' "${value:-/}"
  fi
}

retired_known_sdd_origin() {
  local origin
  origin=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  origin=${origin%/}
  origin=${origin%.git}
  case "$origin" in
    https://github.com/ingwarski/sdd-pipeline-skills|git@github.com:ingwarski/sdd-pipeline-skills|ssh://git@github.com/ingwarski/sdd-pipeline-skills|https://github.com/ingwarski/codex-skills|git@github.com:ingwarski/codex-skills|ssh://git@github.com/ingwarski/codex-skills) return 0 ;;
  esac
  return 1
}

retired_add_root() {
  local root=$1 i
  [[ "$root" == /* ]] || root="$PWD/$root"
  root=$(retired_normalize "$root") || return 1
  [[ "$root" != / ]] || { printf 'Cleanup root cannot be a filesystem root.\n' >&2; return 1; }
  if [[ -e "$root" || -L "$root" ]]; then
    [[ -d "$root" && -r "$root" && -x "$root" ]] || {
      printf 'Cleanup root is not an accessible directory: %s\n' "$root" >&2; return 1;
    }
  fi
  for ((i=0; i<retired_root_count; i++)); do
    [[ "${retired_roots[i]}" != "$root" ]] || return 0
  done
  retired_roots[retired_root_count]=$root
  retired_root_count=$((retired_root_count + 1))
}

retired_prepare() {
  local name root i policy
  [[ -f "$retired_policy" && ! -L "$retired_policy" ]] || {
    printf 'Missing retirement policy.\n' >&2; return 1;
  }
  policy=$(sed 's/\r$//' "$retired_policy")
  [[ "$policy" == "$(printf '%s\n' "${retired_names[@]}")" ]] || {
    printf 'Invalid retirement policy: only the two retired business skills are allowed.\n' >&2; return 1;
  }
  for name in "${retired_names[@]}"; do
    if manifest_entries | awk -F '|' -v name="$name" '$1==name {found=1} END {exit !found}'; then
      printf 'Retired skill is still active: %s\n' "$name" >&2; return 1
    fi
  done
  retired_add_root "$repo_root/skills"
  if [[ $want_codex -eq 1 ]]; then
    retired_add_root "$codex_dir"
    retired_add_root "$repo_root/.agents/skills"
    retired_add_root "$repo_root/.codex/skills"
    if [[ $codex_dir_explicit -eq 0 ]]; then
      retired_add_root "$HOME/.agents/skills"
      retired_add_root "$HOME/.codex/skills"
      [[ -z "${CODEX_HOME:-}" ]] || retired_add_root "$CODEX_HOME/skills"
    fi
  fi
  if [[ $want_claude -eq 1 ]]; then
    retired_add_root "$claude_dir"
    retired_add_root "$repo_root/.claude/skills"
  fi
  for ((i=0; i<retired_extra_count; i++)); do retired_add_root "${retired_extra_roots[i]}"; done
  if [[ $retired_source_count -gt 0 ]]; then
    printf '%s\n' '--retired-source is no longer needed. Use --cleanup-dir OLD_CLONE/skills to include another clone.'
  fi
  # These locations are read only to purge backups made by the former updater.
  # Never create a backup or delete a container based on its name alone.
  for root in "$HOME/.sdd-pipeline/retired-skills" "${SDD_SKILL_BACKUP_DIR:-}"; do
    [[ -n "$root" ]] || continue
    root=$(retired_normalize "$root") || return 1
    [[ "$root" != / ]] || { printf 'Invalid former backup location.\n' >&2; return 1; }
    retired_backup_roots[retired_backup_root_count]=$root
    retired_backup_root_count=$((retired_backup_root_count + 1))
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
