# Codex SDD Skills

This repository contains reusable Codex skills. Its core is a design-first SDD pipeline for moving from a rough product description or trusted existing idea through a visible Product Idea Intake, a coherent pre-design specification, exactly three runnable prototype candidates, one whole-design approval, and implementation planning for a production frontend and backend. It also contains bounded standalone workflows such as communications audits and certificate issuance.

The skills are designed for **SDD - Specification Driven Development**. They are not a TDD workflow and they are not generic prompt templates. Every domain artifact has exactly one owner, and every owner invocation is confined to its declared output boundary. Most owners create one artifact; `to-project-context` is the explicit cohesive two-file bundle owner. `to-sdd-pipeline` owns only the machine-readable orchestration manifest and invokes or re-invokes artifact owners autonomously.

## Skill Chain

Use `to-product-idea` as the visible Phase 0 owner when the product idea is absent, incomplete, imported for validation, or materially changed. After its handoff, `to-sdd-pipeline` is the autonomous downstream entrypoint. Together they dispatch this acyclic graph:

```text
rough-description-or-existing-or-imported-idea -> to-product-idea -> product-idea handoff
-> to-prd
-> to-project-context (project-context.md + canonical-terms.md)
-> to-guardrails
-> to-user-journey
-> to-screen-map
-> to-wireframes
-> to-design-brief
-> to-architecture
-> to-dod-evals
-> to-qa-checklist (proposed visual checks)
-> three prototype candidates
-> one whole-design approval
-> design-brief and QA reconciliation
-> to-development-plan
```

`to-product-idea` solely owns `docs/product-idea.md` and uses a foreground, resumable, one-question-at-a-time intake. `Create product idea and start SDD` atomically creates or versions the file only when needed, preserves an unchanged existing file byte-for-byte, and records its handoff receipt; it is an execution command, not an approval. `to-prd` is the first SDD domain-artifact owner dispatched by `to-sdd-pipeline` after that handoff. `to-project-context` runs immediately after the PRD and both bundle members must validate before later owners run. `docs/wireframes.md` never depends on the later design brief, and the development plan is deliberately post-approval because it consumes the Approved Visual Baseline.

## Included Skills

| Skill | Output | Purpose |
|---|---|---|
| `to-product-idea` | `docs/product-idea.md` | Runs the visible Product Idea Intake, asks only material non-inferable questions one at a time, and atomically creates or versions the operator-confirmed upstream product mandate. |
| `to-sdd-pipeline` | `forge/sdd-manifest.json` | Dispatches artifact owners, tracks dependencies and hashes, runs prototype comparison, resumes after the one approval, and propagates invalidation without editing domain artifacts directly. |
| `to-prd` | `docs/prd.md` | Converts the product idea and current project evidence into the first file-based domain artifact without issue-tracker side effects. |
| `to-project-context` | `docs/project-context.md` and `docs/canonical-terms.md` | Creates the atomic context/vocabulary bundle after PRD validation; the two outputs are validated and hashed separately under one owner invocation. |
| `to-user-journey` | `docs/user-journey.md` | Maps the real user, goal, context, journey stages, friction, decisions, failure path, and success state. |
| `to-screen-map` | `docs/screen-map.md` | Defines screens, surfaces, routes, navigation, transitions, entry/exit points, and the canonical state list per screen. |
| `to-wireframes` | `docs/wireframes.md` | Converts the screen map into low-fidelity screen structures, hierarchy, CTAs, forms, content zones, and state variants. |
| `to-design-brief` | `docs/design-brief.md` | Defines the UX/UI direction and owns the single canonical Approved Visual Baseline manifest after whole-prototype approval. |
| `to-architecture` | `docs/architecture.md` | Defines system architecture, modules, boundaries, data/state model, integrations, runtime model, architecture decisions, and risks. |
| `to-dod-evals` | `docs/dod-evals.md` | Defines Definition of Done, reusable eval gates, verification profile, evidence requirements, state/lane gates, and PR/merge completion rules. |
| `to-guardrails` | `docs/guardrails.md` | Defines source-of-truth order, AI autonomy boundaries, scope limits, conflict handling, stop conditions, and verification policy. |
| `to-qa-checklist` | `docs/qa-checklist.md` | Creates a source-backed QA checklist with acceptance, UX/UI, responsive, accessibility, visual regression, evidence, and release-readiness checks. |
| `to-development-plan` | `docs/development-plan.md` | Converts the current validated SDD plus Approved Visual Baseline into frontend/backend units, interface seams, dependency order, acceptance checks, and verification steps. |
| `communications-audit` | Professional `.docx` audit report | Audits websites and sales or marketing materials through seven communication dimensions, then produces an evidence-led scorecard, prioritized findings, and implementation roadmap. |

## Core Rules

All skills follow the same operating contract:

- AI is not the source of truth. Source files and explicit user answers are.
- Missing product intent is surfaced through the foreground Product Idea Intake, never silently generated in background logs. Material questions persist as `Input needed`; silence, timeout, and recommendations are not consent.
- Intake answers and `Create product idea and start SDD` are input/start actions, not approval receipts. The only normal approval is still approval of the complete integrated prototype.
- Discoverable information must be read from sources or code instead of asked. A focused grill-me gap-check runs only for genuinely non-inferable information that materially changes product scope, the whole-design baseline, or a high-risk boundary.
- Every material gap-check walks one relevant decision branch, asks one question, gives a recommended answer and rationale, cites the source basis or says no source confirms it, names affected downstream artifacts or boundaries, and plays back the confirmed decision plus consequences before continuing.
- Non-material gaps use the smallest reversible source-grounded default, are recorded, and do not become approval gates.
- An owner invocation creates only its declared final output path or cohesive output set. No draft output files.
- Unverified assumptions are never written as facts. `project-context.md` may retain them only in its explicitly labeled `Assumptions` section; unresolved decisions belong in `Open Questions`.
- Anything not source-backed or user-confirmed is either a clearly labeled contextual assumption or an `Open Question`, never silent product truth.
- Every artifact has exactly one owner. `to-project-context` may update only its declared two-file bundle; all other current domain owners update one artifact.
- The orchestrator never edits a domain artifact directly; it dispatches the owning skill and owns only `forge/sdd-manifest.json`.
- Artifacts reference prior artifacts instead of duplicating them.
- Artifact boundaries must be preserved.
- The only normal design approval is approval of the complete integrated prototype. Risk-specific authorization is separate and just in time.

## Artifact Boundaries

The documents are intentionally separated:

- `product-idea.md` owns the current operator-confirmed product mandate. `to-product-idea` is its sole owner; runtime draft/session data and `ProductIdeaHandoffReceipt` remain operational provenance under `forge/intake/`.
- `project-context.md` owns confirmed product context, users, platforms, boundaries, constraints, assumptions, risks, and open questions derived after PRD work.
- `canonical-terms.md` owns normalized downstream vocabulary and aliases without redefining PRD behavior or established technical identifiers.
- `user-journey.md` owns user behavior and journey logic.
- `screen-map.md` owns which screens and states exist.
- `wireframes.md` owns screen structure and state structure.
- `design-brief.md` owns visual and experience direction plus the single canonical Approved Visual Baseline section. The approved prototype owns concrete visual composition, interaction detail, and frontend presentation; PRD/journey artifacts own product behavior.
- `architecture.md` owns system architecture, module boundaries, data/state model, integrations, runtime model, and architecture decisions.
- `dod-evals.md` owns Definition of Done, reusable gates, eval result format, completion evidence requirements, and completion rules.
- `guardrails.md` owns AI behavior, source-of-truth policy, and behavioral evidence policy.
- `qa-checklist.md` owns concrete verification checks and per-check evidence artifacts.
- `development-plan.md` owns implementation units and build order.
- `forge/sdd-manifest.json` owns orchestration state, owner invocation/output-set mapping, source versions and hashes, consumed source fragments, explicit dependencies and dependency states, content hashes, validation, invalidation, and resume state; it does not own domain truth. Internal `validated` projects to Mission Control `Done`, while `ready` means machine-ready rather than approved.

If one artifact needs information from another, it should cite or reference that artifact rather than restating it.

## Installation

For Codex to discover these skills, place each skill directory under your Codex skills directory.

Recommended local install with symlinks:

```bash
mkdir -p ~/.codex/skills
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-sdd-pipeline" ~/.codex/skills/to-sdd-pipeline
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-product-idea" ~/.codex/skills/to-product-idea
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-prd" ~/.codex/skills/to-prd
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-project-context" ~/.codex/skills/to-project-context
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-user-journey" ~/.codex/skills/to-user-journey
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-screen-map" ~/.codex/skills/to-screen-map
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-wireframes" ~/.codex/skills/to-wireframes
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-design-brief" ~/.codex/skills/to-design-brief
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-architecture" ~/.codex/skills/to-architecture
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-dod-evals" ~/.codex/skills/to-dod-evals
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-guardrails" ~/.codex/skills/to-guardrails
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-qa-checklist" ~/.codex/skills/to-qa-checklist
ln -s "/Users/ingwar/Projects/Codex Skills/skills/to-development-plan" ~/.codex/skills/to-development-plan
ln -s "/Users/ingwar/Projects/Codex Skills/skills/communications-audit" ~/.codex/skills/communications-audit
```

If a symlink already exists, remove or update only that symlink. Do not overwrite an existing personal skill with the same name unless that is intentional.

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

The orchestrator dispatches every ready artifact owner without asking the user to continue. A later material product-intent gap returns to the same Intake surface, versions the idea through its owner, and invalidates only transitive dependents. It otherwise pauses only for the one whole-design approval or a just-in-time high-risk authorization. `to-guardrails` runs after the PRD and is regenerated only when a named upstream change invalidates one of its rules; the mere appearance of later UX files is not a rerun trigger.

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
- `verification-before-completion`: `/Users/ingwar/.codex/plugins/cache/openai-curated/superpowers/d6169bef/skills/verification-before-completion/SKILL.md`
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
  to-prd/
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
  communications-audit/
    SKILL.md
    agents/openai.yaml
    references/
    scripts/build_report.py

claude-code-skill-audit-prompt.md
```

`claude-code-skill-audit-prompt.md` is the audit prompt used to review these skills against the user's requirements and relevant external skills.
