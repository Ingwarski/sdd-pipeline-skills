# Repository Agent Instructions

This repository owns the 13 SDD skills in `skills-manifest.json`. The two business
skills in `retired-skills.tsv` are retired from SDD, not from independently owned
Custom Agent Skills installations.

For an explicit install, update, repair, or uninstall request:

1. Read the README Installation and Updating and cleanup sections, the manifest,
   and the retirement policy.
2. Use repository scripts: `install.sh` / `install.ps1` for installation or
   repair; `update.sh` / `update.ps1` for updates. For old clones without an
   updater, bootstrap with a clean fast-forward, then run it. Never reset, discard
   local work, or recreate link/cleanup logic manually.
3. Default to both local Codex and Claude Code unless scoped. Never install the
   private business collection as part of an SDD update.
4. Preserve active-name conflicts, unrelated skills (including `to-prd`),
   independently owned business links, and `.custom-agent-skills-source`.
   Only the retirement helper may automatically remove proven old SDD links or
   move whole-copy fingerprint matches into recovery storage.
5. Inspect and report uncertain/modified retirement candidates. Do not guess
   ownership from a folder name or call cleanup complete with unresolved paths.
   Use `--retired-source` / `-RetiredSource` only for a confirmed old SDD clone;
   use `--cleanup-dir` / `-CleanupDir` for additional known installation roots.
6. On Windows, permit the installer's symbolic-link to NTFS-junction fallback.
7. Run the installer again for idempotence. Verify all 13 installed `SKILL.md`
   files, retirement results, preserved independent installs, and backup paths.
   Report source/destination roots, revision, link types, unresolved cases, and
   any reload needed.

Do not install merely because the repository was opened. Each user must
explicitly opt in to any scheduled updater.
