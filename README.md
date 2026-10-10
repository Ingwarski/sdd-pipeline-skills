# SDD Pipeline Skills

13 skills for Codex and Claude Code turn product intent into specifications, reviewed design and a development plan. **Specification-Driven Development** agrees what to build first; tests verify those decisions.

## Quick start

1. [Install the complete collection](#installation) and [select evidence storage](docs/evidence-storage.md).
2. Open your product project: `Use to-sdd-pipeline for this project.`
3. Answer focused questions and share existing design references once.
4. Choose Codex or Claude Design when prototyping begins; compare three interactive whole-product candidates and approve one complete version.
5. The pipeline records that baseline, reconciles architecture, completion rules and QA, creates `docs/development-plan.md`, then pauses.
6. Send a **new explicit implementation prompt after that pause** to start production work.

A rough description or existing `docs/product-idea.md` is enough to enter. Intake shows its understanding and gaps before one question; coherent intent needs no redundant interview. Share links, screenshots, brand materials or HTML/assets through the prompt or `docs/design-inputs/` in your product repository. “None yet” or “later” is valid. References supply design grounding, never approval.

Existing changes reuse valid documents/baselines and reconcile affected owners. Confirmed headless products skip UI documents and design approval while retaining requirements, security, QA, planning and the implementation prompt. [Scope and direct-host execution](skills/to-sdd-pipeline/references/scope-and-execution.md).

## Installation

Requires **Python 3.12+**; local installer/checker/storage tools use its standard library. Python 3.14 is recommended under [runtime policy](runtime-policy.json); no student Node dependency is added. If necessary, use the [official Python installers](https://www.python.org/downloads/) and [platform instructions](docs/installation.md). Already-current setups preserve a supported runtime; never replace the OS interpreter.

Paste the complete [install-or-update prompt](INSTALL-OR-UPDATE-PROMPT.md) into a local agent. It checks repository revision, exact installed links/resources, Python and evidence setup before deciding what needs work. A current skill installation can still need storage setup; existing choices are preserved. Opening a repository does not install skills, choose a cloud account or upload evidence.

For the tested channel:

```bash
git clone --branch stable https://github.com/Ingwarski/sdd-pipeline-skills.git
cd sdd-pipeline-skills
git switch -c main
```

| Platform | Install | Update |
|---|---|---|
| macOS / Linux | `./install.sh --all` | `./update.sh --channel stable --all` |
| Windows PowerShell | `.\install.ps1 -All` | `.\update.ps1 -Channel stable -All` |

Launchers use the same scripts. Select `--codex`/`--claude` or `-Codex`/`-Claude` for one agent. Windows falls back to NTFS junctions when symbolic links are unavailable. Links always point to the durable clone; use repair after moving it. Conflicting unrelated files are reported, never overwritten. [Destination overrides, bootstrap, repair and uninstall](docs/installation.md).

The updater defaults to `main` for compatibility; explicitly choose `stable` for tested updates. CI advances stable only after the current main passes Linux/macOS/Windows checks. Missing channels and divergent/ahead local commits never cause fallback or downgrade. Plain Git pull performs no retirement cleanup; first evidence use still detects missing setup. No scheduler, hook or background updater is installed.

Retirement permanently removes exactly the two names in [retired-skills.txt](retired-skills.txt), including edited copies/links and matching old backups in selected roots. Additional roots require explicit `--cleanup-dir`/`-CleanupDir`. There is no disk-wide scan, backup, Trash move or link-target traversal. Retirement may finish before a separate Git/link conflict blocks update; failures and remaining paths must be reported.

Former repository: `Ingwarski/codex-skills`. The manifest maps old SDD `to-prd` to `to-sdd-prd` without another confirmation; preserve unrelated third-party `to-prd`. The 13 names, outputs, collection identity and source receipt remain stable. Private business skills are separate and are not installed.

## Workflow and ownership

```text
Product idea → PRD → context + vocabulary → guardrails
→ journey → screen map → wireframes → design brief
→ architecture → completion rules → proposed QA
→ three prototypes → one whole-design approval
→ baseline → reconcile architecture → completion rules → QA
→ development plan → await implementation prompt
```

| Skill | Owned output |
|---|---|
| `to-product-idea` | `docs/product-idea.md` |
| `to-sdd-prd` | `docs/prd.md` |
| `to-project-context` | `docs/project-context.md` + `docs/canonical-terms.md` |
| `to-guardrails` | `docs/guardrails.md` |
| `to-user-journey` | `docs/user-journey.md` |
| `to-screen-map` | `docs/screen-map.md` |
| `to-wireframes` | `docs/wireframes.md` |
| `to-design-brief` | `docs/design-brief.md` |
| `to-architecture` | `docs/architecture.md` |
| `to-dod-evals` | `docs/dod-evals.md` |
| `to-qa-checklist` | `docs/qa-checklist.md` |
| `to-development-plan` | `docs/development-plan.md` |
| `to-sdd-pipeline` | `forge/sdd-manifest.json` |

Each artifact has one owner. Context outputs share an invocation, with independent hashes/results. Owners declare consumed files/sections or explain unused context; the orchestrator records their metadata without editing domain meaning. Standalone owners validate inputs without needing a manifest. [Shared rules](skills/to-sdd-pipeline/references/common-contract.md).

`JOB-*` describes user progress and situation; `UC-*` describes product responses and recovery. Screen map owns state inventory; wireframes own structure; design brief owns appearance/behavior and the approved baseline. [H1–H10](skills/to-sdd-pipeline/references/heuristic-usability-review.md) covers novice/expert efficiency, contextual help and recovery: cause → preserved work → next action → retry/undo → observable success.

Codex shows three separate live pages on the selected visible review surface, defaulting to the external browser. Claude Design compares three tool-native candidates after source-access checks; only the selected export is imported and reviewed. Selection/export is not approval. [Claude handoff](skills/to-sdd-pipeline/references/claude-design-handoff.md).

Frozen rendering inputs include shared fonts, images, CSS and scripts; mutable remote assets must be packaged. Browser inspection still verifies dynamic dependencies. Revisions preserve original approved files/receipts and revalidate affected owners. [Freeze contract](skills/to-sdd-pipeline/references/freeze-contract.md). [Accessibility policy](skills/to-sdd-pipeline/references/accessibility-policy.md) separates WCAG criteria from source-overridable house style. High-risk user-validation deferrals remain named risks, never invented research.

## Evidence storage

Select managed local storage outside Git, a chosen folder/disk/mount, or **Google Drive**. Setup records destination, aggregate/local limits, retention and adoption choice. Machine paths/credentials stay outside Git; `forge/evidence-policy.json` holds portable IDs and policy. Moving to another folder on the same disk reduces Git clutter without freeing disk space.

Drive supports a capability-qualified connected bridge or optional standalone rclone. Setup must upload synthetic bytes and independently retrieve/verify them. Account authentication is a user step; missing capabilities never silently select another provider. Ordinary local users need no cloud account or rclone. [Complete setup, authentication and commands](docs/evidence-storage.md).

Keep authored sources/fixtures, canonical SDD, necessary approved design inputs, compact current results/receipts and evidence references in Git. Generated captures, recordings, large logs, detailed observations and superseded history use immutable verified archive packs. Adoption registers existing objects without payload reupload and preserves original catalogs, times and protections. Never blanket-ignore `forge/` or `output/`; classify actual contents. Ignoring files does not remove their committed history.

Storage prepares active bytes outside the checkout. The read-only checker verifies actual bytes, reference closure, source/plan/baseline/toolchain/execution bindings and original receipt semantics; it performs no network/cache writes. Missing/corrupt evidence blocks its claim. Storage never reruns checks or makes stale observations current. [Storage contract](skills/to-sdd-pipeline/references/evidence-storage-contract.md).

Versioned defaults cover cumulative run/unit/project generation and file counts, retained unique content/objects, combined metadata/index size, local capture/cache/staging/restoration reservations, retries and free-space reserve. Workers/resumes/worktrees share stable IDs and charges; deduplication/cleanup do not refund generation. Managed producers stop truthfully on exhaustion. External writers can bypass physical enforcement, so registered outputs must reconcile before completion. [Numeric policy and sizing rationale](docs/evidence-storage.md#defaults-and-sizing).

Local generated-artifact expiry defaults to **30 days** from original sealing. Protection checks preserve current acceptance/prerequisites, baselines, approvals/authorization, unresolved failures, explicit retention and imported recovery archives. Cache eviction differs from permanent expiry; a sole durable local store is not disposable cache. Cleanup runs at managed boundaries or explicit command, with dry-run and verified deletion; no default daemon. Drive expiry is explicitly selected.

GitHub artifact uploads, when needed, use `retention-days: 30`; the repository artifact/log setting is configured separately. Workflow YAML does not configure log retention, and local protections cannot prevent GitHub expiry. Preserve required bytes in the durable store first. [GitHub retention guidance](https://docs.github.com/en/actions/tutorials/store-and-share-data).

## Validation and safe continuation

A prepared checklist means **checks prepared; tests not run**. QA interprets inspected results; executors produce observations; DoD defines reusable gates; storage persists evidence; the orchestrator indexes it. Visual fidelity, heuristic review, representative-user research, accessibility, security and functionality remain separate claims. [Verification rules](skills/to-sdd-pipeline/references/verification-contract.md).

PRD applies the [OWASP procedure](skills/to-sdd-prd/references/security-authoring.md) using pinned offline ASVS 5.0.0; architecture/DoD/QA/plan retain those requirement IDs and required security acceptance. This adds no skill, approval, scanner, paid service or certification claim. Security-impacting changes return upstream; styling alone preserves unaffected requirements.

The checker validates owner/dependency integrity, typed traceability, contained sources, frozen design, current evidence, promotions and authorization. Consulted-later information creates no false prerequisite loop. Older projects preserve valid documents, IDs, receipts and history; owners review missing metadata without inventing observations. [Manifest and migration](skills/to-sdd-pipeline/references/manifest-contract.md).

```bash
python3 skills/to-sdd-pipeline/scripts/sdd_check.py --project /path/to/product --before development-plan
```

Resolve scripts from the installed skill directory. Direct hosts can execute owner roles inline. External production runners must enforce checker results; this repository contains no production runner and cannot authenticate research or guarantee undeclared source completeness.

After authorization, **finish the full active unit** including integration, tests, fixes and evidence. Pause only for a genuine blocker, required input/permission or explicit stop/change. Parallel tasks stay within the active unit, with exclusive writes and shared reservations. Unit numbers follow dependency order; Unit 8 cannot require Unit 9. Plans embed the continuation rule and retain required real-consumer acceptance. [Unit contract](skills/to-sdd-pipeline/references/unit-execution-contract.md).

## Maintenance

[Lifecycle guidance](skills/to-sdd-pipeline/references/lifecycle-contract.md) allocates applicable delivery, rollback/restore, maintenance and outcome feedback to existing owners without authorizing deployment. [Agent evaluations](docs/agent-evaluations.md) separate independent behavior evidence from deterministic synthetic tests and author self-review.

Instructions state decisions once and load detailed procedures conditionally. Working language follows explicit instruction, recorded preference, then the latest substantive message; product locales remain separate. [Maintenance checks](docs/maintenance.md) measure complete instruction/resource/retry loads under fixed recent-growth and absolute budgets. These are static measurements, not model-billing or live-run savings claims.
