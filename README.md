# SDD Pipeline Skills

This repository contains the 13 Codex and Claude Code skills of a design-first SDD pipeline for moving from a rough product description or trusted existing idea through a visible Product Idea Intake, explicit Jobs To Be Done and product use cases, a coherent pre-design specification, formal H1-H10 heuristic review, exactly three runnable prototype candidates, one whole-design approval, representative-user validation of applicable critical flows, and implementation planning for a production frontend and backend.

## Repository Identity

The user-facing repository name is **SDD Pipeline Skills**.

- GitHub repository: `Ingwarski/sdd-pipeline-skills`
- Local clone directory: `SDD Pipeline Skills`
- Stable skill invocation names: `to-product-idea`, `to-sdd-prd`, `to-sdd-pipeline`, and the other existing `to-*` names
- Stable machine contract: `skills-manifest.json`, `skill_set: sdd-pipeline`, output paths, installer options, and the 13-skill manifest remain unchanged

## Separate Skill Collections

This repository contains only SDD pipeline skills. The standalone
`communications-audit` and `issue-happypro-certificate` skills now live in
[Custom Agent Skills](https://github.com/Ingwarski/custom-agent-skills), a separate
private repository. Their names and behavior are unchanged; their earlier history
remains in this repository.

Each collection has its own `skills-manifest.json` and installation receipt:

- SDD Pipeline Skills: 13 skills; `.codex-sdd-skills-source`.
- Custom Agent Skills: 2 skills; `.custom-agent-skills-source`.

A receipt records the source clone; SDD repairs only its recorded active links.
The source repositories remain separate, with no submodule or
runtime dependency. SDD's permanent retirement rule below is an explicit exception
for two installed names; it does not edit the private source repository.

Existing student SDD installations keep the same GitHub address, installer
commands, and skill names. The SDD updater permanently deletes the two accidental
business-skill names from the selected installation roots, even if a copy was
edited or a link points to another collection. It does not install the private
business collection for students. See [Updating and cleanup](#updating-and-cleanup).

## Version Notes

- [Version 2.0 — Design Quality Update](VERSION-2.0.md)
- [Student Prompt — Updating the Skills](STUDENT-SKILL-UPDATE-PROMPT.md)

The rename changes the repository label and transport location only. Agents must continue calling the existing skill names; no compatibility alias or duplicate skill is needed.

The skills are designed for **SDD - Specification Driven Development**. They are not a TDD workflow and they are not generic prompt templates. Every domain artifact has exactly one owner, and every owner invocation is confined to its declared output boundary. Most owners create one artifact; `to-project-context` is the explicit cohesive two-file bundle owner. `to-sdd-pipeline` owns only the machine-readable orchestration manifest and invokes or re-invokes artifact owners autonomously.

## Skill Chain

Use `to-product-idea` as the visible Phase 0 owner when the product idea is absent, incomplete, imported for validation, or materially changed. After its handoff, `to-sdd-pipeline` is the autonomous downstream entrypoint. Together they dispatch this acyclic graph:

```text
rough-description-or-existing-or-imported-idea -> to-product-idea -> product-idea handoff
-> to-sdd-prd
-> to-project-context (project-context.md + canonical-terms.md)
-> to-guardrails
-> to-user-journey
-> to-screen-map
-> to-wireframes
-> to-design-brief
-> to-architecture
-> to-dod-evals
-> to-qa-checklist (proposed visual checks)
-> design-source-access-preflight (Claude Design only)
-> three prototype candidates
-> one whole-design approval
-> design-brief and QA reconciliation
-> to-development-plan
-> awaiting-implementation-prompt
```

The product-intent to behavior trace is explicit and remains inside the existing graph: `JOB-*` is canonical in `to-product-idea` / `docs/product-idea.md`, while `UC-*` is canonical in `to-sdd-prd` / `docs/prd.md`. `to-user-journey`, `to-screen-map`, `to-wireframes`, `to-design-brief`, `to-architecture`, `to-qa-checklist`, `to-dod-evals`, and `to-development-plan` reference those IDs without copying or redefining their content. No separate JTBD or use-case artifact is created. The formal heuristic vocabulary is shared from [heuristic-usability-review.md](skills/to-sdd-pipeline/references/heuristic-usability-review.md).

When `claude_design` is selected, the pipeline inserts `design-source-access-preflight` between the coherent SDD baseline and prototype generation. It inventories every design material and link named by the validated design brief, records a Codex access receipt, and requires Claude Design to return a source-read receipt for every required item. Missing access pauses the handoff at `awaiting-design-source-access`; Claude Design must not generate candidates from an incomplete or guessed source set.

`to-product-idea` solely owns `docs/product-idea.md` and uses a foreground, resumable, one-question-at-a-time intake. `Create product idea and start SDD` atomically creates or versions the file only when needed, preserves an unchanged existing file byte-for-byte, and records its handoff receipt; it is an execution command, not an approval. `to-sdd-prd` is the first SDD domain-artifact owner dispatched by `to-sdd-pipeline` after that handoff. Its namespaced identity deliberately avoids collisions with unrelated `to-prd` skills. `to-project-context` runs immediately after the PRD and both bundle members must validate before later owners run. `docs/wireframes.md` never depends on the later design brief, and the development plan is deliberately post-approval because it consumes the Approved Visual Baseline.

## Included Skills

| Skill | Output | Purpose |
|---|---|---|
| `to-product-idea` | `docs/product-idea.md` | Runs the visible Product Idea Intake, asks only material non-inferable questions one at a time, captures stable `JOB-*` Jobs To Be Done, and atomically creates or versions the operator-confirmed upstream product mandate. |
| `to-sdd-pipeline` | `forge/sdd-manifest.json` | Dispatches artifact owners, tracks dependencies and hashes, runs prototype comparison, pauses after the validated development plan at `awaiting-implementation-prompt`, and propagates invalidation without editing domain artifacts directly. |
| `to-sdd-prd` | `docs/prd.md` | Converts the product idea and current project evidence into the first file-based domain artifact, defines stable `UC-*` product use cases and their alternate/error paths, and has no issue-tracker side effects. The namespaced name can coexist with third-party `to-prd` skills. |
| `to-project-context` | `docs/project-context.md` and `docs/canonical-terms.md` | Creates the atomic context/vocabulary bundle after PRD validation; the two outputs are validated and hashed separately under one owner invocation. |
| `to-user-journey` | `docs/user-journey.md` | Maps the real user, goal, context, journey stages, friction, decisions, failure path, and success state. |
| `to-screen-map` | `docs/screen-map.md` | Defines screens, surfaces, routes, navigation, transitions, entry/exit points, and the canonical state list per screen. |
| `to-wireframes` | `docs/wireframes.md` | Converts the screen map into low-fidelity screen structures, hierarchy, CTAs, forms, content zones, and state variants. |
| `to-design-brief` | `docs/design-brief.md` | Defines the UX/UI direction, traces jobs/use cases through the experience, owns design-time H1-H10 heuristic coverage, and owns the single canonical Approved Visual Baseline plus representative-user validation plan for critical flows. |
| `to-architecture` | `docs/architecture.md` | Defines system architecture, modules, boundaries, data/state model, integrations, runtime model, architecture decisions, and risks. |
| `to-dod-evals` | `docs/dod-evals.md` | Defines Definition of Done, reusable gates including `heuristic_usability_review` and `representative_user_task_validation`, verification profile, evidence requirements, state/lane gates, and PR/merge completion rules. |
| `to-guardrails` | `docs/guardrails.md` | Defines source-of-truth order, AI autonomy boundaries, scope limits, conflict handling, stop conditions, and verification policy. |
| `to-qa-checklist` | `docs/qa-checklist.md` | Creates a source-backed QA checklist with H1-H10 heuristic, usability-validation, UX/UI, responsive, accessibility, visual regression, evidence, and release-readiness checks. |
| `to-development-plan` | `docs/development-plan.md` | Converts the current validated SDD plus Approved Visual Baseline into frontend/backend units, interface seams, dependency order, acceptance checks, and verification steps. |

## Core Rules

All skills follow the same operating contract:

- AI is not the source of truth. Source files and explicit user answers are.
- The orchestrator resolves one `working_language` before intake and passes it to every owner and design adapter. Questions, recommendations, playbacks, displayed states, reports, and natural-language SDD artifact prose use that language; product UI/content locales remain a separate source-backed setting.
- With Ukrainian `working_language`, all ordinary headings and prose must be natural Ukrainian. English remains only in immutable filenames/paths, code/commands, machine values, API/identifier names, proper names or quotations, and approved IT terms such as `SDD Pipeline`; approved English IT terms and their Ukrainian meanings live in `canonical-terms.md`.
- Missing product intent is surfaced through the foreground Product Idea Intake, never silently generated in background logs. Material questions persist as `Input needed`; silence, timeout, and recommendations are not consent.
- Intake answers and `Create product idea and start SDD` are input/start actions, not approval receipts. The only normal approval is still approval of the complete integrated prototype.
- Discoverable information must be read from sources or code instead of asked. A focused grill-me gap-check runs only for genuinely non-inferable information that materially changes product scope, the whole-design baseline, or a high-risk boundary.
- When Claude Design is the executor, every design source material and link is catalogued with a required/optional status, location, access mode, and hash/capture receipt before candidate generation. A URL alone is not evidence that the design executor saw the material.
- Every material gap-check walks one relevant decision branch, asks one question, gives a recommended answer and rationale, cites the source basis or says no source confirms it, names affected downstream artifacts or boundaries, and plays back the confirmed decision plus consequences before continuing.
- Non-material gaps use the smallest reversible source-grounded default, are recorded, and do not become approval gates.
- An owner invocation creates only its declared final output path or cohesive output set. No draft output files.
- Unverified assumptions are never written as facts. `project-context.md` may retain them only in its explicitly labeled `Assumptions` section; unresolved decisions belong in `Open Questions`.
- Anything not source-backed or user-confirmed is either a clearly labeled contextual assumption or an `Open Question`, never silent product truth.
- Every artifact has exactly one owner. `to-project-context` may update only its declared two-file bundle; all other current domain owners update one artifact.
- The orchestrator never edits a domain artifact directly; it dispatches the owning skill and owns only `forge/sdd-manifest.json`.
- Artifacts reference prior artifacts instead of duplicating them.
- Artifact boundaries must be preserved.
- `JOB-*` is the canonical product-intent unit: situation, desired progress, outcome, current alternative, and design-relevant conditions. Jobs are not feature lists, user-story duplicates, or a second journey document.
- `UC-*` is the canonical product-behavior unit: actor, trigger, goal, preconditions, main success path, alternate/error recovery, postconditions, authority/data boundaries, and linked requirements. Use cases are not screen layouts or implementation tasks.
- Preserve the trace `JOB-* -> UC-* -> journey stage -> screen/state -> wireframe -> design brief -> architecture/QA -> implementation unit`. Downstream artifacts reference IDs and add only their own concern.
- `to-product-idea` uses a grill-me-style design-readiness branch to resolve job/progress, situation/trigger, outcome/alternative, operating conditions, trust/risk, content/evidence, and observable success before the product idea is handed downstream. It asks one material question at a time and records assumptions or open questions explicitly.
- Representative-user validation, heuristic/usability review (including Nielsen Norman-style heuristic checks), visual-QA/browser evidence, and functional/runtime evidence are separate evidence classes. None may be silently substituted for another; no user session, participant, result, or success may be fabricated.
- Applicable critical or consequential user-visible flows require a `representative_user_task_validation` plan/check/evidence path. Validation is a quality gate and evidence of usability, not a second design approval; the only normal design approval remains the complete integrated prototype baseline.
- For regulated, accessibility-critical, safety-sensitive, or otherwise high-risk flows, representative-user validation defaults to pre-approval when feasible; if deferred, the design brief must show the assumption/open risk and must not claim user validation.
- The formal H1-H10 heuristic layer is defined once in `skills/to-sdd-pipeline/references/heuristic-usability-review.md`; `to-design-brief` plans it, `to-qa-checklist` checks it, `to-dod-evals` gates it with `heuristic_usability_review`, and `to-development-plan` maps it to implementation units.
- H1-H10 checks must cover the applicable primary journey, representative screens/states/routes/viewports, desktop/mobile when supported, error/recovery, and accessibility-critical actions. H7 explicitly considers expert efficiency without harming novice defaults; H10 explicitly considers contextual, searchable, actionable, and task-oriented help.
- Error/recovery states use the shared format: `cause -> what was preserved -> next action -> retry/undo option -> condition for successful completion`.
- `heuristic_usability_review`, `representative_user_task_validation`, `approved_visual_baseline_fidelity`, and functional/runtime verification are separate evidence/gate classes. None substitutes for another, and heuristic findings do not automatically create approval gates.
- The only normal design approval is approval of the complete integrated prototype. Risk-specific authorization is separate and just in time.
- After `docs/development-plan.md` validates, the pipeline enters `awaiting-implementation-prompt`. Production implementation requires a later, separate prompt that explicitly asks to start Phase 3; a generic continuation or automatic resume cannot release the gate.

## Artifact Boundaries

The documents are intentionally separated:

- `product-idea.md` owns the current operator-confirmed product mandate. `to-product-idea` is its sole owner; runtime draft/session data and `ProductIdeaHandoffReceipt` remain operational provenance under `forge/intake/`.
- `product-idea.md` also owns the canonical `JOB-*` Jobs To Be Done and the design-readiness discovery decisions that define situation, progress, outcome, alternatives, conditions, trust/risk, content/evidence, and success signals. It does not own product use-case system paths, screens, layouts, or visual direction.
- `project-context.md` owns confirmed product context, working language, distinct product content locales, users, platforms, boundaries, constraints, assumptions, risks, and open questions derived after PRD work.
- `canonical-terms.md` owns normalized downstream vocabulary and aliases, including deliberately preserved English IT terms with their Ukrainian meanings and usage boundaries, without redefining PRD behavior or established technical identifiers.
- `user-journey.md` owns user behavior and journey logic.
- `screen-map.md` owns which screens and states exist.
- `wireframes.md` owns screen structure and state structure.
- `design-brief.md` owns visual and experience direction, the trace through applicable `JOB-*`/`UC-*` references, the representative-user validation plan for critical flows, and the single canonical Approved Visual Baseline section. The approved prototype owns concrete visual composition, interaction detail, and frontend presentation; PRD/journey artifacts own product behavior.
- `design-brief.md` also owns design-time H1-H10 coverage/status and heuristic expectations, using the shared reference without copying its definitions. It does not own executed QA findings or the reusable DoD gate.
- `architecture.md` owns system architecture, module boundaries, data/state model, integrations, runtime model, and architecture decisions.
- `architecture.md` may map applicable `UC-*` product behaviors to technical modules, interfaces, data, and runtime boundaries, but it does not redefine the product use cases.
- `dod-evals.md` owns Definition of Done, reusable gates including `representative_user_task_validation`, eval result format, completion evidence requirements, and completion rules. It does not own the per-flow task plan or per-check evidence.
- `guardrails.md` owns AI behavior, source-of-truth policy, and behavioral evidence policy.
- `qa-checklist.md` owns concrete H1-H10 heuristic checks and per-check evidence artifacts, plus representative-user task checks for applicable critical flows. It does not redefine the shared heuristic definitions, design-brief plan, or DoD gates.
- `development-plan.md` owns implementation units and build order, including references to visual fidelity, heuristic usability, and representative-user validation evidence when applicable.
- `forge/sdd-manifest.json` owns orchestration state, the working-language record, owner invocation/output-set mapping, source versions and hashes, consumed source fragments, explicit dependencies and dependency states, content hashes, validation, invalidation, and resume state; it does not own domain truth. Machine enum values remain stable while operator-facing labels are localized. Internal `validated` projects to Mission Control `Done`, while `ready` means machine-ready rather than approved.

If one artifact needs information from another, it should cite or reference that artifact rather than restating it.

## Installation

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
`git pull --ff-only`, then run the updater. The [student prompt](STUDENT-SKILL-UPDATE-PROMPT.md)
guides an agent through that first update.

The updater verifies the GitHub origin and `main` branch, refuses local edits or
unpublished/diverging commits, fast-forwards, and executes the newly downloaded
installer with repair enabled. It does not reset Git history or discard unrelated
work; permanent deletion of the two retired skill folders is intentional. Use
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

The exact deletion list is [retired-skills.txt](retired-skills.txt). Other skill
names are not retired, and all 13 SDD skill names and behavior remain unchanged.

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

## How To Use

Start with either:

```text
a rough product description
or a trusted existing docs/product-idea.md
```

A pre-existing `docs/product-idea.md` is optional, not an onboarding prerequisite. With no file, the visible intake creates it from the rough description and explicit answers. With an existing file, the intake validates it first, skips redundant questions when it is coherent, and asks only about material gaps or corrections before handoff.

Useful optional initial repository evidence:

```text
README.md
```

The full pipeline always creates the compact `docs/project-context.md` plus `docs/canonical-terms.md` bundle immediately after the PRD so later owners resolve context and vocabulary once. They consume only relevant confirmed sections or terms; descriptive or unrelated content is not copied merely to satisfy ceremony. Beyond this standard bundle, the orchestrator creates the smallest coherent set required by the product.

When the idea is absent, incomplete, or needs material reconciliation, start the visible intake; do not create a placeholder file first:

```text
Use to-product-idea for this project.
```

The intake asks one material question at a time with a recommendation and rationale, keeps a live draft and coverage visible, persists resume state, and writes the authoritative file only after `Create product idea and start SDD`. In DAS Forge, that command launches the downstream pipeline automatically. If an existing file has no current matching handoff, direct orchestration routes it through visible validation, skips redundant questions when coherent, creates the matching handoff, and continues automatically. With an already validated current idea and matching handoff/hash, ask Codex to run the orchestration skill directly:

```text
Use to-sdd-pipeline for this project.
```

The orchestrator dispatches every ready artifact owner through `docs/development-plan.md` without asking the user to continue. After that final SDD artifact validates, it pauses at `awaiting-implementation-prompt`; only a later explicit implementation prompt can release Phase 3. A later material product-intent gap returns to the same Intake surface, versions the idea through its owner, and invalidates only transitive dependents. The pipeline otherwise pauses for the one whole-design approval or a just-in-time high-risk authorization. `to-guardrails` runs after the PRD and is regenerated only when a named upstream change invalidates one of its rules; the mere appearance of later UX files is not a rerun trigger.

Individual owner skills remain callable for targeted artifact work. In that mode the caller is responsible for their documented prerequisites and invalidation. Artifact readiness means validated/current, not separately human-approved.

## What Happens When Information Is Missing

The skills should not invent missing product decisions.

When a genuinely material, non-inferable product-intent gap exists, `to-product-idea` or the orchestrator returns one structured question to the visible Product Idea Intake surface. The affected Product Creation Run enters `Input needed` and resumes automatically after the answer. The question style follows a grill-me pattern:

- ask one question at a time when the answer affects the next question;
- include a recommended answer;
- inspect source files or the codebase instead of asking when the answer can be found there;
- never use timeout, silence, or an unconfirmed recommendation as a material answer;
- continue only after the material missing decision is resolved.

If the gap is not blocking, the skill should use the smallest reversible source-grounded choice, write the artifact, trace the choice, and list any residual uncertainty in `Open Questions`.

## Jobs To Be Done, Use Cases, And Design Validation

The design-first chain now establishes three complementary layers before implementation:

1. `JOB-*` answers why the user acts, in which situation, what progress they want, what outcome signals success, what they use today, and which operating/trust conditions affect design.
2. `UC-*` answers how the product behaves for that job: actors, trigger, preconditions, main path, alternate/error recovery, postconditions, data/authority boundaries, and requirements covered.
3. Journey, screens, wireframes, design brief, QA, DoD, and development plan translate and verify those upstream decisions without becoming competing sources of truth.

The formal heuristic layer uses H1-H10: visibility of system status; match with the real world; user control and freedom; consistency and standards; error prevention; recognition rather than recall; flexibility and efficiency; aesthetic and minimalist design; error diagnosis/recovery; and help/documentation. The complete contract, required evidence, applicability, severity, release effect, screens/states/routes/viewports, and H7/H10 rules live in [heuristic-usability-review.md](skills/to-sdd-pipeline/references/heuristic-usability-review.md).

The design brief plans heuristic coverage and representative-user task validation for critical flows. QA turns both plans into concrete checks and records evidence; DoD evaluates `heuristic_usability_review` and `representative_user_task_validation`; the development plan maps both gates to implementation units. For high-risk flows, the plan records whether user validation is pre-approval, post-implementation, or both. A heuristic review can identify likely usability issues, including issues described by Nielsen Norman heuristics, but it is not evidence that representative users completed the task. Likewise, a visual baseline or browser receipt proves visual/runtime evidence only within its stated scope.

## Design Quality

The UX/UI part of the chain is built around proven product-design mechanisms:

- real user journeys instead of feature lists;
- surface closure between journeys and screens;
- concrete wireframe notation rather than vague layout prose;
- a Design Spine and Experience Spine in `design-brief.md`;
- visual-system inheritance when a project already has tokens, components, or a design system;
- accessibility and responsive behavior as default requirements;
- validation before the design brief is written;
- a distinctiveness check so the design does not collapse into generic AI UI;
- exactly three whole-product interactive candidates on three separate external-browser pages;
- recommendation without automatic selection;
- one engineer approval of the selected complete integrated design baseline;
- a frozen visual-target reference and content hash for reproducible implementation and QA.
- explicit `JOB-*`/`UC-*` traceability from product intent to implementation;
- design-readiness discovery before PRD generation, covering user situation, progress, conditions, trust, content, and success;
- a representative-user task validation plan and concrete evidence path for applicable critical flows, separate from heuristic review and visual QA.

For operational products, a deliberate restraint principle can be the right design decision. The skills should not force decorative design when the product needs density, clarity, and repeat-use efficiency.

## QA And Implementation

`to-qa-checklist` produces checks with severity:

- `P0`: blocks core use or is a severe accessibility failure.
- `P1`: major mismatch or usability regression.
- `P2`: moderate drift or fixable gap.
- `P3`: polish.

Severity and release effect are separate:

- P0 and P1 are blocking.
- P2 blocks only when it violates a required source-backed gate, critical journey, applicable accessibility/security/privacy/legal/payment/data-integrity constraint, supported viewport/device, or approved hierarchy/interaction meaning, or when related P2s combine into P1 impact.
- Other P2 and all P3 findings are advisory follow-up and do not create approvals.
- Release readiness remains binary: `passed` when applicable gates and blocking findings are closed; otherwise `blocked`.

`to-development-plan` is SDD-first. Tests and verification support the current validated spec, but they do not become the source of product truth. It applies project context only where a confirmed fact changes implementation and uses canonical terms only where naming is relevant; it does not duplicate personas or context prose. User-visible units map the Approved Baseline ID; cross-layer units name interfaces produced/consumed and integration evidence; prototype code is only an optional traced frontend seed, never proof of production backend, auth, persistence, or integrations.

`to-dod-evals` separates acceptance criteria from Definition of Done. Acceptance criteria confirm that a specific item was built correctly; DoD/eval gates define the standing completion bar and evidence required before anything can be called done. A mockup, screenshot, prototype, or visually convincing static surface is design/visual evidence only; it is not completed functionality unless connected to source-backed behavior, real state/data/actions, runner evidence, and required DoD gates.

For usability quality, `to-qa-checklist` records the concrete task, representative user group, device/viewport, success criterion, evidence, result, severity, and release effect. `to-dod-evals` evaluates those checks through `representative_user_task_validation`: an applicable critical flow cannot pass merely because a heuristic review, screenshot, browser receipt, or prototype interaction looks correct. If validation is not available, the evidence limit and risk must remain explicit; it cannot be silently marked as passed.

For heuristic quality, `to-qa-checklist` adds H1-H10 to every UX/UI/heuristic check together with task, user group, route, state, viewport, expected behavior, evidence, finding, severity, release effect, and recommendation. `to-dod-evals` evaluates those checks through the separate `heuristic_usability_review` gate; it does not create a human approval gate.

## Authoring References

The skills are custom SDD skills, but they intentionally reuse proven mechanisms from existing skills and references.

For `to-architecture`, the main authoring references were:

- `tad-generator`: `https://github.com/luongnv89/skills/blob/main/skills/tad-generator/SKILL.md`
- `documentation-and-adrs`: `https://github.com/addyosmani/agent-skills/blob/main/skills/documentation-and-adrs/SKILL.md`
- `breakdown-epic-arch`: `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-epic-arch/SKILL.md`
- `eatmycode`: `https://github.com/xwings/eatmycode`

For `to-dod-evals`, the main authoring references were:

- `definition-of-done`: `https://raw.githubusercontent.com/addyosmani/agent-skills/main/references/definition-of-done.md`
- `quality-run-quality-gates`: `https://github.com/dawiddutoit/custom-claude/blob/main/skills/quality-run-quality-gates/SKILL.md`
- the installed `verification-before-completion` skill available during authoring
- `breakdown-plan`: `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-plan/SKILL.md`
- Hermes eval/lane-gate proposal: `https://github.com/NousResearch/hermes-agent/issues/44000`

These references are authoring provenance, not product source files. During a project run, each skill must still use only its declared input files and explicit user answers as product truth.

## Repository Contents

```text
skills/
  to-product-idea/
    SKILL.md
  to-sdd-pipeline/
    SKILL.md
    references/
      claude-design-handoff.md
      heuristic-usability-review.md
  to-sdd-prd/
    SKILL.md
  to-project-context/
    SKILL.md
  to-user-journey/
    SKILL.md
  to-screen-map/
    SKILL.md
  to-wireframes/
    SKILL.md
  to-design-brief/
    SKILL.md
  to-architecture/
    SKILL.md
  to-dod-evals/
    SKILL.md
  to-guardrails/
    SKILL.md
  to-qa-checklist/
    SKILL.md
  to-development-plan/
    SKILL.md

claude-code-skill-audit-prompt.md
```

`claude-code-skill-audit-prompt.md` is the audit prompt used to review these skills against the user's requirements and relevant external skills.
