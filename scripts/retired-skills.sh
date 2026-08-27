# Retirement helpers for install.sh. Data is in retired-skills.tsv, not executable.
retired_policy="$repo_root/retired-skills.tsv"
retired_roots=()
retired_root_count=0
retired_action_roots=()
retired_action_names=()
retired_action_kinds=()
retired_action_count=0
retired_removed=0
retired_archived=0
retired_preserved=0
retired_review=0

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

retired_add_root() {
  local root i
  root=$1
  [[ "$root" == /* ]] || root="$PWD/$root"
  root=$(retired_normalize "$root") || { printf 'Invalid cleanup root.\n' >&2; return 1; }
  [[ "$root" != / ]] || { printf 'Cleanup root cannot be a filesystem root.\n' >&2; return 1; }
  for ((i=0; i<retired_root_count; i++)); do
    [[ "${retired_roots[i]}" != "$root" ]] || return 0
  done
  retired_roots[retired_root_count]=$root
  retired_root_count=$((retired_root_count + 1))
}

retired_read_receipt() {
  local file=$1 value
  [[ -f "$file" && ! -L "$file" ]] || return 0
  value=$(sed -n '1{s/\r$//;p;}' "$file")
  retired_normalize "$value" 2>/dev/null || true
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

retired_source_owner() {
  local root=$1 top origin
  [[ -d "$root" ]] || { printf 'unknown'; return; }
  if [[ -f "$root/skills-manifest.json" ]]; then
    if grep -Eq '"skill_set"[[:space:]]*:[[:space:]]*"custom-agent-skills"' "$root/skills-manifest.json"; then
      printf 'foreign'; return
    fi
  fi
  top=$(git -C "$root" rev-parse --show-toplevel 2>/dev/null || true)
  if [[ -n "$top" && "$(retired_normalize "$top")" == "$(retired_normalize "$root")" ]]; then
    origin=$(git -C "$root" remote get-url origin 2>/dev/null || true)
    if [[ -n "$origin" ]]; then
      if retired_known_sdd_origin "$origin"; then printf 'sdd'; else printf 'foreign'; fi
      return
    fi
  fi
  # Old ZIP exports may have no .git directory, but retain the SDD identity.
  if [[ -f "$root/skills-manifest.json" ]] &&
     grep -Eq '"skill_set"[[:space:]]*:[[:space:]]*"sdd-pipeline"' "$root/skills-manifest.json"; then
    printf 'sdd'
  else
    printf 'unknown'
  fi
}

retired_hash() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    return 1
  fi
}

retired_known_copy() {
  local folder=$1 name=$2 entry relative hashes actual seen=0 expected
  [[ -d "$folder" && ! -L "$folder" ]] || return 1
  expected=$(awk -F '\t' -v skill="$name" 'NR>1 && $1==skill {n++} END {print n+0}' "$retired_policy")
  [[ "$expected" -gt 0 ]] || return 1
  while IFS= read -r -d '' entry; do
    relative=${entry#"$folder/"}
    [[ ! -L "$entry" ]] || return 1
    if [[ -d "$entry" ]]; then
      awk -F '\t' -v skill="$name" -v path="$relative/" 'NR>1 && $1==skill && index($2,path)==1 {ok=1} END {exit !ok}' "$retired_policy" || return 1
    elif [[ -f "$entry" ]]; then
      hashes=$(awk -F '\t' -v skill="$name" -v path="$relative" 'NR>1 && $1==skill && $2==path {print $3 "|" $4}' "$retired_policy")
      [[ -n "$hashes" ]] || return 1
      actual=$(retired_hash "$entry") || return 1
      [[ "$actual" == "${hashes%%|*}" || "$actual" == "${hashes#*|}" ]] || return 1
      seen=$((seen + 1))
    else
      return 1
    fi
  done < <(find "$folder" -mindepth 1 -print0)
  [[ "$seen" -eq "$expected" ]]
}

retired_classify() {
  local root=$1 name=$2 candidate target custom prior owner source_root i
  candidate="$root/$name"
  if [[ -L "$candidate" ]]; then
    target=$(readlink "$candidate")
    [[ "$target" == /* ]] || target="$root/$target"
    target=$(retired_normalize "$target") || { printf 'review'; return; }
    custom=$(retired_read_receipt "$root/.custom-agent-skills-source")
    if [[ -n "$custom" && "$target" == "$(retired_normalize "$custom/skills/$name")" ]]; then
      printf 'preserve'; return
    fi
    owner=unknown
    if [[ "$target" == */skills/"$name" ]]; then
      source_root=${target%/skills/"$name"}
      owner=$(retired_source_owner "$source_root")
      [[ "$owner" != foreign ]] || { printf 'preserve'; return; }
    fi
    prior=$(retired_read_receipt "$root/$receipt_name")
    if [[ "$target" == "$(retired_normalize "$repo_root/skills/$name")" ]] ||
       [[ -n "$prior" && "$target" == "$(retired_normalize "$prior/skills/$name")" ]]; then
      printf 'unlink'; return
    fi
    for ((i=0; i<retired_source_count; i++)); do
      if [[ "$target" == "$(retired_normalize "${retired_sources[i]}/skills/$name")" ]]; then
        printf 'unlink'; return
      fi
    done
    [[ "$owner" != sdd ]] || { printf 'unlink'; return; }
    printf 'review'
  elif [[ -d "$candidate" ]]; then
    if [[ "$root" == */skills ]]; then
      owner=$(retired_source_owner "${root%/skills}")
      [[ "$owner" != foreign ]] || { printf 'preserve'; return; }
    fi
    if retired_known_copy "$candidate" "$name"; then printf 'archive'; else printf 'review'; fi
  elif [[ -e "$candidate" ]]; then
    printf 'review'
  else
    printf 'absent'
  fi
}

retired_prepare() {
  local root name kind i source
  [[ -r "$retired_policy" ]] || { printf 'Missing retirement policy.\n' >&2; return 1; }
  awk -F '\t' '
    NR==1 {if($0!="skill\tfile\tsha256_lf\tsha256_crlf") bad=1; next}
    NF!=4 || $1 !~ /^[a-z0-9-]+$/ || $2 !~ /^[a-zA-Z0-9_.\/-]+$/ ||
    $2 ~ /^\// || index($2,"..") || length($3)!=64 || $3 !~ /^[a-f0-9]+$/ ||
    length($4)!=64 || $4 !~ /^[a-f0-9]+$/ || seen[$1 FS $2]++ {bad=1}
    END {exit (bad || NR<2)}
  ' "$retired_policy" || { printf 'Invalid retirement policy.\n' >&2; return 1; }

  for ((i=0; i<retired_source_count; i++)); do
    source=$(retired_normalize "${retired_sources[i]}") || return 1
    [[ "$source" != / ]] || { printf 'Retired source cannot be a filesystem root.\n' >&2; return 1; }
    retired_sources[i]=$source
  done
  retired_add_root "$repo_root/skills"
  if [[ $want_codex -eq 1 ]]; then
    retired_add_root "$codex_dir"
    if [[ $codex_dir_explicit -eq 0 ]]; then
      [[ ! -d "$HOME/.agents/skills" ]] || retired_add_root "$HOME/.agents/skills"
      [[ ! -d "$HOME/.codex/skills" ]] || retired_add_root "$HOME/.codex/skills"
      [[ -z "${CODEX_HOME:-}" || ! -d "$CODEX_HOME/skills" ]] || retired_add_root "$CODEX_HOME/skills"
    fi
  fi
  [[ $want_claude -eq 0 ]] || retired_add_root "$claude_dir"
  for ((i=0; i<retired_extra_count; i++)); do retired_add_root "${retired_extra_roots[i]}"; done

  while IFS= read -r name; do
    if manifest_entries | awk -F '|' -v name="$name" '$1==name {found=1} END {exit !found}'; then
      printf 'Retired skill is still active: %s\n' "$name" >&2
      return 1
    fi
    for ((i=0; i<retired_root_count; i++)); do
      root=${retired_roots[i]}
      kind=$(retired_classify "$root" "$name")
      case "$kind" in
        absent) ;;
        preserve)
          retired_preserved=$((retired_preserved + 1))
          printf 'Retirement: preserved independent skill %s\n' "$root/$name"
          ;;
        review)
          retired_review=$((retired_review + 1))
          printf 'REVIEW REQUIRED: %s (modified copy or unproven source; preserved)\n' "$root/$name" >&2
          ;;
        unlink|archive)
          retired_action_roots[retired_action_count]=$root
          retired_action_names[retired_action_count]=$name
          retired_action_kinds[retired_action_count]=$kind
          retired_action_count=$((retired_action_count + 1))
          ;;
      esac
    done
  done < <(awk -F '\t' 'NR>1 && !seen[$1]++ {print $1}' "$retired_policy")
  [[ $retired_review -eq 0 ]] || {
    printf '%s\n' 'Cleanup needs review; no installation changes made. Confirm unknown old clone paths with --retired-source, or resolve modified copies first.' >&2
    return 1
  }
}

retired_apply() {
  local i j root name kind path base="" backup
  # Prepare a recovery location before changing any link or copy.
  for ((i=0; i<retired_action_count; i++)); do
    if [[ "${retired_action_kinds[i]}" == archive ]]; then
      base=$(retired_normalize "${SDD_SKILL_BACKUP_DIR:-$HOME/.sdd-pipeline/retired-skills}") || return 1
      [[ "$base" != / ]] || { printf 'Recovery location cannot be a filesystem root.\n' >&2; return 1; }
      for ((j=0; j<retired_root_count; j++)); do
        [[ "$base" != "${retired_roots[j]}" && "$base" != "${retired_roots[j]}/"* ]] || {
          printf 'Recovery backup must be outside every skill directory.\n' >&2; return 1;
        }
      done
      mkdir -p "$base"
      break
    fi
  done
  for ((i=0; i<retired_action_count; i++)); do
    root=${retired_action_roots[i]}
    name=${retired_action_names[i]}
    kind=${retired_action_kinds[i]}
    path="$root/$name"
    [[ "$(retired_classify "$root" "$name")" == "$kind" ]] || {
      printf 'Retired skill changed after preflight: %s\n' "$path" >&2; return 1;
    }
    if [[ "$kind" == unlink ]]; then
      rm -- "$path"
      retired_removed=$((retired_removed + 1))
      printf 'Retirement: removed old SDD-owned link %s\n' "$path"
    else
      backup=$(mktemp -d "$base/$name.XXXXXX")
      printf '%s\n' "$path" > "$backup/original-path.txt"
      mv -- "$path" "$backup/$name"
      retired_archived=$((retired_archived + 1))
      printf 'Retirement: removed copied skill %s; recovery backup: %s\n' "$path" "$backup/$name"
    fi
  done
  printf 'Retirement summary: links-removed=%d copies-archived=%d independent-preserved=%d review-required=%d\n' \
    "$retired_removed" "$retired_archived" "$retired_preserved" "$retired_review"
}
