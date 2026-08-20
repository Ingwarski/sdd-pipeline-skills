#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_root=$(mktemp -d "${TMPDIR:-/tmp}/codex-sdd-installer.XXXXXX")

cleanup() {
  case "$test_root" in
    "${TMPDIR:-/tmp}"/codex-sdd-installer.*) rm -rf -- "$test_root" ;;
    *) printf 'Refusing unsafe cleanup path: %s\n' "$test_root" >&2 ;;
  esac
}
trap cleanup EXIT

codex_dir="$test_root/codex"
claude_dir="$test_root/claude"
mkdir -p "$codex_dir" "$claude_dir/to-prd"
printf '%s\n' 'unrelated skill' > "$claude_dir/to-prd/marker.txt"
ln -s "$repo_root/skills/to-prd" "$codex_dir/to-prd"

first_output=$("$repo_root/install.sh" --all --codex-dir "$codex_dir" --claude-dir "$claude_dir")
printf '%s\n' "$first_output"

while IFS='|' read -r skill_name relative_path legacy_name; do
  [[ -L "$codex_dir/$skill_name" ]]
  [[ -L "$claude_dir/$skill_name" ]]
  cmp -s "$repo_root/$relative_path/SKILL.md" "$codex_dir/$skill_name/SKILL.md"
  cmp -s "$repo_root/$relative_path/SKILL.md" "$claude_dir/$skill_name/SKILL.md"
done < <(sed -nE 's/^[[:space:]]*\{"name": "([^"]+)", "path": "([^"]+)", "legacy_name": (null|"([^"]*)")\},?$/\1|\2|\4/p' "$repo_root/skills-manifest.json")

[[ ! -e "$codex_dir/to-prd" && ! -L "$codex_dir/to-prd" ]]
[[ -f "$claude_dir/to-prd/marker.txt" ]]

second_output=$("$repo_root/install.sh" --all --codex-dir "$codex_dir" --claude-dir "$claude_dir")
printf '%s\n' "$second_output"
[[ "$second_output" == *"created=0 already-installed=26"* ]]

prior_clone="$test_root/prior-clone"
rm "$codex_dir/to-screen-map"
ln -s "$prior_clone/skills/to-screen-map" "$codex_dir/to-screen-map"
printf '%s\n' "$prior_clone" > "$codex_dir/.codex-sdd-skills-source"
"$repo_root/install.sh" --codex --repair --codex-dir "$codex_dir" > /dev/null
cmp -s "$repo_root/skills/to-screen-map/SKILL.md" "$codex_dir/to-screen-map/SKILL.md"

rm "$codex_dir/to-sdd-pipeline"
mkdir "$codex_dir/to-sdd-pipeline"
rm "$codex_dir/to-wireframes"
if "$repo_root/install.sh" --codex --codex-dir "$codex_dir" > "$test_root/conflict.out" 2>&1; then
  printf '%s\n' 'Expected a conflict but installation succeeded.' >&2
  exit 1
fi
grep -q 'CONFLICT real file/directory exists' "$test_root/conflict.out"
[[ ! -e "$codex_dir/to-wireframes" && ! -L "$codex_dir/to-wireframes" ]]
rmdir "$codex_dir/to-sdd-pipeline"
"$repo_root/install.sh" --codex --codex-dir "$codex_dir" > /dev/null

"$repo_root/install.sh" --all --uninstall --codex-dir "$codex_dir" --claude-dir "$claude_dir" > /dev/null
while IFS='|' read -r skill_name relative_path legacy_name; do
  [[ ! -e "$codex_dir/$skill_name" && ! -L "$codex_dir/$skill_name" ]]
  [[ ! -e "$claude_dir/$skill_name" && ! -L "$claude_dir/$skill_name" ]]
done < <(sed -nE 's/^[[:space:]]*\{"name": "([^"]+)", "path": "([^"]+)", "legacy_name": (null|"([^"]*)")\},?$/\1|\2|\4/p' "$repo_root/skills-manifest.json")
[[ -f "$claude_dir/to-prd/marker.txt" ]]

printf '%s\n' 'Unix installer tests passed.'
