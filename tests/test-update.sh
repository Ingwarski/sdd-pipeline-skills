#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_parent="${TMPDIR:-/tmp}"
test_root=$(mktemp -d "$test_parent/sdd-update.XXXXXX")
cleanup() {
  case "$test_root" in
    "$test_parent"/sdd-update.*) rm -rf -- "$test_root" ;;
    *) printf 'Refusing unsafe cleanup: %s\n' "$test_root" >&2 ;;
  esac
}
trap cleanup EXIT
publisher="$test_root/publisher"
checkout="$test_root/checkout"
remote="$test_root/remote.git"
mkdir -p "$publisher/scripts" "$test_root/bin"
cp "$repo_root/update.sh" "$publisher/update.sh"
cp "$repo_root/scripts/retired-skills.sh" "$publisher/scripts/retired-skills.sh"
cp "$repo_root/retired-skills.txt" "$publisher/retired-skills.txt"
printf '%s\n' '#!/usr/bin/env bash' '[[ "$1" == --retire-only ]] || exit 99' > "$publisher/install.sh"
git -C "$publisher" init --quiet --initial-branch=main
git -C "$publisher" add -- update.sh install.sh scripts/retired-skills.sh retired-skills.txt
git -C "$publisher" -c user.name='SDD tests' -c user.email='sdd-tests@example.invalid' commit --quiet -m initial
git clone --quiet --bare "$publisher" "$remote"
git clone --quiet "$remote" "$checkout"
git -C "$checkout" remote set-url origin https://github.com/Ingwarski/sdd-pipeline-skills.git
printf '%s\n' '#!/usr/bin/env bash' '[[ "$1" != --retire-only ]] || exit 0' 'printf "%s\n" new "$@" > "$SDD_UPDATE_TEST_RESULT"' > "$publisher/install.sh"
git -C "$publisher" add -- install.sh
git -C "$publisher" -c user.name='SDD tests' -c user.email='sdd-tests@example.invalid' commit --quiet -m updated
git -C "$publisher" push --quiet "$remote" main

# Only the network fetch is redirected to a disposable local remote.
export SDD_UPDATE_TEST_GIT
SDD_UPDATE_TEST_GIT=$(command -v git)
export SDD_UPDATE_TEST_REMOTE="$remote"
export SDD_UPDATE_TEST_RESULT="$test_root/result.txt"
export SDD_UPDATE_TEST_FETCH="$test_root/fetched"
printf '%s\n' '#!/usr/bin/env bash' \
  'if [[ "$1" == -C && "$3" == fetch ]]; then' \
  '  printf fetched > "$SDD_UPDATE_TEST_FETCH"' \
  '  exec "$SDD_UPDATE_TEST_GIT" -C "$2" fetch --quiet "$SDD_UPDATE_TEST_REMOTE" main' \
  'fi' \
  'exec "$SDD_UPDATE_TEST_GIT" "$@"' > "$test_root/bin/git"
chmod +x "$test_root/bin/git"
run_update() { PATH="$test_root/bin:$PATH" bash "$checkout/update.sh" --codex; }
expect_failure() {
  local message=$1
  if run_update > "$test_root/failure.log" 2>&1; then
    printf 'Expected updater to stop: %s\n' "$message" >&2; exit 1
  fi
  grep -q "$message" "$test_root/failure.log"
  [[ ! -e "$SDD_UPDATE_TEST_RESULT" ]]
}

run_update > /dev/null
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$(git -C "$publisher" rev-parse HEAD)" ]]
[[ "$(sed -n '1p' "$SDD_UPDATE_TEST_RESULT")" == new ]]
grep -qx -- '--repair' "$SDD_UPDATE_TEST_RESULT"
grep -qx -- '--codex' "$SDD_UPDATE_TEST_RESULT"
rm "$SDD_UPDATE_TEST_RESULT" "$SDD_UPDATE_TEST_FETCH"

printf user-work > "$checkout/local.txt"
expect_failure 'Local changes exist'
[[ -f "$checkout/local.txt" && ! -e "$SDD_UPDATE_TEST_FETCH" ]]
rm "$checkout/local.txt"

git -C "$checkout" switch --quiet -c work-in-progress
expect_failure 'requires main'
[[ ! -e "$SDD_UPDATE_TEST_FETCH" ]]
git -C "$checkout" switch --quiet main

git -C "$checkout" remote set-url origin https://github.com/someone/unrelated.git
expect_failure 'not the expected SDD'
[[ ! -e "$SDD_UPDATE_TEST_FETCH" ]]
git -C "$checkout" remote set-url origin https://github.com/Ingwarski/codex-skills.git
run_update > /dev/null
[[ -f "$SDD_UPDATE_TEST_RESULT" ]]
rm "$SDD_UPDATE_TEST_RESULT" "$SDD_UPDATE_TEST_FETCH"

printf local-commit > "$checkout/local.txt"
git -C "$checkout" add -- local.txt
git -C "$checkout" -c user.name='SDD tests' -c user.email='sdd-tests@example.invalid' commit --quiet -m local
local_head=$(git -C "$checkout" rev-parse HEAD)
expect_failure 'ahead of GitHub'
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$local_head" && -f "$checkout/local.txt" ]]
printf upstream-change > "$publisher/upstream.txt"
git -C "$publisher" add -- upstream.txt
git -C "$publisher" -c user.name='SDD tests' -c user.email='sdd-tests@example.invalid' commit --quiet -m upstream
git -C "$publisher" push --quiet "$remote" main
expect_failure 'diverge'
[[ "$(git -C "$checkout" rev-parse HEAD)" == "$local_head" && ! -e "$checkout/upstream.txt" ]]

# End-to-end: a student's update downloads the real installer and deletes copies.
student="$test_root/student"
student_codex="$test_root/student-codex"
student_claude="$test_root/student-claude"
git clone --quiet "$remote" "$student"
git -C "$student" remote set-url origin https://github.com/Ingwarski/sdd-pipeline-skills.git
cp "$repo_root/install.sh" "$repo_root/skills-manifest.json" "$publisher/"
cp -R "$repo_root/skills" "$publisher/skills"
git -C "$publisher" add -- install.sh skills-manifest.json skills
git -C "$publisher" -c user.name='SDD tests' -c user.email='sdd-tests@example.invalid' commit --quiet -m real-installer
git -C "$publisher" push --quiet "$remote" main
for install_root in "$student_codex" "$student_claude"; do
  for name in communications-audit issue-happypro-certificate; do
    mkdir -p "$install_root/$name"
    printf edited-copy > "$install_root/$name/SKILL.md"
  done
done
export SDD_SKILL_BACKUP_DIR="$test_root/former-backups"
PATH="$test_root/bin:$PATH" bash "$student/update.sh" --all --codex-dir "$student_codex" --claude-dir "$student_claude" > "$test_root/student-update.log"
grep -q 'permanently-deleted=4 former-backups-deleted=0 remaining=0 backups-created=0' "$test_root/student-update.log"
for install_root in "$student_codex" "$student_claude"; do
  [[ ! -e "$install_root/communications-audit" && ! -e "$install_root/issue-happypro-certificate" ]]
  [[ -f "$install_root/to-sdd-pipeline/SKILL.md" ]]
done
[[ ! -e "$SDD_SKILL_BACKUP_DIR" ]]

# Untracked retired copies inside the clone must not block their own removal.
mkdir -p "$student/skills/communications-audit" "$student/.agents/skills/issue-happypro-certificate"
printf local-copy > "$student/skills/communications-audit/SKILL.md"
printf local-copy > "$student/.agents/skills/issue-happypro-certificate/SKILL.md"
PATH="$test_root/bin:$PATH" bash "$student/update.sh" --all --codex-dir "$student_codex" --claude-dir "$student_claude" > "$test_root/source-cleanup.log"
[[ ! -e "$student/skills/communications-audit" && ! -e "$student/.agents/skills/issue-happypro-certificate" ]]
[[ -z "$(git -C "$student" status --porcelain)" ]]
grep -q 'permanently-deleted=2' "$test_root/source-cleanup.log"
printf '%s\n' 'Updater tests passed: fresh installer, flags, dirty tree, branch, origin, old URL, ahead/diverged history.'
