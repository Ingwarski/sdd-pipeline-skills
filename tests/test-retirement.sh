#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_parent="${TMPDIR:-/tmp}"
test_root=$(mktemp -d "$test_parent/sdd-retirement.XXXXXX")
cleanup() {
  case "$test_root" in
    "$test_parent"/sdd-retirement.*) rm -rf -- "$test_root" ;;
    *) printf 'Refusing unsafe cleanup: %s\n' "$test_root" >&2 ;;
  esac
}
trap cleanup EXIT
export SDD_SKILL_BACKUP_DIR="$test_root/backups"
codex_dir="$test_root/codex"
claude_dir="$test_root/claude"
history="$test_root/history"
mkdir -p "$codex_dir" "$claude_dir" "$history"
git -C "$repo_root" archive 31ae0fefe00e5b79c99a6a39d418125a291731fd \
  skills/communications-audit skills/issue-happypro-certificate | tar -xf - -C "$history"

install() {
  "$repo_root/install.sh" --all --repair --codex-dir "$codex_dir" --claude-dir "$claude_dir" "$@"
}
expect_review() {
  if install "$@" > "$test_root/review.log" 2>&1; then
    printf 'Expected review-required failure.\n' >&2; exit 1
  fi
  grep -q 'REVIEW REQUIRED' "$test_root/review.log"
}
assert_absent() { [[ ! -e "$1" && ! -L "$1" ]]; }

# Current and recorded former sources, including a relative broken link.
install > /dev/null
old_root="$test_root/missing old clone"
ln -s "$repo_root/skills/communications-audit" "$codex_dir/communications-audit"
ln -s "../missing old clone/skills/issue-happypro-certificate" "$claude_dir/issue-happypro-certificate"
printf '%s\n' "$old_root" > "$claude_dir/.codex-sdd-skills-source"
result=$(install)
[[ "$result" == *"links-removed=2 copies-archived=0"* ]]
assert_absent "$codex_dir/communications-audit"
assert_absent "$claude_dir/issue-happypro-certificate"
[[ ! -e "$SDD_SKILL_BACKUP_DIR" ]]
result=$(install)
[[ "$result" == *"links-removed=0 copies-archived=0"* ]]

# Whole-copy checks accept both original LF and Windows CRLF file contents.
cp -R "$history/skills/communications-audit" "$codex_dir/communications-audit"
mkdir "$claude_dir/issue-happypro-certificate"
awk '{printf "%s\r\n",$0}' "$history/skills/issue-happypro-certificate/SKILL.md" > "$claude_dir/issue-happypro-certificate/SKILL.md"
cp "$claude_dir/issue-happypro-certificate/SKILL.md" "$test_root/crlf-certificate.md"
result=$(install)
[[ "$result" == *"links-removed=0 copies-archived=2"* ]]
assert_absent "$codex_dir/communications-audit"
assert_absent "$claude_dir/issue-happypro-certificate"
audit_backup=$(find "$SDD_SKILL_BACKUP_DIR" -type d -name communications-audit)
certificate_backup=$(find "$SDD_SKILL_BACKUP_DIR" -type d -name issue-happypro-certificate)
diff -r "$history/skills/communications-audit" "$audit_backup"
cmp -s "$test_root/crlf-certificate.md" "$certificate_backup/SKILL.md"
result=$(install)
[[ "$result" == *"copies-archived=0"* ]]

# Recovery must be outside active skill folders; reject before creating it.
cp -R "$history/skills/issue-happypro-certificate" "$codex_dir/issue-happypro-certificate"
if SDD_SKILL_BACKUP_DIR="$codex_dir/recovery" install > "$test_root/backup-error.log" 2>&1; then
  printf 'Expected unsafe recovery location to be refused.\n' >&2; exit 1
fi
grep -q 'outside every skill directory' "$test_root/backup-error.log"
[[ -f "$codex_dir/issue-happypro-certificate/SKILL.md" && ! -e "$codex_dir/recovery" ]]
install > /dev/null

# A changed support file blocks every planned cleanup and install mutation.
cp -R "$history/skills/communications-audit" "$codex_dir/communications-audit"
printf '\nUser changes must survive.\n' >> "$codex_dir/communications-audit/references/report-contract.md"
cp "$codex_dir/communications-audit/references/report-contract.md" "$test_root/edited-reference.md"
ln -s "$repo_root/skills/issue-happypro-certificate" "$codex_dir/issue-happypro-certificate"
rm "$codex_dir/to-wireframes"
expect_review
cmp -s "$test_root/edited-reference.md" "$codex_dir/communications-audit/references/report-contract.md"
[[ -L "$codex_dir/issue-happypro-certificate" ]]
assert_absent "$codex_dir/to-wireframes"
mv "$codex_dir/communications-audit" "$test_root/preserved-user-copy"
install > /dev/null

# Missing or unrecognized old clone roots need explicit confirmation.
ln -s "$old_root/skills/communications-audit" "$codex_dir/communications-audit"
expect_review
[[ -L "$codex_dir/communications-audit" ]]
result=$(install --retired-source "$old_root")
[[ "$result" == *"links-removed=1"* ]]
assert_absent "$codex_dir/communications-audit"

# Existing old repositories identify their own links without name-based guesses.
old_repo="$test_root/old repository"
mkdir -p "$old_repo/skills/communications-audit"
git -C "$old_repo" init --quiet
git -C "$old_repo" remote add origin https://github.com/Ingwarski/codex-skills.git
ln -s "$old_repo/skills/communications-audit" "$codex_dir/communications-audit"
result=$(install)
[[ "$result" == *"links-removed=1"* ]]
[[ -d "$old_repo/skills/communications-audit" ]]
assert_absent "$codex_dir/communications-audit"

# A known project-local install root is cleaned only when explicitly supplied.
project_skills="$test_root/project/.agents/skills"
mkdir -p "$project_skills"
cp -R "$history/skills/issue-happypro-certificate" "$project_skills/issue-happypro-certificate"
printf '%s\n' 'unrelated data' > "$project_skills/unrelated.txt"
install > /dev/null
[[ -f "$project_skills/issue-happypro-certificate/SKILL.md" ]]
result=$(install --cleanup-dir "$project_skills")
[[ "$result" == *"copies-archived=1"* ]]
assert_absent "$project_skills/issue-happypro-certificate"
[[ -f "$project_skills/unrelated.txt" ]]

# A leftover copied folder in the source checkout is retired too (ZIP-style export).
export_root="$test_root/source export"
export_dest="$test_root/export installs"
mkdir -p "$export_root"
cp "$repo_root/install.sh" "$repo_root/skills-manifest.json" "$repo_root/retired-skills.tsv" "$export_root/"
cp -R "$repo_root/scripts" "$repo_root/skills" "$export_root/"
cp -R "$history/skills/communications-audit" "$export_root/skills/communications-audit"
result=$("$export_root/install.sh" --codex --codex-dir "$export_dest")
[[ "$result" == *"copies-archived=1"* ]]
assert_absent "$export_root/skills/communications-audit"
[[ -f "$export_dest/to-sdd-pipeline/SKILL.md" ]]

# Independent installs win even if an obsolete SDD receipt names that same root.
custom_root="$test_root/custom clone"
mkdir -p "$custom_root/skills"
printf '%s\n' '{"skill_set":"custom-agent-skills"}' > "$custom_root/skills-manifest.json"
cp -R "$history/skills/communications-audit" "$custom_root/skills/communications-audit"
cp -R "$history/skills/issue-happypro-certificate" "$custom_root/skills/issue-happypro-certificate"
ln -s "$custom_root/skills/communications-audit" "$codex_dir/communications-audit"
ln -s "$custom_root/skills/issue-happypro-certificate" "$claude_dir/issue-happypro-certificate"
printf '%s\n' "$custom_root" > "$codex_dir/.custom-agent-skills-source"
printf '%s\n' "$custom_root" > "$claude_dir/.codex-sdd-skills-source"
result=$(install --retired-source "$custom_root")
[[ "$result" == *"links-removed=0 copies-archived=0 independent-preserved=2"* ]]
[[ -L "$codex_dir/communications-audit" && -L "$claude_dir/issue-happypro-certificate" ]]
[[ "$(sed -n '1p' "$codex_dir/.custom-agent-skills-source")" == "$custom_root" ]]
diff -r "$history/skills/communications-audit" "$custom_root/skills/communications-audit"

while IFS='|' read -r name relative; do
  cmp -s "$repo_root/$relative/SKILL.md" "$codex_dir/$name/SKILL.md"
  cmp -s "$repo_root/$relative/SKILL.md" "$claude_dir/$name/SKILL.md"
done < <(sed -nE 's/^[[:space:]]*\{"name": "([^"]+)", "path": "([^"]+)".*$/\1|\2/p' "$repo_root/skills-manifest.json")
printf '%s\n' 'Retirement tests passed: old/broken links, LF/CRLF copies, recovery safety, edits, source copies, explicit roots, independent installs, idempotence.'
