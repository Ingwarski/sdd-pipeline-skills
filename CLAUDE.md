# Repository Agent Instructions

This repository owns the 13 SDD skills in `skills-manifest.json`.
`retired-skills.txt` lists exactly two skills that must be permanently removed:
`communications-audit` and `issue-happypro-certificate`.

For an explicit install, update, repair, or uninstall request:

1. Read the README Installation and Updating and cleanup sections, the manifest,
   and the retirement list.
2. Use `install.sh` / `install.ps1` for installation or repair and
   `update.sh` / `update.ps1` for updates. Bootstrap old clones with a clean
   fast-forward. Do not reset Git history or recreate installer logic.
3. Default to both local Codex and Claude Code unless scoped. During install,
   repair, or update, permanently delete both retired names from the managed
   skill folders, including edited copies and links from any source. No backup,
   archive, relocation, Trash, fingerprint exception, or ownership exception.
4. Use `--cleanup-dir` / `-CleanupDir` for additional confirmed project skill
   folders and old SDD clones' `skills/` folders. Do not scan or delete arbitrary
   repositories across the disk. Links are removed without following their targets.
5. Do not install the private business collection. Keep unrelated skills,
   including third-party `to-prd`, unchanged. SDD uses `to-sdd-prd`.
6. Report deletion errors and remaining paths as failures, never completed cleanup.
   Retirement may finish even if a separate conflict blocks SDD link installation.
   The installer also deletes its former retirement backups for the selected roots.
7. On Windows, allow the installer's symbolic-link to NTFS-junction fallback.
8. Rerun installation to verify idempotence. Check all 13 installed `SKILL.md`
   files and the absence of both retired names. Report the revision, roots,
   permanent deletions, unresolved errors, and any required reload.

Do not install merely because the repository was opened. Scheduled updates
require each user's explicit opt-in.
