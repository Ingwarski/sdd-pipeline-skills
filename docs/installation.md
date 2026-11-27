# Installation, Updating and Cleanup

Installation requires Git and Python 3.12+. Python 3.14 is the recommended stable series under the [runtime policy](../runtime-policy.json). The installer and checker use the standard library. The [copyable agent prompt](../INSTALL-OR-UPDATE-PROMPT.md) keeps a supported Python for an already-current installation and follows the existing official Python policy when an installation or update is needed.

Immutable history publication requires filesystem support for atomic exclusive rename: Linux `renameat2`, macOS `renamex_np`, or Windows rename. An unsupported API or filesystem stops publication and preserves any existing record.

## Guarded entry point

Supply **one absolute destination** for the permanent source checkout. Choose its exact path even when the agent is running inside a product. For example, `Projects/Bookstore` and `Projects/SDD Pipeline Skills` can be siblings under an ordinary collection. A product root, an empty child anywhere inside it, a Git worktree, or a path that resolves into one through a symlink or Windows junction will be refused. The guard recognizes non-Git products through code, build and SDD files. For a known product without recognizable markers, such as an asset collection, set `SDD_PRODUCT_ROOT` to its absolute path. A fresh destination may be absent or an existing directory with zero entries, including hidden files.

Select `bootstrap` for a fresh destination or `update` for an existing standalone checkout. Both commands use the same file downloaded from the **exact official revision**. In the examples replace the sample destination with your own absolute path. Run the block from any working directory. The examples download the complete bootstrap into memory before running it with isolated Python. If the selected release does not contain it, wait for an appropriate release.

### macOS or Linux

```bash
(
  set -eu
  destination="$HOME/Projects/SDD Pipeline Skills"
  operation=bootstrap
  origin=https://github.com/Ingwarski/sdd-pipeline-skills.git
  ref=$(git ls-remote --exit-code "$origin" refs/heads/stable)
  revision=${ref%%[[:space:]]*}
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]]
  url="https://raw.githubusercontent.com/Ingwarski/sdd-pipeline-skills/$revision/scripts/install_location.py"
  guard=$(curl --fail --silent --show-error --location "$url")
  printf '%s\n' "$guard" | python3 -I -B - "$operation" --destination "$destination" --revision "$revision" --channel stable
)
```

### Windows PowerShell

```powershell
$destination = Join-Path $HOME 'Projects\SDD Pipeline Skills'
$operation = 'bootstrap'
$origin = 'https://github.com/Ingwarski/sdd-pipeline-skills.git'
$ref = git ls-remote --exit-code $origin refs/heads/stable
if ($LASTEXITCODE -ne 0 -or $ref -notmatch '^([0-9a-f]{40})\s+refs/heads/stable$') {
    throw 'Could not resolve the official stable revision.'
}
$revision = $Matches[1]
$url = "https://raw.githubusercontent.com/Ingwarski/sdd-pipeline-skills/$revision/scripts/install_location.py"
$guard = (Invoke-WebRequest -UseBasicParsing -ErrorAction Stop -Uri $url).Content
if ($guard -is [byte[]]) { $guard = [Text.Encoding]::UTF8.GetString($guard) }
$previousEncoding = $OutputEncoding
try {
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $guard | python -I -B - $operation --destination $destination --revision $revision --channel stable
    if ($LASTEXITCODE -ne 0) { throw "SDD $operation exited with code $LASTEXITCODE." }
} finally {
    $OutputEncoding = $previousEncoding
}
```

The default registers both Codex and Claude Code. Add `--agent codex` or `--agent claude` to select one. Use `--codex-dir` or `--claude-dir` with an absolute personal skill directory to override discovery. The guard resolves the checkout and each registration root separately. A valid checkout paired with a project-local override is refused before cloning or modifying existing installations. Review the conflicting paths in the message. Leave any existing files in place and select a different path explicitly. For an earlier accidental installation, follow [recovery](#recover-a-misplaced-installation).

The supported workflow pins the commit, clones into the exact physical destination, uses local branch `main` and links the selected agents to that durable checkout. Keep the final report showing the physical checkout, full revision, each registration directory and the 13 resolved targets **per selected agent**. A skill count alone cannot identify a misplaced installation.

## Registration and repair

From a verified checkout containing the location guard, `./install.sh --all --repair` or `.\install.ps1 -All -Repair` repairs recorded links. The Install and Update launchers in that checkout call the guarded platform scripts. A standalone copy of a launcher or a launcher from an older release is unsuitable for bootstrapping a fresh checkout.

The source of every link is always this repository clone. For example, if Windows cloned the repository to `C:\Users\Alex\Projects\sdd-pipeline-skills`, the Claude Code link is `%USERPROFILE%\.claude\skills\to-sdd-pipeline -> C:\Users\Alex\Projects\sdd-pipeline-skills\skills\to-sdd-pipeline`. Codex uses `$HOME/.agents/skills` by default. For Codex, an explicit directory takes precedence over `CODEX_SKILLS_DIR`, then `$CODEX_HOME/skills`. Without overrides, an existing `$HOME/.codex/skills` continues to serve a legacy installation when `$HOME/.agents/skills` is absent. For Claude Code, an explicit directory takes precedence over `CLAUDE_SKILLS_DIR`, then `$CLAUDE_CONFIG_DIR/skills`, then `$HOME/.claude/skills`. The platform installer flags are `--codex-dir` / `--claude-dir` or `-CodexDir` / `-ClaudeDir`.

Windows first attempts a true directory symbolic link. When local policy blocks that operation, it creates an NTFS directory junction instead. Both remain links to the clone; neither copies skill contents.

Before retirement or link changes, the installers validate the 13 sources and check active destinations for conflicts. A real directory, file or foreign link occupying an active SDD name stops installation and preserves the existing path. `--repair`/`-Repair` replaces only previously recorded SDD links. `--uninstall`/`-Uninstall` removes only active SDD links owned by this clone; retirement applies to install, repair, and update.

Use `skills-manifest.json` from the selected revision for current installation names and paths. Its `legacy_name: "to-prd"` maps the old SDD request name to `name: "to-sdd-prd"`: the same PRD owner, not a different skill or a fourteenth entry. Agents must normalize an old SDD list before checking availability and continue without rename confirmation, even if no old `to-prd` is installed. Clarify genuinely unknown names or explicit no-renaming constraints; do not invent aliases.

The canonical name allows third-party `to-prd` skills to coexist. The installer removes an old `to-prd` link/junction only when its target matches this clone or its recorded prior source; unrelated skills and unproven copies remain untouched. Do not create a second `to-prd` alias or change its third-party invocation. Installing skills does not authorize creating product documents or running the pipeline.

Moving or deleting the clone breaks its links. Re-run the installer from the new clone with `--repair` or `-Repair`; the installer uses its prior source receipt to replace only links it owns. These personal filesystem links apply to local Codex and Claude Code sessions, not remote/cloud sessions that cannot read the user's local disk.

## Updating and cleanup

Clones from before the repository fresh start have unrelated history. Follow the [fresh-clone migration guide](../HISTORY-REWRITE.md); do not force a merge, reset the old clone or upload its history. The updater procedure below applies to a clone of the current repository.

For an existing standalone checkout on local `main`, change `operation=bootstrap` to `operation=update` (PowerShell: `$operation = 'update'`) in the [guarded entry point](#guarded-entry-point) and supply that checkout’s exact path. This also handles clean, compatible checkouts from before the location guard. On an already guarded release the in-checkout update commands are `./update.sh --channel stable --all` and `.\update.ps1 -Channel stable -All`.

The updater preflights the source and selected personal roots before a Git update or retirement, then fast-forwards a verified checkout. Preserve local edits, unexpected hidden/untracked content and diverging commits for review. An unavailable channel is an error. Use `main` only when explicitly selected for skillset maintenance or testing.

`stable` advances only after all content, Linux, macOS and Windows CI checks pass for the current `main` commit. Publication never force-pushes. If the channel is absent, unavailable, or behind/divergent from the local checkout, stop: do not silently fall back or downgrade.

Updating the installed skillset does not scan or modify product repositories. When a project is next resumed for SDD work, the current workflow upgrades older records and reverifies existing work before continuing. It preserves product files, original records and approval boundaries; migration does not authorize new implementation or deployment. Follow the [completion-preservation procedure](../skills/to-sdd-pipeline/references/completion-preservation.md) in that project's context. This is separate from downloading a tested skillset release, and needs no version-choice question.

For a read-only report with named agent roots, run `python3 -B scripts/installation_status.py --root CLONE --codex-dir CODEX_ROOT --claude-dir CLAUDE_ROOT`, substituting discovered absolute paths and the detected Python executable. Add confirmed legacy/project roots via repeated `--cleanup-root`. It checks exact link/junction targets and recursively linked resources, not merely 13 existing SKILL.md files. Its `scope: local_installation` and `release_provenance: not_checked` remain explicit even when links and storage are `current`. Remote revision, clean Git state and Python support are separate checks; never interpret this helper alone as “up to date.”

### Recover a misplaced installation

1. Stop installation and scheduled updates. Record the product and checkout paths, each actual registration root and link target, any source receipts, Git top level and origin, and the installer transcript. Include hidden, ignored, untracked and staged files and any changes to ignore rules. On Windows record junction targets. A directory name or a clean Git status alone cannot establish ownership.
2. Before repair, make a private backup outside the affected locations. Preserve product files, hidden entries, links as links, local work and Git metadata, including any external worktree or common Git directory. Restore it to a separate folder and compare the inventory, contents and link targets.
3. Review an exact list of proven accidental additions with the owner. Only after approval, quarantine those specific entries intact at unused paths outside all projects. Record original and quarantine paths. Keep ambiguous or overwritten files for review against a trusted pre-install copy. An existing installation is never a reason to empty a folder or run recursive project cleanup.
4. Recheck the product inventory including hidden and untracked files, known product history, personal registrations and ordinary product checks. Then make a **separate** guarded installation at the chosen standalone path. Keep the verified backup and quarantine until the owner accepts recovery. See also [old repository histories](../HISTORY-REWRITE.md).

### Explicitly selected prerelease

Published `stable` remains the default. A user may explicitly select an unpublished
candidate for scoped testing or use; a request to install or resume SDD without
that selection does not opt in. Preserve an existing candidate selection within
its authorized scope instead of repeating a version-choice question. Installing a
candidate does not publish it or authorize product implementation or migration.

Before calling that candidate tested, record its repository origin, full commit
SHA, the user's selection and scope, required CI results/links for that exact SHA,
and the installed-target report in the task's evidence outside reusable skills.
Verify the source checkout is clean and at that SHA, Python is supported, and all
required platform/content jobs succeeded; do not carry an earlier commit's green
CI forward. Report the observed published `stable` revision separately. Unknown
or failed CI means an unverified development candidate, not a tested release.

On resume, recheck candidate identity, clean source and installed targets against
that record. Changed bytes or an uncovered revision require fresh validation;
authoring through installed links is unverified until the final commit passes.
The updater still refuses unpublished/diverging commits and never downgrades to
`stable`. Do not run it as a repair for an intentionally selected candidate.
After candidate verification, use normal project gates and existing authority.
Returning to the release channel follows the supported updater only when it can
fast-forward, or a separately authorized installation from a durable stable clone.

### Retired skills

Every install, repair, and update permanently deletes `communications-audit` and
`issue-happypro-certificate` from the managed skill folders.

- Delete entire copied directories, including local edits and extra files.
- Delete links and broken links regardless of their source or ownership receipt.
- Do not create backups, archives, relocated copies, or Trash entries.
- Do not exempt a copy because its content differs from the original.
- Verify both names are absent; a failed deletion fails the command.

The exact deletion list is [retired-skills.txt](../retired-skills.txt). Other skill
names are not retired, and all 13 SDD skill names and behavior remain unchanged.

During a normal install, repair or update, retirement is confined to the verified checkout and selected personal registration roots. To request additional legacy cleanup separately, inventory the affected paths and confirm the exact directories and intended permanent deletions. Run `./install.sh --all --retire-only --cleanup-dir "/absolute/legacy/skills"` or `.\install.ps1 -All -RetireOnly -CleanupDir 'C:\absolute\legacy\skills'` from a verified checkout. Repeat `--cleanup-dir` or pass a PowerShell array for multiple confirmed roots. Linked parents and former backup directories are checked before retirement. Inspect all errors and remaining paths.

The separate operation can purge matching former retirement backups identified by an `original-path.txt` record. Its roots include the former `$HOME/.sdd-pipeline/retired-skills/` and explicit `SDD_SKILL_BACKUP_DIR`. Use the [recovery procedure](#recover-a-misplaced-installation) for an accidental installation inside a product.

This is irreversible filesystem deletion, not Git-history rewriting. A GitHub
push cannot delete files on a machine that has not run the update.

### Automatic updates

This repository installs no scheduler, Git hook, background agent, or automatic
network check. Pushing to GitHub does not update other machines by itself.

Automatic updates are possible after each user opts in once to a local scheduled
task that runs the updater. A daily or between-session check is preferable to
changing skills during a running task. Use the tested `stable` channel and preserve an opt-out. Repository CI publication is not an automatic download or a scheduler on user machines.

After files arrive locally, Codex detects local skill changes and follows skill
links; restart it if the update is not visible. That local reloading is different
from downloading GitHub changes. See [official skill documentation](https://developers.openai.com/codex/skills/).

## Evidence setup and reconfiguration

A normal install, repair or update sets up skill links. Configure a product’s evidence storage separately after the user selects that project and authorizes setup. The installer’s working directory supplies no evidence project. Read-only storage status may report `setup_required` even when every skill link is current.

The terminal wizard offers managed local, chosen folder/disk/mount, or Google Drive, plus limits, retention and adoption. In an agent's storage-choice dialog, use the question and option descriptions in the [pipeline entry contract](../skills/to-sdd-pipeline/references/evidence-storage-contract.md#pipeline-entry), including the low-storage note and Drive connection prerequisite before the user answers. Noninteractive execution reports `setup_required` without choosing a provider or uploading data. Saved choices are reused.

Use the complete [setup guide](evidence-storage.md) for authentication and policy. In this durable clone:

```bash
python3 scripts/evidence_setup.py wizard --project /path/to/product
python3 scripts/evidence_setup.py status --project /path/to/product
python3 scripts/evidence_setup.py wizard --project /path/to/product --reconfigure
```

Windows uses the detected supported `python`. The manager's first evidence use after a plain Git pull calls `ensure --project PATH`; status remains read-only. This does not replace the updater's separate retirement cleanup. For separately authorized product setup, the guarded platform installer also accepts `--evidence-project PATH`, `--evidence-reconfigure`, `--evidence-non-interactive`, or PowerShell `-EvidenceProject`, `-EvidenceReconfigure`, `-EvidenceNonInteractive`.

`SDD_EVIDENCE_HOME` overrides the external configuration/state root, otherwise `~/.sdd-pipeline/evidence`. Machine destinations and credential configuration remain there or in provider configuration outside Git. Portable `forge/evidence-policy.json` contains stable project/store IDs, numeric limits and retention only. Preserve it across worktrees and reuse the same configured store; a new run path or chat is not a new accounting identity.

Reconfiguration is explicit; changing destination does not silently migrate, delete or reupload old evidence. If adopting an existing collection, preserve original catalogs and use a declarative import mapping, then independently verify active referenced bytes. Adoption reuses the exact selected machine binding, including a custom evidence home. Local users do not need rclone or a cloud account. Connected Drive is the default Drive transport: the active agent services the bundled adapter with its existing plugin/connector, using a temporary `--host-session` or `SDD_EVIDENCE_HOST_SESSION`. No custom bridge program is required. [Host session workflow](drive-transport.md#connected-host-bridge). Drive setup must pass its independent upload/download probe and project generation-authority check before succeeding.

A folder on the same disk can remove generated files from Git without reducing physical disk usage. Durable storage and replaceable working/cache space remain separate, even on the same device. Storage setup does not authorize product implementation, approved-baseline changes or Git-history rewriting.
