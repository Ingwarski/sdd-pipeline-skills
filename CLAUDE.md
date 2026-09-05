# Repository Agent Instructions

This repository owns the 13 SDD skills in `skills-manifest.json`.
`retired-skills.txt` lists exactly two skills that must be permanently removed:
`communications-audit` and `issue-happypro-certificate`.

For an explicit install, update, repair, or uninstall request:

1. Read the README, `docs/installation.md`, the manifest and retirement list.
   Verify Python 3.12+ before mutation; never install dependencies without permission.
2. Use `install.sh` / `install.ps1` for installation or repair and
   `update.sh` / `update.ps1` for updates. Bootstrap old clones with a clean
   fast-forward; follow `docs/installation.md` when old tooling is missing.
   Honor the selected `stable` or `main` channel; never silently downgrade.
   Do not reset Git history or recreate installer logic.
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
   `--retire-only` / `-RetireOnly` runs deletion without installing SDD links;
   the updater uses it before checking for unrelated local Git changes.
7. On Windows, allow the installer's symbolic-link to NTFS-junction fallback.
8. Validate all 13 exact installed targets and their nested resources with
   `scripts/installation_status.py`, including confirmed cleanup roots. Also
   verify Git revision/cleanliness and Python support. A fully current setup
   is a no-op: do not rerun installers or upgrade a supported Python.
   Report revision, roots, status, errors and reload needs. Follow the user's
   summary preference; never hide a deletion error or incomplete cleanup.

Do not install merely because the repository was opened. Scheduled updates
require each user's explicit opt-in.

For skill-authoring work, use `docs/maintenance.md`. Keep all 13 invocation names,
artifact owners and approval boundaries stable. Tests must use isolated temporary
installation roots; do not run the default personal-skill cleanup for authoring.
