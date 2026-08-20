# Claude Code Prompt: Audit SDD Skills Pipeline

You are auditing a set of Codex skills. Do not modify files unless explicitly asked later. Your task is to deeply review whether these created skills match the user's needs and whether they properly reuse proven mechanisms from existing external skills instead of reinventing weak templates.

Workspace:
the repository root containing this prompt

## Created Skills To Audit

Read these files completely:

- `skills/to-product-idea/SKILL.md`
- `skills/to-sdd-pipeline/SKILL.md`
- `skills/to-sdd-prd/SKILL.md`
- `skills/to-project-context/SKILL.md`
- `skills/to-user-journey/SKILL.md`
- `skills/to-screen-map/SKILL.md`
- `skills/to-wireframes/SKILL.md`
- `skills/to-design-brief/SKILL.md`
- `skills/to-architecture/SKILL.md`
- `skills/to-dod-evals/SKILL.md`
- `skills/to-guardrails/SKILL.md`
- `skills/to-qa-checklist/SKILL.md`
- `skills/to-development-plan/SKILL.md`

## User's Core Requirements

1. This is an SDD pipeline, not TDD.
2. The intended chain is:
   `rough description or existing idea -> visible to-product-idea intake -> product-idea handoff -> to-sdd-prd -> to-project-context (project-context.md + canonical-terms.md) -> to-guardrails -> to-user-journey -> to-screen-map -> to-wireframes -> to-design-brief -> to-architecture -> to-dod-evals -> to-qa-checklist -> three prototypes -> one design approval -> to-development-plan`
   A pre-existing `docs/product-idea.md` is optional, never a pipeline-entry prerequisite. Audit both required entry scenarios: no file plus a rough description, and an existing/imported file selected for validation.
3. Every artifact must have exactly one owner, and each owner invocation must stay inside its declared output boundary. `to-project-context` is the explicit cohesive two-file output bundle; its two members must be validated and hashed separately under one invocation.
4. Output files must be strictly separated by responsibility and must not duplicate or contradict one another.
5. AI is not the source of truth. Source files and explicit user answers are the source of truth. `to-product-idea` may interview and recommend but must never invent or silently default the product mandate.
6. If required product intent is missing, Product Idea Intake must surface one visible material question at a time with a recommendation and rationale, persist it as `Input needed`, and wait for an explicit answer. Questions may not exist only in logs or resolve by timeout.
7. No draft output files. The skill should either create the final artifact or ask questions first.
8. No hidden assumptions. `project-context.md` may retain clearly labeled contextual assumptions in its dedicated `Assumptions` section; unresolved decisions go to `Open Questions`, and no assumption may become silent product truth.
9. The goal is not document proliferation. The goal is to reliably move from PRD to high-quality UX/UI design and then implementation planning.
10. If proven mechanisms already exist in other skills, use them. Do not reward shallow original templates.
11. The final audit must be direct, evidence-based, and specific. Do not give vague praise.
12. The pipeline must resolve and persist one working language before intake, pass it to every owner and design adapter, and keep product content locales separate. For Ukrainian, questions, reports, displayed statuses, headings, and artifact prose must be idiomatic Ukrainian; English may remain only for immutable paths/filenames, code/commands, machine values, API/identifiers, names/quotations, and approved IT terms such as `SDD Pipeline`, recorded with Ukrainian meanings in `canonical-terms.md`.

## Expected Output Artifacts In The Pipeline

- `docs/product-idea.md`
- `docs/prd.md`
- `docs/project-context.md`
- `docs/canonical-terms.md`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/wireframes.md`
- `docs/design-brief.md`
- `docs/architecture.md`
- `docs/dod-evals.md`
- `docs/guardrails.md`
- `docs/qa-checklist.md`
- `docs/development-plan.md`

## Artifact Responsibility Boundaries

Use these boundaries as the user's intended contract.

### `docs/product-idea.md`

Owns the current operator-confirmed product mandate, including positioning, target user/problem, desired outcome, core workflow, V1 scope/exclusions, product principles/authority boundaries, success outcomes, assumptions, and open questions. `to-product-idea` is its sole owner.

The skill must support two explicit entry scenarios. When no file exists, it must start from a rough description and use a foreground, resumable Product Idea Intake: one adaptive material question at a time, recommended answer and rationale, live draft/coverage, explicit answer persistence, and atomic final write/hash/handoff after `Create product idea and start SDD`. When an existing/imported file is selected, it must validate that file first, skip redundant questions if it is coherent, and ask only focused questions for material gaps or corrections. The file is optional at entry. The start action is an execution command, not an approval. Runtime dialogue/draft state and `ProductIdeaHandoffReceipt` are operational provenance under `forge/intake/`, not additional product-truth artifacts.

Must not own architecture, visual design, detailed journeys/screens/wireframes, DoD/eval gates, QA checks, implementation units, or unattended AI-selected product intent.

### `docs/project-context.md`

Owns confirmed product context, working language, separate product content locales, users, platforms, boundaries, constraints, assumptions, risks, and open questions derived after PRD work. It must not redefine PRD behavior or downstream architecture/design/DoD decisions.

### `docs/canonical-terms.md`

Owns downstream product vocabulary, aliases, terms to avoid, and deliberately preserved English IT terms with their Ukrainian meanings and usage boundaries. It must not redefine PRD behavior or silently rename established technical identifiers.

### `docs/user-journey.md`

Owns:

- primary user
- user context
- user goal
- motivation
- real-session framing
- named protagonist if source-backed or user-confirmed
- journey stages
- actions
- decision points
- friction
- fears
- blockers
- exit points
- success state
- failure path
- MVP journey risks

Must not own:

- screen list
- routes
- wireframe layout
- colors
- typography
- design tokens
- QA checklist
- implementation tasks

### `docs/screen-map.md`

Owns:

- screens
- surfaces
- routes
- navigation
- entry points
- exit points
- screen states
- transitions
- journey-to-screen trace
- surface closure

Must not own:

- detailed wireframe layout
- component hierarchy inside screens
- final visual design
- QA checklist
- implementation tasks

### `docs/wireframes.md`

Owns:

- low-fidelity screen structure
- hierarchy
- content zones
- CTAs
- fields
- forms
- state variants
- structural responsive notes

Must not own:

- final colors
- typography system
- brand mood
- visual polish
- design tokens
- implementation tasks

### `docs/design-brief.md`

Owns:

- UX/UI design direction
- visual system
- design spine
- experience spine
- information density
- interface tone
- semantic tokens
- typography direction
- color direction
- spacing rhythm
- component appearance principles
- component behavior principles
- interaction feel
- responsive behavior
- accessibility floor
- design handoff prompt or guidance

Must not own:

- new product features
- new screens
- new routes
- detailed wireframe duplication
- QA checklist
- implementation tasks

### `docs/architecture.md`

Owns:

- system architecture overview
- architecture principles and constraints
- module and boundary map
- runtime and automation model
- data and state model
- integration map
- technology stack constraints when source-backed or codebase-confirmed
- security, privacy, reliability, performance, and observability architecture concerns
- architecture diagram
- architecture decision log
- architecture risks and mitigations

Must not own:

- new product requirements
- user journeys
- screen inventory
- wireframe layouts
- visual design direction
- Definition of Done
- eval gates
- QA checklist
- implementation tasks

### `docs/dod-evals.md`

Owns:

- Definition of Done model
- acceptance criteria vs DoD distinction
- reusable verification profile
- hard gates
- unit checks
- system checks
- UX/UI checks
- release checks
- lane/state promotion gates
- eval result format
- evidence requirements
- failure and blocker classification
- rerun and recovery rules
- PR/merge/completion rules

Must not own:

- new product requirements
- architecture decisions
- user journeys
- screen inventory
- wireframe layouts
- visual design direction
- per-screen QA checklist details
- implementation units

### `docs/guardrails.md`

Owns:

- source-of-truth order
- AI autonomy boundaries
- allowed changes
- forbidden changes
- scope boundaries
- conflict resolution
- when to ask
- when to stop
- design authority rules
- evidence requirements
- artifact separation rules
- verification rules

Must not own:

- product journey content
- screen inventory
- wireframes
- visual design direction
- QA checklist details
- implementation plan

### `docs/qa-checklist.md`

Owns:

- source-backed QA checklist
- product acceptance checks
- journey checks
- screen/state checks
- wireframe consistency checks
- UX/UI checks
- visual regression checks
- responsive checks
- accessibility checks
- browser/device checks
- evidence requirements
- evidence limits
- release readiness

Must not own:

- new product requirements
- new journeys
- new screens
- wireframe changes
- visual design direction
- architecture decisions
- Definition of Done or reusable eval gates
- implementation tasks

### `docs/development-plan.md`

Owns:

- implementation units
- dependency order
- codebase map if a codebase exists
- work items
- source references per unit
- acceptance checks per unit
- verification plan
- visual/UX verification
- risks and sequencing
- out of scope

Must not own:

- new product requirements
- new journeys
- new screens
- visual design decisions
- architecture decisions
- Definition of Done or reusable eval gates
- QA checklist duplication beyond references

## External And Proven Skills To Inspect

Do not limit the audit to BMAD UX. BMAD UX is central for UX/UI planning, but the final skills must also learn from verified non-BMAD local skills: grill-me, to-sdd-prd, modern-ux-ui-2026, Product Design plugin skills, Figma plugin skills, verification-before-completion, writing-plans, executing-plans, and QA/design-QA equivalents.

If any file or URL is unavailable, say that explicitly. Do not pretend it was inspected.

### A. Non-BMAD Local Skills To Discover On The Current Machine

Do not assume a username, home-directory layout, plugin-cache version, or operating system. Resolve available skills by name from the current agent's advertised skill catalog and its documented personal, project, system, and plugin skill roots. Read the installed `SKILL.md` and only the references it routes you to. Record the resolved path and version when available; list a source as unavailable when it cannot be found.

Core behavior, source-of-truth, and gap-check:

- `grill-me`
- this repository's `to-product-idea` and `to-sdd-prd`
- `skill-creator` or the current platform's equivalent skill-authoring guide
- `writing-skills`, if installed

UX/UI and design quality:

- `modern-ux-ui-2026`
- current Product Design skills for context gathering, audit, ideation, image-to-code, prototyping, URL-to-code, design QA, and research
- the Product Design audit framework and critical overrides referenced by those skills

Figma and design handoff, if relevant:

- current Figma skills for using Figma, generating designs or libraries, diagramming, and motion handoff

Architecture, DoD, QA, verification, and planning:

- `verification-before-completion`
- `writing-plans`
- `executing-plans`
- `test-driven-development`, if installed, only to identify what not to import because this workflow is SDD, not TDD
- `https://github.com/luongnv89/skills/blob/main/skills/tad-generator/SKILL.md`
- `https://github.com/addyosmani/agent-skills/blob/main/skills/documentation-and-adrs/SKILL.md`
- `https://raw.githubusercontent.com/addyosmani/agent-skills/main/references/definition-of-done.md`
- `https://github.com/dawiddutoit/custom-claude/blob/main/skills/quality-run-quality-gates/SKILL.md`
- `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-epic-arch/SKILL.md`
- `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-plan/SKILL.md`
- `https://github.com/xwings/eatmycode`
- `https://github.com/NousResearch/hermes-agent/issues/44000`

### B. BMAD UX Coach References

Inspect these deeply:

- `https://raw.githubusercontent.com/bmad-code-org/BMAD-METHOD/main/web-bundles/ux-coach/SKILL.md`
- `https://raw.githubusercontent.com/bmad-code-org/BMAD-METHOD/main/web-bundles/ux-coach/INSTRUCTIONS.md`
- `https://raw.githubusercontent.com/bmad-code-org/BMAD-METHOD/main/web-bundles/ux-coach/ux-validation.md`

Extract especially:

- DESIGN.md spine
- EXPERIENCE.md spine
- Decisions log
- named-protagonist journeys
- concern scan
- surface closure
- spines-win-on-conflict rule
- validation rubric
- Stitch handoff prompt shape
- visual-first capture patterns
- accessibility and responsive expectations
- anti-patterns

### C. Previously Discussed Candidate Skills Without Verified URLs

These skill names were previously discussed as potentially relevant, but no verified public `SKILL.md` URLs are provided here. Search for these exact skill names online and in any local skill cache. If found, inspect them deeply and cite the exact path or URL. If not found, explicitly report `unavailable after search`. Do not infer their contents from the name alone, and do not pretend they were inspected.

Product structure and navigation:

- `site-architecture`

Interface, frontend, visual design:

- `frontend-design`
- `design-an-interface`
- `ui-ux-pro-max`

QA and testing:

- `qa`
- `webapp-testing`

Domain and source discipline:

- `domain-modeling`
- `ubiquitous-language`

Planning and implementation:

- `implement`
- `request-refactor-plan`

For each found external skill:

1. Read the full `SKILL.md`.
2. Extract concrete mechanisms that already work.
3. Decide whether each mechanism should be:
   - imported directly;
   - adapted;
   - rejected;
   - used only as a negative example.
4. Compare against the created SDD skills and identify missing useful mechanisms.
5. If a skill has security, dependency, or overreach risks, do not recommend wholesale use. Extract only safe useful mechanisms.

If none of these candidate skills can be found as actual readable `SKILL.md` files, the audit must still proceed using the verified non-BMAD local skills and BMAD UX references above. Do not block the audit on unavailable candidate names.

## Audit Process

1. Read all 13 created skills completely.
2. Read the listed local external/proven skills completely.
3. Fetch and read the BMAD UX Coach references if network access is available.
4. Search for the other named public/external skills.
5. Extract the working mechanisms from every available external skill.
6. Compare each created skill against:
   - the user's requirements;
   - artifact separation;
   - SDD pipeline position;
   - grill-me/gap-check behavior;
   - source-of-truth discipline;
   - UX/UI quality usefulness;
   - reuse of proven mechanisms;
   - avoidance of TDD-first thinking;
   - avoidance of hidden assumptions;
   - final artifact only, no draft output.
   - visible foreground intake, durable resume, typed `Input needed`, no material timeout/default, exact product-idea hash/handoff, and no extra approval receipt.
7. Identify weak, shallow, duplicated, contradictory, overbuilt, or missing parts.
8. Do not praise vaguely. Give concrete findings with file and line references.
9. For every finding, explain:
   - what is wrong;
   - why it matters;
   - which external skill or mechanism should influence the fix;
   - what exact change should be made.
10. Pay special attention to `to-design-brief`: it must be strong enough to guide high-quality UX/UI design, not just produce a generic design brief.
11. Pay special attention to `to-guardrails`: it must prevent AI from inventing scope, silently ignoring missing sources, or claiming completion without evidence.
12. Pay special attention to `to-product-idea`: it must make missing intent visible to the operator, ask one material question at a time, persist/recover the session, never treat a recommendation as consent, write only the final authoritative artifact, preserve an unchanged coherent existing file byte-for-byte, and hand off automatically without creating an approval gate.
13. Pay special attention to whether `to-sdd-pipeline` treats a pre-existing `docs/product-idea.md` as optional at entry and required only as validated input before `to-sdd-prd`; routes no-file, missing/stale-handoff, incomplete, or later-invalidated intent through `to-product-idea`; validates both the no-file and coherent-existing-file paths; and invalidates only transitive dependents.
14. Pay special attention to duplicated ownership between artifacts.
15. Pay special attention to whether the current skills say "source-backed" but still allow vague output.

## Required Report

Return the audit in this exact structure:

```markdown
# SDD Skills Audit

## Executive Verdict

Verdict: ready / partially ready / not ready

Explain the verdict in 3-6 concrete sentences.

## Sources Inspected

### Created Skills

List each created skill and confirm it was read.

### Local External Skills

List each local external skill and confirm whether it was read or unavailable.

### BMAD UX References

List each BMAD URL and confirm whether it was read or unavailable.

### Other Public/External Skills

For each searched skill name, report found/read or unavailable.

## Mechanisms Extracted From Proven Skills

Create a table:

| Source Skill / Reference | Working Mechanism | Should Be Used Where | Current Status In Created Skills | Gap |
|---|---|---|---|---|

## Skill-By-Skill Audit

For each created skill:

### `skill-name`

- Intended output:
- Pipeline position:
- Verdict:
- What works:
- Missing or weak mechanisms:
- Duplication or boundary risks:
- Source-of-truth / grill-me risks:
- UX/UI quality risks, if relevant:
- Recommended fixes:

## Artifact Separation Matrix

Create a table:

| Artifact | Owns | Must Not Own | Current Boundary Quality | Risks | Fix |
|---|---|---|---|---|---|

## External Mechanism Fit Matrix

Create a table:

| Created Skill | Output Artifact | Main Responsibility | Relevant External Mechanisms | What Is Good | What Is Missing | Recommended Fix |
|---|---|---|---|---|---|---|

## UX/UI Quality Risks

Focus especially on whether `to-wireframes` and `to-design-brief` can actually lead to a high-quality product UI.

## Grill-Me And Source-Of-Truth Risks

Explain whether the skills truly prevent invention, hidden assumptions, and premature file creation.

## SDD vs TDD Risks

Explain whether any imported planning/testing mechanism accidentally pushes the process toward TDD rather than SDD.

## Critical Findings

Use this format:

- `[Critical] file:line` Finding title.
  - Problem:
  - Why it matters:
  - External mechanism to use:
  - Exact fix:

## High Findings

Same format.

## Medium Findings

Same format.

## Low Findings

Same format.

## Prioritized Fix List

### Critical

### High

### Medium

### Low

## Final Recommendation

Say whether these skills should be used as-is, patched first, or redesigned.
```

## Hard Rules For This Audit

- Do not modify files in this run.
- Do not claim a source was inspected unless it was actually opened and read.
- Do not infer external skill content from the name alone.
- Do not give generic quality praise.
- Do not propose adding more documents unless absolutely necessary.
- Prefer patching the existing 7 skills over expanding the pipeline.
- Preserve the user's SDD goal: PRD to high-quality UX/UI to implementation planning.
- The user values directness over politeness. Be precise and useful.
