# SDD Pipeline Skills

13 skills for Codex and Claude Code that turn product intent into specifications, reviewed design and a development plan. SDD means **Specification-Driven Development**: agree what to build first; tests verify it rather than define it.

Start from a rough description or a trusted existing idea. The pipeline asks only material unanswered questions, compares three interactive designs, obtains one whole-design approval, and stops before production implementation.

## Quick start

1. Install the complete skill set below.
2. Open your product project and ask: `Use to-sdd-pipeline for this project.`
3. Answer focused product questions and approve one complete design.
4. After the development plan is ready, send a **separate explicit prompt** to start production implementation.

An existing `docs/product-idea.md` is optional. Coherent existing intent is validated without a redundant interview. `to-product-idea` can also be called directly for discovery.

## Installation

Requires **Python 3.9+**; the runtime tools use only its standard library.

If Python is missing, [download it from the official Python website](https://www.python.org/downloads/). Choose the latest stable Python 3 release; 3.9 is the minimum, not a pinned version.

- **Windows:** download the Python install manager from [Python.org's Windows page](https://www.python.org/downloads/windows/), open the downloaded file and choose **Install**. In a new PowerShell window, run `python --version`; the manager installs Python on first use if none is installed. If using the older `.exe` installer, enable **Add Python to PATH** when offered.
- **macOS:** download the [macOS installer](https://www.python.org/downloads/macos/), open the `.pkg` file and follow the setup wizard, including its final **Install Certificates.command** step.
- **Linux:** check `python3 --version` first. If Python is missing or too old, follow the [official Linux instructions](https://docs.python.org/3/using/unix.html#on-linux); Python.org does not provide a Windows-style Linux installer.

Reopen your terminal and agent app after installation. Confirm **3.9 or newer** with `python3 --version` on macOS/Linux or `python --version` (alternatively `py -3 --version`) on Windows, then continue below. Skip installation if a suitable Python version is already available.

Clone [Ingwarski/sdd-pipeline-skills](https://github.com/Ingwarski/sdd-pipeline-skills) into a durable folder, then run:

| Platform | Install | Later updates |
|---|---|---|
| macOS / Linux | `./install.sh --all` | `./update.sh --all` |
| Windows PowerShell | `.\install.ps1 -All` | `.\update.ps1 -All` |

On macOS or Windows, the `Install Skills` and `Update Skills` launchers run the same scripts. Choose `--codex` / `--claude` or `-Codex` / `-Claude` to limit the agent.

Installers create links, not copied skill folders. Both use one strict JSON/source/reference validator before changes. Windows falls back from symbolic links to directory junctions. A repeated install is safe; active SDD conflicts are reported, not overwritten.

See [installation instructions](docs/installation.md) for the agent-assisted prompt, destination overrides, moved-clone repair, uninstall and cleanup scope. New skills are available on the agent's next turn; restart only if changes are not visible.

## Updating and cleanup

For a first update from `Codex Skills` / `Codex SDD Skills` or the old GitHub address, use the current Ukrainian [student update prompt](STUDENT-SKILL-UPDATE-PROMPT.md). Later, use the updater above. **A plain Git pull does not perform cleanup.**

The updater removes the two accidentally distributed business-skill names from scoped skill folders, checks for unrelated local Git changes, fast-forwards clean `main`, then runs the freshly downloaded installer. Cleanup can finish even when an unrelated Git/link conflict later stops the update.

The exact list is [retired-skills.txt](retired-skills.txt). Removal is permanent, includes edited copies/links and matching former updater backups, and creates no backup, archive, relocation or Trash copy. Other skills are not retirement targets. Extra project/old-clone roots require explicit `--cleanup-dir` / `-CleanupDir`; no whole-disk scan or link-target traversal. See [full scope and failure rules](docs/installation.md#retired-business-skills).

No scheduler, Git hook or background updater is installed. GitHub pushes cannot update another machine without that user's local update or explicit scheduling opt-in.

## Repository identity

The repository is **SDD Pipeline Skills**, at `Ingwarski/sdd-pipeline-skills`. The earlier address was `Ingwarski/codex-skills`. Agent invocation names, output paths, the 13-skill manifest, `skill_set: sdd-pipeline` and installation receipt `.codex-sdd-skills-source` remain stable. Use `to-sdd-prd`; unrelated third-party `to-prd` skills may coexist.

Non-SDD custom skills live separately in the private [Custom Agent Skills](https://github.com/Ingwarski/custom-agent-skills) repository, with independent installation records. SDD does not depend on or install that collection; scoped retirement affects the two installed names, not the private source repository.

## Workflow and ownership

```text
Product idea → PRD → context + vocabulary → guardrails
→ user journey → screen map → wireframes → design brief
→ architecture → completion rules → proposed QA checks
→ three prototypes → one whole-design approval
→ record baseline → recheck architecture → recheck completion rules
→ reconcile QA → development plan → wait for implementation prompt
```

| Skill | Owned output | Purpose |
|---|---|---|
| `to-product-idea` | `docs/product-idea.md` | Confirm intent, user needs and Jobs To Be Done. |
| `to-sdd-prd` | `docs/prd.md` | Define requirements, use cases and acceptance outcomes. |
| `to-project-context` | `docs/project-context.md` + `docs/canonical-terms.md` | Establish context and consistent vocabulary together. |
| `to-guardrails` | `docs/guardrails.md` | Define authority, autonomy, scope and evidence policy. |
| `to-user-journey` | `docs/user-journey.md` | Describe the user's situation, actions, friction and outcome. |
| `to-screen-map` | `docs/screen-map.md` | Own screens, navigation and the state inventory. |
| `to-wireframes` | `docs/wireframes.md` | Define structural layouts, actions and recovery. |
| `to-design-brief` | `docs/design-brief.md` | Define visual/interaction rules and the canonical approved baseline. |
| `to-architecture` | `docs/architecture.md` | Define technical boundaries, data, integrations and configuration. |
| `to-dod-evals` | `docs/dod-evals.md` | Define reusable completion gates, not execute tests. |
| `to-qa-checklist` | `docs/qa-checklist.md` | Define concrete checks and record inspected execution evidence. |
| `to-development-plan` | `docs/development-plan.md` | Map requirements/design/architecture to implementation and verification. |
| `to-sdd-pipeline` | `forge/sdd-manifest.json` | Dispatch owners and track current sources, evidence and progress. |

One artifact has one owner. The context pair shares one invocation but separate hashes/results. The orchestrator never edits domain documents; owners return metadata for it to record.

Owners remain callable individually. The caller checks required inputs, validates results and identifies affected downstream work. A manifest is not required merely to write one standalone artifact. See [shared operating rules](skills/to-sdd-pipeline/references/common-contract.md).

## Design and usability

- `JOB-*` captures **why** users act: situation, progress, outcome, alternatives and conditions.
- `UC-*` captures **how the product responds**: actor, trigger, paths, failures/recovery and completion.
- Later documents reference these IDs instead of copying their definitions.
- Wireframes define structure; design and experience “spines” define reusable appearance and behavior rules. Existing systems, accessibility, responsiveness, realistic states and product-specific choices remain required.
- The shared [Nielsen Norman H1-H10 contract](skills/to-sdd-pipeline/references/heuristic-usability-review.md) covers usability systematically, including novice/expert efficiency (H7), contextual help (H10) and recoverable errors.
- Error guidance follows: **cause → what was preserved → next action → retry/undo → observable success**.
- Visual fidelity, heuristic review, representative-user validation, accessibility and functional testing are distinct evidence classes. A good-looking prototype does not prove task success or completed functionality.
- High-risk flows plan user validation before approval where feasible; any deferral remains an explicit risk, never fabricated research.

Codex shows three local candidates in the external browser. With explicitly selected Claude Design, the pipeline first verifies access to every required source, compares three tool-native candidates, then imports and opens only the selected version. A Claude selection is not the final design approval. [Handoff details](skills/to-sdd-pipeline/references/claude-design-handoff.md).

The design brief remains the sole approved-baseline authority. Frozen candidates, earlier approvals and accepted overrides are preserved; a revision rechecks affected architecture, gates, QA and planning without adding another type of approval.

## Checks, evidence and safe continuation

A prepared checklist means **checks prepared; tests not run**. Definition status and execution status are separate. Release is not evaluated during ordinary planning; an actual release evaluation passes only with required evidence and no open blocking findings.

`to-dod-evals` defines the gates; an authorized reviewer/test harness/runner executes them; QA records results; the orchestrator tracks them. Severity and release effect are separate, using the canonical P0–P3 rules. [Verification contract](skills/to-sdd-pipeline/references/verification-contract.md).

The included read-only checker verifies stage prerequisites, owners, document/source hashes, the coupled context bundle, baseline integrity, declared evidence and implementation authorization. It distinguishes **required before a step** from **consulted later**, so QA's later reference to a development plan creates no false dependency loop.

```bash
python3 skills/to-sdd-pipeline/scripts/sdd_check.py --project /path/to/product --before development-plan
```

Agents resolve the checker from the installed skill directory, not the product folder. Older projects retain their documents and history while verified metadata is added. Missing evidence remains a blocker. [Checker schema and migration](skills/to-sdd-pipeline/references/manifest-contract.md).

The checker validates records; it cannot prove research authenticity or replace semantic review. Skills require it before advancement, but **hard enforcement in a separate DAS Forge runner requires that runner to call it and enforce its exit code**. This repository does not contain or modify that runner.

After the plan validates, `awaiting-implementation-prompt` remains mandatory. Approval, automatic resume and a generic “continue” do not authorize production work.

## Clear language and token use

Every skill and generated SDD document uses direct wording, explains unfamiliar terms briefly, records a decision once and references it elsewhere. Required details, evidence, IDs, risks and approval boundaries stay intact. Existing valid project documents are not rewritten just to shorten them.

The working language follows explicit instruction, recorded preference, then the user's latest substantive message. Product locales stay separate. With Ukrainian, ordinary prose/headings are idiomatic Ukrainian; paths, code, machine values, proper names and approved IT terms remain unchanged.

Detailed conditional guidance lives in shared references. The reproducible [maintenance checks and token benchmark](docs/maintenance.md) count referenced instructions and repeated/retry loads, not just short entrypoints. These are instruction-budget measurements, not promises about actual model billing or live end-to-end token usage.

## Further reading

- [Version 2.0 design-quality note](VERSION-2.0.md) — historical summary.
- [Student update prompt, Ukrainian](STUDENT-SKILL-UPDATE-PROMPT.md).
- [Installation and cleanup](docs/installation.md).
- [Maintaining and testing this repository](docs/maintenance.md).
- [Audit prompt](claude-code-skill-audit-prompt.md).
- [Authoring provenance](skills/to-sdd-pipeline/references/authoring-sources.md) — historical influences, not product truth.
