# Installation, Updating and Cleanup

Run commands from the durable SDD clone. Install Python 3.9+ first; both platform installers use the same standard-library parser, and the pipeline checker uses the same runtime. Missing Python or invalid manifest/source/reference files stop before cleanup or link changes. No Python package is needed for installation or the checker.


Clone this repository and run its installer. It creates directory links from each agent's skill location to this clone; it never copies a skill directory. Use `update.sh` or `update.ps1` for later updates so retired installations are cleaned up too. A plain `git pull` updates linked content but does not clean old installed links or copies.

### Recommended agent-assisted installation

An unskilled user should open Codex or Claude Code, paste the prompt below, and let the agent perform and verify the installation. The repository's `AGENTS.md` and `CLAUDE.md` give both agents the same safety contract.

```text
Install the complete SDD skill set from https://github.com/Ingwarski/sdd-pipeline-skills for local Codex and local Claude Code.

If this workspace is not already a durable Git clone of that repository, clone it under my normal Projects directory; do not use a temporary, cache, or download directory. If a durable clone already exists, verify its origin and update it only by a clean fast-forward; preserve local changes and stop instead of overwriting them. Then read the repository's AGENTS.md or CLAUDE.md, the README Installation section, and skills-manifest.json.

Detect my operating system and run the repository-provided installer: install.sh on macOS/Linux or install.ps1 on Windows. For an existing clean main checkout, prefer update.sh or update.ps1. Do not recreate link logic or copy skill directories. Permanently delete communications-audit and issue-happypro-certificate from the selected skill folders, including modified copies and links from any source. Do not back up, archive, relocate, or move them to Trash. Report any deletion failure. Keep other skills unchanged, including unrelated to-prd; SDD uses to-sdd-prd. On Windows, allow the directory-junction fallback.

Install all 13 SDD skills for both tools, run the installer a second time to prove it is idempotent, and verify every installed SKILL.md through its destination path. Report the durable clone path, Codex and Claude Code destination roots, link type used, 13/13 validation result, preserved conflicts, and whether either tool needs a restart. Ask me only if a real conflict or permission boundary remains after the installer has exhausted its safe fallback.
```

The prompt moves platform detection, link creation, conflict handling, and verification to the agent. It does not authorize silent installation merely because the repository was opened.

macOS or Linux:

```bash
./install.sh --all
```

Windows PowerShell:

```powershell
.\install.ps1 -All
```

Nontechnical users can double-click `Install Skills.command` on macOS or `Install Skills.cmd` on Windows. Both launch the same platform installer and install the complete 13-skill SDD set for local Codex and local Claude Code.

The source of every link is always this repository clone. For example, if Windows cloned the repository to `C:\Users\Alex\Projects\sdd-pipeline-skills`, the Claude Code link is `%USERPROFILE%\.claude\skills\to-sdd-pipeline -> C:\Users\Alex\Projects\sdd-pipeline-skills\skills\to-sdd-pipeline`. Codex uses `$HOME/.agents/skills` by default. Existing installations that already use `$CODEX_HOME/skills` or the legacy `$HOME/.codex/skills` continue there. Override detection with `CODEX_SKILLS_DIR`, `CLAUDE_SKILLS_DIR`, `--codex-dir`/`--claude-dir`, or `-CodexDir`/`-ClaudeDir`.

Windows first attempts a true directory symbolic link. When local policy blocks that operation, it creates an NTFS directory junction instead. Both remain links to the clone; neither copies skill contents.

The installers validate the 13 sources, permanently remove the retired business skills, then preflight active SDD destinations before changing SDD links. A real directory, file, or foreign link occupying an active SDD name is a conflict and is not overwritten. Retirement can therefore complete even if a separate SDD conflict blocks installation. `--repair`/`-Repair` replaces only previously recorded SDD links. `--uninstall`/`-Uninstall` removes only active SDD links owned by this clone; retirement applies to install, repair, and update.

The SDD PRD owner is named `to-sdd-prd` so it can coexist with third-party skills named `to-prd`, including older Matt Pocock installations. During migration, the installer removes `to-prd` only when it is an old symlink to this repository. Any unrelated `to-prd` is preserved.

Install only one local agent when needed:

```bash
./install.sh --codex
./install.sh --claude
```

```powershell
.\install.ps1 -Codex
.\install.ps1 -Claude
```

Moving or deleting the clone breaks its links. Re-run the installer from the new clone with `--repair` or `-Repair`; the installer uses its prior source receipt to replace only links it owns. These personal filesystem links apply to local Codex and Claude Code sessions, not remote/cloud sessions that cannot read the user's local disk.

## Updating and cleanup

From a clean `main` checkout, run:

```bash
./update.sh --all
```

```powershell
.\update.ps1 -All
```

Or double-click `Update Skills.command` on macOS / `Update Skills.cmd` on Windows.
For an older clone without these files, first fast-forward it with
`git pull --ff-only`, then run the updater. The [student prompt](../STUDENT-SKILL-UPDATE-PROMPT.md)
guides an agent through that first update.

The updater verifies the GitHub origin and `main` branch, permanently removes the
two retired names, then checks for unrelated local edits or unpublished/diverging
commits. It fast-forwards and runs the newly downloaded installer with repair
enabled. Retirement can finish even if a later Git check stops the update. It does
not reset Git history or discard unrelated work. Use
`--codex` / `--claude` or `-Codex` / `-Claude` to select one agent.

### Retired business skills

`communications-audit` and `issue-happypro-certificate` were accidentally included
in the old SDD repository. Every install, repair, and update permanently deletes
both names from the managed skill folders.

- Delete entire copied directories, including local edits and extra files.
- Delete links and broken links regardless of their source or ownership receipt.
- Do not create backups, archives, relocated copies, or Trash entries.
- Do not exempt a copy because its content differs from the original.
- Verify both names are absent; a failed deletion fails the command.

The exact deletion list is [retired-skills.txt](../retired-skills.txt). Other skill
names are not retired, and all 13 SDD skill names and behavior remain unchanged.
For cleanup without installing or changing SDD links, run `./install.sh --all
--retire-only` or `.\install.ps1 -All -RetireOnly` with the same destination and
cleanup-directory options. The updater uses this mode before its local-change
check, so untracked retired copies inside the clone cannot block their removal.

Cleanup covers this clone's `skills/`, its selected agents' repo-local skill
folders, and the selected personal agent roots. Default Codex discovery includes
`.agents/skills`, legacy `.codex/skills`, and `$CODEX_HOME/skills`. Explicit
destination overrides limit personal-root discovery.

Add other confirmed project skill folders or old SDD clones' `skills/` folders
with `--cleanup-dir PATH` (repeatable) or `-CleanupDir PATH1,PATH2`. There is no
whole-disk scan. Directory links are removed without following their targets;
include another old clone's skill folder explicitly to delete its source copies.
The former `--retired-source` / `-RetiredSource` proof option is no longer needed.

The updater also permanently deletes matching retirement backups made by the
previous version in `$HOME/.sdd-pipeline/retired-skills/` or the former
`SDD_SKILL_BACKUP_DIR`. An `original-path.txt` record must match one of the selected
skill roots; unrelated backup folders are not deletion targets. No new backup
location is created.

This is irreversible filesystem deletion, not Git-history rewriting. A GitHub
push cannot delete files on a machine that has not run the update.

### Automatic updates

This repository installs no scheduler, Git hook, background agent, or automatic
network check. Pushing to GitHub does not update other machines by itself.

Automatic updates are possible after each user opts in once to a local scheduled
task that runs the updater. A daily or between-session check is preferable to
changing skills during a running task. For a classroom rollout, use tested
versions and preserve an opt-out; a tested-release channel is a future addition,
not part of the current updater, which follows `main`.

After files arrive locally, Codex detects local skill changes and follows skill
links; restart it if the update is not visible. That local reloading is different
from downloading GitHub changes. See [official skill documentation](https://developers.openai.com/codex/skills/).
