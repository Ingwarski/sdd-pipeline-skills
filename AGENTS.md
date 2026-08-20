# Repository Agent Instructions

When the user asks to install, update, repair, or uninstall this repository's SDD skills:

1. Read `README.md` Installation and `skills-manifest.json`.
2. Detect the operating system and use the repository installer: `install.sh` on macOS/Linux or `install.ps1` on Windows. Do not recreate link logic manually and never copy skill directories.
3. Default to both local Codex and local Claude Code unless the user scopes the request to one.
4. Preserve every real file/directory and every link not owned by this repository. Stop and explain an exact conflict instead of overwriting it.
5. On Windows, allow `install.ps1` to fall back from a directory symbolic link to an NTFS directory junction.
6. Run the installer a second time to verify idempotence, validate all 13 installed `SKILL.md` files through their destination paths, and report source root, destination roots, link types, conflicts, and any restart needed.

Do not install merely because the repository was opened. Installation requires an explicit user request.
