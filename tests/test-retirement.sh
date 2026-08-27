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
export SDD_SKILL_BACKUP_DIR="$test_root/former-backups"
codex_dir="$test_root/codex"
claude_dir="$test_root/claude"
history="$test_root/history"
mkdir -p "$codex_dir" "$claude_dir" "$history" "$test_root/external"
printf keep > "$test_root/external/marker.txt"
git -C "$repo_root" archive 31ae0fefe00e5b79c99a6a39d418125a291731fd \
  skills/communications-audit skills/issue-happypro-certificate | tar -xf - -C "$history"
install() { "$repo_root/install.sh" --all --repair --codex-dir "$codex_dir" --claude-dir "$claude_dir" "$@"; }
assert_absent() { [[ ! -e "$1" && ! -L "$1" ]]; }
assert_retired_absent() {
  local root
  for root in "$codex_dir" "$claude_dir"; do
    assert_absent "$root/communications-audit"
    assert_absent "$root/issue-happypro-certificate"
  done
}

# Original, edited, extra-file, and Windows-line-ending copies are deleted.
cp -R "$history/skills/communications-audit" "$codex_dir/communications-audit"
printf '\nEdited local content\n' >> "$codex_dir/communications-audit/references/report-contract.md"
printf extra > "$codex_dir/communications-audit/local-notes.txt"
ln -s "$test_root/external" "$codex_dir/communications-audit/nested-link"
mkdir "$claude_dir/issue-happypro-certificate"
awk '{printf "%s\r\n",$0}' "$history/skills/issue-happypro-certificate/SKILL.md" > "$claude_dir/issue-happypro-certificate/SKILL.md"
result=$(install)
[[ "$result" == *"permanently-deleted=2"* && "$result" == *"remaining=0 backups-created=0"* ]]
assert_retired_absent
[[ -f "$test_root/external/marker.txt" && ! -e "$SDD_SKILL_BACKUP_DIR" ]]
result=$(install)
[[ "$result" == *"permanently-deleted=0"* ]]

# Broken links and unknown origins need no ownership exception or receipt.
ln -s "$test_root/missing/skills/communications-audit" "$codex_dir/communications-audit"
ln -s "../missing/issue-happypro-certificate" "$claude_dir/issue-happypro-certificate"
install > /dev/null
assert_retired_absent

# A custom-source receipt does not exempt either retired name.
for name in communications-audit issue-happypro-certificate; do
  ln -s "$history/skills/$name" "$codex_dir/$name"
done
printf '%s\n' "$history" > "$codex_dir/.custom-agent-skills-source"
install > /dev/null
assert_retired_absent
[[ -f "$history/skills/communications-audit/SKILL.md" ]]
[[ -f "$history/skills/issue-happypro-certificate/SKILL.md" ]]

# Other project skill folders are explicitly included, without a whole-disk scan.
project_skills="$test_root/project/.agents/skills"
mkdir -p "$project_skills/communications-audit"
printf local-copy > "$project_skills/communications-audit/SKILL.md"
printf keep > "$project_skills/unrelated.txt"
install --cleanup-dir "$project_skills" > /dev/null
assert_absent "$project_skills/communications-audit"
[[ -f "$project_skills/unrelated.txt" ]]

# Purge known backups left by the previous updater; create no replacements.
for name in communications-audit issue-happypro-certificate; do
  former="$SDD_SKILL_BACKUP_DIR/$name.ABC123"
  mkdir -p "$former"
  cp -R "$history/skills/$name" "$former/$name"
  printf '%s\r\n' "$codex_dir/$name" > "$former/original-path.txt"
done
result=$(install)
[[ "$result" == *"former-backups-deleted=2 remaining=0 backups-created=0"* ]]
assert_absent "$SDD_SKILL_BACKUP_DIR/communications-audit.ABC123"
assert_absent "$SDD_SKILL_BACKUP_DIR/issue-happypro-certificate.ABC123"

# A deletion failure must fail the run, not print a successful cleanup.
mkdir -p "$codex_dir/communications-audit" "$test_root/bin"
printf undeleted > "$codex_dir/communications-audit/SKILL.md"
export SDD_RETIRE_TEST_REAL_RM
SDD_RETIRE_TEST_REAL_RM=$(command -v rm)
export SDD_RETIRE_TEST_FAIL="$(cd "$codex_dir" && pwd -P)/communications-audit"
printf '%s\n' '#!/usr/bin/env bash' \
  'for arg in "$@"; do [[ "$arg" != "$SDD_RETIRE_TEST_FAIL" ]] || exit 1; done' \
  'exec "$SDD_RETIRE_TEST_REAL_RM" "$@"' > "$test_root/bin/rm"
chmod +x "$test_root/bin/rm"
if PATH="$test_root/bin:$PATH" install > "$test_root/failure.log" 2>&1; then
  printf 'Expected deletion failure.\n' >&2; exit 1
fi
grep -q 'Retirement deletion failed' "$test_root/failure.log"
! grep -q 'Retirement summary:' "$test_root/failure.log"
[[ -f "$codex_dir/communications-audit/SKILL.md" ]]
install > /dev/null
assert_retired_absent

# An unrelated SDD conflict does not prevent retirement; no other links change.
rm "$codex_dir/to-wireframes" "$codex_dir/to-sdd-pipeline"
mkdir -p "$codex_dir/to-sdd-pipeline" "$codex_dir/issue-happypro-certificate"
if install > "$test_root/conflict.log" 2>&1; then exit 1; fi
assert_absent "$codex_dir/issue-happypro-certificate"
assert_absent "$codex_dir/to-wireframes"
rmdir "$codex_dir/to-sdd-pipeline"
install > /dev/null

# Delete source-checkout and repo-local installs as well.
export_root="$test_root/source export"
export_dest="$test_root/export installs"
mkdir -p "$export_root/.agents/skills/issue-happypro-certificate"
cp "$repo_root/install.sh" "$repo_root/skills-manifest.json" "$repo_root/retired-skills.txt" "$export_root/"
cp -R "$repo_root/scripts" "$repo_root/skills" "$export_root/"
cp -R "$history/skills/communications-audit" "$export_root/skills/communications-audit"
"$export_root/install.sh" --codex --codex-dir "$export_dest" > /dev/null
assert_absent "$export_root/skills/communications-audit"
assert_absent "$export_root/.agents/skills/issue-happypro-certificate"
[[ -f "$export_dest/to-sdd-pipeline/SKILL.md" ]]

# The policy cannot silently expand deletion to another skill.
mkdir "$export_dest/communications-audit"
printf '%s\n' 'communications-audit' 'issue-happypro-certificate' 'to-wireframes' > "$export_root/retired-skills.txt"
if "$export_root/install.sh" --codex --codex-dir "$export_dest" > "$test_root/policy.log" 2>&1; then exit 1; fi
grep -q 'Invalid retirement policy' "$test_root/policy.log"
[[ -d "$export_dest/communications-audit" && -f "$export_dest/to-wireframes/SKILL.md" ]]

while IFS='|' read -r name relative legacy; do
  cmp -s "$repo_root/$relative/SKILL.md" "$codex_dir/$name/SKILL.md"
  cmp -s "$repo_root/$relative/SKILL.md" "$claude_dir/$name/SKILL.md"
done < <(python3 "$repo_root/scripts/install_manifest.py" --root "$repo_root" --metadata-only)
printf '%s\n' 'Permanent retirement tests passed: copies, edits, broken links, receipts, former backups, failure, source/project roots, no link traversal, idempotence.'
