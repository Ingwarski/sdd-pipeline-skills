# SDD Pipeline Skills

13 skills for Codex and Claude Code that turn product intent into specifications, reviewed design and a development plan. SDD means **Specification-Driven Development**: agree what to build first; tests verify it rather than define it.

## Quick start

1. [Install the complete skill set](#installation).
2. Open your product project and ask: `Use to-sdd-pipeline for this project.`
3. Answer focused product questions and share existing design references when asked.
4. The pipeline prepares the initial SDD documents. When prompted, choose **Codex or Claude Design** for prototyping.
5. Compare the **three interactive whole-product prototypes**, request revisions if needed, then approve one complete version. See [design review and handoff](#design-and-usability) for the tool-specific steps.
6. After approval, the pipeline records the baseline, reconciles architecture, completion rules and QA, then creates `docs/development-plan.md` and pauses.
7. To start production implementation, send a **new, separate explicit prompt after that pause**.

Start with a rough description or existing `docs/product-idea.md`. Intake shows its understanding and gaps before one question; coherent intent needs no redundant interview.

This is the default **new-product UI** path. An **existing change** reuses valid documents and approved design, updating affected work only. A **headless product** skips screens, wireframes, visual design and approval; it still needs requirements, security, QA and a plan, then the separate implementation prompt. [Scope and direct-host execution](skills/to-sdd-pipeline/references/scope-and-execution.md).

During product-idea intake, share design references once: website/app links, screenshots, colors, fonts, brand guides or HTML mockups with their assets. Attach files to your prompt or put them in `docs/design-inputs/` **inside your product repository**, not this skills repository; an existing folder is also fine. “None yet” or “later” is valid. The idea records source notes; the design brief owns the full inventory and design decisions. References are not design approval.

## Installation

Requires **Python 3.12+**; the runtime tools use only its standard library.

If Python is missing, [download it from the official Python website](https://www.python.org/downloads/). Choose the latest stable Python 3 release; 3.12 is the minimum, not a pinned version.

- **Windows:** download the Python install manager from [Python.org's Windows page](https://www.python.org/downloads/windows/), open the downloaded file and choose **Install**. In a new PowerShell window, run `python --version`; the manager installs Python on first use if none is installed. If using the older `.exe` installer, enable **Add Python to PATH** when offered.
- **macOS:** download the [macOS installer](https://www.python.org/downloads/macos/), open the `.pkg` file and follow the setup wizard, including its final **Install Certificates.command** step.
- **Linux:** check `python3 --version` first. If Python is missing or too old, follow the [official Linux instructions](https://docs.python.org/3/using/unix.html#on-linux); Python.org does not provide a Windows-style Linux installer.

Reopen your terminal and agent app after installation. Confirm **3.12 or newer** with `python3 --version` on macOS/Linux or `python --version` (alternatively `py -3 --version`) on Windows, then continue below. Skip installation if a suitable Python version is already available.

The [single setup prompt](INSTALL-OR-UPDATE-PROMPT.md) first checks repository/install state. If skills and the supported runtime are current, it stops without changing Python or running installers. Otherwise it handles official Python installation/update, old-clone bootstrap, cleanup or repair. The [runtime policy](runtime-policy.json) tests maintained Python 3.12 and current stable 3.14; no student Node dependency is added. Python has no official LTS label.

For the tested classroom version, run `git clone --branch stable https://github.com/Ingwarski/sdd-pipeline-skills.git`, then `git switch -c main` inside that durable clone. If `stable` is unavailable, wait for publication; do not substitute unverified `main`. Then run:

| Platform | Install | Later updates |
|---|---|---|
| macOS / Linux | `./install.sh --all` | `./update.sh --channel stable --all` |
| Windows PowerShell | `.\install.ps1 -All` | `.\update.ps1 -Channel stable -All` |

The launchers run the same scripts. The updater's default remains `main` for backward compatibility; select `stable` as above for tested classroom updates. Choose `--codex` / `--claude` or `-Codex` / `-Claude` to limit the agent.

Installers create links, not copied skill folders. Both use one strict JSON/source/reference validator before changes. Windows falls back from symbolic links to directory junctions. A repeated install is safe; active SDD conflicts are reported, not overwritten.

Nontechnical users can paste the single [install-or-update prompt](INSTALL-OR-UPDATE-PROMPT.md) into a local agent. See [installation instructions](docs/installation.md) for destination overrides, moved-clone repair, uninstall and cleanup scope. New skills are available on the agent's next turn; restart only if changes are not visible.

## Updating and cleanup

The same [install-or-update prompt](INSTALL-OR-UPDATE-PROMPT.md) handles first installation, migration from `Codex Skills` / `Codex SDD Skills`, and regular updates. **A plain Git pull does not perform cleanup.**

The updater removes the two accidentally distributed names in [retired-skills.txt](retired-skills.txt) from scoped skill folders, checks for unrelated local Git changes, fast-forwards clean `main`, then runs the freshly downloaded installer. Cleanup can finish even when an unrelated Git/link conflict later stops the update.

Removal is permanent, includes edited copies/links and matching former updater backups, and creates no backup, archive, relocation or Trash copy. Other skills are not retirement targets. Extra project/old-clone roots require explicit `--cleanup-dir` / `-CleanupDir`; no whole-disk scan or link-target traversal. See [full scope and failure rules](docs/installation.md#retired-business-skills).

No scheduler, Git hook or background updater is installed. GitHub pushes cannot update another machine without that user's local update or explicit scheduling opt-in.

CI advances `stable` only after content checks and the Linux/macOS/Windows matrix pass for current `main`. A newer untested `main` is not a stable update. Local commits ahead of that channel are never downgraded. The read-only `scripts/installation_status.py` checks exact link targets and nested resources in explicitly selected roots.

## Repository identity

The earlier GitHub address was `Ingwarski/codex-skills`. Agent invocation names, output paths, the 13-skill manifest, `skill_set: sdd-pipeline` and installation receipt `.codex-sdd-skills-source` remain stable. Use `to-sdd-prd`; unrelated third-party `to-prd` skills may coexist.

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

Each artifact has one owner. Context outputs share an invocation, not hashes/results. Owners declare consumed files/sections, including shared QA rules, or explain unused context. The orchestrator records this metadata without editing domain documents. Older records need owner review, not guessed source history.

Owners remain callable individually. The caller checks required inputs, validates results and identifies affected downstream work. A manifest is not required merely to write one standalone artifact. See [shared operating rules](skills/to-sdd-pipeline/references/common-contract.md).

## Design and usability

- `JOB-*` captures **why** users act: situation, progress, outcome, alternatives and conditions.
- `UC-*` captures **how the product responds**: actor, trigger, paths, failures/recovery and completion.
- Wireframes define structure; design and experience “spines” define reusable appearance and behavior rules. Existing systems, accessibility, responsiveness, realistic states and product-specific choices remain required.
- The shared [Nielsen Norman H1-H10 contract](skills/to-sdd-pipeline/references/heuristic-usability-review.md) covers usability systematically, including novice/expert efficiency (H7), contextual help (H10) and recoverable errors.
- Error guidance follows: **cause → what was preserved → next action → retry/undo → observable success**.
- High-risk flows plan user validation before approval where feasible; any deferral remains an explicit risk, never fabricated research.

Three local candidates use the external default browser unless the user explicitly chooses another visible review surface, including the in-app browser. Claude Design compares three tool-native candidates after source preflight; only the selected export is imported. Export selection is not approval: review the exact imported version, then give a whole-design decision in the active host. [Handoff details](skills/to-sdd-pipeline/references/claude-design-handoff.md).

Frozen candidates, earlier approvals and accepted overrides are preserved; a revision rechecks affected architecture, gates, QA and planning without adding another type of approval.

The frozen design includes its shared CSS, fonts, images and scripts, not just its own folder. Mutable remote assets must be packaged; browser inspection still checks dynamic dependencies. [Freeze contract](skills/to-sdd-pipeline/references/freeze-contract.md).

The [accessibility policy](skills/to-sdd-pipeline/references/accessibility-policy.md) separates WCAG requirements from house style: 320 CSS-pixel reflow, zoom, keyboard/focus and relevant assistive technology; applicable motion behavior; 24px AA target rules versus the preferred 44px touch target. User research asks neutral questions about actual behavior; operator decisions can still include recommendations.

## Product security requirements

Security authoring is part of `to-sdd-prd`, not a fourteenth skill or a separate approval stage. The [reviewed OWASP procedure](skills/to-sdd-prd/references/security-authoring.md) assesses the intended product's exposure, applies relevant ASVS controls and writes testable security requirements into the existing PRD. ASVS means **Application Security Verification Standard**; it supplies secure-development requirements, not a scanner or certification.

The complete ASVS 5.0.0 catalog is bundled with an offline, standard-library Python reader and [source pins/licensing](skills/to-sdd-prd/references/owasp/NOTICE.md). No paid security subscription, API key or network request is required. Windows, macOS and Linux use the existing Python prerequisite. Only the PRD owner reads relevant catalog sections; other owners reference the resulting requirement IDs.

Architecture maps those requirements to controls; DoD defines the required security gate; QA prepares concrete checks; the development plan maps implementation and verification work. [Security traceability records](skills/to-sdd-pipeline/references/security-contract.md) prevent declared requirements from disappearing downstream.

When behavior, permissions, data exposure or integrations change, reassess affected PRD obligations before synchronizing design and downstream documents. Purely visual changes reuse unaffected security requirements.

No security scans run during documentation authoring. Product implementation, actual security verification and ongoing maintenance remain separately authorized work.

## Checks, evidence and safe continuation

A prepared checklist means **checks prepared; tests not run**. Definition status and execution status are separate. Release is not evaluated during ordinary planning; an actual release evaluation passes only with required evidence and no open blocking findings.

Visual fidelity, heuristic review, representative-user validation, accessibility and functional testing need distinct evidence. A good-looking prototype does not prove task success or completed functionality.

`to-dod-evals` defines the gates; an authorized reviewer/test harness/runner executes them; QA records results; the orchestrator tracks them. Severity and release effect are separate, using the canonical P0–P3 rules. [Verification contract](skills/to-sdd-pipeline/references/verification-contract.md).

The read-only checker verifies prerequisites, owners, hashes, context-pair integrity, frozen render resources, evidence and implementation authorization. It rejects omitted check/gate links and excluded-only applicable gates. [Typed traceability](skills/to-sdd-pipeline/references/traceability-contract.md) connects jobs, use cases, requirement clauses, states, checks and units; missing IDs/required mappings block the affected stage. Prototype reuse additionally verifies source/destination bytes and the scoped Git diff. **Consulted-later** information still creates no false prerequisite loop.

```bash
python3 skills/to-sdd-pipeline/scripts/sdd_check.py --project /path/to/product --before development-plan
```

Agents resolve the checker from the installed skill directory, not the product folder. Older projects retain valid documents, IDs and history; their owners supply missing assessments, including security, before verified metadata is recorded. Missing required evidence remains a blocker. [Checker schema and migration](skills/to-sdd-pipeline/references/manifest-contract.md).

The checker validates records, not research authenticity, complete dynamic behavior or control adequacy. Direct Codex/Claude Code can run the pipeline inline, persist intake and reject stale owner returns without DAS Forge. Any external production runner must enforce checker results itself; this repository does not contain or modify it.

After the plan validates, `awaiting-implementation-prompt` remains mandatory. Approval, automatic resume and a generic “continue” do not authorize production work.

## Delivery and evaluation

The [risk-based lifecycle checklist](skills/to-sdd-pipeline/references/lifecycle-contract.md) covers applicable rollout/rollback, migrations, restore, operational ownership, performance/cost, content and post-release feedback within existing owners. It adds no document, deployment permission or approval procedure.

[Behavioral scenarios](docs/agent-evaluations.md) assess actual agent decisions and outputs, separately from deterministic tests. They start **not run**; neither a synthetic fixture nor the author's self-review is independent agent evidence.

## Clear language and token use

Every skill and generated SDD document uses direct wording, explains unfamiliar terms briefly, records a decision once and references it elsewhere. Required details, evidence, IDs, risks and approval boundaries stay intact. Existing valid project documents are not rewritten just to shorten them.

The working language follows explicit instruction, recorded preference, then the user's latest substantive message. Product locales stay separate. With Ukrainian, ordinary prose/headings are idiomatic Ukrainian; paths, code, machine values, proper names and approved IT terms remain unchanged.

Detailed conditional guidance lives in shared references. Reuse unchanged loaded rules and valid artifacts; use `sdd_check.py --snapshot NODE` for an unvalidated hash proposal, not a fabricated review. [Maintenance checks](docs/maintenance.md) count full references/retries and enforce recent-version growth plus absolute budgets. New correctness rules can increase static loads; report that openly. Measurements are not model-billing or live-run savings claims.

## Further reading

- [Version 2.0 design-quality note](VERSION-2.0.md) — historical summary.
- [Audit prompt](claude-code-skill-audit-prompt.md).
- [Authoring provenance](skills/to-sdd-pipeline/references/authoring-sources.md) — historical influences, not product truth.
