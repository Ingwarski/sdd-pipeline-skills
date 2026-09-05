# Installation, Updating and Cleanup

Run commands from the durable SDD clone. Mutating installer/update work requires Python 3.12+; Python 3.14 is the recommended stable series under [runtime policy](../runtime-policy.json). Both installers and the checker use the standard library, with no student packages or Node dependency. Missing Python or invalid sources/references stop before cleanup or link changes.

For new student clones, use `git clone --branch stable https://github.com/Ingwarski/sdd-pipeline-skills.git`, then inside the clone `git switch -c main`. The local branch remains `main`; its selected remote channel is `stable`. Run the installer below. It creates links, never skill copies. Later use the updater: plain `git pull` does not perform retirement cleanup.

### Agent-assisted installation or update

Paste the single [install-or-update prompt](../INSTALL-OR-UPDATE-PROMPT.md) into a local file/terminal agent. It first checks revision, exact installed targets, packaged resources and Python support. A clean, current installation with supported Python stops without reinstalling or upgrading Python. Necessary install/update work uses the latest official stable Python, without replacing the OS interpreter. Opening this repository alone does not authorize installation.

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

From local `main`, select the tested student channel:

```bash
./update.sh --channel stable --all
```

```powershell
.\update.ps1 -Channel stable -All
```

Omitting the channel, including the existing double-click launchers, retains the legacy `main` behavior. Maintainers can explicitly select `--channel main` / `-Channel main`; it may contain changes whose CI has not finished.
For setup, migration from an older clone or a regular agent-run update, use the
single [install-or-update prompt](../INSTALL-OR-UPDATE-PROMPT.md).

The updater verifies the GitHub origin and `main` branch, permanently removes the
two retired names, then checks for unrelated local edits or unpublished/diverging
commits. It fast-forwards and runs the newly downloaded installer with repair
enabled. Retirement can finish even if a later Git check stops the update. It does
not reset Git history or discard unrelated work. Use
`--codex` / `--claude` or `-Codex` / `-Claude` to select one agent.

`stable` advances only after all content, Linux, macOS and Windows CI checks pass for the current `main` commit. Publication never force-pushes. If the channel is absent, unavailable, or behind/divergent from the local checkout, stop: do not silently fall back or downgrade.

Read-only local validation: run `python3 scripts/installation_status.py --root CLONE --skill-root CODEX_ROOT --skill-root CLAUDE_ROOT`, substituting discovered absolute paths and the detected Python executable. Add confirmed legacy/project roots via repeated `--cleanup-root`. It checks exact link/junction targets and recursively linked resources, not merely 13 existing SKILL.md files. Remote revision, clean Git state and Python support are separate checks; never interpret this helper alone as “up to date.”

For old clones missing the helper/updater/channel option, a clean `git merge --ff-only FETCH_HEAD` after fetching `stable` bootstraps current tooling. If retired copies block that merge, use a full temporary checkout of the fetched revision only for its `--retire-only` / `-RetireOnly` installer, with explicit managed roots and the old clone's `skills/` as a cleanup root. Never install links from that temporary checkout or recreate deletion logic by hand. Unrelated changes still block updating; cleanup already performed is irreversible and must be reported.

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
changing skills during a running task. Use the tested `stable` channel and preserve an opt-out. Repository CI publication is not an automatic download or a scheduler on student machines.

After files arrive locally, Codex detects local skill changes and follows skill
links; restart it if the update is not visible. That local reloading is different
from downloading GitHub changes. See [official skill documentation](https://developers.openai.com/codex/skills/).
