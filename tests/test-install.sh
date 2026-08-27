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

custom_clone="$test_root/custom-clone"
mkdir -p "$custom_clone/skills/communications-audit"
printf '%s\n' 'custom skill fixture' > "$custom_clone/skills/communications-audit/SKILL.md"
for install_dir in "$codex_dir" "$claude_dir"; do
  ln -s "$custom_clone/skills/communications-audit" "$install_dir/communications-audit"
  printf '%s\n' "$custom_clone" > "$install_dir/.custom-agent-skills-source"
done

assert_custom_preserved() {
  for install_dir in "$codex_dir" "$claude_dir"; do
    [[ "$(readlink "$install_dir/communications-audit")" == "$custom_clone/skills/communications-audit" ]]
    [[ "$(sed -n '1p' "$install_dir/.custom-agent-skills-source")" == "$custom_clone" ]]
    cmp -s "$custom_clone/skills/communications-audit/SKILL.md" "$install_dir/communications-audit/SKILL.md"
  done
}

source_count=0
for source_dir in "$repo_root"/skills/*; do
  [[ -d "$source_dir" && -f "$source_dir/SKILL.md" ]]
  source_count=$((source_count + 1))
done
[[ "$source_count" -eq 13 ]]

first_output=$("$repo_root/install.sh" --all --codex-dir "$codex_dir" --claude-dir "$claude_dir")
printf '%s\n' "$first_output"
assert_custom_preserved

while IFS='|' read -r skill_name relative_path legacy_name; do
  [[ -L "$codex_dir/$skill_name" ]]
  [[ -L "$claude_dir/$skill_name" ]]
  cmp -s "$repo_root/$relative_path/SKILL.md" "$codex_dir/$skill_name/SKILL.md"
  cmp -s "$repo_root/$relative_path/SKILL.md" "$claude_dir/$skill_name/SKILL.md"
  grep -q 'working_language' "$repo_root/$relative_path/SKILL.md"
  grep -Fq 'For Ukrainian (`uk`)' "$repo_root/$relative_path/SKILL.md"
done < <(sed -nE 's/^[[:space:]]*\{"name": "([^"]+)", "path": "([^"]+)", "legacy_name": (null|"([^"]*)")\},?$/\1|\2|\4/p' "$repo_root/skills-manifest.json")

grep -q 'working_language' "$repo_root/skills/to-sdd-pipeline/references/claude-design-handoff.md"
grep -q 'preserved_english_terms' "$repo_root/skills/to-sdd-pipeline/references/claude-design-handoff.md"
grep -q 'H1-H10 Heuristic Contract' "$repo_root/skills/to-sdd-pipeline/references/heuristic-usability-review.md"
grep -q 'heuristic_usability_review' "$repo_root/skills/to-sdd-pipeline/references/heuristic-usability-review.md"

[[ ! -e "$codex_dir/to-prd" && ! -L "$codex_dir/to-prd" ]]
[[ -f "$claude_dir/to-prd/marker.txt" ]]

second_output=$("$repo_root/install.sh" --all --codex-dir "$codex_dir" --claude-dir "$claude_dir")
printf '%s\n' "$second_output"
[[ "$second_output" == *"created=0 already-installed=26"* ]]
assert_custom_preserved

prior_clone="$test_root/prior-clone"
rm "$codex_dir/to-screen-map"
ln -s "$prior_clone/skills/to-screen-map" "$codex_dir/to-screen-map"
printf '%s\n' "$prior_clone" > "$codex_dir/.codex-sdd-skills-source"
"$repo_root/install.sh" --codex --repair --codex-dir "$codex_dir" > /dev/null
cmp -s "$repo_root/skills/to-screen-map/SKILL.md" "$codex_dir/to-screen-map/SKILL.md"
assert_custom_preserved

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

assert_custom_preserved
printf '%s\n' 'Unix installer tests passed.'
