---
name: to-dod-evals
description: Use when the current validated product, guardrail, UX/design, and architecture SDD chain exists and the user wants dod-evals.md, Definition of Done, eval gates, verification profile, quality gates, engineering lane/state promotion gates, PR/merge rules, or evidence requirements before QA checklist or development planning. Artifact readiness is not a human approval.
---
# to-dod-evals

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/dod-evals.md`, every DoD rule, gate, eval, and evidence requirement must be source-backed, user-confirmed, codebase-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized verification rules not fully determined by source files or existing code, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded rule unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate. If a proposed rule would change an already Approved Visual Baseline, record `baseline_change_required` for the orchestrator instead of asking or approving inside this skill.

Never write a repository-state observation as a bare fact. Record `<claim> — observed <ISO date> via <command>` plus the exact observed paths and content hashes in the orchestrator's scoped repository observation. Never assert that something does not exist without naming the command that would prove it still does not.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/wireframes.md`
- `docs/design-brief.md`
- `docs/architecture.md`
- `docs/guardrails.md`
- `skills/to-sdd-pipeline/references/heuristic-usability-review.md`, for the canonical H1-H10 definitions and heuristic gate contract
- `docs/product-idea.md`, only if `docs/prd.md` explicitly names it as an authoritative source or the user asks to use it

Use confirmed relevant platform, localization, operational, privacy/compliance, risk, and vocabulary facts from the context bundle only when they change an applicable completion or evidence condition. Do not copy descriptive context, promote assumptions to gates, add product scope, or let either file override the PRD, architecture, guardrails, or Approved Visual Baseline. Record only the exact sections or terms consumed when pipeline provenance is requested.

Inspect the codebase when implementation or verification will happen in an existing project. Package scripts, CI config, tests, build config, lint/typecheck config, and deployment config can confirm available gates; they do not authorize new product scope.

## Output
Create or update exactly one artifact:
- `docs/dod-evals.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/dod-evals.md` owns:
- Definition of Done model
- distinction between acceptance criteria and standing DoD
- reusable verification profile
- hard gates, unit checks, system checks, UX/UI checks, and release gates
- reusable representative-user task validation gate for applicable critical or consequential user-visible flows
- reusable H1-H10 `heuristic_usability_review` gate for applicable user-visible flows
- engineering lane/state promotion gates only when sources define a delivery or execution-state promotion contract
- eval result format
- completion evidence requirements
- failure and blocker classification
- rerun, recovery, PR, merge, and completion rules

It must not define:
- new product requirements
- architecture decisions
- user journeys
- screen inventory or wireframe layouts
- visual design direction
- per-screen QA checklist details
- implementation units or task breakdown

`docs/guardrails.md` owns the behavioral evidence policy: when the AI must verify, what counts as evidence, and when missing evidence must stop work. `docs/dod-evals.md` uses that policy to define the reusable completion/eval contract and gate-specific evidence required for Done. `docs/qa-checklist.md` owns concrete checklist items and per-check evidence artifacts for a specific product artifact or release.

## Proven Mechanics To Use
Adapt the useful parts of proven DoD, quality-gate, planning, and eval references:
- From `definition-of-done`: separate acceptance criteria from Definition of Done; acceptance asks "did we build the right thing"; DoD asks "is it finished to our standard"; use a stable reusable bar for correctness, quality, integration, documentation, and ship-readiness.
- From `quality-run-quality-gates`: detect available project gates; run gates before completion claims; report pass/fail clearly; completion is blocked until gates pass; rerun after fixes.
- From `verification-before-completion`: evidence before claims; identify what proves the claim, run it fresh, read the output, then state the result.
- From `breakdown-plan`: define DoD at useful levels such as product, feature/unit, story/task, enabler, and test where sources support those levels.
- From eval/lane-gate patterns: attach eval definitions to workflow state transitions; a lane promotion is blocked until required evals pass; evals have standard result shape and persistable evidence.
- From SDD guardrails: source docs and confirmed code win over agent self-assessment.
- Split intended truth by concern: current validated SDD owns product scope and behavior; the engineer-approved integrated prototype owns visual composition, interaction detail, and frontend presentation and is the visual Definition of Done for every user-visible frontend unit; architecture and guardrails own technical and risk boundaries. Treat even the Approved Visual Baseline as design/visual evidence, not proof of completed functionality, until implementation is connected to real state/data/actions, runner evidence, and required DoD gates.
- Define one reusable parameterized gate named `approved_visual_baseline_fidelity` for frontend, full-stack, and integration units with user-visible output. Parameterize it with the active Baseline ID, immutable target hash, affected routes/states/viewports, permitted variance, concrete QA check IDs, `VisualQAEvidence`, and the `PrototypePromotionReceipt` when prototype code was reused. Pass only when the baseline is current, required coverage exists, every deviation is permitted or source-backed, and no blocking fidelity finding remains. When the development plan declares traced prototype reuse, the receipt must exist at its declared path and its recorded promotion strategy must match the plan's `copy | adapt | reimplement` value. A missing receipt for a unit whose declared production destination exists is blocking, not `not applicable`. A stale or superseded baseline, missing target/coverage, unexplained material drift, P0, P1, or blocking P2 blocks the gate; advisory P2/P3 remains follow-up.
- Define one reusable parameterized gate named `representative_user_task_validation` for applicable critical, consequential, new, or behavior-changing user-visible flows. Parameterize it with the traced `JOB-*` and `UC-*` references, representative user group, task, device/viewport, success criterion, validation evidence, findings, and applicability decision. Pass only when the task was observed with representative user(s), the defined outcome and evidence are recorded, and any blocking findings are closed or explicitly handled by the applicable release rules. `not applicable` is valid only with a source-backed rationale; `deferred` is not a pass for an applicable critical flow. A plan, heuristic review, screenshot, browser receipt, or agent self-assessment does not substitute for representative-user evidence. This gate is evidence of usability validation, not a second design approval gate.
- Define one reusable parameterized gate named `heuristic_usability_review` for applicable user-visible flows. Parameterize it with the relevant H1-H10 IDs, primary journey, traced `JOB-*`/`UC-*`, representative screens/states/routes/viewports, desktop/mobile coverage when supported, error/recovery coverage, accessibility-critical actions, concrete QA check IDs, evidence references, findings, and applicability decisions. Pass only when every applicable heuristic is reviewed, every required surface/viewport/state is covered, required evidence is recorded, and no blocking heuristic finding remains. A heuristic may be `not applicable` only with a source-backed rationale; an unexplained omission or deferred critical review blocks the gate. This gate is separate from `approved_visual_baseline_fidelity` and `representative_user_task_validation`; visual fidelity and user testing cannot substitute for it. Use the shared heuristic reference rather than copying H1-H10 definitions into the DoD artifact.

Do not copy these source skills wholesale:
- Do not turn this into a command runner. This skill writes the DoD/evals source-of-truth document; it does not execute gates.
- Do not create GitHub issues, project automation, or sprint plans.
- Do not equate "tests pass" with done.
- Do not claim WCAG, security, performance, or compliance guarantees from static docs alone.
- Do not invent CI scripts, package scripts, eval harnesses, PR rules, or deployment gates when sources or code do not support them.

## Authoring References Used
These references were used to design this skill. They are not product source files for a project run; product truth still comes only from the Input files and explicit user answers.

- `definition-of-done`: `https://raw.githubusercontent.com/addyosmani/agent-skills/main/references/definition-of-done.md`
  - Used: acceptance criteria vs Definition of Done distinction, standing reusable DoD, correctness/quality/integration/documentation/ship-readiness sections, and red flags against declaring done too early.
  - Not used: one-size-fits-all checklist as final content; project-specific source files still decide what belongs in `docs/dod-evals.md`.
- `quality-run-quality-gates`: `https://github.com/dawiddutoit/custom-claude/blob/main/skills/quality-run-quality-gates/SKILL.md`
  - Used: gate detection mindset, pass/fail reporting, rerun-after-fix loop, and "Definition of Done met/not met" blocking semantics.
  - Not used: command-runner behavior, tool-specific scripts, or executing gates during artifact creation.
- the installed `verification-before-completion` skill available during authoring
  - Used: evidence before claims, identify/run/read/verify gate function, no completion claim without fresh evidence.
  - Not used: runtime execution as the artifact output; this skill writes the reusable DoD/eval contract.
- `breakdown-plan`: `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-plan/SKILL.md`
  - Used: DoD at multiple planning levels, acceptance criteria plus Definition of Done, dependency and gate thinking.
  - Not used: GitHub project automation, issue hierarchy output, sprint/project-management artifacts.
- Hermes eval/lane-gate proposal: `https://github.com/NousResearch/hermes-agent/issues/44000`
  - Used: eval definitions attached to lane/state transitions, standard eval result shape, quality contract over agent self-assessment.
  - Not used: Hermes-specific architecture, cron/memory/CLI implementation proposals.
- Existing local SDD skills in this repository:
  - `skills/to-guardrails/SKILL.md`
  - `skills/to-qa-checklist/SKILL.md`
  - `skills/to-development-plan/SKILL.md`
  - Used: Universal SDD Rule, one-artifact output contract, evidence policy separation, artifact boundaries, severity/release-readiness separation, and Final Report shape.

## Gap-Check
Before writing, verify that sources or code identify:
- product acceptance criteria or success conditions
- architecture/runtime constraints that affect verification
- engineering workflow lanes or completion transitions, when sources define them
- required hard gates such as build, lint, typecheck, tests, security scan, or manual approval
- UX/UI verification expectations
- representative-user task validation expectations for critical flows
- H1-H10 heuristic coverage, evidence, and finding disposition expectations
- PR, merge, branch, commit, or release rules, if relevant
- what evidence counts for completion claims
- whether UI/design evidence is connected to real behavior, state, data, and actions when functionality is claimed
- failure classes and blocker handling
- which checks can be automated now versus later

If verification profile, completion gates, workflow promotion rules, or merge/completion rules are missing, ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise define the smallest credible source-backed verification contract, mark unavailable runtime evidence explicitly, and continue without inventing a human approval.

Ask DoD/eval questions with recommended answers based on sources. Prefer:
- `passed` only when required gates pass with fresh evidence
- `blocked` when an applicable required gate, P0, P1, or a P2 explicitly classified as blocking remains open
- non-blocking P2 and P3 findings remain visible as follow-up work and do not require operator approval or prevent completion
- the canonical product severity meanings: P0 catastrophic severe harm or system-wide unusability; P1 a broken primary journey, core capability, release invariant, or high-impact requirement with no acceptable workaround for a material supported scope; P2 a localized but meaningful defect, regression, requirement gap, or visual/interaction drift while the product remains broadly usable or a reasonable workaround exists; P3 low-impact polish or cosmetic inconsistency without material impact
- every finding records severity, release effect, applicability, source, evidence, and rationale; do not infer release effect from severity alone
- static docs can define intended checks but cannot prove runtime behavior
- manual approval is not a default gate for user-facing transitions; require the single whole-design-baseline approval and only the risk-specific authorizations defined by guardrails for irreversible, destructive, financial, legal, public, privileged, security-sensitive, privacy-sensitive, or external effects

## Workflow
1. Inspect the input files.
2. Inspect codebase verification surfaces when a codebase exists: `package.json`, test directories, CI config, lint/typecheck config, build scripts, Playwright/Vitest/Jest config, and deployment config.
3. Extract acceptance criteria and completion semantics from the PRD and related SDD artifacts.
4. Extract architecture-driven verification needs from `docs/architecture.md`.
5. Separate acceptance criteria, DoD, QA checklist items, and implementation tasks.
6. Define the standing DoD model.
7. Define verification profile tiers: hard gates, unit checks, system checks, UX/UI checks, evidence, static-surface limits, and release/merge checks. For any user-visible frontend scope, include the parameterized `approved_visual_baseline_fidelity` gate and bind it to the current baseline plus concrete QA checks rather than restating the design. Include `heuristic_usability_review` for the applicable H1-H10 scope and bind it to concrete QA heuristic checks. For any applicable critical or consequential user-visible flow, include `representative_user_task_validation` and bind it to concrete QA usability checks rather than restating the task plan.
   When a gate is superseded or declared non-active, remove it from the Gate Matrix and requirement traceability tables or repoint those requirements to the active gate. A gate cannot be simultaneously inactive and load-bearing.
8. Define lane/state promotion gates only when sources define engineering delivery lanes, execution states, or completion transitions. Ordinary product UI states do not create engineering gates.
9. Define eval result format with pass/fail/blocked status, evidence, owner, timestamp/source, and rerun rule.
10. Define failure and blocker classification without duplicating `docs/qa-checklist.md`; heuristic findings are classified through the existing severity/release-effect glossary and do not automatically create approval gates.
11. Before writing the artifact, verify the planned content:
   - Every DoD rule, gate, eval, and evidence requirement traces to a named source file, codebase evidence, or explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
   - The artifact does not invent tests, scripts, CI, PR policy, or implementation scope.
   - Clause-level coverage: split each FR/NFR into its distinct observable obligations and map every applicable obligation to an active gate or an explicit blocker. A requirement ID appearing once is not proof that all its clauses are covered.
12. Create or update only `docs/dod-evals.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Definition Of Done Model`, `Verification Profile`, `Gate Matrix`, `Evidence Requirements`, `Failure And Blocker Classification`, `PR Merge And Completion Rules`, `Out Of Scope`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# DoD And Evals

## Source References

## Definition Of Done Model

## Acceptance Criteria Vs Definition Of Done

## Global Definition Of Done

## Feature Unit Definition Of Done

## Verification Profile

### Hard Gates

### Unit Checks

### System Checks

### UX/UI Checks

### Release Checks

## Gate Matrix

## Lane Or State Promotion Gates

## Eval Result Format

## Evidence Requirements

## Evidence Limits

## Failure And Blocker Classification

## Rerun And Recovery Rules

## PR Merge And Completion Rules

## Out Of Scope

## Open Questions
```

For every gate or eval include:
- `Gate`
- `Purpose`
- `Source References`
- `Applies To`
- `Required Evidence`
- `Pass Condition`
- `Fail Or Block Condition`
- `Rerun Rule`
- `Automation Status`: `automated`, `manual`, `not available yet — pending <named condition>`, or `open question`. A named pending condition must be re-evaluated against the current repository observation on every invocation.

For `approved_visual_baseline_fidelity` additionally include:
- `Baseline ID`
- `Immutable Target Hash`
- `Affected Routes States And Viewports`
- `Permitted Variance And Operator Overrides`
- `QA Check IDs`
- `VisualQAEvidence References`
- `PrototypePromotionReceipt`, when prototype code was reused

For `representative_user_task_validation` additionally include:
- `JOB-*` and `UC-*` references
- `Representative User Group`
- `Task And Success Criterion`
- `Device Or Viewport`
- `Validation Evidence References`
- `Findings And Disposition`
- `Applicability Decision`
- `Validation Result: passed | blocked | deferred | not applicable`

For `heuristic_usability_review` additionally include:
- `Heuristic Coverage: H1-H10 with each item covered | deferred | not applicable`
- `Primary Journey And JOB/UC References`
- `Representative Screens States Routes And Viewports`
- `Desktop And Mobile Coverage`
- `Error And Recovery Coverage`
- `Accessibility-Critical Actions`
- `QA Check IDs And Evidence References`
- `Findings And Recommendations`
- `Applicability Decisions`
- `Review Result: passed | blocked | deferred | not applicable`

For every finding classification include:
- `Severity: P0 | P1 | P2 | P3`
- `Release Effect: blocking | advisory`
- `Applicability`
- `Source`
- `Evidence`
- `Rationale`

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed DoD And Eval Rules`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
